"""Settings panel for .env-driven configuration."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QComboBox,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.env_config import read_env_file, write_env_file


class SettingsPanel(QWidget):
    env_changed = pyqtSignal(dict)

    def __init__(self, env_path: str = ".env", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._env_path = Path(env_path)
        self._build_ui()
        self.load_env()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        box = QGroupBox("Configuraciones")
        form = QFormLayout(box)

        self.env_file = QLineEdit(str(self._env_path.resolve()))
        self.forge_url = QLineEdit()
        self.forge_user = QLineEdit()
        self.forge_password = QLineEdit()
        self.forge_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.forge_token = QLineEdit()
        self.cvat_url = QLineEdit()
        self.cvat_user = QLineEdit()
        self.cvat_password = QLineEdit()
        self.cvat_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.cvat_token = QLineEdit()
        self.model_dir = QLineEdit("models")
        self.capture_dir = QLineEdit("captures")
        self.simulation_mode = QLineEdit("true")
        self.ui_theme = QComboBox()
        self.ui_theme.addItems(["dark", "light"])

        form.addRow(".env", self.env_file)
        form.addRow("Forge URL", self.forge_url)
        form.addRow("Forge User", self.forge_user)
        form.addRow("Forge Password", self.forge_password)
        form.addRow("Forge Token", self.forge_token)
        form.addRow("CVAT URL", self.cvat_url)
        form.addRow("CVAT User", self.cvat_user)
        form.addRow("CVAT Password", self.cvat_password)
        form.addRow("CVAT Token", self.cvat_token)
        form.addRow("Model dir", self.model_dir)
        form.addRow("Capture dir", self.capture_dir)
        form.addRow("Simulation", self.simulation_mode)
        form.addRow("UI theme", self.ui_theme)

        buttons = QHBoxLayout()
        self.reload_button = QPushButton("Cargar .env")
        self.save_button = QPushButton("Guardar .env")
        buttons.addWidget(self.reload_button)
        buttons.addWidget(self.save_button)

        self.reload_button.clicked.connect(self.load_env)
        self.save_button.clicked.connect(self.save_env)

        root.addWidget(box)
        root.addLayout(buttons)

    def load_env(self) -> None:
        values = read_env_file(Path(self.env_file.text().strip() or ".env"))
        self.forge_url.setText(values.get("FORGE_URL", ""))
        self.forge_user.setText(values.get("FORGE_USERNAME", ""))
        self.forge_password.setText(values.get("FORGE_PASSWORD", ""))
        self.forge_token.setText(values.get("FORGE_TOKEN", ""))
        self.cvat_url.setText(values.get("CVAT_URL", "https://app.cvat.ai"))
        self.cvat_user.setText(values.get("CVAT_USERNAME", ""))
        self.cvat_password.setText(values.get("CVAT_PASSWORD", ""))
        self.cvat_token.setText(values.get("CVAT_TOKEN", ""))
        self.model_dir.setText(values.get("MODEL_DIR", "models"))
        self.capture_dir.setText(values.get("CAPTURE_DIR", "captures"))
        self.simulation_mode.setText(values.get("SIMULATION_MODE", "true"))
        theme = values.get("UI_THEME", "dark").strip().lower()
        self.ui_theme.setCurrentText("light" if theme == "light" else "dark")

    def save_env(self) -> None:
        path = Path(self.env_file.text().strip() or ".env")
        values = {
            "FORGE_URL": self.forge_url.text().strip(),
            "FORGE_USERNAME": self.forge_user.text().strip(),
            "FORGE_PASSWORD": self.forge_password.text().strip(),
            "FORGE_TOKEN": self.forge_token.text().strip(),
            "CVAT_URL": self.cvat_url.text().strip(),
            "CVAT_USERNAME": self.cvat_user.text().strip(),
            "CVAT_PASSWORD": self.cvat_password.text().strip(),
            "CVAT_TOKEN": self.cvat_token.text().strip(),
            "MODEL_DIR": self.model_dir.text().strip(),
            "CAPTURE_DIR": self.capture_dir.text().strip(),
            "SIMULATION_MODE": self.simulation_mode.text().strip(),
            "UI_THEME": self.ui_theme.currentText().strip(),
        }
        write_env_file(path, values)
        self.env_changed.emit(values)


class SettingsDialog(QDialog):
    def __init__(self, env_path: str = ".env", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Configuración")
        self.resize(900, 700)
        layout = QVBoxLayout(self)
        self.panel = SettingsPanel(env_path=env_path, parent=self)
        layout.addWidget(self.panel)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close | QDialogButtonBox.StandardButton.Save)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self._save_and_close)
        layout.addWidget(buttons)

    def _save_and_close(self) -> None:
        self.panel.save_env()
        self.accept()
