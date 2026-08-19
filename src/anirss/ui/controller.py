"""Loose UI/backend contract and an in-memory preview controller."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices


@runtime_checkable
class AniRSSController(Protocol):
    """Methods consumed by :class:`~anirss.ui.MainWindow`.

    A real controller does not need to inherit QObject.  Every method is
    resolved using ``getattr`` and all signals are optional.
    """

    def dashboard_snapshot(self) -> Mapping[str, Any]: ...
    def list_subscriptions(self) -> list[Mapping[str, Any]]: ...
    def list_subscription_folders(self) -> list[Mapping[str, Any]]: ...
    def save_subscription_folder(self, folder: Mapping[str, Any]) -> Any: ...
    def delete_subscription_folder(self, folder_id: Any) -> Any: ...
    def move_subscription(self, subscription_id: Any, folder_id: Any | None) -> Any: ...
    def save_subscription(self, subscription: Mapping[str, Any]) -> Any: ...
    def delete_subscription(self, subscription_id: Any) -> Any: ...
    def refresh_all(self) -> Any: ...
    def refresh_subscription(self, subscription_id: Any) -> Any: ...
    def list_subscription_items(
        self, subscription_id: Any, limit: int = 300
    ) -> list[Mapping[str, Any]]: ...
    def download_feed_item(self, subscription_id: Any, item_id: Any) -> Any: ...
    def list_downloads(self, status_filter: str | None = None) -> list[Mapping[str, Any]]: ...
    def pause_download(self, download_id: Any) -> Any: ...
    def resume_download(self, download_id: Any) -> Any: ...
    def remove_download(self, download_id: Any, delete_files: bool = False) -> Any: ...
    def load_settings(self) -> Mapping[str, Any]: ...
    def save_settings(self, settings: Mapping[str, Any]) -> Any: ...
    def open_folder(self, path: str) -> Any: ...


def controller_call(
    controller: object | None,
    name: str,
    *args: Any,
    default: Any = None,
    **kwargs: Any,
) -> Any:
    """Call an optional controller method, returning *default* if absent."""

    method = getattr(controller, name, None)
    resolved_name = name
    if not callable(method):
        aliases = {
            "list_downloads": ("list_tasks",),
            "pause_download": ("pause_task",),
            "resume_download": ("resume_task",),
            "remove_download": ("remove_task", "cancel_task"),
            "load_settings": ("get_settings",),
        }
        for alias in aliases.get(name, (name,)):
            candidate = getattr(controller, alias, None)
            if callable(candidate):
                resolved_name = alias
                method = candidate
                break
    if not callable(method):
        return default
    if name == "list_downloads" and resolved_name == "list_tasks" and args:
        status_filter = args[0]
        args = ([status_filter] if status_filter else None, *args[1:])
    if name == "remove_download" and resolved_name == "cancel_task":
        # The core service's cancellation API intentionally never deletes
        # files.  A richer bridge may implement remove_download itself.
        return method(args[0])
    return method(*args, **kwargs)


class DemoController(QObject):
    """Small mutable dataset for designers and zero-config UI previews."""

    data_changed = Signal()
    subscriptions_changed = Signal()
    downloads_changed = Signal()
    settings_changed = Signal()
    notification = Signal(str, str)
    error = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        base = str(Path.home() / "Downloads" / "AniRSS")
        self._subscription_folders: list[dict[str, Any]] = [
            {
                "id": "seasonal",
                "name": "本季追番",
                "download_directory": str(Path(base) / "本季追番"),
            }
        ]
        self._subscriptions: list[dict[str, Any]] = [
            {
                "id": "frieren",
                "folder_id": "seasonal",
                "name": "葬送的芙莉莲",
                "rss_url": "https://example.com/frieren.xml",
                "save_path": str(Path(base) / "葬送的芙莉莲"),
                "include_keywords": ["1080P", "简体"],
                "exclude_keywords": ["720P"],
                "episode_regex": r"\[(\d+)\]",
                "auto_download": True,
                "enabled": True,
                "last_update": "今天 20:32",
                "episode_count": 28,
            },
            {
                "id": "apothecary",
                "folder_id": "seasonal",
                "name": "药屋少女的呢喃",
                "rss_url": "https://example.com/kusuriya.xml",
                "save_path": str(Path(base) / "药屋少女的呢喃"),
                "include_keywords": ["1080P"],
                "exclude_keywords": [],
                "episode_regex": r"(?:EP|E)(\d+)",
                "auto_download": True,
                "enabled": True,
                "last_update": "昨天 23:10",
                "episode_count": 24,
            },
        ]
        self._downloads: list[dict[str, Any]] = [
            {
                "id": "dl-1",
                "title": "葬送的芙莉莲 [28] [1080P]",
                "anime": "葬送的芙莉莲",
                "episode": "28",
                "status": "downloading",
                "progress": 67,
                "speed": "8.4 MB/s",
                "size": "1.42 GB",
                "eta": "1 分 08 秒",
                "path": str(Path(base) / "葬送的芙莉莲"),
            },
            {
                "id": "dl-2",
                "title": "药屋少女的呢喃 [24] [1080P]",
                "anime": "药屋少女的呢喃",
                "episode": "24",
                "status": "completed",
                "progress": 100,
                "speed": "—",
                "size": "1.16 GB",
                "eta": "已完成",
                "path": str(Path(base) / "药屋少女的呢喃"),
            },
            {
                "id": "dl-3",
                "title": "迷宫饭 [18] [1080P]",
                "anime": "迷宫饭",
                "episode": "18",
                "status": "paused",
                "progress": 31,
                "speed": "—",
                "size": "1.31 GB",
                "eta": "已暂停",
                "path": str(Path(base) / "迷宫饭"),
            },
        ]
        self._subscription_items: dict[Any, list[dict[str, Any]]] = {
            "frieren": [
                {
                    "id": "frieren-28",
                    "title": "葬送的芙莉莲 [28] [1080P] [简体]",
                    "episode": "28",
                    "published_at": "今天 20:28",
                    "description": "旅程的终点，也是新故事的开始。",
                    "link": "https://example.com/frieren/28",
                    "download_url": "https://example.com/files/frieren-28.mkv",
                    "content_type": "video/x-matroska",
                    "download_kind": "http",
                    "matches_rules": True,
                    "task_id": "dl-1",
                    "task_status": "downloading",
                    "task_error": None,
                },
                {
                    "id": "frieren-27",
                    "title": "葬送的芙莉莲 [27] [1080P] [简体]",
                    "episode": "27",
                    "published_at": "2026-08-01 20:30",
                    "description": "这一条已被记录，但尚未加入下载队列。",
                    "link": "https://example.com/frieren/27",
                    "download_url": "magnet:?xt=urn:btih:demo-frieren-27",
                    "content_type": "application/x-bittorrent",
                    "download_kind": "magnet",
                    "matches_rules": True,
                    "task_id": None,
                    "task_status": None,
                    "task_error": None,
                },
            ],
            "apothecary": [
                {
                    "id": "apothecary-24",
                    "title": "药屋少女的呢喃 EP24 [1080P]",
                    "episode": "24",
                    "published_at": "昨天 23:10",
                    "description": "已完成下载的示例条目。",
                    "link": "https://example.com/kusuriya/24",
                    "download_url": "https://example.com/files/kusuriya-24.mkv",
                    "content_type": "video/x-matroska",
                    "download_kind": "http",
                    "matches_rules": True,
                    "task_id": "dl-2",
                    "task_status": "completed",
                    "task_error": None,
                },
                {
                    "id": "apothecary-news",
                    "title": "药屋少女的呢喃 制作访谈",
                    "episode": "",
                    "published_at": "2026-07-28 18:00",
                    "description": "普通资讯条目，没有可下载的附件。",
                    "link": "https://example.com/kusuriya/interview",
                    "download_url": "",
                    "content_type": "",
                    "download_kind": None,
                    "matches_rules": False,
                    "task_id": None,
                    "task_status": None,
                    "task_error": None,
                },
            ],
        }
        self._settings: dict[str, Any] = {
            "download_directory": base,
            "max_concurrent_downloads": 3,
            "poll_interval_minutes": 15,
            "proxy": "",
            "start_on_boot": False,
            "minimize_to_tray": True,
            "seed_after_complete": False,
            "seed_minutes": 30,
            "listen_port": 51413,
            "theme": "light",
            "notifications": True,
        }

    def dashboard_snapshot(self) -> dict[str, Any]:
        active = sum(1 for item in self._downloads if item["status"] == "downloading")
        completed = sum(1 for item in self._downloads if item["status"] == "completed")
        return {
            "subscription_count": len(self._subscriptions),
            "active_downloads": active,
            "completed_downloads": completed,
            "download_speed": "8.4 MB/s" if active else "0 B/s",
            "next_refresh": "约 12 分钟后",
            "recent_tasks": list(reversed(self._downloads[-5:])),
        }

    def list_subscriptions(self) -> list[dict[str, Any]]:
        folders = {item["id"]: item for item in self._subscription_folders}
        result = deepcopy(self._subscriptions)
        for subscription in result:
            folder = folders.get(subscription.get("folder_id"))
            subscription["folder_name"] = folder.get("name", "") if folder else ""
            subscription["folder_download_directory"] = (
                folder.get("download_directory", "") if folder else ""
            )
            if not subscription.get("save_path"):
                root = (
                    Path(str(folder["download_directory"]))
                    if folder
                    else Path(self._settings["download_directory"])
                )
                subscription["resolved_save_path"] = str(
                    root / str(subscription.get("name") or "Anime")
                )
        return result

    def list_subscription_folders(self) -> list[dict[str, Any]]:
        counts: dict[Any, int] = {}
        for subscription in self._subscriptions:
            folder_id = subscription.get("folder_id")
            if folder_id is not None:
                counts[folder_id] = counts.get(folder_id, 0) + 1
        result = deepcopy(self._subscription_folders)
        for folder in result:
            folder["subscription_count"] = counts.get(folder.get("id"), 0)
        return result

    def save_subscription_folder(self, folder: Mapping[str, Any]) -> dict[str, Any]:
        incoming = dict(folder)
        folder_id = incoming.get("id")
        if folder_id is not None:
            for index, existing in enumerate(self._subscription_folders):
                if existing.get("id") == folder_id:
                    self._subscription_folders[index] = {**existing, **incoming}
                    self.subscriptions_changed.emit()
                    return deepcopy(self._subscription_folders[index])
        incoming["id"] = f"folder-{len(self._subscription_folders) + 1}"
        self._subscription_folders.append(incoming)
        self.subscriptions_changed.emit()
        return deepcopy(incoming)

    def delete_subscription_folder(self, folder_id: Any) -> None:
        self._subscription_folders = [
            folder for folder in self._subscription_folders if folder.get("id") != folder_id
        ]
        for subscription in self._subscriptions:
            if subscription.get("folder_id") == folder_id:
                subscription["folder_id"] = None
        self.subscriptions_changed.emit()

    def move_subscription(self, subscription_id: Any, folder_id: Any | None) -> dict[str, Any]:
        if folder_id is not None and not any(
            folder.get("id") == folder_id for folder in self._subscription_folders
        ):
            raise KeyError(f"subscription folder {folder_id} does not exist")
        for subscription in self._subscriptions:
            if subscription.get("id") == subscription_id:
                subscription["folder_id"] = folder_id
                subscription["save_path"] = ""
                subscription.pop("resolved_save_path", None)
                self.subscriptions_changed.emit()
                return next(
                    item for item in self.list_subscriptions() if item.get("id") == subscription_id
                )
        raise KeyError(f"subscription {subscription_id} does not exist")

    def save_subscription(self, subscription: Mapping[str, Any]) -> dict[str, Any]:
        incoming = dict(subscription)
        incoming.setdefault("last_update", "尚未刷新")
        incoming.setdefault("episode_count", 0)
        item_id = incoming.get("id")
        if item_id is not None:
            for index, existing in enumerate(self._subscriptions):
                if existing.get("id") == item_id:
                    self._subscriptions[index] = {**existing, **incoming}
                    self.subscriptions_changed.emit()
                    self.data_changed.emit()
                    return deepcopy(self._subscriptions[index])
        incoming["id"] = f"feed-{len(self._subscriptions) + 1}"
        self._subscriptions.append(incoming)
        self._subscription_items[incoming["id"]] = []
        self.subscriptions_changed.emit()
        self.data_changed.emit()
        return deepcopy(incoming)

    def delete_subscription(self, subscription_id: Any) -> None:
        self._subscriptions = [
            item for item in self._subscriptions if item.get("id") != subscription_id
        ]
        self._subscription_items.pop(subscription_id, None)
        self.subscriptions_changed.emit()
        self.data_changed.emit()

    def refresh_all(self) -> None:
        self.notification.emit("刷新完成", "所有 RSS 订阅均已检查。")
        self.data_changed.emit()

    def refresh_subscription(self, subscription_id: Any) -> None:
        if not any(item.get("id") == subscription_id for item in self._subscriptions):
            raise KeyError(f"subscription {subscription_id} does not exist")
        self.notification.emit("刷新完成", "该订阅的内容已更新。")
        self.subscriptions_changed.emit()
        self.data_changed.emit()

    def list_subscription_items(
        self, subscription_id: Any, limit: int = 300
    ) -> list[dict[str, Any]]:
        if subscription_id not in self._subscription_items:
            raise KeyError(f"subscription {subscription_id} does not exist")
        items = deepcopy(self._subscription_items[subscription_id])
        tasks = {task.get("id"): task for task in self._downloads}
        for item in items:
            task = tasks.get(item.get("task_id"))
            if task is None:
                item["task_id"] = None
                item["task_status"] = None
                item["task_error"] = None
            else:
                item["task_status"] = task.get("status")
                item["task_error"] = task.get("error")
        return items[: max(1, limit)]

    def download_feed_item(self, subscription_id: Any, item_id: Any) -> dict[str, Any]:
        items = self._subscription_items.get(subscription_id)
        if items is None:
            raise KeyError(f"subscription {subscription_id} does not exist")
        item = next((entry for entry in items if entry.get("id") == item_id), None)
        if item is None:
            raise KeyError(f"feed item {item_id} does not exist")
        if not item.get("download_url"):
            raise ValueError("this feed item does not provide a downloadable URL")
        existing = next(
            (task for task in self._downloads if task.get("id") == item.get("task_id")),
            None,
        )
        if existing is not None:
            if existing.get("status") in {"paused", "failed", "cancelled"}:
                existing["status"] = "queued"
                existing["eta"] = "等待中"
                existing["error"] = None
                self.downloads_changed.emit()
                self.data_changed.emit()
            return deepcopy(existing)
        subscription = next(
            entry for entry in self._subscriptions if entry.get("id") == subscription_id
        )
        task = {
            "id": f"manual-{len(self._downloads) + 1}",
            "title": item.get("title") or "未命名条目",
            "anime": subscription.get("name") or "",
            "episode": item.get("episode") or "",
            "status": "queued",
            "progress": 0,
            "speed": "—",
            "size": None,
            "eta": "等待中",
            "path": subscription.get("resolved_save_path") or subscription.get("save_path") or "",
            "kind": item.get("download_kind") or "http",
            "error": None,
        }
        self._downloads.append(task)
        item["task_id"] = task["id"]
        item["task_status"] = task["status"]
        self.downloads_changed.emit()
        self.data_changed.emit()
        self.notification.emit("已加入下载", str(task["title"]))
        return deepcopy(task)

    def list_downloads(self, status_filter: str | None = None) -> list[dict[str, Any]]:
        if not status_filter or status_filter in {"all", "全部"}:
            return deepcopy(self._downloads)
        return [deepcopy(item) for item in self._downloads if item.get("status") == status_filter]

    def _set_status(self, download_id: Any, status: str) -> None:
        for item in self._downloads:
            if item.get("id") == download_id:
                item["status"] = status
                item["eta"] = "已暂停" if status == "paused" else "计算中…"
        self.downloads_changed.emit()
        self.data_changed.emit()

    def pause_download(self, download_id: Any) -> None:
        self._set_status(download_id, "paused")

    def resume_download(self, download_id: Any) -> None:
        self._set_status(download_id, "downloading")

    def remove_download(self, download_id: Any, delete_files: bool = False) -> None:
        del delete_files  # Demo mode never touches the filesystem.
        self._downloads = [item for item in self._downloads if item.get("id") != download_id]
        self.downloads_changed.emit()
        self.data_changed.emit()

    def load_settings(self) -> dict[str, Any]:
        return deepcopy(self._settings)

    def save_settings(self, settings: Mapping[str, Any]) -> None:
        self._settings.update(settings)
        self.settings_changed.emit()
        self.notification.emit("设置已保存", "新的设置已经生效。")

    def open_folder(self, path: str) -> None:
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
