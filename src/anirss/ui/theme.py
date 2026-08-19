"""Light and dark visual themes for AniRSS."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QWidget


@dataclass(frozen=True)
class ThemeColors:
    window: str
    sidebar: str
    surface: str
    surface_alt: str
    surface_hover: str
    border: str
    border_strong: str
    text: str
    text_muted: str
    accent: str
    accent_hover: str
    accent_soft: str
    success: str
    warning: str
    danger: str
    info: str


LIGHT = ThemeColors(
    window="#F1F2F8",
    sidebar="#F8F7FD",
    surface="#FFFFFF",
    surface_alt="#F6F5FB",
    surface_hover="#ECEAF6",
    border="#E1DFEA",
    border_strong="#C9C5D7",
    text="#202231",
    text_muted="#727589",
    accent="#7357EE",
    accent_hover="#6042DA",
    accent_soft="#EEE9FF",
    success="#199A69",
    warning="#C27A17",
    danger="#D44B61",
    info="#367FE4",
)

DARK = ThemeColors(
    window="#0D0E16",
    sidebar="#141522",
    surface="#191B28",
    surface_alt="#202230",
    surface_hover="#2A2C3C",
    border="#303242",
    border_strong="#45485C",
    text="#F3F2F8",
    text_muted="#A09FB2",
    accent="#A18BFF",
    accent_hover="#B19EFF",
    accent_soft="#342D58",
    success="#56CAA0",
    warning="#E7AD56",
    danger="#F07888",
    info="#70A8F3",
)


def colors(theme: str) -> ThemeColors:
    return DARK if theme.lower() in {"dark", "深色"} else LIGHT


def build_stylesheet(theme: str = "light") -> str:
    c = colors(theme)
    return f"""
    * {{
        font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
        font-size: 13px;
        color: {c.text};
    }}
    QMainWindow, QWidget#AppRoot {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
            stop:0 {c.window}, stop:1 {c.surface_alt});
    }}
    QWidget#Workspace {{ background: transparent; }}
    QWidget#Sidebar {{
        background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
            stop:0 {c.sidebar}, stop:1 {c.surface_alt});
        border-right: 1px solid {c.border};
    }}
    QFrame#TopBar {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
            stop:0 {c.surface}, stop:1 {c.surface_alt});
        border-bottom: 1px solid {c.border};
    }}
    QFrame#ContextDot {{ background: {c.accent}; border: 3px solid {c.accent_soft}; border-radius: 5px; }}
    QLabel#BrandTitle {{ font-size: 19px; font-weight: 800; }}
    QLabel#BrandSubtitle, QLabel#Muted, QLabel[muted="true"] {{ color: {c.text_muted}; }}
    QLabel#SidebarSection {{ color: {c.text_muted}; font-size: 10px; font-weight: 750; }}
    QLabel#SidebarFooterText {{ color: {c.text_muted}; font-size: 10px; }}
    QLabel#PageTitle {{ font-size: 27px; font-weight: 800; }}
    QLabel#PageSubtitle {{ color: {c.text_muted}; font-size: 13px; }}
    QFrame#PageAccent {{ background: {c.accent}; border: none; border-radius: 2px; }}
    QLabel#SectionTitle {{ font-size: 16px; font-weight: 700; }}
    QLabel#CardNumber {{ font-size: 29px; font-weight: 800; }}
    QLabel#CardNumber[compact="true"] {{ font-size: 20px; }}
    QLabel#CardCaption {{ color: {c.text_muted}; font-size: 12px; }}
    QLabel#EmptyTitle {{ font-size: 16px; font-weight: 650; }}
    QLabel#EmptyText {{ color: {c.text_muted}; }}

    QFrame#Card, QFrame#SettingsGroup, QFrame#ListCard,
    QFrame#StatCard, QFrame#HeroCard, QFrame#DetailCard {{
        background: {c.surface};
        border: 1px solid {c.border};
        border-radius: 18px;
    }}
    QFrame#HeroCard {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
            stop:0 {c.accent_soft}, stop:0.42 {c.surface}, stop:1 {c.surface});
        border-color: {c.border_strong};
    }}
    QFrame#DetailCard {{ background: {c.surface_alt}; }}
    QFrame#FolderToolbar {{
        background: {c.surface_alt}; border: 1px solid {c.border}; border-radius: 14px;
    }}
    QFrame#SidebarFooter {{
        background: {c.surface}; border: 1px solid {c.border}; border-radius: 12px;
    }}
    QFrame#ListCard:hover {{ border-color: {c.border_strong}; background: {c.surface_alt}; }}
    QFrame#Toolbar {{ background: transparent; border: none; }}
    QFrame#Divider {{ background: {c.border}; min-height: 1px; max-height: 1px; }}

    QPushButton {{
        background: {c.surface}; border: 1px solid {c.border_strong};
        border-radius: 12px; padding: 9px 14px; font-weight: 650;
    }}
    QPushButton:hover {{ background: {c.surface_hover}; border-color: {c.accent}; }}
    QPushButton:pressed {{ background: {c.accent_soft}; }}
    QPushButton:disabled {{ color: {c.text_muted}; background: {c.surface_alt}; border-color: {c.border}; }}
    QPushButton[primary="true"] {{ background: {c.accent}; color: white; border-color: {c.accent}; }}
    QPushButton[primary="true"]:hover {{ background: {c.accent_hover}; border-color: {c.accent_hover}; }}
    QPushButton[danger="true"] {{ color: {c.danger}; }}
    QPushButton[flat="true"] {{ background: transparent; border-color: transparent; padding: 6px; }}
    QPushButton[flat="true"]:hover {{ background: {c.surface_hover}; }}
    QPushButton#NavButton {{
        text-align: left; padding: 11px 13px; border: 1px solid transparent; border-radius: 14px;
        background: transparent; color: {c.text_muted}; font-weight: 550;
    }}
    QPushButton#NavButton:hover {{ background: {c.surface_hover}; color: {c.text}; border-color: {c.border}; }}
    QPushButton#NavButton:checked {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
            stop:0 {c.accent_soft}, stop:1 {c.surface});
        color: {c.accent}; border-color: {c.border_strong}; font-weight: 700;
    }}
    QPushButton#NavButton[compact="true"] {{ text-align: center; padding: 10px; }}
    QFrame#NavIndicator {{ background: {c.accent}; border: none; border-radius: 1px; }}
    QLabel#LinkLabel {{ color: {c.text}; font-weight: 650; }}
    QLabel#LinkLabel:hover {{ color: {c.accent}; }}
    QLabel#LinkLabel:focus {{ color: {c.accent}; }}
    QLabel#StatusChip {{
        color: {c.text_muted}; background: {c.surface}; border: 1px solid {c.border};
        border-radius: 12px; padding: 6px 10px;
    }}

    QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        background: {c.surface_alt}; border: 1px solid {c.border};
        border-radius: 12px; padding: 8px 10px; selection-background-color: {c.accent};
    }}
    QLineEdit:hover, QPlainTextEdit:hover, QSpinBox:hover, QComboBox:hover {{ border-color: {c.border_strong}; }}
    QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{ border: 1px solid {c.accent}; background: {c.surface}; }}
    QLineEdit[invalid="true"] {{ border-color: {c.danger}; }}
    QComboBox::drop-down {{ border: none; width: 26px; }}
    QComboBox QAbstractItemView {{ background: {c.surface}; border: 1px solid {c.border}; selection-background-color: {c.accent_soft}; }}

    QCheckBox {{ spacing: 8px; }}
    QCheckBox::indicator {{ width: 17px; height: 17px; border: 1px solid {c.border_strong}; border-radius: 5px; background: {c.surface_alt}; }}
    QCheckBox::indicator:hover {{ border-color: {c.accent}; }}
    QCheckBox::indicator:checked {{ background: {c.accent}; border-color: {c.accent}; image: none; }}

    QTableWidget {{
        background: {c.surface}; alternate-background-color: {c.surface_alt};
        border: 1px solid {c.border}; border-radius: 17px; gridline-color: transparent;
        selection-background-color: {c.accent_soft}; selection-color: {c.text};
    }}
    QTableWidget::item {{ padding: 9px; border-bottom: 1px solid {c.border}; }}
    QHeaderView::section {{
        background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
            stop:0 {c.surface_alt}, stop:1 {c.surface});
        color: {c.text_muted}; border: none; border-bottom: 1px solid {c.border};
        padding: 11px; font-weight: 700;
    }}
    QTableCornerButton::section {{ background: {c.surface_alt}; border: none; }}

    QProgressBar {{ background: {c.surface_alt}; border: none; border-radius: 4px; height: 8px; text-align: center; color: transparent; }}
    QProgressBar::chunk {{ background: {c.accent}; border-radius: 4px; }}
    QSplitter::handle:vertical {{ background: {c.border}; height: 2px; margin: 3px 42%; }}
    QScrollArea {{ border: none; background: transparent; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {c.border_strong}; min-height: 30px; border-radius: 4px; }}
    QScrollBar::handle:vertical:hover {{ background: {c.accent}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QToolTip {{ background: {c.text}; color: {c.surface}; border: none; border-radius: 7px; padding: 6px 8px; }}
    QStatusBar {{ background: {c.surface}; border-top: 1px solid {c.border}; color: {c.text_muted}; }}
    QMenu {{ background: {c.surface}; border: 1px solid {c.border}; border-radius: 8px; padding: 5px; }}
    QMenu::item {{ padding: 7px 28px 7px 10px; border-radius: 5px; }}
    QMenu::item:selected {{ background: {c.accent_soft}; }}
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
