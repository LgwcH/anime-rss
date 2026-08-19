"""System tray integration for background RSS monitoring."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from .resources import app_icon


class TrayController(QObject):
    """Own the tray icon and expose UI-neutral actions as signals."""

    show_requested = Signal()
    refresh_requested = Signal()
    quit_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.icon = QSystemTrayIcon(app_icon(64), parent)
        self.icon.setToolTip("AniRSS · 番剧自动追更")
        menu = QMenu(parent)
        show_action = QAction("打开 AniRSS", menu)
        show_action.triggered.connect(self.show_requested)
        refresh_action = QAction("立即刷新订阅", menu)
        refresh_action.triggered.connect(self.refresh_requested)
        quit_action = QAction("退出", menu)
        quit_action.triggered.connect(self.quit_requested)
        menu.addAction(show_action)
        menu.addAction(refresh_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.icon.setContextMenu(menu)
        self.icon.activated.connect(self._activated)

    @property
    def available(self) -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    def show(self) -> None:
        if self.available:
            self.icon.show()

    def hide(self) -> None:
        self.icon.hide()

    def notify(self, title: str, message: str, timeout_ms: int = 4500) -> None:
        if self.available and self.icon.isVisible():
            self.icon.showMessage(
                title, message, QSystemTrayIcon.MessageIcon.Information, timeout_ms
            )

    def update_status(self, active: int = 0, speed: str = "") -> None:
        suffix = f"\n{active} 个任务 · {speed}" if active else "\n当前没有活动下载"
        self.icon.setToolTip(f"AniRSS · 番剧自动追更{suffix}")

    def _activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in {
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        }:
            self.show_requested.emit()
