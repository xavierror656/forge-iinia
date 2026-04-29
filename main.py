"""EdgeVision Control Hub bootstrap.

This is the initial executable scaffold for the application:
UI thread, inference thread, GPIO/signals thread, and watchdog orchestration.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import random
import traceback
import queue
import time
from threading import Lock
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

import cv2
from PyQt6.QtCore import QObject, QPoint, QRectF, QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from cvat.cvat_manager import CvatManager
from core.async_worker import AsyncWorker
from core.config_io import ConfigBundle, filter_known_labels, read_path, write_path
from core.env_config import read_env_file
from core.hardware_manager import HardwareManager
from core.forge_manager import ForgeManager
from core.undo import AssignmentHistory, Snapshot
from core.validator import summarize as summarize_warnings, validate as validate_assignments
from core.video_source import (
    VIDEO_SOURCE_PATH,
    InferenceSourceConfig,
    VideoSourceChoice,
    capture_backend_for,
    load_inference_source_config,
    resolve_video_source_candidates,
    save_inference_source_config,
)
from ui.auto_assign import AutoAssignDialog, TARGET_CAMERA, TARGET_GPIO
from ui.cheatsheet import ShortcutsDialog
from ui.command_palette import CommandPalette, PaletteItem
from ui.connection_indicator import ConnectionIndicator
from ui.cvat_panel import CvatPanel
from ui.detection_overlay import DetectionHistogram
from ui.forge_panel import CameraCreateDialog, ForgeConfigDialog, ForgePanel
from ui.gpio_leds import GPIOLedStrip
from ui.settings_panel import SettingsDialog, SettingsPanel
from ui.sparkline import Sparkline
from ui.toast import ToastManager


BRAND_LOGO_PATH = Path(__file__).resolve().parent / "ui" / "iinia_logo.webp"


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
    """Low-overhead display widget for the camera stream with detection overlay."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image: QImage | None = None
        self._status_text = "Esperando stream..."
        self._detections: list[dict] = []
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

    def set_detections(self, detections: list[dict]) -> None:
        self._detections = list(detections)
        self.update()

    def paintGL(self) -> None:  # noqa: N802
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
            painter.fillRect(QRectF(12, 12, max(220, painter.fontMetrics().horizontalAdvance(self._status_text) + 20), 26), QColor(0, 0, 0, 150))
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


