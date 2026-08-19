"""Dashboard page."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .controller import controller_call
from .data import as_mapping, progress_percent
from .widgets import BadgeLabel, ElidedLabel, EmptyState, PageHeader, StatCard

STATUS_LABELS = {
    "downloading": ("下载中", "info"),
    "paused": ("已暂停", "warning"),
    "completed": ("已完成", "success"),
    "failed": ("失败", "danger"),
    "queued": ("等待中", "neutral"),
    "checking": ("校验中", "accent"),
}


def _dict(item: Any) -> dict[str, Any]:
    return as_mapping(item)


class OverviewPage(QWidget):
    """At-a-glance statistics and recently changed downloads."""

    error = Signal(str)

    def __init__(self, controller: object | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._theme = "light"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 26, 30, 26)
        layout.setSpacing(20)
        layout.addWidget(PageHeader("概览", "订阅状态、下载速度与近期任务一目了然"))

        stats = QGridLayout()
        stats.setHorizontalSpacing(12)
        stats.setVerticalSpacing(12)
        self.stats_layout = stats
        self.cards = {
            "subscription_count": StatCard("订阅番剧", "—", "rss", "accent"),
            "active_downloads": StatCard("正在下载", "—", "download", "info"),
            "download_speed": StatCard("当前速度", "—", "refresh", "warning"),
            "completed_downloads": StatCard("已完成", "—", "check", "success"),
        }
        for index, card in enumerate(self.cards.values()):
            stats.addWidget(card, 0, index)
            stats.setColumnStretch(index, 1)
        layout.addLayout(stats)

        section = QHBoxLayout()
        recent_title = QLabel("最近任务")
        recent_title.setObjectName("SectionTitle")
        section.addWidget(recent_title)
        section.addStretch()
        self.next_refresh = ElidedLabel("下次刷新：—")
        self.next_refresh.setMaximumWidth(360)
        self.next_refresh.setObjectName("Muted")
        section.addWidget(self.next_refresh)
        layout.addLayout(section)

        self.content = QStackedWidget()
        self.content.setMinimumHeight(0)
        self.content.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Ignored,
        )
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["任务", "状态", "进度", "剩余 / 完成时间"])
        self.table.setAlternatingRowColors(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(
            max(54, self.fontMetrics().height() * 2 + 20)
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(1, 88)
        self.table.setColumnWidth(2, 76)
        self.table.setColumnWidth(3, 160)
        self.table.cellDoubleClicked.connect(self._open_task_folder)
        self.empty = EmptyState(
            "还没有下载任务",
            "添加 RSS 订阅后，匹配到的新剧集会出现在这里。",
            icon_name="download",
        )
        self.empty_card = QFrame()
        self.empty_card.setObjectName("Card")
        empty_layout = QVBoxLayout(self.empty_card)
        empty_layout.addWidget(self.empty)
        self.content.addWidget(self.table)
        self.content.addWidget(self.empty_card)
        layout.addWidget(self.content, 1)

    def set_controller(self, controller: object | None) -> None:
        self.controller = controller

    def reload(self) -> None:
        try:
            snapshot = controller_call(self.controller, "dashboard_snapshot", default=None)
            if snapshot is None:
                subscriptions = (
                    controller_call(self.controller, "list_subscriptions", default=[]) or []
                )
                tasks = controller_call(self.controller, "list_downloads", None, default=[]) or []
                normalized = [_dict(item) for item in tasks]
                snapshot = {
                    "subscription_count": len(subscriptions),
                    "active_downloads": sum(
                        item.get("status") == "downloading" for item in normalized
                    ),
                    "completed_downloads": sum(
                        item.get("status") == "completed" for item in normalized
                    ),
                    "download_speed": "—",
                    "next_refresh": "按计划自动检查",
                    "recent_tasks": list(reversed(normalized[-6:])),
                }
            elif not isinstance(snapshot, Mapping):
                snapshot = as_mapping(snapshot)
            self.set_snapshot(snapshot)
        except Exception as exc:  # Backend errors should not take down the UI.
            self.error.emit(f"加载概览失败：{exc}")

    def set_snapshot(self, snapshot: Mapping[str, Any]) -> None:
        values = dict(snapshot)
        self.cards["subscription_count"].set_value(
            values.get("subscription_count", values.get("subscriptions", 0)), "启用中的订阅"
        )
        active = values.get("active_downloads", values.get("downloading", 0))
        self.cards["active_downloads"].set_value(active, "并发任务")
        self.cards["download_speed"].set_value(
            values.get("download_speed", values.get("speed", "0 B/s")), "总下载速度"
        )
        self.cards["completed_downloads"].set_value(
            values.get("completed_downloads", values.get("completed", 0)), "累计完成"
        )
        self.next_refresh.setText(f"下次刷新：{values.get('next_refresh', '等待计划')}")
        recent = values.get("recent_tasks", values.get("recent_downloads", []))
        self.set_recent_tasks(
            recent if isinstance(recent, Sequence) and not isinstance(recent, str) else []
        )

    def set_recent_tasks(self, tasks: Sequence[Any]) -> None:
        scroll_value = self.table.verticalScrollBar().value()
        self.table.setRowCount(0)
        for task in tasks:
            item = _dict(task)
            row = self.table.rowCount()
            self.table.insertRow(row)
            title = str(item.get("title") or item.get("name") or "未命名任务")[:2000]
            anime = str(item.get("anime") or "")[:500]
            title_item = QTableWidgetItem(title)
            tooltip = title
            if anime and anime not in title:
                tooltip = f"{title}\n番剧：{anime}"
            title_item.setToolTip(tooltip)
            title_item.setData(Qt.ItemDataRole.UserRole, item)
            self.table.setItem(row, 0, title_item)

            status = str(item.get("status", "queued"))[:50].lower()
            fallback = f"{status[:11]}…" if len(status) > 12 else status or "未知"
            label_text, tone = STATUS_LABELS.get(status, (fallback, "neutral"))
            badge = BadgeLabel(label_text, tone)
            badge.set_theme(self._theme)
            cell = QWidget()
            cell_layout = QHBoxLayout(cell)
            cell_layout.setContentsMargins(7, 0, 7, 0)
            cell_layout.addWidget(badge)
            self.table.setCellWidget(row, 1, cell)

            self.table.setItem(
                row, 2, QTableWidgetItem(f"{progress_percent(item.get('progress', 0))}%")
            )
            when = str(
                item.get("eta") or item.get("completed_at") or item.get("updated_at") or "—"
            )[:500]
            when_item = QTableWidgetItem(when)
            when_item.setToolTip(when)
            self.table.setItem(row, 3, when_item)
        self.content.setCurrentWidget(self.table if tasks else self.empty_card)
        QTimer.singleShot(
            0,
            lambda value=scroll_value: self.table.verticalScrollBar().setValue(
                min(value, self.table.verticalScrollBar().maximum())
            ),
        )

    def _open_task_folder(self, row: int, _column: int) -> None:
        item = self.table.item(row, 0)
        task = item.data(Qt.ItemDataRole.UserRole) if item else {}
        path = task.get("path") if isinstance(task, Mapping) else None
        if path:
            try:
                controller_call(self.controller, "open_folder", str(path))
            except Exception as exc:
                self.error.emit(f"无法打开保存目录：{exc}")

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        for card in self.cards.values():
            card.set_theme(theme)
        self.empty.set_theme(theme)
        for row in range(self.table.rowCount()):
            cell = self.table.cellWidget(row, 1)
            if cell:
                for badge in cell.findChildren(BadgeLabel):
                    badge.set_theme(theme)

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self.empty.set_compact(event.size().height() < 520)
        self._arrange_stat_cards()

    def _arrange_stat_cards(self) -> None:
        compact = self.height() < 560
        columns = 4 if compact or self.width() >= 980 else 2
        cards = list(self.cards.values())
        for card in cards:
            card.set_compact(compact)
            self.stats_layout.removeWidget(card)
        for column in range(4):
            self.stats_layout.setColumnStretch(column, 0)
        for index, card in enumerate(cards):
            row, column = divmod(index, columns)
            self.stats_layout.addWidget(card, row, column)
            self.stats_layout.setColumnStretch(column, 1)
