"""Reusable widgets shared by AniRSS pages (08-compact-pro design)."""

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
from PySide6.QtGui import QColor, QIcon, QPainter, QPen
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
from .theme import colors


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
        self.setFixedSize(36, 20)
        self._offset = 2.0
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
            self._set_offset(18.0 if checked else 2.0)
            self._set_deform(0.0)
            return
        self._animation.setStartValue(self._offset)
        target = 18.0 if checked else 2.0
        overshoot = 19.4 if checked else 0.6
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
            self._set_offset(18.0 if checked else 2.0)
            self._set_deform(0.0)
        finally:
            self._programmatic_change = False

    def paintEvent(self, _event: Any) -> None:
        c = colors(self._theme)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(c.accent if self.isChecked() else c.line2))
        painter.drawRoundedRect(QRectF(0, 2, 36, 16), 8, 8)
        painter.setBrush(QColor("#FFFFFF"))
        knob_width = 12.0 + 2.4 * self._deform
        knob_height = 12.0 - 1.6 * self._deform
        knob_x = self._offset - (knob_width - 12.0) / 2.0
        knob_y = 4.0 + (12.0 - knob_height) / 2.0
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


# ---------------------------------------------------------------------------
# compact-pro 状态体系: 6px 圆点 + 12px 灰字
# ---------------------------------------------------------------------------

_DOT_STYLES: dict[str, tuple[str, str | None]] = {
    # name -> (fill, outline)
    "run": ("#0969DA", None),  # 下载中: 唯一强调色
    "sub": ("#57606A", None),  # 追番中
    "done": ("transparent", "#8C959F"),  # 已完成: 空心灰圈
    "wait": ("#C3CBD2", None),  # 待处理
    "dead": ("transparent", "#24292F"),  # 源失效/失败: 空心黑圈
}

_TONE_TO_DOT: dict[str, str] = {
    "info": "run",
    "accent": "run",
    "success": "done",
    "warning": "sub",
    "danger": "dead",
    "neutral": "wait",
}


class StatusDot(QWidget):
    """A 6px status dot; the only place colour encodes state."""

    def __init__(self, state: str = "sub", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state if state in _DOT_STYLES else "sub"
        self._theme = "light"
        self.setFixedSize(10, 10)

    def set_state(self, state: str) -> None:
        self._state = state if state in _DOT_STYLES else "sub"
        self.update()

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        self.update()

    def paintEvent(self, _event: Any) -> None:
        c = colors(self._theme)
        fill, outline = _DOT_STYLES[self._state]
        if self._theme == "dark":
            fill = {
                "#0969DA": c.accent,
                "#57606A": c.text2,
                "#C3CBD2": c.wait,
                "#24292F": c.text,
                "transparent": "transparent",
            }[fill]
            if outline == "#8C959F":
                outline = c.text3
            elif outline == "#24292F":
                outline = c.text
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(2.75, 2.75, 4.5, 4.5) if outline else QRectF(2, 2, 6, 6)
        painter.setBrush(QColor(fill))
        if outline:
            pen = QPen(QColor(outline), 1.5)
            painter.setPen(pen)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(rect)
        painter.end()


class BadgeLabel(QWidget):
    """Status text prefixed by a 6px dot (formerly a coloured pill)."""

    _tones: ClassVar[dict[str, str]] = _TONE_TO_DOT

    def __init__(
        self, text: str = "", tone: str = "neutral", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._tone = tone if tone in self._tones else "neutral"
        self._theme = "light"
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.dot = StatusDot(self._tones[self._tone])
        layout.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignVCenter)
        self.label = QLabel(text)
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.label, 0, Qt.AlignmentFlag.AlignVCenter)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._restyle()

    def text(self) -> str:
        return self.label.text()

    def setText(self, text: str) -> None:
        self.label.setText(text)
        if hasattr(self, "_tone"):
            self._update_minimum_size()

    def setTone(self, tone: str) -> None:
        self.set_tone(tone)

    def set_tone(self, tone: str) -> None:
        self._tone = tone if tone in self._tones else "neutral"
        self.dot.set_state(self._tones[self._tone])

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        self.dot.set_theme(theme)
        self._restyle()

    def _restyle(self) -> None:
        c = colors(self._theme)
        self.label.setStyleSheet(f"color:{c.text2}; font-size:12px; background:transparent;")
        self._update_minimum_size()

    def _update_minimum_size(self) -> None:
        metrics = self.label.fontMetrics()
        self.setMinimumSize(metrics.horizontalAdvance(self.label.text()) + 16, metrics.height() + 4)


