"""Strip of LED indicators that flash when a GPIO event fires."""

from __future__ import annotations

from PyQt6.QtCore import QPropertyAnimation, QTimer, Qt, pyqtProperty
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ui.icons import icon as _icon


class _Led(QWidget):
    def __init__(self, port: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.port = port
        self._intensity = 0.0
        self._color = QColor("#62d2a2")
        self.setFixedSize(18, 24)
        self.setToolTip(port)
        self._animation = QPropertyAnimation(self, b"intensity", self)
        self._animation.setDuration(700)
        self._animation.setStartValue(1.0)
        self._animation.setEndValue(0.0)

    def get_intensity(self) -> float:
        return self._intensity

    def set_intensity(self, value: float) -> None:
        self._intensity = max(0.0, min(1.0, value))
        self.update()

    intensity = pyqtProperty(float, fget=get_intensity, fset=set_intensity)

    def pulse(self, color: str = "#62d2a2") -> None:
        self._color = QColor(color)
        if self._animation.state() != QPropertyAnimation.State.Stopped:
            self._animation.stop()
        self._animation.start()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(2, 2, -2, -2)
        body = QColor("#1b2028")
        painter.setBrush(body)
        painter.setPen(QColor("#2a313a"))
        painter.drawRoundedRect(rect, 4, 4)
        glow = QColor(self._color)
        glow.setAlphaF(self._intensity)
        painter.setBrush(glow)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), 3, 3)


class GPIOLedStrip(QWidget):
    def __init__(self, ports: list[str] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._leds: dict[str, _Led] = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(4)
        title_icon = QLabel()
        title_icon.setFixedSize(14, 14)
        title_icon.setPixmap(_icon("plug", size=14, color="muted").pixmap(14, 14))
        title = QLabel("GPIO live")
        title.setStyleSheet("color:#9fb2c8; font-size:11px;")
        header.addWidget(title_icon)
        header.addWidget(title)
        header.addStretch(1)
        outer.addLayout(header)
        strip = QHBoxLayout()
        strip.setSpacing(2)
        strip.setContentsMargins(0, 0, 0, 0)
        for port in (ports or [f"GPIO{n}" for n in range(2, 28)]):
            led = _Led(port)
            self._leds[port] = led
            strip.addWidget(led)
        strip.addStretch(1)
        outer.addLayout(strip)

    def pulse(self, port: str, *, active: bool) -> None:
        led = self._leds.get(port)
        if led is None:
            return
        led.pulse("#62d2a2" if active else "#e35f6a")

    def reset(self) -> None:
        for led in self._leds.values():
            led.set_intensity(0.0)
