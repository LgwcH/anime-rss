"""Detailed application settings page."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QBoxLayout,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .controller import controller_call
from .data import as_mapping
from .resources import icon
from .theme import colors
from .widgets import JellyButton as QPushButton
from .widgets import PageHeader, ToggleSwitch


def _setting(source: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in source and source[key] is not None:
            return source[key]
    return default


class SettingsGroup(QFrame):
    """Card with a title and aligned settings rows."""

    def __init__(self, title: str, description: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SettingsGroup")
        self._rows: list[tuple[QBoxLayout, QWidget]] = []
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(20, 17, 20, 17)
        self.body.setSpacing(0)
        heading = QLabel(title)
        heading.setTextFormat(Qt.TextFormat.PlainText)
        heading.setObjectName("SectionTitle")
        self.body.addWidget(heading)
        if description:
            detail = QLabel(description)
            detail.setTextFormat(Qt.TextFormat.PlainText)
            detail.setObjectName("Muted")
            detail.setWordWrap(True)
            self.body.addWidget(detail)
            self.body.addSpacing(13)

    def add_setting(
        self,
        title: str,
        description: str,
        control: QWidget,
        compact: bool = False,
    ) -> None:
        if self.body.count() > 2:
            divider = QFrame()
            divider.setObjectName("Divider")
            self.body.addWidget(divider)
        row = QWidget()
        layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, row)
        layout.setContentsMargins(0, 12, 0, 12)
        layout.setSpacing(20)
        label_block = QWidget()
        labels = QVBoxLayout(label_block)
        labels.setContentsMargins(0, 0, 0, 0)
        labels.setSpacing(3)
        title_label = QLabel(title)
        title_label.setTextFormat(Qt.TextFormat.PlainText)
        title_label.setStyleSheet("font-weight:600;")
        labels.addWidget(title_label)
        if description:
            desc = QLabel(description)
            desc.setTextFormat(Qt.TextFormat.PlainText)
            desc.setObjectName("Muted")
            desc.setWordWrap(True)
            labels.addWidget(desc)
        layout.addWidget(label_block, 1)
        if compact:
            control.setSizePolicy(
                control.sizePolicy().horizontalPolicy(), control.sizePolicy().verticalPolicy()
            )
        layout.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
        self._rows.append((layout, control))
        self.body.addWidget(row)

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        stacked = event.size().width() < 650
        direction = (
            QBoxLayout.Direction.TopToBottom if stacked else QBoxLayout.Direction.LeftToRight
        )
        for layout, control in self._rows:
            layout.setDirection(direction)
            layout.setSpacing(10 if stacked else 20)
            alignment = (
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                if stacked
                else Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            layout.setAlignment(control, alignment)


class SettingsPage(QWidget):
    """All user-facing downloader and desktop integration preferences."""

    theme_changed = Signal(str)
    saved = Signal()
    error = Signal(str)
    message = Signal(str)

    def __init__(self, controller: object | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._theme = "light"
        self._loaded: dict[str, Any] = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(30, 26, 20, 18)
        root.setSpacing(16)

        top = QHBoxLayout()
        top.addWidget(PageHeader("设置", "下载器、自动刷新和系统行为均可精细控制"))
        top.addStretch()
        self.save_button = QPushButton("保存设置")
        self.save_button.setProperty("primary", True)
        self.save_button.setIcon(icon("check", "#FFFFFF", 18))
        self.save_button.clicked.connect(self.save)
        top.addWidget(self.save_button, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(top)

        self.settings_scroll = QScrollArea()
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(0, 2, 10, 10)
        self.content_layout.setSpacing(13)

        download_group = SettingsGroup("下载与刷新", "控制文件保存方式及 RSS 检查频率。")
        directory_control = QWidget()
        directory_layout = QHBoxLayout(directory_control)
        directory_layout.setContentsMargins(0, 0, 0, 0)
        directory_layout.setSpacing(7)
        self.directory_edit = QLineEdit()
        self.directory_edit.setPlaceholderText("选择默认下载目录")
        directory_layout.addWidget(self.directory_edit)
        browse = QPushButton("浏览")
        browse.setIcon(icon("folder", "#717789", 17))
        browse.clicked.connect(self._browse_directory)
        directory_layout.addWidget(browse)
        directory_control.setMaximumWidth(460)
        download_group.add_setting(
            "默认下载目录", "未单独指定目录的番剧会在这里自动创建子文件夹。", directory_control
        )

        self.concurrent_spin = QSpinBox()
        self.concurrent_spin.setRange(1, 20)
        self.concurrent_spin.setSuffix(" 个")
        self.concurrent_spin.setMinimumWidth(110)
        download_group.add_setting(
            "并发下载", "同时下载的任务数；网络较慢时建议设为 2–3。", self.concurrent_spin
        )

        self.poll_spin = QSpinBox()
        self.poll_spin.setRange(1, 1440)
        self.poll_spin.setSuffix(" 分钟")
        self.poll_spin.setMinimumWidth(120)
        download_group.add_setting(
            "RSS 轮询间隔", "定时检查所有已启用订阅，过短可能触发站点限制。", self.poll_spin
        )

        self.proxy_edit = QLineEdit()
        self.proxy_edit.setPlaceholderText("例如 http://127.0.0.1:7890")
        self.proxy_edit.setMinimumWidth(220)
        self.proxy_edit.setMaximumWidth(420)
        download_group.add_setting(
            "网络代理",
            "仅用于 RSS 与 HTTP 下载的 HTTP/HTTPS 代理；BT 流量不经过此项。",
            self.proxy_edit,
        )
        self.content_layout.addWidget(download_group)

        behavior_group = SettingsGroup("启动与后台", "决定 AniRSS 在 Windows 中的启动和关闭行为。")
        self.autostart_toggle = ToggleSwitch()
        behavior_group.add_setting(
            "开机自启动", "登录 Windows 后自动启动 AniRSS。", self.autostart_toggle
        )
        self.tray_toggle = ToggleSwitch()
        behavior_group.add_setting(
            "最小化到托盘", "关闭主窗口时继续在后台检查订阅和下载。", self.tray_toggle
        )
        self.notification_toggle = ToggleSwitch()
        behavior_group.add_setting(
            "桌面通知", "发现新剧集、下载完成或任务失败时显示通知。", self.notification_toggle
        )
        self.content_layout.addWidget(behavior_group)

        bt_group = SettingsGroup(
            "内置下载器", "BitTorrent 参数会应用于新任务；完成后的默认行为可随时调整。"
        )
        seed_control = QWidget()
        seed_layout = QHBoxLayout(seed_control)
        seed_layout.setContentsMargins(0, 0, 0, 0)
        seed_layout.setSpacing(10)
        self.seed_toggle = ToggleSwitch()
        self.seed_toggle.toggled.connect(self._seed_toggled)
        seed_layout.addWidget(self.seed_toggle)
        self.seed_minutes = QSpinBox()
        self.seed_minutes.setRange(1, 1440)
        self.seed_minutes.setSuffix(" 分钟")
        self.seed_minutes.setMinimumWidth(120)
        seed_layout.addWidget(self.seed_minutes)
        bt_group.add_setting(
            "下载完成后继续做种", "关闭时任务完成即停止上传；开启后按右侧时长做种。", seed_control
        )

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setMinimumWidth(120)
        bt_group.add_setting(
            "监听端口", "用于接收 BitTorrent 入站连接，修改后可能需要重启下载引擎。", self.port_spin
        )

        self.metadata_timeout_spin = QSpinBox()
        self.metadata_timeout_spin.setRange(30, 1800)
        self.metadata_timeout_spin.setSuffix(" 秒")
        self.metadata_timeout_spin.setMinimumWidth(120)
        bt_group.add_setting(
            "磁力解析超时",
            "在限定时间内获取不到磁力元数据时标记失败并释放下载槽。",
            self.metadata_timeout_spin,
        )

        self.stall_timeout_spin = QSpinBox()
        self.stall_timeout_spin.setRange(1, 120)
        self.stall_timeout_spin.setSuffix(" 分钟")
        self.stall_timeout_spin.setMinimumWidth(120)
        bt_group.add_setting(
            "无数据超时",
            "已有元数据但持续没有收到数据时暂停本次尝试，避免阻塞整个队列。",
            self.stall_timeout_spin,
        )
        self.content_layout.addWidget(bt_group)

        appearance_group = SettingsGroup("外观", "选择更适合当前环境的界面配色。")
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("浅色", "light")
        self.theme_combo.addItem("深色", "dark")
        self.theme_combo.addItem("跟随系统", "system")
        self.theme_combo.setMinimumWidth(140)
        self.theme_combo.currentIndexChanged.connect(self._preview_theme)
        appearance_group.add_setting(
            "主题", "主题切换会立即预览，保存后在下次启动时继续使用。", self.theme_combo
        )
        self.content_layout.addWidget(appearance_group)
        self.content_layout.addStretch()

        self.settings_scroll.setWidget(content)
        root.addWidget(self.settings_scroll, 1)

    def set_controller(self, controller: object | None) -> None:
        self.controller = controller

    def reload(self) -> None:
        try:
            result = controller_call(self.controller, "load_settings", default={}) or {}
            normalized = as_mapping(result)
            if normalized:
                self.set_settings(normalized)
        except Exception as exc:
            self.error.emit(f"加载设置失败：{exc}")

    def set_settings(self, settings: Mapping[str, Any]) -> None:
        scroll_value = self.settings_scroll.verticalScrollBar().value()
        self._loaded = dict(settings)
        self.directory_edit.setText(
            str(
                _setting(
                    settings, "download_directory", "download_dir", "download_root", default=""
                )
            )
        )
        self.concurrent_spin.setValue(
            int(_setting(settings, "max_concurrent_downloads", "concurrency", default=3))
        )
        self.poll_spin.setValue(
            int(
                _setting(
                    settings,
                    "poll_interval_minutes",
                    "poll_interval",
                    "default_poll_interval_minutes",
                    default=15,
                )
            )
        )
        self.proxy_edit.setText(str(_setting(settings, "proxy", "proxy_url", default="") or ""))
        self.autostart_toggle.setChecked(
            bool(_setting(settings, "start_on_boot", "autostart", default=False))
        )
        self.tray_toggle.setChecked(bool(_setting(settings, "minimize_to_tray", default=True)))
        self.notification_toggle.setChecked(
            bool(
                _setting(settings, "notifications", "notifications_enabled", "notify", default=True)
            )
        )
        self.seed_toggle.setChecked(
            bool(
                _setting(
                    settings,
                    "seed_after_complete",
                    "seed_after_completion",
                    "seed_enabled",
                    default=False,
                )
            )
        )
        self.seed_minutes.setValue(
            int(_setting(settings, "seed_minutes", "seed_time_minutes", default=30))
        )
        self.port_spin.setValue(int(_setting(settings, "listen_port", "port", default=51413)))
        self.metadata_timeout_spin.setValue(
            int(_setting(settings, "bt_metadata_timeout_seconds", default=120))
        )
        self.stall_timeout_spin.setValue(
            max(1, int(_setting(settings, "bt_stall_timeout_seconds", default=600)) // 60)
        )
        requested_theme = str(_setting(settings, "theme", default="light")).lower()
        index = self.theme_combo.findData(requested_theme)
        self.theme_combo.blockSignals(True)
        self.theme_combo.setCurrentIndex(index if index >= 0 else 0)
        self.theme_combo.blockSignals(False)
        self._seed_toggled(self.seed_toggle.isChecked())
        QTimer.singleShot(
            0,
            lambda value=scroll_value: self.settings_scroll.verticalScrollBar().setValue(
                min(value, self.settings_scroll.verticalScrollBar().maximum())
            ),
        )

    def values(self) -> dict[str, Any]:
        download_directory = self.directory_edit.text().strip()
        poll_interval = self.poll_spin.value()
        proxy = self.proxy_edit.text().strip()
        autostart = self.autostart_toggle.isChecked()
        notifications = self.notification_toggle.isChecked()
        seed_after = self.seed_toggle.isChecked()
        seed_minutes = self.seed_minutes.value()
        return {
            "download_directory": download_directory,
            "download_root": download_directory,
            "max_concurrent_downloads": self.concurrent_spin.value(),
            "poll_interval_minutes": poll_interval,
            "default_poll_interval_minutes": poll_interval,
            "proxy": proxy,
            "proxy_url": proxy or None,
            "start_on_boot": autostart,
            "autostart": autostart,
            "minimize_to_tray": self.tray_toggle.isChecked(),
            "notifications": notifications,
            "notifications_enabled": notifications,
            "seed_after_complete": seed_after,
            "seed_after_completion": seed_after,
            "seed_minutes": seed_minutes,
            "seed_time_minutes": seed_minutes,
            "listen_port": self.port_spin.value(),
            "bt_metadata_timeout_seconds": self.metadata_timeout_spin.value(),
            "bt_stall_timeout_seconds": self.stall_timeout_spin.value() * 60,
            "theme": str(self.theme_combo.currentData()),
        }

    def save(self) -> None:
        if not self.directory_edit.text().strip():
            self.error.emit("请选择默认下载目录。")
            self.directory_edit.setFocus()
            return
        try:
            controller_call(self.controller, "save_settings", self.values())
            self._loaded = self.values()
            self.message.emit("设置已保存")
            self.saved.emit()
        except Exception as exc:
            self.error.emit(f"保存设置失败：{exc}")

    def _browse_directory(self) -> None:
        start = self.directory_edit.text().strip() or str(Path.home())
        selected = QFileDialog.getExistingDirectory(self, "选择默认下载目录", start)
        if selected:
            self.directory_edit.setText(selected)

    def _seed_toggled(self, enabled: bool) -> None:
        self.seed_minutes.setEnabled(enabled)
        self.seed_minutes.setToolTip("" if enabled else "开启“下载完成后继续做种”后可设置时长")

    def _preview_theme(self, _index: int) -> None:
        self.theme_changed.emit(str(self.theme_combo.currentData()))

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        c = colors(theme)
        for toggle in self.findChildren(ToggleSwitch):
            toggle.set_theme(theme)
        # Icons created with a fixed neutral colour need refreshing on dark mode.
        for button in self.findChildren(QPushButton):
            if button.text() == "浏览":
                button.setIcon(icon("folder", c.text_muted, 17))