class InferenceWorker(QThread):
    source_ready = pyqtSignal(dict)
    frame_ready = pyqtSignal(object)
    telemetry_ready = pyqtSignal(dict)
    log_message = pyqtSignal(str)
    detection_event = pyqtSignal(str, bool)
    detections_payload = pyqtSignal(list)
    model_loaded = pyqtSignal(str)
    frozen = pyqtSignal()

    def __init__(
        self,
        model_path: str | None,
        hardware: HardwareManager,
        parent: QObject | None = None,
        *,
        source_config: InferenceSourceConfig | None = None,
    ) -> None:
        super().__init__(parent)
        self._hardware = hardware
        self._model_path = Path(model_path) if model_path else None
        self._source_config = replace(source_config or InferenceSourceConfig())
        self._stop_requested = False
        self._last_heartbeat = time.monotonic()
        self._last_model_mtime = 0.0
        self._known_labels: list[dict] = []
        self._known_lock = Lock()
        self._states: dict[str, DetectionState] = {}
        self._rng = random.Random(13)
        self._capture: cv2.VideoCapture | None = None
        self._active_choice: VideoSourceChoice | None = None
        self._discovered_sources: list[VideoSourceChoice] = []
        self._source_status = "Esperando stream..."
        self._last_source_signature: tuple[Any, ...] | None = None
        self._read_failures = 0

    def set_known_labels(self, labels: list[dict]) -> None:
        with self._known_lock:
            self._known_labels = list(labels)
            valid = {label.get("name") for label in labels if isinstance(label, dict)}
            self._states = {name: self._states.get(name, DetectionState(label=name, threshold=3))
                            for name in valid if name}

    def set_source_config(self, config: InferenceSourceConfig) -> None:
        self._source_config = replace(config)
        self._capture = None
        self._active_choice = None
        self._read_failures = 0
        self._source_status = "Esperando stream..."
        self._last_source_signature = None

    @staticmethod
    def _color_for_label(label: str) -> str:
        palette = ["#62d2a2", "#5aa9e6", "#f4b942", "#e66b6b", "#b57ff5", "#7ad3c8"]
        if not label:
            return palette[0]
        return palette[sum(ord(ch) for ch in label) % len(palette)]

    def _frame_to_qimage(self, frame: Any) -> QImage | None:
        if frame is None:
            return None
        try:
            if len(frame.shape) == 2:
                rgb = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
            elif frame.shape[2] == 4:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGRA2RGBA)
            else:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        except Exception:
            return None
        height, width = rgb.shape[:2]
        bytes_per_line = rgb.strides[0]
        return QImage(rgb.data, width, height, bytes_per_line, QImage.Format.Format_RGB888 if rgb.shape[2] == 3 else QImage.Format.Format_RGBA8888).copy()

    def _simulate_detections(self) -> list[dict]:
        with self._known_lock:
            labels = [str(label.get("name", "")).strip() for label in self._known_labels if isinstance(label, dict) and str(label.get("name", "")).strip()]

        if not labels:
            labels = ["person", "vehicle", "package"]

        count = self._rng.randint(1, min(3, len(labels)))
        selected = labels[:count] if len(labels) <= count else self._rng.sample(labels, count)
        detections: list[dict] = []
        for name in selected:
            x1 = self._rng.uniform(0.05, 0.7)
            y1 = self._rng.uniform(0.05, 0.7)
            w = self._rng.uniform(0.15, 0.25)
            h = self._rng.uniform(0.15, 0.25)
            x2 = min(0.98, x1 + w)
            y2 = min(0.98, y1 + h)
            detections.append(
                {
                    "label": name,
                    "confidence": round(self._rng.uniform(0.62, 0.97), 2),
                    "bbox": (x1, y1, x2, y2),
                    "color": self._color_for_label(name),
                }
            )
        return detections

    def _open_capture(self, choice: VideoSourceChoice) -> cv2.VideoCapture | None:
        backend = capture_backend_for(choice)
        source: Any = choice.source
        if choice.kind == "rtsp" or str(source).startswith("rtsp://"):
            backend = cv2.CAP_FFMPEG
        elif backend in {cv2.CAP_V4L2, cv2.CAP_ANY}:
            match = re.match(r"^(?:/dev/video)?(\d+)$", str(source).strip())
            if match:
                source = int(match.group(1))

        capture = cv2.VideoCapture(source, backend)
        if not capture.isOpened():
            capture.release()
            return None
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return capture

    @staticmethod
    def _source_signature(choice: VideoSourceChoice | None, discovered: list[VideoSourceChoice], active: bool) -> tuple[Any, ...]:
        return (
            choice.kind if choice else "simulation",
            choice.source if choice else "",
            choice.label if choice else "",
            choice.backend if choice else "",
            active,
            tuple((item.source, item.available) for item in discovered),
        )

    def _emit_source_state(self, choice: VideoSourceChoice | None, *, active: bool, discovered: list[VideoSourceChoice]) -> bool:
        signature = self._source_signature(choice, discovered, active)
        if signature == self._last_source_signature:
            return False
        self._last_source_signature = signature
        payload = {
            "mode": self._source_config.mode,
            "active": active,
            "simulation": not active,
            "kind": choice.kind if choice else "simulation",
            "label": choice.label if choice else "Sin fuente de video",
            "source": choice.source if choice else "",
            "backend": choice.backend if choice else "",
            "status": self._source_status,
            "discovered_sources": [item.as_dict() for item in discovered],
        }
        self.source_ready.emit(payload)
        return True

    def _ensure_capture(self) -> None:
        if self._capture is not None:
            return

        candidates, discovered = resolve_video_source_candidates(self._source_config, self._hardware)
        self._discovered_sources = discovered

        chosen: VideoSourceChoice | None = None
        capture: cv2.VideoCapture | None = None
        for candidate in candidates:
            capture = self._open_capture(candidate)
            if capture is not None:
                chosen = candidate
                break

        if capture is None and self._source_config.mode == "rtsp":
            fallback = replace(self._source_config, mode="auto")
            fallback_candidates, discovered = resolve_video_source_candidates(fallback, self._hardware)
            self._discovered_sources = discovered
            for candidate in fallback_candidates:
                capture = self._open_capture(candidate)
                if capture is not None:
                    chosen = candidate
                    self.log_message.emit("RTSP no disponible, usando cámara local.")
                    break

        self._capture = capture
        self._active_choice = chosen
        self._read_failures = 0
        self._source_status = f"{chosen.kind.upper()} · {chosen.label}" if chosen else "Esperando stream..."
        emitted = self._emit_source_state(chosen, active=bool(capture), discovered=self._discovered_sources)
        if emitted and chosen:
            self.log_message.emit(f"Video source opened: {chosen.label}")
        elif emitted and candidates:
            self.log_message.emit("Video source unavailable, using simulated preview.")

    def _release_capture(self) -> None:
        if self._capture is not None:
            self._capture.release()
        self._capture = None

    def _update_detection_states(self, detections: list[dict]) -> None:
        seen_names: set[str] = set()
        for det in detections:
            name = str(det.get("label", "")).strip()
            if not name:
                continue
            seen_names.add(name)
            state = self._states.get(name)
            if state and state.register(True):
                self.detection_event.emit(name, True)
        for name, state in list(self._states.items()):
            if name not in seen_names:
                state.register(False)

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
        self._last_heartbeat = time.monotonic()
        self._maybe_hot_reload()

        if self._capture is None:
            self._ensure_capture()

        start = time.perf_counter()
        image: QImage | None = None
        frame_size: tuple[int, int] | None = None
        simulation = self._capture is None

        if self._capture is not None:
            ok, frame = self._capture.read()
            if ok and frame is not None:
                image = self._frame_to_qimage(frame)
                if image is not None:
                    frame_size = (int(frame.shape[1]), int(frame.shape[0]))
                self._read_failures = 0
                simulation = False
            else:
                self._read_failures += 1
                if self._read_failures >= 3:
                    self.log_message.emit("Video source lost. Retrying...")
                    self._release_capture()
                    self._read_failures = 0
                    self._source_status = "Esperando stream..."
                    self._emit_source_state(None, active=False, discovered=self._discovered_sources)
                simulation = True

        detections = self._simulate_detections()
        self.detections_payload.emit(detections)
        self._update_detection_states(detections)

        frame = {
            "timestamp": self._last_heartbeat,
            "provider": self._hardware.info.name,
            "simulation": simulation,
            "detections": detections,
            "image": image,
            "frame_size": frame_size,
            "status": self._source_status,
            "source": self._active_choice.source if self._active_choice else "",
            "source_label": self._active_choice.label if self._active_choice else self._source_status,
        }
        self.frame_ready.emit(frame)

        elapsed_ms = (time.perf_counter() - start) * 1000.0
        fps = 1.0 / max(0.001, time.perf_counter() - start)
        telemetry = TelemetrySnapshot(
            capture_fps=fps,
            inference_fps=fps,
            latency_ms=elapsed_ms,
            ram_mb=256.0,
            vram_mb=128.0 if self._hardware.supports_tensor_rt() else 0.0,
            soc_temp_c=0.0,
            provider_name=self._hardware.info.name,
        )
        self.telemetry_ready.emit(asdict(telemetry))

    def run(self) -> None:
        self._load_model()
        try:
            while not self._stop_requested:
                try:
                    self._run_inference_step()
                    self.msleep(33 if self._capture is not None else 500)
                except Exception as exc:  # pragma: no cover - defensive scaffold
                    self.log_message.emit(f"Inference error: {exc}")
                    self.frozen.emit()
                    self.msleep(500)
        finally:
            self._release_capture()


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
        self._video_source_config = load_inference_source_config(VIDEO_SOURCE_PATH)
        self._known_labels: list[dict] = []
        self._latest_source_state: dict[str, Any] = {}
        self._latest_telemetry: dict[str, Any] = {}
        self._inference_worker = self._create_inference_worker()
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

    def _create_inference_worker(self) -> InferenceWorker:
        worker = InferenceWorker(None, self._hardware, self, source_config=self._video_source_config)
        if self._known_labels:
            worker.set_known_labels(self._known_labels)
        return worker

    def _build_ui(self) -> None:
        self.setWindowTitle("EdgeVision Control Hub")
        self.resize(1400, 900)

        central = QWidget(self)
        root = QVBoxLayout(central)

        header = QHBoxLayout()
        self.brand_logo = QLabel()
        brand_pixmap = QPixmap(str(BRAND_LOGO_PATH))
        if not brand_pixmap.isNull():
            self.brand_logo.setPixmap(
                brand_pixmap.scaledToHeight(26, Qt.TransformationMode.SmoothTransformation)
            )
            self.brand_logo.setToolTip("INIIA")
        else:
            self.brand_logo.hide()
        self.hardware_label = QLabel(f"Hardware: {self._hardware.info.name}")
        self.hardware_hint = QLabel(self._hardware.info.deployment_note)
        self.simulation_switch = QCheckBox("Modo Simulación")
        self.simulation_switch.setChecked(self._hardware.is_simulation())
        self.simulation_switch.setEnabled(False)
        self.settings_button = QPushButton("Config .env")
        self.dark_mode_switch = QCheckBox("Dark mode")
        self.dark_mode_switch.setChecked(True)
        header.addWidget(self.brand_logo)
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

        live_tab = self._build_live_tab()

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
        self.forge_panel.bulk_clear_requested.connect(self._on_bulk_clear_gpio)

    def _build_live_tab(self) -> QWidget:
        live_tab = QWidget()
        outer = QVBoxLayout(live_tab)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        video_box = QWidget()
        video_layout = QVBoxLayout(video_box)
        video_layout.setContentsMargins(0, 0, 0, 0)
        video_layout.setSpacing(6)
        self.status_banner = QLabel("Ready")
        self.status_banner.setStyleSheet(
            "padding: 6px 10px; border-radius: 6px; background: #1b2028; color: #d8dde3;"
        )
        video_layout.addWidget(self.status_banner)
        self.stream_banner = QLabel("Fuente de video pendiente...")
        self.stream_banner.setWordWrap(True)
        self.stream_banner.setStyleSheet(
            "padding: 6px 10px; border-radius: 6px; background: #141820; color: #cfd6e1;"
        )
        video_layout.addWidget(self.stream_banner)
        video_layout.addWidget(self.video_widget, 1)
        self.video_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        side_box = QFrame()
        side_box.setFrameShape(QFrame.Shape.StyledPanel)
        side_box.setStyleSheet("QFrame { background:#11141a; border:1px solid #2a313a; border-radius:8px; }")
        side_layout = QVBoxLayout(side_box)
        side_layout.setContentsMargins(12, 12, 12, 12)
        side_layout.setSpacing(8)

        title = QLabel("Telemetría")
        title.setStyleSheet("font-weight:600; color:#9fb2c8;")
        side_layout.addWidget(title)

        telemetry_grid = QGridLayout()
        telemetry_grid.setHorizontalSpacing(12)
        telemetry_grid.setVerticalSpacing(6)
        self.fps_capture = QLabel("0.0")
        self.fps_inference = QLabel("0.0")
        self.latency = QLabel("0.0 ms")
        self.ram = QLabel("0 MB")
        self.vram = QLabel("0 MB")
        self.temperature = QLabel("0 °C")
        for value_label in (self.fps_capture, self.fps_inference, self.latency, self.ram, self.vram, self.temperature):
            value_label.setStyleSheet("font-weight:600; color:#e6eaf2;")
        rows = [
            ("FPS captura", self.fps_capture),
            ("FPS inferencia", self.fps_inference),
            ("Latencia", self.latency),
            ("RAM", self.ram),
            ("VRAM", self.vram),
            ("SoC", self.temperature),
        ]
        for row, (label_text, value_widget) in enumerate(rows):
            key = QLabel(label_text)
            key.setStyleSheet("color:#8b95a1;")
            telemetry_grid.addWidget(key, row, 0)
            telemetry_grid.addWidget(value_widget, row, 1)
        side_layout.addLayout(telemetry_grid)

        health_label = QLabel("Health")
        health_label.setStyleSheet("color:#8b95a1; margin-top:6px;")
        side_layout.addWidget(health_label)
        self.health_bar = QProgressBar()
        self.health_bar.setRange(0, 100)
        self.health_bar.setValue(100)
        self.health_bar.setTextVisible(False)
        self.health_bar.setFixedHeight(8)
        self.health_bar.setStyleSheet(
            "QProgressBar { background:#0f1115; border:1px solid #2a313a; border-radius:4px; }"
            "QProgressBar::chunk { background:#62d2a2; border-radius:4px; }"
        )
        side_layout.addWidget(self.health_bar)

        side_layout.addStretch(1)

        self.capture_button = QPushButton("Tomar foto")
        self.capture_button.clicked.connect(self._capture_component_photo)
        self.restart_button = QPushButton("Reiniciar inferencia")
        self.restart_button.clicked.connect(self._restart_inference)
        side_layout.addWidget(self.capture_button)
        side_layout.addWidget(self.restart_button)

        side_box.setMinimumWidth(220)
        side_box.setMaximumWidth(320)

        splitter.addWidget(video_box)
        splitter.addWidget(side_box)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([900, 260])
        self._live_splitter = splitter

        outer.addWidget(splitter)
        return live_tab

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
        dialog.panel.video_source_changed.connect(self._apply_video_source_config)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.settings_panel.load_env()

    def _apply_video_source_config(self, payload: dict) -> None:
        if not isinstance(payload, dict):
            return

        self._video_source_config = InferenceSourceConfig.from_mapping(payload)
        save_inference_source_config(VIDEO_SOURCE_PATH, self._video_source_config)
        self._set_status("Reiniciando fuente de video...")
        self._append_log("Video source configuration saved.")
        QTimer.singleShot(0, self._restart_inference)

    def _on_source_ready(self, payload: dict) -> None:
        if not isinstance(payload, dict):
            return

        self._latest_source_state = dict(payload)

        discovered = payload.get("discovered_sources")
        if isinstance(discovered, list):
            self._video_source_config.discovered_sources = [item for item in discovered if isinstance(item, dict)]

        source = str(payload.get("source", "")).strip()
        label = str(payload.get("label", "")).strip()
        kind = str(payload.get("kind", "")).strip()
        backend = str(payload.get("backend", "")).strip()
        active = bool(payload.get("active", False))

        if active and source and kind != "rtsp" and self._video_source_config.mode != "rtsp":
            self._video_source_config.camera_source = source
            self._video_source_config.camera_label = label or source
            self._video_source_config.camera_backend = backend

        self._video_source_config.last_resolved_source = source
        self._video_source_config.last_resolved_label = label or source
        self._video_source_config.last_resolved_kind = kind
        self._video_source_config.last_resolved_backend = backend
        save_inference_source_config(VIDEO_SOURCE_PATH, self._video_source_config)

        if self.settings_panel is not None:
            self.settings_panel.load_video_source()

        status = str(payload.get("status", "")).strip() or label or source or "Sin fuente de video"
        self._refresh_live_summary()
        if active:
            self._set_status(f"Video activo: {status}")
            self._append_log(f"Video source active: {status}")
        else:
            self._set_status(f"Video en simulación: {status}")
            self._append_log(f"Video source simulation: {status}")

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

    def _refresh_live_summary(self) -> None:
        if not hasattr(self, "stream_banner"):
            return

        source = self._latest_source_state
        telemetry = self._latest_telemetry
        active = bool(source.get("active", False))
        kind = str(source.get("kind", "simulation")).strip().upper() or "SIM"
        label = str(source.get("label", "")).strip() or str(source.get("source", "")).strip() or "Sin fuente"
        state = "Activa" if active else "Reintentando" if source.get("source") else "Sin señal"
        fps = float(telemetry.get("capture_fps", 0.0) or 0.0)
        latency = float(telemetry.get("latency_ms", 0.0) or 0.0)
        provider = str(telemetry.get("provider_name", self._hardware.info.name)).strip()
        text = f"{state} · {kind} · {label} · {fps:.1f} FPS · {latency:.0f} ms · {provider}"
        self.stream_banner.setText(text)
        self.video_widget.set_status(text)

        if active:
            bg = "#163122" if kind != "RTSP" else "#1d2f4a"
            fg = "#eaf7ef" if kind != "RTSP" else "#e7f0ff"
            border = "#2f6b52" if kind != "RTSP" else "#45678d"
        elif source.get("source"):
            bg = "#3a3017"
            fg = "#f6e7bf"
            border = "#7a6124"
        else:
            bg = "#341d22"
            fg = "#f7d7de"
            border = "#7b3945"
        self.stream_banner.setStyleSheet(
            f"padding: 6px 10px; border-radius: 6px; background: {bg}; color: {fg}; border: 1px solid {border};"
        )

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
        self._camera_name_by_id = {c.id: c.name for c in cameras}
        self._refresh_label_assignment_index()
        self.forge_panel.set_status("Forge lists refreshed")
        self._set_status("Forge data refreshed")
        if self.forge_panel.projects.count() and self.forge_panel.projects.currentRow() < 0:
            self.forge_panel.projects.setCurrentRow(0)
        self._on_forge_project_selected()
        self._sync_selected_camera_assignments()

    def _refresh_label_assignment_index(self) -> None:
        camera_for_label: dict[str, list[str]] = {}
        name_by_id = getattr(self, "_camera_name_by_id", {})
        for camera_id_str, labels in self._camera_assignments.items():
            try:
                camera_id = int(camera_id_str)
            except (TypeError, ValueError):
                continue
            display = name_by_id.get(camera_id, f"cam {camera_id}")
            for label in labels:
                normalized = self._normalize_label_name(label)
                if not normalized:
                    continue
                camera_for_label.setdefault(normalized, []).append(display)
        self.forge_panel.set_label_assignments(camera_for_label)

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

    def _on_bulk_clear_gpio(self, labels: list[str]) -> None:
        project_id = self.forge_panel.selected_project_id()
        if project_id is None:
            self._append_log("Select a project first.")
            return
        cleaned = [label for label in (self._normalize_label_name(raw) for raw in labels) if label]
        if not cleaned:
            return
        key = str(project_id)
        current = dict(self._gpio_assignments.get(key, {}))
        removed = [label for label in cleaned if current.pop(label, None) is not None]
        if not removed:
            self._append_log("Selected labels had no GPIO assignment.")
            return
        if current:
            self._gpio_assignments[key] = current
        else:
            self._gpio_assignments.pop(key, None)
        self._save_gpio_assignments()
        self.forge_panel.set_gpio_assignments(current)
        self._gpio_worker.set_assignments(current)
        self._append_log(f"Cleared GPIO assignment for {len(removed)} labels.")

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
        self._refresh_label_assignment_index()
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
        self._known_labels = [item for item in labels if isinstance(item, dict)] if isinstance(labels, list) else []
        self._inference_worker.set_known_labels(self._known_labels)
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
        self._inference_worker.source_ready.connect(self._on_source_ready)
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
        self._append_log(f"Video input mode: {self._video_source_config.mode}")
        self._append_log(f"Recommended model format: {self._hardware.info.recommended_model_format}")
        self._gpio_worker.start()
        self._inference_worker.start()
        self._watchdog.start()

    def _append_log(self, message: str) -> None:
        self.console.appendPlainText(message)
        self.statusBar().showMessage(message, 5000)

    def _update_telemetry(self, telemetry: dict) -> None:
        self._latest_telemetry = dict(telemetry)
        self.fps_capture.setText(f"{telemetry.get('capture_fps', 0.0):.1f}")
        self.fps_inference.setText(f"{telemetry.get('inference_fps', 0.0):.1f}")
        self.latency.setText(f"{telemetry.get('latency_ms', 0.0):.1f} ms")
        self.ram.setText(f"{telemetry.get('ram_mb', 0.0):.0f} MB")
        self.vram.setText(f"{telemetry.get('vram_mb', 0.0):.0f} MB")
        self.temperature.setText(f"{telemetry.get('soc_temp_c', 0.0):.1f} °C")
        self.health_bar.setValue(min(100, max(0, 100 - int(telemetry.get('latency_ms', 0.0)))))
        self._refresh_live_summary()

    def _restart_inference(self) -> None:
        self._append_log("Restarting inference worker...")
        self._watchdog.request_stop()
        if self._inference_worker.isRunning():
            self._inference_worker.request_stop()
            self._inference_worker.wait(2000)
        self._watchdog.wait(1000)
        self._inference_worker = self._create_inference_worker()
        self._watchdog = Watchdog(self._inference_worker, parent=self)
        self._wire_threads()
        self._watchdog.start()
        self._inference_worker.start()

    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            self.forge_panel.save_state()
        except Exception:
            pass
        try:
            save_inference_source_config(VIDEO_SOURCE_PATH, self._video_source_config)
        except Exception:
            pass
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
