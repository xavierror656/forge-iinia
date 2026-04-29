"""Settings panel for .env-driven configuration."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QComboBox,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from core.env_config import read_env_file, write_env_file
from core.video_source import (
    VIDEO_SOURCE_PATH,
    InferenceSourceConfig,
    VideoSourceChoice,
    friendly_rtsp_name,
    discover_video_sources,
    load_inference_source_config,
    normalize_rtsp_url,
    probe_rtsp_url,
    save_inference_source_config,
)


class SettingsPanel(QWidget):
    env_changed = pyqtSignal(dict)
    video_source_changed = pyqtSignal(dict)

    def __init__(self, env_path: str = ".env", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._env_path = Path(env_path)
        self._video_source_config = InferenceSourceConfig()
        self._available_sources: dict[str, VideoSourceChoice] = {}
        self._rtsp_cameras: list[dict[str, object]] = []
        self._rtsp_default_camera: str = ""
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

        source_box = QGroupBox("Fuente de video")
        source_layout = QVBoxLayout(source_box)
        source_form = QFormLayout()
        self.source_mode = QComboBox()
        self.source_mode.addItem("Auto", "auto")
        self.source_mode.addItem("USB", "webcam")
        self.source_mode.addItem("CSI", "csi")
        self.source_mode.addItem("RTSP", "rtsp")
        self.local_source = QComboBox()
        self.local_source.setEditable(False)
        self.local_source.setMinimumContentsLength(24)
        self.rtsp_url = QLineEdit()
        self.rtsp_url.setPlaceholderText("rtsp://host:554/stream")
        self.rtsp_username = QLineEdit()
        self.rtsp_username.setPlaceholderText("Usuario opcional")
        self.rtsp_password = QLineEdit()
        self.rtsp_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.rtsp_password.setPlaceholderText("Contraseña opcional")
        self.source_status = QLabel("Auto detectará cámaras USB/CSI en Linux.")
        self.source_status.setWordWrap(True)
        self.detect_sources_button = QPushButton("Detectar cámaras")
        self.save_source_button = QPushButton("Guardar JSON")
        buttons = QHBoxLayout()
        buttons.addWidget(self.detect_sources_button)
        buttons.addWidget(self.save_source_button)
        buttons.addStretch(1)
        button_row = QWidget()
        button_row.setLayout(buttons)

        source_form.addRow("Modo", self.source_mode)
        source_form.addRow("Fuente local", self.local_source)
        source_form.addRow("Estado", self.source_status)
        source_form.addRow(button_row)

        rtsp_box = QGroupBox("Cámaras RTSP")
        rtsp_layout = QVBoxLayout(rtsp_box)
        rtsp_editor = QFormLayout()
        self.rtsp_name = QLineEdit()
        self.rtsp_name.setPlaceholderText("Camara frontal")
        self.rtsp_enabled = QCheckBox("Habilitada")
        self.rtsp_enabled.setChecked(True)
        rtsp_editor.addRow("Nombre", self.rtsp_name)
        rtsp_editor.addRow("RTSP URL", self.rtsp_url)
        rtsp_editor.addRow("RTSP usuario", self.rtsp_username)
        rtsp_editor.addRow("RTSP contraseña", self.rtsp_password)
        rtsp_editor.addRow("Estado", self.rtsp_enabled)

        self.rtsp_list = QListWidget()
        self.rtsp_list.currentItemChanged.connect(self._load_selected_rtsp_camera)
        self.rtsp_summary = QLabel("Sin cámaras RTSP registradas.")
        self.rtsp_summary.setWordWrap(True)
        self.rtsp_status = QLabel("Prueba una cámara RTSP para verificar conexión.")
        self.rtsp_status.setWordWrap(True)
        self.rtsp_status.setStyleSheet("color:#9fb2c8;")
        rtsp_buttons = QHBoxLayout()
        self.new_rtsp_button = QPushButton("Nueva")
        self.add_rtsp_button = QPushButton("Agregar/Actualizar")
        self.test_rtsp_button = QPushButton("Probar conexión")
        self.remove_rtsp_button = QPushButton("Eliminar")
        self.default_rtsp_button = QPushButton("Usar como inicio")
        rtsp_buttons.addWidget(self.new_rtsp_button)
        rtsp_buttons.addWidget(self.add_rtsp_button)
        rtsp_buttons.addWidget(self.test_rtsp_button)
        rtsp_buttons.addWidget(self.remove_rtsp_button)
        rtsp_buttons.addWidget(self.default_rtsp_button)
        rtsp_buttons.addStretch(1)

        rtsp_layout.addLayout(rtsp_editor)
        rtsp_layout.addWidget(self.rtsp_list)
        rtsp_layout.addWidget(self.rtsp_summary)
        rtsp_layout.addWidget(self.rtsp_status)
        rtsp_buttons_widget = QWidget()
        rtsp_buttons_widget.setLayout(rtsp_buttons)
        rtsp_layout.addWidget(rtsp_buttons_widget)

        source_layout.addLayout(source_form)
        source_layout.addWidget(rtsp_box)

        buttons = QHBoxLayout()
        self.reload_button = QPushButton("Cargar .env")
        self.save_button = QPushButton("Guardar .env")
        buttons.addWidget(self.reload_button)
        buttons.addWidget(self.save_button)

        self.reload_button.clicked.connect(self.load_env)
        self.save_button.clicked.connect(self.save_env)
        self.detect_sources_button.clicked.connect(self.refresh_video_sources)
        self.save_source_button.clicked.connect(self.save_video_source)
        self.new_rtsp_button.clicked.connect(self._new_rtsp_camera)
        self.add_rtsp_button.clicked.connect(self._add_or_update_rtsp_camera)
        self.test_rtsp_button.clicked.connect(self._test_rtsp_camera)
        self.remove_rtsp_button.clicked.connect(self._remove_rtsp_camera)
        self.default_rtsp_button.clicked.connect(self._mark_selected_rtsp_default)
        self.source_mode.currentIndexChanged.connect(lambda *_: self._sync_video_source_fields())
        self.rtsp_url.textChanged.connect(lambda *_: self._sync_video_source_fields())

        root.addWidget(box)
        root.addWidget(source_box)
        root.addLayout(buttons)

        self._sync_video_source_fields()

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
        self.load_video_source()

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

    def _rtsp_camera_from_fields(self) -> dict[str, object] | None:
        url = self.rtsp_url.text().strip()
        normalized_url, error = normalize_rtsp_url(url)
        if error:
            self._set_rtsp_status(error, ok=False)
            return None
        name = self.rtsp_name.text().strip() or friendly_rtsp_name(normalized_url) or f"RTSP {len(self._rtsp_cameras) + 1}"
        return {
            "name": name,
            "url": normalized_url,
            "username": self.rtsp_username.text().strip(),
            "password": self.rtsp_password.text().strip(),
            "enabled": self.rtsp_enabled.isChecked(),
        }

    def _set_rtsp_status(self, text: str, *, ok: bool | None = None) -> None:
        color = "#9fb2c8"
        if ok is True:
            color = "#62d2a2"
        elif ok is False:
            color = "#e66b6b"
        self.rtsp_status.setStyleSheet(f"color:{color};")
        self.rtsp_status.setText(text)

    def _refresh_rtsp_list(self, *, select_name: str | None = None) -> None:
        self.rtsp_list.blockSignals(True)
        self.rtsp_list.clear()
        default_name = self._rtsp_default_camera.strip()
        for camera in self._rtsp_cameras:
            name = str(camera.get("name", "")).strip() or "RTSP"
            url = str(camera.get("url", "")).strip()
            enabled = bool(camera.get("enabled", True))
            label = name
            if name == default_name:
                label += " (default)"
            if not enabled:
                label += " [off]"
            if url:
                label += f" · {url}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, dict(camera))
            self.rtsp_list.addItem(item)

        target_name = select_name or default_name
        if not target_name and self.rtsp_list.count():
            target_name = str(self.rtsp_list.item(0).data(Qt.ItemDataRole.UserRole).get("name", ""))

        if target_name:
            for index in range(self.rtsp_list.count()):
                item = self.rtsp_list.item(index)
                data = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(data, dict) and str(data.get("name", "")).strip() == target_name:
                    self.rtsp_list.setCurrentRow(index)
                    break
        elif self.rtsp_list.count() == 0:
            self._load_selected_rtsp_camera(None, None)

        self.rtsp_list.blockSignals(False)
        if self.rtsp_list.currentItem() is not None:
            self._load_selected_rtsp_camera(self.rtsp_list.currentItem(), None)
        self._update_rtsp_summary()

    def _update_rtsp_summary(self) -> None:
        total = len(self._rtsp_cameras)
        enabled = sum(1 for camera in self._rtsp_cameras if bool(camera.get("enabled", True)))
        default_name = self._rtsp_default_camera.strip() or "ninguna"
        if total:
            self.rtsp_summary.setText(f"{enabled} de {total} cámaras habilitadas · inicio: {default_name}")
        else:
            self.rtsp_summary.setText("Sin cámaras RTSP registradas.")

    def _load_selected_rtsp_camera(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is None:
            self.rtsp_name.clear()
            self.rtsp_url.clear()
            self.rtsp_username.clear()
            self.rtsp_password.clear()
            self.rtsp_enabled.setChecked(True)
            return
        data = current.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict):
            return
        self.rtsp_name.setText(str(data.get("name", "")))
        self.rtsp_url.setText(str(data.get("url", "")))
        self.rtsp_username.setText(str(data.get("username", "")))
        self.rtsp_password.setText(str(data.get("password", "")))
        self.rtsp_enabled.setChecked(bool(data.get("enabled", True)))

    def _new_rtsp_camera(self) -> None:
        self.rtsp_list.blockSignals(True)
        self.rtsp_list.clearSelection()
        self.rtsp_list.setCurrentRow(-1)
        self.rtsp_list.blockSignals(False)
        self._load_selected_rtsp_camera(None, None)

    def _test_rtsp_camera(self) -> None:
        normalized_url, error = normalize_rtsp_url(self.rtsp_url.text().strip())
        if error:
            self._set_rtsp_status(error, ok=False)
            return

        self._set_rtsp_status("Probando conexión RTSP...", ok=None)

        ok, message = probe_rtsp_url(
            normalized_url,
            self.rtsp_username.text().strip(),
            self.rtsp_password.text().strip(),
        )
        self._set_rtsp_status(message, ok=ok)
        if ok and not self.rtsp_name.text().strip():
            self.rtsp_name.setText(friendly_rtsp_name(normalized_url))

    def _add_or_update_rtsp_camera(self) -> None:
        camera = self._rtsp_camera_from_fields()
        if camera is None:
            self.source_status.setText("Completa la URL RTSP para agregar la cámara.")
            return

        name = str(camera.get("name", "")).strip()
        selected_index = self.rtsp_list.currentRow()
        existing_index = next(
            (i for i, item in enumerate(self._rtsp_cameras) if str(item.get("name", "")).strip() == name),
            None,
        )
        index = selected_index if selected_index >= 0 else existing_index
        if index is None or index < 0:
            self._rtsp_cameras.append(camera)
            index = len(self._rtsp_cameras) - 1
        else:
            if existing_index is not None and existing_index != index:
                self._rtsp_cameras.pop(existing_index)
                if existing_index < index:
                    index -= 1
            if index < len(self._rtsp_cameras):
                self._rtsp_cameras[index] = camera
            else:
                self._rtsp_cameras.append(camera)
                index = len(self._rtsp_cameras) - 1

        if not self._rtsp_default_camera.strip():
            self._rtsp_default_camera = name
        self._ensure_valid_rtsp_default(preferred_name=name)
        self._refresh_rtsp_list(select_name=name)
        self.save_video_source()
        self._set_rtsp_status(f"Guardada: {name}", ok=True)

    def _remove_rtsp_camera(self) -> None:
        index = self.rtsp_list.currentRow()
        if index < 0 or index >= len(self._rtsp_cameras):
            return
        removed = self._rtsp_cameras.pop(index)
        if str(removed.get("name", "")).strip() == self._rtsp_default_camera.strip():
            self._rtsp_default_camera = str(self._rtsp_cameras[0].get("name", "")).strip() if self._rtsp_cameras else ""
        self._ensure_valid_rtsp_default()
        self._refresh_rtsp_list()
        self.save_video_source()
        self._set_rtsp_status("Cámara RTSP eliminada.", ok=True)

    def _mark_selected_rtsp_default(self) -> None:
        index = self.rtsp_list.currentRow()
        if index < 0 or index >= len(self._rtsp_cameras):
            return
        name = str(self._rtsp_cameras[index].get("name", "")).strip()
        if not name:
            return
        self._rtsp_default_camera = name
        self._refresh_rtsp_list(select_name=name)
        self.save_video_source()
        self._set_rtsp_status(f"Inicio RTSP: {name}", ok=True)

    def _ensure_valid_rtsp_default(self, preferred_name: str | None = None) -> None:
        known_names = [str(camera.get("name", "")).strip() for camera in self._rtsp_cameras if str(camera.get("name", "")).strip()]
        if not known_names:
            self._rtsp_default_camera = ""
            return
        if self._rtsp_default_camera.strip() not in known_names:
            preferred = str(preferred_name or "").strip()
            self._rtsp_default_camera = preferred if preferred and preferred in known_names else known_names[0]

    def _sync_video_source_fields(self) -> None:
        mode = str(self.source_mode.currentData() or "auto").strip().lower()
        local_enabled = mode in {"auto", "webcam", "csi"}
        self.local_source.setEnabled(local_enabled)
        self.detect_sources_button.setEnabled(local_enabled)
        self.test_rtsp_button.setEnabled(bool(self.rtsp_url.text().strip()))

    def _populate_local_sources(self, sources: list[VideoSourceChoice], selected_source: str = "") -> None:
        self._available_sources = {choice.source: choice for choice in sources if choice.source}
        self.local_source.blockSignals(True)
        self.local_source.clear()
        for choice in sources:
            label = choice.label
            if not choice.available:
                label = f"{label} (sin señal)"
            self.local_source.addItem(label, choice.source)
        if selected_source and self.local_source.findData(selected_source) < 0:
            fallback_choice = VideoSourceChoice(kind="manual", label=selected_source, source=selected_source, backend="", available=False)
            self.local_source.addItem(fallback_choice.label, selected_source)
            self._available_sources[selected_source] = fallback_choice
        if self.local_source.count() == 0:
            self.local_source.addItem("Sin cámaras detectadas", "")
        if selected_source:
            index = self.local_source.findData(selected_source)
            if index >= 0:
                self.local_source.setCurrentIndex(index)
        elif self.local_source.count() > 0:
            self.local_source.setCurrentIndex(0)
        self.local_source.blockSignals(False)

    def refresh_video_sources(self) -> None:
        sources = discover_video_sources()
        selected_source = self._selected_local_source()
        self._video_source_config.discovered_sources = [choice.as_dict() for choice in sources]
        self._populate_local_sources(sources, selected_source=selected_source)
        if sources:
            active = self._available_sources.get(self._selected_local_source())
            if active is None and sources:
                active = sources[0]
            self.source_status.setText(f"Detectadas {len(sources)} cámaras locales.")
        else:
            self.source_status.setText("No se detectaron cámaras locales. RTSP sigue disponible.")

    def load_video_source(self) -> None:
        self._video_source_config = load_inference_source_config(VIDEO_SOURCE_PATH)
        cfg = self._video_source_config

        mode_index = self.source_mode.findData(cfg.mode)
        if mode_index >= 0:
            self.source_mode.setCurrentIndex(mode_index)

        self.rtsp_url.setText(cfg.rtsp_url)
        self.rtsp_username.setText(cfg.rtsp_username)
        self.rtsp_password.setText(cfg.rtsp_password)

        self._rtsp_cameras = [dict(camera) for camera in cfg.rtsp_cameras if isinstance(camera, dict)]
        if not self._rtsp_cameras and cfg.rtsp_url.strip():
            self._rtsp_cameras = [
                {
                    "name": cfg.default_rtsp_camera.strip() or "RTSP 1",
                    "url": cfg.rtsp_url,
                    "username": cfg.rtsp_username,
                    "password": cfg.rtsp_password,
                    "enabled": True,
                }
            ]
        self._rtsp_default_camera = cfg.default_rtsp_camera.strip() or (
            str(self._rtsp_cameras[0].get("name", "")).strip() if self._rtsp_cameras else ""
        )
        if self._rtsp_default_camera and self._rtsp_cameras:
            known_names = {str(camera.get("name", "")).strip() for camera in self._rtsp_cameras}
            if self._rtsp_default_camera not in known_names:
                self._rtsp_default_camera = str(self._rtsp_cameras[0].get("name", "")).strip()
        self._refresh_rtsp_list(select_name=self._rtsp_default_camera or None)
        if self._rtsp_cameras:
            self._set_rtsp_status(f"{len(self._rtsp_cameras)} cámaras RTSP cargadas.", ok=True)
        else:
            self._set_rtsp_status("Sin cámaras RTSP registradas.", ok=None)

        sources = [VideoSourceChoice(**item) for item in cfg.discovered_sources if isinstance(item, dict)]
        selected = cfg.camera_source or (
            cfg.last_resolved_source if cfg.mode != "rtsp" and cfg.last_resolved_kind != "rtsp" else ""
        )
        if sources:
            self._populate_local_sources(sources, selected_source=selected)
        elif selected:
            self._populate_local_sources([VideoSourceChoice(kind=cfg.mode or "auto", label=cfg.camera_label or selected, source=selected, backend=cfg.camera_backend or "")], selected_source=selected)
        else:
            self._populate_local_sources([], selected_source="")

        if cfg.last_resolved_source:
            self.source_status.setText(
                f"Fuente activa: {cfg.last_resolved_label or cfg.last_resolved_source}"
            )
        else:
            self.source_status.setText("Auto detectará cámaras USB/CSI en Linux.")

        self._sync_video_source_fields()

    def _selected_local_source(self) -> str:
        source = self.local_source.currentData()
        if isinstance(source, str):
            return source.strip()
        return str(self.local_source.currentText()).strip()

    def save_video_source(self) -> None:
        mode = str(self.source_mode.currentData() or "auto").strip().lower() or "auto"
        selected_source = self._selected_local_source()
        choice = self._available_sources.get(selected_source)
        default_camera = self._default_rtsp_for_save()
        rtsp_cameras = [dict(camera) for camera in self._rtsp_cameras if str(camera.get("url", "")).strip()]
        if not rtsp_cameras and default_camera is not None:
            rtsp_cameras = [dict(default_camera)]
        if mode == "rtsp" and not rtsp_cameras:
            self._set_rtsp_status("Agrega una cámara RTSP válida antes de guardar.", ok=False)
            return
        config = InferenceSourceConfig(
            version=1,
            mode=mode,
            rtsp_url=default_camera.get("url", "") if default_camera else self.rtsp_url.text().strip(),
            rtsp_username=default_camera.get("username", "") if default_camera else self.rtsp_username.text().strip(),
            rtsp_password=default_camera.get("password", "") if default_camera else self.rtsp_password.text().strip(),
            default_rtsp_camera=(self._rtsp_default_camera.strip() or str(default_camera.get("name", "")).strip()) if default_camera else self._rtsp_default_camera.strip(),
            rtsp_cameras=rtsp_cameras,
            camera_source=selected_source,
            camera_label=choice.label if choice else selected_source,
            camera_backend=choice.backend if choice else "",
            last_resolved_source=self._video_source_config.last_resolved_source,
            last_resolved_label=self._video_source_config.last_resolved_label,
            last_resolved_kind=self._video_source_config.last_resolved_kind,
            last_resolved_backend=self._video_source_config.last_resolved_backend,
            discovered_sources=[choice.as_dict() for choice in self._available_sources.values()],
        )
        save_inference_source_config(VIDEO_SOURCE_PATH, config)
        self._video_source_config = config
        self.source_status.setText(f"Guardado en {VIDEO_SOURCE_PATH}")
        self.video_source_changed.emit(config.to_mapping())

    def _default_rtsp_for_save(self) -> dict[str, object] | None:
        if self._rtsp_default_camera.strip():
            for camera in self._rtsp_cameras:
                if str(camera.get("name", "")).strip() == self._rtsp_default_camera.strip():
                    return camera
        for camera in self._rtsp_cameras:
            if bool(camera.get("enabled", True)):
                return camera
        if self._rtsp_cameras:
            return self._rtsp_cameras[0]
        return self._rtsp_camera_from_fields()


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
        self.panel.save_video_source()
        self.accept()
