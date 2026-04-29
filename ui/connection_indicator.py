"""Status dot indicating health of an external service."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget


class ConnectionIndicator(QWidget):
    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._name = name
        self._state = "unknown"  # unknown | ok | error
        self._latency_ms: float | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 0, 8, 0)
        layout.setSpacing(6)
        self._dot = _Dot(self)
        self._label = QLabel(f"{name}: —")
        self._label.setStyleSheet("color:#9fb2c8;")
        layout.addWidget(self._dot)
        layout.addWidget(self._label)

    def set_state(self, state: str, *, latency_ms: float | None = None, detail: str = "") -> None:
        self._state = state
        self._latency_ms = latency_ms
        if state == "ok":
            color = QColor("#62d2a2")
            text = f"{self._name}: {latency_ms:.0f} ms" if latency_ms is not None else f"{self._name}: OK"
        elif state == "error":
            color = QColor("#e35f6a")
            text = f"{self._name}: error"
            if detail:
                text += f" ({detail})"
        else:
            color = QColor("#7a8392")
            text = f"{self._name}: —"
        self._dot.set_color(color)
        self._label.setText(text)
        self._label.setToolTip(detail or text)


class _Dot(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor("#7a8392")
        self.setFixedSize(10, 10)

    def set_color(self, color: QColor) -> None:
        self._color = color
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(self._color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(self.rect())
