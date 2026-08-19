"""Small vector assets and the application mark used by the desktop interface.

Navigation icons are rendered from tiny SVG snippets at runtime and therefore
remain crisp on HiDPI displays. The packaged application mark uses the shared
PNG asset with a code-drawn fallback for minimal source installations.
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from ..paths import resource_path

_PATHS: dict[str, str] = {
    "overview": '<rect x="4" y="4" width="6" height="6" rx="1"/><rect x="14" y="4" width="6" height="6" rx="1"/><rect x="4" y="14" width="6" height="6" rx="1"/><rect x="14" y="14" width="6" height="6" rx="1"/>',
    "rss": '<path d="M5 18.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Z"/><path d="M4 10a10 10 0 0 1 10 10" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/><path d="M4 5a15 15 0 0 1 15 15" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/>',
    "download": '<path d="M12 3v12m0 0 4.5-4.5M12 15l-4.5-4.5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/><path d="M5 19h14" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/>',
    "settings": '<path d="M9.3 3.5h5.4l.7 2.3 2.1 1.2 2.3-.5 2.7 4.7-1.6 1.8v2.4l1.6 1.8-2.7 4.7-2.3-.5-2.1 1.2-.7 2.3H9.3l-.7-2.3-2.1-1.2-2.3.5-2.7-4.7 1.6-1.8V13l-1.6-1.8 2.7-4.7 2.3.5 2.1-1.2.7-2.3Z" transform="scale(.8) translate(3 1)" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" stroke-width="2"/>',
    "refresh": '<path d="M19 7v5h-5M5 17v-5h5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M18 11a7 7 0 0 0-12-4L5 8m1 5a7 7 0 0 0 12 4l1-1" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
    "plus": '<path d="M12 5v14M5 12h14" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/>',
    "edit": '<path d="m5 16-.8 4 4-.8L19 6.4 15.6 3 5 13.6V16Z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><path d="m13.7 5 3.3 3.3" fill="none" stroke="currentColor" stroke-width="2"/>',
    "delete": '<path d="M5 7h14M9 7V4h6v3m2 0-1 13H8L7 7m3 4v5m4-5v5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
    "pause": '<path d="M8 5v14M16 5v14" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"/>',
    "play": '<path d="m8 5 11 7-11 7V5Z"/>',
    "folder": '<path d="M3 7h7l2 2h9v10H3V7Z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>',
    "check": '<path d="m5 12 4 4L19 6" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6" fill="none" stroke="currentColor" stroke-width="2"/><path d="m15 15 5 5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
    "clock": '<circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 7v5l3 2" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
    "bell": '<path d="M6 17h12l-1.5-2v-4.5a4.5 4.5 0 0 0-9 0V15L6 17Zm4 3h4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
    "arrow": '<path d="m9 5 7 7-7 7" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>',
    "back": '<path d="m15 5-7 7 7 7" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>',
    "close": '<path d="m6 6 12 12M18 6 6 18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/>',
    "tray": '<path d="M5 18h14M7 18v-6a5 5 0 0 1 10 0v6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><path d="M12 3v2" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
}


@lru_cache(maxsize=256)
def icon(name: str, color: str = "#667085", size: int = 24) -> QIcon:
    """Return a theme-coloured vector icon."""

    paths = _PATHS.get(name, _PATHS["overview"])
    # SVG uses currentColor for strokes, while filled paths inherit ``fill``.
    body = paths.replace("currentColor", color)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" '
        f'height="{size}" viewBox="0 0 24 24" fill="{color}">{body}</svg>'
    )
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


def app_icon(size: int = 64) -> QIcon:
    """Load AniRSS' application mark, with a code-only fallback."""

    asset = resource_path("resources/icons/anirss.png")
    if asset.is_file():
        loaded = QIcon(str(asset))
        if not loaded.isNull():
            return loaded

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#7C5CFC"))
    painter.drawRoundedRect(2, 2, size - 4, size - 4, size * 0.24, size * 0.24)
    painter.setBrush(QColor("#FFFFFF"))
    painter.drawEllipse(int(size * 0.24), int(size * 0.62), int(size * 0.12), int(size * 0.12))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    from PySide6.QtGui import QPen

    pen = QPen(QColor("#FFFFFF"), max(2, size // 14))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    rect = int(size * 0.54)
    painter.drawArc(int(size * 0.24), int(size * 0.24), rect, rect, 0, 90 * 16)
    painter.drawArc(
        int(size * 0.24), int(size * 0.40), int(size * 0.38), int(size * 0.38), 0, 90 * 16
    )
    painter.end()
    return QIcon(pixmap)
