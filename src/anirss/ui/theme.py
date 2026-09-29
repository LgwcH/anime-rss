"""Light and dark visual themes for AniRSS (08-compact-pro design)."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap, QPolygonF
from PySide6.QtWidgets import QApplication, QWidget


@dataclass(frozen=True)
class ThemeColors:
    window: str
    panel: str
    line: str
    line2: str
    text: str
    text2: str
    text3: str
    accent: str
    accent_hover: str
    accent_soft: str
    hover: str
    selected: str
    track: str
    wait: str
    success: str
    warning: str
    danger: str
    info: str

    # Compatibility aliases used by older widgets.
    @property
    def sidebar(self) -> str:
        return self.window

    @property
    def surface(self) -> str:
        return self.panel

    @property
    def surface_alt(self) -> str:
        return self.hover

    @property
    def surface_hover(self) -> str:
        return self.track

    @property
    def border(self) -> str:
        return self.line

    @property
    def border_strong(self) -> str:
        return self.line2

    @property
    def text_muted(self) -> str:
        return self.text2


LIGHT = ThemeColors(
    window="#FAFAFA",
    panel="#FFFFFF",
    line="#E1E4E8",
    line2="#D0D7DE",
    text="#24292F",
    text2="#57606A",
    text3="#8C959F",
    accent="#0969DA",
    accent_hover="#0757BA",
    accent_soft="#DDF0FF",
    hover="#F6F8FA",
    selected="#EFF1F3",
    track="#EAEEF2",
    wait="#C3CBD2",
    success="#1A7F37",
    warning="#9A6700",
    danger="#CF222E",
    info="#0969DA",
)

DARK = ThemeColors(
    window="#0D1117",
    panel="#161B22",
    line="#21262D",
    line2="#30363D",
    text="#E6EDF3",
    text2="#9198A1",
    text3="#6E7681",
    accent="#4493F8",
    accent_hover="#58A6FF",
    accent_soft="#12315E",
    hover="#1C2129",
    selected="#21262D",
    track="#21262D",
    wait="#3D444D",
    success="#3FB950",
    warning="#D29922",
    danger="#F85149",
    info="#4493F8",
)


def colors(theme: str) -> ThemeColors:
    return DARK if theme.lower() in {"dark", "深色"} else LIGHT


def _spin_arrow_asset(theme: str, direction: str, *, disabled: bool = False) -> str:
    """Render a small triangle PNG for spin-box arrows and cache it on disk.

    Qt style sheets cannot draw triangles (the CSS border trick renders as
    solid bars), so the arrows are painted once per theme into a temp cache
    and referenced from QSS by path.
    """

    c = colors(theme)
    suffix = "disabled" if disabled else "normal"
    target = Path(tempfile.gettempdir()) / "anirss-theme-assets" / theme
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"spin-{direction}-{suffix}.png"
    if path.is_file():
        return path.as_posix()

    color = QColor(c.text3 if disabled else c.text2)
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    if direction == "up":
        points = [(8.0, 4.5), (12.5, 11.5), (3.5, 11.5)]
    else:
        points = [(8.0, 11.5), (3.5, 4.5), (12.5, 4.5)]
    painter.drawPolygon(QPolygonF([QPointF(x, y) for x, y in points]))
    painter.end()
    pixmap.save(str(path))
    return path.as_posix()


def build_stylesheet(theme: str = "light") -> str:
    c = colors(theme)
    arrow_up = _spin_arrow_asset(theme, "up")
    arrow_down = _spin_arrow_asset(theme, "down")
    arrow_up_disabled = _spin_arrow_asset(theme, "up", disabled=True)
    arrow_down_disabled = _spin_arrow_asset(theme, "down", disabled=True)
    return f"""
    * {{
        font-family: "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif;
        font-size: 13px;
        color: {c.text};
    }}
    QMainWindow, QWidget#AppRoot {{ background: {c.window}; }}
    QDialog {{ background: {c.panel}; }}
    QWidget#Workspace {{ background: {c.panel}; }}

    /* ---------- 顶栏 ---------- */
    QFrame#TopBar {{ background: {c.window}; border-bottom: 1px solid {c.line}; }}
    QLabel#LogoBlock {{
        background: {c.text}; color: {c.panel}; border-radius: 3px;
        font-size: 10px; font-weight: 700;
    }}
    QLabel#BrandLabel {{ font-size: 14px; font-weight: 600; letter-spacing: 0.2px; }}
    QFrame#VLine {{ background: {c.line2}; max-width: 1px; min-width: 1px; }}
    QLabel#Crumb {{ color: {c.text2}; font-size: 12px; }}
    QLineEdit#TopSearch {{
        background: {c.panel}; border: 1px solid {c.line2}; border-radius: 6px;
        font-size: 12px; padding: 0 10px; selection-background-color: {c.accent};
    }}
    QLineEdit#TopSearch:focus {{ border-color: {c.accent}; }}
    QLabel#ConnStatus {{ color: {c.text2}; font-size: 12px; }}

    /* ---------- 导航 ---------- */
    QFrame#Sidebar {{ background: {c.window}; border-right: 1px solid {c.line}; }}
    QLabel#NavLabel {{ color: {c.text3}; font-size: 12px; padding: 0 10px; }}
    #NavItem {{
        background: transparent; border: none; border-radius: 6px;
        color: {c.text2}; font-size: 13px;
    }}
    #NavItem:hover {{ background: {c.hover}; }}
    #NavItem:checked {{ background: {c.selected}; }}
    #NavItem QLabel {{ color: {c.text2}; font-size: 13px; background: transparent; }}
    #NavItem:checked QLabel#NavText {{ color: {c.text}; font-weight: 600; }}
    QLabel#NavBadge {{
        background: {c.track}; color: {c.text2}; border-radius: 9px;
        font-size: 12px; padding: 0 6px; min-height: 18px; max-height: 18px;
    }}
    QFrame#NavIndicator {{ background: {c.accent}; border: none; border-radius: 1px; }}
    QFrame#NavFooter {{ border-top: 1px solid {c.line}; }}
    QLabel#NavFooterSub {{ color: {c.text3}; font-size: 12px; }}

    /* ---------- 通用文字 ---------- */
    QLabel#Muted, QLabel[muted="true"] {{ color: {c.text3}; font-size: 12px; }}
    QLabel#PageTitle {{ font-size: 14px; font-weight: 600; }}
    QLabel#PageSubtitle {{ color: {c.text3}; font-size: 12px; }}
    QLabel#SectionTitle {{ font-size: 13px; font-weight: 600; }}
    QLabel#SectionCount {{ color: {c.text3}; font-size: 12px; }}
    QLabel#EmptyTitle {{ font-size: 13px; font-weight: 600; }}
    QLabel#EmptyText {{ color: {c.text3}; font-size: 12px; }}
    QLabel#LinkLabel {{ color: {c.text2}; font-size: 12px; }}
    QLabel#LinkLabel:hover {{ color: {c.accent}; }}
    QLabel#KpiLabel {{ color: {c.text3}; font-size: 12px; }}
    QLabel#KpiValue {{ font-size: 20px; font-weight: 600; }}
    QLabel#KpiUnit {{ color: {c.text3}; font-size: 12px; }}
    QLabel#KpiSub {{ color: {c.text2}; font-size: 12px; }}

    /* ---------- 分隔与面板 ---------- */
    QFrame#Divider {{ background: {c.line}; min-height: 1px; max-height: 1px; border: none; }}
    QFrame#HDivider {{ background: {c.line}; min-width: 1px; max-width: 1px; border: none; }}
    QFrame#KpiStrip {{
        background: transparent;
        border-top: 1px solid {c.line}; border-bottom: 1px solid {c.line};
    }}
    QFrame#KpiCell {{ background: transparent; border: none; }}
    QFrame#KpiCell[first="false"] {{ border-left: 1px solid {c.line}; }}
    QFrame#Card, QFrame#SettingsGroup, QFrame#DetailCard {{
        background: {c.panel}; border: 1px solid {c.line}; border-radius: 6px;
    }}
    QFrame#DetailCard {{ background: {c.hover}; }}
    QFrame#ListPanel {{
        background: {c.panel}; border: none; border-right: 1px solid {c.line};
    }}
    QFrame#ListTools {{ border-bottom: 1px solid {c.line}; }}
    QFrame#FilterBar {{ border-bottom: 1px solid {c.line}; }}
    QFrame#ListFooter {{ border-top: 1px solid {c.line}; }}
    #SubRow {{
        background: transparent; border: none;
        border-bottom: 1px solid {c.line}; border-radius: 0;
    }}
    #SubRow:hover {{ background: {c.hover}; }}
    #SubRow:checked {{ background: {c.selected}; }}
    #SubRow QLabel {{ background: transparent; }}
    #SubRow QLabel#Muted {{ color: {c.text3}; }}
    QLabel#SubProgress {{ color: {c.text2}; }}
    QFrame#Toolbar {{ background: transparent; border: none; }}
    QFrame#InfoGrid {{
        background: transparent;
        border-top: 1px solid {c.line}; border-bottom: 1px solid {c.line};
    }}
    QFrame#InfoCell {{ background: transparent; border: none; }}
    QFrame#InfoCell[first="false"] {{ border-left: 1px solid {c.line}; }}
    QLabel#InfoLabel {{ color: {c.text3}; font-size: 12px; }}
    QLabel#InfoValue {{ color: {c.text}; font-size: 12px; }}

    /* ---------- 按钮 ---------- */
    QPushButton {{
        background: {c.panel}; border: 1px solid {c.line2}; border-radius: 6px;
        padding: 4px 10px; font-size: 12px; color: {c.text};
        min-height: 16px;
    }}
    QPushButton:hover {{ background: {c.hover}; }}
    QPushButton:pressed {{ background: {c.selected}; }}
    QPushButton:disabled {{
        color: {c.text3}; background: {c.hover}; border-color: {c.line};
    }}
    QPushButton[primary="true"] {{
        background: {c.accent}; border-color: {c.accent}; color: #FFFFFF; font-weight: 600;
    }}
    QPushButton[primary="true"]:hover {{ background: {c.accent_hover}; border-color: {c.accent_hover}; }}
    QPushButton[primary="true"]:disabled {{ background: {c.wait}; border-color: {c.wait}; }}
    QPushButton[danger="true"] {{ color: {c.danger}; }}
    QPushButton[flat="true"] {{ background: transparent; border-color: transparent; }}
    QPushButton[flat="true"]:hover {{ background: {c.hover}; }}
    QPushButton#IconButton {{
        background: {c.panel}; border: 1px solid {c.line2}; border-radius: 6px;
        padding: 0; min-width: 26px; max-width: 26px; min-height: 26px; max-height: 26px;
    }}
    QPushButton#IconButton:hover {{ background: {c.hover}; }}
    QPushButton#BlockPrimary {{ min-height: 30px; }}

    /* ---------- 筛选页签（列表栏 / 详情页） ---------- */
    QPushButton#FilterTab {{
        background: transparent; border: none; border-radius: 0;
        border-bottom: 2px solid transparent;
        color: {c.text3}; font-size: 12px; padding: 6px 2px 7px;
    }}
    QPushButton#FilterTab:hover {{ color: {c.text}; }}
    QPushButton#FilterTab:checked {{
        color: {c.text}; font-weight: 600; border-bottom: 2px solid {c.text};
    }}
    QPushButton#TabItem {{
        background: transparent; border: none; border-radius: 0;
        border-bottom: 2px solid transparent;
        color: {c.text2}; font-size: 13px; padding: 8px 0 9px;
    }}
    QPushButton#TabItem:hover {{ color: {c.text}; }}
    QPushButton#TabItem:checked {{
        color: {c.text}; font-weight: 600; border-bottom: 2px solid {c.accent};
    }}

    /* ---------- 输入控件 ---------- */
    QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        background: {c.panel}; border: 1px solid {c.line2}; border-radius: 6px;
        padding: 4px 8px; font-size: 12px; selection-background-color: {c.accent};
    }}
    QLineEdit:hover, QPlainTextEdit:hover, QSpinBox:hover, QComboBox:hover {{
        border-color: {c.text3};
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{
        border-color: {c.accent};
    }}
    QLineEdit[invalid="true"] {{ border-color: {c.danger}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background: {c.panel}; border: 1px solid {c.line2};
        selection-background-color: {c.selected}; selection-color: {c.text};
        outline: none;
    }}
    QSpinBox, QDoubleSpinBox {{ padding-right: 24px; }}
    QSpinBox::up-button, QDoubleSpinBox::up-button,
    QSpinBox::down-button, QDoubleSpinBox::down-button {{
        subcontrol-origin: border;
        width: 20px;
        background: transparent;
        border: none;
        margin: 1px 1px 0 0;
    }}
    QSpinBox::up-button, QDoubleSpinBox::up-button {{
        subcontrol-position: top right;
        border-top-right-radius: 5px;
    }}
    QSpinBox::down-button, QDoubleSpinBox::down-button {{
        subcontrol-position: bottom right;
        border-bottom-right-radius: 5px;
        margin-bottom: 1px;
    }}
    QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
    QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
        background: {c.hover};
    }}
    QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed,
    QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed {{
        background: {c.selected};
    }}
    QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
        image: url("{arrow_up}"); width: 9px; height: 9px;
    }}
    QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
        image: url("{arrow_down}"); width: 9px; height: 9px;
    }}
    QSpinBox::up-arrow:disabled, QDoubleSpinBox::up-arrow:disabled {{
        image: url("{arrow_up_disabled}");
    }}
    QSpinBox::down-arrow:disabled, QDoubleSpinBox::down-arrow:disabled {{
        image: url("{arrow_down_disabled}");
    }}

    QCheckBox {{ spacing: 8px; font-size: 12px; }}
    QCheckBox::indicator {{
        width: 14px; height: 14px; border: 1px solid {c.line2};
        border-radius: 3px; background: {c.panel};
    }}
    QCheckBox::indicator:hover {{ border-color: {c.accent}; }}
    QCheckBox::indicator:checked {{
        background: {c.accent}; border-color: {c.accent}; image: none;
    }}

    /* ---------- 表格 ---------- */
    QTableWidget {{
        background: {c.panel}; alternate-background-color: {c.panel};
        border: none; gridline-color: transparent; font-size: 12px;
        selection-background-color: {c.selected}; selection-color: {c.text};
        outline: none;
    }}
    QTableWidget::item {{
        border-bottom: 1px solid {c.line}; padding: 0 8px; color: {c.text2};
    }}
    QTableWidget::item:selected {{ background: {c.selected}; }}
    QHeaderView::section {{
        background: {c.panel}; color: {c.text3}; font-size: 12px; font-weight: 400;
        border: none; border-bottom: 1px solid {c.line}; padding: 0 8px;
    }}
    QTableCornerButton::section {{ background: {c.panel}; border: none; }}

    /* ---------- 进度条（4px 轨道） ---------- */
    QProgressBar {{
        background: {c.track}; border: none; border-radius: 2px;
        min-height: 4px; max-height: 4px; color: transparent;
    }}
    QProgressBar::chunk {{ background: {c.accent}; border-radius: 2px; }}
    QProgressBar[neutral="true"]::chunk {{ background: {c.text2}; }}

    /* ---------- 滚动与杂项 ---------- */
    QSplitter::handle:vertical {{ background: {c.line}; height: 1px; margin: 2px 42%; }}
    QScrollArea {{ border: none; background: transparent; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
    QScrollBar::handle:vertical {{
        background: {c.line2}; min-height: 30px; border-radius: 4px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {c.text3}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 2px; }}
    QScrollBar::handle:horizontal {{
        background: {c.line2}; min-width: 30px; border-radius: 4px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
    QToolTip {{
        background: {c.text}; color: {c.panel}; border: none;
        border-radius: 4px; padding: 4px 8px; font-size: 12px;
    }}
    QStatusBar {{
        background: {c.window}; border-top: 1px solid {c.line};
        color: {c.text3}; font-size: 12px;
    }}
    QMenu {{
        background: {c.panel}; border: 1px solid {c.line2};
        border-radius: 6px; padding: 4px;
    }}
    QMenu::item {{ padding: 6px 24px 6px 10px; border-radius: 4px; font-size: 12px; }}
    QMenu::item:selected {{ background: {c.hover}; }}
    """


class ThemeManager(QObject):
    """Apply a theme consistently and notify icon-bearing widgets."""

    changed = Signal(str)

    def __init__(self, theme: str = "light", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._theme = "dark" if theme.lower() in {"dark", "深色"} else "light"

    @property
    def theme(self) -> str:
        return self._theme

    @property
    def palette(self) -> ThemeColors:
        return colors(self._theme)

    def apply(self, target: QApplication | QWidget, theme: str | None = None) -> None:
        new_theme = theme or self._theme
        new_theme = "dark" if new_theme.lower() in {"dark", "深色"} else "light"
        self._theme = new_theme
        target.setStyleSheet(build_stylesheet(new_theme))
        self.changed.emit(new_theme)
