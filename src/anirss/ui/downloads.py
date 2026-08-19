"""Built-in downloader task page."""

from __future__ import annotations

import html
from collections.abc import Sequence
from typing import Any

from PySide6.QtCore import Qt, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .controller import controller_call
from .data import as_mapping, human_bytes, progress_percent
from .dialogs import RemoveDownloadDialog
from .resources import icon
from .theme import colors
from .widgets import BadgeLabel, ElidedLabel, EmptyState, PageHeader
from .widgets import JellyButton as QPushButton
from .worker import FunctionWorker

STATUS_LABELS = {
    "downloading": ("下载中", "info"),
    "paused": ("已暂停", "warning"),
    "completed": ("已完成", "success"),
    "failed": ("失败", "danger"),
    "queued": ("等待中", "neutral"),
    "checking": ("校验中", "accent"),
    "seeding": ("做种中", "accent"),
    "cancelled": ("已取消", "neutral"),
}


def _dict(item: Any) -> dict[str, Any]:
    return as_mapping(item)


class DownloadsPage(QWidget):
    """Filter and control downloads managed by the embedded engine."""

    changed = Signal()
    error = Signal(str)
    message = Signal(str)

    def __init__(self, controller: object | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._theme = "light"
        self._all_items: list[dict[str, Any]] = []
        self._visible_items: list[dict[str, Any]] = []
        self._remove_workers: set[FunctionWorker] = set()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 26, 30, 26)
        layout.setSpacing(18)
        layout.addWidget(PageHeader("下载", "内置下载器会自动接管匹配的种子与磁力链接"))

        toolbar = QHBoxLayout()
        toolbar.setSpacing(9)
        toolbar.addWidget(QLabel("状态"))
        self.filter_combo = QComboBox()
        self.filter_combo.addItem("全部任务", None)
        self.filter_combo.addItem("下载中", "downloading")
        self.filter_combo.addItem("等待中", "queued")
        self.filter_combo.addItem("已暂停", "paused")
        self.filter_combo.addItem("已完成", "completed")
        self.filter_combo.addItem("失败", "failed")
        self.filter_combo.setMinimumWidth(125)
        self.filter_combo.currentIndexChanged.connect(self.reload)
        toolbar.addWidget(self.filter_combo)
        toolbar.addStretch()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索任务或番剧…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMinimumWidth(180)
        self.search_edit.setMaximumWidth(360)
        self.search_edit.textChanged.connect(self._apply_search)
        toolbar.addWidget(self.search_edit)
        layout.addLayout(toolbar)

        self.stack = QStackedWidget()
        self.stack.setMinimumHeight(0)
        self.stack.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Ignored,
        )
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["任务", "进度", "大小", "速度", "状态", "操作"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(
            max(68, self.fontMetrics().height() * 3 + 16)
        )
        self.table.cellDoubleClicked.connect(self._open_folder)
        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(64)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(2, 94)
        self.table.setColumnWidth(3, 112)
        self.table.setColumnWidth(4, 88)
        self.table.setColumnWidth(5, 132)
        self.stack.addWidget(self.table)

        self.empty_card = QFrame()
        self.empty_card.setObjectName("Card")
        empty_layout = QVBoxLayout(self.empty_card)
        self.empty = EmptyState(
            "暂无下载任务",
            "匹配到新剧集后，下载进度和速度会显示在这里。",
            icon_name="download",
        )
        empty_layout.addWidget(self.empty)
        self.stack.addWidget(self.empty_card)
        layout.addWidget(self.stack, 1)

    def set_controller(self, controller: object | None) -> None:
        self.controller = controller

    def reload(self, _index: int | None = None, *, preserve_scroll: bool = True) -> None:
        status_filter = self.filter_combo.currentData()
        try:
            try:
                result = (
                    controller_call(self.controller, "list_downloads", status_filter, default=[])
                    or []
                )
            except TypeError:
                # Compatibility with controllers exposing list_downloads() only.
                result = controller_call(self.controller, "list_downloads", default=[]) or []
                if status_filter:
                    result = [item for item in result if _dict(item).get("status") == status_filter]
            self._all_items = [_dict(item) for item in result]
            self._apply_search(preserve_scroll=preserve_scroll)
        except Exception as exc:
            self.error.emit(f"加载下载任务失败：{exc}")

    def set_downloads(self, downloads: Sequence[Any]) -> None:
        self._all_items = [_dict(item) for item in downloads]
        self._apply_search()

    def focus_task(self, task_id: Any) -> None:
        """Show, select and scroll to a task opened from subscription details."""

        self.filter_combo.blockSignals(True)
        self.search_edit.blockSignals(True)
        try:
            self.filter_combo.setCurrentIndex(0)
            self.search_edit.clear()
        finally:
            self.filter_combo.blockSignals(False)
            self.search_edit.blockSignals(False)
        self.reload(preserve_scroll=False)
        for row, item in enumerate(self._visible_items):
            if item.get("id") == task_id:
                self.table.selectRow(row)
                table_item = self.table.item(row, 0)
                if table_item is not None:
                    self.table.scrollToItem(table_item)
                break

    def _apply_search(self, _text: str | None = None, *, preserve_scroll: bool = True) -> None:
        query = self.search_edit.text().strip().casefold()
        if query:
            self._visible_items = [
                item
                for item in self._all_items
                if query in str(item.get("title", ""))[:2000].casefold()
                or query in str(item.get("anime", ""))[:500].casefold()
            ]
        else:
            self._visible_items = list(self._all_items)
        self._render(preserve_scroll=preserve_scroll)

    def _render(self, *, preserve_scroll: bool = True) -> None:
        scroll_value = self.table.verticalScrollBar().value() if preserve_scroll else 0
        self.table.setRowCount(0)
        c = colors(self._theme)
        for item in self._visible_items:
            row = self.table.rowCount()
            self.table.insertRow(row)
            title = str(item.get("title") or item.get("name") or "未命名任务")[:2000]
            anime = str(item.get("anime") or item.get("series_name") or "")[:500]
            task_cell = QWidget()
            task_layout = QVBoxLayout(task_cell)
            task_layout.setContentsMargins(7, 7, 6, 7)
            task_layout.setSpacing(2)
            title_label = ElidedLabel(title)
            title_label.setStyleSheet("font-weight:650;")
            progress = progress_percent(item.get("progress", 0))
            meta_parts = [
                part
                for part in [anime, f"第 {item.get('episode')} 集" if item.get("episode") else ""]
                if part
            ]
            wide_meta = " · ".join(meta_parts) or "RSS 自动任务"
            speed = str(item.get("speed") or "—")[:100]
            compact_meta = f"{wide_meta} · {progress}% · {speed}"
            meta = ElidedLabel(wide_meta)
            meta.setObjectName("DownloadMeta")
            meta.setProperty("wideText", wide_meta)
            meta.setProperty("compactText", compact_meta)
            meta.setStyleSheet(f"color:{c.text_muted};font-size:11px;")
            task_layout.addWidget(title_label)
            task_layout.addWidget(meta)
            self.table.setCellWidget(row, 0, task_cell)
            data_item = QTableWidgetItem()
            data_item.setData(Qt.ItemDataRole.UserRole, item)
            self.table.setItem(row, 0, data_item)
            # Replacing an item does not replace the cell widget; it stores row data.

            progress_cell = QWidget()
            progress_layout = QVBoxLayout(progress_cell)
            progress_layout.setContentsMargins(7, 8, 7, 7)
            progress_layout.setSpacing(5)
            progress_line = QHBoxLayout()
            progress_label = ElidedLabel(f"{progress}%")
            progress_label.setStyleSheet("font-weight:650;")
            eta = ElidedLabel(str(item.get("eta") or "—"))
            eta.setMaximumWidth(110)
            eta.setStyleSheet(f"color:{c.text_muted};font-size:11px;")
            progress_line.addWidget(progress_label)
            progress_line.addStretch()
            progress_line.addWidget(eta)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(progress)
            bar.setTextVisible(False)
            progress_layout.addLayout(progress_line)
            progress_layout.addWidget(bar)
            self.table.setCellWidget(row, 1, progress_cell)

            total_size = item.get("size", item.get("total_bytes"))
            self.table.setItem(row, 2, QTableWidgetItem(human_bytes(total_size)))
            speed_text = str(item.get("speed") or "—")[:500]
            speed_item = QTableWidgetItem(speed_text)
            speed_item.setToolTip(html.escape(speed_text))
            self.table.setItem(row, 3, speed_item)

            status = str(item.get("status") or "queued")[:50].lower()
            fallback = f"{status[:11]}…" if len(status) > 12 else status or "未知"
            label_text, tone = STATUS_LABELS.get(status, (fallback, "neutral"))
            badge = BadgeLabel(label_text, tone)
            badge.set_theme(self._theme)
            status_cell = QWidget()
            status_layout = QHBoxLayout(status_cell)
            status_layout.setContentsMargins(5, 0, 5, 0)
            status_layout.addWidget(badge)
            self.table.setCellWidget(row, 4, status_cell)

            actions = QWidget()
            action_layout = QHBoxLayout(actions)
            action_layout.setContentsMargins(3, 0, 3, 0)
            action_layout.setSpacing(1)
            if status in {"downloading", "checking", "seeding"}:
                toggle = self._action_button("pause", "暂停任务", c.text_muted)
                toggle.clicked.connect(lambda _checked=False, r=row: self._pause(r))
            elif status in {"paused", "failed", "queued"}:
                toggle = self._action_button("play", "恢复任务", c.accent)
                toggle.clicked.connect(lambda _checked=False, r=row: self._resume(r))
            else:
                toggle = self._action_button("folder", "打开保存目录", c.text_muted)
                toggle.clicked.connect(lambda _checked=False, r=row: self._open_folder(r, 0))
            remove = self._action_button("delete", "移除任务", c.danger)
            remove.setProperty("danger", True)
            remove.clicked.connect(lambda _checked=False, r=row: self._remove(r))
            action_layout.addWidget(toggle)
            action_layout.addWidget(remove)
            self.table.setCellWidget(row, 5, actions)

        has_rows = bool(self._visible_items)
        filtered = bool(self._all_items) and (
            bool(self.search_edit.text().strip()) or self.filter_combo.currentData() is not None
        )
        if filtered and not has_rows:
            self.empty.set_content(
                "没有符合条件的任务",
                "换一个搜索词或状态筛选，即可重新查看下载任务。",
            )
        else:
            self.empty.set_content(
                "暂无下载任务",
                "匹配到新剧集后，下载进度和速度会显示在这里。",
            )
        self._update_responsive_columns(self.width())
        self.stack.setCurrentWidget(self.table if has_rows else self.empty_card)
        QTimer.singleShot(
            0,
            lambda value=scroll_value: self.table.verticalScrollBar().setValue(
                min(value, self.table.verticalScrollBar().maximum())
            ),
        )

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self.empty.set_compact(event.size().height() < 520)
        self._update_responsive_columns(event.size().width())

    def _update_responsive_columns(self, width: int) -> None:
        self.table.setColumnHidden(2, width < 820)
        self.table.setColumnHidden(3, width < 700)
        compact = width < 560
        self.table.setColumnHidden(1, compact)
        self.table.setColumnWidth(5, 96 if compact else 132)
        self.table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            if compact
            else Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.search_edit.setMinimumWidth(120 if compact else 180)
        for row in range(self.table.rowCount()):
            cell = self.table.cellWidget(row, 0)
            meta = cell.findChild(ElidedLabel, "DownloadMeta") if cell is not None else None
            if meta is not None:
                key = "compactText" if compact else "wideText"
                meta.setText(str(meta.property(key) or ""))

    def _action_button(self, name: str, tooltip: str, color: str) -> QPushButton:
        button = QPushButton()
        button.setProperty("flat", True)
        button.setFixedSize(36, 34)
        button.setToolTip(tooltip)
        button.setIcon(icon(name, color, 18))
        return button

    def _item(self, row: int) -> dict[str, Any] | None:
        return self._visible_items[row] if 0 <= row < len(self._visible_items) else None

    def _pause(self, row: int) -> None:
        item = self._item(row)
        if item is None:
            return
        try:
            controller_call(self.controller, "pause_download", item.get("id"))
            self.message.emit("任务已暂停")
            self.reload()
            self.changed.emit()
        except Exception as exc:
            self.error.emit(f"暂停任务失败：{exc}")

    def _resume(self, row: int) -> None:
        item = self._item(row)
        if item is None:
            return
        try:
            controller_call(self.controller, "resume_download", item.get("id"))
            self.message.emit("任务已恢复")
            self.reload()
            self.changed.emit()
        except Exception as exc:
            self.error.emit(f"恢复任务失败：{exc}")

    def _remove(self, row: int) -> None:
        item = self._item(row)
        if item is None:
            return
        dialog = RemoveDownloadDialog(str(item.get("title") or "该任务"), self)
        if dialog.exec() != QMessageBox.StandardButton.Ok:
            return
        task_id = item.get("id")
        delete_files = dialog.delete_files.isChecked()

        def operation() -> Any:
            try:
                return controller_call(
                    self.controller,
                    "remove_download",
                    task_id,
                    delete_files=delete_files,
                )
            except TypeError:
                return controller_call(self.controller, "remove_download", task_id, delete_files)

        worker = FunctionWorker(operation)
        self._remove_workers.add(worker)
        worker.signals.succeeded.connect(
            lambda _result, current=worker: self._remove_finished(current)
        )
        worker.signals.failed.connect(
            lambda detail, current=worker: self._remove_failed(current, detail)
        )
        self.message.emit("正在停止并移除任务…")
        QThreadPool.globalInstance().start(worker)

    def _remove_finished(self, worker: FunctionWorker) -> None:
        self._remove_workers.discard(worker)
        self.message.emit("下载任务已移除")
        self.reload()
        self.changed.emit()

    def _remove_failed(self, worker: FunctionWorker, detail: str) -> None:
        self._remove_workers.discard(worker)
        self.error.emit(f"移除任务失败：{detail}")

    def _open_folder(self, row: int, _column: int) -> None:
        item = self._item(row)
        if item is None:
            return
        path = item.get("path") or item.get("save_path") or item.get("destination_directory")
        if not path:
            self.message.emit("该任务还没有可打开的保存目录")
            return
        try:
            controller_call(self.controller, "open_folder", str(path))
        except Exception as exc:
            self.error.emit(f"无法打开保存目录：{exc}")

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        self.empty.set_theme(theme)
        if self._visible_items or self._all_items:
            self._render()
