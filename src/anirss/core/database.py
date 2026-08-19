"""Thread-safe SQLite persistence for the AniRSS core."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import (
    AppSettings,
    DownloadKind,
    DownloadStatus,
    DownloadTask,
    FeedItem,
    Subscription,
    SubscriptionFolder,
    utc_now,
)

SCHEMA_VERSION = 2


def _datetime_to_text(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _datetime_from_text(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class SQLiteRepository:
    """A small serialized repository around one SQLite connection.

    ``sqlite3`` connections are not safe for overlapping operations.  A
    re-entrant lock therefore guards this connection while
    ``check_same_thread=False`` allows scheduler and download workers to share
    it safely.  The repository owns the connection and should be closed when
    the application exits.
    """

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        if self.database_path != ":memory:":
            Path(self.database_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._closed = False
        self._connection = sqlite3.connect(
            self.database_path,
            check_same_thread=False,
            timeout=30,
        )
        self._connection.row_factory = sqlite3.Row
        with self._lock:
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA busy_timeout = 30000")
            if self.database_path != ":memory:":
                self._connection.execute("PRAGMA journal_mode = WAL")
        self.initialize()

    def initialize(self) -> None:
        with self._transaction() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS subscription_folders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    download_directory TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    feed_url TEXT NOT NULL UNIQUE,
                    directory_name TEXT,
                    save_directory TEXT,
                    folder_id INTEGER
                        REFERENCES subscription_folders(id) ON DELETE SET NULL,
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

                CREATE TABLE IF NOT EXISTS feed_items (
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

                CREATE TABLE IF NOT EXISTS download_tasks (
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
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_subscriptions_enabled
                    ON subscriptions(enabled);
                CREATE INDEX IF NOT EXISTS idx_feed_items_subscription
                    ON feed_items(subscription_id, published_at);
                CREATE INDEX IF NOT EXISTS idx_download_tasks_status
                    ON download_tasks(status, created_at);

                CREATE TABLE IF NOT EXISTS app_settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    payload TEXT NOT NULL
                );

                PRAGMA user_version = 2;
                """
            )
            # Databases created by an early 0.1 development build did not yet
            # persist the optional custom episode matcher.
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(subscriptions)")
            }
            if "episode_pattern" not in columns:
                connection.execute("ALTER TABLE subscriptions ADD COLUMN episode_pattern TEXT")
            if "save_directory" not in columns:
                connection.execute("ALTER TABLE subscriptions ADD COLUMN save_directory TEXT")
            if "download_existing" not in columns:
                connection.execute(
                    "ALTER TABLE subscriptions ADD COLUMN download_existing "
                    "INTEGER NOT NULL DEFAULT 0"
                )
            if "folder_id" not in columns:
                connection.execute(
                    "ALTER TABLE subscriptions ADD COLUMN folder_id INTEGER "
                    "REFERENCES subscription_folders(id) ON DELETE SET NULL"
                )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_subscriptions_folder "
                "ON subscriptions(folder_id, name)"
            )
            feed_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(feed_items)")
            }
            if "content_type" not in feed_columns:
                connection.execute("ALTER TABLE feed_items ADD COLUMN content_type TEXT")
            row = connection.execute("SELECT 1 FROM app_settings WHERE id = 1").fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO app_settings(id, payload) VALUES(1, ?)",
                    (json.dumps(AppSettings().to_dict(), ensure_ascii=False),),
                )

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            if self._closed:
                raise RuntimeError("repository is closed")
            try:
                yield self._connection
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._connection.close()
                self._closed = True

    def __enter__(self) -> SQLiteRepository:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # Subscription folders ---------------------------------------------
    def save_subscription_folder(self, folder: SubscriptionFolder) -> SubscriptionFolder:
        now = utc_now()
        with self._transaction() as connection:
            if folder.id is None:
                cursor = connection.execute(
                    """
                    INSERT INTO subscription_folders(
                        name, download_directory, created_at, updated_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        folder.name,
                        folder.download_directory,
                        _datetime_to_text(folder.created_at),
                        _datetime_to_text(now),
                    ),
                )
                lastrowid = cursor.lastrowid
                assert lastrowid is not None
                folder_id = int(lastrowid)
            else:
                cursor = connection.execute(
                    """
                    UPDATE subscription_folders
                    SET name = ?, download_directory = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        folder.name,
                        folder.download_directory,
                        _datetime_to_text(now),
                        folder.id,
                    ),
                )
                if cursor.rowcount == 0:
                    raise KeyError(f"subscription folder {folder.id} does not exist")
                folder_id = folder.id
        saved = self.get_subscription_folder(folder_id)
        assert saved is not None
        return saved

    def get_subscription_folder(self, folder_id: int) -> SubscriptionFolder | None:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM subscription_folders WHERE id = ?", (folder_id,)
            ).fetchone()
        return self._subscription_folder_from_row(row) if row is not None else None

    def list_subscription_folders(self) -> list[SubscriptionFolder]:
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM subscription_folders ORDER BY name COLLATE NOCASE, id"
            ).fetchall()
        return [self._subscription_folder_from_row(row) for row in rows]

    def delete_subscription_folder(self, folder_id: int) -> bool:
        with self._transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM subscription_folders WHERE id = ?", (folder_id,)
            )
        return cursor.rowcount > 0

    # Subscriptions -----------------------------------------------------
    def save_subscription(self, subscription: Subscription) -> Subscription:
        now = utc_now()
        with self._transaction() as connection:
            if subscription.id is None:
                cursor = connection.execute(
                    """
                    INSERT INTO subscriptions(
                        name, feed_url, directory_name, save_directory, folder_id, enabled,
                        download_enabled, download_existing,
                        poll_interval_minutes, include_pattern, exclude_pattern,
                        episode_pattern,
                        last_checked_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        subscription.name,
                        subscription.feed_url,
                        subscription.directory_name,
                        subscription.save_directory,
                        subscription.folder_id,
                        int(subscription.enabled),
                        int(subscription.download_enabled),
                        int(subscription.download_existing),
                        subscription.poll_interval_minutes,
                        subscription.include_pattern,
                        subscription.exclude_pattern,
                        subscription.episode_pattern,
                        _datetime_to_text(subscription.last_checked_at),
                        _datetime_to_text(subscription.created_at),
                        _datetime_to_text(now),
                    ),
                )
                lastrowid = cursor.lastrowid
                assert lastrowid is not None
                subscription_id = int(lastrowid)
            else:
                subscription_id = self._update_subscription_row(connection, subscription, now)
        saved = self.get_subscription(subscription_id)
        assert saved is not None
        return saved

    def save_subscription_replacing_history(self, subscription: Subscription) -> Subscription:
        """Atomically update a source and remove all metadata from the old source."""

        if subscription.id is None:
            raise ValueError("replacing a feed source requires an existing subscription")
        now = utc_now()
        with self._transaction() as connection:
            subscription_id = self._update_subscription_row(connection, subscription, now)
            # Download tasks are removed by the feed_items ON DELETE CASCADE.
            connection.execute(
                "DELETE FROM feed_items WHERE subscription_id = ?",
                (subscription_id,),
            )
            row = connection.execute(
                "SELECT * FROM subscriptions WHERE id = ?",
                (subscription_id,),
            ).fetchone()
            assert row is not None
            saved = self._subscription_from_row(row)
        return saved

    def get_subscription(self, subscription_id: int) -> Subscription | None:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM subscriptions WHERE id = ?", (subscription_id,)
            ).fetchone()
        return self._subscription_from_row(row) if row is not None else None

    def list_subscriptions(self, *, enabled_only: bool = False) -> list[Subscription]:
        query = "SELECT * FROM subscriptions"
        parameters: Sequence[object] = ()
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY name COLLATE NOCASE, id"
        with self._transaction() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._subscription_from_row(row) for row in rows]

    def delete_subscription(self, subscription_id: int) -> bool:
        with self._transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM subscriptions WHERE id = ?", (subscription_id,)
            )
        return cursor.rowcount > 0

    def clear_subscription_history(self, subscription_id: int) -> int:
        """Clear feed/task metadata for a replaced source, preserving files."""

        with self._transaction() as connection:
            task_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM download_tasks WHERE subscription_id = ?",
                    (subscription_id,),
                ).fetchone()[0]
            )
            item_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM feed_items WHERE subscription_id = ?",
                    (subscription_id,),
                ).fetchone()[0]
            )
            # Tasks are removed through the feed_items ON DELETE CASCADE.
            connection.execute(
                "DELETE FROM feed_items WHERE subscription_id = ?",
                (subscription_id,),
            )
        return task_count + item_count

    # Feed items --------------------------------------------------------
    def add_feed_item(self, item: FeedItem) -> tuple[FeedItem, bool]:
        """Insert an item and return ``(stored_item, was_inserted)``."""

        with self._transaction() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO feed_items(
                        subscription_id, guid, title, download_url, content_type,
                        link, description, published_at, episode, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.subscription_id,
                        item.guid,
                        item.title,
                        item.download_url,
                        item.content_type,
                        item.link,
                        item.description,
                        _datetime_to_text(item.published_at),
                        item.episode,
                        _datetime_to_text(item.created_at),
                    ),
                )
                lastrowid = cursor.lastrowid
                assert lastrowid is not None
                item_id = int(lastrowid)
                inserted = True
            except sqlite3.IntegrityError:
                row = connection.execute(
                    """
                    SELECT id FROM feed_items
                    WHERE subscription_id = ?
                      AND (guid = ? OR (download_url IS NOT NULL AND download_url = ?))
                    ORDER BY id LIMIT 1
                    """,
                    (item.subscription_id, item.guid, item.download_url),
                ).fetchone()
                if row is None:
                    raise
                item_id = int(row["id"])
                inserted = False
        stored = self.get_feed_item(item_id)
        assert stored is not None
        return stored, inserted

    def get_feed_item(self, item_id: int) -> FeedItem | None:
        with self._transaction() as connection:
            row = connection.execute("SELECT * FROM feed_items WHERE id = ?", (item_id,)).fetchone()
        return self._feed_item_from_row(row) if row is not None else None

    def list_feed_items(self, subscription_id: int, *, limit: int | None = None) -> list[FeedItem]:
        query = (
            "SELECT * FROM feed_items WHERE subscription_id = ? "
            "ORDER BY COALESCE(published_at, created_at) DESC, id DESC"
        )
        parameters: list[object] = [subscription_id]
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(max(0, limit))
        with self._transaction() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._feed_item_from_row(row) for row in rows]

    def count_feed_items(self, subscription_id: int) -> int:
        """Count recorded entries without loading their potentially large descriptions."""

        with self._transaction() as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM feed_items WHERE subscription_id = ?",
                (subscription_id,),
            ).fetchone()
        return int(row[0]) if row is not None else 0

    def add_feed_item_with_download_task(
        self,
        item: FeedItem,
        *,
        destination_directory: str,
        filename: str,
        kind: DownloadKind,
    ) -> tuple[FeedItem, DownloadTask | None, bool]:
        """Atomically insert a newly observed item and its required task.

        If task creation fails, the item insert is rolled back so a later feed
        refresh can retry instead of silently treating the episode as handled.
        """

        if not item.download_url:
            raise ValueError("a download task requires a source URL")
        with self._transaction() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO feed_items(
                        subscription_id, guid, title, download_url, content_type,
                        link, description, published_at, episode, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.subscription_id,
                        item.guid,
                        item.title,
                        item.download_url,
                        item.content_type,
                        item.link,
                        item.description,
                        _datetime_to_text(item.published_at),
                        item.episode,
                        _datetime_to_text(item.created_at),
                    ),
                )
            except sqlite3.IntegrityError:
                item_row = connection.execute(
                    """
                    SELECT * FROM feed_items
                    WHERE subscription_id = ?
                      AND (guid = ? OR (download_url IS NOT NULL AND download_url = ?))
                    ORDER BY id LIMIT 1
                    """,
                    (item.subscription_id, item.guid, item.download_url),
                ).fetchone()
                if item_row is None:
                    raise
                task_row = connection.execute(
                    "SELECT * FROM download_tasks WHERE feed_item_id = ?",
                    (item_row["id"],),
                ).fetchone()
                return (
                    self._feed_item_from_row(item_row),
                    self._download_task_from_row(task_row) if task_row is not None else None,
                    False,
                )

            item_id = cursor.lastrowid
            assert item_id is not None
            stored_item = replace(item, id=int(item_id))
            task = DownloadTask(
                subscription_id=item.subscription_id,
                feed_item_id=int(item_id),
                title=item.title,
                source_url=item.download_url,
                destination_directory=destination_directory,
                filename=filename,
                kind=kind,
            )
            task_cursor = connection.execute(
                """
                INSERT INTO download_tasks(
                    subscription_id, feed_item_id, title, source_url,
                    destination_directory, filename, kind, status, progress,
                    downloaded_bytes, total_bytes, error, created_at,
                    started_at, completed_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._task_values(task),
            )
            task_id = task_cursor.lastrowid
            assert task_id is not None
            return stored_item, replace(task, id=int(task_id)), True

    # Download tasks ----------------------------------------------------
    def add_download_task(self, task: DownloadTask) -> tuple[DownloadTask, bool]:
        with self._transaction() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO download_tasks(
                        subscription_id, feed_item_id, title, source_url,
                        destination_directory, filename, kind, status, progress,
                        downloaded_bytes, total_bytes, error, created_at,
                        started_at, completed_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    self._task_values(task),
                )
                lastrowid = cursor.lastrowid
                assert lastrowid is not None
                task_id = int(lastrowid)
                inserted = True
            except sqlite3.IntegrityError:
                row = connection.execute(
                    "SELECT id FROM download_tasks WHERE feed_item_id = ?",
                    (task.feed_item_id,),
                ).fetchone()
                if row is None:
                    raise
                task_id = int(row["id"])
                inserted = False
        stored = self.get_download_task(task_id)
        assert stored is not None
        return stored, inserted

    def get_download_task(self, task_id: int) -> DownloadTask | None:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM download_tasks WHERE id = ?", (task_id,)
            ).fetchone()
        return self._download_task_from_row(row) if row is not None else None

    def get_download_task_for_feed_item(self, feed_item_id: int) -> DownloadTask | None:
        """Return the single task associated with a discovered feed item."""

        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM download_tasks WHERE feed_item_id = ?",
                (feed_item_id,),
            ).fetchone()
        return self._download_task_from_row(row) if row is not None else None

    def list_download_tasks(
        self,
        *,
        statuses: Sequence[DownloadStatus | str] | None = None,
        subscription_id: int | None = None,
        limit: int | None = None,
    ) -> list[DownloadTask]:
        clauses: list[str] = []
        parameters: list[object] = []
        if statuses:
            values = [DownloadStatus(value).value for value in statuses]
            clauses.append("status IN (" + ",".join("?" for _ in values) + ")")
            parameters.extend(values)
        if subscription_id is not None:
            clauses.append("subscription_id = ?")
            parameters.append(subscription_id)
        query = "SELECT * FROM download_tasks"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC, id DESC"
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(max(0, limit))
        with self._transaction() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._download_task_from_row(row) for row in rows]

    def save_download_task(self, task: DownloadTask) -> DownloadTask:
        if task.id is None:
            return self.add_download_task(task)[0]
        task_id = task.id
        task = replace(task, updated_at=utc_now())
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE download_tasks SET
                    subscription_id = ?, feed_item_id = ?, title = ?,
                    source_url = ?, destination_directory = ?, filename = ?,
                    kind = ?, status = ?, progress = ?, downloaded_bytes = ?,
                    total_bytes = ?, error = ?, created_at = ?, started_at = ?,
                    completed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (*self._task_values(task), task_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"download task {task_id} does not exist")
        saved = self.get_download_task(task_id)
        assert saved is not None
        return saved

    def delete_download_task(self, task_id: int) -> bool:
        """Delete task metadata only; downloaded files are never touched."""

        with self._transaction() as connection:
            cursor = connection.execute("DELETE FROM download_tasks WHERE id = ?", (task_id,))
        return cursor.rowcount > 0

    def update_download_task(self, task_id: int, **changes: Any) -> DownloadTask:
        task = self.get_download_task(task_id)
        if task is None:
            raise KeyError(f"download task {task_id} does not exist")
        allowed = {
            field_name
            for field_name in task.__dataclass_fields__
            if field_name not in {"id", "subscription_id", "feed_item_id", "created_at"}
        }
        unknown = changes.keys() - allowed
        if unknown:
            raise ValueError(f"unsupported task fields: {', '.join(sorted(unknown))}")
        return self.save_download_task(replace(task, **changes))

    def requeue_interrupted_tasks(self) -> int:
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE download_tasks
                SET status = ?, error = NULL, updated_at = ?
                WHERE status = ?
                """,
                (
                    DownloadStatus.QUEUED.value,
                    _datetime_to_text(utc_now()),
                    DownloadStatus.DOWNLOADING.value,
                ),
            )
        return cursor.rowcount

    # Settings ----------------------------------------------------------
    def get_settings(self) -> AppSettings:
        with self._transaction() as connection:
            row = connection.execute("SELECT payload FROM app_settings WHERE id = 1").fetchone()
        if row is None:
            return AppSettings()
        return AppSettings.from_mapping(json.loads(row["payload"]))

    def save_settings(self, settings: AppSettings) -> AppSettings:
        payload = json.dumps(settings.to_dict(), ensure_ascii=False, sort_keys=True)
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO app_settings(id, payload) VALUES(1, ?)
                ON CONFLICT(id) DO UPDATE SET payload = excluded.payload
                """,
                (payload,),
            )
        return self.get_settings()

    @staticmethod
    def _subscription_folder_from_row(row: sqlite3.Row) -> SubscriptionFolder:
        return SubscriptionFolder(
            id=row["id"],
            name=row["name"],
            download_directory=row["download_directory"],
            created_at=_datetime_from_text(row["created_at"]),  # type: ignore[arg-type]
            updated_at=_datetime_from_text(row["updated_at"]),  # type: ignore[arg-type]
        )

    @staticmethod
    def _subscription_from_row(row: sqlite3.Row) -> Subscription:
        return Subscription(
            id=row["id"],
            name=row["name"],
            feed_url=row["feed_url"],
            directory_name=row["directory_name"],
            save_directory=row["save_directory"],
            folder_id=row["folder_id"],
            enabled=bool(row["enabled"]),
            download_enabled=bool(row["download_enabled"]),
            download_existing=bool(row["download_existing"]),
            poll_interval_minutes=row["poll_interval_minutes"],
            include_pattern=row["include_pattern"],
            exclude_pattern=row["exclude_pattern"],
            episode_pattern=row["episode_pattern"],
            last_checked_at=_datetime_from_text(row["last_checked_at"]),
            created_at=_datetime_from_text(row["created_at"]),  # type: ignore[arg-type]
            updated_at=_datetime_from_text(row["updated_at"]),  # type: ignore[arg-type]
        )

    @staticmethod
    def _feed_item_from_row(row: sqlite3.Row) -> FeedItem:
        return FeedItem(
            id=row["id"],
            subscription_id=row["subscription_id"],
            guid=row["guid"],
            title=row["title"],
            download_url=row["download_url"],
            content_type=row["content_type"],
            link=row["link"],
            description=row["description"],
            published_at=_datetime_from_text(row["published_at"]),
            episode=row["episode"],
            created_at=_datetime_from_text(row["created_at"]),  # type: ignore[arg-type]
        )

    @staticmethod
    def _download_task_from_row(row: sqlite3.Row) -> DownloadTask:
        return DownloadTask(
            id=row["id"],
            subscription_id=row["subscription_id"],
            feed_item_id=row["feed_item_id"],
            title=row["title"],
            source_url=row["source_url"],
            destination_directory=row["destination_directory"],
            filename=row["filename"],
            kind=DownloadKind(row["kind"]),
            status=DownloadStatus(row["status"]),
            progress=row["progress"],
            downloaded_bytes=row["downloaded_bytes"],
            total_bytes=row["total_bytes"],
            error=row["error"],
            created_at=_datetime_from_text(row["created_at"]),  # type: ignore[arg-type]
            started_at=_datetime_from_text(row["started_at"]),
            completed_at=_datetime_from_text(row["completed_at"]),
            updated_at=_datetime_from_text(row["updated_at"]),  # type: ignore[arg-type]
        )

    @staticmethod
    def _task_values(task: DownloadTask) -> tuple[object, ...]:
        return (
            task.subscription_id,
            task.feed_item_id,
            task.title,
            task.source_url,
            task.destination_directory,
            task.filename,
            task.kind.value,
            task.status.value,
            task.progress,
            task.downloaded_bytes,
            task.total_bytes,
            task.error,
            _datetime_to_text(task.created_at),
            _datetime_to_text(task.started_at),
            _datetime_to_text(task.completed_at),
            _datetime_to_text(task.updated_at),
        )

    @staticmethod
    def _update_subscription_row(
        connection: sqlite3.Connection,
        subscription: Subscription,
        now: datetime,
    ) -> int:
        assert subscription.id is not None
        cursor = connection.execute(
            """
            UPDATE subscriptions SET
                name = ?, feed_url = ?, directory_name = ?,
                save_directory = ?, folder_id = ?, enabled = ?, download_enabled = ?,
                download_existing = ?, poll_interval_minutes = ?,
                include_pattern = ?, exclude_pattern = ?,
                episode_pattern = ?, last_checked_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                subscription.name,
                subscription.feed_url,
                subscription.directory_name,
                subscription.save_directory,
                subscription.folder_id,
                int(subscription.enabled),
                int(subscription.download_enabled),
                int(subscription.download_existing),
                subscription.poll_interval_minutes,
                subscription.include_pattern,
                subscription.exclude_pattern,
                subscription.episode_pattern,
                _datetime_to_text(subscription.last_checked_at),
                _datetime_to_text(now),
                subscription.id,
            ),
        )
        if cursor.rowcount == 0:
            raise KeyError(f"subscription {subscription.id} does not exist")
        return subscription.id


__all__ = ["SCHEMA_VERSION", "SQLiteRepository"]
