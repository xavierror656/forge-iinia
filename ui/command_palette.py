"""Global Ctrl+K command palette across labels, cameras, lines, ports."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QDialog, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from ui.icons import icon as _icon


@dataclass
class PaletteItem:
    kind: str  # "label" | "camera" | "line" | "port" | "project"
    text: str
    payload: object


KIND_ICONS = {
    "label": ("tag", "accent"),
    "camera": ("camera-video", "info"),
    "line": ("diagram-3", "primary"),
    "port": ("plug", "warning"),
    "project": ("folder", "primary"),
}


class CommandPalette(QDialog):
    selected = pyqtSignal(object)

    def __init__(self, items: list[PaletteItem], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Buscar")
        self.setWindowIcon(_icon("search", size=24))
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setModal(True)
        self.resize(560, 440)
        self.setStyleSheet(
            "QDialog { background:#11141a; border:1px solid #2a313a; border-radius:10px; }"
            "QLineEdit { background:#0f1115; border:1px solid #2a313a; border-radius:6px; padding:8px; color:#e6eaf2; }"
            "QListWidget { background:#0f1115; border:none; color:#cfd6e1; }"
            "QListWidget::item { padding:6px 8px; }"
            "QListWidget::item:selected { background:#243043; color:#ffffff; }"
        )

        self._items = list(items)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar label, cámara, línea, puerto, proyecto...")
        self.search.textChanged.connect(self._refresh)
        font = QFont()
        font.setPointSize(11)
        self.search.setFont(font)
        self.search.addAction(_icon("search", size=16), QLineEdit.ActionPosition.LeadingPosition)

        self.list = QListWidget()
        self.list.itemActivated.connect(self._emit_current)

        layout.addWidget(self.search)
        layout.addWidget(self.list, 1)

        self.search.installEventFilter(self)
        self._refresh()

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self.search and event.type() == event.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                row = self.list.currentRow()
                if key == Qt.Key.Key_Down:
                    self.list.setCurrentRow(min(self.list.count() - 1, row + 1))
                else:
                    self.list.setCurrentRow(max(0, row - 1))
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._emit_current()
                return True
            if key == Qt.Key.Key_Escape:
                self.reject()
                return True
        return super().eventFilter(obj, event)

    def _refresh(self) -> None:
        needle = self.search.text().strip().lower()
        self.list.clear()
        for item in self._items:
            if needle and needle not in item.text.lower() and needle not in item.kind.lower():
                continue
            icon_name, color = KIND_ICONS.get(item.kind, ("circle", "muted"))
            entry = QListWidgetItem(item.text)
            entry.setIcon(_icon(icon_name, size=16, color=color))
            entry.setData(Qt.ItemDataRole.UserRole, item)
            self.list.addItem(entry)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _emit_current(self) -> None:
        item = self.list.currentItem()
        if not item:
            return
        payload = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(payload, PaletteItem):
            self.selected.emit(payload)
            self.accept()
