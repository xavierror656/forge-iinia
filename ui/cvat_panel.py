"""CVAT control panel widget."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class CvatPanel(QWidget):
    connect_requested = pyqtSignal(str, str, str)
    refresh_requested = pyqtSignal()
    capture_requested = pyqtSignal()
    export_requested = pyqtSignal(int, str, str)
    upload_requested = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def set_values(
        self,
        *,
        base_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        token: str | None = None,
    ) -> None:
        if base_url is not None:
            self.base_url.setText(base_url)
        if username is not None:
            self.username.setText(username)
        if password is not None:
            self.password.setText(password)
        if token is not None:
            self.token.setText(token)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        conn_box = QGroupBox("CVAT")
        form = QFormLayout(conn_box)
        self.base_url = QLineEdit("https://app.cvat.ai")
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.token = QLineEdit()
        self.token.setPlaceholderText("Token opcional")
        self.project_id = QLineEdit()
        self.project_id.setPlaceholderText("Project ID")
        self.task_id = QLineEdit()
        self.task_id.setPlaceholderText("Task ID")
        self.export_format = QComboBox()
        self.export_format.addItems(["CVAT for images 1.1", "COCO 1.0", "YOLO 1.1"])
        self.capture_dir = QLineEdit(str(Path("captures").resolve()))

        form.addRow("Base URL", self.base_url)
        form.addRow("Username", self.username)
        form.addRow("Password", self.password)
        form.addRow("Token", self.token)
        form.addRow("Project ID", self.project_id)
        form.addRow("Task ID", self.task_id)
        form.addRow("Export format", self.export_format)
        form.addRow("Capture dir", self.capture_dir)

        buttons = QHBoxLayout()
        self.connect_button = QPushButton("Conectar")
        self.refresh_button = QPushButton("Refrescar")
        self.capture_button = QPushButton("Tomar foto")
        self.upload_button = QPushButton("Subir fotos")
        self.export_button = QPushButton("Descargar modelo/export")
        buttons.addWidget(self.connect_button)
        buttons.addWidget(self.refresh_button)
        buttons.addWidget(self.capture_button)
        buttons.addWidget(self.upload_button)
        buttons.addWidget(self.export_button)

        self.projects = QListWidget()
        self.jobs = QListWidget()
        self.status = QTextEdit()
        self.status.setReadOnly(True)
        self.status.setMaximumHeight(90)
        self.status.setPlaceholderText("Estado CVAT...")

        root.addWidget(conn_box)
        root.addLayout(buttons)
        root.addWidget(QLabel("Projects"))
        root.addWidget(self.projects)
        root.addWidget(QLabel("Jobs"))
        root.addWidget(self.jobs)
        root.addWidget(QLabel("Estado"))
        root.addWidget(self.status)

    def set_status(self, text: str) -> None:
        self.status.setPlainText(text)
