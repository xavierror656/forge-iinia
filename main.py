"""EdgeVision Control Hub bootstrap.

This is the initial executable scaffold for the application:
UI thread, inference thread, GPIO/signals thread, and watchdog orchestration.
"""

from __future__ import annotations

import argparse
import ast
import json
import traceback
import queue
import time
from threading import Lock
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, QPoint, QThread, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from cvat.cvat_manager import CvatManager
from core.async_worker import AsyncWorker
from core.env_config import read_env_file
from core.hardware_manager import HardwareManager
from core.forge_manager import ForgeManager
from ui.cvat_panel import CvatPanel
from ui.forge_panel import CameraCreateDialog, ForgeConfigDialog, ForgePanel
from ui.settings_panel import SettingsDialog, SettingsPanel


@dataclass(slots=True)
class TelemetrySnapshot:
    capture_fps: float = 0.0
    inference_fps: float = 0.0
    latency_ms: float = 0.0
    ram_mb: float = 0.0
    vram_mb: float = 0.0
    soc_temp_c: float = 0.0
    provider_name: str = ""


@dataclass(slots=True)
class DetectionState:
    label: str
    consecutive_frames: int = 0
    threshold: int = 3
    latched: bool = False

    def register(self, detected: bool) -> bool:
        if detected:
            self.consecutive_frames += 1
        else:
            self.consecutive_frames = 0
            self.latched = False

        if self.consecutive_frames >= self.threshold and not self.latched:
            self.latched = True
            return True

        return False


