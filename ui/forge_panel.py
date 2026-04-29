"""Forge operations panel for project and camera assignment."""

from __future__ import annotations

import ast
import base64
import json
from pathlib import Path

from PyQt6.QtCore import QMimeData, QPoint, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QDrag, QFont, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSplitter,
    QScrollArea,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTabWidget,
    QToolButton,
    QTextEdit,
    QVBoxLayout,
    QSpinBox,
    QWidget,
)


UI_STATE_PATH = Path("configs/ui_state.json")


def _label_text(value: object) -> str:
    if isinstance(value, dict):
        name = value.get("name")
        if name is None:
            return ""
        text = str(name).strip()
        return text

    text = str(value).strip()
    if not text:
        return ""
    if text.startswith("{") and text.endswith("}"):
        try:
            parsed = ast.literal_eval(text)
        except (ValueError, SyntaxError):
            return text
        if isinstance(parsed, dict):
            name = parsed.get("name")
            if name is not None:
                parsed_name = str(name).strip()
                if parsed_name:
                    return parsed_name
    return text


def _short_label(text: str, limit: int = 18) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _label_prefix(name: str) -> str:
    for sep in ("_", "-", " ", "."):
        if sep in name:
            return name.split(sep, 1)[0].lower()
    return name[:1].lower() or "·"


class ColorChipDelegate(QStyledItemDelegate):
    """Paints a colored dot next to the label text instead of using item background."""

    DOT_RADIUS = 6
    DOT_PADDING = 10

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._header_font = QFont()
        self._header_font.setBold(True)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:  # noqa: D401
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)

        is_header = bool(index.data(Qt.ItemDataRole.UserRole + 1))
        if is_header:
            painter.save()
            painter.fillRect(option.rect, QColor("#0d1016"))
            painter.setFont(self._header_font)
            painter.setPen(QPen(QColor("#9fb2c8")))
            text_rect = option.rect.adjusted(10, 0, -6, 0)
            painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), index.data())
            painter.restore()
            return

        data = index.data(Qt.ItemDataRole.UserRole)
        color_hex = ""
        if isinstance(data, dict):
            color_hex = str(data.get("color", "")).strip()

        widget = option.widget
        style = widget.style() if widget else None
        opt.text = ""
        if style is not None:
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)
        else:
            painter.fillRect(option.rect, opt.backgroundBrush)

        rect: QRect = option.rect
        cx = rect.left() + self.DOT_PADDING
        cy = rect.center().y()

        if color_hex:
            color = QColor(color_hex)
            if not color.isValid():
                color = QColor("#7a8392")
        else:
            color = QColor("#3a4452")

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(QBrush(color))
        painter.setPen(QPen(QColor("#0a0c10"), 1))
        painter.drawEllipse(QPoint(cx, cy), self.DOT_RADIUS, self.DOT_RADIUS)
        painter.restore()

        text = index.data() or ""
        text_rect = rect.adjusted(self.DOT_PADDING * 2 + self.DOT_RADIUS, 0, -8, 0)
        painter.save()
        if option.state & QStyle.StateFlag.State_Selected:
            painter.setPen(QPen(QColor("#ffffff")))
        else:
            painter.setPen(QPen(QColor("#e6eaf2")))
        painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text)
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:  # noqa: N802
        size = super().sizeHint(option, index)
        is_header = bool(index.data(Qt.ItemDataRole.UserRole + 1))
        size.setHeight(28 if is_header else 26)
        return size


class DragListWidget(QListWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDragDropMode(QListWidget.DragDropMode.DragOnly)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)

    def _selectable_items(self) -> list[QListWidgetItem]:
        items = [item for item in self.selectedItems() if not item.data(Qt.ItemDataRole.UserRole + 1)]
        if items:
            return items
        current = self.currentItem()
        if current and not current.data(Qt.ItemDataRole.UserRole + 1):
            return [current]
        return []

    def startDrag(self, supportedActions):  # noqa: N802
        items = self._selectable_items()
        if not items:
            return
        labels = [_label_text(item.data(Qt.ItemDataRole.UserRole) or item.text()) for item in items]
        labels = [label for label in labels if label.strip()]
        if not labels:
            return
        mime = QMimeData()
        mime.setText("\n".join(labels))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(self._build_drag_pixmap(len(labels), labels[0]))
        drag.setHotSpot(QPoint(20, 16))
        drag.exec(supportedActions)

    @staticmethod
    def _build_drag_pixmap(count: int, sample: str) -> QPixmap:
        text = f"{count} labels" if count > 1 else _short_label(sample, 24)
        width = max(120, 16 + len(text) * 7)
        pixmap = QPixmap(width, 32)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(QBrush(QColor("#243043")))
        painter.setPen(QPen(QColor("#4d6b8a"), 1))
        painter.drawRoundedRect(0, 0, width - 1, 31, 8, 8)
        painter.setPen(QPen(QColor("#e6eaf2")))
        painter.drawText(pixmap.rect(), int(Qt.AlignmentFlag.AlignCenter), text)
        painter.end()
        return pixmap


class CameraListWidget(QListWidget):
    labels_dropped = pyqtSignal(int, list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QListWidget.DragDropMode.DropOnly)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasText():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasText():
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        if not event.mimeData().hasText():
            super().dropEvent(event)
            return
        pos = event.position().toPoint() if hasattr(event, "position") else QPoint()
        item = self.itemAt(pos) or self.currentItem()
        if item is None:
            return
        camera_id = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(camera_id, int):
            return
        labels = [line.strip() for line in event.mimeData().text().splitlines() if line.strip()]
        if labels:
            self.labels_dropped.emit(camera_id, labels)
            event.acceptProposedAction()
            return
        super().dropEvent(event)


