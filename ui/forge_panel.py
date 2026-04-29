"""Forge operations panel for project and camera assignment."""

from __future__ import annotations

import ast
import base64

from PyQt6.QtCore import QMimeData, QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QDrag, QPixmap
from PyQt6.QtWidgets import (
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
    QPushButton,
    QSplitter,
    QScrollArea,
    QToolButton,
    QTextEdit,
    QVBoxLayout,
    QSpinBox,
    QWidget,
)


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


class DragListWidget(QListWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDragDropMode(QListWidget.DragDropMode.DragOnly)

    def startDrag(self, supportedActions):  # noqa: N802
        items = self.selectedItems()
        if not items:
            item = self.currentItem()
            items = [item] if item else []
        labels = [_label_text(item.data(Qt.ItemDataRole.UserRole) or item.text()) for item in items if item]
        mime = QMimeData()
        mime.setText("\n".join(label for label in labels if label.strip()))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(supportedActions)


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
                padding: 10px 12px;
                border: 1px solid #2a313a;
                border-radius: 10px;
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
        self.content_layout.setContentsMargins(6, 6, 6, 6)
        self.content_layout.setSpacing(8)

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
        self.image.setMinimumHeight(110)
        self.image.setStyleSheet("background:#0f1115; border-radius:6px; color:#8b95a1;")

        crop = str(data.get("preview_base64", "")).strip()
        pixmap = QPixmap()
        if crop and pixmap.loadFromData(base64.b64decode(crop)):
            self.image.setPixmap(pixmap.scaled(220, 110, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        else:
            self.image.setText("No crop")

        self.title = QLabel(str(data.get("name", "")))
        self.title.setStyleSheet("font-weight: 600;")
        self.subtitle = QLabel(f"{data.get('type', '')}")
        self.subtitle.setStyleSheet("color:#9fb2c8; font-size: 11px;")
        layout.addWidget(self.image)
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.clicked.emit(self._data)
        super().mousePressEvent(event)


class LabelGalleryWidget(QWidget):
    selected = pyqtSignal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[dict[str, object]] = []
        self._cards: list[LabelPreviewCard] = []
        self._filter_text = ""
        layout = QVBoxLayout(self)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.content = QWidget()
        self.grid = QGridLayout(self.content)
        self.grid.setSpacing(10)
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
        for index, item in enumerate(visible_items[:24]):
            card = LabelPreviewCard(item)
            card.clicked.connect(self.selected.emit)
            self._cards.append(card)
            self.grid.addWidget(card, index // 2, index % 2)
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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._label_source: list[str | dict] = []
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

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
        actions.addWidget(self.connect_button)
        actions.addWidget(self.refresh_button)

        self.projects = QListWidget()
        self.cameras = CameraListWidget()
        self.lines = QListWidget()
        self.labels = DragListWidget()
        self.labels.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.labels.itemClicked.connect(self._on_label_item_clicked)
        self.assigned = QListWidget()
        self.gpio_ports = PortListWidget()
        self.gpio_port = QComboBox()
        self.gpio_port.setEditable(True)
        self.gpio_port.addItems([f"GPIO{n}" for n in range(2, 28)])
        for widget in (self.projects, self.cameras, self.lines, self.labels, self.assigned, self.gpio_ports):
            widget.setSpacing(6)
            widget.setStyleSheet(
                """
                QListWidget::item {
                    margin: 3px;
                    padding: 8px;
                    border: 1px solid #2a313a;
                    border-radius: 8px;
                    background: #171a21;
                }
                QListWidget::item:selected {
                    background: #243043;
                    border-color: #4d6b8a;
                }
                """
            )

        self.line_name = QLineEdit()
        self.line_name.setPlaceholderText("New line name")
        self.component_filter = QLineEdit()
        self.component_filter.setPlaceholderText("Filtrar / pegar labels")
        self.component_filter.textChanged.connect(self.filter_labels)

        self.create_camera_button = QPushButton("Crear cámara")
        self.create_line_button = QPushButton("Crear línea")
        self.assign_button = QPushButton("Asignar GPIO")
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
        self.label_search.setPlaceholderText("Buscar label, color o tipo")
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
        self.gpio_preview.setMaximumHeight(120)
        self.gpio_preview.setStyleSheet("padding:8px; border:1px solid #2a313a; border-radius:8px; background:#111318; color:#d8dde3;")

        self.labels_hint = QLabel("0 labels")

        self.project_section = CollapsibleSection("Projects", "Select a project", expanded=True)
        self.project_section.content_layout.addWidget(self.projects)

        self.camera_section = CollapsibleSection("Cameras", "Select a camera", expanded=True)
        self.camera_section.content_layout.addWidget(self.cameras)
        self.camera_section.content_layout.addWidget(self.create_camera_button)

        self.line_section = CollapsibleSection("Lines", "Select a line", expanded=True)
        self.line_section.content_layout.addWidget(self.lines)
        self.line_section.content_layout.addWidget(self.line_name)
        self.line_section.content_layout.addWidget(self.create_line_button)

        self.labels_section = CollapsibleSection("Labels", "Drag & drop source", expanded=True)
        self.labels_section.content_layout.addWidget(self.component_filter)
        self.labels_section.content_layout.addWidget(self.labels_hint)
        self.labels_section.content_layout.addWidget(self.labels)

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
        left_layout.addWidget(self.project_section)
        left_layout.addWidget(self.camera_section)
        left_layout.addWidget(self.line_section)
        left_layout.addWidget(self.labels_section)

        right_box = QWidget(self)
        right_layout = QVBoxLayout(right_box)
        right_layout.addWidget(QLabel("Assigned components"))
        right_layout.addWidget(self.assigned)
        right_layout.addWidget(QLabel("GPIO ports"))
        right_layout.addWidget(self.gpio_ports)
        right_layout.addWidget(self.gpio_preview)
        right_layout.addWidget(self.label_search)
        right_layout.addWidget(QLabel("Label gallery"))
        right_layout.addWidget(self.label_gallery)
        right_layout.addWidget(QLabel("Label detail"))
        right_layout.addWidget(self.label_detail_image)
        right_layout.addWidget(self.label_detail)
        right_layout.addWidget(QLabel("Project preview"))
        right_layout.addWidget(self.project_preview)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        left_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        left_scroll.setWidget(left_box)

        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        right_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        right_scroll.setWidget(right_box)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_scroll)
        splitter.addWidget(right_scroll)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)

        bottom = QHBoxLayout()
        bottom.addWidget(self.gpio_port)
        bottom.addWidget(self.assign_button)
        bottom.addWidget(self.send_conf_button)

        root.addLayout(actions)
        root.addWidget(splitter)
        root.addLayout(bottom)

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
            suffix = f" [{', '.join(components)}]" if components else ""
            item = QListWidgetItem(f"{camera_id}: {name}{suffix}")
            item.setData(Qt.ItemDataRole.UserRole, camera_id)
            item.setToolTip(f"Drop labels here to assign to {name}")
            item.setSizeHint(item.sizeHint() * 1.4)
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

    def set_labels(self, labels: list[str] | list[dict]) -> None:
        self._label_source = list(labels)
        self.labels.clear()
        for label in labels:
            if isinstance(label, dict):
                name = str(label.get("name", "")).strip()
                if not name:
                    continue
                item = QListWidgetItem(name)
                item.setData(Qt.ItemDataRole.UserRole, label)
                color = str(label.get("color", "")).strip()
                if color:
                    item.setBackground(QColor(color))
                self.labels.addItem(item)
            else:
                text = str(label).strip()
                if not text:
                    continue
                item = QListWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, {"name": text, "type": "", "color": "", "preview_base64": ""})
                self.labels.addItem(item)
        self.labels_hint.setText(f"{self.labels.count()} labels (drag to cameras, YOLO-style projects often stay <= 80)")
        self.labels_section.set_summary(f"{self.labels.count()} labels" if self.labels.count() else "Drag & drop source")
        self.filter_label_views(self.label_search.text())

    def filter_labels(self, text: str) -> None:
        needle = text.strip().lower()
        for i in range(self.labels.count()):
            item = self.labels.item(i)
            item.setHidden(bool(needle) and needle not in item.text().lower())

    def filter_label_views(self, text: str) -> None:
        needle = text.strip().lower()
        for i in range(self.labels.count()):
            item = self.labels.item(i)
            data = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(data, dict):
                haystack = " ".join(str(data.get(key, "")) for key in ("name", "type", "color")).lower()
            else:
                haystack = item.text().lower()
            item.setHidden(bool(needle) and needle not in haystack)
        self.label_gallery.set_filter(text)
        visible = [self.labels.item(i) for i in range(self.labels.count()) if not self.labels.item(i).isHidden()]
        current = self.labels.currentItem()
        if visible and (current is None or current.isHidden()):
            self.labels.setCurrentItem(visible[0])
            self._on_label_item_clicked(visible[0])

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
            suffix = f" - {', '.join(labels[:4])}" if labels else ""
            if len(labels) > 4:
                suffix += f" (+{len(labels) - 4})"
            item = QListWidgetItem(f"{port}{suffix}")
            item.setData(Qt.ItemDataRole.UserRole, port)
            item.setToolTip(f"Drop labels here to assign to {port}")
            item.setSizeHint(item.sizeHint() * 1.35)
            self.gpio_ports.addItem(item)

        if port_map:
            lines = []
            for port, labels in sorted(port_map.items()):
                preview = ", ".join(_short_label(label) for label in labels[:4])
                if len(labels) > 4:
                    preview += f" (+{len(labels) - 4})"
                lines.append(f"{port}: {preview}")
            if len(lines) > 8:
                hidden = len(lines) - 8
                lines = lines[:8] + [f"+{hidden} more ports"]
            self.gpio_preview.setText("\n".join(lines))
        else:
            self.gpio_preview.setText("Drop labels onto a GPIO port")

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
        text = "\n".join([f"Name: {name}", f"Type: {label_type or 'n/a'}", f"Color: {color or 'n/a'}"])
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
        data = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(data, dict):
            self.set_selected_label_preview(data)
            self.label_selected.emit(data)

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
            data = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(data, dict):
                selected.append(str(data.get("name", "")).strip())
            else:
                selected.append(item.text())
        if selected:
            return selected
        item = self.labels.currentItem()
        if not item:
            return []
        data = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(data, dict):
            name = str(data.get("name", "")).strip()
            return [name] if name else []
        return [item.text()]
