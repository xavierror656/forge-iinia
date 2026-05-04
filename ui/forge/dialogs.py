"""Dialogs used by the Forge tab.

Pulled out of ``ui/forge_panel.py`` so that file can shrink toward a single
responsibility (the panel itself).
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ui.icons import icon as _icon

from ui.icons import icon as _icon


class ForgeConfigDialog(QDialog):
    def __init__(
        self,
        *,
        base_url: str = "",
        username: str = "",
        password: str = "",
        token: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Configuración Forge")
        self.setWindowIcon(_icon("gear", size=24))
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
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        if (ok_button := buttons.button(QDialogButtonBox.StandardButton.Ok)) is not None:
            ok_button.setIcon(_icon("check-lg", size=16))
        if (cancel_button := buttons.button(QDialogButtonBox.StandardButton.Cancel)) is not None:
            cancel_button.setIcon(_icon("x-lg", size=16))
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
    def __init__(
        self,
        *,
        line_options: list[tuple[int, str]] | None = None,
        selected_line_id: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Nueva cámara")
        self.setWindowIcon(_icon("camera-video", size=24))
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.number = QSpinBox()
        self.number.setRange(0, 2147483647)
        self.number.setValue(1)
        self.device_ip = QLineEdit()
        self.device_ip.setPlaceholderText("192.168.1.10")
        self.protocol = QComboBox()
        self.protocol.setEditable(True)
        self.protocol.addItem(_icon("camera-video", size=16), "rtsp")
        self.protocol.addItem(_icon("globe", size=16), "http")
        self.protocol.addItem(_icon("ethernet", size=16), "tcp")
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
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        if (ok_button := buttons.button(QDialogButtonBox.StandardButton.Ok)) is not None:
            ok_button.setIcon(_icon("check-lg", size=16))
        if (cancel_button := buttons.button(QDialogButtonBox.StandardButton.Cancel)) is not None:
            cancel_button.setIcon(_icon("x-lg", size=16))
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
