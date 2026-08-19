"""Domain models used by AniRSS's UI-independent core.

The models deliberately contain only values that SQLite and JSON can represent.
Filesystem paths are stored as strings so a database can be moved between
Windows installations without constructing a ``Path`` on import.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(UTC)


class DownloadStatus(StrEnum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DownloadKind(StrEnum):
    HTTP = "http"
    TORRENT = "torrent"
    MAGNET = "magnet"


class ServiceEventType(StrEnum):
    SUBSCRIPTION_SAVED = "subscription_saved"
    SUBSCRIPTION_DELETED = "subscription_deleted"
    SUBSCRIPTION_FOLDER_SAVED = "subscription_folder_saved"
    SUBSCRIPTION_FOLDER_DELETED = "subscription_folder_deleted"
    REFRESH_STARTED = "refresh_started"
    REFRESH_FINISHED = "refresh_finished"
    REFRESH_FAILED = "refresh_failed"
    TASK_ADDED = "task_added"
    TASK_UPDATED = "task_updated"
    TASK_REMOVED = "task_removed"
    SETTINGS_SAVED = "settings_saved"
    ERROR = "error"


@dataclass(slots=True)
class SubscriptionFolder:
    name: str
    download_directory: str
    id: int | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.name = self.name.strip()
        self.download_directory = str(self.download_directory).strip()
        if not self.name:
            raise ValueError("subscription folder name cannot be empty")
        if not self.download_directory:
            raise ValueError("subscription folder download directory cannot be empty")


@dataclass(slots=True)
class Subscription:
    name: str
    feed_url: str
    id: int | None = None
    folder_id: int | None = None
    directory_name: str | None = None
    save_directory: str | None = None
    enabled: bool = True
    download_enabled: bool = True
    download_existing: bool = False
    poll_interval_minutes: int | None = None
    include_pattern: str | None = None
    exclude_pattern: str | None = None
    episode_pattern: str | None = None
    last_checked_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.name = self.name.strip()
        self.feed_url = self.feed_url.strip()
        if not self.name:
            raise ValueError("subscription name cannot be empty")
        if not self.feed_url:
            raise ValueError("feed URL cannot be empty")
        if self.poll_interval_minutes is not None and self.poll_interval_minutes < 1:
            raise ValueError("poll_interval_minutes must be at least 1")
        if self.directory_name is not None:
            self.directory_name = self.directory_name.strip() or None
        if self.save_directory is not None:
            self.save_directory = str(self.save_directory).strip() or None


@dataclass(slots=True)
class FeedItem:
    subscription_id: int
    guid: str
    title: str
    download_url: str | None = None
    content_type: str | None = None
    id: int | None = None
    link: str | None = None
    description: str | None = None
    published_at: datetime | None = None
    episode: str | None = None
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.guid = self.guid.strip()
        self.title = self.title.strip()
        if not self.guid:
            raise ValueError("feed item guid cannot be empty")
        if not self.title:
            self.title = "Untitled"


@dataclass(slots=True)
class DownloadTask:
    subscription_id: int
    feed_item_id: int
    title: str
    source_url: str
    destination_directory: str
    filename: str
    kind: DownloadKind = DownloadKind.HTTP
    id: int | None = None
    status: DownloadStatus = DownloadStatus.QUEUED
    progress: float = 0.0
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, DownloadKind):
            self.kind = DownloadKind(self.kind)
        if not isinstance(self.status, DownloadStatus):
            self.status = DownloadStatus(self.status)
        self.progress = max(0.0, min(1.0, float(self.progress)))
        if self.downloaded_bytes < 0:
            raise ValueError("downloaded_bytes cannot be negative")
        if self.total_bytes is not None and self.total_bytes < 0:
            raise ValueError("total_bytes cannot be negative")


@dataclass(slots=True)
class AppSettings:
    download_root: str = field(default_factory=lambda: str(Path.home() / "Downloads" / "AniRSS"))
    default_poll_interval_minutes: int = 30
    max_concurrent_downloads: int = 3
    request_timeout_seconds: int = 30
    user_agent: str = "AniRSS/0.1"
    proxy_url: str | None = None
    autostart: bool = False
    launch_minimized: bool = False
    minimize_to_tray: bool = True
    theme: str = "system"
    notifications_enabled: bool = True
    seed_after_completion: bool = False
    seed_time_minutes: int = 0
    listen_port: int = 6881
    bt_metadata_timeout_seconds: int = 120
    bt_stall_timeout_seconds: int = 600
    download_speed_limit_kib: int = 0
    upload_speed_limit_kib: int = 0
    keep_partial_downloads: bool = True
    overwrite_existing: bool = False
    verify_tls: bool = True
    scheduler_tick_seconds: int = 15

    def __post_init__(self) -> None:
        self.download_root = str(self.download_root).strip()
        if not self.download_root:
            raise ValueError("download_root cannot be empty")
        if self.default_poll_interval_minutes < 1:
            raise ValueError("default_poll_interval_minutes must be at least 1")
        if self.max_concurrent_downloads < 1:
            raise ValueError("max_concurrent_downloads must be at least 1")
        if self.request_timeout_seconds < 1:
            raise ValueError("request_timeout_seconds must be at least 1")
        if self.seed_time_minutes < 0:
            raise ValueError("seed_time_minutes cannot be negative")
        if not 0 <= self.listen_port <= 65535:
            raise ValueError("listen_port must be between 0 and 65535")
        if self.bt_metadata_timeout_seconds < 30:
            raise ValueError("bt_metadata_timeout_seconds must be at least 30")
        if self.bt_stall_timeout_seconds < 60:
            raise ValueError("bt_stall_timeout_seconds must be at least 60")
        if self.download_speed_limit_kib < 0 or self.upload_speed_limit_kib < 0:
            raise ValueError("speed limits cannot be negative")
        if self.theme not in {"system", "light", "dark"}:
            raise ValueError("theme must be 'system', 'light', or 'dark'")
        if self.proxy_url is not None:
            self.proxy_url = self.proxy_url.strip() or None
        if self.scheduler_tick_seconds < 1:
            raise ValueError("scheduler_tick_seconds must be at least 1")

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> AppSettings:
        """Build settings while ignoring UI-only/forward-compatible keys."""

        values = dict(values)
        if "proxy" in values and "proxy_url" not in values:
            values["proxy_url"] = values["proxy"]
        known = cls.__dataclass_fields__
        return cls(**{key: value for key, value in values.items() if key in known})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class ServiceEvent:
    type: ServiceEventType
    message: str = ""
    subscription_id: int | None = None
    task_id: int | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)


__all__ = [
    "AppSettings",
    "DownloadKind",
    "DownloadStatus",
    "DownloadTask",
    "FeedItem",
    "ServiceEvent",
    "ServiceEventType",
    "Subscription",
    "utc_now",
]
