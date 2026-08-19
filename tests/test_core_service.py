from __future__ import annotations

import tempfile
import threading
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from anirss.core.database import SQLiteRepository
from anirss.core.downloaders import (
    DownloadCancelled,
    DownloadControl,
    DownloaderRouter,
    DownloadResult,
)
from anirss.core.models import (
    AppSettings,
    DownloadKind,
    DownloadStatus,
    DownloadTask,
    FeedItem,
    ServiceEvent,
    ServiceEventType,
)
from anirss.core.service import AniRSSService, ServiceStopping

RSS = b"""<rss version="2.0"><channel>
  <item><title>Example - 01 [1080p]</title><guid>one</guid>
    <enclosure url="https://cdn.example/one.mkv" /></item>
  <item><title>Example - 02 [1080p]</title><guid>two</guid>
    <enclosure url="https://cdn.example/two.mkv" /></item>
</channel></rss>"""


class _BlockingDownloader:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.cancelled = threading.Event()

    def download(
        self,
        _task: DownloadTask,
        _settings: AppSettings,
        control: DownloadControl,
        _progress_callback: Callable[[int, int | None, float], None] | None = None,
    ) -> DownloadResult:
        self.started.set()
        try:
            while True:
                control.checkpoint(0.01)
        except DownloadCancelled:
            self.cancelled.set()
            raise


class _SlowCancelDownloader:
    """Hold the first cancelled worker open to exercise immediate retry."""

    def __init__(self) -> None:
        self.first_started = threading.Event()
        self.cancel_observed = threading.Event()
        self.release_first = threading.Event()
        self.second_started = threading.Event()
        self._attempt_lock = threading.Lock()
        self._attempts = 0

    def download(
        self,
        _task: DownloadTask,
        _settings: AppSettings,
        control: DownloadControl,
        _progress_callback: Callable[[int, int | None, float], None] | None = None,
    ) -> DownloadResult:
        with self._attempt_lock:
            self._attempts += 1
            attempt = self._attempts
        if attempt == 1:
            self.first_started.set()
        else:
            self.second_started.set()
        try:
            while True:
                control.checkpoint(0.01)
        except DownloadCancelled:
            if attempt == 1:
                self.cancel_observed.set()
                if not self.release_first.wait(2):
                    raise TimeoutError("test did not release cancelled worker") from None
            raise


class _SequencedBlockingDownloader:
    def __init__(self) -> None:
        self.first_started = threading.Event()
        self.second_started = threading.Event()
        self._lock = threading.Lock()
        self._starts = 0

    def download(
        self,
        _task: DownloadTask,
        _settings: AppSettings,
        control: DownloadControl,
        _progress_callback: Callable[[int, int | None, float], None] | None = None,
    ) -> DownloadResult:
        with self._lock:
            self._starts += 1
            starts = self._starts
        (self.first_started if starts == 1 else self.second_started).set()
        while True:
            control.checkpoint(0.01)


class _AutostartRecorder:
    def __init__(self) -> None:
        self.command: list[str] | None = None

    def is_configured(self, command: list[str]) -> bool:
        return self.command == command

    def set_enabled(self, enabled: bool, command: list[str]) -> bool:
        self.command = list(command) if enabled else None
        return enabled


class ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        repository = SQLiteRepository(Path(self.temporary.name) / "service.db")
        self.service = AniRSSService(
            repository=repository,
            feed_fetcher=lambda _url, _settings: RSS,
        )
        self.service.save_settings(
            AppSettings(download_root=str(Path(self.temporary.name) / "downloads"))
        )

    def tearDown(self) -> None:
        self.service.stop()
        self.service.repository.close()
        self.temporary.cleanup()

    def test_refresh_creates_tasks_once(self) -> None:
        subscription = self.service.save_subscription(
            {
                "name": "Example",
                "feed_url": "https://example.test/rss",
                "download_existing": True,
            }
        )
        assert subscription.id is not None
        first = self.service.refresh_subscription(subscription.id)
        second = self.service.refresh_subscription(subscription.id)
        self.assertEqual(len(first), 2)
        self.assertEqual(second, [])
        self.assertEqual(len(self.service.list_tasks()), 2)
        self.assertTrue(Path(first[0].destination_directory).is_dir())

    def test_first_refresh_is_a_safe_baseline_by_default(self) -> None:
        subscription = self.service.save_subscription(
            {"name": "Baseline", "feed_url": "https://example.test/baseline"}
        )
        assert subscription.id is not None
        self.assertEqual(self.service.refresh_subscription(subscription.id), [])
        updated_feed = RSS.replace(
            b"</channel>",
            b"<item><title>Example - 03 [1080p]</title><guid>three</guid>"
            b"<enclosure url='https://cdn.example/three.mkv' /></item></channel>",
        )
        self.service._feed_fetcher = lambda _url, _settings: updated_feed
        created = self.service.refresh_subscription(subscription.id)
        self.assertEqual(len(created), 1)
        self.assertIn("03", created[0].title)

    def test_manual_download_queues_one_baseline_item_and_is_idempotent(self) -> None:
        subscription = self.service.save_subscription(
            {
                "name": "Manual baseline",
                "feed_url": "https://example.test/manual-baseline",
                "auto_download": False,
                "include_pattern": "will never match",
            }
        )
        assert subscription.id is not None
        self.assertEqual(self.service.refresh_subscription(subscription.id), [])
        items = self.service.list_feed_items(subscription.id)
        self.assertEqual(len(items), 2)
        assert items[0].id is not None
        before = self.service.repository.get_subscription(subscription.id)
        events: list[ServiceEvent] = []
        self.service.subscribe(ServiceEventType.TASK_ADDED, events.append)

        first = self.service.download_feed_item(subscription.id, items[0].id)
        second = self.service.download_feed_item(subscription.id, items[0].id)

        self.assertEqual(first.id, second.id)
        self.assertEqual(first.status, DownloadStatus.QUEUED)
        self.assertEqual(len(self.service.list_tasks()), 1)
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].payload.get("manual"))
        self.assertTrue(Path(first.destination_directory).is_dir())
        after = self.service.repository.get_subscription(subscription.id)
        assert before is not None and after is not None
        self.assertEqual(after.last_checked_at, before.last_checked_at)
        self.assertFalse(after.download_enabled)

    def test_concurrent_manual_download_clicks_create_one_task(self) -> None:
        subscription = self.service.save_subscription(
            {"name": "Double click", "feed_url": "https://example.test/double-click"}
        )
        assert subscription.id is not None
        self.service.refresh_subscription(subscription.id)
        item = self.service.list_feed_items(subscription.id)[0]
        assert item.id is not None
        barrier = threading.Barrier(6)
        tasks: list[DownloadTask] = []
        errors: list[BaseException] = []
        events: list[ServiceEvent] = []
        self.service.subscribe(ServiceEventType.TASK_ADDED, events.append)

        def queue() -> None:
            try:
                barrier.wait(2)
                tasks.append(self.service.download_feed_item(subscription.id or 0, item.id or 0))
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=queue) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(3)

        self.assertEqual(errors, [])
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(len({task.id for task in tasks}), 1)
        self.assertEqual(len(self.service.list_tasks()), 1)
        self.assertEqual(len(events), 1)

    def test_manual_download_validates_ownership_url_kind_and_retry(self) -> None:
        first = self.service.save_subscription(
            {"name": "Manual one", "feed_url": "https://example.test/manual-one"}
        )
        second = self.service.save_subscription(
            {"name": "Manual two", "feed_url": "https://example.test/manual-two"}
        )
        assert first.id is not None and second.id is not None
        no_url, _ = self.service.repository.add_feed_item(
            FeedItem(subscription_id=first.id, guid="no-url", title="No download")
        )
        torrent, _ = self.service.repository.add_feed_item(
            FeedItem(
                subscription_id=first.id,
                guid="dynamic-torrent",
                title="Dynamic torrent",
                download_url="https://example.test/download?id=42",
                content_type="application/x-bittorrent",
            )
        )
        assert no_url.id is not None and torrent.id is not None

        with self.assertRaises(KeyError):
            self.service.download_feed_item(second.id, torrent.id)
        with self.assertRaisesRegex(ValueError, "downloadable URL"):
            self.service.download_feed_item(first.id, no_url.id)
        self.assertEqual(self.service.list_tasks(), [])

        task = self.service.download_feed_item(first.id, torrent.id)
        self.assertEqual(task.kind, DownloadKind.TORRENT)
        assert task.id is not None
        failed = self.service.repository.update_download_task(
            task.id,
            status=DownloadStatus.FAILED,
            error="temporary failure",
        )
        self.assertEqual(failed.status, DownloadStatus.FAILED)
        retried = self.service.download_feed_item(first.id, torrent.id)
        self.assertEqual(retried.id, task.id)
        self.assertEqual(retried.status, DownloadStatus.QUEUED)
        self.assertIsNone(retried.error)
        self.assertEqual(len(self.service.list_tasks()), 1)

    def test_manual_download_is_rejected_after_service_stop(self) -> None:
        subscription = self.service.save_subscription(
            {"name": "Stopped", "feed_url": "https://example.test/stopped"}
        )
        assert subscription.id is not None
        item, _ = self.service.repository.add_feed_item(
            FeedItem(
                subscription_id=subscription.id,
                guid="stopped-item",
                title="Stopped item",
                download_url="https://example.test/stopped.mkv",
            )
        )
        assert item.id is not None
        self.service.stop()
        with self.assertRaises(ServiceStopping):
            self.service.download_feed_item(subscription.id, item.id)
        self.assertEqual(self.service.list_tasks(), [])

    def test_immediate_manual_retry_survives_cancelled_worker_exit(self) -> None:
        downloader = _SlowCancelDownloader()
        self.service._downloaders = DownloaderRouter(http=downloader, torrent=downloader)
        subscription = self.service.save_subscription(
            {
                "name": "Immediate retry",
                "feed_url": "https://example.test/immediate-retry",
                "enabled": False,
            }
        )
        assert subscription.id is not None
        item, _ = self.service.repository.add_feed_item(
            FeedItem(
                subscription_id=subscription.id,
                guid="immediate-retry-item",
                title="Immediate retry item",
                download_url="https://example.test/immediate-retry.mkv",
            )
        )
        assert item.id is not None
        self.service.start()

        first = self.service.download_feed_item(subscription.id, item.id)
        assert first.id is not None
        self.assertTrue(downloader.first_started.wait(2))
        self.assertEqual(
            self.service.cancel_task(first.id).status,
            DownloadStatus.CANCELLED,
        )
        self.assertTrue(downloader.cancel_observed.wait(2))

        retried = self.service.download_feed_item(subscription.id, item.id)
        self.assertEqual(retried.id, first.id)
        self.assertEqual(retried.status, DownloadStatus.QUEUED)
        downloader.release_first.set()

        self.assertTrue(downloader.second_started.wait(2))
        current = self.service.get_task(first.id)
        assert current is not None
        self.assertEqual(current.status, DownloadStatus.DOWNLOADING)

    def test_pausing_active_task_releases_executor_slot(self) -> None:
        downloader = _SequencedBlockingDownloader()
        self.service._downloaders = DownloaderRouter(http=downloader, torrent=downloader)
        self.service.save_settings(
            AppSettings(
                download_root=str(Path(self.temporary.name) / "downloads"),
                max_concurrent_downloads=1,
            )
        )
        subscription = self.service.save_subscription(
            {
                "name": "Pause queue",
                "feed_url": "https://example.test/pause-queue",
                "enabled": False,
            }
        )
        assert subscription.id is not None
        items: list[FeedItem] = []
        for index in (1, 2):
            item, _ = self.service.repository.add_feed_item(
                FeedItem(
                    subscription_id=subscription.id,
                    guid=f"pause-{index}",
                    title=f"Pause {index}",
                    download_url=f"https://example.test/pause-{index}.mkv",
                )
            )
            items.append(item)
        self.service.start()
        assert items[0].id is not None
        assert items[1].id is not None
        first = self.service.download_feed_item(subscription.id, items[0].id)
        self.service.download_feed_item(subscription.id, items[1].id)
        assert first.id is not None
        self.assertTrue(downloader.first_started.wait(2))

        paused = self.service.pause_task(first.id)

        self.assertEqual(paused.status, DownloadStatus.PAUSED)
        self.assertTrue(downloader.second_started.wait(2))

    def test_start_repairs_missing_autostart_entry(self) -> None:
        self.service.stop()
        recorder = _AutostartRecorder()
        self.service._autostart = cast(Any, recorder)
        self.service.repository.save_settings(
            AppSettings(
                download_root=str(Path(self.temporary.name) / "downloads"),
                autostart=True,
            )
        )

        self.service.start()

        self.assertIsNotNone(recorder.command)
        assert recorder.command is not None
        self.assertTrue(Path(recorder.command[0]).is_absolute())

    def test_baseline_records_filtered_items_before_rules_are_loosened(self) -> None:
        subscription = self.service.save_subscription(
            {
                "name": "Filtered baseline",
                "feed_url": "https://example.test/filtered",
                "include_pattern": "Never matches",
            }
        )
        assert subscription.id is not None

        self.assertEqual(self.service.refresh_subscription(subscription.id), [])
        self.assertEqual(
            len(self.service.repository.list_feed_items(subscription.id)),
            2,
        )

        updated = self.service.save_subscription(
            {
                "id": subscription.id,
                "name": subscription.name,
                "feed_url": subscription.feed_url,
                "include_pattern": "",
                "download_existing": True,
            }
        )
        assert updated.id is not None
        self.assertEqual(self.service.refresh_subscription(updated.id), [])
        self.assertEqual(self.service.list_tasks(), [])

        newer_feed = RSS.replace(
            b"</channel>",
            b"<item><title>Example - 03 [1080p]</title><guid>three</guid>"
            b"<enclosure url='https://cdn.example/three.mkv' /></item></channel>",
        )
        self.service._feed_fetcher = lambda _url, _settings: newer_feed
        created = self.service.refresh_subscription(updated.id)
        self.assertEqual(len(created), 1)
        self.assertIn("03", created[0].title)

    def test_failed_first_refresh_does_not_destroy_safe_baseline(self) -> None:
        subscription = self.service.save_subscription(
            {"name": "Retry baseline", "feed_url": "https://example.test/retry"}
        )
        assert subscription.id is not None
        attempts = 0

        def fail_once(_url: str, _settings: AppSettings) -> bytes:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise OSError("temporary network failure")
            return RSS

        self.service._feed_fetcher = fail_once
        with self.assertRaises(OSError):
            self.service.refresh_subscription(subscription.id)
        stored = self.service.repository.get_subscription(subscription.id)
        assert stored is not None
        self.assertIsNone(stored.last_checked_at)
        self.assertEqual(self.service.refresh_subscription(subscription.id), [])
        self.assertEqual(self.service.list_tasks(), [])

    def test_partial_first_refresh_recovery_keeps_the_safe_baseline(self) -> None:
        subscription = self.service.save_subscription(
            {"name": "Interrupted baseline", "feed_url": "https://example.test/interrupted"}
        )
        assert subscription.id is not None
        self.service.repository.add_feed_item(
            FeedItem(
                subscription_id=subscription.id,
                guid="one",
                title="Example - 01 [1080p]",
                download_url="https://cdn.example/one.mkv",
            )
        )

        self.assertIsNone(subscription.last_checked_at)
        self.assertEqual(self.service.refresh_subscription(subscription.id), [])
        self.assertEqual(self.service.list_tasks(), [])
        self.assertEqual(
            len(self.service.repository.list_feed_items(subscription.id)),
            2,
        )

    def test_task_creation_failure_rolls_back_seen_item_for_retry(self) -> None:
        subscription = self.service.save_subscription(
            {
                "name": "Atomic queue",
                "feed_url": "https://example.test/atomic",
                "download_existing": True,
            }
        )
        assert subscription.id is not None
        original_task_values = self.service.repository._task_values
        with (
            patch.object(
                self.service.repository,
                "_task_values",
                side_effect=OSError("temporary database failure"),
            ),
            self.assertRaises(OSError),
        ):
            self.service.refresh_subscription(subscription.id)
        self.assertEqual(self.service.repository.list_feed_items(subscription.id), [])
        self.assertEqual(self.service.list_tasks(), [])

        with patch.object(
            self.service.repository,
            "_task_values",
            wraps=original_task_values,
        ):
            created = self.service.refresh_subscription(subscription.id)
        self.assertEqual(len(created), 2)
        self.assertEqual(len(self.service.list_tasks()), 2)

    def test_changing_feed_url_resets_history_and_builds_new_baseline(self) -> None:
        subscription = self.service.save_subscription(
            {
                "name": "Changed source",
                "feed_url": "https://example.test/old.xml",
                "download_existing": True,
            }
        )
        assert subscription.id is not None
        self.assertEqual(len(self.service.refresh_subscription(subscription.id)), 2)
        changed = self.service.save_subscription(
            {
                "id": subscription.id,
                "name": subscription.name,
                "feed_url": "https://example.test/new.xml",
                "download_existing": False,
            }
        )
        self.assertIsNone(changed.last_checked_at)
        self.assertEqual(self.service.list_tasks(), [])
        assert changed.id is not None
        self.assertEqual(self.service.refresh_subscription(changed.id), [])
        self.assertEqual(self.service.list_tasks(), [])

    def test_delete_waits_for_refresh_and_cancels_its_new_worker(self) -> None:
        downloader = _BlockingDownloader()
        self.service._downloaders = DownloaderRouter(http=downloader, torrent=downloader)
        feed_started = threading.Event()
        release_feed = threading.Event()

        def fetch(_url: str, _settings: AppSettings) -> bytes:
            feed_started.set()
            if not release_feed.wait(2):
                raise TimeoutError("test did not release the feed")
            return RSS

        self.service._feed_fetcher = fetch
        subscription = self.service.save_subscription(
            {
                "name": "Delete race",
                "feed_url": "https://example.test/delete-race",
                "enabled": False,
                "download_existing": True,
            }
        )
        assert subscription.id is not None
        self.service.start()

        thread_errors: list[BaseException] = []
        delete_results: list[bool] = []
        delete_done = threading.Event()
        original_save = self.service.repository.save_subscription

        def save_after_worker_started(value):
            if value.last_checked_at is not None and not downloader.started.wait(2):
                raise TimeoutError("download worker did not start")
            return original_save(value)

        def refresh() -> None:
            try:
                self.service.refresh_subscription(subscription.id or 0)
            except BaseException as exc:
                thread_errors.append(exc)

        def delete() -> None:
            try:
                delete_results.append(self.service.delete_subscription(subscription.id or 0))
            except BaseException as exc:
                thread_errors.append(exc)
            finally:
                delete_done.set()

        with patch.object(
            self.service.repository,
            "save_subscription",
            side_effect=save_after_worker_started,
        ):
            refresh_thread = threading.Thread(target=refresh)
            refresh_thread.start()
            self.assertTrue(feed_started.wait(1))
            delete_thread = threading.Thread(target=delete)
            delete_thread.start()
            self.assertFalse(delete_done.wait(0.05))
            release_feed.set()
            refresh_thread.join(3)
            delete_thread.join(3)

        self.assertFalse(refresh_thread.is_alive())
        self.assertFalse(delete_thread.is_alive())
        self.assertEqual(thread_errors, [])
        self.assertEqual(delete_results, [True])
        self.assertTrue(downloader.cancelled.wait(2))
        self.assertEqual(self.service.list_subscriptions(), [])
        self.assertEqual(self.service.list_tasks(), [])

    def test_delete_waits_for_manual_queue_and_cancels_its_worker(self) -> None:
        downloader = _BlockingDownloader()
        self.service._downloaders = DownloaderRouter(http=downloader, torrent=downloader)
        subscription = self.service.save_subscription(
            {
                "name": "Delete manual race",
                "feed_url": "https://example.test/delete-manual-race",
                "enabled": False,
            }
        )
        assert subscription.id is not None
        item, _ = self.service.repository.add_feed_item(
            FeedItem(
                subscription_id=subscription.id,
                guid="manual-race-item",
                title="Manual race item",
                download_url="https://example.test/manual-race.mkv",
            )
        )
        assert item.id is not None
        queue_entered = threading.Event()
        release_queue = threading.Event()
        delete_done = threading.Event()
        errors: list[BaseException] = []
        delete_results: list[bool] = []
        original_add = self.service.repository.add_download_task

        def blocking_add(task: DownloadTask) -> tuple[DownloadTask, bool]:
            queue_entered.set()
            if not release_queue.wait(2):
                raise TimeoutError("test did not release manual queue")
            return original_add(task)

        def queue() -> None:
            try:
                self.service.download_feed_item(subscription.id or 0, item.id or 0)
            except BaseException as exc:
                errors.append(exc)

        def delete() -> None:
            try:
                delete_results.append(self.service.delete_subscription(subscription.id or 0))
            except BaseException as exc:
                errors.append(exc)
            finally:
                delete_done.set()

        self.service.start()
        with patch.object(
            self.service.repository,
            "add_download_task",
            side_effect=blocking_add,
        ):
            queue_thread = threading.Thread(target=queue)
            queue_thread.start()
            self.assertTrue(queue_entered.wait(1))
            delete_thread = threading.Thread(target=delete)
            delete_thread.start()
            self.assertFalse(delete_done.wait(0.05))
            release_queue.set()
            queue_thread.join(3)
            delete_thread.join(3)

        self.assertFalse(queue_thread.is_alive())
        self.assertFalse(delete_thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(delete_results, [True])
        self.assertTrue(downloader.cancelled.wait(2))
        self.assertEqual(self.service.list_subscriptions(), [])
        self.assertEqual(self.service.list_tasks(), [])

    def test_queued_stale_refresh_reloads_subscription_after_feed_change(self) -> None:
        old_url = "https://example.test/old-stale.xml"
        new_url = "https://example.test/new-current.xml"
        old_feed = b"""<rss><channel><item><guid>old</guid><title>Old 01</title>
            <enclosure url="https://cdn.example/old.mkv" /></item></channel></rss>"""
        new_feed = b"""<rss><channel><item><guid>new</guid><title>New 01</title>
            <enclosure url="https://cdn.example/new.mkv" /></item></channel></rss>"""
        fetched_urls: list[str] = []

        def fetch(url: str, _settings: AppSettings) -> bytes:
            fetched_urls.append(url)
            return old_feed if url == old_url else new_feed

        self.service._feed_fetcher = fetch
        stale = self.service.save_subscription(
            {"name": "Changed while queued", "feed_url": old_url}
        )
        assert stale.id is not None
        changed = self.service.save_subscription(
            {
                "id": stale.id,
                "name": stale.name,
                "feed_url": new_url,
                "download_existing": False,
            }
        )
        assert changed.id is not None

        self.assertEqual(self.service._refresh_subscription(stale), [])
        self.assertEqual(fetched_urls, [new_url])
        stored_items = self.service.repository.list_feed_items(changed.id)
        self.assertEqual([item.guid for item in stored_items], ["new"])
        self.assertEqual(self.service.refresh_subscription(changed.id), [])
        self.assertEqual(self.service.list_tasks(), [])

    def test_duplicate_names_get_independent_directories(self) -> None:
        first = self.service.save_subscription(
            {"name": "Same", "feed_url": "https://example.test/one.xml"}
        )
        second = self.service.save_subscription(
            {"name": "Same", "feed_url": "https://example.test/two.xml"}
        )
        self.assertNotEqual(
            first.directory_name or first.name,
            second.directory_name or second.name,
        )

    def test_explicit_shared_directory_reserves_filenames_globally(self) -> None:
        shared = str(Path(self.temporary.name).resolve() / "shared")
        first = self.service.save_subscription(
            {
                "name": "First",
                "feed_url": "https://example.test/first.xml",
                "save_path": shared,
                "download_existing": True,
            }
        )
        second = self.service.save_subscription(
            {
                "name": "Second",
                "feed_url": "https://example.test/second.xml",
                "save_path": shared,
                "download_existing": True,
            }
        )
        assert first.id is not None
        assert second.id is not None
        self.service.refresh_subscription(first.id)
        self.service.refresh_subscription(second.id)
        tasks = self.service.list_tasks()
        self.assertEqual(len(tasks), 4)
        self.assertEqual(len({task.filename.casefold() for task in tasks}), 4)

    def test_invalid_filter_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.service.save_subscription(
                {
                    "name": "Broken",
                    "feed_url": "https://example.test/rss",
                    "include_pattern": "[",
                }
            )

    def test_ui_aliases_and_keyword_lists(self) -> None:
        explicit = str(Path(self.temporary.name).resolve() / "chosen" / "Show")
        subscription = self.service.save_subscription(
            {
                "name": "Aliased",
                "rss_url": "https://example.test/aliases.xml",
                "save_path": explicit,
                "auto_download": False,
                "episode_regex": r"-(\d+)",
                "include_keywords": ["1080p", "CHS"],
                "exclude_keywords": ["合集", "繁体"],
            }
        )
        self.assertEqual(subscription.feed_url, "https://example.test/aliases.xml")
        self.assertEqual(subscription.save_directory, explicit)
        self.assertFalse(subscription.download_enabled)
        self.assertTrue(repr(subscription.include_pattern).find("1080p") >= 0)
        self.assertTrue(Path(explicit).is_dir())

    def test_relative_explicit_save_directory_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.service.save_subscription(
                {
                    "name": "Relative",
                    "rss_url": "https://example.test/relative.xml",
                    "save_path": "../outside",
                }
            )

    def test_remove_http_task_deletes_only_exact_files(self) -> None:
        subscription = self.service.save_subscription(
            {"name": "Removal", "rss_url": "https://example.test/removal.xml"}
        )
        assert subscription.id is not None
        item, _ = self.service.repository.add_feed_item(
            FeedItem(
                subscription_id=subscription.id,
                guid="remove-one",
                title="Remove one",
                download_url="https://example.test/remove-one.mkv",
            )
        )
        assert item.id is not None
        directory = Path(self.temporary.name) / "remove-output"
        directory.mkdir()
        target = directory / "remove-one.mkv"
        partial = directory / "remove-one.mkv.part"
        unrelated = directory / "keep-me.mkv"
        target.write_bytes(b"done")
        partial.write_bytes(b"partial")
        unrelated.write_bytes(b"keep")
        task, _ = self.service.repository.add_download_task(
            DownloadTask(
                subscription_id=subscription.id,
                feed_item_id=item.id,
                title=item.title,
                source_url=item.download_url or "",
                destination_directory=str(directory),
                filename=target.name,
            )
        )
        assert task.id is not None
        self.assertTrue(self.service.remove_task(task.id, delete_files=True))
        self.assertFalse(target.exists())
        self.assertFalse(partial.exists())
        self.assertTrue(unrelated.exists())

    def test_remove_bt_task_refuses_automatic_file_deletion(self) -> None:
        subscription = self.service.save_subscription(
            {"name": "BT", "rss_url": "https://example.test/bt.xml"}
        )
        assert subscription.id is not None
        item, _ = self.service.repository.add_feed_item(
            FeedItem(
                subscription_id=subscription.id,
                guid="bt-one",
                title="BT one",
                download_url="magnet:?xt=urn:btih:abc",
            )
        )
        assert item.id is not None
        task, _ = self.service.repository.add_download_task(
            DownloadTask(
                subscription_id=subscription.id,
                feed_item_id=item.id,
                title=item.title,
                source_url=item.download_url or "",
                destination_directory=self.temporary.name,
                filename="BT one",
                kind=DownloadKind.MAGNET,
            )
        )
        assert task.id is not None
        with self.assertRaisesRegex(ValueError, "cannot safely enumerate"):
            self.service.remove_task(task.id, delete_files=True)
        self.assertIsNotNone(self.service.get_task(task.id))


if __name__ == "__main__":
    unittest.main()
