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
        self._image: QImage | None = None
        self._status_text = "Esperando stream..."
        self._detections: list[dict[str, Any]] = []
        self._frame_size: tuple[int, int] | None = None
        self.setMinimumHeight(360)

    def set_frame(self, frame: Any) -> None:
        self._image = None
        self._frame_size = None
        if isinstance(frame, dict):
            status = frame.get("status") or frame.get("source_label") or frame.get("source") or "Stream activo"
            self._status_text = str(status)
            detections = frame.get("detections")
            if isinstance(detections, list):
                self._detections = list(detections)
            image = frame.get("image")
            if isinstance(image, QImage):
                self._image = image
            frame_size = frame.get("frame_size")
            if isinstance(frame_size, (tuple, list)) and len(frame_size) == 2:
                try:
                    self._frame_size = (int(frame_size[0]), int(frame_size[1]))
                except (TypeError, ValueError):
                    self._frame_size = None
        elif isinstance(frame, QImage):
            self._image = frame
        else:
            self._status_text = "Esperando stream..."
        self.update()

    def set_status(self, text: str) -> None:
        self._status_text = text
        self.update()

    def set_detections(self, detections: list[dict[str, Any]]) -> None:
        self._detections = list(detections)
        self.update()

    def paintGL(self) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#111318"))
        if self._image is not None and not self._image.isNull():
            scaled = self._image.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            x_offset = (self.width() - scaled.width()) // 2
            y_offset = (self.height() - scaled.height()) // 2
            painter.drawImage(QPoint(x_offset, y_offset), scaled)

            img_width = max(1, self._image.width())
            img_height = max(1, self._image.height())
            scale_x = scaled.width() / img_width
            scale_y = scaled.height() / img_height

            for det in self._detections:
                bbox = det.get("bbox") or (0.1, 0.1, 0.3, 0.3)
                if not isinstance(bbox, (tuple, list)) or len(bbox) != 4:
                    continue
                try:
                    x1, y1, x2, y2 = (float(value) for value in bbox)
                except (TypeError, ValueError):
                    continue

                if max(abs(x1), abs(y1), abs(x2), abs(y2)) <= 1.5:
                    rect = QRectF(
                        x_offset + x1 * scaled.width(),
                        y_offset + y1 * scaled.height(),
                        (x2 - x1) * scaled.width(),
                        (y2 - y1) * scaled.height(),
                    )
                else:
                    rect = QRectF(
                        x_offset + x1 * scale_x,
                        y_offset + y1 * scale_y,
                        (x2 - x1) * scale_x,
                        (y2 - y1) * scale_y,
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
                    banner_x = int(max(0, rect.x()))
                    banner_y = int(max(0, rect.y() - th))
                    painter.fillRect(QRectF(banner_x, banner_y, tw, th), color)
                    painter.setPen(QPen(QColor("#0a0c10")))
                    painter.drawText(QPoint(banner_x + 4, banner_y + th - 4), text)

            painter.setPen(QPen(QColor("#0a0c10")))
            painter.fillRect(
                QRectF(12, 12, max(220, painter.fontMetrics().horizontalAdvance(self._status_text) + 20), 26),
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
        index = sum(ord(ch) for ch in label) % len(palette)
        return palette[index]
