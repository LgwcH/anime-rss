"""High-level synchronous API for UI and headless AniRSS frontends."""

from __future__ import annotations

import os
import re
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor, TimeoutError
from contextlib import suppress
from dataclasses import asdict, replace
from functools import partial
from pathlib import Path
from typing import Any

from .autostart import AutostartManager, default_launch_command
from .database import SQLiteRepository
from .downloaders import (
    DownloadCancelled,
    DownloadControl,
    DownloaderRouter,
    LibtorrentDownloader,
    classify_download,
)
from .feeds import fetch_feed, parse_feed
from .models import (
    AppSettings,
    DownloadKind,
    DownloadStatus,
    DownloadTask,
    FeedItem,
    ServiceEvent,
    ServiceEventType,
    Subscription,
    SubscriptionFolder,
    utc_now,
)
from .naming import (
    NamingPolicy,
    ensure_within_root,
    recognize_episode,
    safe_download_path,
    sanitize_component,
)
from .scheduler import SubscriptionScheduler

EventCallback = Callable[[ServiceEvent], None]
FeedFetcher = Callable[[str, AppSettings], bytes]


class ServiceStopping(RuntimeError):
    """Raised internally when a refresh is interrupted by application exit."""


class RefreshBatchError(RuntimeError):
    """Report one or more failed feeds after the remaining feeds were checked."""

    def __init__(self, failures: list[tuple[str, Exception]]) -> None:
        self.failures = failures
        names = "、".join(name for name, _error in failures[:3])
        suffix = "等" if len(failures) > 3 else ""
        super().__init__(f"{len(failures)} 个订阅刷新失败：{names}{suffix}")


def default_data_directory() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base / "AniRSS"