class PortListWidget(QListWidget):
    labels_dropped = pyqtSignal(str, list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QListWidget.DragDropMode.DropOnly)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasText():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasText():
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        if not event.mimeData().hasText():
            super().dropEvent(event)
            return
        pos = event.position().toPoint() if hasattr(event, "position") else QPoint()
        item = self.itemAt(pos) or self.currentItem()
        if item is None:
            return
        port = str(item.data(Qt.ItemDataRole.UserRole) or item.text().split(" ", 1)[0]).strip()
        labels = [line.strip() for line in event.mimeData().text().splitlines() if line.strip()]
        if labels and port:
            self.labels_dropped.emit(port, labels)
            event.acceptProposedAction()
            return
        super().dropEvent(event)


class CollapsibleSection(QWidget):
    def __init__(self, title: str, summary: str = "", expanded: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._title = title
        self._summary = summary

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.header = QToolButton()
        self.header.setCheckable(True)
        self.header.setChecked(expanded)
        self.header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.header.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.header.toggled.connect(self._sync_state)
        self.header.setStyleSheet(
            """
            QToolButton {
                padding: 8px 10px;
                border: 1px solid #2a313a;
                border-radius: 8px;
                background: #141820;
                color: #e6eaf2;
                font-weight: 600;
                text-align: left;
            }
            QToolButton:hover { background: #1b2028; }
            """
        )

        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(4, 4, 4, 4)
        self.content_layout.setSpacing(6)

        layout.addWidget(self.header)
        layout.addWidget(self.content)
        self._sync_state()

    def _update_text(self) -> None:
        text = self._title if not self._summary else f"{self._title} · {self._summary}"
        self.header.setText(text)

    def _sync_state(self, *_args) -> None:
        expanded = self.header.isChecked()
        self.content.setVisible(expanded)
        self.header.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self._update_text()

    def set_summary(self, summary: str) -> None:
        self._summary = summary
        self._update_text()

    def set_expanded(self, expanded: bool) -> None:
        self.header.setChecked(expanded)
        self._sync_state()

    def is_expanded(self) -> bool:
        return self.content.isVisible()


class LabelPreviewCard(QFrame):
    clicked = pyqtSignal(dict)

    def __init__(self, data: dict[str, object], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._data = data
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.image = QLabel()
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumHeight(96)
        self.image.setStyleSheet("background:#0f1115; border-radius:6px; color:#8b95a1;")

        crop = str(data.get("preview_base64", "")).strip()
        pixmap = QPixmap()
        if crop and pixmap.loadFromData(base64.b64decode(crop)):
            self.image.setPixmap(pixmap.scaled(220, 96, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        else:
            self.image.setText("No crop")

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)
        color_dot = QLabel()
        color_dot.setFixedSize(10, 10)
        color = str(data.get("color", "")).strip() or "#3a4452"
        color_dot.setStyleSheet(f"background:{color}; border-radius:5px; border:1px solid #0a0c10;")
        self.title = QLabel(str(data.get("name", "")))
        self.title.setStyleSheet("font-weight: 600;")
        title_row.addWidget(color_dot)
        title_row.addWidget(self.title, 1)

        self.subtitle = QLabel(str(data.get("type", "") or ""))
        self.subtitle.setStyleSheet("color:#9fb2c8; font-size: 11px;")
        layout.addWidget(self.image)
        layout.addLayout(title_row)
        layout.addWidget(self.subtitle)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.clicked.emit(self._data)
        super().mousePressEvent(event)


class LabelGalleryWidget(QWidget):
    selected = pyqtSignal(dict)

    COLUMNS = 3

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[dict[str, object]] = []
        self._cards: list[LabelPreviewCard] = []
        self._filter_text = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.content = QWidget()
        self.grid = QGridLayout(self.content)
        self.grid.setSpacing(8)
        self.grid.setContentsMargins(4, 4, 4, 4)
        self.scroll.setWidget(self.content)
        layout.addWidget(self.scroll)

    def set_items(self, items: list[dict]) -> None:
        self._items = list(items)
        self.refresh()

    def set_filter(self, text: str) -> None:
        self._filter_text = text.strip().lower()
        self.refresh()

    def refresh(self) -> None:
        while self.grid.count():
            child = self.grid.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._cards.clear()
        visible_items = [item for item in self._items if self._matches(item)]
        for index, item in enumerate(visible_items):
            card = LabelPreviewCard(item)
            card.clicked.connect(self.selected.emit)
            self._cards.append(card)
            self.grid.addWidget(card, index // self.COLUMNS, index % self.COLUMNS)
        if visible_items:
            self.selected.emit(visible_items[0])

    def _matches(self, item: dict[str, object]) -> bool:
        if not self._filter_text:
            return True
        haystack = " ".join(
            str(item.get(key, ""))
            for key in ("name", "type", "color")
        ).lower()
        return self._filter_text in haystack



class ForgeConfigDialog(QDialog):
    def __init__(self, *, base_url: str = "", username: str = "", password: str = "", token: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Configuración Forge")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.base_url = QLineEdit(base_url)
        self.username = QLineEdit(username)
        self.password = QLineEdit(password)
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.token = QLineEdit(token)
        self.token.setPlaceholderText("Token opcional")
        form.addRow("Base URL", self.base_url)
        form.addRow("Username", self.username)
        form.addRow("Password", self.password)
        form.addRow("Token", self.token)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> dict[str, str]:
        return {
            "base_url": self.base_url.text().strip(),
            "username": self.username.text().strip(),
            "password": self.password.text().strip(),
            "token": self.token.text().strip(),
        }


class CameraCreateDialog(QDialog):
    def __init__(self, *, line_options: list[tuple[int, str]] | None = None, selected_line_id: int | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Nueva cámara")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.number = QSpinBox()
        self.number.setRange(0, 2147483647)
        self.number.setValue(1)
        self.device_ip = QLineEdit()
        self.device_ip.setPlaceholderText("192.168.1.10")
        self.protocol = QComboBox()
        self.protocol.setEditable(True)
        self.protocol.addItems(["rtsp", "http", "tcp"])
        self.status = QLineEdit("active")
        self.line = QComboBox()
        self.line.setEditable(False)
        self._line_ids: list[int] = []
        for line_id, name in (line_options or []):
            self._line_ids.append(line_id)
            self.line.addItem(f"{line_id}: {name}", line_id)
        if selected_line_id is not None:
            idx = self.line.findData(selected_line_id)
            if idx >= 0:
                self.line.setCurrentIndex(idx)
        self.labels = QLineEdit()
        self.labels.setPlaceholderText("Opcional: labels separadas por coma")
        form.addRow("Number", self.number)
        form.addRow("Device IP", self.device_ip)
        form.addRow("Protocol", self.protocol)
        form.addRow("Status", self.status)
        form.addRow("Line", self.line)
        form.addRow("Labels", self.labels)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> dict[str, object]:
        labels = [item.strip() for item in self.labels.text().split(",") if item.strip()]
        line_id = self.line.currentData()
        return {
            "number": self.number.value(),
            "device_ip": self.device_ip.text().strip(),
            "protocol": self.protocol.currentText().strip(),
            "status": self.status.text().strip(),
            "line": int(line_id) if isinstance(line_id, int) else 0,
            "labels": labels,
        }


class ForgePanel(QWidget):
    connect_requested = pyqtSignal(str, str, str)
    refresh_requested = pyqtSignal()
    assign_requested = pyqtSignal(int, int, list)
    send_conf_requested = pyqtSignal(int)
    project_changed = pyqtSignal(int)
    label_selected = pyqtSignal(dict)
    camera_labels_dropped = pyqtSignal(int, list)
    gpio_labels_dropped = pyqtSignal(str, list)
    bulk_clear_requested = pyqtSignal(list)

    FILTER_ALL = "all"
    FILTER_NO_CAMERA = "no_camera"
    FILTER_NO_GPIO = "no_gpio"
    FILTER_ASSIGNED = "assigned"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._label_source: list[str | dict] = []
        self._camera_for_label: dict[str, list[str]] = {}
        self._gpio_for_label: dict[str, str] = {}
        self._filter_mode: str = self.FILTER_ALL
        self._group_mode: str = "none"
        self._build_ui()
        self._install_shortcuts()
        self._restore_state()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        self.base_url = QLineEdit("https://forge.iinia.ai/api/swagger/")
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.token = QLineEdit()
        self.token.setPlaceholderText("Token opcional")

        actions = QHBoxLayout()
        self.connect_button = QPushButton("Conectar Forge")
        self.refresh_button = QPushButton("Refrescar Forge")
        self.connect_button.setToolTip("Abrir configuración Forge")
        self.coverage_label = QLabel("0 labels · 0 cám · 0 gpio")
        self.coverage_label.setStyleSheet(
            "padding:4px 10px; border-radius:10px; background:#1b2028; color:#9fb2c8; font-weight:600;"
        )
        actions.addWidget(self.connect_button)
        actions.addWidget(self.refresh_button)
        actions.addStretch(1)
        actions.addWidget(self.coverage_label)

        self.projects = QListWidget()
        self.cameras = CameraListWidget()
        self.lines = QListWidget()
        self.labels = DragListWidget()
        self.labels.setItemDelegate(ColorChipDelegate(self.labels))
        self.labels.setUniformItemSizes(False)
        self.labels.itemClicked.connect(self._on_label_item_clicked)
        self.assigned = QListWidget()
        self.gpio_ports = PortListWidget()
        self.gpio_port = QComboBox()
        self.gpio_port.setEditable(True)
        self.gpio_port.addItems([f"GPIO{n}" for n in range(2, 28)])
        for widget in (self.projects, self.cameras, self.lines, self.assigned, self.gpio_ports):
            widget.setSpacing(4)
            widget.setStyleSheet(
                """
                QListWidget::item {
                    margin: 2px;
                    padding: 6px 8px;
                    border: 1px solid #2a313a;
                    border-radius: 6px;
                    background: #171a21;
                }
                QListWidget::item:selected {
                    background: #243043;
                    border-color: #4d6b8a;
                }
                """
            )
        self.labels.setStyleSheet(
            """
            QListWidget { background:#10141b; border:1px solid #2a313a; border-radius:6px; }
            QListWidget::item { padding: 0px; }
            QListWidget::item:selected { background:#243043; }
            """
        )

        self.line_name = QLineEdit()
        self.line_name.setPlaceholderText("New line name")
        self.component_filter = QLineEdit()
        self.component_filter.setPlaceholderText("Filtrar / pegar labels")
        self.component_filter.textChanged.connect(self.filter_labels)

        self.create_camera_button = QPushButton("Crear cámara")
        self.create_line_button = QPushButton("Crear línea")
        self.assign_button = QPushButton("Asignar a GPIO")
        self.assign_button.setToolTip("Asigna las labels seleccionadas al puerto GPIO actual")
        self.bulk_clear_button = QPushButton("Limpiar GPIO")
        self.bulk_clear_button.setToolTip("Quita la asignación GPIO de las labels seleccionadas")
        self.bulk_clear_button.clicked.connect(self._emit_bulk_clear)
        self.send_conf_button = QPushButton("Enviar conf a línea")

        self.preview_status = QTextEdit()
        self.preview_status.setReadOnly(True)
        self.preview_status.setMaximumHeight(110)
        self.preview_status.setPlaceholderText("Forge status...")

        self.project_summary = QTextEdit()
        self.project_summary.setReadOnly(True)
        self.project_summary.setMaximumHeight(140)
        self.project_summary.setPlaceholderText("Project stats / preview...")

        self.label_gallery = LabelGalleryWidget()
        self.label_gallery.selected.connect(self._on_gallery_label_selected)
        self.label_search = QLineEdit()
        self.label_search.setPlaceholderText("Buscar label, color o tipo  (presiona / para enfocar)")
        self.label_search.textChanged.connect(self.filter_label_views)
        self.label_detail = QLabel("Select a label to inspect")
        self.label_detail.setWordWrap(True)
        self.label_detail.setStyleSheet("padding:10px; border:1px solid #2a313a; border-radius:8px; background:#111318; color:#d8dde3;")
        self.label_detail_image = QLabel()
        self.label_detail_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label_detail_image.setMinimumHeight(180)
        self.label_detail_image.setStyleSheet("background:#0f1115; border:1px solid #2a313a; border-radius:8px; color:#8b95a1;")

        self.project_preview = QLabel("Preview del proyecto")
        self.project_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.project_preview.setMinimumHeight(220)
        self.project_preview.setStyleSheet("background:#111318; color:#8b95a1; border:1px solid #2a313a; border-radius:8px;")

        self.gpio_preview = QLabel("GPIO preview")
        self.gpio_preview.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.gpio_preview.setWordWrap(True)
        self.gpio_preview.setTextFormat(Qt.TextFormat.PlainText)
        self.gpio_preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.gpio_preview.setMinimumHeight(120)
        self.gpio_preview.setStyleSheet("padding:8px; border:1px solid #2a313a; border-radius:8px; background:#111318; color:#d8dde3;")

        self.labels_hint = QLabel("0 labels")
        self.labels_hint.setStyleSheet("color:#9fb2c8;")

        self._build_filter_chips()
        self._build_group_combo()

        self.project_section = CollapsibleSection("Projects", "Select a project", expanded=True)
        self.project_section.content_layout.addWidget(self.projects)

        self.camera_section = CollapsibleSection("Cameras", "Select a camera", expanded=True)
        self.camera_section.content_layout.addWidget(self.cameras)
        self.camera_section.content_layout.addWidget(self.create_camera_button)

        self.line_section = CollapsibleSection("Lines", "Select a line", expanded=True)
        self.line_section.content_layout.addWidget(self.lines)
        self.line_section.content_layout.addWidget(self.line_name)
        self.line_section.content_layout.addWidget(self.create_line_button)

        labels_box = QWidget(self)
        labels_layout = QVBoxLayout(labels_box)
        labels_layout.setContentsMargins(0, 0, 0, 0)
        labels_layout.setSpacing(6)
        header_row = QHBoxLayout()
        header_row.addWidget(QLabel("Labels"))
        header_row.addStretch(1)
        header_row.addWidget(QLabel("Group:"))
        header_row.addWidget(self.group_combo)
        labels_layout.addLayout(header_row)
        labels_layout.addLayout(self.filter_chip_layout)
        labels_layout.addWidget(self.component_filter)
        labels_layout.addWidget(self.labels_hint)
        labels_layout.addWidget(self.labels, 1)

        self.projects.currentItemChanged.connect(
            lambda current, _previous: self._sync_compact_section(self.project_section, current, "Select a project")
        )
        self.cameras.currentItemChanged.connect(
            lambda current, _previous: self._sync_compact_section(self.camera_section, current, "Select a camera")
        )
        self.lines.currentItemChanged.connect(
            lambda current, _previous: self._sync_compact_section(self.line_section, current, "Select a line")
        )

        left_box = QWidget(self)
        left_layout = QVBoxLayout(left_box)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)
        left_layout.addWidget(self.project_section)
        left_layout.addWidget(self.camera_section)
        left_layout.addWidget(self.line_section)
        left_layout.addWidget(self.preview_status)

        right_tabs = QTabWidget()
        right_tabs.setTabPosition(QTabWidget.TabPosition.North)

        gpio_tab = QWidget()
        gpio_layout = QVBoxLayout(gpio_tab)
        gpio_layout.setContentsMargins(4, 4, 4, 4)
        gpio_layout.setSpacing(6)
        gpio_layout.addWidget(QLabel("Assigned components"))
        gpio_layout.addWidget(self.assigned)
        gpio_layout.addWidget(QLabel("GPIO ports"))
        gpio_layout.addWidget(self.gpio_ports, 1)
        gpio_layout.addWidget(QLabel("Resumen GPIO"))
        gpio_layout.addWidget(self.gpio_preview)

        gallery_tab = QWidget()
        gallery_layout = QVBoxLayout(gallery_tab)
        gallery_layout.setContentsMargins(4, 4, 4, 4)
        gallery_layout.setSpacing(6)
        gallery_layout.addWidget(self.label_search)
        gallery_layout.addWidget(self.label_gallery, 1)

        detail_tab = QWidget()
        detail_layout = QVBoxLayout(detail_tab)
        detail_layout.setContentsMargins(4, 4, 4, 4)
        detail_layout.setSpacing(6)
        detail_layout.addWidget(self.label_detail_image)
        detail_layout.addWidget(self.label_detail)
        detail_layout.addWidget(QLabel("Project preview"))
        detail_layout.addWidget(self.project_preview, 1)
        detail_layout.addWidget(self.project_summary)

        right_tabs.addTab(gpio_tab, "GPIO & Cámaras")
        right_tabs.addTab(gallery_tab, "Galería")
        right_tabs.addTab(detail_tab, "Detalle")
        self.right_tabs = right_tabs

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(left_box)
        self.splitter.addWidget(labels_box)
        self.splitter.addWidget(right_tabs)
        self.splitter.setStretchFactor(0, 2)
        self.splitter.setStretchFactor(1, 3)
        self.splitter.setStretchFactor(2, 3)
        self.splitter.setSizes([280, 380, 420])

        bottom = QHBoxLayout()
        bottom.addWidget(QLabel("GPIO:"))
        bottom.addWidget(self.gpio_port)
        bottom.addWidget(self.assign_button)
        bottom.addWidget(self.bulk_clear_button)
        bottom.addStretch(1)
        bottom.addWidget(self.send_conf_button)

        root.addLayout(actions)
        root.addWidget(self.splitter, 1)
        root.addLayout(bottom)

    def _build_filter_chips(self) -> None:
        self.filter_chip_layout = QHBoxLayout()
        self.filter_chip_layout.setContentsMargins(0, 0, 0, 0)
        self.filter_chip_layout.setSpacing(4)
        self._filter_group = QButtonGroup(self)
        self._filter_group.setExclusive(True)
        self._filter_buttons: dict[str, QToolButton] = {}
        chips = [
            (self.FILTER_ALL, "Todos"),
            (self.FILTER_NO_CAMERA, "Sin cámara"),
            (self.FILTER_NO_GPIO, "Sin GPIO"),
            (self.FILTER_ASSIGNED, "Asignados"),
        ]
        for mode, label in chips:
            btn = QToolButton()
            btn.setText(label)
            btn.setCheckable(True)
            btn.setAutoExclusive(False)
            btn.setStyleSheet(
                """
                QToolButton {
                    padding: 4px 10px;
                    border: 1px solid #2a313a;
                    border-radius: 12px;
                    background: #141820;
                    color: #cfd6e1;
                }
                QToolButton:checked {
                    background: #243043;
                    border-color: #4d6b8a;
                    color: #ffffff;
                }
                QToolButton:hover { background: #1b2028; }
                """
            )
            btn.clicked.connect(lambda _checked=False, m=mode: self._set_filter_mode(m))
            self._filter_group.addButton(btn)
            self._filter_buttons[mode] = btn
            self.filter_chip_layout.addWidget(btn)
        self.filter_chip_layout.addStretch(1)
        self._filter_buttons[self.FILTER_ALL].setChecked(True)

    def _build_group_combo(self) -> None:
        self.group_combo = QComboBox()
        self.group_combo.addItem("Sin agrupar", "none")
        self.group_combo.addItem("Por prefijo", "prefix")
        self.group_combo.addItem("Por tipo", "type")
        self.group_combo.addItem("Por estado", "status")
        self.group_combo.currentIndexChanged.connect(self._on_group_changed)

    def _install_shortcuts(self) -> None:
        focus_search = QShortcut(QKeySequence("/"), self)
        focus_search.activated.connect(lambda: self.label_search.setFocus())
        focus_search.setContext(Qt.ShortcutContext.WindowShortcut)

        focus_filter = QShortcut(QKeySequence(Qt.Modifier.CTRL | Qt.Key.Key_F), self)
        focus_filter.activated.connect(lambda: self.component_filter.setFocus())

        clear = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        clear.activated.connect(self._clear_filters)

        select_all = QShortcut(QKeySequence(Qt.Modifier.CTRL | Qt.Key.Key_A), self.labels)
        select_all.activated.connect(self._select_all_visible_labels)
        select_all.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)

    def _clear_filters(self) -> None:
        self.label_search.clear()
        self.component_filter.clear()
        self._set_filter_mode(self.FILTER_ALL)

    def _select_all_visible_labels(self) -> None:
        self.labels.clearSelection()
        for i in range(self.labels.count()):
            item = self.labels.item(i)
            if item.isHidden() or item.data(Qt.ItemDataRole.UserRole + 1):
                continue
            item.setSelected(True)

    def _set_filter_mode(self, mode: str) -> None:
        self._filter_mode = mode
        for key, btn in self._filter_buttons.items():
            btn.setChecked(key == mode)
        self.filter_label_views(self.label_search.text())

    def _on_group_changed(self, _index: int) -> None:
        self._group_mode = self.group_combo.currentData() or "none"
        self.set_labels(self._label_source)

    def set_status(self, text: str) -> None:
        self.preview_status.setPlainText(text)

    def set_summary(self, text: str) -> None:
        self.project_summary.setPlainText(text)

    def set_projects(self, items: list[tuple[int, str]]) -> None:
        self.projects.clear()
        for project_id, name in items:
            item = QListWidgetItem(f"{project_id}: {name}")
            item.setData(Qt.ItemDataRole.UserRole, project_id)
            self.projects.addItem(item)
        self.project_section.set_summary(f"{self.projects.count()} projects" if self.projects.count() else "Select a project")

    def set_cameras(self, items: list[tuple[int, str, list[str]]]) -> None:
        self.cameras.clear()
        for camera_id, name, components in items:
            count = len(components)
            suffix = f"  ({count})" if count else ""
            item = QListWidgetItem(f"{camera_id}: {name}{suffix}")
            item.setData(Qt.ItemDataRole.UserRole, camera_id)
            tooltip = f"Drop labels here to assign to {name}"
            if components:
                preview = ", ".join(components[:8])
                if len(components) > 8:
                    preview += f" (+{len(components) - 8})"
                tooltip += f"\nLabels: {preview}"
            item.setToolTip(tooltip)
            item.setSizeHint(item.sizeHint() * 1.3)
            self.cameras.addItem(item)
        self.camera_section.set_summary(f"{self.cameras.count()} cameras" if self.cameras.count() else "Select a camera")

    def set_lines(self, items: list[tuple[int, str]]) -> None:
        self.lines.clear()
        for line_id, name in items:
            item = QListWidgetItem(f"{line_id}: {name}")
            item.setData(Qt.ItemDataRole.UserRole, line_id)
            item.setSizeHint(item.sizeHint() * 1.2)
            self.lines.addItem(item)
        self.line_section.set_summary(f"{self.lines.count()} lines" if self.lines.count() else "Select a line")

    def _label_dict(self, label: object) -> dict:
        if isinstance(label, dict):
            data = dict(label)
            data["name"] = str(data.get("name", "")).strip()
            return data
        text = str(label).strip()
        return {"name": text, "type": "", "color": "", "preview_base64": ""}

    def set_labels(self, labels: list[str] | list[dict]) -> None:
        previous_selected = {item.data(Qt.ItemDataRole.UserRole)["name"] for item in self.labels.selectedItems() if isinstance(item.data(Qt.ItemDataRole.UserRole), dict)}
        self._label_source = list(labels)
        self.labels.clear()
        normalized = [self._label_dict(label) for label in labels if self._label_dict(label)["name"]]

        groups = self._group_labels(normalized)
        for header, members in groups:
            if header:
                head_item = QListWidgetItem(header)
                head_item.setFlags(Qt.ItemFlag.NoItemFlags)
                head_item.setData(Qt.ItemDataRole.UserRole + 1, True)
                self.labels.addItem(head_item)
            for data in members:
                self._append_label_item(data, restore_selection=previous_selected)

        self.labels_hint.setText(
            f"{len(normalized)} labels (drag a cámaras/GPIO · Ctrl+A para todos los visibles · / para buscar)"
        )
        self._refresh_label_tooltips()
        self._update_coverage()
        self.filter_label_views(self.label_search.text())

    def _append_label_item(self, data: dict, *, restore_selection: set[str]) -> None:
        name = data.get("name", "")
        item = QListWidgetItem(name)
        item.setData(Qt.ItemDataRole.UserRole, data)
        if name in restore_selection:
            item.setSelected(True)
        self.labels.addItem(item)

    def _group_labels(self, labels: list[dict]) -> list[tuple[str, list[dict]]]:
        if self._group_mode == "none" or not labels:
            return [("", labels)]
        buckets: dict[str, list[dict]] = {}
        if self._group_mode == "prefix":
            for data in labels:
                key = _label_prefix(data.get("name", ""))
                buckets.setdefault(key, []).append(data)
        elif self._group_mode == "type":
            for data in labels:
                key = (str(data.get("type", "")).strip() or "—").lower()
                buckets.setdefault(key, []).append(data)
        elif self._group_mode == "status":
            for data in labels:
                name = data.get("name", "")
                has_cam = bool(self._camera_for_label.get(name))
                has_gpio = bool(self._gpio_for_label.get(name))
                if has_cam and has_gpio:
                    key = "asignados"
                elif has_cam or has_gpio:
                    key = "parciales"
                else:
                    key = "sin asignar"
                buckets.setdefault(key, []).append(data)
        else:
            return [("", labels)]

        ordered = sorted(buckets.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        return [(f"{key.upper()}  ({len(members)})", members) for key, members in ordered]

    def _refresh_label_tooltips(self) -> None:
        for i in range(self.labels.count()):
            item = self.labels.item(i)
            data = item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(data, dict):
                continue
            name = data.get("name", "")
            cam_list = self._camera_for_label.get(name, [])
            gpio = self._gpio_for_label.get(name, "")
            tooltip_lines = [f"<b>{name}</b>"]
            if data.get("type"):
                tooltip_lines.append(f"Tipo: {data.get('type')}")
            if data.get("color"):
                tooltip_lines.append(f"Color: {data.get('color')}")
            if cam_list:
                tooltip_lines.append("Cámaras: " + ", ".join(cam_list[:6]) + (f" (+{len(cam_list) - 6})" if len(cam_list) > 6 else ""))
            else:
                tooltip_lines.append("<i>Sin cámara asignada</i>")
            if gpio:
                tooltip_lines.append(f"GPIO: {gpio}")
            else:
                tooltip_lines.append("<i>Sin GPIO asignado</i>")
            item.setToolTip("<br>".join(tooltip_lines))

    def filter_labels(self, text: str) -> None:
        self.filter_label_views(self.label_search.text() or text)

    def filter_label_views(self, text: str) -> None:
        needle = text.strip().lower()
        component_needle = self.component_filter.text().strip().lower()
        last_visible_index = -1
        active_group_visible = False
        group_indexes: list[int] = []

        for i in range(self.labels.count()):
            item = self.labels.item(i)
            is_header = bool(item.data(Qt.ItemDataRole.UserRole + 1))
            if is_header:
                if last_visible_index >= 0 and not active_group_visible:
                    self.labels.item(last_visible_index).setHidden(True)
                last_visible_index = i
                active_group_visible = False
                group_indexes.append(i)
                item.setHidden(False)
                continue
            data = item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(data, dict):
                item.setHidden(True)
                continue
            name = data.get("name", "")
            haystack = " ".join(str(data.get(key, "")) for key in ("name", "type", "color")).lower()
            text_match = (not needle or needle in haystack) and (not component_needle or component_needle in haystack)
            mode_match = self._matches_filter_mode(name)
            visible = text_match and mode_match
            item.setHidden(not visible)
            if visible:
                active_group_visible = True

        if last_visible_index >= 0 and not active_group_visible:
            self.labels.item(last_visible_index).setHidden(True)

        self.label_gallery.set_filter(needle or component_needle)
        visible_items = [self.labels.item(i) for i in range(self.labels.count())
                         if not self.labels.item(i).isHidden() and not self.labels.item(i).data(Qt.ItemDataRole.UserRole + 1)]
        current = self.labels.currentItem()
        if visible_items and (current is None or current.isHidden() or current.data(Qt.ItemDataRole.UserRole + 1)):
            self.labels.setCurrentItem(visible_items[0])
            self._on_label_item_clicked(visible_items[0])

        self.labels_hint.setText(
            f"{len(visible_items)} de {sum(1 for i in range(self.labels.count()) if not self.labels.item(i).data(Qt.ItemDataRole.UserRole + 1))} labels"
        )

    def _matches_filter_mode(self, name: str) -> bool:
        if self._filter_mode == self.FILTER_ALL:
            return True
        has_cam = bool(self._camera_for_label.get(name))
        has_gpio = bool(self._gpio_for_label.get(name))
        if self._filter_mode == self.FILTER_NO_CAMERA:
            return not has_cam
        if self._filter_mode == self.FILTER_NO_GPIO:
            return not has_gpio
        if self._filter_mode == self.FILTER_ASSIGNED:
            return has_cam and has_gpio
        return True

    def _selection_summary(self, item: QListWidgetItem | None) -> str:
        if item is None:
            return ""
        text = item.text().strip()
        if ":" in text:
            text = text.split(":", 1)[1].strip()
        if "[" in text:
            text = text.split("[", 1)[0].strip()
        if len(text) > 42:
            text = text[:39].rstrip() + "..."
        return text

    def _sync_compact_section(self, section: CollapsibleSection, item: QListWidgetItem | None, fallback: str) -> None:
        if item is None:
            section.set_summary(fallback)
            return
        section.set_summary(self._selection_summary(item) or fallback)
        section.set_expanded(False)

    def set_assigned(self, labels: list[str]) -> None:
        self.assigned.clear()
        for label in labels:
            text = _label_text(label)
            if text:
                self.assigned.addItem(text)

    def set_gpio_assignments(self, assignments: dict[str, str]) -> None:
        port_map: dict[str, list[str]] = {}
        for label, port in sorted(assignments.items()):
            port_text = str(port).strip()
            text = _label_text(label)
            if text and port_text:
                port_map.setdefault(port_text, []).append(text)

        self.gpio_ports.clear()
        for port in [f"GPIO{n}" for n in range(2, 28)]:
            labels = port_map.get(port, [])
            count = len(labels)
            suffix = f"  ·  {count} labels" if count else "  ·  vacío"
            item = QListWidgetItem(f"{port}{suffix}")
            item.setData(Qt.ItemDataRole.UserRole, port)
            tooltip = f"Drop labels here to assign to {port}"
            if labels:
                tooltip += "\n" + "\n".join(f"• {label}" for label in labels)
            item.setToolTip(tooltip)
            item.setSizeHint(item.sizeHint() * 1.25)
            self.gpio_ports.addItem(item)

        if port_map:
            lines = []
            for port, labels in sorted(port_map.items()):
                preview = ", ".join(_short_label(label) for label in labels[:5])
                if len(labels) > 5:
                    preview += f" (+{len(labels) - 5})"
                lines.append(f"{port}  →  {preview}")
            if len(lines) > 12:
                hidden = len(lines) - 12
                lines = lines[:12] + [f"+{hidden} más puertos"]
            self.gpio_preview.setText("\n".join(lines))
        else:
            self.gpio_preview.setText("Drop labels onto a GPIO port")

        self._gpio_for_label = {str(label): str(port) for label, port in assignments.items() if str(port).strip()}
        self._refresh_label_tooltips()
        self._update_coverage()
        self.filter_label_views(self.label_search.text())

    def set_label_assignments(self, camera_for_label: dict[str, list[str]]) -> None:
        self._camera_for_label = {name: list(cams) for name, cams in (camera_for_label or {}).items()}
        self._refresh_label_tooltips()
        self._update_coverage()
        self.filter_label_views(self.label_search.text())

    def _update_coverage(self) -> None:
        total = sum(1 for i in range(self.labels.count()) if not self.labels.item(i).data(Qt.ItemDataRole.UserRole + 1))
        if total == 0:
            self.coverage_label.setText("0 labels")
            return
        names = []
        for i in range(self.labels.count()):
            item = self.labels.item(i)
            if item.data(Qt.ItemDataRole.UserRole + 1):
                continue
            data = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(data, dict):
                names.append(data.get("name", ""))
        with_camera = sum(1 for name in names if self._camera_for_label.get(name))
        with_gpio = sum(1 for name in names if self._gpio_for_label.get(name))
        self.coverage_label.setText(
            f"{total} labels · cám {with_camera}/{total} · gpio {with_gpio}/{total}"
        )

    def set_label_previews(self, items: list[dict]) -> None:
        self._label_source = list(items)
        self.label_gallery.set_items(items)
        if items:
            self.set_selected_label_preview(items[0])
        else:
            self.label_detail.setText("Select a label to inspect")
            self.label_detail_image.clear()

    def set_selected_label_preview(self, item: dict) -> None:
        if not isinstance(item, dict):
            return
        name = str(item.get("name", "")).strip()
        label_type = str(item.get("type", "")).strip()
        color = str(item.get("color", "")).strip()
        crop = str(item.get("preview_base64", "")).strip()
        cams = self._camera_for_label.get(name, [])
        gpio = self._gpio_for_label.get(name, "")
        text = "\n".join([
            f"Name: {name}",
            f"Type: {label_type or 'n/a'}",
            f"Color: {color or 'n/a'}",
            f"Cámaras: {', '.join(cams) if cams else '—'}",
            f"GPIO: {gpio or '—'}",
        ])
        self.label_detail.setText(text)
        pixmap = QPixmap()
        if crop and pixmap.loadFromData(base64.b64decode(crop)):
            self.label_detail_image.setPixmap(
                pixmap.scaled(
                    420,
                    180,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        else:
            self.label_detail_image.setText("No crop available")

    def _on_gallery_label_selected(self, item: dict) -> None:
        self.set_selected_label_preview(item)
        self.label_selected.emit(item)

    def _on_label_item_clicked(self, item: QListWidgetItem) -> None:
        if item.data(Qt.ItemDataRole.UserRole + 1):
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(data, dict):
            self.set_selected_label_preview(data)
            self.label_selected.emit(data)

    def _emit_bulk_clear(self) -> None:
        labels = self.selected_labels()
        if labels:
            self.bulk_clear_requested.emit(labels)

    def set_project_preview(self, image_data: bytes | None) -> None:
        if not image_data:
            self.project_preview.setText("Preview del proyecto")
            self.project_preview.setPixmap(QPixmap())
            return
        pixmap = QPixmap()
        if pixmap.loadFromData(image_data):
            self.project_preview.setPixmap(
                pixmap.scaled(
                    self.project_preview.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self.project_preview.setText("")
        else:
            self.project_preview.setText("No se pudo cargar preview")
            self.project_preview.setPixmap(QPixmap())

    def connection_values(self) -> dict[str, str]:
        return {
            "base_url": self.base_url.text().strip(),
            "username": self.username.text().strip(),
            "password": self.password.text().strip(),
            "token": self.token.text().strip(),
        }

    def set_connection_values(self, *, base_url: str = "", username: str = "", password: str = "", token: str = "") -> None:
        self.base_url.setText(base_url)
        self.username.setText(username)
        self.password.setText(password)
        self.token.setText(token)

    def selected_gpio_port(self) -> str:
        return self.gpio_port.currentText().strip()

    def selected_camera_id(self) -> int | None:
        item = self.cameras.currentItem()
        if not item:
            return None
        raw = item.data(Qt.ItemDataRole.UserRole)
        return int(raw) if isinstance(raw, int) else None

    def selected_project_id(self) -> int | None:
        item = self.projects.currentItem()
        if not item:
            return None
        raw = item.data(Qt.ItemDataRole.UserRole)
        return int(raw) if isinstance(raw, int) else None

    def selected_line_id(self) -> int | None:
        item = self.lines.currentItem()
        if not item:
            return None
        raw = item.data(Qt.ItemDataRole.UserRole)
        return int(raw) if isinstance(raw, int) else None

    def line_options(self) -> list[tuple[int, str]]:
        options: list[tuple[int, str]] = []
        for i in range(self.lines.count()):
            item = self.lines.item(i)
            line_id = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(line_id, int):
                text = item.text().split(":", 1)[1].strip() if ":" in item.text() else item.text()
                options.append((line_id, text))
        return options

    def selected_labels(self) -> list[str]:
        selected = []
        for item in self.labels.selectedItems():
            if item.data(Qt.ItemDataRole.UserRole + 1):
                continue
            data = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(data, dict):
                name = str(data.get("name", "")).strip()
                if name:
                    selected.append(name)
            else:
                selected.append(item.text())
        if selected:
            return list(dict.fromkeys(selected))
        item = self.labels.currentItem()
        if not item or item.data(Qt.ItemDataRole.UserRole + 1):
            return []
        data = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(data, dict):
            name = str(data.get("name", "")).strip()
            return [name] if name else []
        return [item.text()]

    def _restore_state(self) -> None:
        try:
            if not UI_STATE_PATH.exists():
                return
            payload = json.loads(UI_STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(payload, dict):
            return
        sizes = payload.get("forge_splitter_sizes")
        if isinstance(sizes, list) and all(isinstance(v, int) for v in sizes) and len(sizes) == self.splitter.count():
            self.splitter.setSizes(sizes)
        for section, key in (
            (self.project_section, "section_projects"),
            (self.camera_section, "section_cameras"),
            (self.line_section, "section_lines"),
        ):
            if key in payload and isinstance(payload[key], bool):
                section.set_expanded(payload[key])
        group = payload.get("group_mode")
        if isinstance(group, str):
            idx = self.group_combo.findData(group)
            if idx >= 0:
                self.group_combo.setCurrentIndex(idx)
        filter_mode = payload.get("filter_mode")
        if isinstance(filter_mode, str) and filter_mode in self._filter_buttons:
            self._set_filter_mode(filter_mode)
        tab_index = payload.get("right_tab_index")
        if isinstance(tab_index, int) and 0 <= tab_index < self.right_tabs.count():
            self.right_tabs.setCurrentIndex(tab_index)

    def save_state(self) -> None:
        try:
            UI_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            payload: dict = {}
            if UI_STATE_PATH.exists():
                try:
                    existing = json.loads(UI_STATE_PATH.read_text(encoding="utf-8"))
                    if isinstance(existing, dict):
                        payload = existing
                except Exception:
                    payload = {}
            payload["forge_splitter_sizes"] = self.splitter.sizes()
            payload["section_projects"] = self.project_section.is_expanded()
            payload["section_cameras"] = self.camera_section.is_expanded()
            payload["section_lines"] = self.line_section.is_expanded()
            payload["group_mode"] = self._group_mode
            payload["filter_mode"] = self._filter_mode
            payload["right_tab_index"] = self.right_tabs.currentIndex()
            UI_STATE_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
