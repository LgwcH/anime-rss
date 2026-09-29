"""RSS subscription management page (08-compact-pro three-column layout)."""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import suppress
from typing import Any
from urllib.parse import urlparse

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QScrollArea,
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
    CoverAvatar,
    ElidedLabel,
    EmptyState,
    IconRow,
    clear_layout,
)
from .widgets import (
    JellyButton as QPushButton,
)

_FILTER_MODES = (
    ("all", "全部"),
    ("following", "追番中"),
    ("record", "仅记录"),
    ("disabled", "已停用"),
)


def _dict(item: Any) -> dict[str, Any]:
    return as_mapping(item)


def _state_of(item: dict[str, Any]) -> tuple[str, str, str]:
    """Return ``(filter_key, label, tone)`` for a subscription mapping."""

    enabled = bool(item.get("enabled", True))
    auto = bool(item.get("auto_download", item.get("download_enabled", True)))
    if enabled and auto:
        return "following", "追番中", "sub"
    if enabled:
        return "record", "仅记录", "wait"
    return "disabled", "已停用", "done"


def _host_of(item: dict[str, Any]) -> str:
    url = str(item.get("rss_url") or item.get("url") or item.get("feed_url") or "")
    return urlparse(url).netloc or url or "未知来源"


class SubscriptionRow(IconRow):
    """One subscription entry in the 320px list column."""

    indicator_inset = 0

    def __init__(self, item: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SubRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 9, 16, 9)
        layout.setSpacing(10)

        self.cover = CoverAvatar(str(item.get("name") or "?"), 28)
        self.cover.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.cover, 0, Qt.AlignmentFlag.AlignVCenter)

        mid = QVBoxLayout()
        mid.setContentsMargins(0, 0, 0, 0)
        mid.setSpacing(1)
        name = ElidedLabel(str(item.get("name") or item.get("title") or "未命名番剧"))
        name.setStyleSheet("font-size:13px; font-weight:600;")
        name.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        mid.addWidget(name)
        meta = ElidedLabel(
            f"{_host_of(item)} · {item.get('last_update') or '尚未刷新'!s}"
        )
        meta.setObjectName("Muted")
        meta.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        mid.addWidget(meta)
        layout.addLayout(mid, 1)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(3)
        count = item.get("episode_count")
        progress = QLabel(f"{count} 集" if count is not None else "—")
        progress.setStyleSheet("font-size:12px;")
        progress.setObjectName("SubProgress")
        progress.setAlignment(Qt.AlignmentFlag.AlignRight)
        progress.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        right.addWidget(progress)
        _key, label, tone = _state_of(item)
        self.status = BadgeLabel(label, tone)
        self.status.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        right.addWidget(self.status, 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(right)
        self.setFixedHeight(max(50, self.sizeHint().height()))

    def set_theme(self, theme: str) -> None:
        super().set_theme(theme)
        self.status.set_theme(theme)


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
        self._rows: list[SubscriptionRow] = []
        self._selected_row = -1
        self._filter_mode = "all"
        self._detail_subscription_id: Any = None
        self._refreshing_subscription_id: Any = None

        root_layout = QHBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ---------------- 列表栏 (320px) ----------------
        list_panel = QFrame()
        list_panel.setObjectName("ListPanel")
        list_panel.setFixedWidth(320)
        list_layout = QVBoxLayout(list_panel)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(0)

        tools = QFrame()
        tools.setObjectName("ListTools")
        tools_layout = QVBoxLayout(tools)
        tools_layout.setContentsMargins(16, 12, 16, 10)
        tools_layout.setSpacing(8)
        self.add_button = QPushButton("＋ 添加订阅")
        self.add_button.setProperty("primary", True)
        self.add_button.setObjectName("BlockPrimary")
        self.add_button.setFixedHeight(30)
        self.add_button.clicked.connect(self.add_subscription)
        tools_layout.addWidget(self.add_button)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索番名 / 字幕组")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._search_changed)
        tools_layout.addWidget(self.search_edit)
        folder_row = QHBoxLayout()
        folder_row.setContentsMargins(0, 0, 0, 0)
        folder_row.setSpacing(6)
        self.folder_filter = QComboBox()
        self.folder_filter.setFixedHeight(26)
        self.folder_filter.currentIndexChanged.connect(self._folder_filter_changed)
        folder_row.addWidget(self.folder_filter, 1)
        self.new_folder_button = QPushButton()
        self.new_folder_button.setObjectName("IconButton")
        self.new_folder_button.setFixedSize(26, 26)
        self.new_folder_button.setToolTip("新建订阅文件夹")
        self.new_folder_button.clicked.connect(self.add_folder)
        folder_row.addWidget(self.new_folder_button)
        self.edit_folder_button = QPushButton()
        self.edit_folder_button.setObjectName("IconButton")
        self.edit_folder_button.setFixedSize(26, 26)
        self.edit_folder_button.setToolTip("编辑当前文件夹")
        self.edit_folder_button.clicked.connect(self.edit_current_folder)
        folder_row.addWidget(self.edit_folder_button)
        self.delete_folder_button = QPushButton()
        self.delete_folder_button.setObjectName("IconButton")
        self.delete_folder_button.setProperty("danger", True)
        self.delete_folder_button.setFixedSize(26, 26)
        self.delete_folder_button.setToolTip("删除当前文件夹")
        self.delete_folder_button.clicked.connect(self.delete_current_folder)
        folder_row.addWidget(self.delete_folder_button)
        self.move_button = QPushButton()
        self.move_button.setObjectName("IconButton")
        self.move_button.setFixedSize(26, 26)
        self.move_button.setToolTip("移动选中订阅到其他文件夹")
        self.move_button.setEnabled(False)
        self.move_button.clicked.connect(self.move_selected_subscription)
        folder_row.addWidget(self.move_button)
        tools_layout.addLayout(folder_row)
        list_layout.addWidget(tools)

        filter_bar = QFrame()
        filter_bar.setObjectName("FilterBar")
        filter_bar.setFixedHeight(32)
        filter_layout = QHBoxLayout(filter_bar)
        filter_layout.setContentsMargins(16, 0, 16, 0)
        filter_layout.setSpacing(14)
        self.filter_group = QButtonGroup(self)
        self.filter_group.setExclusive(True)
        self.filter_buttons: dict[str, QPushButton] = {}
        for key, label in _FILTER_MODES:
            button = QPushButton(label)
            button.setObjectName("FilterTab")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(
                lambda _checked=False, mode=key: self._set_filter_mode(mode)
            )
            self.filter_group.addButton(button)
            self.filter_buttons[key] = button
            filter_layout.addWidget(button)
        filter_layout.addStretch()
        self.filter_buttons["all"].setChecked(True)
        list_layout.addWidget(filter_bar)

        self.rows_area = QScrollArea()
        self.rows_area.setWidgetResizable(True)
        self.rows_area.setFrameShape(QFrame.Shape.NoFrame)
        self.rows_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.rows_host = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_host)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(0)
        self.rows_layout.addStretch()
        self.rows_area.setWidget(self.rows_host)
        list_layout.addWidget(self.rows_area, 1)

        self.list_foot = QFrame()
        self.list_foot.setObjectName("ListFooter")
        foot_layout = QHBoxLayout(self.list_foot)
        foot_layout.setContentsMargins(16, 10, 16, 10)
        self.list_summary = ElidedLabel("")
        self.list_summary.setObjectName("Muted")
        foot_layout.addWidget(self.list_summary, 1)
        list_layout.addWidget(self.list_foot)
        root_layout.addWidget(list_panel)

        # ---------------- 详情主区 ----------------
        self.route_stack = AnimatedStackedWidget()
        self.list_view = QWidget()
        placeholder_layout = QVBoxLayout(self.list_view)
        self.placeholder = EmptyState(
            "选择左侧的订阅",
            "这里会显示该番剧的剧集列表、匹配规则与下载状态。",
            "添加订阅",
            "rss",
        )
        self.placeholder.action_clicked.connect(self.add_subscription)
        placeholder_layout.addWidget(self.placeholder)
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
        root_layout.addWidget(self.route_stack, 1)

        self.empty = EmptyState(
            "还没有 RSS 订阅",
            "添加第一部番剧，AniRSS 会定时检查更新并为它创建独立文件夹。",
            "添加第一个订阅",
            "rss",
        )
        self.empty.action_clicked.connect(self.add_subscription)

    # ------------------------------------------------------------- data flow

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
        scroll_value = self.rows_area.verticalScrollBar().value() if preserve_scroll else 0
        self._all_items = [_dict(item) for item in subscriptions]
        if folders is not None:
            self._folders = [_dict(folder) for folder in folders]
        self._update_folder_filter()
        self._apply_filters()
        self._render_rows()
        if preserve_scroll:
            QTimer.singleShot(
                0,
                lambda value=scroll_value: self.rows_area.verticalScrollBar().setValue(
                    min(value, self.rows_area.verticalScrollBar().maximum())
                ),
            )
        if self._detail_subscription_id is not None:
            current = next(
                (
                    item
                    for item in self._all_items
                    if item.get("id") == self._detail_subscription_id
                ),
                None,
            )
            if current is None:
                self.show_subscription_list()
            else:
                self.detail_view.set_subscription(current, reload_items=refresh_detail)
                self.detail_view.set_refreshing(self._refreshing_subscription_id)
                if self.detail_active:
                    self.route_changed.emit(str(current.get("name") or "订阅详情"))

    def _apply_filters(self) -> None:
        selected_folder = self.folder_filter.currentData()
        query = self.search_edit.text().strip().casefold()
        items: list[dict[str, Any]] = []
        for item in self._all_items:
            if selected_folder == "__unfile__":
                if item.get("folder_id") is not None:
                    continue
            elif (
                selected_folder not in {None, "__all__"}
                and item.get("folder_id") != selected_folder
            ):
                continue
            filter_key, _label, _tone = _state_of(item)
            if self._filter_mode != "all" and filter_key != self._filter_mode:
                continue
            if query:
                include = item.get("include_keywords") or []
                if isinstance(include, str):
                    include = [include]
                blob = " ".join(
                    [
                        str(item.get("name") or ""),
                        str(item.get("rss_url") or ""),
                        " ".join(str(word) for word in include),
                    ]
                ).casefold()
                if query not in blob:
                    continue
            items.append(item)
        self._items = items

    def _render_rows(self) -> None:
        self.rows_layout.removeWidget(self.empty)
        self.empty.hide()
        clear_layout(self.rows_layout)
        self._rows = []
        counts = {"all": len(self._all_items)}
        for item in self._all_items:
            key, _label, _tone = _state_of(item)
            counts[key] = counts.get(key, 0) + 1
        for key, label in _FILTER_MODES:
            self.filter_buttons[key].setText(f"{label} {counts.get(key, 0)}")
        for index, item in enumerate(self._items):
            row = SubscriptionRow(item)
            row.set_theme(self._theme)
            row.clicked.connect(lambda _checked=False, r=index: self.open_subscription(r))
            self._rows.append(row)
            self.rows_layout.addWidget(row)
        if not self._items:
            if self._all_items:
                self.empty.set_content(
                    "没有符合条件的订阅",
                    "换一个搜索词、文件夹或状态筛选，即可重新查看订阅。",
                )
            else:
                self.empty.set_content(
                    "还没有 RSS 订阅",
                    "添加第一部番剧，AniRSS 会定时检查更新并为它创建独立文件夹。",
                )
            self.rows_layout.addWidget(self.empty)
            self.empty.show()
        self.rows_layout.addStretch()
        self.rows_layout.activate()
        self.rows_host.setMinimumHeight(self.rows_layout.sizeHint().height())
        folder_count = len(self._folders)
        sources = len({_host_of(item) for item in self._all_items})
        self.list_summary.setText(
            f"{len(self._all_items)} 个订阅 · {sources} 个 RSS 源 · {folder_count} 个文件夹"
        )
        selected_id = self._detail_subscription_id
        self._selected_row = next(
            (
                index
                for index, item in enumerate(self._items)
                if selected_id is not None and item.get("id") == selected_id
            ),
            -1,
        )
        for index, row in enumerate(self._rows):
            row.blockSignals(True)
            row.setChecked(index == self._selected_row)
            row.blockSignals(False)
        self.move_button.setEnabled(0 <= self._selected_row < len(self._items))

    def _set_filter_mode(self, mode: str) -> None:
        self._filter_mode = mode
        self._apply_filters()
        self._render_rows()

    def _search_changed(self, _text: str) -> None:
        self._apply_filters()
        self._render_rows()

    def apply_search(self, query: str) -> None:
        self.search_edit.setText(query)
        if self._items:
            self.open_subscription(0)

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

    def _folder_filter_changed(self, _index: int | None = None) -> None:
        self._apply_filters()
        self._render_rows()

    def _current_folder(self) -> dict[str, Any] | None:
        folder_id = self.folder_filter.currentData()
        return next(
            (folder for folder in self._folders if folder.get("id") == folder_id),
            None,
        )

    # ------------------------------------------------------------- selection

    def select_subscription(self, row: int) -> None:
        self.open_subscription(row)

    def open_subscription(self, row: int) -> None:
        if not 0 <= row < len(self._items):
            return
        item = self._items[row]
        self._selected_row = row
        for index, row_widget in enumerate(self._rows):
            row_widget.blockSignals(True)
            row_widget.setChecked(index == row)
            row_widget.blockSignals(False)
        self.move_button.setEnabled(True)
        self._detail_subscription_id = item.get("id")
        self.route_stack.transition_to_widget(self.detail_view)
        self.detail_view.set_subscription(item)
        self.detail_view.set_refreshing(self._refreshing_subscription_id)
        self.route_changed.emit(str(item.get("name") or "订阅详情"))

    def show_subscription_list(self) -> None:
        self._detail_subscription_id = None
        self._selected_row = -1
        for row_widget in self._rows:
            row_widget.blockSignals(True)
            row_widget.setChecked(False)
            row_widget.blockSignals(False)
        self.move_button.setEnabled(False)
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

    # --------------------------------------------------------------- actions

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
        row = self._selected_row
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
        self.new_folder_button.setIcon(icon("plus", c.text2, 14))
        self.edit_folder_button.setIcon(icon("edit", c.text2, 14))
        self.delete_folder_button.setIcon(icon("delete", c.danger, 14))
        self.move_button.setIcon(icon("folder", c.text2, 14))
        self.empty.set_theme(theme)
        self.placeholder.set_theme(theme)
        self.detail_view.set_theme(theme)
        for row in self._rows:
            row.set_theme(theme)

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self.empty.set_compact(event.size().height() < 520)
        self.placeholder.set_compact(event.size().height() < 520)
