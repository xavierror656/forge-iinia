"""Tiny inline chart for telemetry."""

from __future__ import annotations

from collections import deque

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QWidget


class Sparkline(QWidget):
    def __init__(self, *, capacity: int = 60, color: str = "#62d2a2", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._values: deque[float] = deque(maxlen=capacity)
        self._capacity = capacity
        self._color = QColor(color)
        self._min_floor = 0.0
        self.setMinimumHeight(28)
        self.setMaximumHeight(36)

    def push(self, value: float) -> None:
        self._values.append(float(value))
        self.update()

    def reset(self) -> None:
        self._values.clear()
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(2, 2, -2, -2)
        painter.fillRect(rect, QColor("#0f1115"))
        painter.setPen(QPen(QColor("#1d2330"), 1))
        painter.drawRect(rect)

        if len(self._values) < 2:
            painter.setPen(QPen(QColor("#3a4452")))
            painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), "—")
            return

        values = list(self._values)
        v_min = min(min(values), self._min_floor)
        v_max = max(values)
        span = max(v_max - v_min, 1e-6)

        n = len(values)
        x_step = rect.width() / max(self._capacity - 1, 1)
        x_offset = rect.left() + (self._capacity - n) * x_step

        points: list[QPointF] = []
        for i, value in enumerate(values):
            x = x_offset + i * x_step
            y_norm = (value - v_min) / span
            y = rect.bottom() - y_norm * rect.height()
            points.append(QPointF(x, y))

        polygon = QPolygonF(points + [QPointF(points[-1].x(), rect.bottom()), QPointF(points[0].x(), rect.bottom())])
        fill_color = QColor(self._color)
        fill_color.setAlpha(64)
        painter.setBrush(fill_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(polygon)

        painter.setPen(QPen(self._color, 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolyline(QPolygonF(points))

        painter.setPen(QPen(QColor("#9fb2c8")))
        painter.drawText(rect.adjusted(4, 0, -4, 0), int(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight), f"{values[-1]:.1f}")
