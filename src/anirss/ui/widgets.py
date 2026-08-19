"""Reusable widgets shared by AniRSS pages."""

from __future__ import annotations

import html
from typing import Any, ClassVar

from PySide6.QtCore import (
    Property,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyleOptionButton,
    QStylePainter,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from .motion import (
    ENTER_DURATION_MS,
    PRESS_DURATION_MS,
    RELEASE_DURATION_MS,
    TOGGLE_DURATION_MS,
    ease_in_out_curve,
    ease_out_curve,
    reduced_motion_requested,
)
from .resources import icon
from .theme import ThemeColors, colors


def clear_layout(layout: QLayout) -> None:
    """Remove and delete all widgets currently held by *layout*."""

    while layout.count():
        item = layout.takeAt(0)
        if item is None:
            continue
        widget = item.widget()
        child_layout = item.layout()
        if widget is not None:
            widget.deleteLater()
        elif child_layout is not None:
            clear_layout(child_layout)


class JellyButton(QPushButton):
    """Native button with subtle, mouse-only squash and elastic release feedback."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._deform = 0.0
        self._press_motion: QPropertyAnimation | None = None

    def _get_deform(self) -> float:
        return self._deform

    def _set_deform(self, value: float) -> None:
        self._deform = float(value)
        self.update()

    deform = Property(float, _get_deform, _set_deform)

    def _start_motion(self, *, pressed: bool) -> None:
        current = self._press_motion
        self._press_motion = None
        if current is not None:
            current.stop()
            current.deleteLater()
        if reduced_motion_requested():
            self._set_deform(0.0)
            return
        animation = QPropertyAnimation(self, b"deform", self)
        animation.setStartValue(self._deform)
        animation.setEasingCurve(ease_out_curve())
        if pressed:
            animation.setDuration(PRESS_DURATION_MS)
            animation.setEndValue(1.0)
        else:
            animation.setDuration(RELEASE_DURATION_MS)
            animation.setKeyValueAt(0.48, -0.24)
            animation.setEndValue(0.0)
        animation.finished.connect(lambda motion=animation: self._motion_finished(motion))
        self._press_motion = animation
        animation.start()

    def _motion_finished(self, animation: QPropertyAnimation) -> None:
        if self._press_motion is not animation:
            return
        self._press_motion = None
        animation.deleteLater()

    def mousePressEvent(self, event: Any) -> None:
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self._start_motion(pressed=True)

    def mouseReleaseEvent(self, event: Any) -> None:
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self._start_motion(pressed=False)

    def leaveEvent(self, event: Any) -> None:
        super().leaveEvent(event)
        if not self.isDown() and self._deform != 0.0:
            self._start_motion(pressed=False)

    def paintEvent(self, _event: Any) -> None:
        option = QStyleOptionButton()
        self.initStyleOption(option)
        painter = QStylePainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pressed_amount = max(0.0, self._deform)
        rebound_amount = max(0.0, -self._deform)
        scale_x = 1.0 - 0.012 * pressed_amount + 0.006 * rebound_amount
        scale_y = 1.0 - 0.035 * pressed_amount + 0.008 * rebound_amount
        center = self.rect().center()
        painter.translate(center)
        painter.scale(scale_x, scale_y)
        painter.translate(-center)
        painter.drawControl(QStyle.ControlElement.CE_PushButton, option)
        painter.end()


class ToggleSwitch(QAbstractButton):
    """A compact animated switch with native keyboard/click behaviour."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(42, 24)
        self._offset = 3.0
        self._deform = 0.0
        self._theme = "light"
        self._programmatic_change = False
        self._animation = QPropertyAnimation(self, b"offset", self)
        self._animation.setDuration(TOGGLE_DURATION_MS)
        self._animation.setEasingCurve(ease_out_curve())
        self._deform_animation = QPropertyAnimation(self, b"deform", self)
        self._deform_animation.setDuration(TOGGLE_DURATION_MS)
        self._deform_animation.setEasingCurve(ease_out_curve())
        self._animation_group = QParallelAnimationGroup(self)
        self._animation_group.addAnimation(self._animation)
        self._animation_group.addAnimation(self._deform_animation)
        self.toggled.connect(self._animate)

    def _get_offset(self) -> float:
        return self._offset

    def _set_offset(self, value: float) -> None:
        self._offset = value
        self.update()

    offset = Property(float, _get_offset, _set_offset)

    def _get_deform(self) -> float:
        return self._deform

    def _set_deform(self, value: float) -> None:
        self._deform = float(value)
        self.update()

    deform = Property(float, _get_deform, _set_deform)

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        self.update()

    def _animate(self, checked: bool) -> None:
        self._animation_group.stop()
        if self._programmatic_change or reduced_motion_requested():
            self._set_offset(21.0 if checked else 3.0)
            self._set_deform(0.0)
            return
        self._animation.setStartValue(self._offset)
        target = 21.0 if checked else 3.0
        overshoot = 22.4 if checked else 1.6
        self._animation.setKeyValueAt(0.72, overshoot)
        self._animation.setEndValue(target)
        self._deform_animation.setStartValue(self._deform)
        self._deform_animation.setKeyValueAt(0.38, 1.0)
        self._deform_animation.setKeyValueAt(0.72, -0.26)
        self._deform_animation.setEndValue(0.0)
        self._animation_group.start()

    def setChecked(self, checked: bool) -> None:
        self._animation_group.stop()
        self._programmatic_change = True
        try:
            super().setChecked(checked)
            self._set_offset(21.0 if checked else 3.0)
            self._set_deform(0.0)
        finally:
            self._programmatic_change = False

    def paintEvent(self, _event: Any) -> None:
        c = colors(self._theme)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(c.accent if self.isChecked() else c.border_strong))
        painter.drawRoundedRect(QRectF(0, 2, 42, 20), 10, 10)
        painter.setBrush(QColor("#FFFFFF"))
        knob_width = 16.0 + 3.2 * self._deform
        knob_height = 16.0 - 2.0 * self._deform
        knob_x = self._offset - (knob_width - 16.0) / 2.0
        knob_y = 4.0 + (16.0 - knob_height) / 2.0
        painter.drawEllipse(QRectF(knob_x, knob_y, knob_width, knob_height))
        painter.end()


