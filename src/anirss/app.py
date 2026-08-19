"""AniRSS desktop application entry point."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import cast

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from . import __version__
from .core.service import AniRSSService
from .desktop_controller import DesktopController
from .logging_setup import configure_logging
from .paths import app_data_dir
from .single_instance import AlreadyRunningError, SingleInstanceLock
from .ui import DemoController, MainWindow


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="anirss",
        description="RSS 驱动的番剧自动下载管理器",
    )
    parser.add_argument("--data-dir", help="覆盖数据库和日志目录")
    parser.add_argument("--minimized", action="store_true", help="启动后最小化到系统托盘")
    parser.add_argument("--demo", action="store_true", help="使用示例数据预览界面")
    parser.add_argument("--verbose", action="store_true", help="记录调试级日志")
    parser.add_argument("--version", action="version", version=f"AniRSS {__version__}")
    return parser


def create_application(
    argv: Sequence[str] | None = None,
) -> tuple[QApplication, MainWindow, DesktopController | DemoController]:
    """Build the application without entering Qt's event loop (useful in tests)."""

    raw_args = list(sys.argv[1:] if argv is None else argv)
    options = _parser().parse_args(raw_args)
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    existing_app = QApplication.instance()
    app = (
        cast(QApplication, existing_app)
        if existing_app is not None
        else QApplication([sys.argv[0], *raw_args])
    )
    app.setApplicationName("AniRSS")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("AniRSS Contributors")
    app.setDesktopFileName("org.anirss.desktop")

    if options.demo:
        controller: DesktopController | DemoController = DemoController()
    else:
        data_directory = app_data_dir(options.data_dir)
        instance_lock = SingleInstanceLock(data_directory / "anirss.instance.lock")
        if not instance_lock.acquire():
            raise AlreadyRunningError(
                "another AniRSS instance is already using this data directory"
            )
        configure_logging(data_directory, verbose=options.verbose)
        try:
            service = AniRSSService(database_path=data_directory / "anirss.db")
            controller = DesktopController(service, instance_lock=instance_lock)
            controller.start()
        except Exception:
            instance_lock.release()
            raise

    window = MainWindow(controller)
    if isinstance(controller, DesktopController):
        app.aboutToQuit.connect(controller.close)
    start_minimized = bool(options.minimized)
    if isinstance(controller, DesktopController):
        start_minimized = start_minimized or controller.service.get_settings().launch_minimized
    if start_minimized and window.tray.available:
        window.hide()
    else:
        window.show()
    return app, window, controller


def main(argv: Sequence[str] | None = None) -> int:
    if sys.platform != "win32":
        print("AniRSS 仅支持 Windows 10/11。", file=sys.stderr)
        return 1

    # Helps Windows choose the packaged app icon/group independently of python.exe.
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("org.anirss.desktop")
    except (AttributeError, OSError):
        pass
    try:
        app, _window, _controller = create_application(argv)
    except AlreadyRunningError:
        existing_app = QApplication.instance()
        if existing_app is not None:
            QMessageBox.information(
                None,
                "AniRSS 已在运行",
                "另一个 AniRSS 窗口正在使用同一数据目录。请从任务栏或系统托盘打开它。",
            )
        else:  # pragma: no cover - create_application constructs Qt first
            print("AniRSS 已在运行。", file=sys.stderr)
        return 1
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
