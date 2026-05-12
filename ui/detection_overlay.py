"""Live detection histogram showing top recent labels."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget


@dataclass
class DetectionEvent:
    label: str
    color: str
    confidence: float
    timestamp: float


class DetectionHistogram(QWidget):
    WINDOW_S = 5.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._events: deque[DetectionEvent] = deque(maxlen=500)
        self.setMinimumHeight(180)

    def push(self, *, label: str, color: str = "#62d2a2", confidence: float = 1.0) -> None:
        self._events.append(DetectionEvent(label=label, color=color, confidence=confidence, timestamp=time.monotonic()))
        self.update()

    def reset(self) -> None:
        self._events.clear()
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(2, 2, -2, -2)
        painter.fillRect(rect, QColor("#0f1115"))
        painter.setPen(QPen(QColor("#1d2330"), 1))
        painter.drawRect(rect)

        now = time.monotonic()
        active = [e for e in self._events if now - e.timestamp <= self.WINDOW_S]
        if not active:
            painter.setPen(QPen(QColor("#3a4452")))
            painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), "sin detecciones recientes")
            painter.end()
            return

        counts: dict[str, int] = {}
        colors: dict[str, str] = {}
        for ev in active:
            counts[ev.label] = counts.get(ev.label, 0) + 1
            colors[ev.label] = ev.color
        sorted_items = sorted(counts.items(), key=lambda kv: -kv[1])[:10]
        max_count = max(c for _, c in sorted_items)

        row_height = max(14, rect.height() // max(len(sorted_items), 1) - 2)
        y = rect.top() + 4
        bar_left = rect.left() + 110
        bar_width_total = rect.right() - bar_left - 30

        painter.setFont(self.font())
        for label, count in sorted_items:
            color = QColor(colors.get(label, "#62d2a2"))
            painter.setPen(QPen(QColor("#cfd6e1")))
            painter.drawText(rect.left() + 6, y, 100, row_height, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), label[:14])
            bar_width = int(bar_width_total * (count / max_count))
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(bar_left, y + 2, bar_width, row_height - 4, 3, 3)
            painter.setPen(QPen(QColor("#9fb2c8")))
            painter.drawText(bar_left + bar_width + 6, y, 30, row_height, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), str(count))
            y += row_height + 2
            if y > rect.bottom():
                break
        painter.end()