class ElidedLabel(QLabel):
    """Plain-text label that shrinks safely and exposes the full value as a tooltip."""

    def __init__(
        self,
        text: str = "",
        mode: Qt.TextElideMode = Qt.TextElideMode.ElideRight,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._full_text = ""
        self._elide_mode = mode
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)
        self.setText(text)

    def text(self) -> str:
        return self._full_text

    def displayed_text(self) -> str:
        return super().text()

    def setText(self, text: str) -> None:
        self._full_text = str(text)
        self._update_elision()

    def sizeHint(self) -> QSize:
        metrics = self.fontMetrics()
        natural = metrics.horizontalAdvance(self._full_text) + 4
        return QSize(min(520, max(40, natural)), metrics.height() + 4)

    def minimumSizeHint(self) -> QSize:
        return QSize(24, self.fontMetrics().height() + 4)

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self._update_elision()

    def _update_elision(self) -> None:
        available = max(0, self.contentsRect().width())
        if available <= 0:
            rendered = self._full_text
        else:
            rendered = self.fontMetrics().elidedText(
                self._full_text,
                self._elide_mode,
                available,
            )
        super().setText(rendered)
        super().setToolTip(html.escape(self._full_text) if rendered != self._full_text else "")


class ClickableElidedLabel(ElidedLabel):
    """Keyboard-accessible elided label used for compact table links."""

    clicked = Signal()

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent=parent)
        self.setObjectName("LinkLabel")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def mouseReleaseEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: Any) -> None:
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space}:
            self.clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class BadgeLabel(QLabel):
    """A small coloured status pill."""

    _tones: ClassVar[dict[str, tuple[str, str, str, str]]] = {
        "success": ("#E8F8F1", "#17875E", "#19392F", "#69D0A7"),
        "warning": ("#FFF3DE", "#A76608", "#3C301D", "#E9AE58"),
        "danger": ("#FDECEF", "#C53C50", "#412329", "#F17A89"),
        "info": ("#EAF2FF", "#2E70D1", "#1E3049", "#79A8EF"),
        "neutral": ("#F0F1F5", "#656B7B", "#292D38", "#A4A9B7"),
        "accent": ("#EFECFF", "#6549D8", "#302B52", "#A794FF"),
    }

    def __init__(
        self, text: str = "", tone: str = "neutral", parent: QWidget | None = None
    ) -> None:
        super().__init__(text, parent)
        self._tone = tone
        self._theme = "light"
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._restyle()

    def set_tone(self, tone: str) -> None:
        self._tone = tone if tone in self._tones else "neutral"
        self._restyle()

    def setText(self, text: str) -> None:
        super().setText(text)
        if hasattr(self, "_tone"):
            self._update_minimum_size()

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        self._restyle()

    def _restyle(self) -> None:
        light_bg, light_fg, dark_bg, dark_fg = self._tones[self._tone]
        bg, fg = (dark_bg, dark_fg) if self._theme == "dark" else (light_bg, light_fg)
        self.setStyleSheet(
            f"QLabel {{background:{bg}; color:{fg}; border:none; border-radius:9px;"
            "font-size:11px; font-weight:600; padding:2px 7px;}"
        )
        self._update_minimum_size()

    def _update_minimum_size(self) -> None:
        metrics = self.fontMetrics()
        self.setMinimumSize(metrics.horizontalAdvance(self.text()) + 18, metrics.height() + 8)


