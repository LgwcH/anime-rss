"""AniRSS main desktop window (08-compact-pro shell)."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QEvent, Qt, QThreadPool, QTimer
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QKeySequence,
    QPalette,
    QResizeEvent,
    QScreen,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from .controller import DemoController, controller_call
from .data import as_mapping
from .downloads import DownloadsPage
from .motion import AnimatedStackedWidget
from .overview import OverviewPage
from .resources import app_icon, icon
from .settings import SettingsPage
from .subscriptions import SubscriptionsPage
from .theme import ThemeManager, colors
from .tray import TrayController
from .widgets import ElidedLabel, Sidebar, StatusDot
from .widgets import JellyButton as QPushButton
from .worker import FunctionWorker


def _vline() -> QFrame:
    line = QFrame()
    line.setObjectName("VLine")
    line.setFixedSize(1, 16)
    return line


class MainWindow(QMainWindow):
    """Polished Windows-first shell around an injectable backend controller.

    Passing ``None`` creates a :class:`DemoController`, which makes the entire
    interface explorable without network access or a configured downloader.
    """

    PAGE_NAMES = ("概览", "订阅", "下载", "设置")

    def __init__(self, controller: object | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller if controller is not None else DemoController(self)
        self._force_quit = False
        self._initial_load_done = False
        self._tray_hint_shown = False
        self._theme_request = "light"
        self._resolved_theme = "light"
        self._minimize_to_tray = True
        self._notifications = True
        self._refresh_worker: FunctionWorker | None = None
        self._subscription_refresh_worker: FunctionWorker | None = None
        self._subscription_refresh_id: object | None = None
        self._subscription_refresh_name = ""
        self._screen_signal_connected = False
        self._thread_pool = QThreadPool.globalInstance()

        self.setWindowTitle("AniRSS · 番剧自动追更")
        self.setWindowIcon(app_icon(64))
        self._apply_screen_constraints(QApplication.primaryScreen(), initial=True)

        root = QWidget()
        root.setObjectName("AppRoot")
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ---------- 顶栏 (41px) ----------
        self.topbar = QFrame()
        self.topbar.setObjectName("TopBar")
        self.topbar.setFixedHeight(41)
        self.topbar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.top_layout = QHBoxLayout(self.topbar)
        self.top_layout.setContentsMargins(16, 0, 16, 0)
        self.top_layout.setSpacing(10)
        self.logo = QLabel("A")
        self.logo.setObjectName("LogoBlock")
        self.logo.setFixedSize(16, 16)
        self.logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.top_layout.addWidget(self.logo)
        brand = QLabel("AniRSS")
        brand.setObjectName("BrandLabel")
        self.top_layout.addWidget(brand)
        self.top_layout.addWidget(_vline())
        self.breadcrumb = ElidedLabel("概览")
        self.breadcrumb.setObjectName("Crumb")
        self.top_layout.addWidget(self.breadcrumb, 1)
        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("TopSearch")
        self.search_edit.setFixedSize(220, 26)
        self.search_edit.setPlaceholderText("搜索订阅 / 剧集    Ctrl K")
        self.search_edit.returnPressed.connect(self._apply_global_search)
        self.top_layout.addWidget(self.search_edit)
        self.refresh_button = QPushButton()
        self.refresh_button.setObjectName("IconButton")
        self.refresh_button.setFixedSize(26, 26)
        self.refresh_button.setToolTip("刷新全部源 (Ctrl R)")
        self.refresh_button.clicked.connect(self.refresh_all)
        self.top_layout.addWidget(self.refresh_button)
        self.top_layout.addWidget(_vline())
        self.conn_dot = StatusDot("sub")
        self.top_layout.addWidget(self.conn_dot, 0, Qt.AlignmentFlag.AlignVCenter)
        self.refresh_status = ElidedLabel("下载器空闲")
        self.refresh_status.setObjectName("ConnStatus")
        self.refresh_status.setMinimumWidth(120)
        self.refresh_status.setMaximumWidth(240)
        self.top_layout.addWidget(self.refresh_status)
        root_layout.addWidget(self.topbar)

        # ---------- 主体: 导航 + 页面 ----------
        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        root_layout.addWidget(body, 1)

        self.sidebar = Sidebar()
        self.sidebar.page_selected.connect(self._select_page)
        body_layout.addWidget(self.sidebar)

        workspace = QWidget()
        workspace.setObjectName("Workspace")
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)
        body_layout.addWidget(workspace, 1)

        self.pages = AnimatedStackedWidget()
        self.overview_page = OverviewPage(self.controller)
        self.subscriptions_page = SubscriptionsPage(self.controller)
        self.downloads_page = DownloadsPage(self.controller)
        self.settings_page = SettingsPage(self.controller)
        self.page_list = [
            self.overview_page,
            self.subscriptions_page,
            self.downloads_page,
            self.settings_page,
        ]
        for page in self.page_list:
            self.pages.addWidget(page)
            if hasattr(page, "error"):
                page.error.connect(self.show_error)
            if hasattr(page, "message"):
                page.message.connect(self.show_message)
        workspace_layout.addWidget(self.pages, 1)

        self.overview_page.refresh_requested.connect(self.refresh_all)
        self.overview_page.show_all_downloads.connect(lambda: self.sidebar.select(2))
        self.subscriptions_page.changed.connect(self.overview_page.reload)
        self.subscriptions_page.changed.connect(self._update_nav_badges)
        self.subscriptions_page.route_changed.connect(self._subscription_route_changed)
        self.subscriptions_page.refresh_requested.connect(self.refresh_subscription)
        self.subscriptions_page.show_download_requested.connect(self._show_download_task)
        self.downloads_page.changed.connect(self.overview_page.reload)
        self.downloads_page.changed.connect(self._update_nav_badges)
        self.settings_page.theme_changed.connect(self.apply_theme)
        self.settings_page.saved.connect(self._settings_saved)

        self.theme_manager = ThemeManager("light", self)
        self.tray = TrayController(self)
        self.tray.show_requested.connect(self.restore_from_tray)
        self.tray.refresh_requested.connect(self.refresh_all)
        self.tray.quit_requested.connect(self.quit_application)
        self.tray.show()

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(5000)
        self._poll_timer.timeout.connect(self._poll_current_page)
        self._poll_timer.start()

        refresh_action = QAction(self)
        refresh_action.setShortcut("Ctrl+R")
        refresh_action.triggered.connect(self.refresh_all)
        self.addAction(refresh_action)
        settings_action = QAction(self)
        settings_action.setShortcut("Ctrl+,")
        settings_action.triggered.connect(self._open_settings_shortcut)
        self.addAction(settings_action)
        search_action = QAction(self)
        search_action.setShortcut(QKeySequence("Ctrl+K"))
        search_action.triggered.connect(self._focus_search)
        self.addAction(search_action)

        self._connect_controller_signals()
        self._load_initial_settings()
        self._update_icons()
        self._update_nav_badges()
        self.statusBar().showMessage("就绪")

    def _apply_screen_constraints(self, screen: QScreen | None, *, initial: bool = False) -> None:
        available = screen.availableGeometry() if screen is not None else None
        available_width = available.width() if available is not None else 1366
        available_height = available.height() if available is not None else 768
        minimum_width = min(
            920,
            max(700, int(available_width * 0.78)),
            max(1, int(available_width * 0.94)),
        )
        minimum_height = min(
            620,
            max(440, int(available_height * 0.78)),
            max(1, int(available_height * 0.94)),
        )
        initial_width = max(minimum_width, min(1260, int(available_width * 0.92)))
        initial_height = max(minimum_height, min(800, int(available_height * 0.92)))
        self.setMinimumSize(minimum_width, minimum_height)
        if initial:
            self.resize(initial_width, initial_height)
            return
        maximum_width = max(minimum_width, int(available_width * 0.94))
        maximum_height = max(minimum_height, int(available_height * 0.94))
        self.resize(
            min(maximum_width, max(minimum_width, self.width())),
            min(maximum_height, max(minimum_height, self.height())),
        )

    def _connect_optional_signal(self, name: str, slot: Any) -> bool:
        signal = getattr(self.controller, name, None)
        connector = getattr(signal, "connect", None)
        if not callable(connector):
            return False
        try:
            connector(slot)
        except (TypeError, RuntimeError):
            return False
        return True

    def _connect_controller_signals(self) -> None:
        precise_connections = [
            self._connect_optional_signal("subscriptions_changed", self._subscriptions_changed),
            self._connect_optional_signal("downloads_changed", self._downloads_changed),
            self._connect_optional_signal("settings_changed", self._load_initial_settings),
        ]
        if not any(precise_connections):
            self._connect_optional_signal("data_changed", self._reload_visible_data)
        self._connect_optional_signal("notification", self._controller_notification)
        self._connect_optional_signal("error", self.show_error)

    def _subscriptions_changed(self) -> None:
        current = self.pages.currentWidget()
        if current is self.subscriptions_page:
            refresh_detail = not (
                self._subscription_refresh_id is not None
                and self.subscriptions_page.detail_active
                and self.subscriptions_page.detail_view.subscription_id
                != self._subscription_refresh_id
            )
            self.subscriptions_page.reload(refresh_detail=refresh_detail)
        elif current is self.overview_page:
            self.overview_page.reload()
        self._update_nav_badges()

    def _downloads_changed(self) -> None:
        current = self.pages.currentWidget()
        if current is self.downloads_page:
            self.downloads_page.reload()
        elif current is self.overview_page:
            self.overview_page.reload()
        self._update_nav_badges()

    def _load_initial_settings(self) -> None:
        try:
            settings = controller_call(self.controller, "load_settings", default={}) or {}
        except Exception as exc:
            settings = {}
            self.show_error(f"加载设置失败：{exc}")
        normalized = as_mapping(settings)
        if normalized:
            self.settings_page.set_settings(normalized)
            self._minimize_to_tray = bool(normalized.get("minimize_to_tray", True))
            self._notifications = bool(
                normalized.get(
                    "notifications",
                    normalized.get("notifications_enabled", normalized.get("notify", True)),
                )
            )
            self.apply_theme(str(normalized.get("theme", "light")))
        else:
            self.apply_theme("light")

    def _settings_saved(self) -> None:
        values = self.settings_page.values()
        self._minimize_to_tray = bool(values["minimize_to_tray"])
        self._notifications = bool(values["notifications"])
        self.apply_theme(str(values["theme"]))

    def apply_theme(self, requested: str) -> None:
        requested = requested.lower()
        self._theme_request = requested if requested in {"light", "dark", "system"} else "light"
        if self._theme_request == "system":
            app = QApplication.instance()
            palette = app.palette() if isinstance(app, QApplication) else self.palette()
            resolved = (
                "dark" if palette.color(QPalette.ColorRole.Window).lightness() < 128 else "light"
            )
        else:
            resolved = self._theme_request
        self._resolved_theme = resolved
        self.theme_manager.apply(self, resolved)
        self.sidebar.set_theme(resolved)
        for page in self.page_list:
            setter = getattr(page, "set_theme", None)
            if callable(setter):
                setter(resolved)
        self._update_icons()

    def _update_icons(self) -> None:
        c = colors(self._resolved_theme)
        self.refresh_button.setIcon(icon("refresh", c.text2, 14))
        self.conn_dot.set_theme(self._resolved_theme)

    def _select_page(self, index: int, *, animate: bool = True) -> None:
        if not 0 <= index < len(self.page_list):
            return
        self.pages.transition_to(index, animate=animate)
        if index == 1 and self.subscriptions_page.detail_active:
            name = self.subscriptions_page.detail_view.subscription_name
            self.breadcrumb.setText(f"工作台  /  订阅  /  {name}")
        else:
            self.breadcrumb.setText(f"工作台  /  {self.PAGE_NAMES[index]}")
        self._reload_page(index)

    def _open_settings_shortcut(self) -> None:
        self.sidebar.select_without_animation(3)
        self._select_page(3, animate=False)

    def _focus_search(self) -> None:
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def _apply_global_search(self) -> None:
        query = self.search_edit.text().strip()
        if not query:
            return
        self.sidebar.select(1)
        self.subscriptions_page.apply_search(query)

    def _subscription_route_changed(self, name: str) -> None:
        if self.pages.currentWidget() is self.subscriptions_page:
            suffix = f"  /  {name}" if name else ""
            self.breadcrumb.setText(f"工作台  /  订阅{suffix}")

    def _reload_page(self, index: int) -> None:
        page = self.page_list[index]
        reload_method = getattr(page, "reload", None)
        if callable(reload_method):
            reload_method()

    def _reload_visible_data(self) -> None:
        self._reload_page(self.pages.currentIndex())
        if self.pages.currentWidget() is not self.overview_page:
            self.overview_page.reload()

    def _poll_current_page(self) -> None:
        if not self.isVisible():
            return
        index = self.pages.currentIndex()
        if index in {0, 1, 2}:
            self._reload_page(index)
        self._update_tray_status()
        self._update_conn_status()

    def _snapshot(self) -> dict[str, Any]:
        try:
            snapshot = controller_call(self.controller, "dashboard_snapshot", default={}) or {}
            return as_mapping(snapshot)
        except Exception:
            return {}

    def _update_conn_status(self) -> None:
        normalized = self._snapshot()
        if not normalized:
            return
        active = int(normalized.get("active_downloads", normalized.get("downloading", 0)) or 0)
        speed = str(normalized.get("download_speed", normalized.get("speed", "")))
        if active:
            self.refresh_status.setText(f"{active} 个任务 · {speed}")
            self.conn_dot.set_state("run")
        else:
            self.refresh_status.setText("下载器空闲")
            self.conn_dot.set_state("sub")
        subtext = f"v{__version__}"
        if speed and speed not in {"0 B/s", "—"}:
            subtext = f"v{__version__} · 合计 {speed}"
        self.sidebar.set_status(
            f"{active} 个下载中" if active else "下载器空闲",
            subtext,
            active=bool(active),
        )

    def _update_nav_badges(self) -> None:
        try:
            subscriptions = controller_call(self.controller, "list_subscriptions", default=[]) or []
            self.sidebar.set_badge(1, len(subscriptions) or None)
        except Exception:
            pass
        snapshot = self._snapshot()
        if snapshot:
            active = int(snapshot.get("active_downloads", snapshot.get("downloading", 0)) or 0)
            self.sidebar.set_badge(2, active or None)

    def refresh_all(self) -> None:
        if self._refresh_worker is not None or self._subscription_refresh_worker is not None:
            return
        self.refresh_button.setEnabled(False)
        self.overview_page.set_refreshing(True)
        self.refresh_status.setText("正在检查所有订阅")
        worker = FunctionWorker(lambda: controller_call(self.controller, "refresh_all"))
        self._refresh_worker = worker
        worker.signals.succeeded.connect(self._refresh_finished)
        worker.signals.failed.connect(self._refresh_failed)
        self._thread_pool.start(worker)

    def _refresh_finished(self, _result: object = None) -> None:
        self._refresh_worker = None
        self.overview_page.reload()
        self.subscriptions_page.reload()
        self.downloads_page.reload()
        self.overview_page.set_refreshing(False)
        self.refresh_status.setText("刚刚完成刷新")
        self.refresh_button.setEnabled(True)
        self._update_nav_badges()
        self.show_message("所有订阅已刷新", 3500)

    def _refresh_failed(self, detail: str) -> None:
        self._refresh_worker = None
        self.overview_page.set_refreshing(False)
        self.refresh_status.setText("刷新失败")
        self.refresh_button.setEnabled(True)
        self.show_error(f"刷新订阅失败：{detail}")

    def refresh_subscription(self, subscription_id: object) -> None:
        if self._refresh_worker is not None or self._subscription_refresh_worker is not None:
            return
        self._subscription_refresh_id = subscription_id
        self._subscription_refresh_name = self.subscriptions_page.detail_view.subscription_name
        self.subscriptions_page.set_detail_refreshing(subscription_id, True)
        self.refresh_button.setEnabled(False)
        self.refresh_status.setText(f"正在刷新 {self._subscription_refresh_name}")
        worker = FunctionWorker(
            lambda: controller_call(self.controller, "refresh_subscription", subscription_id)
        )
        self._subscription_refresh_worker = worker
        worker.signals.succeeded.connect(self._subscription_refresh_finished)
        worker.signals.failed.connect(self._subscription_refresh_failed)
        self._thread_pool.start(worker)

    def _subscription_refresh_finished(self, _result: object = None) -> None:
        subscription_id = self._subscription_refresh_id
        subscription_name = self._subscription_refresh_name or "该订阅"
        self._subscription_refresh_worker = None
        self._subscription_refresh_id = None
        self._subscription_refresh_name = ""
        if subscription_id is not None:
            self.subscriptions_page.detail_refresh_finished(subscription_id)
        self.downloads_page.reload()
        self.overview_page.reload()
        self.refresh_status.setText(f"刚刚完成 {subscription_name} 的刷新")
        self.refresh_button.setEnabled(True)
        self.show_message(f"“{subscription_name}”的订阅内容已更新", 3500)

    def _subscription_refresh_failed(self, detail: str) -> None:
        subscription_id = self._subscription_refresh_id
        subscription_name = self._subscription_refresh_name or "该订阅"
        self._subscription_refresh_worker = None
        self._subscription_refresh_id = None
        self._subscription_refresh_name = ""
        if subscription_id is not None:
            self.subscriptions_page.set_detail_refreshing(subscription_id, False)
        self.refresh_status.setText(f"{subscription_name} 刷新失败")
        self.refresh_button.setEnabled(True)
        self.show_error(f"刷新“{subscription_name}”失败：{detail}")

    def _show_download_task(self, task_id: object) -> None:
        self.sidebar.select(2)
        self.downloads_page.focus_task(task_id)

    def _update_tray_status(self) -> None:
        normalized = self._snapshot()
        if normalized:
            active = int(normalized.get("active_downloads", normalized.get("downloading", 0)) or 0)
            speed = str(normalized.get("download_speed", normalized.get("speed", "")))
            self.tray.update_status(active, speed)

    def _controller_notification(self, title: str, message: str) -> None:
        self.show_message(f"{title}：{message}")
        if self._notifications:
            self.tray.notify(title, message)

    def show_message(self, message: str, timeout_ms: int = 4500) -> None:
        self.statusBar().showMessage(message, timeout_ms)

    def show_error(self, message: str) -> None:
        self.statusBar().showMessage(message, 7000)
        if self._notifications:
            self.tray.notify("AniRSS 遇到问题", message)

    def restore_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_application(self) -> None:
        self._force_quit = True
        self.tray.hide()
        QApplication.quit()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        handle = self.windowHandle()
        if handle is not None and not self._screen_signal_connected:
            handle.screenChanged.connect(self._apply_screen_constraints)
            self._screen_signal_connected = True
            self._apply_screen_constraints(handle.screen())
        if not self._initial_load_done:
            self._initial_load_done = True
            QTimer.singleShot(0, self._reload_all)

    def _reload_all(self) -> None:
        self.overview_page.reload()
        self.subscriptions_page.reload()
        self.downloads_page.reload()
        self._update_tray_status()
        self._update_conn_status()
        self._update_nav_badges()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if (
            event.type() == QEvent.Type.WindowStateChange
            and self.isMinimized()
            and self._minimize_to_tray
            and self.tray.available
        ):
            QTimer.singleShot(0, self.hide)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if not hasattr(self, "sidebar"):
            return
        compact = event.size().width() < 1120
        self.sidebar.set_compact(compact)
        self.search_edit.setVisible(event.size().width() >= 900)
        self.refresh_status.setVisible(event.size().width() >= 1040)
        self.conn_dot.setVisible(event.size().width() >= 1040)

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._force_quit and self._minimize_to_tray and self.tray.available:
            event.ignore()
            self.hide()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self.tray.notify("AniRSS 仍在运行", "订阅检查和下载会在后台继续。")
            return
        self.tray.hide()
        event.accept()
