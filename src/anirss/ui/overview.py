"""Dashboard page (08-compact-pro overview)."""

from __future__ import annotations

import shutil
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .controller import controller_call
from .data import as_mapping, human_bytes, progress_percent
from .widgets import (
    CoverAvatar,
    ElidedLabel,
    KpiCell,
    SectionHeader,
    StatusDot,
    clear_layout,
)
from .widgets import JellyButton as QPushButton

_WEEKDAYS = "一二三四五六日"

_STATUS_VERBS = {
    "downloading": "开始下载",
    "queued": "已加入下载队列",
    "paused": "已暂停",
    "completed": "下载完成",
    "failed": "下载失败",
    "checking": "校验中",
    "seeding": "做种中",
    "cancelled": "已取消",
}


def _dict(item: Any) -> dict[str, Any]:
    return as_mapping(item)


def _size_text(value: Any) -> str:
    if value in {None, ""}:
        return ""
    return human_bytes(value)


class _DownloadRow(QWidget):
    """One active download: cover, title/meta and a 340px progress block."""

    def __init__(
        self,
        task: Mapping[str, Any],
        on_open_folder: Any,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._task = dict(task)
        self._on_open_folder = on_open_folder
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 10)
        layout.setSpacing(12)
        anime = str(self._task.get("anime") or self._task.get("series_name") or "")
        episode = str(self._task.get("episode") or "")
        layout.addWidget(CoverAvatar(anime or str(self._task.get("title") or "?"), 34))

        info = QVBoxLayout()
        info.setContentsMargins(0, 0, 0, 0)
        info.setSpacing(2)
        name = anime or str(self._task.get("title") or "未命名任务")
        if episode:
            name = f"{name} · EP{episode}"
        name_label = ElidedLabel(name)
        name_label.setStyleSheet("font-size:13px; font-weight:600;")
        info.addWidget(name_label)
        meta_parts = [str(self._task.get("title") or "")]
        size = _size_text(self._task.get("size", self._task.get("total_bytes")))
        if size:
            meta_parts.append(size)
        status = str(self._task.get("status") or "")
        if status and status != "downloading":
            meta_parts.append(_STATUS_VERBS.get(status, status))
        meta = ElidedLabel(" · ".join(part for part in meta_parts if part))
        meta.setObjectName("Muted")
        info.addWidget(meta)
        layout.addLayout(info, 1)

        progress_block = QVBoxLayout()
        progress_block.setContentsMargins(0, 0, 0, 0)
        progress_block.setSpacing(4)
        stats_row = QHBoxLayout()
        stats_row.setContentsMargins(0, 0, 0, 0)
        speed = str(self._task.get("speed") or "")
        eta = str(self._task.get("eta") or "")
        stats_text = " · ".join(
            part
            for part in [
                speed if speed and speed != "—" else "",
                f"剩余 {eta}" if eta and status == "downloading" else eta,
            ]
            if part
        )
        stats = ElidedLabel(stats_text or "—")
        stats.setObjectName("Muted")
        stats.setStyleSheet("font-size:12px;")
        stats_row.addWidget(stats, 1)
        progress = progress_percent(self._task.get("progress", 0))
        pct = QLabel(f"{progress}%")
        pct.setStyleSheet("font-size:12px; font-weight:600;")
        stats_row.addWidget(pct)
        progress_block.addLayout(stats_row)
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(progress)
        bar.setTextVisible(False)
        progress_block.addWidget(bar)
        progress_host = QWidget()
        progress_host.setLayout(progress_block)
        progress_host.setFixedWidth(340)
        layout.addWidget(progress_host, 0, Qt.AlignmentFlag.AlignVCenter)

    def mouseDoubleClickEvent(self, event: Any) -> None:
        self._on_open_folder(self._task)
        super().mouseDoubleClickEvent(event)


class _KvRow(QWidget):
    """``dot + label .... value`` row used in the storage/source sections."""

    def __init__(
        self,
        label: str,
        value: str,
        *,
        dot: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 3, 0, 3)
        layout.setSpacing(6)
        if dot:
            layout.addWidget(StatusDot(dot), 0, Qt.AlignmentFlag.AlignVCenter)
        key = QLabel(label)
        key.setObjectName("Muted")
        key.setStyleSheet("font-size:12px;")
        layout.addWidget(key)
        layout.addStretch()
        self.value_label = ElidedLabel(value)
        self.value_label.setStyleSheet("font-size:12px;")
        self.value_label.setMaximumWidth(180)
        layout.addWidget(self.value_label, 0, Qt.AlignmentFlag.AlignRight)