class PageHeader(QWidget):
    """Title/subtitle pair used at the top of every page."""

    def __init__(self, title: str, subtitle: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PageHeader")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(10)
        self.accent = QFrame()
        self.accent.setObjectName("PageAccent")
        self.accent.setFixedSize(5, 25)
        title_row.addWidget(self.accent, 0, Qt.AlignmentFlag.AlignVCenter)
        self.title = ElidedLabel(title)
        self.title.setObjectName("PageTitle")
        title_row.addWidget(self.title, 1)
        self.subtitle = ElidedLabel(subtitle)
        self.subtitle.setObjectName("PageSubtitle")
        layout.addLayout(title_row)
        layout.addWidget(self.subtitle)


class StatCard(QFrame):
    """Dashboard metric card."""

    def __init__(
        self,
        caption: str,
        value: str = "—",
        icon_name: str = "overview",
        tone: str = "accent",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("StatCard")
        self.setProperty("tone", tone)
        self._icon_name = icon_name
        self._theme = "light"
        self._tone = tone
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(17, 15, 17, 15)
        self.body.setSpacing(9)
        self.accent_line = QFrame()
        self.accent_line.setFixedSize(34, 4)
        self.body.addWidget(self.accent_line)
        top = QHBoxLayout()
        self.caption = ElidedLabel(caption)
        self.caption.setObjectName("CardCaption")
        top.addWidget(self.caption)
        top.addStretch()
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(30, 30)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top.addWidget(self.icon_label)
        self.body.addLayout(top)
        self.value_label = ElidedLabel(value)
        self.value_label.setObjectName("CardNumber")
        self.body.addWidget(self.value_label)
        self.hint = ElidedLabel(" ")
        self.hint.setObjectName("Muted")
        self.body.addWidget(self.hint)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._restyle_icon()

    def set_value(self, value: Any, hint: str = "") -> None:
        self.value_label.setText(str(value))
        self.hint.setText(hint or " ")

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        self._restyle_icon()

    def set_compact(self, compact: bool) -> None:
        self.hint.setVisible(not compact)
        self.accent_line.setVisible(not compact)
        if compact:
            self.body.setContentsMargins(13, 10, 13, 10)
        else:
            self.body.setContentsMargins(17, 15, 17, 15)
        self.body.setSpacing(6 if compact else 10)
        self.value_label.setProperty("compact", compact)
        self.value_label.style().unpolish(self.value_label)
        self.value_label.style().polish(self.value_label)

    def _restyle_icon(self) -> None:
        c = colors(self._theme)
        if self._theme == "dark":
            tones = {
                "accent": (c.accent, c.accent_soft),
                "info": (c.info, "#20304A"),
                "success": (c.success, "#20372F"),
                "warning": (c.warning, "#3B3020"),
            }
        else:
            tones = {
                "accent": (c.accent, c.accent_soft),
                "info": (c.info, "#EAF3FF"),
                "success": (c.success, "#EAF8F2"),
                "warning": (c.warning, "#FFF5E5"),
            }
        foreground, soft = tones.get(self._tone, tones["accent"])
        self.icon_label.setPixmap(icon(self._icon_name, foreground, 19).pixmap(19, 19))
        self.icon_label.setStyleSheet(
            f"background:{soft}; border:1px solid {foreground}; border-radius:10px;"
        )
        self.accent_line.setStyleSheet(f"background:{foreground}; border:none; border-radius:2px;")


class EmptyState(QWidget):
    """Friendly Chinese empty-state placeholder."""

    action_clicked = Signal()

    def __init__(
        self,
        title: str,
        message: str,
        action_text: str = "",
        icon_name: str = "rss",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._icon_name = icon_name
        self._theme = "light"
        self.body = QVBoxLayout(self)
        self.body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body.setContentsMargins(30, 48, 30, 48)
        self.body.setSpacing(8)
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(54, 54)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignHCenter)
        self.title_label = QLabel(title)
        self.title_label.setTextFormat(Qt.TextFormat.PlainText)
        self.title_label.setObjectName("EmptyTitle")
        self.body.addWidget(self.title_label, 0, Qt.AlignmentFlag.AlignHCenter)
        self.detail_label = QLabel(message)
        self.detail_label.setTextFormat(Qt.TextFormat.PlainText)
        self.detail_label.setObjectName("EmptyText")
        self.detail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail_label.setWordWrap(True)
        self.detail_label.setMaximumWidth(520)
        self.body.addWidget(self.detail_label, 0, Qt.AlignmentFlag.AlignHCenter)
        self.action = JellyButton(action_text)
        self.action.setProperty("primary", True)
        self.action.setVisible(bool(action_text))
        self.action.clicked.connect(self.action_clicked)
        self.body.addWidget(self.action, 0, Qt.AlignmentFlag.AlignHCenter)
        self.set_theme("light")

    def set_content(self, title: str, message: str) -> None:
        self.title_label.setText(title)
        self.detail_label.setText(message)

    def set_compact(self, compact: bool) -> None:
        self.icon_label.setVisible(not compact)
        self.detail_label.setVisible(not compact)
        if compact:
            self.body.setContentsMargins(16, 12, 16, 12)
        else:
            self.body.setContentsMargins(30, 48, 30, 48)
        self.body.setSpacing(4 if compact else 8)

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        c = colors(theme)
        self.icon_label.setPixmap(icon(self._icon_name, c.accent, 27).pixmap(27, 27))
        self.icon_label.setStyleSheet(f"background:{c.accent_soft}; border-radius:16px;")


class JellyNavIndicator(QWidget):
    """Paint-only navigation capsule that stretches and settles after a move."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._deform = 0.0
        self._theme = "light"
        self.setFixedSize(8, 30)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def _get_deform(self) -> float:
        return self._deform

    def _set_deform(self, value: float) -> None:
        self._deform = float(value)
        self.update()

    deform = Property(float, _get_deform, _set_deform)

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        self.update()

    def paintEvent(self, _event: Any) -> None:
        c = colors(self._theme)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(c.accent))
        height = 23.0 + 5.0 * self._deform
        width = 4.0 - 0.8 * self._deform
        rect = QRectF(
            (self.width() - width) / 2.0,
            (self.height() - height) / 2.0,
            width,
            height,
        )
        painter.drawRoundedRect(rect, width / 2.0, width / 2.0)
        painter.end()


class Sidebar(QFrame):
    """Left navigation rail with an exclusive button group."""

    page_selected = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(206)
        self._theme = "light"
        self._compact = False
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(15, 20, 15, 16)
        self._layout.setSpacing(6)

        brand = QHBoxLayout()
        self.mark = QLabel("A")
        self.mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mark.setFixedSize(40, 40)
        self.mark.setStyleSheet(
            "background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #9B7BFF,"
            "stop:0.52 #7357F3,stop:1 #4F3CC9);color:white;border-radius:13px;"
            "font-size:18px;font-weight:850;"
        )
        brand.addWidget(self.mark)
        self.brand_names = QWidget()
        names = QVBoxLayout(self.brand_names)
        names.setContentsMargins(0, 0, 0, 0)
        names.setSpacing(0)
        title = QLabel("AniRSS")
        title.setObjectName("BrandTitle")
        subtitle = QLabel("番剧自动追更")
        subtitle.setObjectName("BrandSubtitle")
        names.addWidget(title)
        names.addWidget(subtitle)
        brand.addWidget(self.brand_names)
        brand.addStretch()
        self._layout.addLayout(brand)
        self._layout.addSpacing(18)

        self.section_label = QLabel("工作区")
        self.section_label.setObjectName("SidebarSection")
        self._layout.addWidget(self.section_label)
        self._layout.addSpacing(2)

        self.indicator = JellyNavIndicator(self)
        self._indicator_animation = QPropertyAnimation(self.indicator, b"pos", self)
        self._indicator_animation.setDuration(ENTER_DURATION_MS)
        self._indicator_animation.setEasingCurve(ease_in_out_curve())
        self._indicator_deform_animation = QPropertyAnimation(self.indicator, b"deform", self)
        self._indicator_deform_animation.setDuration(ENTER_DURATION_MS)
        self._indicator_deform_animation.setEasingCurve(ease_out_curve())
        self._indicator_group = QParallelAnimationGroup(self)
        self._indicator_group.addAnimation(self._indicator_animation)
        self._indicator_group.addAnimation(self._indicator_deform_animation)

        self.buttons: list[JellyButton] = []
        self._button_labels: list[str] = []
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        items = [("概览", "overview"), ("订阅", "rss"), ("下载", "download"), ("设置", "settings")]
        for index, (text, icon_name) in enumerate(items):
            button = JellyButton(text)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setMinimumHeight(46)
            button.setProperty("iconName", icon_name)
            self.group.addButton(button, index)
            self.buttons.append(button)
            self._button_labels.append(text)
            self._layout.addWidget(button)
        self.buttons[0].setChecked(True)
        self.group.idClicked.connect(self._button_selected)
        self._layout.addStretch()

        self.footer_card = QFrame()
        self.footer_card.setObjectName("SidebarFooter")
        footer_layout = QVBoxLayout(self.footer_card)
        footer_layout.setContentsMargins(10, 9, 10, 9)
        self.footer = QLabel(f"开源 · 本地优先\nv{__version__}")
        self.footer.setObjectName("SidebarFooterText")
        self.footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer_layout.addWidget(self.footer)
        self._layout.addWidget(self.footer_card)
        self.set_theme("light")
        QTimer.singleShot(0, self._sync_indicator)

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        c = colors(theme)
        self.indicator.set_theme(theme)
        for button in self.buttons:
            button.setIcon(icon(str(button.property("iconName")), c.text_muted, 20))
            button.setIconSize(QSize(20, 20))

    def select(self, index: int) -> None:
        if 0 <= index < len(self.buttons):
            self.buttons[index].setChecked(True)
            self._move_indicator(index, animate=True)
            self.page_selected.emit(index)

    def select_without_animation(self, index: int) -> None:
        if 0 <= index < len(self.buttons):
            self.buttons[index].setChecked(True)
            self._move_indicator(index, animate=False)

    def set_compact(self, compact: bool) -> None:
        if compact == self._compact:
            return
        self._compact = compact
        self._indicator_group.stop()
        self.setFixedWidth(88 if compact else 206)
        self.brand_names.setVisible(not compact)
        self.section_label.setVisible(not compact)
        self.footer_card.setVisible(not compact)
        self._layout.setContentsMargins(12 if compact else 15, 20, 12 if compact else 15, 16)
        for button, label in zip(self.buttons, self._button_labels, strict=True):
            button.setText("" if compact else label)
            button.setToolTip(label if compact else "")
            button.setProperty("compact", compact)
            button.style().unpolish(button)
            button.style().polish(button)
        QTimer.singleShot(0, self._sync_indicator)

    def _button_selected(self, index: int) -> None:
        self._move_indicator(index, animate=True)
        self.page_selected.emit(index)

    def _move_indicator(self, index: int, *, animate: bool) -> None:
        if not 0 <= index < len(self.buttons):
            return
        button = self.buttons[index]
        target = QPoint(2, button.geometry().center().y() - self.indicator.height() // 2)
        self.indicator.raise_()
        self._indicator_group.stop()
        if animate and not reduced_motion_requested() and self.isVisible():
            self._indicator_animation.setStartValue(self.indicator.pos())
            self._indicator_animation.setEndValue(target)
            self._indicator_deform_animation.setStartValue(self.indicator._get_deform())
            self._indicator_deform_animation.setKeyValueAt(0.36, 1.0)
            self._indicator_deform_animation.setKeyValueAt(0.72, -0.24)
            self._indicator_deform_animation.setEndValue(0.0)
            self._indicator_group.start()
        else:
            self.indicator.move(target)
            self.indicator._set_deform(0.0)

    def _sync_indicator(self) -> None:
        index = self.group.checkedId()
        self._move_indicator(index if index >= 0 else 0, animate=False)

    def showEvent(self, event: Any) -> None:
        super().showEvent(event)
        self._sync_indicator()

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self._sync_indicator()


class RingIndicator(QWidget):
    """Minimal circular progress indicator used for active downloads."""

    def __init__(self, value: int = 0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._value = max(0, min(100, value))
        self._theme = "light"
        self.setFixedSize(42, 42)

    def set_value(self, value: int) -> None:
        self._value = max(0, min(100, value))
        self.update()

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        self.update()

    def paintEvent(self, _event: Any) -> None:
        c: ThemeColors = colors(self._theme)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(4, 4, 34, 34)
        pen = QPen(QColor(c.border), 4)
        painter.setPen(pen)
        painter.drawArc(rect, 0, 360 * 16)
        pen.setColor(QColor(c.accent))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(rect, 90 * 16, -int(360 * 16 * self._value / 100))
        painter.setPen(QColor(c.text))
        font = QFont(self.font())
        font.setPointSize(7)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, str(self._value))
        painter.end()
