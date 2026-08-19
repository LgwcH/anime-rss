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


if __name__ == "__main__":
    unittest.main()
