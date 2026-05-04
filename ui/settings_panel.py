"""Settings panel for .env-driven configuration."""

from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QComboBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
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
from ui.icons import icon
from ui.theme import settings_panel_stylesheet


class SettingsPanel(QWidget):
    env_changed = pyqtSignal(dict)
    video_source_changed = pyqtSignal(dict)
    forge_test_requested = pyqtSignal(dict)

    def __init__(
        self,
        env_path: str = ".env",
        parent: QWidget | None = None,
        *,
        ui_profile: str = "desktop",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("SettingsPanel")
        self._env_path = Path(env_path)
        self._ui_profile = ui_profile
        self._video_source_config = InferenceSourceConfig()
        self._available_sources: dict[str, VideoSourceChoice] = {}
        self._rtsp_cameras: list[dict[str, object]] = []
        self._rtsp_default_camera: str = ""
        self._rtsp_card_widgets: list[dict[str, QWidget]] = []
        self._local_cameras: list[dict[str, object]] = []
        self._local_card_widgets: list[dict[str, QWidget]] = []
        self._local_selected_index: int | None = None
        self._build_ui()
        self.load_env()
        self.set_theme("dark")

    def set_theme(self, theme: str) -> None:
        self.setStyleSheet(settings_panel_stylesheet(theme))
        self._apply_icons()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(16)

        box = QGroupBox("Configuraciones .env")
        env_layout = QVBoxLayout(box)
        env_layout.setSpacing(12)

        self.env_file = QLineEdit(str(self._env_path.resolve()))
        self.env_file.setStyleSheet("font-size: 11px; color: #6c7680;")
        env_file_row = QHBoxLayout()
        env_file_row.setSpacing(8)
        env_file_row.addWidget(self.env_file, 1)
        self.reload_button = QPushButton("Cargar .env")
        self.save_button = QPushButton("Guardar .env")
        self.import_env_button = QPushButton("Importar .env")
        self.test_forge_button = QPushButton("Probar Forge")
        self.test_forge_button.setToolTip("Verifica las credenciales con un ping al backend")
        self.test_forge_button.clicked.connect(self._on_test_forge_clicked)
        env_file_row.addWidget(self.reload_button)
        env_file_row.addWidget(self.save_button)
        env_file_row.addWidget(self.import_env_button)
        env_file_row.addWidget(self.test_forge_button)
        env_layout.addLayout(env_file_row)

        self.forge_test_status = QLabel("")
        self.forge_test_status.setStyleSheet("color:#8b95a1; font-size:11px;")
        env_layout.addWidget(self.forge_test_status)

        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.forge_url = QLineEdit()
        self.forge_user = QLineEdit()
        self.forge_password = QLineEdit()
        self.forge_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.forge_token = QLineEdit()
        self.forge_model_url = QLineEdit()
        self.forge_model_url.setPlaceholderText("URL directa opcional al .pt")
        self.forge_model_asset_uuid = QLineEdit()
        self.forge_model_asset_uuid.setPlaceholderText("UUID de /api/assets/{uuid}")
        self.model_dir = QLineEdit("models")
        self.capture_dir = QLineEdit("captures")
        self.simulation_mode = QLineEdit("true")
        self.ui_theme = QComboBox()
        self.ui_theme.addItem(icon("moon", size=16), "dark")
        self.ui_theme.addItem(icon("sun", size=16), "light")

        form.addRow("Forge URL", self.forge_url)
        form.addRow("Forge User", self.forge_user)
        form.addRow("Forge Password", self.forge_password)
        form.addRow("Forge Token", self.forge_token)
        form.addRow("Forge model URL", self.forge_model_url)
        form.addRow("Forge asset UUID", self.forge_model_asset_uuid)
        form.addRow("Model dir", self.model_dir)
        form.addRow("Capture dir", self.capture_dir)
        form.addRow("Simulation", self.simulation_mode)
        form.addRow("UI theme", self.ui_theme)

        env_layout.addLayout(form)

        output_box = QGroupBox("Salidas de inferencia")
        output_layout = QVBoxLayout(output_box)
        output_layout.setSpacing(12)

        output_hint = QLabel(
            "Publica cada frame inferido a red/industria. GPIO se configura desde Forge arrastrando labels a puertos."
        )
        output_hint.setWordWrap(True)
        output_layout.addWidget(output_hint)

        output_form = QFormLayout()
        output_form.setSpacing(8)
        output_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.output_mqtt_enabled = QLineEdit("false")
        self.output_mqtt_host = QLineEdit()
        self.output_mqtt_port = QLineEdit("1883")
        self.output_mqtt_topic = QLineEdit("edgevision/inference")
        self.output_http_enabled = QLineEdit("false")
        self.output_http_url = QLineEdit()
        self.output_websocket_enabled = QLineEdit("false")
        self.output_websocket_url = QLineEdit()
        self.output_tcp_enabled = QLineEdit("false")
        self.output_tcp_host = QLineEdit()
        self.output_tcp_port = QLineEdit("9000")
        self.output_udp_enabled = QLineEdit("false")
        self.output_udp_host = QLineEdit()
        self.output_udp_port = QLineEdit("9001")
        self.output_modbus_enabled = QLineEdit("false")
        self.output_modbus_host = QLineEdit()
        self.output_modbus_port = QLineEdit("502")
        self.output_modbus_unit_id = QLineEdit("1")
        self.output_modbus_count_register = QLineEdit("0")
        self.output_modbus_active_coil = QLineEdit("0")

        output_form.addRow("MQTT enabled", self.output_mqtt_enabled)
        output_form.addRow("MQTT host", self.output_mqtt_host)
        output_form.addRow("MQTT port", self.output_mqtt_port)
        output_form.addRow("MQTT topic", self.output_mqtt_topic)
        output_form.addRow("HTTP enabled", self.output_http_enabled)
        output_form.addRow("HTTP URL", self.output_http_url)
        output_form.addRow("WebSocket enabled", self.output_websocket_enabled)
        output_form.addRow("WebSocket URL", self.output_websocket_url)
        output_form.addRow("TCP enabled", self.output_tcp_enabled)
        output_form.addRow("TCP host", self.output_tcp_host)
        output_form.addRow("TCP port", self.output_tcp_port)
        output_form.addRow("UDP enabled", self.output_udp_enabled)
        output_form.addRow("UDP host", self.output_udp_host)
        output_form.addRow("UDP port", self.output_udp_port)
        output_form.addRow("Modbus enabled", self.output_modbus_enabled)
        output_form.addRow("Modbus host", self.output_modbus_host)
        output_form.addRow("Modbus port", self.output_modbus_port)
        output_form.addRow("Modbus unit", self.output_modbus_unit_id)
        output_form.addRow("Modbus count register", self.output_modbus_count_register)
        output_form.addRow("Modbus active coil", self.output_modbus_active_coil)
        output_layout.addLayout(output_form)

        source_box = QGroupBox("Fuente de video")
        source_layout = QVBoxLayout(source_box)
        source_layout.setSpacing(12)

        source_form = QFormLayout()
        source_form.setSpacing(8)
        source_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.source_mode = QComboBox()
        self.source_mode.addItem(icon("activity", size=16), "Auto", "auto")
        self.source_mode.addItem(icon("camera-video", size=16), "USB", "webcam")
        self.source_mode.addItem(icon("diagram-3", size=16), "CSI", "csi")
        self.source_mode.addItem(icon("broadcast", size=16), "RTSP", "rtsp")
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
        self.source_status_icon = QLabel()
        self.source_status_icon.setFixedSize(16, 16)
        self.source_status_icon.setPixmap(icon("info-circle", size=16, color="info").pixmap(16, 16))
        self.source_status_row = QWidget()
        source_status_layout = QHBoxLayout(self.source_status_row)
        source_status_layout.setContentsMargins(0, 0, 0, 0)
        source_status_layout.setSpacing(6)
        source_status_layout.addWidget(self.source_status_icon)
        source_status_layout.addWidget(self.source_status, 1)
        self.detect_sources_button = QPushButton("Detectar")
        self.save_source_button = QPushButton("Guardar JSON")
        self.import_source_button = QPushButton("Importar JSON")
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addWidget(self.detect_sources_button)
        buttons.addWidget(self.save_source_button)
        buttons.addWidget(self.import_source_button)
        buttons.addStretch(1)

        source_form.addRow("Modo", self.source_mode)
        source_form.addRow("Fuente local", self.local_source)
        source_form.addRow("Estado", self.source_status_row)
        source_form.addRow("", buttons)

        self.rtsp_box = QGroupBox("Cámaras RTSP")
        rtsp_box = self.rtsp_box
        rtsp_layout = QVBoxLayout(rtsp_box)
        rtsp_layout.setSpacing(12)

        rtsp_editor = QFormLayout()
        rtsp_editor.setSpacing(8)
        rtsp_editor.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
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
        self.rtsp_list.setVisible(False)

        self.rtsp_cards_container = QVBoxLayout()
        self.rtsp_cards_container.setSpacing(8)
        self.rtsp_cards_container.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.rtsp_cards_widget = QWidget()
        self.rtsp_cards_widget.setLayout(self.rtsp_cards_container)

        self.rtsp_scroll = QScrollArea()
        self.rtsp_scroll.setWidgetResizable(True)
        self.rtsp_scroll.setWidget(self.rtsp_cards_widget)
        self.rtsp_scroll.setMinimumHeight(180)
        self.rtsp_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.rtsp_summary = QLabel("Sin cámaras RTSP registradas.")
        self.rtsp_summary.setWordWrap(True)
        self.rtsp_summary_icon = QLabel()
        self.rtsp_summary_icon.setFixedSize(16, 16)
        self.rtsp_summary_icon.setPixmap(icon("broadcast", size=16, color="info").pixmap(16, 16))
        self.rtsp_summary_row = QWidget()
        rtsp_summary_layout = QHBoxLayout(self.rtsp_summary_row)
        rtsp_summary_layout.setContentsMargins(0, 0, 0, 0)
        rtsp_summary_layout.setSpacing(6)
        rtsp_summary_layout.addWidget(self.rtsp_summary_icon)
        rtsp_summary_layout.addWidget(self.rtsp_summary, 1)
        self.rtsp_status = QLabel("Prueba una cámara RTSP para verificar conexión.")
        self.rtsp_status.setWordWrap(True)
        self.rtsp_status.setObjectName("")
        self.rtsp_status_icon = QLabel()
        self.rtsp_status_icon.setFixedSize(16, 16)
        self.rtsp_status_icon.setPixmap(icon("info-circle", size=16, color="info").pixmap(16, 16))
        self.rtsp_status_row = QWidget()
        rtsp_status_layout = QHBoxLayout(self.rtsp_status_row)
        rtsp_status_layout.setContentsMargins(0, 0, 0, 0)
        rtsp_status_layout.setSpacing(6)
        rtsp_status_layout.addWidget(self.rtsp_status_icon)
        rtsp_status_layout.addWidget(self.rtsp_status, 1)

        rtsp_buttons = QHBoxLayout()
        rtsp_buttons.setSpacing(8)
        self.new_rtsp_button = QPushButton("Nueva")
        self.add_rtsp_button = QPushButton("Agregar")
        self.test_rtsp_button = QPushButton("Probar")
        self.remove_rtsp_button = QPushButton("Eliminar")
        self.default_rtsp_button = QPushButton("Default")
        rtsp_buttons.addWidget(self.new_rtsp_button)
        rtsp_buttons.addWidget(self.add_rtsp_button)
        rtsp_buttons.addWidget(self.test_rtsp_button)
        rtsp_buttons.addWidget(self.remove_rtsp_button)
        rtsp_buttons.addWidget(self.default_rtsp_button)
        rtsp_buttons.addStretch(1)

        rtsp_layout.addLayout(rtsp_editor)
        rtsp_layout.addWidget(self.rtsp_list)
        rtsp_layout.addWidget(self.rtsp_scroll)
        rtsp_layout.addWidget(self.rtsp_summary_row)
        rtsp_layout.addWidget(self.rtsp_status_row)
        rtsp_buttons_widget = QWidget()
        rtsp_buttons_widget.setLayout(rtsp_buttons)
        rtsp_layout.addWidget(rtsp_buttons_widget)

        self.local_box = QGroupBox("Cámaras locales (USB/CSI)")
        local_box = self.local_box
        local_layout = QVBoxLayout(local_box)
        local_layout.setSpacing(12)

        local_editor = QFormLayout()
        local_editor.setSpacing(8)
        local_editor.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.local_name = QLineEdit()
        self.local_name.setPlaceholderText("Cámara frontal")
        self.local_kind = QComboBox()
        self.local_kind.addItem(icon("camera-video", size=16), "USB", "webcam")
        self.local_kind.addItem(icon("diagram-3", size=16), "CSI", "csi")
        self.local_source_input = QLineEdit()
        self.local_source_input.setPlaceholderText("/dev/video0 o pipeline GStreamer")
        self.local_backend = QComboBox()
        self.local_backend.addItem("Auto", "")
        self.local_backend.addItem("V4L2", "v4l2")
        self.local_backend.addItem("GStreamer", "gstreamer")
        self.local_backend.addItem("FFmpeg", "ffmpeg")
        self.local_enabled = QCheckBox("Habilitada")
        self.local_enabled.setChecked(True)
        local_editor.addRow("Nombre", self.local_name)
        local_editor.addRow("Tipo", self.local_kind)
        local_editor.addRow("Fuente", self.local_source_input)
        local_editor.addRow("Backend", self.local_backend)
        local_editor.addRow("Estado", self.local_enabled)

        self.local_cards_container = QVBoxLayout()
        self.local_cards_container.setSpacing(8)
        self.local_cards_container.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.local_cards_widget = QWidget()
        self.local_cards_widget.setLayout(self.local_cards_container)
        self.local_scroll = QScrollArea()
        self.local_scroll.setWidgetResizable(True)
        self.local_scroll.setWidget(self.local_cards_widget)
        self.local_scroll.setMinimumHeight(140)
        self.local_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.local_summary = QLabel("Sin cámaras locales registradas.")
        self.local_summary.setWordWrap(True)
        self.local_summary_icon = QLabel()
        self.local_summary_icon.setFixedSize(16, 16)
        self.local_summary_icon.setPixmap(icon("camera-video", size=16, color="info").pixmap(16, 16))
        self.local_summary_row = QWidget()
        local_summary_layout = QHBoxLayout(self.local_summary_row)
        local_summary_layout.setContentsMargins(0, 0, 0, 0)
        local_summary_layout.setSpacing(6)
        local_summary_layout.addWidget(self.local_summary_icon)
        local_summary_layout.addWidget(self.local_summary, 1)

        local_buttons = QHBoxLayout()
        local_buttons.setSpacing(8)
        self.new_local_button = QPushButton("Nueva")
        self.add_local_button = QPushButton("Agregar")
        self.remove_local_button = QPushButton("Eliminar")
        self.detect_local_button = QPushButton("Detectar y agregar")
        local_buttons.addWidget(self.new_local_button)
        local_buttons.addWidget(self.add_local_button)
        local_buttons.addWidget(self.remove_local_button)
        local_buttons.addWidget(self.detect_local_button)
        local_buttons.addStretch(1)

        local_layout.addLayout(local_editor)
        local_layout.addWidget(self.local_scroll)
        local_layout.addWidget(self.local_summary_row)
        local_buttons_widget = QWidget()
        local_buttons_widget.setLayout(local_buttons)
        local_layout.addWidget(local_buttons_widget)

        self.new_local_button.clicked.connect(self._new_local_camera)
        self.add_local_button.clicked.connect(self._add_or_update_local_camera)
        self.remove_local_button.clicked.connect(self._remove_local_camera)
        self.detect_local_button.clicked.connect(self._detect_and_add_local_cameras)

        source_layout.addLayout(source_form)
        source_layout.addWidget(local_box)
        source_layout.addWidget(rtsp_box)

        self.reload_button.clicked.connect(self.load_env)
        self.save_button.clicked.connect(self.save_env)
        self.import_env_button.clicked.connect(self.import_env_file)
        self.detect_sources_button.clicked.connect(self.refresh_video_sources)
        self.save_source_button.clicked.connect(self.save_video_source)
        self.import_source_button.clicked.connect(self.import_video_source_file)
        self.new_rtsp_button.clicked.connect(self._new_rtsp_camera)
        self.add_rtsp_button.clicked.connect(self._add_or_update_rtsp_camera)
        self.test_rtsp_button.clicked.connect(self._test_rtsp_camera)
        self.remove_rtsp_button.clicked.connect(self._remove_rtsp_camera)
        self.default_rtsp_button.clicked.connect(self._mark_selected_rtsp_default)
        self.source_mode.currentIndexChanged.connect(lambda *_: self._sync_video_source_fields())
        self.rtsp_url.textChanged.connect(lambda *_: self._sync_video_source_fields())

        root.addWidget(box)
        root.addWidget(output_box)
        root.addWidget(source_box)

        self._apply_icons()
        self._sync_video_source_fields()
        self._apply_ui_profile()

    def _apply_ui_profile(self) -> None:
        if self._ui_profile == "single":
            self.rtsp_box.setVisible(False)
            self.local_box.setVisible(False)
            for index in range(self.source_mode.count()):
                if self.source_mode.itemData(index) == "rtsp":
                    self.source_mode.removeItem(index)
                    break

    def _apply_icons(self) -> None:
        self.reload_button.setIcon(icon("arrow-clockwise", size=16))
        self.save_button.setIcon(icon("save2", size=16))
        self.import_env_button.setIcon(icon("upload", size=16, color="info"))
        self.detect_sources_button.setIcon(icon("camera-video", size=16))
        self.save_source_button.setIcon(icon("save", size=16))
        self.import_source_button.setIcon(icon("file-earmark-arrow-up", size=16, color="info"))
        self.new_rtsp_button.setIcon(icon("plus-circle", size=16, color="accent"))
        self.add_rtsp_button.setIcon(icon("check-circle", size=16, color="accent"))
        self.test_rtsp_button.setIcon(icon("ethernet", size=16, color="info"))
        self.remove_rtsp_button.setIcon(icon("trash3", size=16, color="danger"))
        self.default_rtsp_button.setIcon(icon("star-fill", size=16, color="warning"))
        self.new_local_button.setIcon(icon("plus-circle", size=16, color="accent"))
        self.add_local_button.setIcon(icon("check-circle", size=16, color="accent"))
        self.remove_local_button.setIcon(icon("trash3", size=16, color="danger"))
        self.detect_local_button.setIcon(icon("camera-video", size=16, color="info"))

    def _build_rtsp_card(self, camera: dict[str, object], index: int, is_default: bool) -> QFrame:
        name = str(camera.get("name", "")).strip() or "RTSP"
        url = str(camera.get("url", "")).strip()
        username = str(camera.get("username", "")).strip()
        enabled = bool(camera.get("enabled", True))

        card = QFrame()
        card.setObjectName("rtspCard")

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(8)

        def _badge(text: str, icon_name: str, color: str, text_color: str) -> QWidget:
            badge = QWidget()
            badge_layout = QHBoxLayout(badge)
            badge_layout.setContentsMargins(0, 0, 0, 0)
            badge_layout.setSpacing(4)
            badge_icon = QLabel()
            badge_icon.setFixedSize(14, 14)
            badge_icon.setPixmap(icon(icon_name, size=14, color=color).pixmap(14, 14))
            badge_text = QLabel(text)
            badge_text.setStyleSheet(f"color: {text_color}; font-size: 11px; font-weight: 600;")
            badge_layout.addWidget(badge_icon)
            badge_layout.addWidget(badge_text)
            return badge

        cam_icon = QLabel()
        cam_icon.setPixmap(icon("camera-video", size=16).pixmap(16, 16))
        cam_icon.setFixedSize(18, 18)
        header.addWidget(cam_icon)

        name_badge = QLabel(name)
        name_badge.setObjectName("badge")
        name_badge.setStyleSheet("font-size: 12px; font-weight: 600; color: #e6eaf2;")
        header.addWidget(name_badge)

        header.addStretch(1)

        if is_default:
            header.addWidget(_badge("Default", "star-fill", "warning", "#f4b942"))

        header.addWidget(
            _badge(
                "Activo" if enabled else "Inactivo",
                "check-circle" if enabled else "x-circle",
                "accent" if enabled else "danger",
                "#62d2a2" if enabled else "#e66b6b",
            )
        )

        card_layout.addLayout(header)

        details = QHBoxLayout()
        details.setSpacing(12)
        url_display = QLabel(url if url else "(sin URL)")
        url_display.setStyleSheet("color: #6c7680; font-size: 10px;")
        url_display.setWordWrap(True)
        details.addWidget(url_display, 1)

        if username:
            user_label = QLabel(f"@{username}")
            user_label.setStyleSheet("color: #6c7680; font-size: 10px;")
            details.addWidget(user_label)

        card_layout.addLayout(details)

        return card

    def _refresh_rtsp_cards(self, *, select_name: str | None = None) -> None:
        while self.rtsp_cards_container.count():
            item = self.rtsp_cards_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._rtsp_card_widgets.clear()
        default_name = self._rtsp_default_camera.strip()

        for idx, camera in enumerate(self._rtsp_cameras):
            name = str(camera.get("name", "")).strip() or "RTSP"
            is_default = name == default_name
            card = self._build_rtsp_card(camera, idx, is_default)
            card.mousePressEvent = self._make_card_click_handler(idx)
            self.rtsp_cards_container.addWidget(card)
            self._rtsp_card_widgets.append({"card": card, "index": idx, "name": name})

        self.rtsp_cards_container.addStretch(1)

        target_name = select_name or default_name
        if target_name:
            for entry in self._rtsp_card_widgets:
                if entry["name"] == target_name:
                    self.rtsp_list.blockSignals(True)
                    self.rtsp_list.setCurrentRow(entry["index"])
                    self.rtsp_list.blockSignals(False)
                    self._highlight_card(entry["index"])
                    break
        elif self.rtsp_cameras:
            self.rtsp_list.blockSignals(True)
            self.rtsp_list.setCurrentRow(0)
            self.rtsp_list.blockSignals(False)
            self._highlight_card(0)

    def _highlight_card(self, index: int) -> None:
        for i, entry in enumerate(self._rtsp_card_widgets):
            card = entry["card"]
            if i == index and index >= 0:
                card.setStyleSheet(
                    "QFrame#rtspCard { background: #171a21; border: 2px solid #62d2a2; border-radius: 10px; padding: 12px; }"
                )
            else:
                card.setStyleSheet(
                    "QFrame#rtspCard { background: #171a21; border: 1px solid #2a313a; border-radius: 10px; padding: 12px; }"
                )

    def _make_card_click_handler(self, index: int):
        def handler(event):
            self.rtsp_list.blockSignals(True)
            self.rtsp_list.setCurrentRow(index)
            self.rtsp_list.blockSignals(False)
            self._load_selected_rtsp_camera(self.rtsp_list.currentItem(), None)
            self._highlight_card(index)

        return handler

    def load_env(self) -> None:
        values = read_env_file(Path(self.env_file.text().strip() or ".env"))
        self.forge_url.setText(values.get("FORGE_URL", ""))
        self.forge_user.setText(values.get("FORGE_USERNAME", ""))
        self.forge_password.setText(values.get("FORGE_PASSWORD", ""))
        self.forge_token.setText(values.get("FORGE_TOKEN", ""))
        self.forge_model_url.setText(values.get("FORGE_MODEL_URL", ""))
        self.forge_model_asset_uuid.setText(values.get("FORGE_MODEL_ASSET_UUID", ""))
        self.model_dir.setText(values.get("MODEL_DIR", "models"))
        self.capture_dir.setText(values.get("CAPTURE_DIR", "captures"))
        self.simulation_mode.setText(values.get("SIMULATION_MODE", "true"))
        self.output_mqtt_enabled.setText(values.get("OUTPUT_MQTT_ENABLED", "false"))
        self.output_mqtt_host.setText(values.get("OUTPUT_MQTT_HOST", ""))
        self.output_mqtt_port.setText(values.get("OUTPUT_MQTT_PORT", "1883"))
        self.output_mqtt_topic.setText(values.get("OUTPUT_MQTT_TOPIC", "edgevision/inference"))
        self.output_http_enabled.setText(values.get("OUTPUT_HTTP_ENABLED", "false"))
        self.output_http_url.setText(values.get("OUTPUT_HTTP_URL", ""))
        self.output_websocket_enabled.setText(values.get("OUTPUT_WEBSOCKET_ENABLED", "false"))
        self.output_websocket_url.setText(values.get("OUTPUT_WEBSOCKET_URL", ""))
        self.output_tcp_enabled.setText(values.get("OUTPUT_TCP_ENABLED", "false"))
        self.output_tcp_host.setText(values.get("OUTPUT_TCP_HOST", ""))
        self.output_tcp_port.setText(values.get("OUTPUT_TCP_PORT", "9000"))
        self.output_udp_enabled.setText(values.get("OUTPUT_UDP_ENABLED", "false"))
        self.output_udp_host.setText(values.get("OUTPUT_UDP_HOST", ""))
        self.output_udp_port.setText(values.get("OUTPUT_UDP_PORT", "9001"))
        self.output_modbus_enabled.setText(values.get("OUTPUT_MODBUS_ENABLED", "false"))
        self.output_modbus_host.setText(values.get("OUTPUT_MODBUS_HOST", ""))
        self.output_modbus_port.setText(values.get("OUTPUT_MODBUS_PORT", "502"))
        self.output_modbus_unit_id.setText(values.get("OUTPUT_MODBUS_UNIT_ID", "1"))
        self.output_modbus_count_register.setText(values.get("OUTPUT_MODBUS_COUNT_REGISTER", "0"))
        self.output_modbus_active_coil.setText(values.get("OUTPUT_MODBUS_ACTIVE_COIL", "0"))
        theme = values.get("UI_THEME", "dark").strip().lower()
        self.ui_theme.setCurrentText("light" if theme == "light" else "dark")
        self.load_video_source()

    def _on_test_forge_clicked(self) -> None:
        self.forge_test_status.setText("Probando…")
        self.forge_test_status.setStyleSheet("color:#f4cd6b; font-size:11px;")
        self.forge_test_requested.emit({
            "FORGE_URL": self.forge_url.text().strip(),
            "FORGE_USERNAME": self.forge_user.text().strip(),
            "FORGE_PASSWORD": self.forge_password.text(),
            "FORGE_TOKEN": self.forge_token.text().strip(),
        })

    def set_forge_test_result(self, ok: bool, detail: str = "") -> None:
        if ok:
            self.forge_test_status.setText(f"✓ Conexión OK · {detail}".strip(" ·"))
            self.forge_test_status.setStyleSheet("color:#62d2a2; font-size:11px;")
        else:
            self.forge_test_status.setText(f"✗ {detail or 'Error de conexión'}")
            self.forge_test_status.setStyleSheet("color:#e66b6b; font-size:11px;")

    def save_env(self) -> None:
        path = Path(self.env_file.text().strip() or ".env")
        values = {
            "FORGE_URL": self.forge_url.text().strip(),
            "FORGE_USERNAME": self.forge_user.text().strip(),
            "FORGE_PASSWORD": self.forge_password.text().strip(),
            "FORGE_TOKEN": self.forge_token.text().strip(),
            "FORGE_MODEL_URL": self.forge_model_url.text().strip(),
            "FORGE_MODEL_ASSET_UUID": self.forge_model_asset_uuid.text().strip(),
            "MODEL_DIR": self.model_dir.text().strip(),
            "CAPTURE_DIR": self.capture_dir.text().strip(),
            "SIMULATION_MODE": self.simulation_mode.text().strip(),
            "UI_THEME": self.ui_theme.currentText().strip(),
            "OUTPUT_MQTT_ENABLED": self.output_mqtt_enabled.text().strip(),
            "OUTPUT_MQTT_HOST": self.output_mqtt_host.text().strip(),
            "OUTPUT_MQTT_PORT": self.output_mqtt_port.text().strip(),
            "OUTPUT_MQTT_TOPIC": self.output_mqtt_topic.text().strip(),
            "OUTPUT_HTTP_ENABLED": self.output_http_enabled.text().strip(),
            "OUTPUT_HTTP_URL": self.output_http_url.text().strip(),
            "OUTPUT_WEBSOCKET_ENABLED": self.output_websocket_enabled.text().strip(),
            "OUTPUT_WEBSOCKET_URL": self.output_websocket_url.text().strip(),
            "OUTPUT_TCP_ENABLED": self.output_tcp_enabled.text().strip(),
            "OUTPUT_TCP_HOST": self.output_tcp_host.text().strip(),
            "OUTPUT_TCP_PORT": self.output_tcp_port.text().strip(),
            "OUTPUT_UDP_ENABLED": self.output_udp_enabled.text().strip(),
            "OUTPUT_UDP_HOST": self.output_udp_host.text().strip(),
            "OUTPUT_UDP_PORT": self.output_udp_port.text().strip(),
            "OUTPUT_MODBUS_ENABLED": self.output_modbus_enabled.text().strip(),
            "OUTPUT_MODBUS_HOST": self.output_modbus_host.text().strip(),
            "OUTPUT_MODBUS_PORT": self.output_modbus_port.text().strip(),
            "OUTPUT_MODBUS_UNIT_ID": self.output_modbus_unit_id.text().strip(),
            "OUTPUT_MODBUS_COUNT_REGISTER": self.output_modbus_count_register.text().strip(),
            "OUTPUT_MODBUS_ACTIVE_COIL": self.output_modbus_active_coil.text().strip(),
        }
        write_env_file(path, values)
        self.env_changed.emit(values)

    def import_env_file(self) -> None:
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            "Importar configuración .env",
            str(Path.home()),
            "Env files (*.env *.txt);;All files (*)",
        )
        if not selected:
            return
        source = Path(selected)
        target = Path(self.env_file.text().strip() or ".env")
        try:
            values = read_env_file(source)
            if not values:
                raise ValueError("El archivo no contiene claves KEY=VALUE válidas.")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
        except Exception as exc:
            self.forge_test_status.setText(f"No se pudo importar .env: {exc}")
            self.forge_test_status.setStyleSheet("color:#e66b6b; font-size:11px;")
            return

        self.load_env()
        self.forge_test_status.setText(f".env importado desde {source.name}")
        self.forge_test_status.setStyleSheet("color:#62d2a2; font-size:11px;")
        self.env_changed.emit(read_env_file(target))

    def import_video_source_file(self) -> None:
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            "Importar inference_source.json",
            str(Path.home()),
            "JSON files (*.json);;All files (*)",
        )
        if not selected:
            return
        source = Path(selected)
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("El JSON debe tener un objeto en la raíz.")
            config = InferenceSourceConfig.from_mapping(payload)
            save_inference_source_config(VIDEO_SOURCE_PATH, config)
        except Exception as exc:
            self._set_source_status(
                f"No se pudo importar JSON: {exc}",
                icon_name="x-circle",
                icon_color="danger",
            )
            return

        self._video_source_config = config
        self.load_video_source()
        self._set_source_status(
            f"Fuente importada desde {source.name}",
            icon_name="file-earmark-check",
            icon_color="accent",
        )
        self.video_source_changed.emit(config.to_mapping())

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
        self.rtsp_status.setObjectName("")
        if ok is True:
            color = "#62d2a2"
            self.rtsp_status.setObjectName("statusOk")
            icon_name, icon_color = "check-circle", "accent"
        elif ok is False:
            color = "#e66b6b"
            self.rtsp_status.setObjectName("statusOff")
            icon_name, icon_color = "x-circle", "danger"
        self.rtsp_status.setStyleSheet(f"color:{color};")
        self.rtsp_status.setText(text)
        if ok is None:
            icon_name, icon_color = "info-circle", "info"
        self.rtsp_status_icon.setPixmap(icon(icon_name, size=16, color=icon_color).pixmap(16, 16))

    def _set_source_status(self, text: str, *, icon_name: str = "info-circle", icon_color: str = "info") -> None:
        self.source_status.setText(text)
        self.source_status_icon.setPixmap(icon(icon_name, size=16, color=icon_color).pixmap(16, 16))
        color_map = {
            "info": "#9fb2c8",
            "accent": "#62d2a2",
            "warning": "#f4b942",
            "danger": "#e66b6b",
            "muted": "#6c7680",
        }
        self.source_status.setStyleSheet(f"color:{color_map.get(icon_color, '#9fb2c8')};")

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
            if name == default_name:
                item.setIcon(icon("star-fill", size=16, color="warning"))
            elif enabled:
                item.setIcon(icon("broadcast", size=16, color="accent"))
            else:
                item.setIcon(icon("x-circle", size=16, color="danger"))
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
        self._refresh_rtsp_cards(select_name=target_name if target_name else None)

    def _update_rtsp_summary(self) -> None:
        total = len(self._rtsp_cameras)
        enabled = sum(1 for camera in self._rtsp_cameras if bool(camera.get("enabled", True)))
        default_name = self._rtsp_default_camera.strip() or "ninguna"
        if total:
            self.rtsp_summary.setText(f"{enabled} de {total} cámaras habilitadas · inicio: {default_name}")
            icon_name, icon_color = ("broadcast", "info") if enabled else ("slash-circle", "muted")
        else:
            self.rtsp_summary.setText("Sin cámaras RTSP registradas.")
            icon_name, icon_color = "slash-circle", "muted"
        self.rtsp_summary_icon.setPixmap(icon(icon_name, size=16, color=icon_color).pixmap(16, 16))
        color_map = {
            "info": "#9fb2c8",
            "accent": "#62d2a2",
            "warning": "#f4b942",
            "danger": "#e66b6b",
            "muted": "#6c7680",
        }
        self.rtsp_summary.setStyleSheet(f"color:{color_map.get(icon_color, '#9fb2c8')};")

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
        self._highlight_card(-1)

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
            self._set_source_status(
                "Completa la URL RTSP para agregar la cámara.",
                icon_name="x-circle",
                icon_color="danger",
            )
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

    def _build_local_card(self, camera: dict[str, object], index: int) -> QFrame:
        name = str(camera.get("name", "")).strip() or f"Cámara {index + 1}"
        kind = str(camera.get("kind", "webcam")).strip().lower() or "webcam"
        source = str(camera.get("source", "")).strip()
        backend = str(camera.get("backend", "")).strip().lower()
        enabled = bool(camera.get("enabled", True))

        card = QFrame()
        card.setObjectName("rtspCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(8)
        cam_icon = QLabel()
        icon_name = "diagram-3" if kind == "csi" else "camera-video"
        cam_icon.setPixmap(icon(icon_name, size=16).pixmap(16, 16))
        cam_icon.setFixedSize(18, 18)
        header.addWidget(cam_icon)

        name_badge = QLabel(name)
        name_badge.setObjectName("badge")
        name_badge.setStyleSheet("font-size: 12px; font-weight: 600; color: #e6eaf2;")
        header.addWidget(name_badge)

        kind_badge = QLabel(kind.upper())
        kind_badge.setObjectName("badge")
        kind_badge.setStyleSheet("font-size: 10px; font-weight: 600; color: #9fb2c8;")
        header.addWidget(kind_badge)

        header.addStretch(1)

        status_text = "Activa" if enabled else "Inactiva"
        status_color = "#62d2a2" if enabled else "#e66b6b"
        status_label = QLabel(status_text)
        status_label.setStyleSheet(f"color: {status_color}; font-size: 11px; font-weight: 600;")
        header.addWidget(status_label)

        card_layout.addLayout(header)

        details_text = source if source else "(sin fuente)"
        if backend:
            details_text = f"{details_text}  ·  {backend}"
        details = QLabel(details_text)
        details.setStyleSheet("color: #6c7680; font-size: 10px;")
        details.setWordWrap(True)
        card_layout.addWidget(details)

        return card

    def _make_local_card_click_handler(self, index: int):
        def _handler(_event):
            if 0 <= index < len(self._local_cameras):
                self._local_selected_index = index
                self._load_local_camera_into_form(index)
                self._refresh_local_cards()
        return _handler

    def _refresh_local_cards(self) -> None:
        while self.local_cards_container.count():
            item = self.local_cards_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._local_card_widgets.clear()

        for idx, camera in enumerate(self._local_cameras):
            card = self._build_local_card(camera, idx)
            card.mousePressEvent = self._make_local_card_click_handler(idx)
            if self._local_selected_index == idx:
                card.setStyleSheet(card.styleSheet() + "QFrame#rtspCard { border-color: #62d2a2; }")
            self.local_cards_container.addWidget(card)
            self._local_card_widgets.append({"card": card, "index": idx})

        self.local_cards_container.addStretch(1)
        self._refresh_local_summary()

    def _refresh_local_summary(self) -> None:
        total = len(self._local_cameras)
        enabled = sum(1 for camera in self._local_cameras if bool(camera.get("enabled", True)))
        if total == 0:
            self.local_summary.setText("Sin cámaras locales registradas.")
        else:
            self.local_summary.setText(f"{total} cámara(s) local(es), {enabled} habilitada(s).")

    def _load_local_camera_into_form(self, index: int) -> None:
        if not (0 <= index < len(self._local_cameras)):
            return
        camera = self._local_cameras[index]
        self.local_name.setText(str(camera.get("name", "")))
        kind = str(camera.get("kind", "webcam")).strip().lower() or "webcam"
        kind_idx = self.local_kind.findData(kind)
        if kind_idx >= 0:
            self.local_kind.setCurrentIndex(kind_idx)
        self.local_source_input.setText(str(camera.get("source", "")))
        backend = str(camera.get("backend", "")).strip().lower()
        backend_idx = self.local_backend.findData(backend)
        self.local_backend.setCurrentIndex(backend_idx if backend_idx >= 0 else 0)
        self.local_enabled.setChecked(bool(camera.get("enabled", True)))

    def _local_camera_from_fields(self) -> dict[str, object] | None:
        source = self.local_source_input.text().strip()
        if not source:
            self.local_summary.setText("Indica una fuente (/dev/videoN o pipeline GStreamer).")
            return None
        kind = str(self.local_kind.currentData() or "webcam").strip().lower() or "webcam"
        backend = str(self.local_backend.currentData() or "").strip().lower()
        if not backend:
            backend = "gstreamer" if kind == "csi" else "v4l2"
        name = self.local_name.text().strip() or f"Cámara {len(self._local_cameras) + 1}"
        return {
            "name": name,
            "kind": kind,
            "source": source,
            "backend": backend,
            "enabled": self.local_enabled.isChecked(),
        }

    def _new_local_camera(self) -> None:
        self._local_selected_index = None
        self.local_name.clear()
        self.local_kind.setCurrentIndex(0)
        self.local_source_input.clear()
        self.local_backend.setCurrentIndex(0)
        self.local_enabled.setChecked(True)
        self._refresh_local_cards()

    def _add_or_update_local_camera(self) -> None:
        camera = self._local_camera_from_fields()
        if camera is None:
            return
        name = str(camera.get("name", "")).strip()
        existing_index = next(
            (i for i, item in enumerate(self._local_cameras) if str(item.get("name", "")).strip() == name),
            -1,
        )
        if self._local_selected_index is None:
            if existing_index >= 0:
                self._local_cameras[existing_index] = camera
                self._local_selected_index = existing_index
            else:
                self._local_cameras.append(camera)
                self._local_selected_index = len(self._local_cameras) - 1
        else:
            idx = self._local_selected_index
            if 0 <= idx < len(self._local_cameras):
                self._local_cameras[idx] = camera
            else:
                self._local_cameras.append(camera)
                self._local_selected_index = len(self._local_cameras) - 1
        self._refresh_local_cards()

    def _remove_local_camera(self) -> None:
        idx = self._local_selected_index
        if idx is None or not (0 <= idx < len(self._local_cameras)):
            return
        self._local_cameras.pop(idx)
        self._local_selected_index = None
        self._new_local_camera()

    def _detect_and_add_local_cameras(self) -> None:
        sources = discover_video_sources()
        existing_sources = {str(cam.get("source", "")).strip() for cam in self._local_cameras}
        added = 0
        skipped_unavailable = 0
        for choice in sources:
            if not choice.source or choice.source in existing_sources:
                continue
            if not choice.available:
                skipped_unavailable += 1
                continue
            kind = choice.kind if choice.kind in {"webcam", "csi"} else "webcam"
            self._local_cameras.append({
                "name": choice.label or choice.source,
                "kind": kind,
                "source": choice.source,
                "backend": choice.backend or ("gstreamer" if kind == "csi" else "v4l2"),
                "enabled": True,
            })
            existing_sources.add(choice.source)
            added += 1
        self._refresh_local_cards()
        if added:
            suffix = f" ({skipped_unavailable} sin señal omitidas)" if skipped_unavailable else ""
            self._set_source_status(
                f"Agregadas {added} cámara(s) detectada(s){suffix}.",
                icon_name="camera-video",
                icon_color="accent",
            )
        elif skipped_unavailable:
            self._set_source_status(
                f"Se detectaron {skipped_unavailable} dispositivo(s) sin señal capturable.",
                icon_name="slash-circle",
                icon_color="warning",
            )
        else:
            self._set_source_status(
                "No hay cámaras locales nuevas para agregar.",
                icon_name="info-circle",
                icon_color="info",
            )

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
            icon_name = {
                "webcam": "camera-video",
                "csi": "diagram-3",
                "rtsp": "broadcast",
                "manual": "question-circle",
            }.get(choice.kind, "activity")
            icon_color = "muted" if not choice.available else "accent"
            self.local_source.addItem(icon(icon_name, size=16, color=icon_color), label, choice.source)
        if selected_source and self.local_source.findData(selected_source) < 0:
            fallback_choice = VideoSourceChoice(kind="manual", label=selected_source, source=selected_source, backend="", available=False)
            self.local_source.addItem(icon("question-circle", size=16, color="muted"), fallback_choice.label, selected_source)
            self._available_sources[selected_source] = fallback_choice
        if self.local_source.count() == 0:
            self.local_source.addItem(icon("slash-circle", size=16, color="muted"), "Sin cámaras detectadas", "")
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
            self._set_source_status(
                f"Detectadas {len(sources)} cámaras locales.",
                icon_name="camera-video",
                icon_color="accent",
            )
        else:
            self._set_source_status(
                "No se detectaron cámaras locales. RTSP sigue disponible.",
                icon_name="slash-circle",
                icon_color="warning",
            )

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

        self._local_cameras = [dict(cam) for cam in cfg.local_cameras if isinstance(cam, dict)]
        self._local_selected_index = None
        self._refresh_local_cards()

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
            self._set_source_status(
                f"Fuente activa: {cfg.last_resolved_label or cfg.last_resolved_source}",
                icon_name="camera-video",
                icon_color="accent",
            )
        else:
            self._set_source_status(
                "Auto detectará cámaras USB/CSI en Linux.",
                icon_name="info-circle",
                icon_color="info",
            )

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
        local_cameras = [dict(cam) for cam in self._local_cameras if str(cam.get("source", "")).strip()]
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
            local_cameras=local_cameras,
            last_resolved_source=self._video_source_config.last_resolved_source,
            last_resolved_label=self._video_source_config.last_resolved_label,
            last_resolved_kind=self._video_source_config.last_resolved_kind,
            last_resolved_backend=self._video_source_config.last_resolved_backend,
            discovered_sources=[choice.as_dict() for choice in self._available_sources.values()],
        )
        save_inference_source_config(VIDEO_SOURCE_PATH, config)
        self._video_source_config = config
        self._set_source_status(
            f"Guardado en {VIDEO_SOURCE_PATH}",
            icon_name="save",
            icon_color="accent",
        )
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
    def __init__(
        self,
        env_path: str = ".env",
        parent: QWidget | None = None,
        *,
        ui_profile: str = "desktop",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Configuración")
        self.setWindowIcon(icon("gear", size=24))
        self.setSizeGripEnabled(True)
        self.setMinimumSize(720, 480)
        screen = self.screen() if parent is None else parent.screen()
        if screen is not None:
            available = screen.availableSize()
            self.resize(min(1000, int(available.width() * 0.85)), min(820, int(available.height() * 0.9)))
        else:
            self.resize(1000, 820)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        self.panel = SettingsPanel(env_path=env_path, parent=scroll, ui_profile=ui_profile)
        scroll.setWidget(self.panel)
        layout.addWidget(scroll, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close | QDialogButtonBox.StandardButton.Save)
        if (save_button := buttons.button(QDialogButtonBox.StandardButton.Save)) is not None:
            save_button.setIcon(icon("save", size=16))
        if (close_button := buttons.button(QDialogButtonBox.StandardButton.Close)) is not None:
            close_button.setIcon(icon("x-lg", size=16))
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self._save_and_close)
        button_row = QWidget()
        button_layout = QHBoxLayout(button_row)
        button_layout.setContentsMargins(16, 8, 16, 12)
        button_layout.addStretch(1)
        button_layout.addWidget(buttons)
        layout.addWidget(button_row, 0)

    def _save_and_close(self) -> None:
        self.panel.save_env()
        self.panel.save_video_source()
        self.accept()