class CoverAvatar(QLabel):
    """Rounded letter avatar whose muted colour derives from the title."""

    _palette: ClassVar[tuple[str, ...]] = (
        "#7F9B8A",
        "#8A7F9E",
        "#A08A72",
        "#6B7D8C",
        "#9E7F7F",
        "#7A7A72",
        "#728A9E",
        "#967F9B",
    )

    def __init__(self, title: str = "", size: int = 28, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_title(title)

    def set_title(self, title: str) -> None:
        title = str(title or "?")
        letter = title.strip()[:1] or "?"
        colour = self._palette[sum(ord(ch) for ch in title) % len(self._palette)]
        self.setText(letter)
        font_size = max(10, round(self._size * 0.42))
        self.setStyleSheet(
            f"background:{colour}; color:#FFFFFF; border-radius:{min(6, self._size // 7)}px;"
            f"font-size:{font_size}px; font-weight:600;"
        )


class SectionHeader(QWidget):
    """``标题 + 计数`` row with an optional right-aligned action link."""

    action_clicked = Signal()

    def __init__(
        self,
        title: str,
        count: str = "",
        action: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.setFixedHeight(28)
        self.title = QLabel(title)
        self.title.setObjectName("SectionTitle")
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.title)
        self.count = QLabel(count)
        self.count.setObjectName("SectionCount")
        self.count.setTextFormat(Qt.TextFormat.PlainText)
        self.count.setVisible(bool(count))
        layout.addWidget(self.count)
        layout.addStretch()
        self.action = ClickableElidedLabel(action)
        self.action.setVisible(bool(action))
        self.action.clicked.connect(self.action_clicked)
        layout.addWidget(self.action)

    def set_count(self, count: str) -> None:
        self.count.setText(count)
        self.count.setVisible(bool(count))

    def set_action(self, action: str) -> None:
        self.action.setText(action)
        self.action.setVisible(bool(action))


class KpiCell(QFrame):
    """One metric in the overview KPI strip."""

    def __init__(self, caption: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("KpiCell")
        self.setProperty("first", False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(2)
        self.caption = ElidedLabel(caption)
        self.caption.setObjectName("KpiLabel")
        layout.addWidget(self.caption)
        value_row = QHBoxLayout()
        value_row.setContentsMargins(0, 0, 0, 0)
        value_row.setSpacing(3)
        self.value_label = QLabel("—")
        self.value_label.setObjectName("KpiValue")
        value_row.addWidget(self.value_label, 0, Qt.AlignmentFlag.AlignBaseline)
        self.unit_label = QLabel("")
        self.unit_label.setObjectName("KpiUnit")
        value_row.addWidget(self.unit_label, 0, Qt.AlignmentFlag.AlignBaseline)
        value_row.addStretch()
        layout.addLayout(value_row)
        self.hint = ElidedLabel(" ")
        self.hint.setObjectName("KpiSub")
        layout.addWidget(self.hint)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def set_value(self, value: Any, hint: str = "", unit: str = "") -> None:
        self.value_label.setText(str(value))
        self.unit_label.setText(unit)
        self.hint.setText(hint or " ")

    def set_compact(self, compact: bool) -> None:
        self.hint.setVisible(not compact)

    def set_theme(self, theme: str) -> None:
        del theme  # Fully stylesheet-driven.


class IconRow(QAbstractButton):
    """Base for checkable rows that paint a flat hover/checked background."""

    indicator_inset: ClassVar[int] = 0  # px inset for the 2px accent bar

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._theme = "light"

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        self.update()

    def paintEvent(self, _event: Any) -> None:
        option = QStyleOptionButton()
        option.initFrom(self)
        if self.isChecked():
            option.state |= QStyle.StateFlag.State_On
        else:
            option.state &= ~QStyle.StateFlag.State_On
        if self.underMouse() and self.isEnabled():
            option.state |= QStyle.StateFlag.State_MouseOver
        else:
            option.state &= ~QStyle.StateFlag.State_MouseOver
        option.text = ""
        option.icon = QIcon()
        painter = QStylePainter(self)
        painter.drawControl(QStyle.ControlElement.CE_PushButton, option)
        if self.isChecked():
            c = colors(self._theme)
            inset = self.indicator_inset
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(c.accent))
            painter.drawRoundedRect(QRectF(0, inset, 2, max(1, self.height() - 2 * inset)), 1, 1)
        painter.end()


class NavItem(IconRow):
    """One navigation entry: icon + label + optional count badge."""

    indicator_inset = 6

    def __init__(self, text: str, icon_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("NavItem")
        self.setFixedHeight(30)
        self._icon_name = icon_name
        self._label_text = text
        self._compact = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(8)
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(16, 16)
        self.icon_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignVCenter)
        self.text_label = QLabel(text)
        self.text_label.setObjectName("NavText")
        self.text_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.text_label, 1)
        self.badge = QLabel()
        self.badge.setObjectName("NavBadge")
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.badge.setVisible(False)
        layout.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignVCenter)
        self.set_theme("light")

    def set_badge(self, count: int | None) -> None:
        if count:
            self.badge.setText(str(count))
            self.badge.setVisible(not self._compact)
        else:
            self.badge.setVisible(False)

    def set_compact(self, compact: bool) -> None:
        self._compact = compact
        self.text_label.setVisible(not compact)
        self.badge.setVisible(not compact and bool(self.badge.text()))
        self.setToolTip(self._label_text if compact else "")

    def set_theme(self, theme: str) -> None:
        super().set_theme(theme)
        self._refresh_icon()

    def _refresh_icon(self) -> None:
        c = colors(self._theme)
        colour = c.accent if self.isChecked() else c.text2
        self.icon_label.setPixmap(icon(self._icon_name, colour, 16).pixmap(16, 16))

    def setChecked(self, checked: bool) -> None:
        super().setChecked(checked)
        if hasattr(self, "icon_label"):
            self._refresh_icon()


