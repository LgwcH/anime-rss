"""Inline detail view for discovered entries in one RSS subscription."""

from __future__ import annotations

import html
import re
from collections.abc import Mapping, Sequence
from contextlib import suppress
from typing import Any

from PySide6.QtCore import QPropertyAnimation, Qt, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QBoxLayout,
    QComboBox,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .controller import controller_call
from .data import as_mapping
from .motion import COLLAPSE_DURATION_MS, ease_out_curve, reduced_motion_requested
from .resources import icon
from .theme import colors
from .widgets import BadgeLabel, ElidedLabel, EmptyState, PageHeader
from .widgets import JellyButton as QPushButton
from .worker import FunctionWorker

_STATUS_PRESENTATION: dict[str, tuple[str, str, str, str]] = {
    "queued": ("等待中", "info", "查看任务", "show"),
    "downloading": ("下载中", "accent", "查看任务", "show"),
    "paused": ("已暂停", "warning", "继续", "download"),
    "completed": ("已完成", "success", "查看任务", "show"),
    "failed": ("下载失败", "danger", "重试", "download"),
    "cancelled": ("已取消", "neutral", "重新下载", "download"),
}


def _plain_description(value: Any) -> str:
    text = html.unescape(str(value or "")[:20000])
    text = re.sub(r"(?i)<\s*(?:br|/p|/div)\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()[:6000]


def _kind_text(value: Any) -> str:
    return {
        "http": "HTTP",
        "torrent": "种子",
        "magnet": "磁力",
    }.get(str(value or "").lower(), "—")


def _keyword_summary(value: Any, empty: str) -> tuple[str, str]:
    if not value:
        return empty, empty
    if isinstance(value, str):
        full = value[:4000]
        summary = full if len(full) <= 80 else f"{full[:77]}…"
        return summary, full
    if isinstance(value, Sequence):
        total = len(value)
        full_items = [str(item)[:200] for item in value[:100]]
        full = "、".join(full_items)[:4000]
        shown = [str(item)[:12] for item in value[:2]]
        summary = "、".join(shown)
        if total > len(shown):
            summary = f"{summary}（另 {total - len(shown)} 项）"
        return summary or empty, full or empty
    full = str(value)[:4000]
    summary = full if len(full) <= 80 else f"{full[:77]}…"
    return summary, full


class SubscriptionDetailView(QWidget):
    """Browse recorded feed items and explicitly queue individual downloads."""

    back_requested = Signal()
    edit_requested = Signal(object)
    refresh_requested = Signal(object)
    show_download_requested = Signal(object)
    changed = Signal()
    message = Signal(str)
    error = Signal(str)

    def __init__(self, controller: object | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._theme = "light"
        self._subscription: dict[str, Any] = {}
        self._items: list[dict[str, Any]] = []
        self._connected_signals: list[Any] = []
        self._download_workers: dict[tuple[Any, Any], FunctionWorker] = {}
        self._refreshing_subscription_id: Any = None
        self._secondary_header_forced = False

        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(30, 18, 30, 22)
        self.root_layout.setSpacing(11)

        navigation = QHBoxLayout()
        self.back_button = QPushButton("返回订阅")
        self.back_button.setProperty("flat", True)
        self.back_button.clicked.connect(lambda _checked=False: self.back_requested.emit())
        navigation.addWidget(self.back_button)
        navigation.addStretch()
        self.root_layout.addLayout(navigation)

        self.header_card = QFrame()
        self.header_card.setObjectName("HeroCard")
        header_layout = QVBoxLayout(self.header_card)
        header_layout.setContentsMargins(20, 17, 20, 17)
        header_layout.setSpacing(10)
        self.header_top = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.header_top.setSpacing(8)
        self.header = PageHeader("订阅详情", "选择条目后可自主加入下载队列")
        self.header_top.addWidget(self.header, 1)
        self.header_actions = QWidget()
        header_actions_layout = QHBoxLayout(self.header_actions)
        header_actions_layout.setContentsMargins(0, 0, 0, 0)
        header_actions_layout.setSpacing(8)
        self.edit_button = QPushButton("编辑")
        self.edit_button.setProperty("expandedText", "编辑")
        self.edit_button.clicked.connect(self._request_edit)
        header_actions_layout.addWidget(self.edit_button)
        self.folder_button = QPushButton("打开文件夹")
        self.folder_button.setProperty("expandedText", "打开文件夹")
        self.folder_button.clicked.connect(self._open_folder)
        header_actions_layout.addWidget(self.folder_button)
        self.info_button = QPushButton("订阅信息")
        self.info_button.setProperty("expandedText", "订阅信息")
        self.info_button.setProperty("flat", True)
        self.info_button.setToolTip("查看 RSS 来源、保存位置和匹配规则")
        self.info_button.clicked.connect(self._toggle_subscription_info)
        self.info_button.hide()
        header_actions_layout.addWidget(self.info_button)
        self.refresh_button = QPushButton("刷新此订阅")
        self.refresh_button.setProperty("expandedText", "刷新此订阅")
        self.refresh_button.setProperty("primary", True)
        self.refresh_button.clicked.connect(self._request_refresh)
        header_actions_layout.addWidget(self.refresh_button)
        self._header_actions_compact = False
        self._update_header_action_mode(True)
        self.header_top.addWidget(self.header_actions)
        header_layout.addLayout(self.header_top)
        self.metadata_widget = QWidget()
        metadata_layout = QHBoxLayout(self.metadata_widget)
        metadata_layout.setContentsMargins(0, 0, 0, 0)
        metadata_layout.setSpacing(14)
        self.count_metadata = ElidedLabel()
        self.count_metadata.setObjectName("Muted")
        self.count_metadata.setMaximumWidth(180)
        self.count_metadata.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Preferred,
        )
        metadata_layout.addWidget(self.count_metadata)
        self.refresh_metadata = ElidedLabel()
        self.refresh_metadata.setObjectName("Muted")
        self.refresh_metadata.setMaximumWidth(280)
        self.refresh_metadata.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Preferred,
        )
        metadata_layout.addWidget(self.refresh_metadata)
        self.metadata = ElidedLabel("", Qt.TextElideMode.ElideMiddle)
        self.metadata.setObjectName("Muted")
        metadata_layout.addWidget(self.metadata, 1)
        header_layout.addWidget(self.metadata_widget)
        self.rules = QLabel()
        self.rules.setTextFormat(Qt.TextFormat.PlainText)
        self.rules.setWordWrap(True)
        self.rules.setMinimumWidth(0)
        self.rules.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.rules.setObjectName("Muted")
        header_layout.addWidget(self.rules)
        self.root_layout.addWidget(self.header_card)

        self.notice = QLabel(
            "自主下载会忽略自动下载开关和关键词筛选，但只处理你选择的这一条；"
            "BT 在下载阶段仍可能上传数据。"
        )
        self.notice.setTextFormat(Qt.TextFormat.PlainText)
        self.notice.setWordWrap(True)
        self.notice.setObjectName("Muted")
        self.root_layout.addWidget(self.notice)

        self.toolbar_widget = QWidget()
        self.toolbar = QGridLayout(self.toolbar_widget)
        self.toolbar.setContentsMargins(0, 0, 0, 0)
        self.toolbar.setHorizontalSpacing(9)
        self.toolbar.setVerticalSpacing(8)
        self.filter_combo = QComboBox()
        self.filter_combo.addItem("全部条目", "all")
        self.filter_combo.addItem("可手动下载", "undownloaded")
        self.filter_combo.addItem("下载中", "active")
        self.filter_combo.addItem("已完成", "completed")
        self.filter_combo.addItem("规则未匹配", "excluded")
        self.filter_combo.currentIndexChanged.connect(self._apply_filter)
        self.toolbar.addWidget(self.filter_combo, 0, 0)
        self.details_button = QPushButton("显示条目详情")
        self.details_button.setProperty("flat", True)
        self.details_button.clicked.connect(self._toggle_details)
        self.toolbar.addWidget(self.details_button, 0, 1)
        self.toolbar.setColumnStretch(2, 1)
        self.visible_count = QLabel("0 条")
        self.visible_count.setTextFormat(Qt.TextFormat.PlainText)
        self.visible_count.setObjectName("Muted")
        self.toolbar.addWidget(self.visible_count, 0, 3)
        self.search_edit = QLineEdit()
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setPlaceholderText("搜索标题、集数或简介…")
        self.search_edit.setMinimumWidth(180)
        self.search_edit.setMaximumWidth(320)
        self.search_edit.textChanged.connect(self._apply_filter)
        self.toolbar.addWidget(self.search_edit, 0, 4)
        self.root_layout.addWidget(self.toolbar_widget)

        self.content_stack = QStackedWidget()
        self.content_stack.setMinimumHeight(0)
        self.content_stack.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Ignored,
        )
        self.table_container = QWidget()
        table_layout = QVBoxLayout(self.table_container)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(12)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["集数", "条目标题", "发布时间", "类型", "状态", "操作"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(
            max(54, self.fontMetrics().height() * 2 + 20)
        )
        table_header = self.table.horizontalHeader()
        table_header.setMinimumSectionSize(64)
        table_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        table_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        table_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        table_header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        table_header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 76)
        self.table.setColumnWidth(2, 144)
        self.table.setColumnWidth(3, 72)
        self.table.setColumnWidth(4, 88)
        self.table.setColumnWidth(5, 128)
        self.table.currentCellChanged.connect(self._selection_changed)
        self.table.cellClicked.connect(lambda _row, _column: self._set_details_expanded(True))

        self.details_card = QFrame()
        self.details_card.setObjectName("DetailCard")
        self.details_card.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        details_layout = QVBoxLayout(self.details_card)
        details_layout.setContentsMargins(16, 13, 16, 14)
        details_layout.setSpacing(7)
        self.detail_title = ElidedLabel("选择一个条目查看详细内容")
        self.detail_title.setObjectName("SectionTitle")
        self.detail_title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        details_layout.addWidget(self.detail_title)
        self.detail_description = QPlainTextEdit()
        self.detail_description.setReadOnly(True)
        self.detail_description.setMaximumHeight(92)
        self.detail_description.setPlaceholderText("该条目没有简介")
        details_layout.addWidget(self.detail_description)
        source_grid = QGridLayout()
        source_grid.setContentsMargins(0, 0, 0, 0)
        source_grid.setHorizontalSpacing(10)
        source_grid.setVerticalSpacing(6)
        source_grid.addWidget(QLabel("条目页面"), 0, 0)
        self.article_url = QLineEdit()
        self.article_url.setReadOnly(True)
        self.article_url.setPlaceholderText("RSS 未提供条目页面")
        source_grid.addWidget(self.article_url, 0, 1)
        source_grid.addWidget(QLabel("下载地址"), 1, 0)
        self.download_url = QLineEdit()
        self.download_url.setReadOnly(True)
        self.download_url.setPlaceholderText("没有可识别下载地址")
        source_grid.addWidget(self.download_url, 1, 1)
        source_grid.setColumnStretch(1, 1)
        details_layout.addLayout(source_grid)
        self.details_scroll = QScrollArea()
        self.details_scroll.setWidgetResizable(True)
        self.details_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.details_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.details_scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Ignored,
        )
        self.details_scroll.setWidget(self.details_card)
        self.content_splitter = QSplitter(Qt.Orientation.Vertical)
        self.content_splitter.setChildrenCollapsible(True)
        self.content_splitter.addWidget(self.table)
        self.content_splitter.addWidget(self.details_scroll)
        self.content_splitter.setStretchFactor(0, 4)
        self.content_splitter.setStretchFactor(1, 1)
        self._details_expanded = False
        self.content_splitter.setSizes([480, 0])
        self.content_splitter.splitterMoved.connect(self._splitter_moved)
        table_layout.addWidget(self.content_splitter, 1)
        self.content_stack.addWidget(self.table_container)

        empty_card = QFrame()
        empty_card.setObjectName("Card")
        empty_layout = QVBoxLayout(empty_card)
        self.empty = EmptyState(
            "尚未记录订阅内容",
            "点击“刷新此订阅”读取 RSS；首次刷新默认只建立安全基线，不会批量下载历史条目。",
            "刷新此订阅",
            "rss",
        )
        self.empty.action_clicked.connect(self._request_refresh)
        empty_layout.addWidget(self.empty)
        self.content_stack.addWidget(empty_card)
        self.filter_empty_card = QFrame()
        self.filter_empty_card.setObjectName("Card")
        filter_empty_layout = QVBoxLayout(self.filter_empty_card)
        self.filter_empty = EmptyState(
            "没有符合条件的条目",
            "换一个搜索词或筛选条件，即可重新查看订阅内容。",
            icon_name="search",
        )
        filter_empty_layout.addWidget(self.filter_empty)
        self.content_stack.addWidget(self.filter_empty_card)
        self.root_layout.addWidget(self.content_stack, 1)

        self._detail_overlay: QLabel | None = None
        self._detail_animation: QPropertyAnimation | None = None
        self._toolbar_stacked = True
        self.toolbar.addWidget(self.search_edit, 1, 0, 1, 5)
        self.search_edit.setMaximumWidth(16777215)

        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(350)
        self._reload_timer.timeout.connect(self.reload)
        self._connect_controller_signals()
        self.set_theme("light")

    @property
    def subscription_id(self) -> Any:
        return self._subscription.get("id")

    @property
    def subscription_name(self) -> str:
        return str(self._subscription.get("name") or "订阅详情")[:500]

    def set_controller(self, controller: object | None) -> None:
        self._disconnect_controller_signals()
        self.controller = controller
        self._connect_controller_signals()

    def set_subscription(
        self,
        subscription: Mapping[str, Any],
        *,
        reload_items: bool = True,
    ) -> None:
        changed_subscription = self.subscription_id != subscription.get("id")
        self._subscription = dict(subscription)
        if changed_subscription:
            self._set_details_expanded(False, animate=False)
        self._update_header()
        self._update_refresh_button()
        self._apply_current_responsive_layout()
        QTimer.singleShot(0, self._apply_current_responsive_layout)
        if reload_items:
            self.reload()

    def _update_header(self) -> None:
        name = self.subscription_name
        feed_url = str(
            self._subscription.get("rss_url") or self._subscription.get("feed_url") or "—"
        )[:2000]
        count = str(self._subscription.get("episode_count", 0))[:40]
        last_update = str(self._subscription.get("last_update") or "尚未刷新")[:100]
        path = str(
            self._subscription.get("resolved_save_path")
            or self._subscription.get("save_path")
            or "使用全局下载目录"
        )[:4000]
        self.header.title.setText(name)
        self.header.subtitle.setText(feed_url)
        self.header.subtitle.setToolTip(html.escape(feed_url))
        self.count_metadata.setText(f"已记录 {count} 条")
        self.refresh_metadata.setText(f"上次刷新 {last_update}")
        self.metadata.setText(f"保存到 {path}")
        include_text, include_full = _keyword_summary(
            self._subscription.get("include_keywords"),
            "不限",
        )
        exclude_text, exclude_full = _keyword_summary(
            self._subscription.get("exclude_keywords"),
            "无",
        )
        rules_text = f"包含：{include_text}    排除：{exclude_text}"
        self.rules.setText(rules_text)
        self.header_card.setToolTip(
            html.escape(
                f"已记录 {count} 条\n上次刷新 {last_update}\n保存到 {path}\n"
                f"包含：{include_full}\n排除：{exclude_full}"
            )
        )

    def reload(self) -> None:
        if self.subscription_id is None or not self.isVisible():
            return
        selected_id = self._selected_item_id()
        scroll_value = self.table.verticalScrollBar().value()
        try:
            result = (
                controller_call(
                    self.controller,
                    "list_subscription_items",
                    self.subscription_id,
                    300,
                    default=[],
                )
                or []
            )
            self.set_items(result, selected_id=selected_id, scroll_value=scroll_value)
        except Exception as exc:
            self.error.emit(f"加载订阅内容失败：{exc}")

    def set_items(
        self,
        items: Sequence[Any],
        *,
        selected_id: Any = None,
        scroll_value: int = 0,
    ) -> None:
        details_scroll_value = self.details_scroll.verticalScrollBar().value()
        self._items = []
        for source in items:
            item = as_mapping(source)
            title = str(item.get("title") or "未命名条目")[:2000]
            episode = str(item.get("episode") or "—")[:100]
            description = _plain_description(item.get("description"))
            item["_display_title"] = title
            item["_display_episode"] = episode
            item["_plain_description"] = description
            item["_search_blob"] = f"{title} {episode} {description}".casefold()
            self._items.append(item)
        self.table.setRowCount(0)
        c = colors(self._theme)
        selected_row = -1
        for item in self._items:
            row = self.table.rowCount()
            self.table.insertRow(row)
            item_id = item.get("id")
            episode = str(item["_display_episode"])
            episode_item = QTableWidgetItem(episode)
            episode_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            episode_item.setData(Qt.ItemDataRole.UserRole, item_id)
            self.table.setItem(row, 0, episode_item)

            title = str(item["_display_title"])
            title_item = QTableWidgetItem(title)
            description = str(item["_plain_description"])
            detail_tooltip = title if not description else f"{title}\n\n{description}"
            title_item.setToolTip(html.escape(detail_tooltip))
            self.table.setItem(row, 1, title_item)
            published = str(item.get("published_at") or "—")[:500]
            published_item = QTableWidgetItem(published)
            published_item.setToolTip(html.escape(published))
            self.table.setItem(row, 2, published_item)
            kind_item = QTableWidgetItem(_kind_text(item.get("download_kind")))
            kind_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 3, kind_item)

            status, tone, action_text, action_kind = self._presentation(item)
            badge = BadgeLabel(status, tone)
            badge.set_theme(self._theme)
            if not bool(item.get("matches_rules", True)):
                badge.setToolTip("该条目未匹配自动下载规则，仍可手动下载。")
            status_cell = QWidget()
            status_layout = QHBoxLayout(status_cell)
            status_layout.setContentsMargins(4, 0, 4, 0)
            status_layout.addWidget(badge)
            self.table.setCellWidget(row, 4, status_cell)

            action = QPushButton(action_text)
            action.setMinimumWidth(100)
            pending_key = (self.subscription_id, item_id)
            if pending_key in self._download_workers:
                action.setText("处理中…")
                action.setEnabled(False)
            elif action_kind == "download":
                action.setProperty("primary", True)
                action.setIcon(icon("download", "#FFFFFF", 16))
                action.clicked.connect(
                    lambda _checked=False, current=item: self._download_item(current)
                )
            elif action_kind == "show":
                action.setIcon(icon("arrow", c.text_muted, 15))
                action.clicked.connect(
                    lambda _checked=False, current=item: self._show_download(current)
                )
            else:
                action.setEnabled(False)
                action.setToolTip("RSS 条目没有 enclosure、种子或磁力链接。")
                action.setIcon(icon("download", c.text_muted, 16))
            action.setProperty("expandedText", action.text())
            action.setProperty("expandedToolTip", action.toolTip())
            action_cell = QWidget()
            action_layout = QHBoxLayout(action_cell)
            action_layout.setContentsMargins(4, 0, 4, 0)
            action_layout.addWidget(action)
            self.table.setCellWidget(row, 5, action_cell)
            if selected_id is not None and item_id == selected_id:
                selected_row = row

        self.content_stack.setCurrentIndex(0 if self._items else 1)
        self.empty.set_theme(self._theme)
        self._update_table_columns(self.width())
        self._apply_filter()
        if self._items:
            if selected_row < 0 or self.table.isRowHidden(selected_row):
                selected_row = self._first_visible_row()
            if selected_row >= 0:
                self.table.selectRow(selected_row)
                self._show_item_details(selected_row)
            self.table.verticalScrollBar().setValue(scroll_value)
            self.details_scroll.verticalScrollBar().setValue(
                min(
                    details_scroll_value,
                    self.details_scroll.verticalScrollBar().maximum(),
                )
            )
        else:
            self._show_item_details(-1)

    @staticmethod
    def _presentation(item: Mapping[str, Any]) -> tuple[str, str, str, str]:
        status = str(item.get("task_status") or "")[:50].lower()
        if status:
            fallback = f"{status[:11]}…" if len(status) > 12 else status
            return _STATUS_PRESENTATION.get(
                status,
                (fallback, "neutral", "查看任务", "show"),
            )
        if item.get("download_url"):
            return "可下载", "info", "下载", "download"
        return "无资源", "neutral", "无资源", "disabled"

    def _apply_filter(self, _value: Any = None) -> None:
        query = self.search_edit.text().strip().casefold()
        mode = str(self.filter_combo.currentData() or "all")
        visible = 0
        for row, item in enumerate(self._items):
            haystack = str(item.get("_search_blob") or "")
            status = str(item.get("task_status") or "").lower()
            matches_mode = (
                mode == "all"
                or (mode == "undownloaded" and bool(item.get("download_url")) and not status)
                or (mode == "active" and status in {"queued", "downloading", "paused"})
                or (mode == "completed" and status == "completed")
                or (mode == "excluded" and not bool(item.get("matches_rules", True)))
            )
            hidden = bool(query and query not in haystack) or not matches_mode
            self.table.setRowHidden(row, hidden)
            if not hidden:
                visible += 1
        self.visible_count.setText(f"显示 {visible} / {len(self._items)} 条")
        if self._items:
            self.content_stack.setCurrentWidget(
                self.table_container if visible else self.filter_empty_card
            )
        current = self.table.currentRow()
        if current < 0 or self.table.isRowHidden(current):
            first = self._first_visible_row()
            if first >= 0:
                self.table.selectRow(first)
                self._show_item_details(first)
            else:
                self.table.clearSelection()
                self.table.setCurrentCell(-1, -1)
                self._show_item_details(-1)

    def _first_visible_row(self) -> int:
        return next(
            (row for row in range(self.table.rowCount()) if not self.table.isRowHidden(row)),
            -1,
        )

    def _selection_changed(
        self,
        current_row: int,
        _current_column: int,
        _previous_row: int,
        _previous_column: int,
    ) -> None:
        self._show_item_details(current_row)

    def _toggle_details(self) -> None:
        self._set_details_expanded(not self._details_expanded)

    def _set_details_expanded(self, expanded: bool, *, animate: bool = True) -> None:
        if expanded == self._details_expanded:
            return
        snapshot = None
        if (
            animate
            and not reduced_motion_requested()
            and self.content_splitter.isVisible()
            and self.content_splitter.width() > 0
            and self.content_splitter.height() > 0
        ):
            snapshot = self.content_splitter.grab()
        self._details_expanded = expanded
        self._apply_detail_panes()
        if snapshot is not None and not snapshot.isNull():
            self._fade_splitter_snapshot(snapshot)

    def _apply_detail_panes(self) -> None:
        available = max(1, self.content_splitter.height())
        if not self._details_expanded:
            self.table.setVisible(True)
            self.content_splitter.setSizes([available, 0])
            self.details_button.setText("显示条目详情")
            return

        exclusive_detail = self.height() < 500
        self.table.setVisible(not exclusive_detail)
        if exclusive_detail:
            self.content_splitter.setSizes([0, available])
        else:
            minimum_table = max(76, min(130, available // 2))
            needed = max(120, self.details_card.sizeHint().height())
            detail_height = min(needed, max(80, available - minimum_table))
            self.content_splitter.setSizes([available - detail_height, detail_height])
        self.details_button.setText("收起条目详情")

    def _fade_splitter_snapshot(self, snapshot: Any) -> None:
        self._cleanup_detail_animation()
        overlay = QLabel(self.table_container)
        overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        overlay.setPixmap(snapshot)
        overlay.setScaledContents(True)
        overlay.setGeometry(self.content_splitter.geometry())
        effect = QGraphicsOpacityEffect(overlay)
        overlay.setGraphicsEffect(effect)
        overlay.show()
        overlay.raise_()
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setStartValue(1.0)
        animation.setEndValue(0.0)
        animation.setDuration(COLLAPSE_DURATION_MS)
        animation.setEasingCurve(ease_out_curve())
        animation.finished.connect(self._cleanup_detail_animation)
        self._detail_overlay = overlay
        self._detail_animation = animation
        animation.start()

    def _cleanup_detail_animation(self) -> None:
        animation = self._detail_animation
        self._detail_animation = None
        if animation is not None:
            animation.stop()
            animation.deleteLater()
        overlay = self._detail_overlay
        self._detail_overlay = None
        if overlay is not None:
            overlay.deleteLater()

    def _splitter_moved(self, _position: int, _index: int) -> None:
        sizes = self.content_splitter.sizes()
        expanded = len(sizes) > 1 and sizes[1] > 0
        self._details_expanded = expanded
        self.details_button.setText("收起条目详情" if expanded else "显示条目详情")

    def _show_item_details(self, row: int) -> None:
        if not 0 <= row < len(self._items) or self.table.isRowHidden(row):
            title = (
                "没有符合当前筛选的条目"
                if self._items and self._first_visible_row() < 0
                else "选择一个条目查看详细内容"
            )
            self.detail_title.setText(title)
            self.detail_description.clear()
            self.article_url.clear()
            self.download_url.clear()
            return
        item = self._items[row]
        self.detail_title.setText(str(item["_display_title"]))
        self.detail_description.setPlainText(str(item["_plain_description"]))
        article = str(item.get("link") or "")
        download = str(item.get("download_url") or "")
        self.article_url.setText(article)
        self.article_url.setToolTip(html.escape(article))
        self.download_url.setText(download)
        self.download_url.setToolTip(html.escape(download))

    def _selected_item_id(self) -> Any:
        row = self.table.currentRow()
        if not 0 <= row < len(self._items):
            return None
        return self._items[row].get("id")

    def _download_item(self, item: Mapping[str, Any]) -> None:
        subscription_id = self.subscription_id
        item_id = item.get("id")
        key = (subscription_id, item_id)
        if subscription_id is None or item_id is None or key in self._download_workers:
            return

        worker = FunctionWorker(
            lambda: controller_call(
                self.controller,
                "download_feed_item",
                subscription_id,
                item_id,
            )
        )
        self._download_workers[key] = worker
        worker.signals.succeeded.connect(
            lambda _result, current=key: self._download_finished(current)
        )
        worker.signals.failed.connect(
            lambda detail, current=key: self._download_failed(current, detail)
        )
        self._rerender_preserving_position()
        self.message.emit("正在加入下载队列…")
        QThreadPool.globalInstance().start(worker)

    def _download_finished(self, key: tuple[Any, Any]) -> None:
        self._download_workers.pop(key, None)
        self._reload_timer.stop()
        self.message.emit("条目已加入或恢复下载")
        self.changed.emit()

    def _download_failed(self, key: tuple[Any, Any], detail: str) -> None:
        self._download_workers.pop(key, None)
        self._rerender_preserving_position()
        self.error.emit(f"无法加入下载：{detail}")

    def _rerender_preserving_position(self) -> None:
        if not self._items:
            return
        selected_id = self._selected_item_id()
        scroll_value = self.table.verticalScrollBar().value()
        self.set_items(
            self._items,
            selected_id=selected_id,
            scroll_value=scroll_value,
        )

    def _show_download(self, item: Mapping[str, Any]) -> None:
        task_id = item.get("task_id")
        if task_id is not None:
            self.show_download_requested.emit(task_id)

    def _request_edit(self) -> None:
        if self._subscription:
            self.edit_requested.emit(dict(self._subscription))

    def _request_refresh(self) -> None:
        if self.subscription_id is not None:
            self.refresh_requested.emit(self.subscription_id)

    def _toggle_subscription_info(self) -> None:
        self._secondary_header_forced = not self._secondary_header_forced
        self._apply_current_responsive_layout()

    def set_refreshing(self, subscription_id: Any = None) -> None:
        self._refreshing_subscription_id = subscription_id
        self._update_refresh_button()

    def _update_refresh_button(self) -> None:
        if self._refreshing_subscription_id is None:
            self.refresh_button.setEnabled(True)
            text = "刷新此订阅"
        elif self.subscription_id == self._refreshing_subscription_id:
            self.refresh_button.setEnabled(False)
            text = "正在刷新…"
        else:
            self.refresh_button.setEnabled(False)
            text = "其他订阅刷新中…"
        self.refresh_button.setProperty("expandedText", text)
        self._update_header_action_mode(self.width() < 520)

    def _open_folder(self) -> None:
        path = str(
            self._subscription.get("resolved_save_path")
            or self._subscription.get("save_path")
            or ""
        )
        if not path:
            self.error.emit("该订阅尚未确定保存目录")
            return
        try:
            controller_call(self.controller, "open_folder", path)
        except Exception as exc:
            self.error.emit(f"无法打开保存目录：{exc}")

    def schedule_reload(self, *_args: Any) -> None:
        if self.isVisible() and self.subscription_id is not None:
            self._reload_timer.start()

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self._apply_responsive_layout(event.size().width(), event.size().height())

    def showEvent(self, event: Any) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._apply_current_responsive_layout)

    def _apply_current_responsive_layout(self) -> None:
        self._apply_responsive_layout(self.width(), self.height())

    def _apply_responsive_layout(self, width: int, height: int) -> None:
        compact = width < 720
        horizontal_margin = 18 if compact else 30
        self.root_layout.setContentsMargins(horizontal_margin, 14, horizontal_margin, 18)
        self.notice.setVisible(height >= 600)
        compact_empty = height < 520
        self.empty.set_compact(compact_empty)
        self.filter_empty.set_compact(compact_empty)
        compact_header = height < 520
        self.info_button.setVisible(compact_header)
        show_secondary_header = not compact_header or self._secondary_header_forced
        info_text = "收起信息" if show_secondary_header and compact_header else "订阅信息"
        self.info_button.setProperty("expandedText", info_text)
        self._update_header_action_mode(width < 520)
        self.header.subtitle.setVisible(show_secondary_header)
        self.metadata_widget.setVisible(show_secondary_header)
        self.rules.setVisible(show_secondary_header)

        stacked_header = width < 600
        self.header_top.setDirection(
            QBoxLayout.Direction.TopToBottom if stacked_header else QBoxLayout.Direction.LeftToRight
        )
        self.header_top.setAlignment(
            self.header_actions,
            Qt.AlignmentFlag.AlignLeft if stacked_header else Qt.AlignmentFlag.AlignVCenter,
        )

        stacked_toolbar = width < 590
        if stacked_toolbar != self._toolbar_stacked:
            self._toolbar_stacked = stacked_toolbar
            if stacked_toolbar:
                self.toolbar.addWidget(self.search_edit, 1, 0, 1, 5)
                self.search_edit.setMaximumWidth(16777215)
            else:
                self.toolbar.addWidget(self.search_edit, 0, 4)
                self.search_edit.setMaximumWidth(320)

        self._update_table_columns(width)
        if self._details_expanded:
            self._cleanup_detail_animation()
            self._apply_detail_panes()

    def _update_header_action_mode(self, compact: bool) -> None:
        self._header_actions_compact = compact
        for button in (
            self.edit_button,
            self.folder_button,
            self.info_button,
            self.refresh_button,
        ):
            full_text = str(button.property("expandedText") or "")
            if compact:
                button.setText("")
                button.setFixedSize(38, 34)
                if not button.toolTip():
                    button.setToolTip(full_text)
            else:
                button.setMinimumSize(0, 0)
                button.setMaximumSize(16777215, 16777215)
                button.setText(full_text)

    def _update_table_columns(self, width: int) -> None:
        self.table.setColumnHidden(2, width < 760)
        self.table.setColumnHidden(3, width < 650)
        compact_actions = width < 680
        self.table.setColumnWidth(5, 64 if compact_actions else 128)
        c = colors(self._theme)
        for row in range(self.table.rowCount()):
            cell = self.table.cellWidget(row, 5)
            action = cell.findChild(QPushButton) if cell is not None else None
            if action is None:
                continue
            full_text = str(action.property("expandedText") or "")
            full_tooltip = str(action.property("expandedToolTip") or "")
            if compact_actions:
                if action.icon().isNull():
                    action.setIcon(icon("refresh", c.text_muted, 16))
                action.setText("")
                action.setToolTip(full_tooltip or full_text)
                action.setFixedSize(38, 34)
            else:
                action.setMinimumSize(100, 0)
                action.setMaximumSize(16777215, 16777215)
                action.setText(full_text)
                action.setToolTip(full_tooltip)

    def _connect_controller_signals(self) -> None:
        for name in ("downloads_changed",):
            signal = getattr(self.controller, name, None)
            connector = getattr(signal, "connect", None)
            if callable(connector):
                with suppress(TypeError, RuntimeError):
                    connector(self.schedule_reload)
                    self._connected_signals.append(signal)

    def _disconnect_controller_signals(self) -> None:
        for signal in self._connected_signals:
            with suppress(TypeError, RuntimeError):
                signal.disconnect(self.schedule_reload)
        self._connected_signals.clear()

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        c = colors(theme)
        self.back_button.setIcon(icon("back", c.text_muted, 17))
        self.edit_button.setIcon(icon("edit", c.text_muted, 16))
        self.folder_button.setIcon(icon("folder", c.text_muted, 16))
        self.info_button.setIcon(icon("search", c.text_muted, 16))
        self.refresh_button.setIcon(icon("refresh", "#FFFFFF", 16))
        self.empty.set_theme(theme)
        self.filter_empty.set_theme(theme)
        if self._items:
            selected_id = self._selected_item_id()
            scroll_value = self.table.verticalScrollBar().value()
            self.set_items(
                self._items,
                selected_id=selected_id,
                scroll_value=scroll_value,
            )


__all__ = ["SubscriptionDetailView"]
