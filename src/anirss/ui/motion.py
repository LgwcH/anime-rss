"""Small, dependency-free motion primitives for the Qt Widgets interface."""

from __future__ import annotations

import ctypes
import os
from contextlib import suppress

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QParallelAnimationGroup,
    QPointF,
    QPropertyAnimation,
    Qt,
    Signal,
)
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsOpacityEffect, QStackedWidget, QWidget

PRESS_DURATION_MS = 120
RELEASE_DURATION_MS = 180
ENTER_DURATION_MS = 220
TOGGLE_DURATION_MS = 220
COLLAPSE_DURATION_MS = 200


def reduced_motion_requested() -> bool:
    """Honor an explicit override and the Windows client-animation setting."""

    override = os.environ.get("ANIRSS_REDUCE_MOTION", "").strip().casefold()
    if override in {"1", "true", "yes", "on"}:
        return True
    if override in {"0", "false", "no", "off"}:
        return False
    # SPI_GETCLIENTAREAANIMATION mirrors Windows' "Animation effects" setting.
    user32 = getattr(getattr(ctypes, "windll", None), "user32", None)
    if user32 is None:
        return False
    animations_enabled = ctypes.c_int(1)
    with suppress(OSError, ValueError):
        succeeded = bool(
            user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(animations_enabled), 0)
        )
        if succeeded:
            return not bool(animations_enabled.value)
    return False


def ease_out_curve() -> QEasingCurve:
    """Strong UI ease-out: cubic-bezier(0.23, 1, 0.32, 1)."""

    curve = QEasingCurve(QEasingCurve.Type.BezierSpline)
    curve.addCubicBezierSegment(
        QPointF(0.23, 1.0),
        QPointF(0.32, 1.0),
        QPointF(1.0, 1.0),
    )
    return curve


def ease_in_out_curve() -> QEasingCurve:
    """Strong movement curve: cubic-bezier(0.77, 0, 0.175, 1)."""

    curve = QEasingCurve(QEasingCurve.Type.BezierSpline)
    curve.addCubicBezierSegment(
        QPointF(0.77, 0.0),
        QPointF(0.175, 1.0),
        QPointF(1.0, 1.0),
    )
    return curve


class AnimatedStackedWidget(QStackedWidget):
    """Cross-fade occasional page changes without delaying interaction."""

    transition_finished = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._animation_group: QParallelAnimationGroup | None = None
        self._overlay: JellySnapshotOverlay | None = None
        self._animated_widget: QWidget | None = None
        self._animated_effect: QGraphicsOpacityEffect | None = None

    def transition_to(self, index: int, *, animate: bool = True) -> None:
        if not 0 <= index < self.count():
            return
        if index == self.currentIndex():
            self.transition_finished.emit(index)
            return

        self._cleanup_animation()
        outgoing = self.currentWidget()
        snapshot = outgoing.grab() if outgoing is not None and outgoing.isVisible() else None
        super().setCurrentIndex(index)
        incoming = self.currentWidget()
        if (
            incoming is None
            or snapshot is None
            or snapshot.isNull()
            or not animate
            or reduced_motion_requested()
            or not self.isVisible()
        ):
            self.transition_finished.emit(index)
            return

        overlay = JellySnapshotOverlay(snapshot, self)
        overlay.setGeometry(incoming.geometry())
        overlay.show()
        overlay.raise_()

        outgoing_effect = QGraphicsOpacityEffect(overlay)
        overlay.setGraphicsEffect(outgoing_effect)
        incoming_effect = QGraphicsOpacityEffect(incoming)
        incoming.setGraphicsEffect(incoming_effect)
        outgoing_effect.setOpacity(1.0)
        incoming_effect.setOpacity(0.0)

        outgoing_animation = QPropertyAnimation(outgoing_effect, b"opacity", self)
        outgoing_animation.setStartValue(1.0)
        outgoing_animation.setEndValue(0.0)
        outgoing_animation.setDuration(ENTER_DURATION_MS)
        outgoing_animation.setEasingCurve(ease_out_curve())
        incoming_animation = QPropertyAnimation(incoming_effect, b"opacity", self)
        incoming_animation.setStartValue(0.0)
        incoming_animation.setEndValue(1.0)
        incoming_animation.setDuration(ENTER_DURATION_MS)
        incoming_animation.setEasingCurve(ease_out_curve())
        deform_animation = QPropertyAnimation(overlay, b"deform", self)
        deform_animation.setDuration(ENTER_DURATION_MS)
        deform_animation.setStartValue(0.0)
        deform_animation.setKeyValueAt(0.38, 1.0)
        deform_animation.setKeyValueAt(0.72, -0.28)
        deform_animation.setEndValue(0.0)
        deform_animation.setEasingCurve(ease_out_curve())

        group = QParallelAnimationGroup(self)
        group.addAnimation(outgoing_animation)
        group.addAnimation(incoming_animation)
        group.addAnimation(deform_animation)
        group.finished.connect(lambda current=index: self._finish_animation(current))
        self._animation_group = group
        self._overlay = overlay
        self._animated_widget = incoming
        self._animated_effect = incoming_effect
        group.start()

    def transition_to_widget(self, widget: QWidget, *, animate: bool = True) -> None:
        index = self.indexOf(widget)
        if index >= 0:
            self.transition_to(index, animate=animate)

    def _finish_animation(self, index: int) -> None:
        self._cleanup_animation()
        self.transition_finished.emit(index)

    def _cleanup_animation(self) -> None:
        group = self._animation_group
        self._animation_group = None
        if group is not None:
            group.stop()
            group.deleteLater()
        if (
            self._animated_widget is not None
            and self._animated_widget.graphicsEffect() is self._animated_effect
        ):
            self._animated_widget.setGraphicsEffect(None)  # type: ignore[arg-type]
        self._animated_widget = None
        self._animated_effect = None
        overlay = self._overlay
        self._overlay = None
        if overlay is not None:
            overlay.deleteLater()


class JellySnapshotOverlay(QWidget):
    """Paint-only page snapshot that softly stretches while fading away."""

    def __init__(self, pixmap: QPixmap, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixmap = pixmap
        self._deform = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

    def _get_deform(self) -> float:
        return self._deform

    def _set_deform(self, value: float) -> None:
        self._deform = float(value)
        self.update()

    deform = Property(float, _get_deform, _set_deform)

    def paintEvent(self, _event: object) -> None:
        if self._pixmap.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        amount = self._deform
        scale_x = 1.0 + 0.007 * amount
        scale_y = 1.0 - 0.005 * amount
        center = self.rect().center()
        painter.translate(center)
        painter.scale(scale_x, scale_y)
        painter.translate(-center)
        painter.drawPixmap(self.rect(), self._pixmap)
        painter.end()


__all__ = [
    "COLLAPSE_DURATION_MS",
    "ENTER_DURATION_MS",
    "PRESS_DURATION_MS",
    "RELEASE_DURATION_MS",
    "TOGGLE_DURATION_MS",
    "AnimatedStackedWidget",
    "JellySnapshotOverlay",
    "ease_in_out_curve",
    "ease_out_curve",
    "reduced_motion_requested",
]