class _ActivityRow(QWidget):
    """``时间 + 事件`` single-line activity entry."""

    def __init__(self, time_text: str, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 6)
        layout.setSpacing(10)
        time_label = QLabel(time_text)
        time_label.setObjectName("Muted")
        time_label.setFixedWidth(76)
        layout.addWidget(time_label, 0, Qt.AlignmentFlag.AlignTop)
        self.text_label = ElidedLabel(text)
        self.text_label.setStyleSheet("font-size:12px;")
        layout.addWidget(self.text_label, 1)


class OverviewPage(QWidget):
    """At-a-glance KPIs, active downloads, storage and recent activity."""

    error = Signal(str)
    refresh_requested = Signal()
    show_all_downloads = Signal()

    def __init__(self, controller: object | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._theme = "light"
        self._tasks: list[dict[str, Any]] = []
        self._subscriptions: list[dict[str, Any]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(self.scroll_area)

        container = QWidget()
        outer = QHBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        column = QWidget()
        column.setMaximumWidth(1064)
        outer.addWidget(column, 1064)
        outer.addStretch(1)
        self.scroll_area.setWidget(container)

        layout = QVBoxLayout(column)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(0)

        # 页头
        head = QHBoxLayout()
        head.setSpacing(12)
        title = QLabel("概览")
        title.setObjectName("PageTitle")
        head.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
        today = datetime.now()
        date_text = f"{today.year}年{today.month}月{today.day}日 周{_WEEKDAYS[today.weekday()]}"
        self.next_refresh = ElidedLabel(date_text)
        self.next_refresh.setObjectName("PageSubtitle")
        self.next_refresh.setMaximumWidth(420)
        head.addWidget(self.next_refresh, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addStretch()
        self.refresh_button = QPushButton("⟳ 刷新全部源")
        self.refresh_button.setProperty("primary", True)
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        head.addWidget(self.refresh_button, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(head)
        layout.addSpacing(16)

        # KPI 条
        self.cards = {
            "subscription_count": KpiCell("活跃订阅"),
            "active_downloads": KpiCell("下载中任务"),
            "download_speed": KpiCell("当前速度"),
            "completed_downloads": KpiCell("累计完成"),
        }
        strip = QFrame()
        strip.setObjectName("KpiStrip")
        strip_layout = QHBoxLayout(strip)
        strip_layout.setContentsMargins(0, 0, 0, 0)
        strip_layout.setSpacing(0)
        for index, card in enumerate(self.cards.values()):
            card.setProperty("first", index == 0)
            if index == 0:
                card_layout = card.layout()
                if card_layout is not None:
                    card_layout.setContentsMargins(0, 12, 16, 12)
            strip_layout.addWidget(card, 1)
        layout.addWidget(strip)

        # 下载中
        self.dl_header = SectionHeader("下载中", action="查看全部任务 →")
        self.dl_header.action_clicked.connect(self.show_all_downloads.emit)
        dl_section = QVBoxLayout()
        dl_section.setContentsMargins(0, 20, 0, 0)
        dl_section.setSpacing(0)
        dl_section.addWidget(self.dl_header)
        self.dl_rows = QVBoxLayout()
        self.dl_rows.setContentsMargins(0, 4, 0, 0)
        self.dl_rows.setSpacing(0)
        dl_section.addLayout(self.dl_rows)
        self.dl_empty = QLabel("当前没有下载中的任务")
        self.dl_empty.setObjectName("Muted")
        self.dl_empty.setContentsMargins(0, 10, 0, 10)
        dl_section.addWidget(self.dl_empty)
        layout.addLayout(dl_section)

        # 底部双栏
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 20, 0, 0)
        bottom.setSpacing(32)

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(0)
        self.storage_header = SectionHeader("存储占用")
        left.addWidget(self.storage_header)
        storage_value_row = QHBoxLayout()
        storage_value_row.setContentsMargins(0, 2, 0, 0)
        storage_value_row.setSpacing(6)
        self.storage_value = QLabel("—")
        self.storage_value.setStyleSheet("font-size:20px; font-weight:600;")
        storage_value_row.addWidget(self.storage_value, 0, Qt.AlignmentFlag.AlignBaseline)
        self.storage_caption = ElidedLabel("")
        self.storage_caption.setObjectName("Muted")
        storage_value_row.addWidget(self.storage_caption, 0, Qt.AlignmentFlag.AlignBaseline)
        storage_value_row.addStretch()
        left.addLayout(storage_value_row)
        self.storage_bar = QProgressBar()
        self.storage_bar.setProperty("neutral", True)
        self.storage_bar.setRange(0, 100)
        self.storage_bar.setTextVisible(False)
        left.addSpacing(8)
        left.addWidget(self.storage_bar)
        self.storage_rows = QVBoxLayout()
        self.storage_rows.setContentsMargins(0, 6, 0, 0)
        self.storage_rows.setSpacing(0)
        left.addLayout(self.storage_rows)

        self.source_header = SectionHeader("RSS 源")
        left.addSpacing(24)
        left.addWidget(self.source_header)
        self.source_rows = QVBoxLayout()
        self.source_rows.setContentsMargins(0, 4, 0, 0)
        self.source_rows.setSpacing(0)
        left.addLayout(self.source_rows)
        left.addStretch()
        left_host = QWidget()
        left_host.setLayout(left)
        left_host.setFixedWidth(320)
        bottom.addWidget(left_host, 0, Qt.AlignmentFlag.AlignTop)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        self.activity_header = SectionHeader("最近活动")
        right.addWidget(self.activity_header)
        self.activity_rows = QVBoxLayout()
        self.activity_rows.setContentsMargins(0, 4, 0, 0)
        self.activity_rows.setSpacing(0)
        right.addLayout(self.activity_rows)
        self.activity_empty = QLabel("还没有可展示的活动记录")
        self.activity_empty.setObjectName("Muted")
        self.activity_empty.setContentsMargins(0, 8, 0, 8)
        right.addWidget(self.activity_empty)
        right.addStretch()
        right_host = QWidget()
        right_host.setLayout(right)
        bottom.addWidget(right_host, 1)
        layout.addLayout(bottom)
        layout.addStretch()

    # ------------------------------------------------------------------ API

    def set_controller(self, controller: object | None) -> None:
        self.controller = controller

    def set_refreshing(self, refreshing: bool) -> None:
        self.refresh_button.setEnabled(not refreshing)
        self.refresh_button.setText("正在刷新…" if refreshing else "⟳ 刷新全部源")

    def reload(self) -> None:
        try:
            snapshot = controller_call(self.controller, "dashboard_snapshot", default=None)
            subscriptions = (
                controller_call(self.controller, "list_subscriptions", default=[]) or []
            )
            tasks = controller_call(self.controller, "list_downloads", None, default=[]) or []
            normalized_tasks = [_dict(item) for item in tasks]
            self._subscriptions = [_dict(item) for item in subscriptions]
            if snapshot is None:
                snapshot = {
                    "subscription_count": len(self._subscriptions),
                    "active_downloads": sum(
                        item.get("status") == "downloading" for item in normalized_tasks
                    ),
                    "completed_downloads": sum(
                        item.get("completed", item.get("status") == "completed")
                        for item in normalized_tasks
                    ),
                    "download_speed": "—",
                    "next_refresh": "按计划自动检查",
                    "recent_tasks": list(reversed(normalized_tasks[-8:])),
                }
            elif not isinstance(snapshot, Mapping):
                snapshot = as_mapping(snapshot)
            snapshot = dict(snapshot)
            snapshot.setdefault("recent_tasks", list(reversed(normalized_tasks[-8:])))
            self._tasks = normalized_tasks
            self.set_snapshot(snapshot)
            self._render_sources()
            self._render_storage()
        except Exception as exc:  # Backend errors should not take down the UI.
            self.error.emit(f"加载概览失败：{exc}")

    def set_snapshot(self, snapshot: Mapping[str, Any]) -> None:
        values = dict(snapshot)
        active = int(values.get("active_downloads", values.get("downloading", 0)) or 0)
        speed = str(values.get("download_speed", values.get("speed", "0 B/s")))
        self.cards["subscription_count"].set_value(
            values.get("subscription_count", values.get("subscriptions", 0)),
            "启用中的 RSS 订阅",
            "部",
        )
        self.cards["active_downloads"].set_value(active, f"合计 {speed}", "项")
        self.cards["download_speed"].set_value(speed, "全部任务合计速度")
        self.cards["completed_downloads"].set_value(
            values.get("completed_downloads", values.get("completed", 0)),
            "历史完成任务",
            "项",
        )
        today = datetime.now()
        date_text = f"{today.year}年{today.month}月{today.day}日 周{_WEEKDAYS[today.weekday()]}"
        self.next_refresh.setText(
            f"{date_text} · 下次刷新 {values.get('next_refresh', '等待计划')}"
        )
        recent = values.get("recent_tasks", values.get("recent_downloads", []))
        self.set_recent_tasks(
            recent if isinstance(recent, Sequence) and not isinstance(recent, str) else []
        )

    def set_recent_tasks(self, tasks: Sequence[Any]) -> None:
        normalized = [_dict(item) for item in tasks]
        active = [
            item
            for item in normalized
            if str(item.get("status") or "")
            in {"downloading", "queued", "paused", "checking", "seeding"}
        ]
        clear_layout(self.dl_rows)
        for task in active[:6]:
            self.dl_rows.addWidget(_DownloadRow(task, self._open_task_folder))
        self.dl_empty.setVisible(not active)
        self.dl_header.set_count(f"{len(active)} 项" if active else "")

        clear_layout(self.activity_rows)
        entries = normalized[:10]
        for task in entries:
            status = str(task.get("status") or "")[:50]
            verb = _STATUS_VERBS.get(status, status or "已更新")
            anime = str(task.get("anime") or task.get("series_name") or "")
            episode = str(task.get("episode") or "")
            title = anime or str(task.get("title") or "未命名任务")
            if episode:
                title = f"{title} EP{episode}"
            size = _size_text(task.get("size", task.get("total_bytes")))
            when = str(
                task.get("completed_at")
                or task.get("updated_at")
                or task.get("eta")
                or ""
            )[:40]
            text = f"{title} {verb}"
            if size:
                text = f"{text} · {size}"
            self.activity_rows.addWidget(_ActivityRow(when or "—", text))
        self.activity_empty.setVisible(not entries)

    # -------------------------------------------------------------- internals

    def _render_sources(self) -> None:
        clear_layout(self.source_rows)
        seen: dict[str, str] = {}
        for subscription in self._subscriptions:
            url = str(subscription.get("rss_url") or subscription.get("feed_url") or "")
            host = urlparse(url).netloc or url or "未知来源"
            last_update = str(subscription.get("last_update") or "尚未刷新")
            seen.setdefault(host, last_update)
        for host, last_update in seen.items():
            state = "wait" if last_update in {"尚未刷新", "", "—"} else "sub"
            self.source_rows.addWidget(
                _KvRow(host, f"上次更新 {last_update}", dot=state)
            )
        self.source_header.set_count(f"{len(seen)} 个" if seen else "")
        if not seen:
            empty = QLabel("添加订阅后会显示来源状态")
            empty.setObjectName("Muted")
            empty.setContentsMargins(0, 6, 0, 6)
            self.source_rows.addWidget(empty)

    def _render_storage(self) -> None:
        clear_layout(self.storage_rows)
        directory = ""
        try:
            settings = as_mapping(
                controller_call(self.controller, "load_settings", default={}) or {}
            )
            directory = str(
                settings.get("download_directory")
                or settings.get("download_dir")
                or settings.get("download_root")
                or ""
            )
        except Exception:
            directory = ""
        self.storage_header.set_count(directory or "")
        try:
            usage = shutil.disk_usage(directory or ".")
        except OSError:
            self.storage_value.setText("—")
            self.storage_caption.setText("无法读取磁盘信息")
            self.storage_bar.setValue(0)
            return
        used = usage.total - usage.free
        percent = round(used / usage.total * 100) if usage.total else 0
        self.storage_value.setText(human_bytes(used))
        self.storage_caption.setText(f"/ {human_bytes(usage.total)} · {percent}%")
        self.storage_bar.setValue(percent)
        self.storage_rows.addWidget(_KvRow("已用空间", human_bytes(used)))
        self.storage_rows.addWidget(_KvRow("可用空间", human_bytes(usage.free)))
        if directory:
            row = _KvRow("下载目录", directory)
            row.setToolTip(directory)
            self.storage_rows.addWidget(row)

    def _open_task_folder(self, task: Mapping[str, Any]) -> None:
        path = task.get("path") or task.get("save_path")
        if path:
            try:
                controller_call(self.controller, "open_folder", str(path))
            except Exception as exc:
                self.error.emit(f"无法打开保存目录：{exc}")

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        for card in self.cards.values():
            card.set_theme(theme)

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        compact = event.size().height() < 520
        for card in self.cards.values():
            card.set_compact(compact)
