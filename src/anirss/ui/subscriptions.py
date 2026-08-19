"""RSS subscription management page."""

from __future__ import annotations

import html
from collections.abc import Sequence
from contextlib import suppress
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .controller import controller_call
from .data import as_mapping
from .dialogs import SubscriptionDialog, SubscriptionFolderDialog
from .motion import AnimatedStackedWidget
from .resources import icon
from .subscription_detail import SubscriptionDetailView
from .theme import colors
from .widgets import (
    BadgeLabel,
    ClickableElidedLabel,
    ElidedLabel,
    EmptyState,
    PageHeader,
)
from .widgets import (
    JellyButton as QPushButton,
)


def _dict(item: Any) -> dict[str, Any]:
    return as_mapping(item)


def _keyword_text(value: Any) -> str:
    if isinstance(value, str):
        return value[:2000]
    if isinstance(value, Sequence):
        return "、".join(str(part)[:200] for part in value[:100])[:2000]
    return ""


class SubscriptionsPage(QWidget):
    """List, add, edit and remove per-anime RSS feeds."""

    changed = Signal()
    error = Signal(str)
    message = Signal(str)
    route_changed = Signal(str)
    refresh_requested = Signal(object)
    show_download_requested = Signal(object)

    def __init__(self, controller: object | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._theme = "light"
        self._all_items: list[dict[str, Any]] = []
        self._items: list[dict[str, Any]] = []
        self._folders: list[dict[str, Any]] = []
        self._detail_subscription_id: Any = None
        self._refreshing_subscription_id: Any = None

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.route_stack = AnimatedStackedWidget()
        self.list_view = QWidget()
        layout = QVBoxLayout(self.list_view)
        layout.setContentsMargins(30, 26, 30, 26)
        layout.setSpacing(18)
        top = QHBoxLayout()
        top.addWidget(PageHeader("订阅", "点击番剧查看具体条目，并按需自主下载"))
        top.addStretch()
        self.add_button = QPushButton("新增订阅")
        self.add_button.setProperty("primary", True)
        self.add_button.setIcon(icon("plus", "#FFFFFF", 18))
        self.add_button.clicked.connect(self.add_subscription)
        top.addWidget(self.add_button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top)

        folder_panel = QFrame()
        folder_panel.setObjectName("FolderToolbar")
        folder_panel_layout = QVBoxLayout(folder_panel)
        folder_panel_layout.setContentsMargins(12, 10, 12, 10)
        folder_panel_layout.setSpacing(7)
        folder_filter_row = QHBoxLayout()
        folder_filter_row.setSpacing(8)
        folder_label = QLabel("订阅文件夹")
        folder_label.setTextFormat(Qt.TextFormat.PlainText)
        folder_label.setStyleSheet("font-weight:600;")
        folder_filter_row.addWidget(folder_label)
        self.folder_filter = QComboBox()
        self.folder_filter.setMinimumWidth(120)
        self.folder_filter.setMaximumWidth(320)
        self.folder_filter.currentIndexChanged.connect(self._folder_filter_changed)
        folder_filter_row.addWidget(self.folder_filter, 1)
        self.new_folder_button = QPushButton("新建文件夹")
        self.new_folder_button.setIcon(icon("plus", "#717789", 17))
        self.new_folder_button.clicked.connect(self.add_folder)
        folder_filter_row.addWidget(self.new_folder_button)
        folder_panel_layout.addLayout(folder_filter_row)

        folder_action_row = QHBoxLayout()
        folder_action_row.setSpacing(6)
        self.folder_path = ElidedLabel("按文件夹筛选和整理订阅")
        self.folder_path.setObjectName("Muted")
        folder_action_row.addWidget(self.folder_path, 1)
        self.edit_folder_button = QPushButton()
        self.edit_folder_button.setProperty("flat", True)
        self.edit_folder_button.setFixedSize(36, 34)
        self.edit_folder_button.setToolTip("编辑当前文件夹")
        self.edit_folder_button.setIcon(icon("edit", "#717789", 17))
        self.edit_folder_button.clicked.connect(self.edit_current_folder)
        folder_action_row.addWidget(self.edit_folder_button)
        self.delete_folder_button = QPushButton()
        self.delete_folder_button.setProperty("flat", True)
        self.delete_folder_button.setProperty("danger", True)
        self.delete_folder_button.setFixedSize(36, 34)
        self.delete_folder_button.setToolTip("删除当前文件夹")
        self.delete_folder_button.setIcon(icon("delete", "#D84A5B", 17))
        self.delete_folder_button.clicked.connect(self.delete_current_folder)
        folder_action_row.addWidget(self.delete_folder_button)
        self.move_button = QPushButton("移动订阅")
        self.move_button.setIcon(icon("folder", "#717789", 17))
        self.move_button.setEnabled(False)
        self.move_button.clicked.connect(self.move_selected_subscription)
        folder_action_row.addWidget(self.move_button)
        folder_panel_layout.addLayout(folder_action_row)
        layout.addWidget(folder_panel)

        self.stack = QStackedWidget()
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["番剧", "RSS 来源", "匹配规则", "保存位置", "状态", "操作"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(
            max(68, self.fontMetrics().height() * 3 + 16)
        )
        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(76)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(4, 88)
        self.table.setColumnWidth(5, 132)
        self.table.cellDoubleClicked.connect(lambda row, _column: self.open_subscription(row))
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.stack.addWidget(self.table)

        self.empty_card = QFrame()
        self.empty_card.setObjectName("Card")
        empty_layout = QVBoxLayout(self.empty_card)
        self.empty = EmptyState(
            "还没有 RSS 订阅",
            "添加第一部番剧，AniRSS 会定时检查更新并为它创建独立文件夹。",
            "添加第一个订阅",
            "rss",
        )
        self.empty.action_clicked.connect(self.add_subscription)
        empty_layout.addWidget(self.empty)
        self.stack.addWidget(self.empty_card)
        layout.addWidget(self.stack, 1)

        self.route_stack.addWidget(self.list_view)
        self.detail_view = SubscriptionDetailView(self.controller)
        self.detail_view.back_requested.connect(self.show_subscription_list)
        self.detail_view.edit_requested.connect(self._edit_subscription_item)
        self.detail_view.refresh_requested.connect(self.refresh_requested.emit)
        self.detail_view.show_download_requested.connect(self.show_download_requested.emit)
        self.detail_view.changed.connect(self._detail_changed)
        self.detail_view.message.connect(self.message.emit)
        self.detail_view.error.connect(self.error.emit)
        self.route_stack.addWidget(self.detail_view)
        root_layout.addWidget(self.route_stack)

    def set_controller(self, controller: object | None) -> None:
        self.controller = controller
        self.detail_view.set_controller(controller)

    @property
    def detail_active(self) -> bool:
        return (
            self._detail_subscription_id is not None
            and self.route_stack.currentWidget() is self.detail_view
        )

    def reload(self, *, refresh_detail: bool = True) -> None:
        try:
            result = controller_call(self.controller, "list_subscriptions", default=[]) or []
            folders = (
                controller_call(self.controller, "list_subscription_folders", default=[]) or []
            )
            self.set_subscriptions(
                result,
                folders=folders,
                refresh_detail=refresh_detail,
            )
        except Exception as exc:
            self.error.emit(f"加载订阅失败：{exc}")

    def set_subscriptions(
        self,
        subscriptions: Sequence[Any],
        *,
        folders: Sequence[Any] | None = None,
        refresh_detail: bool = True,
        preserve_scroll: bool = True,
    ) -> None:
        scroll_value = self.table.verticalScrollBar().value() if preserve_scroll else 0
        self._all_items = [_dict(item) for item in subscriptions]
        if folders is not None:
            self._folders = [_dict(folder) for folder in folders]
        self._update_folder_filter()
        selected_folder = self.folder_filter.currentData()
        if selected_folder == "__unfiled__":
            self._items = [item for item in self._all_items if item.get("folder_id") is None]
        elif selected_folder in {None, "__all__"}:
            self._items = list(self._all_items)
        else:
            self._items = [
                item for item in self._all_items if item.get("folder_id") == selected_folder
            ]
        self.table.setRowCount(0)
        c = colors(self._theme)
        for item in self._items:
            row = self.table.rowCount()
            self.table.insertRow(row)
            name = str(
                item.get("name") or item.get("anime_name") or item.get("title") or "未命名番剧"
            )[:2000]
            episode_count = item.get("episode_count")
            subtitle = f"已记录 {episode_count} 条" if episode_count is not None else "等待首次刷新"
            name_widget = QWidget()
            name_layout = QVBoxLayout(name_widget)
            name_layout.setContentsMargins(7, 7, 5, 7)
            name_layout.setSpacing(2)
            name_label = ClickableElidedLabel(name)
            name_label.clicked.connect(lambda r=row: self.open_subscription(r))
            hint = ElidedLabel(subtitle)
            hint.setObjectName("Muted")
            hint.setStyleSheet(f"color:{c.text_muted};font-size:11px;")
            name_layout.addWidget(name_label)
            name_layout.addWidget(hint)
            self.table.setCellWidget(row, 0, name_widget)

            url = str(item.get("rss_url") or item.get("url") or item.get("feed_url") or "—")[:4000]
            url_item = QTableWidgetItem(url)
            url_item.setToolTip(html.escape(url))
            url_item.setData(Qt.ItemDataRole.UserRole, item)
            self.table.setItem(row, 1, url_item)

            include = _keyword_text(
                item.get("include_keywords", item.get("include_pattern", item.get("include", [])))
            )
            exclude = _keyword_text(
                item.get("exclude_keywords", item.get("exclude_pattern", item.get("exclude", [])))
            )
            rules = f"包含：{include or '不限'}\n排除：{exclude or '无'}"
            rule_item = QTableWidgetItem(rules)
            rule_item.setToolTip(
                html.escape(f"{rules}\n集数：{item.get('episode_regex') or '默认规则'}")
            )
            self.table.setItem(row, 2, rule_item)

            path = str(
                item.get("resolved_save_path")
                or item.get("save_path")
                or item.get("save_directory")
                or item.get("directory_name")
                or "使用全局目录"
            )[:4000]
            path_item = QTableWidgetItem(path)
            path_item.setToolTip(html.escape(path))
            self.table.setItem(row, 3, path_item)

            enabled = bool(item.get("enabled", True))
            auto = bool(item.get("auto_download", item.get("download_enabled", True)))
            state_text = "自动下载" if enabled and auto else "仅记录" if enabled else "已停用"
            state_tone = "success" if enabled and auto else "info" if enabled else "neutral"
            badge = BadgeLabel(state_text, state_tone)
            if enabled and not auto:
                badge.setToolTip("新条目只写入去重记录，不创建任务或发送下载通知。")
            badge.set_theme(self._theme)
            state_cell = QWidget()
            state_layout = QHBoxLayout(state_cell)
            state_layout.setContentsMargins(5, 0, 5, 0)
            state_layout.addWidget(badge)
            self.table.setCellWidget(row, 4, state_cell)

            actions = QWidget()
            action_layout = QHBoxLayout(actions)
            action_layout.setContentsMargins(3, 0, 3, 0)
            action_layout.setSpacing(1)
            view = QPushButton()
            view.setProperty("flat", True)
            view.setToolTip("查看订阅内容")
            view.setFixedSize(36, 34)
            view.setIcon(icon("search", c.accent, 18))
            view.clicked.connect(lambda _checked=False, r=row: self.open_subscription(r))
            edit = QPushButton()
            edit.setProperty("flat", True)
            edit.setToolTip("编辑订阅")
            edit.setFixedSize(36, 34)
            edit.setIcon(icon("edit", c.text_muted, 18))
            edit.clicked.connect(lambda _checked=False, r=row: self.edit_subscription(r))
            remove = QPushButton()
            remove.setProperty("flat", True)
            remove.setProperty("danger", True)
            remove.setToolTip("删除订阅")
            remove.setFixedSize(36, 34)
            remove.setIcon(icon("delete", c.danger, 18))
            remove.clicked.connect(lambda _checked=False, r=row: self.delete_subscription(r))
            action_layout.addWidget(view)
            action_layout.addWidget(edit)
            action_layout.addWidget(remove)
            self.table.setCellWidget(row, 5, actions)
        self.stack.setCurrentWidget(self.table if self._items else self.empty_card)
        self._update_responsive_columns(self.width())
        self._selection_changed()
        if preserve_scroll:
            QTimer.singleShot(
                0,
                lambda value=scroll_value: self.table.verticalScrollBar().setValue(
                    min(value, self.table.verticalScrollBar().maximum())
                ),
            )
        if self._detail_subscription_id is not None:
            current = next(
                (item for item in self._items if item.get("id") == self._detail_subscription_id),
                None,
            )
            if current is None:
                self.show_subscription_list()
            else:
                self.detail_view.set_subscription(current, reload_items=refresh_detail)
                self.detail_view.set_refreshing(self._refreshing_subscription_id)
                if self.detail_active:
                    self.route_changed.emit(str(current.get("name") or "订阅详情"))

    def _update_folder_filter(self) -> None:
        selected = self.folder_filter.currentData()
        self.folder_filter.blockSignals(True)
        self.folder_filter.clear()
        self.folder_filter.addItem(f"全部订阅（{len(self._all_items)}）", "__all__")
        unfiled_count = sum(item.get("folder_id") is None for item in self._all_items)
        self.folder_filter.addItem(f"未分类（{unfiled_count}）", "__unfiled__")
        for folder in self._folders:
            folder_id = folder.get("id")
            count = sum(item.get("folder_id") == folder_id for item in self._all_items)
            name = str(folder.get("name") or "未命名文件夹")[:200]
            self.folder_filter.addItem(f"{name}（{count}）", folder_id)
            index = self.folder_filter.count() - 1
            self.folder_filter.setItemData(
                index,
                str(folder.get("download_directory") or ""),
                Qt.ItemDataRole.ToolTipRole,
            )
        index = self.folder_filter.findData(selected)
        self.folder_filter.setCurrentIndex(index if index >= 0 else 0)
        self.folder_filter.blockSignals(False)
        current_folder = self._current_folder()
        is_folder = current_folder is not None
        self.edit_folder_button.setEnabled(is_folder)
        self.delete_folder_button.setEnabled(is_folder)
        if current_folder is not None:
            self.folder_path.setText(
                f"下载根目录：{current_folder.get('download_directory') or '尚未设置'}"
            )
        elif self.folder_filter.currentData() == "__unfiled__":
            self.folder_path.setText("未分类订阅使用全局下载目录")
        else:
            self.folder_path.setText("按文件夹筛选和整理订阅")

    def _folder_filter_changed(self, _index: int | None = None) -> None:
        self.set_subscriptions(
            self._all_items,
            folders=self._folders,
            refresh_detail=False,
            preserve_scroll=False,
        )

    def _current_folder(self) -> dict[str, Any] | None:
        folder_id = self.folder_filter.currentData()
        return next(
            (folder for folder in self._folders if folder.get("id") == folder_id),
            None,
        )

    def _selection_changed(self) -> None:
        self.move_button.setEnabled(0 <= self.table.currentRow() < len(self._items))

    def open_subscription(self, row: int) -> None:
        if not 0 <= row < len(self._items):
            return
        item = self._items[row]
        self._detail_subscription_id = item.get("id")
        self.route_stack.transition_to_widget(self.detail_view)
        self.detail_view.set_subscription(item)
        self.detail_view.set_refreshing(self._refreshing_subscription_id)
        self.route_changed.emit(str(item.get("name") or "订阅详情"))

    def show_subscription_list(self) -> None:
        self._detail_subscription_id = None
        self.route_stack.transition_to_widget(self.list_view)
        self.route_changed.emit("")

    def _detail_changed(self) -> None:
        self.reload()
        self.changed.emit()

    def set_detail_refreshing(self, subscription_id: Any, refreshing: bool) -> None:
        self._refreshing_subscription_id = subscription_id if refreshing else None
        self.detail_view.set_refreshing(self._refreshing_subscription_id)

    def detail_refresh_finished(self, subscription_id: Any) -> None:
        if self._refreshing_subscription_id == subscription_id:
            self._refreshing_subscription_id = None
        refresh_current = self.detail_active and self._detail_subscription_id == subscription_id
        self.reload(refresh_detail=refresh_current)
        self.detail_view.set_refreshing(self._refreshing_subscription_id)

    def _default_directory(self) -> str:
        try:
            settings = controller_call(self.controller, "load_settings", default={}) or {}
            settings = as_mapping(settings)
            if settings:
                return str(
                    settings.get("download_directory")
                    or settings.get("download_dir")
                    or settings.get("download_root")
                    or ""
                )
        except Exception:
            pass
        return ""

    def add_folder(self) -> None:
        dialog = SubscriptionFolderDialog(default_directory=self._default_directory(), parent=self)
        if dialog.exec() != SubscriptionFolderDialog.DialogCode.Accepted:
            return
        try:
            saved = controller_call(self.controller, "save_subscription_folder", dialog.data())
            self.message.emit("订阅文件夹已创建")
            self.reload(refresh_detail=False)
            saved_id = _dict(saved).get("id")
            index = self.folder_filter.findData(saved_id)
            if index >= 0:
                self.folder_filter.setCurrentIndex(index)
            self.changed.emit()
        except Exception as exc:
            self.error.emit(f"创建订阅文件夹失败：{exc}")

    def edit_current_folder(self) -> None:
        folder = self._current_folder()
        if folder is None:
            self.message.emit("请先选择一个订阅文件夹")
            return
        dialog = SubscriptionFolderDialog(folder, self._default_directory(), self)
        if dialog.exec() != SubscriptionFolderDialog.DialogCode.Accepted:
            return
        try:
            controller_call(self.controller, "save_subscription_folder", dialog.data())
            self.message.emit("订阅文件夹已更新")
            self.reload(refresh_detail=False)
            self.changed.emit()
        except Exception as exc:
            self.error.emit(f"更新订阅文件夹失败：{exc}")

    def delete_current_folder(self) -> None:
        folder = self._current_folder()
        if folder is None:
            self.message.emit("请先选择一个订阅文件夹")
            return
        name = str(folder.get("name") or "该文件夹")[:120]
        decision = QMessageBox.question(
            self,
            "删除订阅文件夹",
            f"确定删除“{name}”吗？\n其中的订阅会变为未分类，已有文件不会移动或删除。",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel,
        )
        if decision != QMessageBox.StandardButton.Yes:
            return
        try:
            controller_call(self.controller, "delete_subscription_folder", folder.get("id"))
            self.message.emit("订阅文件夹已删除，原有订阅已转为未分类")
            self.reload(refresh_detail=False)
            self.changed.emit()
        except Exception as exc:
            self.error.emit(f"删除订阅文件夹失败：{exc}")

    def move_selected_subscription(self) -> None:
        row = self.table.currentRow()
        if not 0 <= row < len(self._items):
            self.message.emit("请先选择要移动的订阅")
            return
        subscription = self._items[row]
        options: list[tuple[str, Any | None]] = [("未分类（全局下载目录）", None)]
        options.extend(
            (str(folder.get("name") or "未命名文件夹")[:200], folder.get("id"))
            for folder in self._folders
        )
        current_folder_id = subscription.get("folder_id")
        current_index = next(
            (
                index
                for index, (_label, folder_id) in enumerate(options)
                if folder_id == current_folder_id
            ),
            0,
        )
        selected, accepted = QInputDialog.getItem(
            self,
            "移动订阅",
            "移动到：",
            [label for label, _folder_id in options],
            current_index,
            False,
        )
        if not accepted:
            return
        selected_index = next(
            (index for index, (label, _folder_id) in enumerate(options) if label == selected),
            current_index,
        )
        folder_id = options[selected_index][1]
        try:
            controller_call(
                self.controller,
                "move_subscription",
                subscription.get("id"),
                folder_id,
            )
            destination = options[selected_index][0]
            self.message.emit(f"订阅已移动到“{destination}”，未来任务将使用新目录")
            self.reload(refresh_detail=False)
            self.changed.emit()
        except Exception as exc:
            self.error.emit(f"移动订阅失败：{exc}")

    def add_subscription(self) -> None:
        dialog = SubscriptionDialog(
            default_directory=self._default_directory(), parent=self, folders=self._folders
        )
        for toggle in dialog.findChildren(QWidget):
            if hasattr(toggle, "set_theme"):
                with suppress(TypeError):
                    toggle.set_theme(self._theme)
        if dialog.exec() != SubscriptionDialog.DialogCode.Accepted:
            return
        payload = dialog.data()
        try:
            controller_call(self.controller, "save_subscription", payload)
            self.message.emit("订阅已添加")
            self.reload()
            self.changed.emit()
        except Exception as exc:
            self.error.emit(f"保存订阅失败：{exc}")

    def edit_subscription(self, row: int) -> None:
        if not 0 <= row < len(self._items):
            return
        self._edit_subscription_item(self._items[row])

    def _edit_subscription_item(self, item: Any) -> None:
        source = _dict(item)
        if not source:
            return
        dialog = SubscriptionDialog(source, self._default_directory(), self, folders=self._folders)
        for toggle in dialog.findChildren(QWidget):
            if hasattr(toggle, "set_theme"):
                with suppress(TypeError):
                    toggle.set_theme(self._theme)
        if dialog.exec() != SubscriptionDialog.DialogCode.Accepted:
            return
        payload = dialog.data()
        old_url = str(source.get("rss_url") or source.get("feed_url") or "")
        new_url = str(payload.get("rss_url") or payload.get("feed_url") or "")
        if old_url and new_url != old_url:
            decision = QMessageBox.question(
                self,
                "更换 RSS 来源",
                "更换来源会重置该订阅的条目和任务记录，以安全建立新基线。\n"
                "已经下载到磁盘的文件不会删除。是否继续？",
                QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
                QMessageBox.StandardButton.Cancel,
            )
            if decision != QMessageBox.StandardButton.Yes:
                return
        try:
            controller_call(self.controller, "save_subscription", payload)
            self.message.emit("订阅已更新")
            self.reload()
            self.changed.emit()
        except Exception as exc:
            self.error.emit(f"更新订阅失败：{exc}")

    def delete_subscription(self, row: int) -> None:
        if not 0 <= row < len(self._items):
            return
        item = self._items[row]
        name = str(item.get("name") or item.get("title") or "该订阅")
        display_name = name if len(name) <= 120 else f"{name[:117]}…"
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setWindowTitle("删除订阅")
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(f"确定删除“{display_name}”吗？\n已下载的文件不会被删除。")
        dialog.setStandardButtons(
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes
        )
        dialog.setDefaultButton(QMessageBox.StandardButton.Cancel)
        dialog.button(QMessageBox.StandardButton.Cancel).setText("取消")
        dialog.button(QMessageBox.StandardButton.Yes).setText("删除")
        result = dialog.exec()
        if result != QMessageBox.StandardButton.Yes:
            return
        try:
            controller_call(self.controller, "delete_subscription", item.get("id"))
            self.message.emit("订阅已删除")
            self.reload()
            self.changed.emit()
        except Exception as exc:
            self.error.emit(f"删除订阅失败：{exc}")

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        c = colors(theme)
        self.new_folder_button.setIcon(icon("plus", c.text_muted, 17))
        self.edit_folder_button.setIcon(icon("edit", c.text_muted, 17))
        self.delete_folder_button.setIcon(icon("delete", c.danger, 17))
        self.move_button.setIcon(icon("folder", c.text_muted, 17))
        self.empty.set_theme(theme)
        self.detail_view.set_theme(theme)
        if self._all_items:
            self.set_subscriptions(self._all_items, folders=self._folders)

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self.empty.set_compact(event.size().height() < 520)
        self._update_responsive_columns(event.size().width())

    def _update_responsive_columns(self, width: int) -> None:
        self.table.setColumnHidden(1, width < 860)
        self.table.setColumnHidden(2, width < 1040)
        self.table.setColumnHidden(3, width < 720)
