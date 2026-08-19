"""Public, UI-independent AniRSS core API."""

from .autostart import AutostartError, AutostartManager, default_launch_command
from .database import SCHEMA_VERSION, SQLiteRepository
from .downloaders import (
    DownloadCancelled,
    DownloadControl,
    DownloadError,
    DownloaderRouter,
    DownloadResult,
    HttpDownloader,
    LibtorrentDownloader,
    LibtorrentUnavailableError,
    classify_download,
)
from .feeds import FeedError, FeedParseError, fetch_feed, parse_date, parse_feed
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
)
from .naming import (
    NamingPolicy,
    UnsafePathError,
    create_series_directory,
    ensure_within_root,
    filename_for_item,
    recognize_episode,
    safe_download_path,
    sanitize_component,
)
from .scheduler import SubscriptionScheduler
from .service import AniRSSService, default_data_directory

__all__ = [
    "SCHEMA_VERSION",
    "AniRSSService",
    "AppSettings",
    "AutostartError",
    "AutostartManager",
    "DownloadCancelled",
    "DownloadControl",
    "DownloadError",
    "DownloadKind",
    "DownloadResult",
    "DownloadStatus",
    "DownloadTask",
    "DownloaderRouter",
    "FeedError",
    "FeedItem",
    "FeedParseError",
    "HttpDownloader",
    "LibtorrentDownloader",
    "LibtorrentUnavailableError",
    "NamingPolicy",
    "SQLiteRepository",
    "ServiceEvent",
    "ServiceEventType",
    "Subscription",
    "SubscriptionFolder",
    "SubscriptionScheduler",
    "UnsafePathError",
    "classify_download",
    "create_series_directory",
    "default_data_directory",
    "default_launch_command",
    "ensure_within_root",
    "fetch_feed",
    "filename_for_item",
    "parse_date",
    "parse_feed",
    "recognize_episode",
    "safe_download_path",
    "sanitize_component",
]
