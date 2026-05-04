"""Toast notifications stacked in the corner of the parent widget."""

from __future__ import annotations

from PyQt6.QtCore import QPropertyAnimation, QTimer, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QHBoxLayout, QLabel, QWidget

from ui.icons import icon as _icon


SEVERITY_STYLE = {
    "info": ("#1b2028", "#9fb2c8"),
    "success": ("#1d2f24", "#62d2a2"),
    "warn": ("#332714", "#e3b341"),
    "error": ("#3a1a1f", "#e35f6a"),
}

SEVERITY_ICON = {
    "info": ("info-circle", "info"),
    "success": ("check-circle", "accent"),
    "warn": ("exclamation-triangle", "warning"),
    "error": ("x-circle", "danger"),
}


class _Toast(QWidget):
    def __init__(self, message: str, severity: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        bg, fg = SEVERITY_STYLE.get(severity, SEVERITY_STYLE["info"])
        self.setStyleSheet(
            f"background:{bg}; color:{fg}; border:1px solid {fg}; border-radius:8px; padding:8px 12px;"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        icon_name, icon_color = SEVERITY_ICON.get(severity, SEVERITY_ICON["info"])
        icon_label = QLabel()
        icon_label.setFixedSize(16, 16)
        icon_label.setPixmap(_icon(icon_name, size=16, color=icon_color).pixmap(16, 16))
        label = QLabel(message)
        label.setWordWrap(True)
        label.setStyleSheet(f"color:{fg};")
        layout.addWidget(icon_label)
        layout.addWidget(label)

        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)
        self._fade_in = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade_in.setDuration(180)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_out = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade_out.setDuration(220)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.finished.connect(self._on_dismissed)
        self._on_dismiss_cb = lambda: None

    def show_and_schedule(self, *, ttl_ms: int) -> None:
        self.show()
        self._fade_in.start()
        QTimer.singleShot(ttl_ms, self._fade_out.start)

    def _on_dismissed(self) -> None:
        self._on_dismiss_cb()
        self.deleteLater()


class ToastManager:
    def __init__(self, parent: QWidget) -> None:
        self._parent = parent
        self._stack: list[_Toast] = []
        self._max_visible = 4

    def show(self, message: str, *, severity: str = "info", ttl_ms: int = 4000) -> None:
        toast = _Toast(message, severity, self._parent)
        toast.adjustSize()
        toast.setMinimumWidth(280)
        toast.setMaximumWidth(420)
        toast._on_dismiss_cb = lambda t=toast: self._cleanup(t)
        self._stack.append(toast)
        self._reflow()
        if len(self._stack) > self._max_visible:
            old = self._stack[0]
            old._fade_out.start()
        toast.show_and_schedule(ttl_ms=ttl_ms)

    def _cleanup(self, toast: _Toast) -> None:
        if toast in self._stack:
            self._stack.remove(toast)
        self._reflow()

    def _reflow(self) -> None:
        margin = 16
        spacing = 8
        parent_size = self._parent.size()
        x_base = parent_size.width() - margin
        y = parent_size.height() - margin
        for toast in reversed(self._stack):
            toast.adjustSize()
            w = max(280, min(420, toast.sizeHint().width()))
            h = toast.sizeHint().height()
            y -= h
            toast.setGeometry(x_base - w, y, w, h)
            y -= spacing
        for toast in self._stack:
            toast.raise_()

    def reflow(self) -> None:
        self._reflow()
