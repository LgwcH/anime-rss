"""Launch a local UI preview with sample data.

Run with ``python -m anirss.ui`` after installing PySide6.  The regular
application entry point injects the real backend controller instead.
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .controller import DemoController
from .main_window import MainWindow


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("AniRSS")
    app.setOrganizationName("AniRSS")
    controller = DemoController()
    window = MainWindow(controller)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