class OpenGLVideoWidget(QOpenGLWidget):
    """Low-overhead display widget for the camera stream."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._frame: Any = None
        self._status_text = "Waiting for stream..."
        self.setMinimumHeight(360)

    def set_frame(self, frame: Any) -> None:
        self._frame = frame
        self.update()

    def set_status(self, text: str) -> None:
        self._status_text = text
        self.update()

    def paintGL(self) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#111318"))
        painter.setPen(QPen(QColor("#62d2a2")))
        painter.drawText(self.rect().adjusted(16, 16, -16, -16), 0x84, self._status_text)
        if self._frame is not None:
            painter.setPen(QPen(QColor("#ffffff")))
            painter.drawText(QPoint(16, 48), "Frame buffer received")
        painter.end()


class InferenceWorker(QThread):
    frame_ready = pyqtSignal(object)
    telemetry_ready = pyqtSignal(dict)
    log_message = pyqtSignal(str)
    detection_event = pyqtSignal(str, bool)
    model_loaded = pyqtSignal(str)
    frozen = pyqtSignal()

    def __init__(self, model_path: str | None, hardware: HardwareManager, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._hardware = hardware
        self._model_path = Path(model_path) if model_path else None
        self._stop_requested = False
        self._last_heartbeat = time.monotonic()
        self._last_model_mtime = 0.0
        self._simulated_detection = DetectionState(label="person", threshold=4)

    def request_stop(self) -> None:
        self._stop_requested = True

    def heartbeat(self) -> float:
        return self._last_heartbeat

    def _load_model(self) -> None:
        if not self._model_path:
            self.log_message.emit("No model path provided. Running in simulation mode.")
            self.model_loaded.emit("simulation")
            return

        if not self._model_path.exists():
            self.log_message.emit(f"Model not found: {self._model_path}")
            self.model_loaded.emit("missing")
            return

        self._last_model_mtime = self._model_path.stat().st_mtime
        self.log_message.emit(f"Model loaded: {self._model_path.name}")
        self.model_loaded.emit(str(self._model_path))

    def _maybe_hot_reload(self) -> None:
        if not self._model_path or not self._model_path.exists():
            return
        current_mtime = self._model_path.stat().st_mtime
        if current_mtime > self._last_model_mtime:
            self.log_message.emit(f"Hot reload triggered for {self._model_path.name}")
            self._load_model()

    def _run_inference_step(self) -> None:
        start = time.perf_counter()
        self._last_heartbeat = time.monotonic()
        self._maybe_hot_reload()

        detected = int(time.monotonic() * 10) % 7 == 0
        stable = self._simulated_detection.register(detected)
        if stable:
            self.detection_event.emit(self._simulated_detection.label, True)

        frame = {
            "timestamp": self._last_heartbeat,
            "provider": self._hardware.info.name,
            "simulation": self._hardware.is_simulation(),
        }
        self.frame_ready.emit(frame)

        elapsed_ms = (time.perf_counter() - start) * 1000.0
        telemetry = TelemetrySnapshot(
            capture_fps=30.0,
            inference_fps=30.0,
            latency_ms=elapsed_ms,
            ram_mb=256.0,
            vram_mb=128.0 if self._hardware.supports_tensor_rt() else 0.0,
            soc_temp_c=0.0,
            provider_name=self._hardware.info.name,
        )
        self.telemetry_ready.emit(asdict(telemetry))

    def run(self) -> None:
        self._load_model()
        while not self._stop_requested:
            try:
                self._run_inference_step()
                self.msleep(33)
            except Exception as exc:  # pragma: no cover - defensive scaffold
                self.log_message.emit(f"Inference error: {exc}")
                self.frozen.emit()
                self.msleep(500)


class GPIOWorker(QThread):
    log_message = pyqtSignal(str)

    def __init__(self, hardware: HardwareManager, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._hardware = hardware
        self._events: "queue.Queue[tuple[str, bool]]" = queue.Queue()
        self._stop_requested = False
        self._simulation = hardware.is_simulation()
        self._assignments: dict[str, str] = {}
        self._assignments_lock = Lock()

    def request_stop(self) -> None:
        self._stop_requested = True

    def enqueue_detection(self, label: str, active: bool) -> None:
        self._events.put((label, active))

    def set_assignments(self, assignments: dict[str, str]) -> None:
        with self._assignments_lock:
            self._assignments = dict(assignments)

    def run(self) -> None:
        while not self._stop_requested:
            try:
                label, active = self._events.get(timeout=0.25)
            except queue.Empty:
                continue

            with self._assignments_lock:
                port = self._assignments.get(label, "")

            if self._simulation:
                if port:
                    self.log_message.emit(f"[SIM] GPIO event: {label} -> {active} on {port}")
                else:
                    self.log_message.emit(f"[SIM] GPIO event: {label} -> {active}")
            else:
                if port:
                    self.log_message.emit(f"GPIO event: {label} -> {active} on {port} via {self._hardware.info.gpio_backend}")
                else:
                    self.log_message.emit(f"GPIO event: {label} -> {active} via {self._hardware.info.gpio_backend}")


class Watchdog(QThread):
    restart_requested = pyqtSignal()
    log_message = pyqtSignal(str)

    def __init__(self, inference_worker: InferenceWorker, timeout_s: float = 2.5, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._inference_worker = inference_worker
        self._timeout_s = timeout_s
        self._stop_requested = False

    def request_stop(self) -> None:
        self._stop_requested = True

    def run(self) -> None:
        while not self._stop_requested:
            age = time.monotonic() - self._inference_worker.heartbeat()
            if age > self._timeout_s:
                self.log_message.emit("Watchdog detected inference freeze. Restart requested.")
                self.restart_requested.emit()
                return
            self.msleep(500)


class MainWindow(QMainWindow):
    def __init__(self, hardware: HardwareManager) -> None:
        super().__init__()
        self._hardware = hardware
        self._cvat = CvatManager("https://app.cvat.ai")
        self._forge = ForgeManager("https://forge.iinia.ai/api/swagger/")
        self._workers: list[AsyncWorker] = []
        self._camera_assignments: dict[str, list[str]] = self._load_local_assignments()
        self._gpio_assignments: dict[str, dict[str, str]] = self._load_gpio_assignments()
        self._inference_worker = InferenceWorker(None, hardware, self)
        self._gpio_worker = GPIOWorker(hardware, self)
        self._watchdog = Watchdog(self._inference_worker, parent=self)
        self._build_ui()
        self._apply_env_settings(read_env_file(Path(self.settings_panel.env_file.text().strip() or ".env")))
        self._wire_threads()
        self._start_threads()
        self._bootstrap_from_env()

    def _report_error(self, context: str, exc: Exception) -> None:
        message = f"{context}: {exc}"
        self._set_status(message)
        self._append_log(message)

    def _safe_ui_call(self, fn, *, context: str) -> None:
        try:
            fn()
        except Exception as exc:  # pragma: no cover - UI guard
            self._report_error(context, exc)
            self._append_log(traceback.format_exc())

    def _build_ui(self) -> None:
        self.setWindowTitle("EdgeVision Control Hub")
        self.resize(1400, 900)

        central = QWidget(self)
        root = QVBoxLayout(central)

        header = QHBoxLayout()
        self.hardware_label = QLabel(f"Hardware: {self._hardware.info.name}")
        self.hardware_hint = QLabel(self._hardware.info.deployment_note)
        self.simulation_switch = QCheckBox("Modo Simulación")
        self.simulation_switch.setChecked(self._hardware.is_simulation())
        self.simulation_switch.setEnabled(False)
        self.settings_button = QPushButton("Config .env")
        self.dark_mode_switch = QCheckBox("Dark mode")
        self.dark_mode_switch.setChecked(True)
        header.addWidget(self.hardware_label)
        header.addStretch(1)
        header.addWidget(self.settings_button)
        header.addWidget(self.dark_mode_switch)
        header.addWidget(self.simulation_switch)

        self.video_widget = OpenGLVideoWidget(self)
        self.settings_panel = SettingsPanel()
        self.cvat_panel = CvatPanel()
        self.forge_panel = ForgePanel()
        self.tabs = QTabWidget()

        live_tab = QWidget()
        live_layout = QVBoxLayout(live_tab)

        telemetry_grid = QGridLayout()
        self.fps_capture = QLabel("0.0")
        self.fps_inference = QLabel("0.0")
        self.latency = QLabel("0.0 ms")
        self.ram = QLabel("0 MB")
        self.vram = QLabel("0 MB")
        self.temperature = QLabel("0 °C")
        telemetry_grid.addWidget(QLabel("FPS captura"), 0, 0)
        telemetry_grid.addWidget(self.fps_capture, 0, 1)
        telemetry_grid.addWidget(QLabel("FPS inferencia"), 0, 2)
        telemetry_grid.addWidget(self.fps_inference, 0, 3)
        telemetry_grid.addWidget(QLabel("Latencia"), 1, 0)
        telemetry_grid.addWidget(self.latency, 1, 1)
        telemetry_grid.addWidget(QLabel("RAM"), 1, 2)
        telemetry_grid.addWidget(self.ram, 1, 3)
        telemetry_grid.addWidget(QLabel("VRAM"), 2, 0)
        telemetry_grid.addWidget(self.vram, 2, 1)
        telemetry_grid.addWidget(QLabel("SoC"), 2, 2)
        telemetry_grid.addWidget(self.temperature, 2, 3)

        self.health_bar = QProgressBar()
        self.health_bar.setRange(0, 100)
        self.health_bar.setValue(100)

        self.capture_button = QPushButton("Tomar foto de componente")
        self.capture_button.clicked.connect(self._capture_component_photo)

        self.restart_button = QPushButton("Reiniciar inferencia")
        self.restart_button.clicked.connect(self._restart_inference)

        self.status_banner = QLabel("Ready")
        self.status_banner.setStyleSheet("padding: 6px; border-radius: 6px; background: #1b2028; color: #d8dde3;")

        live_layout.addWidget(self.video_widget)
        live_layout.addWidget(self.status_banner)
        live_layout.addLayout(telemetry_grid)
        live_layout.addWidget(self.health_bar)
        live_layout.addWidget(self.capture_button)
        live_layout.addWidget(self.restart_button)

        forge_tab = QWidget()
        forge_layout = QVBoxLayout(forge_tab)
        forge_layout.addWidget(self.forge_panel)

        logs_tab = QWidget()
        logs_layout = QVBoxLayout(logs_tab)
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setPlaceholderText("System log...")
        self.console.setFont(QFont("JetBrains Mono", 9))
        logs_layout.addWidget(self.console)

        self.tabs.addTab(live_tab, "Live")
        self.tabs.addTab(forge_tab, "Forge")
        self.tabs.addTab(logs_tab, "Logs")

        root.addLayout(header)
        root.addWidget(self.hardware_hint)
        root.addWidget(self.tabs)

        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar(self))

        self.settings_panel.env_changed.connect(self._apply_env_settings)
        self.settings_button.clicked.connect(self._open_settings_dialog)
        self.dark_mode_switch.toggled.connect(self._apply_dark_theme)
        self.dark_mode_switch.toggled.connect(lambda enabled: self.settings_panel.ui_theme.setCurrentText("dark" if enabled else "light"))
        self.cvat_panel.connect_button.clicked.connect(self._connect_cvat)
        self.cvat_panel.refresh_button.clicked.connect(self._refresh_cvat_lists)
        self.cvat_panel.capture_button.clicked.connect(self._capture_component_photo)
        self.cvat_panel.upload_button.clicked.connect(self._upload_cvat_photos)
        self.cvat_panel.export_button.clicked.connect(self._download_cvat_export)
        self.forge_panel.connect_button.clicked.connect(self._open_forge_config_dialog)
        self.forge_panel.refresh_button.clicked.connect(self._refresh_forge_lists)
        self.forge_panel.projects.currentItemChanged.connect(lambda *_: self._on_forge_project_selected())
        self.forge_panel.cameras.currentItemChanged.connect(lambda *_: self._sync_selected_camera_assignments())
        self.forge_panel.label_selected.connect(self._suggest_targets_for_label)
        self.forge_panel.camera_labels_dropped.connect(self._on_camera_labels_dropped)
        self.forge_panel.gpio_ports.labels_dropped.connect(self._on_gpio_labels_dropped)
        self.forge_panel.create_camera_button.clicked.connect(self._create_forge_camera)
        self.forge_panel.create_line_button.clicked.connect(self._create_forge_line)
        self.forge_panel.assign_button.clicked.connect(self._assign_components_to_camera)
        self.forge_panel.send_conf_button.clicked.connect(self._send_line_conf)

    def _apply_env_settings(self, values: dict) -> None:
        forge_url = values.get("FORGE_URL") or self.forge_panel.base_url.text().strip()
        self._forge = ForgeManager(forge_url or "https://forge.iinia.ai/api/swagger/")
        if token := values.get("FORGE_TOKEN"):
            self._forge.set_token(token)
        elif values.get("FORGE_USERNAME") and values.get("FORGE_PASSWORD"):
            self._forge.set_basic_auth(values.get("FORGE_USERNAME", ""), values.get("FORGE_PASSWORD", ""))
        self.forge_panel.base_url.setText(forge_url or "")
        self.forge_panel.username.setText(values.get("FORGE_USERNAME", ""))
        self.forge_panel.password.setText(values.get("FORGE_PASSWORD", ""))
        self.forge_panel.token.setText(values.get("FORGE_TOKEN", ""))
        cvat_url = values.get("CVAT_URL") or self.cvat_panel.base_url.text().strip()
        self._cvat = CvatManager(cvat_url or "https://app.cvat.ai")
        if token := values.get("CVAT_TOKEN"):
            self._cvat.set_token(token)
        elif values.get("CVAT_USERNAME") and values.get("CVAT_PASSWORD"):
            self._cvat.set_basic_auth(values.get("CVAT_USERNAME", ""), values.get("CVAT_PASSWORD", ""))
        self.cvat_panel.set_values(
            base_url=cvat_url,
            username=values.get("CVAT_USERNAME"),
            password=values.get("CVAT_PASSWORD"),
            token=values.get("CVAT_TOKEN"),
        )
        self.cvat_panel.set_status("Configuración cargada desde .env")
        self.forge_panel.set_status("Configuración Forge cargada desde .env")
        theme = str(values.get("UI_THEME", "dark")).strip().lower()
        self.dark_mode_switch.setChecked(theme != "light")
        self._set_status("Configuration loaded from .env")
        self._append_log("Configuration loaded from .env")
        self._apply_dark_theme(self.dark_mode_switch.isChecked())

    def _open_settings_dialog(self) -> None:
        dialog = SettingsDialog(env_path=self.settings_panel.env_file.text().strip() or ".env", parent=self)
        dialog.panel.env_changed.connect(self._apply_env_settings)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.settings_panel.load_env()

    def _load_local_assignments(self) -> dict[str, list[str]]:
        path = Path("configs/forge_camera_assignments.json")
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                assignments: dict[str, list[str]] = {}
                dirty = False
                for key, value in payload.items():
                    raw_values: list[object] = []
                    if isinstance(value, list):
                        raw_values = list(value)
                    elif isinstance(value, dict):
                        raw_values = list(value.keys())
                    else:
                        dirty = True
                        continue
                    labels = self._normalize_label_list(raw_values)
                    if labels:
                        assignments[str(key)] = labels
                    raw_labels = [str(label).strip() for label in raw_values if str(label).strip()]
                    if labels != raw_labels:
                        dirty = True
                if dirty:
                    try:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text(json.dumps(assignments, indent=2, ensure_ascii=False), encoding="utf-8")
                    except Exception:
                        pass
                return assignments
        except Exception:
            return {}
        return {}

    def _save_local_assignments(self) -> None:
        path = Path("configs/forge_camera_assignments.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._camera_assignments, indent=2, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _normalize_label_name(raw: object) -> str | None:
        if isinstance(raw, dict):
            name = raw.get("name")
            if name is None:
                return None
            text = str(name).strip()
            return text or None

        text = str(raw).strip()
        if not text:
            return None
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

    @classmethod
    def _normalize_label_list(cls, values: list[object]) -> list[str]:
        normalized: list[str] = []
        for raw in values:
            label = cls._normalize_label_name(raw)
            if label:
                normalized.append(label)
        return list(dict.fromkeys(normalized))

    def _load_gpio_assignments(self) -> dict[str, dict[str, str]]:
        path = Path("configs/forge_gpio_assignments.json")
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                assignments: dict[str, dict[str, str]] = {}
                dirty = False
                for project_id, value in payload.items():
                    if not isinstance(value, dict):
                        dirty = True
                        continue
                    cleaned: dict[str, str] = {}
                    for raw_label, raw_port in value.items():
                        label = self._normalize_label_name(raw_label)
                        port = str(raw_port).strip()
                        if not label or not port:
                            dirty = True
                            continue
                        cleaned[label] = port
                    raw_labels = [str(label).strip() for label in value.keys() if str(label).strip()]
                    if list(cleaned.keys()) != raw_labels:
                        dirty = True
                    if cleaned:
                        assignments[str(project_id)] = cleaned
                if dirty:
                    try:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text(json.dumps(assignments, indent=2, ensure_ascii=False), encoding="utf-8")
                    except Exception:
                        pass
                return assignments
        except Exception:
            return {}
        return {}

    def _save_gpio_assignments(self) -> None:
        path = Path("configs/forge_gpio_assignments.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._gpio_assignments, indent=2, ensure_ascii=False), encoding="utf-8")

    def _bootstrap_from_env(self) -> None:
        if self.forge_panel.username.text().strip() or self.forge_panel.token.text().strip():
            self._refresh_forge_lists()

    def _set_status(self, text: str) -> None:
        self.status_banner.setText(text)

    def _apply_dark_theme(self, enabled: bool) -> None:
        app = QApplication.instance()
        if app is None:
            return
        if enabled:
            app.setStyleSheet(
                """
                QMainWindow, QWidget { background: #0f1115; color: #e6eaf2; }
                QLabel { color: #e6eaf2; }
                QLineEdit, QTextEdit, QPlainTextEdit, QListWidget, QComboBox {
                    background: #171a21; color: #e6eaf2; border: 1px solid #2a313a; border-radius: 6px; padding: 6px;
                }
                QPushButton {
                    background: #1f2430; color: #e6eaf2; border: 1px solid #2a313a; border-radius: 6px; padding: 6px 10px;
                }
                QPushButton:hover { background: #272d3a; }
                QTabWidget::pane { border: 1px solid #2a313a; }
                QTabBar::tab { background: #1a1f28; color: #cfd6e1; padding: 8px 12px; }
                QTabBar::tab:selected { background: #232a36; }
                """
            )
        else:
            app.setStyleSheet("")

    def _run_async(self, fn, *, on_ok=None, on_error=None, busy_text: str | None = None) -> None:
        worker = AsyncWorker(fn, self)
        self._workers.append(worker)
        if busy_text:
            self._set_status(busy_text)

        def cleanup() -> None:
            if worker in self._workers:
                self._workers.remove(worker)
            worker.deleteLater()

        def ok(value: object) -> None:
            if on_ok:
                try:
                    on_ok(value)
                except Exception as exc:  # pragma: no cover - async callback guard
                    self._report_error("Async success callback error", exc)

        def fail(message: str) -> None:
            if on_error:
                try:
                    on_error(message)
                except Exception as exc:  # pragma: no cover - async callback guard
                    self._report_error("Async error callback error", exc)

        worker.finished_ok.connect(ok)
        worker.failed.connect(fail)
        worker.finished.connect(cleanup)
        worker.start()

    def _component_capture_path(self) -> Path:
        capture_root = Path(self.settings_panel.capture_dir.text().strip() or "captures")
        capture_root.mkdir(parents=True, exist_ok=True)
        return capture_root / f"component_{int(time.time())}.png"

    def _capture_component_photo(self) -> None:
        def _capture() -> None:
            path = self._component_capture_path()
            image: QImage = self.video_widget.grabFramebuffer()
            if not image.save(str(path)):
                raise RuntimeError(f"Could not save image to {path}")
            self._append_log(f"Component photo saved: {path}")
            self._set_status(f"Photo saved: {path.name}")

        self._safe_ui_call(_capture, context="Capture photo error")

    def _selected_task_id(self) -> int | None:
        raw = self.cvat_panel.task_id.text().strip()
        return int(raw) if raw.isdigit() else None

    def _selected_project_id(self) -> int | None:
        raw = self.cvat_panel.project_id.text().strip()
        return int(raw) if raw.isdigit() else None

    def _connect_cvat(self) -> None:
        base_url = self.cvat_panel.base_url.text().strip()
        token = self.cvat_panel.token.text().strip()
        username = self.cvat_panel.username.text().strip()
        password = self.cvat_panel.password.text().strip()
        self._run_async(
            lambda: self._connect_cvat_sync(base_url, token, username, password),
            on_ok=self._on_cvat_connected,
            on_error=lambda err: self._report_error("CVAT connect error", RuntimeError(err)),
            busy_text="Connecting to CVAT...",
        )

    def _connect_cvat_sync(self, base_url: str, token: str, username: str, password: str) -> str:
        self._cvat = CvatManager(base_url or "https://app.cvat.ai")
        if token:
            self._cvat.set_token(token)
            return "token"
        if username and password:
            self._cvat.login(username, password)
            return "login"
        return "url"

    def _on_cvat_connected(self, mode: object) -> None:
        status = {
            "token": "CVAT token configured",
            "login": "CVAT authenticated",
            "url": "CVAT URL configured",
        }.get(str(mode), "CVAT ready")
        self.cvat_panel.set_status(status)
        self._set_status(status)
        self._append_log(status)

    def _refresh_cvat_lists(self) -> None:
        task_id = self._selected_task_id()
        self._run_async(
            lambda: {
                "projects": self._cvat.list_projects(),
                "jobs": self._cvat.list_jobs(task_id=task_id),
            },
            on_ok=self._populate_cvat_lists,
            on_error=lambda err: self._report_error("CVAT refresh error", RuntimeError(err)),
            busy_text="Refreshing CVAT lists...",
        )

    def _populate_cvat_lists(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        self.cvat_panel.projects.clear()
        self.cvat_panel.jobs.clear()
        for project in payload.get("projects", []):
            self.cvat_panel.projects.addItem(f"{project.id}: {project.name}")
        for job in payload.get("jobs", []):
            self.cvat_panel.jobs.addItem(f"{job.id}: {job.name} (task {job.task_id})")
        self.cvat_panel.set_status("Projects and jobs refreshed")
        self._set_status("CVAT data refreshed")
        self._append_log("CVAT projects and jobs refreshed.")

    def _upload_cvat_photos(self) -> None:
        task_id = self._selected_task_id()
        if task_id is None:
            self._append_log("Set a valid Task ID before uploading photos.")
            return
        capture_root = Path(self.settings_panel.capture_dir.text().strip() or "captures")
        image_paths = sorted(capture_root.glob("*.png"))[-10:]
        if not image_paths:
            self._append_log("No component photos found to upload.")
            return
        self._run_async(
            lambda: self._cvat.upload_images_to_task(task_id, image_paths),
            on_ok=lambda _: self._append_log(f"Uploaded {len(image_paths)} photos to CVAT task {task_id}."),
            on_error=lambda err: self._report_error("CVAT upload error", RuntimeError(err)),
            busy_text=f"Uploading {len(image_paths)} photos...",
        )

    def _download_cvat_export(self) -> None:
        export_format = self.cvat_panel.export_format.currentText()
        out_dir = Path(self.settings_panel.model_dir.text().strip() or "models") / "cvat"
        project_id = self._selected_project_id()
        task_id = self._selected_task_id()
        self._run_async(
            lambda: self._cvat.download_export_to_dir(
                project_id=project_id,
                task_id=None if project_id is not None else task_id,
                export_format=export_format,
                out_dir=out_dir,
            ),
            on_ok=lambda path: self._append_log(f"CVAT export downloaded: {path}"),
            on_error=lambda err: self._report_error("CVAT export error", RuntimeError(err)),
            busy_text="Downloading CVAT export...",
        )

    def _connect_forge(self) -> None:
        base_url = self.forge_panel.base_url.text().strip()
        username = self.forge_panel.username.text().strip()
        password = self.forge_panel.password.text().strip()
        token = self.forge_panel.token.text().strip()
        self._run_async(
            lambda: self._connect_forge_sync(base_url, username, password, token),
            on_ok=lambda _: self._on_forge_connected(),
            on_error=lambda err: self._report_error("Forge connect error", RuntimeError(err)),
            busy_text="Connecting to Forge...",
        )

    def _open_forge_config_dialog(self) -> None:
        dialog = ForgeConfigDialog(
            base_url=self.forge_panel.base_url.text().strip(),
            username=self.forge_panel.username.text().strip(),
            password=self.forge_panel.password.text().strip(),
            token=self.forge_panel.token.text().strip(),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        self.forge_panel.set_connection_values(
            base_url=values["base_url"],
            username=values["username"],
            password=values["password"],
            token=values["token"],
        )
        self._connect_forge()

    def _connect_forge_sync(self, base_url: str, username: str, password: str, token: str) -> str:
        self._forge = ForgeManager(base_url or "https://forge.iinia.ai/api/swagger/")
        if token:
            self._forge.set_token(token)
            return "token"
        if username and password:
            self._forge.set_basic_auth(username, password)
            return "basic"
        return "url"

    def _on_forge_connected(self) -> None:
        self.forge_panel.set_status("Forge ready")
        self._set_status("Forge ready")
        self._append_log("Forge connection ready.")

    def _refresh_forge_lists(self) -> None:
        self._run_async(
            lambda: {
                "projects": self._forge.list_projects(),
                "cameras": self._forge.list_cameras(),
                "lines": self._forge.list_lines(),
            },
            on_ok=self._populate_forge_lists,
            on_error=lambda err: self._report_error("Forge refresh error", RuntimeError(err)),
            busy_text="Refreshing Forge data...",
        )

    def _populate_forge_lists(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        projects = payload.get("projects", [])
        cameras = payload.get("cameras", [])
        lines = payload.get("lines", [])
        self.forge_panel.set_projects([(p.id, p.name) for p in projects])
        self.forge_panel.set_cameras([(c.id, c.name, c.components) for c in cameras])
        self.forge_panel.set_lines([(l.id, l.name) for l in lines])
        self.forge_panel.set_status("Forge lists refreshed")
        self._set_status("Forge data refreshed")
        if self.forge_panel.projects.count() and self.forge_panel.projects.currentRow() < 0:
            self.forge_panel.projects.setCurrentRow(0)
        self._on_forge_project_selected()
        self._sync_selected_camera_assignments()

    def _refresh_forge_project_details(self) -> None:
        project_id = self.forge_panel.selected_project_id()
        if project_id is None:
            return
        self._run_async(
            lambda: {
                "labels": self._forge.project_labels_preview(project_id),
                "stats": self._forge.project_label_stats(project_id),
                "preview": self._forge.get_project(project_id),
            },
            on_ok=self._populate_forge_project_details,
            on_error=lambda err: self._report_error("Forge project error", RuntimeError(err)),
            busy_text=f"Loading project {project_id} details...",
        )

    def _camera_assignment_key(self) -> str | None:
        camera_id = self.forge_panel.selected_camera_id()
        return str(camera_id) if camera_id is not None else None

    def _current_camera_assignments(self) -> list[str]:
        key = self._camera_assignment_key()
        if key is None:
            return []
        return list(self._camera_assignments.get(key, []))

    def _current_gpio_assignments(self) -> dict[str, str]:
        project_id = self.forge_panel.selected_project_id()
        if project_id is None:
            return {}
        return dict(self._gpio_assignments.get(str(project_id), {}))

    def _on_forge_project_selected(self) -> None:
        self._refresh_forge_project_details()
        self._sync_selected_camera_assignments()

    def _sync_selected_camera_assignments(self) -> None:
        assignments = self._current_camera_assignments()
        self.forge_panel.set_assigned(assignments)
        self.forge_panel.set_gpio_assignments(self._current_gpio_assignments())
        self._gpio_worker.set_assignments(self._current_gpio_assignments())

    def _on_gpio_labels_dropped(self, port: str, labels: list[str]) -> None:
        project_id = self.forge_panel.selected_project_id()
        if project_id is None:
            self._append_log("Select a project first.")
            return
        cleaned_labels = [label for label in (self._normalize_label_name(raw) for raw in labels) if label]
        if not cleaned_labels:
            return
        key = str(project_id)
        current = dict(self._gpio_assignments.get(key, {}))
        for label in cleaned_labels:
            current[label] = port
        self._gpio_assignments[key] = current
        self._save_gpio_assignments()
        self.forge_panel.set_gpio_assignments(current)
        self._gpio_worker.set_assignments(current)
        self._append_log(f"Assigned {len(cleaned_labels)} labels to {port}.")

    def _on_camera_labels_dropped(self, camera_id: int, labels: list[str]) -> None:
        key = str(camera_id)
        current = list(self._camera_assignments.get(key, []))
        cleaned_labels = [label for label in (self._normalize_label_name(raw) for raw in labels) if label]
        if not cleaned_labels:
            return
        for label in cleaned_labels:
            if label not in current:
                current.append(label)
        self._camera_assignments[key] = current
        self._save_local_assignments()
        self._append_log(f"Camera {camera_id}: assigned {len(cleaned_labels)} labels via drag & drop.")
        self._run_async(
            lambda: self._forge.update_camera(camera_id, {"labels": current, "assigned_components": current, "components": current}),
            on_ok=lambda _: (self._append_log(f"Camera {camera_id} updated from drag & drop."), self._refresh_forge_lists()),
            on_error=lambda err: self._report_error("Camera drag-drop update failed", RuntimeError(err)),
            busy_text=f"Updating camera {camera_id}...",
        )

    def _suggest_targets_for_label(self, item: dict) -> None:
        label_name = str(item.get("name", "")).strip()
        if not label_name:
            return

        for i in range(self.forge_panel.cameras.count()):
            camera_item = self.forge_panel.cameras.item(i)
            camera_id = camera_item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(camera_id, int):
                continue
            if label_name in self._camera_assignments.get(str(camera_id), []):
                self.forge_panel.cameras.setCurrentItem(camera_item)
                break

        project_id = self.forge_panel.selected_project_id()
        if project_id is None:
            return

        gpio_map = self._gpio_assignments.get(str(project_id), {})
        port = gpio_map.get(label_name)
        if port:
            self.forge_panel.gpio_port.setCurrentText(port)
            self._gpio_worker.set_assignments(gpio_map)

    def _populate_forge_project_details(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        labels = payload.get("labels", [])
        stats = payload.get("stats", {})
        preview = payload.get("preview", {})
        self.forge_panel.set_labels(labels if isinstance(labels, list) else [])
        if self.forge_panel.labels.count() and self.forge_panel.labels.currentRow() < 0:
            self.forge_panel.labels.setCurrentRow(0)
        label_display: list[str] = []
        if isinstance(labels, list):
            for item in labels:
                if isinstance(item, dict):
                    name = str(item.get("name", "")).strip()
                    color = str(item.get("color", "")).strip()
                    if name:
                        label_display.append(f"{name} ({color})" if color else name)
                else:
                    text = str(item).strip()
                    if text:
                        label_display.append(text)
        self.forge_panel.set_label_previews(labels if isinstance(labels, list) else [])
        self.forge_panel.set_summary(
            "\n".join(
                [
                    f"Labels: {', '.join(label_display) if label_display else 'none'}",
                    f"Stats: {json.dumps(stats, ensure_ascii=False)[:500]}",
                    f"Preview: {json.dumps(preview, ensure_ascii=False)[:500]}",
                ]
            )
        )

    def _selected_forge_labels(self) -> list[str]:
        labels = self.forge_panel.selected_labels()
        if labels:
            return labels
        text = self.forge_panel.component_filter.text().strip()
        if text:
            return [item.strip() for item in text.split(",") if item.strip()]
        return []

    def _create_forge_camera(self) -> None:
        line_options = self.forge_panel.line_options()
        if not line_options:
            self._append_log("No Forge lines loaded. Refresh Forge first.")
            return
        line_id = self.forge_panel.selected_line_id() or (line_options[0][0] if line_options else None)
        dialog = CameraCreateDialog(line_options=line_options, selected_line_id=line_id, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        if not values["device_ip"]:
            self._append_log("Device IP is required.")
            return
        if not values["protocol"]:
            self._append_log("Protocol is required.")
            return
        if not values["line"]:
            self._append_log("Select a Forge line first.")
            return
        components = self._selected_forge_labels()
        payload = {
            "number": values["number"],
            "status": values["status"],
            "device_ip": values["device_ip"],
            "protocol": values["protocol"],
            "line": values["line"],
            "labels": components,
            "assigned_components": components,
            "components": components,
        }
        self._run_async(
            lambda: self._forge.create_camera(payload),
            on_ok=lambda _: self._append_log(f"Camera created on line {values['line']} with device {values['device_ip']}"),
            on_error=lambda err: self._report_error("Forge camera error", RuntimeError(err)),
            busy_text="Creating camera...",
        )

    def _create_forge_line(self) -> None:
        name = self.forge_panel.line_name.text().strip()
        if not name:
            self._append_log("Line name is required.")
            return
        project_id = self.forge_panel.selected_project_id()
        payload = {"name": name, "project_id": project_id}
        self._run_async(
            lambda: self._forge.create_line(payload),
            on_ok=lambda _: self._append_log(f"Line created: {name}"),
            on_error=lambda err: self._report_error("Forge line error", RuntimeError(err)),
            busy_text=f"Creating line {name}...",
        )

    def _assign_components_to_camera(self) -> None:
        camera_id = self.forge_panel.selected_camera_id()
        if camera_id is None:
            self._append_log("Select a camera first.")
            return
        labels = self._selected_forge_labels()
        if not labels:
            self._append_log("Select or type labels to assign.")
            return

        port = self.forge_panel.selected_gpio_port()
        if not port:
            self._append_log("Select a GPIO port first.")
            return

        project_id = self.forge_panel.selected_project_id()
        if project_id is None:
            self._append_log("Select a project first.")
            return
        key = str(project_id)
        current = dict(self._gpio_assignments.get(key, {}))
        for label in labels:
            current[label] = port
        self._gpio_assignments[key] = current
        self._save_gpio_assignments()
        self.forge_panel.set_gpio_assignments(current)
        self._gpio_worker.set_assignments(current)

        payload = {"gpio_assignments": current, "labels": labels, "gpio_port": port}
        self._run_async(
            lambda: self._forge.update_camera(camera_id, payload),
            on_ok=lambda _: self._append_log(f"Assigned {len(labels)} labels to {port}."),
            on_error=lambda err: self._report_error("GPIO assignment update failed", RuntimeError(err)),
            busy_text=f"Assigning labels to {port}...",
        )

    def _send_line_conf(self) -> None:
        line_id = self.forge_panel.selected_line_id()
        if line_id is None:
            self._append_log("Select a line first.")
            return
        payload = {"gpio_assignments": self._gpio_assignments, "camera_assignments": self._camera_assignments}
        self._run_async(
            lambda: self._forge.send_conf(line_id, payload),
            on_ok=lambda _: self._append_log(f"Configuration sent to line {line_id}."),
            on_error=lambda err: self._report_error("Forge send_conf error", RuntimeError(err)),
            busy_text=f"Sending configuration to line {line_id}...",
        )

    def _wire_threads(self) -> None:
        self._inference_worker.frame_ready.connect(self.video_widget.set_frame)
        self._inference_worker.telemetry_ready.connect(self._update_telemetry)
        self._inference_worker.log_message.connect(self._append_log)
        self._inference_worker.detection_event.connect(self._gpio_worker.enqueue_detection)
        self._inference_worker.model_loaded.connect(lambda model: self._set_status(f"Model: {model}"))
        self._inference_worker.frozen.connect(lambda: self._report_error("Inference frozen", RuntimeError("watchdog will restart worker")))
        self._gpio_worker.log_message.connect(self._append_log)
        self._watchdog.log_message.connect(self._append_log)
        self._watchdog.restart_requested.connect(self._restart_inference)

    def _start_threads(self) -> None:
        self._append_log(f"Selected backend: {self._hardware.info.camera_backend} / {self._hardware.info.gpio_backend}")
        self._append_log(f"Recommended model format: {self._hardware.info.recommended_model_format}")
        self._gpio_worker.start()
        self._inference_worker.start()
        self._watchdog.start()

    def _append_log(self, message: str) -> None:
        self.console.appendPlainText(message)
        self.statusBar().showMessage(message, 5000)

    def _update_telemetry(self, telemetry: dict) -> None:
        self.fps_capture.setText(f"{telemetry.get('capture_fps', 0.0):.1f}")
        self.fps_inference.setText(f"{telemetry.get('inference_fps', 0.0):.1f}")
        self.latency.setText(f"{telemetry.get('latency_ms', 0.0):.1f} ms")
        self.ram.setText(f"{telemetry.get('ram_mb', 0.0):.0f} MB")
        self.vram.setText(f"{telemetry.get('vram_mb', 0.0):.0f} MB")
        self.temperature.setText(f"{telemetry.get('soc_temp_c', 0.0):.1f} °C")
        self.health_bar.setValue(min(100, max(0, 100 - int(telemetry.get('latency_ms', 0.0)))))

    def _restart_inference(self) -> None:
        self._append_log("Restarting inference worker...")
        self._watchdog.request_stop()
        if self._inference_worker.isRunning():
            self._inference_worker.request_stop()
            self._inference_worker.wait(2000)
        self._watchdog.wait(1000)
        self._inference_worker = InferenceWorker(None, self._hardware, self)
        self._watchdog = Watchdog(self._inference_worker, parent=self)
        self._wire_threads()
        self._watchdog.start()
        self._inference_worker.start()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._watchdog.request_stop()
        self._gpio_worker.request_stop()
        self._inference_worker.request_stop()
        self._watchdog.wait(1000)
        self._gpio_worker.wait(1000)
        self._inference_worker.wait(1000)
        super().closeEvent(event)


def main() -> int:
    parser = argparse.ArgumentParser(description="EdgeVision Control Hub")
    parser.add_argument("--headless", action="store_true", help="Run without opening the Qt UI")
    args = parser.parse_args()

    if args.headless:
        return run_headless()

    app = QApplication([])
    app.setFont(QFont("Inter", 10))
    hardware = HardwareManager()
    window = MainWindow(hardware)
    window.show()
    return app.exec()


def run_headless() -> int:
    env = read_env_file(Path(".env"))
    hardware = HardwareManager()
    print("EdgeVision Control Hub headless mode")
    print(f"Hardware: {hardware.info.name}")
    print(f"Recommended model format: {hardware.info.recommended_model_format}")
    print(f"Forge URL: {env.get('FORGE_URL', '')}")
    print(f"CVAT URL: {env.get('CVAT_URL', 'https://app.cvat.ai')}")
    for i in range(3):
        print(f"Cycle {i + 1}: capture -> inference -> gpio dispatch")
        time.sleep(0.2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