class AniRSSService:
    """Coordinate subscriptions, polling, de-duplication, and downloads.

    Public methods are synchronous and safe to call from a desktop bridge.
    Events may originate from worker threads, so a Qt frontend should relay
    them through a signal before updating widgets.
    """

    def __init__(
        self,
        database_path: str | Path | None = None,
        *,
        repository: SQLiteRepository | None = None,
        feed_fetcher: FeedFetcher | None = None,
        downloader_router: DownloaderRouter | None = None,
        autostart_manager: AutostartManager | None = None,
    ) -> None:
        if repository is not None and database_path is not None:
            raise ValueError("pass either database_path or repository, not both")
        self.repository = repository or SQLiteRepository(
            database_path or default_data_directory() / "anirss.db"
        )
        self._owns_repository = repository is None
        self._feed_fetcher = feed_fetcher or fetch_feed
        if downloader_router is not None:
            self._downloaders = downloader_router
        else:
            state_path: Path | None = None
            if self.repository.database_path != ":memory:":
                state_path = (
                    Path(self.repository.database_path).expanduser().resolve().parent
                    / "libtorrent.state"
                )
            self._downloaders = DownloaderRouter(
                torrent=LibtorrentDownloader(state_path=state_path)
            )
        self._autostart = autostart_manager or AutostartManager()
        self._callbacks: dict[str, list[EventCallback]] = {}
        self._callback_lock = threading.RLock()
        self._state_lock = threading.RLock()
        self._shutdown_event = threading.Event()
        self._refresh_locks: dict[int, threading.Lock] = {}
        self._filename_lock = threading.Lock()
        self._controls: dict[int, DownloadControl] = {}
        self._futures: dict[int, Future[None]] = {}
        self._executor: ThreadPoolExecutor | None = None
        self._running = False
        self._stopping = False
        self._scheduler = SubscriptionScheduler(
            self.repository,
            self.get_settings,
            self._refresh_from_scheduler,
            self._scheduler_error,
        )

    @property
    def running(self) -> bool:
        with self._state_lock:
            return self._running

    # Lifecycle ---------------------------------------------------------
    def start(self) -> None:
        settings = self.get_settings()
        if settings.autostart:
            command = default_launch_command(minimized=settings.launch_minimized)
            try:
                is_configured = getattr(self._autostart, "is_configured", None)
                if not callable(is_configured) or not is_configured(command):
                    self._autostart.set_enabled(True, command)
            except Exception as exc:
                self._emit(
                    ServiceEvent(
                        ServiceEventType.ERROR,
                        f"Could not repair the user autostart entry: {exc}",
                    )
                )
        with self._state_lock:
            if self._running:
                return
            self._stopping = False
            self._shutdown_event.clear()
            self.repository.requeue_interrupted_tasks()
            self._executor = ThreadPoolExecutor(
                max_workers=self.get_settings().max_concurrent_downloads,
                thread_name_prefix="AniRSS download",
            )
            self._running = True
            queued = self.repository.list_download_tasks(statuses=[DownloadStatus.QUEUED])
            for task in reversed(queued):
                self._submit_task_locked(task)
        self._scheduler.start()

    def stop(self, *, wait: bool = True) -> None:
        """Stop polling/downloads; interrupted tasks remain resumable."""

        self._shutdown_event.set()
        scheduler_stopped = self._scheduler.stop(
            timeout=self.get_settings().request_timeout_seconds + 5
        )
        with self._state_lock:
            if not self._running and self._executor is None:
                if not scheduler_stopped:
                    raise RuntimeError(
                        "subscription scheduler did not stop in time; the database was kept open"
                    )
                return
            self._stopping = True
            self._running = False
            controls = list(self._controls.values())
            futures = list(self._futures.values())
            executor = self._executor
            self._executor = None
        for control in controls:
            control.cancel()
        for future in futures:
            future.cancel()
        if executor:
            executor.shutdown(wait=wait, cancel_futures=True)
        # Workers normally perform this transition themselves.  This also
        # covers a process shutdown while a queued state update was pending.
        self.repository.requeue_interrupted_tasks()
        with self._state_lock:
            self._controls.clear()
            self._futures.clear()
            self._stopping = False
        if not scheduler_stopped:
            raise RuntimeError(
                "subscription scheduler did not stop in time; the database was kept open"
            )

    def close(self) -> None:
        self.stop()
        try:
            self._downloaders.close()
        finally:
            if self._owns_repository:
                self.repository.close()

    def __enter__(self) -> AniRSSService:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # Events ------------------------------------------------------------
    def subscribe(
        self, event: ServiceEventType | str, callback: EventCallback
    ) -> Callable[[], None]:
        """Subscribe to an event type (or ``"*"``) and return an unsubscribe."""

        key = event.value if isinstance(event, ServiceEventType) else str(event)
        with self._callback_lock:
            self._callbacks.setdefault(key, []).append(callback)

        def unsubscribe() -> None:
            with self._callback_lock:
                callbacks = self._callbacks.get(key, [])
                if callback in callbacks:
                    callbacks.remove(callback)

        return unsubscribe

    def set_event_callback(self, callback: EventCallback | None) -> None:
        with self._callback_lock:
            self._callbacks["*"] = [callback] if callback else []

    def _emit(self, event: ServiceEvent) -> None:
        with self._callback_lock:
            callbacks = list(self._callbacks.get(event.type.value, ()))
            callbacks.extend(self._callbacks.get("*", ()))
        for callback in callbacks:
            try:
                callback(event)
            except Exception:
                # Observers must never terminate scheduler/download workers.
                continue

    # Subscription API --------------------------------------------------
    def list_subscriptions(self) -> list[Subscription]:
        return self.repository.list_subscriptions()

    def list_subscription_folders(self) -> list[SubscriptionFolder]:
        return self.repository.list_subscription_folders()

    def save_subscription_folder(
        self, data: SubscriptionFolder | Mapping[str, Any]
    ) -> SubscriptionFolder:
        if isinstance(data, SubscriptionFolder):
            folder = data
        else:
            values = dict(data)
            folder_id = values.get("id")
            existing = None
            if folder_id is not None and folder_id != "":
                existing = self.repository.get_subscription_folder(int(folder_id))
            if existing is not None:
                merged = asdict(existing)
                merged.update(
                    {key: values[key] for key in ("name", "download_directory") if key in values}
                )
                folder = SubscriptionFolder(**merged)
            else:
                folder = SubscriptionFolder(
                    name=str(values.get("name") or ""),
                    download_directory=str(values.get("download_directory") or ""),
                )
        directory = Path(folder.download_directory).expanduser()
        if not directory.is_absolute():
            raise ValueError("subscription folder download directory must be absolute")
        directory.mkdir(parents=True, exist_ok=True)
        saved = self.repository.save_subscription_folder(
            replace(folder, download_directory=str(directory.resolve()))
        )
        self._emit(
            ServiceEvent(
                ServiceEventType.SUBSCRIPTION_FOLDER_SAVED,
                f"Saved subscription folder {saved.name}",
                payload={"folder_id": saved.id},
            )
        )
        return saved

    def delete_subscription_folder(self, folder_id: int) -> bool:
        deleted = self.repository.delete_subscription_folder(folder_id)
        if deleted:
            self._emit(
                ServiceEvent(
                    ServiceEventType.SUBSCRIPTION_FOLDER_DELETED,
                    "Subscription folder deleted; subscriptions and files were kept",
                    payload={"folder_id": folder_id},
                )
            )
        return deleted

    def move_subscription(self, subscription_id: int, folder_id: int | None) -> Subscription:
        if folder_id is not None and self.repository.get_subscription_folder(folder_id) is None:
            raise KeyError(f"subscription folder {folder_id} does not exist")
        return self.save_subscription(
            {
                "id": subscription_id,
                "folder_id": folder_id,
                # Moving opts back into the selected folder's default root.
                # Existing files are intentionally never relocated.
                "save_directory": None,
            }
        )

    def save_subscription(self, data: Subscription | Mapping[str, Any]) -> Subscription:
        subscription = self._subscription_from_input(data)
        self._validate_subscription_patterns(subscription)
        refresh_lock: threading.Lock | None = None
        if subscription.id is not None:
            with self._state_lock:
                refresh_lock = self._refresh_locks.setdefault(subscription.id, threading.Lock())
            refresh_lock.acquire()
        try:
            saved = self._save_subscription_locked(subscription)
        finally:
            if refresh_lock is not None:
                refresh_lock.release()
        self._emit(
            ServiceEvent(
                ServiceEventType.SUBSCRIPTION_SAVED,
                f"Saved subscription {saved.name}",
                subscription_id=saved.id,
            )
        )
        self._scheduler.wake()
        return saved

    def _save_subscription_locked(self, subscription: Subscription) -> Subscription:
        if (
            subscription.folder_id is not None
            and self.repository.get_subscription_folder(subscription.folder_id) is None
        ):
            raise KeyError(f"subscription folder {subscription.folder_id} does not exist")
        subscription = self._assign_unique_directory(subscription)
        existing = (
            self.repository.get_subscription(subscription.id)
            if subscription.id is not None
            else None
        )
        feed_changed = bool(existing and existing.feed_url != subscription.feed_url)
        if feed_changed:
            assert subscription.id is not None
            for task in self.repository.list_download_tasks(subscription_id=subscription.id):
                if task.id is None:
                    continue
                with self._state_lock:
                    control = self._controls.get(task.id)
                if control:
                    control.cancel()
            subscription = replace(subscription, last_checked_at=None)
        naming = self._naming_for_subscription(subscription)
        naming.directory_for(subscription, create=True)
        if feed_changed:
            return self.repository.save_subscription_replacing_history(subscription)
        return self.repository.save_subscription(subscription)

    def delete_subscription(self, subscription_id: int) -> bool:
        with self._state_lock:
            refresh_lock = self._refresh_locks.setdefault(subscription_id, threading.Lock())
        with refresh_lock:
            for task in self.repository.list_download_tasks(subscription_id=subscription_id):
                if task.id is not None:
                    with self._state_lock:
                        control = self._controls.get(task.id)
                    if control:
                        control.cancel()
            deleted = self.repository.delete_subscription(subscription_id)
        if deleted:
            self._emit(
                ServiceEvent(
                    ServiceEventType.SUBSCRIPTION_DELETED,
                    "Subscription deleted; downloaded files were kept",
                    subscription_id=subscription_id,
                )
            )
        return deleted

    def refresh_all(self) -> list[DownloadTask]:
        created: list[DownloadTask] = []
        failures: list[tuple[str, Exception]] = []
        for subscription in self.repository.list_subscriptions(enabled_only=True):
            if self._shutdown_event.is_set():
                break
            try:
                created.extend(self._refresh_subscription(subscription))
            except ServiceStopping:
                break
            except Exception as exc:
                # The individual refresh emitted a detailed failure.  Continue
                # so one unavailable feed does not block all other feeds.
                failures.append((subscription.name, exc))
                continue
        if failures:
            raise RefreshBatchError(failures)
        return created

    def refresh_subscription(self, subscription_id: int) -> list[DownloadTask]:
        subscription = self.repository.get_subscription(subscription_id)
        if subscription is None:
            raise KeyError(f"subscription {subscription_id} does not exist")
        return self._refresh_subscription(subscription)

    def _refresh_from_scheduler(self, subscription: Subscription) -> list[DownloadTask]:
        return self._refresh_subscription(subscription)

    def _refresh_subscription(self, subscription: Subscription) -> list[DownloadTask]:
        assert subscription.id is not None
        subscription_id = subscription.id
        with self._state_lock:
            refresh_lock = self._refresh_locks.setdefault(subscription_id, threading.Lock())
        with refresh_lock:
            if self._shutdown_event.is_set():
                raise ServiceStopping("service is stopping")
            # Scheduler/manual refresh callers may have queued an older dataclass
            # snapshot.  Always reload after acquiring the same lock used by edits,
            # otherwise a feed-URL change can resurrect the old source's history and
            # incorrectly consume the new source's first-refresh safety baseline.
            current_subscription = self.repository.get_subscription(subscription_id)
            if current_subscription is None:
                return []
            subscription = current_subscription
            self._emit(
                ServiceEvent(
                    ServiceEventType.REFRESH_STARTED,
                    f"Refreshing {subscription.name}",
                    subscription_id=subscription_id,
                )
            )
            settings = self.get_settings()
            try:
                raw = self._feed_fetcher(subscription.feed_url, settings)
                if self._shutdown_event.is_set():
                    raise ServiceStopping("service is stopping")
                feed_items = parse_feed(
                    raw,
                    subscription_id,
                    base_url=subscription.feed_url,
                )
                created_tasks: list[DownloadTask] = []
                # A missing success timestamp is authoritative even when a prior
                # process wrote only part of the feed before crashing.  Treat the
                # remaining historical entries as baseline as well.
                initial_baseline = subscription.last_checked_at is None
                naming = self._naming_for_subscription(subscription, settings=settings)
                destination = naming.directory_for(subscription, create=True)
                include = (
                    re.compile(subscription.include_pattern, re.I)
                    if subscription.include_pattern
                    else None
                )
                exclude = (
                    re.compile(subscription.exclude_pattern, re.I)
                    if subscription.exclude_pattern
                    else None
                )
                for item in feed_items:
                    if subscription.episode_pattern:
                        item = replace(
                            item,
                            episode=recognize_episode(item.title, subscription.episode_pattern),
                        )
                    # Record every observed entry before applying download filters.  This
                    # makes the first refresh a complete safety baseline: loosening a
                    # filter later must not turn old feed history into newly seen items.
                    matches_filters = not (
                        (include and not include.search(item.title))
                        or (exclude and exclude.search(item.title))
                    )
                    should_create_task = bool(
                        matches_filters
                        and subscription.download_enabled
                        and item.download_url
                        and not (initial_baseline and not subscription.download_existing)
                    )
                    if not should_create_task:
                        self.repository.add_feed_item(item)
                        continue
                    _, stored_task, task_was_new = self._create_feed_item_download_task(
                        subscription, item, destination, naming
                    )
                    if not task_was_new or stored_task is None:
                        continue
                    created_tasks.append(stored_task)
                    self._emit(
                        ServiceEvent(
                            ServiceEventType.TASK_ADDED,
                            f"Queued {stored_task.title}",
                            subscription_id=subscription_id,
                            task_id=stored_task.id,
                        )
                    )
                    with self._state_lock:
                        if self._running:
                            self._submit_task_locked(stored_task)

                current = self.repository.get_subscription(subscription_id)
                if current is not None:
                    self.repository.save_subscription(replace(current, last_checked_at=utc_now()))
                self._emit(
                    ServiceEvent(
                        ServiceEventType.REFRESH_FINISHED,
                        f"Found {len(created_tasks)} new downloads",
                        subscription_id=subscription_id,
                        payload={"new_tasks": len(created_tasks)},
                    )
                )
                return created_tasks
            except ServiceStopping:
                raise
            except Exception as exc:
                current = self.repository.get_subscription(subscription_id)
                # Preserve a new subscription's "no successful baseline yet"
                # state.  Otherwise one transient first-fetch failure would
                # make the next successful refresh enqueue the whole backlog.
                if current is not None and current.last_checked_at is not None:
                    with suppress(Exception):
                        self.repository.save_subscription(
                            replace(current, last_checked_at=utc_now())
                        )
                self._emit(
                    ServiceEvent(
                        ServiceEventType.REFRESH_FAILED,
                        str(exc),
                        subscription_id=subscription_id,
                    )
                )
                raise

    # Download task API -------------------------------------------------
    def list_tasks(
        self,
        statuses: Sequence[DownloadStatus | str] | None = None,
        *,
        subscription_id: int | None = None,
        limit: int | None = None,
    ) -> list[DownloadTask]:
        return self.repository.list_download_tasks(
            statuses=statuses,
            subscription_id=subscription_id,
            limit=limit,
        )

    def list_feed_items(
        self,
        subscription_id: int,
        *,
        limit: int | None = None,
    ) -> list[FeedItem]:
        """List discovered entries for one subscription, newest first."""

        if self.repository.get_subscription(subscription_id) is None:
            raise KeyError(f"subscription {subscription_id} does not exist")
        return self.repository.list_feed_items(subscription_id, limit=limit)

    def download_feed_item(self, subscription_id: int, item_id: int) -> DownloadTask:
        """Queue or resume an explicitly selected feed item.

        Manual downloads intentionally bypass the subscription's automatic
        download switch and title filters. They still share the refresh/edit
        lock, filename reservation, task de-duplication and safe destination
        logic used by automatic downloads.
        """

        if self._shutdown_event.is_set():
            raise ServiceStopping("service is stopping")
        with self._state_lock:
            refresh_lock = self._refresh_locks.setdefault(subscription_id, threading.Lock())
        with refresh_lock:
            if self._shutdown_event.is_set():
                raise ServiceStopping("service is stopping")
            # The subscription or item may have been removed/replaced while we
            # waited for a refresh or edit to finish, so reload both under the
            # same lock before creating any task.
            subscription = self.repository.get_subscription(subscription_id)
            item = self.repository.get_feed_item(item_id)
            if subscription is None or item is None or item.subscription_id != subscription_id:
                raise KeyError(f"feed item {item_id} does not exist")
            if not item.download_url:
                raise ValueError("this feed item does not provide a downloadable URL")

            existing = self.repository.get_download_task_for_feed_item(item_id)
            if existing is not None:
                if existing.status in {
                    DownloadStatus.PAUSED,
                    DownloadStatus.FAILED,
                    DownloadStatus.CANCELLED,
                }:
                    assert existing.id is not None
                    return self.resume_task(existing.id)
                if existing.status == DownloadStatus.QUEUED:
                    with self._state_lock:
                        if self._running:
                            self._submit_task_locked(existing)
                return existing

            settings = self.get_settings()
            naming = self._naming_for_subscription(subscription, settings=settings)
            destination = naming.directory_for(subscription, create=True)
            with self._filename_lock:
                # Keep the database uniqueness constraint as the final guard in
                # case another API client queued the same item concurrently.
                existing = self.repository.get_download_task_for_feed_item(item_id)
                if existing is None:
                    filename = self._unique_task_filename(
                        destination,
                        naming.filename_for(item),
                    )
                    task, inserted = self.repository.add_download_task(
                        DownloadTask(
                            subscription_id=subscription_id,
                            feed_item_id=item_id,
                            title=item.title,
                            source_url=item.download_url,
                            destination_directory=str(destination),
                            filename=filename,
                            kind=classify_download(item.download_url, item.content_type),
                        )
                    )
                else:
                    task, inserted = existing, False

            if not inserted:
                if task.status in {
                    DownloadStatus.PAUSED,
                    DownloadStatus.FAILED,
                    DownloadStatus.CANCELLED,
                }:
                    assert task.id is not None
                    return self.resume_task(task.id)
                if task.status == DownloadStatus.QUEUED:
                    with self._state_lock:
                        if self._running:
                            self._submit_task_locked(task)
                return task

            self._emit(
                ServiceEvent(
                    ServiceEventType.TASK_ADDED,
                    f"Manually queued {task.title}",
                    subscription_id=subscription_id,
                    task_id=task.id,
                    payload={"manual": True},
                )
            )
            with self._state_lock:
                if self._running:
                    self._submit_task_locked(task)
            return task

    def get_task(self, task_id: int) -> DownloadTask | None:
        return self.repository.get_download_task(task_id)

    def pause_task(self, task_id: int) -> DownloadTask:
        task = self._require_task(task_id)
        if task.status in {DownloadStatus.COMPLETED, DownloadStatus.CANCELLED}:
            return task
        with self._state_lock:
            control = self._controls.get(task_id)
            future = self._futures.get(task_id)
            updated = self.repository.update_download_task(task_id, status=DownloadStatus.PAUSED)
            if control:
                # Cancelling the current attempt releases its executor slot.
                # Resume creates a fresh HTTP range request or torrent handle.
                control.cancel()
            if future:
                future.cancel()
        self._emit_task_update(updated, "Paused")
        return updated

    def resume_task(self, task_id: int) -> DownloadTask:
        task = self._require_task(task_id)
        if task.status == DownloadStatus.COMPLETED:
            return task
        with self._state_lock:
            control = self._controls.get(task_id)
            future = self._futures.get(task_id)
            if (
                task.status == DownloadStatus.PAUSED
                and control
                and not control.cancelled
                and future is not None
                and future.running()
                and task.started_at is not None
            ):
                control.resume()
                status = DownloadStatus.DOWNLOADING
            else:
                if control and not control.cancelled:
                    control.resume()
                status = DownloadStatus.QUEUED
            updated = self.repository.update_download_task(task_id, status=status, error=None)
            if self._running and status == DownloadStatus.QUEUED:
                self._submit_task_locked(updated)
        self._emit_task_update(updated, "Resumed")
        return updated

    def cancel_task(self, task_id: int) -> DownloadTask:
        task = self._require_task(task_id)
        if task.status in {DownloadStatus.COMPLETED, DownloadStatus.CANCELLED}:
            return task
        with self._state_lock:
            control = self._controls.get(task_id)
            future = self._futures.get(task_id)
            if control:
                control.cancel()
            if future:
                future.cancel()
            updated = self.repository.update_download_task(
                task_id,
                status=DownloadStatus.CANCELLED,
                error=None,
            )
        self._emit_task_update(updated, "Cancelled")
        return updated

    def remove_task(self, task_id: int, *, delete_files: bool = False) -> bool:
        """Remove task metadata and optionally its exact HTTP output files.

        Torrent/magnet payloads may span many files and directories that are
        not represented by ``DownloadTask.filename``.  AniRSS therefore
        refuses automatic BT file deletion instead of risking removal of an
        entire series directory.
        """

        task = self._require_task(task_id)
        if delete_files and task.kind in {DownloadKind.TORRENT, DownloadKind.MAGNET}:
            raise ValueError(
                "AniRSS cannot safely enumerate every file in this BT task; "
                "remove its metadata only and review downloaded files manually"
            )
        with self._state_lock:
            control = self._controls.get(task_id)
            future = self._futures.get(task_id)
            if control:
                control.cancel()
            if future:
                future.cancel()
        if delete_files and future and not future.done():
            try:
                future.result(timeout=self.get_settings().request_timeout_seconds + 2)
            except (CancelledError, DownloadCancelled):
                pass
            except TimeoutError as exc:
                raise RuntimeError(
                    "download worker did not stop in time; files and metadata were kept"
                ) from exc
        if delete_files:
            self._delete_http_task_files(task)
        deleted = self.repository.delete_download_task(task_id)
        if deleted:
            self._emit(
                ServiceEvent(
                    ServiceEventType.TASK_REMOVED,
                    "Task removed",
                    subscription_id=task.subscription_id,
                    task_id=task.id,
                    payload={"files_deleted": delete_files},
                )
            )
        return deleted

    def delete_task_metadata(self, task_id: int) -> bool:
        """Compatibility alias for ``remove_task(delete_files=False)``."""

        return self.remove_task(task_id, delete_files=False)

    def remove_download(self, task_id: int, *, delete_files: bool = False) -> bool:
        """Desktop-controller-friendly alias for :meth:`remove_task`."""

        return self.remove_task(task_id, delete_files=delete_files)

    @staticmethod
    def _delete_http_task_files(task: DownloadTask) -> None:
        directory = Path(task.destination_directory).expanduser().resolve()
        target = safe_download_path(directory, task.filename)
        partial = ensure_within_root(directory, target.with_name(target.name + ".part"))
        for path in (target, partial):
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                raise RuntimeError(f"could not delete download file {path}: {exc}") from exc

    def _submit_task_locked(self, task: DownloadTask) -> None:
        assert task.id is not None
        task_id = task.id
        existing = self._futures.get(task_id)
        if existing is not None and existing.done():
            self._futures.pop(task_id, None)
            self._controls.pop(task_id, None)
            existing = None
        if self._executor is None or existing is not None:
            return
        control = DownloadControl()
        self._controls[task_id] = control
        future = self._executor.submit(self._run_task, task_id, control)
        self._futures[task_id] = future
        future.add_done_callback(partial(self._task_future_done, task_id))

    def _task_future_done(self, task_id: int, _future: Future[None]) -> None:
        with self._state_lock:
            if self._futures.get(task_id) is not _future:
                return
            self._futures.pop(task_id, None)
            self._controls.pop(task_id, None)
            task = self.repository.get_download_task(task_id)
            if self._running and task is not None and task.status == DownloadStatus.QUEUED:
                self._submit_task_locked(task)

    def _run_task(self, task_id: int, control: DownloadControl) -> None:
        # Serialize the QUEUED -> DOWNLOADING transition with pause/resume/
        # cancel so a worker cannot overwrite a just-written PAUSED state.
        with self._state_lock:
            task = self.repository.get_download_task(task_id)
            if (
                task is None
                or task.status != DownloadStatus.QUEUED
                or control.cancelled
                or control.paused
            ):
                return
            task = self.repository.update_download_task(
                task_id,
                status=DownloadStatus.DOWNLOADING,
                started_at=task.started_at or utc_now(),
                error=None,
            )
        self._emit_task_update(task, "Downloading")
        last_written_progress = -1.0
        last_written_at = 0.0

        def on_progress(downloaded: int, total: int | None, progress: float) -> None:
            nonlocal last_written_at, last_written_progress
            now = time.monotonic()
            # Record at least once per second so speed remains meaningful for
            # large/slow tasks, while retaining the ~1% write optimization.
            if (
                progress < 1.0
                and progress - last_written_progress < 0.01
                and now - last_written_at < 1.0
            ):
                return
            last_written_progress = progress
            last_written_at = now
            try:
                updated = self.repository.update_download_task(
                    task_id,
                    downloaded_bytes=downloaded,
                    total_bytes=total,
                    progress=progress,
                )
                self._emit_task_update(updated, "Progress")
            except KeyError:
                return

        try:
            result = self._downloaders.for_task(task).download(
                task, self.get_settings(), control, on_progress
            )
            current = self.repository.get_download_task(task_id)
            if current is None or current.status == DownloadStatus.CANCELLED:
                return
            completed = self.repository.update_download_task(
                task_id,
                status=DownloadStatus.COMPLETED,
                progress=1.0,
                downloaded_bytes=result.downloaded_bytes,
                total_bytes=result.total_bytes,
                completed_at=utc_now(),
                error=None,
            )
            self._emit_task_update(completed, "Completed")
        except DownloadCancelled:
            current = self.repository.get_download_task(task_id)
            if current is None:
                return
            # A user can retry while the cancelled worker is still unwinding.
            # Preserve that explicit QUEUED intent; the future's done callback
            # will submit a fresh worker after this one has fully exited.
            if current.status in {
                DownloadStatus.CANCELLED,
                DownloadStatus.PAUSED,
                DownloadStatus.QUEUED,
            }:
                return
            target_status = DownloadStatus.QUEUED if self._stopping else DownloadStatus.CANCELLED
            updated = self.repository.update_download_task(
                task_id, status=target_status, error=None
            )
            self._emit_task_update(updated, "Interrupted")
        except Exception as exc:
            current = self.repository.get_download_task(task_id)
            if current is None or current.status == DownloadStatus.CANCELLED:
                return
            target_status = DownloadStatus.QUEUED if self._stopping else DownloadStatus.FAILED
            updated = self.repository.update_download_task(
                task_id,
                status=target_status,
                error=None if self._stopping else str(exc),
            )
            self._emit_task_update(updated, "Failed")

    def _emit_task_update(self, task: DownloadTask, message: str) -> None:
        self._emit(
            ServiceEvent(
                ServiceEventType.TASK_UPDATED,
                message,
                subscription_id=task.subscription_id,
                task_id=task.id,
                payload={
                    "status": task.status.value,
                    "progress": task.progress,
                    "downloaded_bytes": task.downloaded_bytes,
                    "total_bytes": task.total_bytes,
                    "error": task.error,
                },
            )
        )

    def _require_task(self, task_id: int) -> DownloadTask:
        task = self.repository.get_download_task(task_id)
        if task is None:
            raise KeyError(f"download task {task_id} does not exist")
        return task

    # Settings/autostart API -------------------------------------------
    def get_settings(self) -> AppSettings:
        return self.repository.get_settings()

    def save_settings(self, data: AppSettings | Mapping[str, Any]) -> AppSettings:
        previous = self.get_settings()
        if isinstance(data, AppSettings):
            settings = data
        else:
            merged = previous.to_dict()
            merged.update(data)
            settings = AppSettings.from_mapping(merged)
        Path(settings.download_root).expanduser().mkdir(parents=True, exist_ok=True)
        command = default_launch_command(minimized=settings.launch_minimized)
        if settings.autostart:
            is_configured = getattr(self._autostart, "is_configured", None)
            matches = bool(callable(is_configured) and is_configured(command))
            if not matches:
                self._autostart.set_enabled(True, command)
        elif previous.autostart:
            self._autostart.set_enabled(False, command)
        saved = self.repository.save_settings(settings)
        self._scheduler.wake()
        self._emit(ServiceEvent(ServiceEventType.SETTINGS_SAVED, "Settings saved"))
        return saved

    def configure_autostart(self, enabled: bool) -> AppSettings:
        settings = self.get_settings()
        command = default_launch_command(minimized=settings.launch_minimized)
        actual = self._autostart.set_enabled(enabled, command)
        saved = self.repository.save_settings(replace(settings, autostart=actual))
        self._emit(ServiceEvent(ServiceEventType.SETTINGS_SAVED, "Settings saved"))
        return saved

    # Helpers -----------------------------------------------------------
    def _subscription_from_input(self, data: Subscription | Mapping[str, Any]) -> Subscription:
        if isinstance(data, Subscription):
            return data
        values = dict(data)
        aliases = {
            "url": "feed_url",
            "rss_url": "feed_url",
            "folder_name": "directory_name",
            "save_path": "save_directory",
            "interval_minutes": "poll_interval_minutes",
            "auto_download": "download_enabled",
            "episode_regex": "episode_pattern",
        }
        for old, new in aliases.items():
            if old in values and new not in values:
                values[new] = values[old]
        if "include_keywords" in values and "include_pattern" not in values:
            values["include_pattern"] = self._keywords_pattern(
                values["include_keywords"], require_all=True
            )
        if "exclude_keywords" in values and "exclude_pattern" not in values:
            values["exclude_pattern"] = self._keywords_pattern(
                values["exclude_keywords"], require_all=False
            )
        subscription_id = values.get("id")
        if subscription_id is None or subscription_id == "":
            existing = None
        else:
            existing = self.repository.get_subscription(int(subscription_id))
        editable = {
            "name",
            "feed_url",
            "directory_name",
            "save_directory",
            "folder_id",
            "enabled",
            "download_enabled",
            "download_existing",
            "poll_interval_minutes",
            "include_pattern",
            "exclude_pattern",
            "episode_pattern",
        }
        if existing:
            merged = asdict(existing)
            merged.update({key: values[key] for key in editable if key in values})
            return Subscription(**merged)
        required = {key: values[key] for key in editable if key in values}
        return Subscription(**required)

    @staticmethod
    def _keywords_pattern(value: object, *, require_all: bool) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            keywords = [value.strip()] if value.strip() else []
        else:
            if not isinstance(value, Iterable):
                raise ValueError("keywords must be a string or a sequence of strings")
            keywords = [str(item).strip() for item in value]
            keywords = [keyword for keyword in keywords if keyword]
        if not keywords:
            return None
        escaped = [re.escape(keyword) for keyword in keywords]
        if require_all:
            return "".join(f"(?=.*{keyword})" for keyword in escaped)
        return "(?:" + "|".join(escaped) + ")"

    @staticmethod
    def _validate_subscription_patterns(subscription: Subscription) -> None:
        for label, pattern in (
            ("include_pattern", subscription.include_pattern),
            ("exclude_pattern", subscription.exclude_pattern),
            ("episode_pattern", subscription.episode_pattern),
        ):
            if not pattern:
                continue
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"invalid {label}: {exc}") from exc

    def _assign_unique_directory(self, subscription: Subscription) -> Subscription:
        if subscription.save_directory:
            return subscription
        requested = subscription.directory_name or subscription.name
        base = sanitize_component(requested, fallback="Anime")
        used = {
            sanitize_component(other.directory_name or other.name, fallback="Anime").casefold()
            for other in self.repository.list_subscriptions()
            if other.id != subscription.id and other.folder_id == subscription.folder_id
        }
        if base.casefold() not in used:
            # Preserve a user-selected directory label; default names need no
            # duplicate copy in the database.
            return subscription
        number = 2
        candidate = f"{base} ({number})"
        while candidate.casefold() in used:
            number += 1
            candidate = f"{base} ({number})"
        return replace(subscription, directory_name=candidate)

    def _naming_for_subscription(
        self,
        subscription: Subscription,
        *,
        settings: AppSettings | None = None,
    ) -> NamingPolicy:
        root = (settings or self.get_settings()).download_root
        if subscription.folder_id is not None:
            folder = self.repository.get_subscription_folder(subscription.folder_id)
            if folder is not None:
                root = folder.download_directory
        return NamingPolicy(root)

    def subscription_directory(self, subscription: Subscription, *, create: bool = False) -> Path:
        return self._naming_for_subscription(subscription).directory_for(
            subscription, create=create
        )

    def _scheduler_error(self, subscription: Subscription, exc: Exception) -> None:
        if isinstance(exc, ServiceStopping):
            return
        self._emit(
            ServiceEvent(
                ServiceEventType.ERROR,
                str(exc),
                subscription_id=subscription.id,
            )
        )

    def _unique_task_filename(
        self,
        destination: Path,
        requested: str,
    ) -> str:
        used = {
            task.filename.casefold()
            for task in self.repository.list_download_tasks()
            if Path(task.destination_directory).resolve() == destination.resolve()
        }
        candidate = requested
        path = safe_download_path(destination, candidate)
        number = 2
        while candidate.casefold() in used or path.exists() or Path(str(path) + ".part").exists():
            suffix = Path(requested).suffix
            stem = requested[: -len(suffix)] if suffix else requested
            candidate = sanitize_component(f"{stem} ({number}){suffix}", max_length=220)
            path = safe_download_path(destination, candidate)
            number += 1
        return candidate

    def _create_feed_item_download_task(
        self,
        subscription: Subscription,
        item: FeedItem,
        destination: Path,
        naming: NamingPolicy,
    ) -> tuple[FeedItem, DownloadTask | None, bool]:
        """Atomically reserve a filename and persist the item/task pair."""

        assert subscription.id is not None
        assert item.download_url is not None
        with self._filename_lock:
            filename = self._unique_task_filename(destination, naming.filename_for(item))
            return self.repository.add_feed_item_with_download_task(
                item,
                destination_directory=str(destination),
                filename=filename,
                kind=classify_download(item.download_url, item.content_type),
            )


__all__ = [
    "AniRSSService",
    "RefreshBatchError",
    "ServiceStopping",
    "default_data_directory",
]
