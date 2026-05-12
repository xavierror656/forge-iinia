"""Low-overhead Qt widget for displaying camera frames + detection overlay."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QPoint, QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPen
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtWidgets import QWidget


class OpenGLVideoWidget(QOpenGLWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._raw_image: QImage | None = None
        self._scaled_image: QImage | None = None
        self._blit_x = 0
        self._blit_y = 0
        self._scale_x = 1.0
        self._scale_y = 1.0
        self._status_text = "Esperando stream..."
        self._detections: list[dict[str, Any]] = []
        self.setMinimumHeight(360)

    def set_frame(self, frame: Any) -> None:
        self._raw_image = None
        self._scaled_image = None
        if isinstance(frame, dict):
            status = frame.get("status") or frame.get("source_label") or frame.get("source") or "Stream activo"
            self._status_text = str(status)
            detections = frame.get("detections")
            if isinstance(detections, list):
                self._detections = list(detections)
            image = frame.get("image")
            if isinstance(image, QImage):
                self._raw_image = image
        elif isinstance(frame, QImage):
            self._raw_image = frame
        else:
            self._status_text = "Esperando stream..."
        if self._raw_image is not None:
            self._recompute_scale()
        self.update()

    def set_status(self, text: str) -> None:
        self._status_text = text
        self.update()

    def set_detections(self, detections: list[dict[str, Any]]) -> None:
        self._detections = list(detections)
        self.update()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._scaled_image = None  # invalidate; recompute on next paint if raw available
        if self._raw_image is not None:
            self._recompute_scale()

    def _recompute_scale(self) -> None:
        img = self._raw_image
        if img is None or img.isNull():
            self._scaled_image = None
            return
        scaled = img.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)
        self._scaled_image = scaled
        self._blit_x = (self.width() - scaled.width()) // 2
        self._blit_y = (self.height() - scaled.height()) // 2
        self._scale_x = scaled.width() / max(1, img.width())
        self._scale_y = scaled.height() / max(1, img.height())

    def paintGL(self) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#111318"))

        if self._scaled_image is not None and not self._scaled_image.isNull():
            painter.drawImage(QPoint(self._blit_x, self._blit_y), self._scaled_image)

            for det in self._detections:
                bbox = det.get("bbox") or (0.1, 0.1, 0.3, 0.3)
                if not isinstance(bbox, (tuple, list)) or len(bbox) != 4:
                    continue
                try:
                    x1, y1, x2, y2 = (float(v) for v in bbox)
                except (TypeError, ValueError):
                    continue

                sw, sh = self._scaled_image.width(), self._scaled_image.height()
                if max(abs(x1), abs(y1), abs(x2), abs(y2)) <= 1.5:
                    rect = QRectF(
                        self._blit_x + x1 * sw,
                        self._blit_y + y1 * sh,
                        (x2 - x1) * sw,
                        (y2 - y1) * sh,
                    )
                else:
                    rect = QRectF(
                        self._blit_x + x1 * self._scale_x,
                        self._blit_y + y1 * self._scale_y,
                        (x2 - x1) * self._scale_x,
                        (y2 - y1) * self._scale_y,
                    )

                color_hex = det.get("color") or self._label_color(str(det.get("label", "")))
                color = QColor(color_hex)
                if not color.isValid():
                    color = QColor("#62d2a2")
                painter.setPen(QPen(color, 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(rect)

                label = str(det.get("label", "")).strip()
                conf = det.get("confidence", 0.0)
                text = f"{label}  {conf:.2f}" if label and conf else label
                if text:
                    fm = painter.fontMetrics()
                    tw = fm.horizontalAdvance(text) + 8
                    th = fm.height() + 4
                    bx = int(max(0, rect.x()))
                    by = int(max(0, rect.y() - th))
                    painter.fillRect(QRectF(bx, by, tw, th), color)
                    painter.setPen(QPen(QColor("#0a0c10")))
                    painter.drawText(QPoint(bx + 4, by + th - 4), text)

            painter.setPen(QPen(QColor("#0a0c10")))
            fm = painter.fontMetrics()
            painter.fillRect(
                QRectF(12, 12, max(220, fm.horizontalAdvance(self._status_text) + 20), 26),
                QColor(0, 0, 0, 150),
            )
            painter.setPen(QPen(QColor("#e6eaf2")))
            painter.drawText(QPoint(22, 30), self._status_text)
        else:
            painter.setPen(QPen(QColor("#62d2a2")))
            painter.drawText(self.rect().adjusted(16, 16, -16, -16), 0x84, self._status_text)
        painter.end()

    @staticmethod
    def _label_color(label: str) -> str:
        palette = ["#62d2a2", "#5aa9e6", "#f4b942", "#e66b6b", "#b57ff5", "#7ad3c8"]
        if not label:
            return palette[0]
        return palette[sum(ord(ch) for ch in label) % len(palette)]