class NavIndicator(QWidget):
    """Paint-only 2px accent bar that moves to the checked navigation item."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._deform = 0.0
        self._theme = "light"
        self.setFixedSize(2, 18)
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
        painter.drawRoundedRect(QRectF(self.rect()), 1, 1)
        painter.end()


class Sidebar(QFrame):
    """200px navigation rail with grouped items and count badges."""

    page_selected = Signal(int)

    EXPANDED_WIDTH = 200
    COMPACT_WIDTH = 64

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(self.EXPANDED_WIDTH)
        self._theme = "light"
        self._compact = False
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(8, 12, 8, 8)
        self._layout.setSpacing(2)

        self._group_labels: list[QLabel] = []
        self.buttons: list[NavItem] = []
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        groups = [
            ("工作台", [("概览", "overview"), ("订阅管理", "rss"), ("下载任务", "download")]),
            ("系统", [("设置", "settings")]),
        ]
        index = 0
        for label_text, items in groups:
            label = QLabel(label_text)
            label.setObjectName("NavLabel")
            self._group_labels.append(label)
            self._layout.addWidget(label)
            self._layout.addSpacing(4)
            for text, icon_name in items:
                button = NavItem(text, icon_name)
                self.group.addButton(button, index)
                self.buttons.append(button)
                self._layout.addWidget(button)
                index += 1
            self._layout.addSpacing(12)
        self.buttons[0].setChecked(True)
        self.group.idClicked.connect(self._button_selected)
        self._layout.addStretch()

        self.indicator = NavIndicator(self)
        self._indicator_animation = QPropertyAnimation(self.indicator, b"pos", self)
        self._indicator_animation.setDuration(ENTER_DURATION_MS)
        self._indicator_animation.setEasingCurve(ease_in_out_curve())

        self.footer = QFrame()
        self.footer.setObjectName("NavFooter")
        footer_layout = QVBoxLayout(self.footer)
        footer_layout.setContentsMargins(10, 12, 10, 4)
        footer_layout.setSpacing(4)
        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(6)
        self.status_dot = StatusDot("sub")
        status_row.addWidget(self.status_dot, 0, Qt.AlignmentFlag.AlignVCenter)
        self.status_label = ElidedLabel("下载器空闲")
        self.status_label.setObjectName("Muted")
        status_row.addWidget(self.status_label, 1)
        footer_layout.addLayout(status_row)
        self.footer_sub = ElidedLabel(f"v{__version__}")
        self.footer_sub.setObjectName("NavFooterSub")
        footer_layout.addWidget(self.footer_sub)
        self._layout.addWidget(self.footer)
        self.set_theme("light")
        QTimer.singleShot(0, self._sync_indicator)

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        self.indicator.set_theme(theme)
        self.status_dot.set_theme(theme)
        for button in self.buttons:
            button.set_theme(theme)

    def set_badge(self, index: int, count: int | None) -> None:
        if 0 <= index < len(self.buttons):
            self.buttons[index].set_badge(count)

    def set_status(self, text: str, subtext: str = "", *, active: bool = False) -> None:
        self.status_label.setText(text)
        self.footer_sub.setText(subtext or f"v{__version__}")
        self.status_dot.set_state("run" if active else "sub")

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
        self._indicator_animation.stop()
        self.setFixedWidth(self.COMPACT_WIDTH if compact else self.EXPANDED_WIDTH)
        for label in self._group_labels:
            label.setVisible(not compact)
        self.footer.setVisible(not compact)
        self._layout.setContentsMargins(6 if compact else 8, 12, 6 if compact else 8, 8)
        for button in self.buttons:
            button.set_compact(compact)
        QTimer.singleShot(0, self._sync_indicator)

    def _button_selected(self, index: int) -> None:
        self._move_indicator(index, animate=True)
        self.page_selected.emit(index)

    def _move_indicator(self, index: int, *, animate: bool) -> None:
        if not 0 <= index < len(self.buttons):
            return
        button = self.buttons[index]
        target = QPoint(8 if not self._compact else 6, button.geometry().center().y() - 9)
        self.indicator.raise_()
        self._indicator_animation.stop()
        if animate and not reduced_motion_requested() and self.isVisible():
            self._indicator_animation.setStartValue(self.indicator.pos())
            self._indicator_animation.setEndValue(target)
            self._indicator_animation.start()
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


class PageHeader(QWidget):
    """Compact title/subtitle pair used at the top of a page or card."""

    def __init__(self, title: str, subtitle: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PageHeader")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.title_layout = QHBoxLayout()
        self.title_layout.setContentsMargins(0, 0, 0, 0)
        self.title_layout.setSpacing(10)
        self.title = ElidedLabel(title)
        self.title.setObjectName("PageTitle")
        self.title_layout.addWidget(self.title, 0, Qt.AlignmentFlag.AlignVCenter)
        self.subtitle = ElidedLabel(subtitle)
        self.subtitle.setObjectName("PageSubtitle")
        layout.addLayout(self.title_layout)
        layout.addWidget(self.subtitle)


class EmptyState(QWidget):
    """Quiet Chinese empty-state placeholder."""

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
        self.body.setContentsMargins(30, 40, 30, 40)
        self.body.setSpacing(6)
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(32, 32)
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
        self.detail_label.setMaximumWidth(460)
        self.body.addWidget(self.detail_label, 0, Qt.AlignmentFlag.AlignHCenter)
        self.action = JellyButton(action_text)
        self.action.setProperty("primary", True)
        self.action.setVisible(bool(action_text))
        self.action.clicked.connect(self.action_clicked)
        self.body.addSpacing(4)
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
            self.body.setContentsMargins(30, 40, 30, 40)
        self.body.setSpacing(4 if compact else 6)

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        c = colors(theme)
        self.icon_label.setPixmap(icon(self._icon_name, c.text3, 18).pixmap(18, 18))
        self.icon_label.setStyleSheet(f"background:{c.track}; border-radius:{8}px;")
