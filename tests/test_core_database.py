from __future__ import annotations

import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from anirss.core.database import SQLiteRepository
from anirss.core.models import (
    AppSettings,
    DownloadKind,
    DownloadStatus,
    DownloadTask,
    FeedItem,
    Subscription,
    SubscriptionFolder,
)


class DatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repository = SQLiteRepository(Path(self.temporary.name) / "state.db")
        self.subscription = self.repository.save_subscription(
            Subscription(name="Example", feed_url="https://example.test/rss")
        )

    def tearDown(self) -> None:
        self.repository.close()
        self.temporary.cleanup()

    def test_subscription_crud(self) -> None:
        assert self.subscription.id is not None
        updated = self.repository.save_subscription(
            replace(self.subscription, name="Renamed", episode_pattern=r"#(\d+)")
        )
        self.assertEqual(updated.name, "Renamed")
        self.assertEqual(updated.episode_pattern, r"#(\d+)")
        self.assertEqual(len(self.repository.list_subscriptions()), 1)
        assert updated.id is not None
        self.assertTrue(self.repository.delete_subscription(updated.id))
        self.assertIsNone(self.repository.get_subscription(updated.id))

    def test_subscription_folder_crud_and_delete_keeps_subscription(self) -> None:
        folder = self.repository.save_subscription_folder(
            SubscriptionFolder(
                name="Seasonal",
                download_directory=str(Path(self.temporary.name) / "Seasonal"),
            )
        )
        assert folder.id is not None
        assert self.subscription.id is not None
        assigned = self.repository.save_subscription(
            replace(self.subscription, folder_id=folder.id)
        )
        self.assertEqual(assigned.folder_id, folder.id)
        self.assertEqual(self.repository.list_subscription_folders(), [folder])

        renamed = self.repository.save_subscription_folder(replace(folder, name="Archive"))
        self.assertEqual(renamed.name, "Archive")
        self.assertTrue(self.repository.delete_subscription_folder(folder.id))
        kept = self.repository.get_subscription(self.subscription.id)
        assert kept is not None
        self.assertIsNone(kept.folder_id)

    def test_schema_one_database_migrates_subscription_folders_in_place(self) -> None:
        database_path = Path(self.temporary.name) / "legacy.db"
        connection = sqlite3.connect(database_path)
        connection.executescript(
            """
            CREATE TABLE subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                feed_url TEXT NOT NULL UNIQUE,
                directory_name TEXT,
                save_directory TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                download_enabled INTEGER NOT NULL DEFAULT 1,
                download_existing INTEGER NOT NULL DEFAULT 0,
                poll_interval_minutes INTEGER,
                include_pattern TEXT,
                exclude_pattern TEXT,
                episode_pattern TEXT,
                last_checked_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            PRAGMA user_version = 1;
            """
        )
        connection.commit()
        connection.close()

        migrated = SQLiteRepository(database_path)
        migrated.close()
        connection = sqlite3.connect(database_path)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(subscriptions)")}
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        connection.close()
        self.assertIn("folder_id", columns)
        self.assertIn("subscription_folders", tables)
        self.assertEqual(version, 2)

    def test_feed_and_task_deduplication(self) -> None:
        assert self.subscription.id is not None
        item = FeedItem(
            subscription_id=self.subscription.id,
            guid="same-guid",
            title="Example [01]",
            download_url="https://cdn.example/01.mkv",
        )
        stored, first_insert = self.repository.add_feed_item(item)
        duplicate, second_insert = self.repository.add_feed_item(item)
        self.assertTrue(first_insert)
        self.assertFalse(second_insert)
        self.assertEqual(stored.id, duplicate.id)

        assert stored.id is not None
        task = DownloadTask(
            subscription_id=self.subscription.id,
            feed_item_id=stored.id,
            title=stored.title,
            source_url=stored.download_url or "",
            destination_directory=self.temporary.name,
            filename="01.mkv",
            kind=DownloadKind.HTTP,
        )
        stored_task, task_inserted = self.repository.add_download_task(task)
        duplicate_task, duplicate_inserted = self.repository.add_download_task(task)
        self.assertTrue(task_inserted)
        self.assertFalse(duplicate_inserted)
        self.assertEqual(stored_task.id, duplicate_task.id)
        self.assertEqual(
            self.repository.get_download_task_for_feed_item(stored.id),
            stored_task,
        )

        assert stored_task.id is not None
        updated = self.repository.update_download_task(
            stored_task.id,
            status=DownloadStatus.DOWNLOADING,
            progress=0.5,
            downloaded_bytes=50,
            total_bytes=100,
        )
        self.assertEqual(updated.status, DownloadStatus.DOWNLOADING)
        self.assertEqual(self.repository.requeue_interrupted_tasks(), 1)
        queued_task = self.repository.get_download_task(stored_task.id)
        assert queued_task is not None
        self.assertEqual(queued_task.status, DownloadStatus.QUEUED)
        self.assertTrue(self.repository.delete_download_task(stored_task.id))
        self.assertIsNone(self.repository.get_download_task(stored_task.id))
        self.assertIsNone(self.repository.get_download_task_for_feed_item(stored.id))

    def test_settings_round_trip_ui_fields(self) -> None:
        settings = AppSettings(
            download_root=self.temporary.name,
            proxy_url="http://127.0.0.1:8080",
            launch_minimized=True,
            minimize_to_tray=False,
            theme="dark",
            notifications_enabled=False,
            listen_port=51413,
            download_speed_limit_kib=2048,
            upload_speed_limit_kib=128,
        )
        self.repository.save_settings(settings)
        self.assertEqual(self.repository.get_settings(), settings)

    def test_delete_subscription_cascades_metadata(self) -> None:
        assert self.subscription.id is not None
        item, _ = self.repository.add_feed_item(
            FeedItem(
                subscription_id=self.subscription.id,
                guid="one",
                title="One",
                download_url="https://example.test/one.mkv",
            )
        )
        assert item.id is not None
        self.repository.add_download_task(
            DownloadTask(
                subscription_id=self.subscription.id,
                feed_item_id=item.id,
                title="One",
                source_url=item.download_url or "",
                destination_directory=self.temporary.name,
                filename="one.mkv",
            )
        )
        self.repository.delete_subscription(self.subscription.id)
        self.assertEqual(self.repository.list_download_tasks(), [])

    def test_source_replacement_rolls_back_if_history_cleanup_fails(self) -> None:
        assert self.subscription.id is not None
        item, _ = self.repository.add_feed_item(
            FeedItem(
                subscription_id=self.subscription.id,
                guid="old-source-item",
                title="Old source item",
                download_url="https://example.test/old.mkv",
            )
        )
        assert item.id is not None
        self.repository.add_download_task(
            DownloadTask(
                subscription_id=self.subscription.id,
                feed_item_id=item.id,
                title=item.title,
                source_url=item.download_url or "",
                destination_directory=self.temporary.name,
                filename="old.mkv",
            )
        )
        with self.repository._transaction() as connection:
            connection.execute(
                """
                CREATE TRIGGER reject_history_cleanup
                BEFORE DELETE ON feed_items
                BEGIN
                    SELECT RAISE(ABORT, 'simulated cleanup failure');
                END
                """
            )

        changed = replace(
            self.subscription,
            feed_url="https://example.test/new-rss",
            last_checked_at=None,
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.repository.save_subscription_replacing_history(changed)

        stored = self.repository.get_subscription(self.subscription.id)
        assert stored is not None
        self.assertEqual(stored.feed_url, self.subscription.feed_url)
        self.assertEqual(len(self.repository.list_feed_items(self.subscription.id)), 1)
        self.assertEqual(len(self.repository.list_download_tasks()), 1)

    def _new_task(self) -> DownloadTask:
        assert self.subscription.id is not None
        item, _ = self.repository.add_feed_item(
            FeedItem(
                subscription_id=self.subscription.id,
                guid="field-update-item",
                title="Field update item",
                download_url="https://example.test/field.mkv",
            )
        )
        assert item.id is not None
        # Mirror production: the service always persists the resolved path
        # handed out by NamingPolicy.directory_for.  CI temp dirs may contain
        # 8.3 short names that resolve() expands, so an unresolved path here
        # would not match directory-scoped queries.
        task, _ = self.repository.add_download_task(
            DownloadTask(
                subscription_id=self.subscription.id,
                feed_item_id=item.id,
                title=item.title,
                source_url=item.download_url or "",
                destination_directory=str(Path(self.temporary.name).resolve()),
                filename="field.mkv",
            )
        )
        assert task.id is not None
        return task

    def test_field_update_does_not_clobber_unrelated_columns(self) -> None:
        task = self._new_task()
        assert task.id is not None
        paused = self.repository.update_download_task_fields(
            task.id,
            DownloadStatus.QUEUED,
            DownloadStatus.DOWNLOADING,
            status=DownloadStatus.PAUSED,
            error="stop here",
        )
        self.assertEqual(paused.status, DownloadStatus.PAUSED)
        # A late progress write must not resurrect the pre-pause status or
        # drop the recorded error; only the given columns change.
        progressed = self.repository.update_download_task(
            task.id,
            progress=0.5,
            downloaded_bytes=50,
            total_bytes=100,
        )
        self.assertEqual(progressed.status, DownloadStatus.PAUSED)
        self.assertEqual(progressed.error, "stop here")
        self.assertEqual(progressed.progress, 0.5)
        self.assertEqual(progressed.downloaded_bytes, 50)
        self.assertEqual(progressed.total_bytes, 100)

    def test_guarded_update_is_a_no_op_outside_the_allowed_statuses(self) -> None:
        task = self._new_task()
        assert task.id is not None
        completed = self.repository.update_download_task_fields(
            task.id,
            DownloadStatus.QUEUED,
            status=DownloadStatus.COMPLETED,
            progress=1.0,
        )
        self.assertEqual(completed.status, DownloadStatus.COMPLETED)
        # A stale pause racing the completion must not revive the task.
        stale = self.repository.update_download_task_fields(
            task.id,
            DownloadStatus.QUEUED,
            DownloadStatus.DOWNLOADING,
            status=DownloadStatus.PAUSED,
        )
        self.assertEqual(stale.status, DownloadStatus.COMPLETED)
        self.assertEqual(stale.progress, 1.0)

    def test_download_task_file_manifest_round_trip(self) -> None:
        task = self._new_task()
        assert task.id is not None
        self.assertEqual(task.file_manifest, ())
        updated = self.repository.update_download_task_fields(
            task.id,
            file_manifest=["Series/Season 1/ep01.mkv", "Series/ep02.mkv"],
        )
        self.assertEqual(
            updated.file_manifest,
            ("Series/Season 1/ep01.mkv", "Series/ep02.mkv"),
        )
        reloaded = self.repository.get_download_task(task.id)
        assert reloaded is not None
        self.assertEqual(reloaded.file_manifest, updated.file_manifest)
        # A full-row save keeps the manifest instead of dropping it.
        kept = self.repository.save_download_task(reloaded)
        self.assertEqual(kept.file_manifest, updated.file_manifest)

    def test_field_update_validates_fields_and_task_existence(self) -> None:
        task = self._new_task()
        assert task.id is not None
        with self.assertRaisesRegex(ValueError, "unsupported task fields"):
            self.repository.update_download_task_fields(task.id, no_such_column=1)
        with self.assertRaises(KeyError):
            self.repository.update_download_task_fields(task.id + 100, progress=0.1)

    def test_download_task_filenames_are_scoped_to_the_directory(self) -> None:
        task = self._new_task()
        assert task.id is not None
        assert self.subscription.id is not None
        other_item, _ = self.repository.add_feed_item(
            FeedItem(
                subscription_id=self.subscription.id,
                guid="other-directory-item",
                title="Other directory item",
                download_url="https://example.test/other.mkv",
            )
        )
        assert other_item.id is not None
        other_directory = str(Path(self.temporary.name, "elsewhere").resolve())
        self.repository.add_download_task(
            DownloadTask(
                subscription_id=self.subscription.id,
                feed_item_id=other_item.id,
                title=other_item.title,
                source_url=other_item.download_url or "",
                destination_directory=other_directory,
                filename="field.mkv",
            )
        )
        scoped = self.repository.list_download_task_filenames(
            str(Path(self.temporary.name).resolve())
        )
        self.assertEqual(scoped, ["field.mkv"])
        self.assertEqual(
            self.repository.list_download_task_filenames(other_directory),
            ["field.mkv"],
        )
        self.assertEqual(
            self.repository.list_download_task_filenames(
                str(Path(self.temporary.name, "unused").resolve())
            ),
            [],
        )

    def test_manual_task_without_subscription_roundtrip(self) -> None:
        task = DownloadTask(
            subscription_id=None,
            feed_item_id=None,
            title="Manual magnet",
            source_url="magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567",
            destination_directory=self.temporary.name,
            filename="Manual magnet",
            kind=DownloadKind.MAGNET,
        )
        stored, inserted = self.repository.add_download_task(task)
        self.assertTrue(inserted)
        self.assertIsNone(stored.subscription_id)
        self.assertIsNone(stored.feed_item_id)

        found = self.repository.find_manual_task_by_source_url(task.source_url)
        self.assertEqual(found, stored)
        # Subscription tasks with the same URL are not matched.
        subscription_task = self._new_task()
        assert subscription_task.id is not None
        self.assertIsNone(
            self.repository.find_manual_task_by_source_url(subscription_task.source_url)
        )

    def test_notnull_task_columns_are_migrated_nullable(self) -> None:
        database_path = Path(self.temporary.name) / "legacy-tasks.db"
        connection = sqlite3.connect(database_path)
        connection.executescript(
            """
            CREATE TABLE subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                feed_url TEXT NOT NULL UNIQUE,
                directory_name TEXT,
                save_directory TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                download_enabled INTEGER NOT NULL DEFAULT 1,
                download_existing INTEGER NOT NULL DEFAULT 0,
                poll_interval_minutes INTEGER,
                include_pattern TEXT,
                exclude_pattern TEXT,
                episode_pattern TEXT,
                last_checked_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE feed_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subscription_id INTEGER NOT NULL
                    REFERENCES subscriptions(id) ON DELETE CASCADE,
                guid TEXT NOT NULL,
                title TEXT NOT NULL,
                download_url TEXT,
                content_type TEXT,
                link TEXT,
                description TEXT,
                published_at TEXT,
                episode TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(subscription_id, guid),
                UNIQUE(subscription_id, download_url)
            );
            CREATE TABLE download_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subscription_id INTEGER NOT NULL
                    REFERENCES subscriptions(id) ON DELETE CASCADE,
                feed_item_id INTEGER NOT NULL UNIQUE
                    REFERENCES feed_items(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                source_url TEXT NOT NULL,
                destination_directory TEXT NOT NULL,
                filename TEXT NOT NULL,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                progress REAL NOT NULL DEFAULT 0,
                downloaded_bytes INTEGER NOT NULL DEFAULT 0,
                total_bytes INTEGER,
                error TEXT,
                file_manifest TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                updated_at TEXT NOT NULL
            );
            INSERT INTO subscriptions(
                name, feed_url, enabled, download_enabled, download_existing,
                created_at, updated_at
            ) VALUES ('Legacy', 'https://example.test/legacy', 1, 1, 0,
                '2026-01-01T00:00:00', '2026-01-01T00:00:00');
            INSERT INTO feed_items(
                subscription_id, guid, title, download_url, created_at
            ) VALUES (1, 'legacy-item', 'Legacy item', 'https://example.test/a.mkv',
                '2026-01-01T00:00:00');
            INSERT INTO download_tasks(
                subscription_id, feed_item_id, title, source_url,
                destination_directory, filename, kind, status,
                created_at, updated_at
            ) VALUES (1, 1, 'Legacy item', 'https://example.test/a.mkv',
                '/tmp/legacy', 'a.mkv', 'http', 'completed',
                '2026-01-01T00:00:00', '2026-01-01T00:00:00');
            PRAGMA user_version = 2;
            """
        )
        connection.commit()
        connection.close()

        migrated = SQLiteRepository(database_path)
        tasks = migrated.list_download_tasks()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].title, "Legacy item")
        manual, inserted = migrated.add_download_task(
            DownloadTask(
                subscription_id=None,
                feed_item_id=None,
                title="Manual",
                source_url="magnet:?xt=urn:btih:abcdef",
                destination_directory=self.temporary.name,
                filename="Manual",
                kind=DownloadKind.MAGNET,
            )
        )
        self.assertTrue(inserted)
        migrated.close()

        connection = sqlite3.connect(database_path)
        notnull = {
            row[1]: row[3] for row in connection.execute("PRAGMA table_info(download_tasks)")
        }
        indexes = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
        }
        connection.close()
        self.assertEqual(notnull["subscription_id"], 0)
        self.assertEqual(notnull["feed_item_id"], 0)
        self.assertIn("idx_download_tasks_status", indexes)
        self.assertIn("idx_download_tasks_destination", indexes)
        assert manual.id is not None


if __name__ == "__main__":
    unittest.main()
