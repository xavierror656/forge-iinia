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
import urllib.parse
import torch
from threading import Lock
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PyQt6.QtCore import QEvent, QObject, QPoint, QRectF, QThread, QTimer, Qt, pyqtSignal
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

import logging

from app.state import DetectionState, TelemetrySnapshot
from app.threads.watchdog import Watchdog
from app.widgets.video_widget import OpenGLVideoWidget
from core.async_worker import AsyncWorker
from core.audit_log import AuditLog
from core.captures_cleanup import cleanup_captures
from core.gpio_backend import GPIOBackend, select_backend
from core.gpio_dispatch import GPIODispatcher
from core.logging_config import configure as configure_logging
from core.output_adapters import InferenceOutputDispatcher, InferenceOutputConfig, inference_payload_from_frame
from core.shutdown import install_signal_handlers
from core.telemetry_log import TelemetryLog


log = logging.getLogger("edgevision")
from core.config_io import ConfigBundle, filter_known_labels, read_path, write_path
from core.config_store import (
    GPIO_ASSIGNMENTS_PATH,
    get_last_camera_id,
    get_last_project_id,
    load_gpio_assignments,
    save_gpio_assignments,
    set_last_camera_id,
    set_last_project_id,
)
from core.env_config import read_env_file
from core.settings import Settings
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
from ui.detection_overlay import DetectionHistogram
from ui.forge_panel import CameraCreateDialog, ForgeConfigDialog, ForgePanel
from ui.gpio_leds import GPIOLedStrip
from ui.settings_panel import SettingsDialog, SettingsPanel
from ui.icons import icon as _icon
from ui.sparkline import Sparkline
from ui.toast import ToastManager


BRAND_LOGO_PATH = Path(__file__).resolve().parent / "ui" / "iinia_logo.webp"


class InferenceWorker(QThread):
    source_ready = pyqtSignal(dict)
    frame_ready = pyqtSignal(object)
    telemetry_ready = pyqtSignal(dict)
    log_message = pyqtSignal(str)
    detection_event = pyqtSignal(str, str, bool)
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
        camera_id: str = "primary",
        forced_choice: VideoSourceChoice | None = None,
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
        self._camera_id = camera_id
        self._forced_choice = forced_choice
        self._model: Any = None
        self._pending_model_signature: tuple[float, int] | None = None

    @property
    def camera_id(self) -> str:
        return self._camera_id

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

    def _simulation_frame(self) -> Any:
        frame = np.zeros((736, 1280, 3), dtype=np.uint8)
        frame[:, :] = (18, 20, 26)
        cv2.rectangle(frame, (70, 80), (1210, 656), (44, 54, 68), 2)
        cv2.rectangle(frame, (120, 140), (430, 520), (70, 90, 115), -1)
        cv2.rectangle(frame, (520, 190), (860, 560), (45, 105, 82), -1)
        cv2.rectangle(frame, (940, 230), (1130, 470), (98, 70, 48), -1)
        cv2.putText(
            frame,
            "SIMULATION FRAME - REAL MODEL INPUT",
            (90, 55),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (210, 220, 235),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            "No camera signal. Running .pt inference on this synthetic frame.",
            (90, 705),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (135, 150, 170),
            2,
            cv2.LINE_AA,
        )
        return frame

    def _detections_from_model(self, frame: Any, *, allow_simulated: bool = False) -> list[dict]:
        if self._model is None:
            return self._simulate_detections() if allow_simulated else []
        if frame is None:
            frame = self._simulation_frame()
        try:
            _device = "cuda:0" if torch.cuda.is_available() else "cpu"
            results = self._model.predict(frame, verbose=False, conf=0.05, device=_device)
        except Exception as exc:
            self.log_message.emit(f"Model inference failed, using simulation: {exc}")
            return self._simulate_detections()
        if not results:
            return []
        result = results[0]
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            return []
        names = getattr(result, "names", {}) or getattr(self._model, "names", {}) or {}
        detections: list[dict] = []
        try:
            xyxy = boxes.xyxy.cpu().tolist()
            cls_values = boxes.cls.cpu().tolist()
            conf_values = boxes.conf.cpu().tolist()
        except Exception:
            return []
        for bbox, cls_id, confidence in zip(xyxy, cls_values, conf_values):
            try:
                class_index = int(cls_id)
            except (TypeError, ValueError):
                class_index = -1
            label = str(names.get(class_index, class_index if class_index >= 0 else "object"))
            detections.append(
                {
                    "label": label,
                    "confidence": round(float(confidence), 4),
                    "bbox": [round(float(value), 2) for value in bbox[:4]],
                    "class_id": class_index,
                    "color": self._color_for_label(label),
                }
            )
        return detections

    def _open_capture(self, choice: VideoSourceChoice) -> cv2.VideoCapture | None:
        backend = capture_backend_for(choice)
        source: Any = choice.source
        if choice.kind == "rtsp" or str(source).startswith("rtsp://"):
            backend = cv2.CAP_FFMPEG
            params = [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 4000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 4000]
            try:
                capture = cv2.VideoCapture(source, backend, params)
            except TypeError:
                capture = cv2.VideoCapture(source, backend)
        elif backend in {cv2.CAP_V4L2, cv2.CAP_ANY}:
            match = re.match(r"^(?:/dev/video)?(\d+)$", str(source).strip())
            if match:
                source = int(match.group(1))
            capture = cv2.VideoCapture(source, backend)
        else:
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
        self._last_heartbeat = time.monotonic()

        if self._forced_choice is not None:
            self._discovered_sources = []
            chosen: VideoSourceChoice | None = None
            capture = self._open_capture(self._forced_choice)
            if capture is not None:
                chosen = self._forced_choice
            self._capture = capture
            self._active_choice = chosen
            self._read_failures = 0
            self._source_status = (
                f"{chosen.kind.upper()} · {chosen.label}" if chosen else "Esperando stream..."
            )
            self._emit_source_state(
                chosen, active=bool(capture), discovered=self._discovered_sources
            )
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
            if state is None:
                state = DetectionState(label=name, threshold=3)
                self._states[name] = state
            if state and state.register(True):
                self.detection_event.emit(name, self._camera_id, True)
        for name, state in list(self._states.items()):
            if name not in seen_names:
                state.register(False)

    def request_stop(self) -> None:
        self._stop_requested = True

    def heartbeat(self) -> float:
        return self._last_heartbeat

    def set_model_path(self, path: str | Path | None) -> None:
        self._model_path = Path(path) if path else None
        self._last_model_mtime = 0.0
        self._pending_model_signature = None

    def _load_model(self) -> None:
        if not self._model_path:
            self._model = None
            self.log_message.emit("No model path provided. Running in simulation mode.")
            self.model_loaded.emit("simulation")
            return

        if not self._model_path.exists():
            self._model = None
            self.log_message.emit(f"Model not found: {self._model_path}")
            self.model_loaded.emit("missing")
            return

        try:
            from ultralytics import YOLO  # type: ignore[import-not-found]
        except Exception as exc:
            self._model = None
            self.log_message.emit(f"ultralytics unavailable, staying in simulation: {exc}")
            self.model_loaded.emit("simulation")
            return

        try:
            _device = "cuda:0" if torch.cuda.is_available() else "cpu"
            self._model = YOLO(str(self._model_path))
            self._model.to(_device)
        except Exception as exc:
            self._model = None
            self.log_message.emit(f"Model load failed: {exc}")
            self.model_loaded.emit("error")
            return

        stat = self._model_path.stat()
        self._last_model_mtime = stat.st_mtime
        self._pending_model_signature = None
        self.log_message.emit(f"Model loaded: {self._model_path.name} (device: {_device})")
        self.model_loaded.emit(str(self._model_path))

    def _maybe_hot_reload(self) -> None:
        """Reload the model if the file changed and looks stable.

        We require two consecutive checks with the same (mtime, size) before
        swapping so a partial copy ``YOLO(...)`` mid-flight never gets loaded.
        """
        if not self._model_path or not self._model_path.exists():
            return
        try:
            stat = self._model_path.stat()
        except OSError:
            return
        signature = (stat.st_mtime, stat.st_size)
        if signature[0] <= self._last_model_mtime:
            self._pending_model_signature = None
            return
        if self._pending_model_signature == signature:
            self.log_message.emit(f"Hot reload triggered for {self._model_path.name}")
            self._load_model()
        else:
            self._pending_model_signature = signature

    def _run_inference_step(self) -> None:
        self._last_heartbeat = time.monotonic()
        self._maybe_hot_reload()

        if self._capture is None:
            self._ensure_capture()

        start = time.perf_counter()
        image: QImage | None = None
        frame_size: tuple[int, int] | None = None
        raw_frame: Any = None
        simulation = self._capture is None

        if self._capture is not None:
            ok, frame = self._capture.read()
            if ok and frame is not None:
                raw_frame = frame
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

        if raw_frame is None and simulation:
            raw_frame = self._simulation_frame()
            image = self._frame_to_qimage(raw_frame)
            frame_size = (int(raw_frame.shape[1]), int(raw_frame.shape[0]))
            if self._model is not None:
                self._source_status = "Simulación · inferencia real sobre frame sintético"

        detections = self._detections_from_model(raw_frame, allow_simulated=simulation)
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

    def __init__(
        self,
        hardware: HardwareManager,
        parent: QObject | None = None,
        *,
        audit_log: AuditLog | None = None,
        dedupe_seconds: float = 1.0,
        backend: GPIOBackend | None = None,
        pulse_seconds: float = 0.1,
    ) -> None:
        super().__init__(parent)
        self._hardware = hardware
        self._events: "queue.Queue[tuple[str, str, bool]]" = queue.Queue()
        self._stop_requested = False
        self._simulation = hardware.is_simulation()
        self._dispatcher = GPIODispatcher(dedupe_seconds=dedupe_seconds)
        self._dispatcher_lock = Lock()
        self._audit = audit_log
        self._backend = backend or select_backend(simulation=self._simulation)
        self._pulse_seconds = max(0.0, float(pulse_seconds))

    def request_stop(self) -> None:
        self._stop_requested = True

    def enqueue_detection(self, label: str, camera_id: str, active: bool) -> None:
        self._events.put((label, camera_id, active))

    def set_assignments(self, assignments: dict[str, str]) -> None:
        with self._dispatcher_lock:
            self._dispatcher.set_assignments(assignments)

    def run(self) -> None:
        while not self._stop_requested:
            try:
                label, camera_id, active = self._events.get(timeout=0.25)
            except queue.Empty:
                continue

            with self._dispatcher_lock:
                decision = self._dispatcher.decide(label, camera_id, active)

            if not decision.fire:
                if decision.reason == "deduped" and self._audit is not None:
                    try:
                        self._audit.record(
                            kind="gpio_dedup",
                            label=label,
                            active=active,
                            camera_id=camera_id,
                        )
                    except OSError:
                        pass
                continue

            port = decision.port
            cam_suffix = f" (cam {camera_id})" if camera_id else ""
            driven = False
            if port and active:
                driven = self._backend.pulse(port, self._pulse_seconds)
            backend_tag = self._backend.name
            if self._simulation:
                if port:
                    self.log_message.emit(f"[SIM] GPIO event: {label} -> {active} on {port}{cam_suffix}")
                else:
                    self.log_message.emit(f"[SIM] GPIO event: {label} -> {active}{cam_suffix}")
            else:
                outcome = "ok" if driven else "no-driver"
                if port:
                    self.log_message.emit(
                        f"GPIO event: {label} -> {active} on {port} via {backend_tag} ({outcome}){cam_suffix}"
                    )
                else:
                    self.log_message.emit(
                        f"GPIO event: {label} -> {active} via {backend_tag}{cam_suffix}"
                    )

            if self._audit is not None:
                try:
                    self._audit.record(
                        kind="gpio_simulated" if self._simulation else "gpio",
                        label=label,
                        active=active,
                        port=port,
                        camera_id=camera_id,
                        extra={"backend": self._backend.name, "driven": driven},
                    )
                except OSError as exc:
                    self.log_message.emit(f"Audit log write failed: {exc}")


class MainWindow(QMainWindow):
    def __init__(self, hardware: HardwareManager, settings: Settings | None = None) -> None:
        super().__init__()
        self._hardware = hardware
        self._settings = settings or Settings.load()
        self._forge = ForgeManager(
            self._settings.forge_url or "https://forge.iinia.ai/api/swagger/",
            retry_attempts=self._settings.http_retry_attempts,
        )
        self._workers: list[AsyncWorker] = []
        self._camera_assignments: dict[str, list[str]] = self._load_local_assignments()
        self._gpio_assignments: dict[str, dict[str, str]] = self._load_gpio_assignments()
        self._video_source_config = load_inference_source_config(VIDEO_SOURCE_PATH)
        self._known_labels: list[dict] = []
        self._latest_source_state: dict[str, Any] = {}
        self._latest_telemetry: dict[str, Any] = {}
        self._model_path = self._resolve_model_path(self._settings.model_path)
        self._model_download_inflight = False
        capture_dir = self._settings.capture_path
        self._audit_log = AuditLog(capture_dir / "events.jsonl")
        self._telemetry_log = TelemetryLog(capture_dir / "telemetry.jsonl")
        self._output_dispatcher = InferenceOutputDispatcher(
            self._settings.output_config,
            log=lambda message: self._append_log(message),
        )
        try:
            removed, freed = cleanup_captures(capture_dir)
            if removed:
                log.info("captures cleanup: removed %d files (%d bytes)", removed, freed)
        except OSError as exc:
            log.warning("captures cleanup failed: %s", exc)
        self._inference_workers: list[InferenceWorker] = self._create_inference_workers()
        self._inference_worker: InferenceWorker = self._inference_workers[0]
        self._gpio_worker = GPIOWorker(
            hardware,
            self,
            audit_log=self._audit_log,
            dedupe_seconds=self._settings.gpio_dedupe_seconds,
            pulse_seconds=self._settings.gpio_pulse_seconds,
        )
        self._watchdogs: list[Watchdog] = [
            Watchdog(worker, timeout_s=self._settings.watchdog_timeout_seconds, parent=self)
            for worker in self._inference_workers
        ]
        self._watchdog: Watchdog = self._watchdogs[0]
        self._build_ui()
        self._toast = ToastManager(self)
        self._assignment_history = AssignmentHistory(on_apply=self._restore_snapshot)
        self._assignment_history.initialize(self._camera_assignments, self._gpio_assignments)
        self._install_global_shortcuts()
        self._apply_env_settings(read_env_file(Path(self.settings_panel.env_file.text().strip() or ".env")))
        self._wire_threads()
        self._start_threads()
        self._bootstrap_from_env()

    def _install_global_shortcuts(self) -> None:
        help_shortcut = QShortcut(QKeySequence("F1"), self)
        help_shortcut.activated.connect(self._open_shortcuts_dialog)
        question = QShortcut(QKeySequence(Qt.Key.Key_Question), self)
        question.activated.connect(self._open_shortcuts_dialog)
        undo = QShortcut(QKeySequence("Ctrl+Z"), self)
        undo.activated.connect(self._undo_assignment)
        redo = QShortcut(QKeySequence("Ctrl+Y"), self)
        redo.activated.connect(self._redo_assignment)

    def _open_shortcuts_dialog(self) -> None:
        ShortcutsDialog(self).exec()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "_toast"):
            self._toast.reflow()

    def _undo_assignment(self) -> None:
        label = self._assignment_history.undo()
        if label is None:
            self._toast.show("Nada que deshacer", severity="info", ttl_ms=2000)
            return
        self._toast.show(f"Deshecho: {label}", severity="success", ttl_ms=2500)

    def _redo_assignment(self) -> None:
        label = self._assignment_history.redo()
        if label is None:
            self._toast.show("Nada que rehacer", severity="info", ttl_ms=2000)
            return
        self._toast.show(f"Rehecho: {label}", severity="success", ttl_ms=2500)

    def _push_assignment_history(self, label: str) -> None:
        if hasattr(self, "_assignment_history"):
            self._assignment_history.push(label, self._camera_assignments, self._gpio_assignments)

    def _restore_snapshot(self, snapshot: Snapshot) -> None:
        self._gpio_assignments = {k: dict(v) for k, v in snapshot.gpios.items()}
        self._camera_assignments = {k: list(v) for k, v in snapshot.cameras.items()}
        self._save_gpio_assignments()
        self._save_local_assignments()
        project_id = self.forge_panel.selected_project_id()
        if project_id is not None:
            current = dict(self._gpio_assignments.get(str(project_id), {}))
            self.forge_panel.set_gpio_assignments(current)
            self._gpio_worker.set_assignments(current)
        self._refresh_label_assignment_index()

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

    def _resolve_active_sources(self) -> list[VideoSourceChoice]:
        """Decide which sources to actually run inference on simultaneously.

        Rule: each enabled RTSP camera or each *configured* enabled local
        (USB/CSI) camera gets its own worker when there are 2+ of them.
        Auto-discovered local devices are not promoted to tiles to avoid
        spawning workers for /dev/videoN nodes that can't be captured.
        """
        config = self._video_source_config
        mode = (config.mode or "auto").strip().lower()
        if mode == "rtsp":
            candidates, _ = resolve_video_source_candidates(config, self._hardware)
            rtsp_candidates = [c for c in candidates if c.kind == "rtsp"]
            return rtsp_candidates if len(rtsp_candidates) > 1 else []

        local_candidates: list[VideoSourceChoice] = []
        for item in config.local_cameras:
            if not isinstance(item, dict):
                continue
            if not bool(item.get("enabled", True)):
                continue
            kind = str(item.get("kind", "webcam")).strip().lower() or "webcam"
            if mode == "webcam" and kind != "webcam":
                continue
            if mode == "csi" and kind != "csi":
                continue
            source = str(item.get("source", "")).strip()
            if not source:
                continue
            backend = str(item.get("backend", "")).strip().lower() or (
                "gstreamer" if kind == "csi" else "v4l2"
            )
            label = str(item.get("name", "")).strip() or source
            local_candidates.append(
                VideoSourceChoice(kind=kind, label=label, source=source, backend=backend, available=True)
            )
        return local_candidates if len(local_candidates) > 1 else []

    @staticmethod
    def _resolve_model_path(path: Path) -> Path | None:
        if path.is_file():
            return path
        if not path.exists() or not path.is_dir():
            return None
        candidates = sorted(path.glob("*.pt"), key=lambda candidate: candidate.stat().st_mtime, reverse=True)
        return candidates[0] if candidates else None

    def _create_inference_workers(self) -> list[InferenceWorker]:
        active = self._resolve_active_sources()
        if not active:
            primary = InferenceWorker(
                self._model_path,
                self._hardware,
                self,
                source_config=self._video_source_config,
                camera_id="primary",
            )
            if self._known_labels:
                primary.set_known_labels(self._known_labels)
            return [primary]

        workers: list[InferenceWorker] = []
        for index, choice in enumerate(active):
            cam_id = choice.label.strip() or f"cam-{index + 1}"
            worker = InferenceWorker(
                self._model_path,
                self._hardware,
                self,
                source_config=self._video_source_config,
                camera_id=cam_id,
                forced_choice=choice,
            )
            if self._known_labels:
                worker.set_known_labels(self._known_labels)
            workers.append(worker)
        return workers

    def _create_inference_worker(self) -> InferenceWorker:
        return self._create_inference_workers()[0]

    def _build_ui(self) -> None:
        self.setWindowTitle("EdgeVision Control Hub")
        self.setWindowIcon(_icon("app", size=24))
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
        self.hardware_icon = QLabel()
        self.hardware_icon.setFixedSize(16, 16)
        self.hardware_icon.setPixmap(_icon("cpu", size=16, color="muted").pixmap(16, 16))
        self.hardware_label = QLabel(f"Hardware: {self._hardware.info.name}")
        self.hardware_hint = QLabel(self._hardware.info.deployment_note)
        self.simulation_switch = QCheckBox("Modo Simulación")
        self.simulation_switch.setChecked(self._hardware.is_simulation())
        self.simulation_switch.setEnabled(False)
        self.simulation_switch.setIcon(_icon("cpu", size=16))
        self.settings_button = QPushButton(" Config .env")
        self.settings_button.setIcon(_icon("gear", size=16))
        self.dark_mode_switch = QCheckBox("Dark mode")
        self.dark_mode_switch.setChecked(True)
        self.dark_mode_switch.setIcon(_icon("moon", size=16))
        header.addWidget(self.brand_logo)
        header.addWidget(self.hardware_icon)
        header.addWidget(self.hardware_label)
        header.addStretch(1)
        header.addWidget(self.settings_button)
        header.addWidget(self.dark_mode_switch)
        header.addWidget(self.simulation_switch)

        self.settings_panel = SettingsPanel(ui_profile=self._hardware.ui_profile)
        self.forge_panel = ForgePanel(ui_profile=self._hardware.ui_profile)
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

        self.tabs.addTab(live_tab, _icon("camera-video", size=16), "Live")
        self.tabs.addTab(forge_tab, _icon("box-seam", size=16), "Forge")
        self.tabs.addTab(logs_tab, _icon("terminal", size=16), "Logs")

        root.addLayout(header)
        root.addWidget(self.hardware_hint)
        root.addWidget(self.tabs)

        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar(self))

        self.settings_panel.env_changed.connect(self._apply_env_settings)
        self.settings_panel.forge_test_requested.connect(self._test_forge_connection)
        self.settings_button.clicked.connect(self._open_settings_dialog)
        self.dark_mode_switch.toggled.connect(self._apply_dark_theme)
        self.dark_mode_switch.toggled.connect(
            lambda enabled: self.dark_mode_switch.setIcon(_icon("moon" if enabled else "sun", size=16))
        )
        self.dark_mode_switch.toggled.connect(lambda enabled: self.settings_panel.ui_theme.setCurrentText("dark" if enabled else "light"))
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
        self.forge_panel.send_conf_requested.connect(lambda _line_id: self._send_line_conf())
        self.forge_panel.bulk_clear_requested.connect(self._on_bulk_clear_gpio)
        self.forge_panel.help_requested.connect(self._open_shortcuts_dialog)
        self.forge_panel.download_model_requested.connect(self._download_forge_project_model)

    def _build_live_tab(self) -> QWidget:
        profile = self._hardware.ui_profile
        video_box = self._build_video_box(profile)
        side_box = self._build_side_box()

        live_tab = QWidget()
        outer = QVBoxLayout(live_tab)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(profile == "single")
        splitter.addWidget(video_box)
        splitter.addWidget(side_box)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 0)
        if profile == "single":
            splitter.setSizes([1400, 0])
        else:
            splitter.setSizes([900, 260])
        self._live_splitter = splitter

        outer.addWidget(splitter)

        if profile == "single":
            self._install_fullscreen_shortcut()
            self._apply_lite_stylesheet()

        return live_tab

    def _build_video_box(self, profile: str) -> QWidget:
        video_box = QWidget()
        video_layout = QVBoxLayout(video_box)
        video_layout.setContentsMargins(0, 0, 0, 0)
        video_layout.setSpacing(6)

        self._build_status_banners(video_layout)
        self._video_layout = video_layout
        self._video_profile = profile
        self._video_view_widget = self._make_video_view_widget()
        video_layout.addWidget(self._video_view_widget, 1)

        return video_box

    def _make_video_view_widget(self) -> QWidget:
        use_grid = self._video_profile == "multi" or len(self._inference_workers) > 1
        if use_grid:
            return self._build_video_grid()
        self.video_widget = OpenGLVideoWidget(self)
        self.video_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._tiles: list[OpenGLVideoWidget] = [self.video_widget]
        return self.video_widget

    def _rebuild_video_view(self) -> None:
        if not hasattr(self, "_video_layout") or not hasattr(self, "_video_view_widget"):
            return
        old = self._video_view_widget
        self._video_layout.removeWidget(old)
        old.setParent(None)
        old.deleteLater()
        if hasattr(self, "_tile_health_timer"):
            try:
                self._tile_health_timer.stop()
            except Exception:
                pass
        self._video_view_widget = self._make_video_view_widget()
        self._video_layout.addWidget(self._video_view_widget, 1)

    def _build_status_banners(self, video_layout: QVBoxLayout) -> None:
        self.status_banner_icon = QLabel()
        self.status_banner_icon.setFixedSize(16, 16)
        self.status_banner_icon.setPixmap(_icon("info-circle", size=16, color="info").pixmap(16, 16))
        status_row = QWidget()
        status_row_layout = QHBoxLayout(status_row)
        status_row_layout.setContentsMargins(0, 0, 0, 0)
        status_row_layout.setSpacing(8)
        self.status_banner = QLabel("Ready")
        self.status_banner.setStyleSheet(
            "padding: 6px 10px; border-radius: 6px; background: #1b2028; color: #d8dde3;"
        )
        status_row_layout.addWidget(self.status_banner_icon)
        status_row_layout.addWidget(self.status_banner, 1)
        video_layout.addWidget(status_row)

        self.stream_banner_icon = QLabel()
        self.stream_banner_icon.setFixedSize(16, 16)
        self.stream_banner_icon.setPixmap(_icon("camera-video", size=16, color="muted").pixmap(16, 16))
        stream_row = QWidget()
        stream_row_layout = QHBoxLayout(stream_row)
        stream_row_layout.setContentsMargins(0, 0, 0, 0)
        stream_row_layout.setSpacing(8)
        self.stream_banner = QLabel("Fuente de video pendiente...")
        self.stream_banner.setWordWrap(True)
        self.stream_banner.setStyleSheet(
            "padding: 6px 10px; border-radius: 6px; background: #141820; color: #cfd6e1;"
        )
        stream_row_layout.addWidget(self.stream_banner_icon)
        stream_row_layout.addWidget(self.stream_banner, 1)
        video_layout.addWidget(stream_row)

        self.pool_banner_icon = QLabel()
        self.pool_banner_icon.setFixedSize(16, 16)
        self.pool_banner_icon.setPixmap(_icon("diagram-3", size=16, color="muted").pixmap(16, 16))
        pool_row = QWidget()
        pool_row_layout = QHBoxLayout(pool_row)
        pool_row_layout.setContentsMargins(0, 0, 0, 0)
        pool_row_layout.setSpacing(8)
        self.pool_banner = QLabel("")
        self.pool_banner.setWordWrap(True)
        self.pool_banner.setStyleSheet(
            "padding: 4px 10px; border-radius: 6px; background: #141820; color: #9aa6b2; font-size: 11px;"
        )
        self.pool_banner.setVisible(False)
        pool_row_layout.addWidget(self.pool_banner_icon)
        pool_row_layout.addWidget(self.pool_banner, 1)
        self.pool_row = pool_row
        self.pool_row.setVisible(False)
        video_layout.addWidget(pool_row)

    def _build_video_grid(self) -> QWidget:
        n = max(1, len(self._inference_workers))

        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)

        self._tile_grid_layout = grid
        self._tile_widgets: list[QWidget] = []
        self._tiles: list[OpenGLVideoWidget] = []
        self._tile_badges: list[QLabel] = []
        self._tile_camera_ids: list[str] = []
        self._tile_frame_history: list[list[float]] = []
        self._tile_last_frame: list[float] = []
        self._spotlight_index: int | None = None
        for index in range(n):
            cam_id = self._inference_workers[index].camera_id
            tile, video, badge = self._build_tile(cam_id)
            tile.installEventFilter(self)
            self._tile_widgets.append(tile)
            self._tiles.append(video)
            self._tile_badges.append(badge)
            self._tile_camera_ids.append(cam_id)
            self._tile_frame_history.append([])
            self._tile_last_frame.append(0.0)

        self._apply_spotlight_layout()
        self.video_widget = self._tiles[0]
        self._tile_health_timer = QTimer(self)
        self._tile_health_timer.setInterval(500)
        self._tile_health_timer.timeout.connect(self._refresh_tile_health)
        self._tile_health_timer.start()
        return grid_widget

    def _apply_spotlight_layout(self) -> None:
        grid = self._tile_grid_layout
        while grid.count():
            grid.takeAt(0)
        n = len(self._tile_widgets)
        if self._spotlight_index is None or n <= 1:
            rows, cols = self._tile_grid_dims(n)
            for r in range(rows):
                grid.setRowStretch(r, 1)
            for c in range(cols):
                grid.setColumnStretch(c, 1)
            for index, tile in enumerate(self._tile_widgets):
                r, c = divmod(index, cols)
                grid.addWidget(tile, r, c)
            return
        spot = max(0, min(self._spotlight_index, n - 1))
        others = n - 1
        spot_cols = 4
        grid.addWidget(self._tile_widgets[spot], 0, 0, max(1, others), spot_cols)
        side = 0
        for idx, tile in enumerate(self._tile_widgets):
            if idx == spot:
                continue
            grid.addWidget(tile, side, spot_cols, 1, 1)
            side += 1
        for r in range(max(1, others)):
            grid.setRowStretch(r, 1)
        for c in range(spot_cols):
            grid.setColumnStretch(c, 4)
        grid.setColumnStretch(spot_cols, 1)

    def _toggle_spotlight(self, index: int) -> None:
        if not hasattr(self, "_tile_widgets") or len(self._tile_widgets) <= 1:
            return
        self._spotlight_index = None if self._spotlight_index == index else index
        self._apply_spotlight_layout()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if hasattr(self, "_tile_widgets") and obj in self._tile_widgets:
            if event.type() == QEvent.Type.MouseButtonDblClick:
                self._spotlight_index = None
                self._apply_spotlight_layout()
                return True
            if event.type() == QEvent.Type.MouseButtonPress:
                self._toggle_spotlight(self._tile_widgets.index(obj))
                return True
        return super().eventFilter(obj, event)

    @staticmethod
    def _tile_grid_dims(n: int) -> tuple[int, int]:
        if n <= 1:
            return (1, 1)
        if n == 2:
            return (1, 2)
        if n <= 4:
            return (2, 2)
        if n <= 6:
            return (2, 3)
        if n <= 9:
            return (3, 3)
        cols = 4
        rows = (n + cols - 1) // cols
        return (rows, cols)

    def _build_tile(self, camera_id: str) -> tuple[QWidget, OpenGLVideoWidget, QLabel]:
        tile = QFrame()
        tile.setFrameShape(QFrame.Shape.StyledPanel)
        tile.setStyleSheet("QFrame { background:#0d1014; border:1px solid #2a313a; border-radius:6px; }")
        layout = QVBoxLayout(tile)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        video = OpenGLVideoWidget(tile)
        video.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        video.setMinimumHeight(180)
        layout.addWidget(video, 1)

        badge = QLabel(camera_id)
        badge.setStyleSheet(self._TILE_BADGE_QSS_ONLINE)
        badge.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(badge, 0)
        return tile, video, badge

    _TILE_BADGE_QSS_ONLINE = (
        "padding: 2px 6px; background: rgba(0,0,0,0.55); color: #e6eaf2;"
        " font-size: 10px; border-radius: 4px;"
    )
    _TILE_BADGE_QSS_OFFLINE = (
        "padding: 2px 6px; background: rgba(58, 31, 36, 0.85); color: #e9a4a4;"
        " font-size: 10px; border-radius: 4px;"
    )

    def _on_tile_frame(self, index: int) -> None:
        if not hasattr(self, "_tile_frame_history") or index >= len(self._tile_frame_history):
            return
        now = time.monotonic()
        history = self._tile_frame_history[index]
        history.append(now)
        if len(history) > 30:
            del history[0 : len(history) - 30]
        self._tile_last_frame[index] = now

    def _refresh_tile_health(self) -> None:
        if not hasattr(self, "_tile_badges"):
            return
        now = time.monotonic()
        for i, badge in enumerate(self._tile_badges):
            history = self._tile_frame_history[i]
            if len(history) >= 2:
                fps = (len(history) - 1) / max(0.001, history[-1] - history[0])
            else:
                fps = 0.0
            offline = (now - self._tile_last_frame[i]) > 2.0 if self._tile_last_frame[i] > 0 else True
            cam_id = self._tile_camera_ids[i]
            if offline:
                badge.setText(f"●  {cam_id}  ·  offline")
                badge.setStyleSheet(self._TILE_BADGE_QSS_OFFLINE)
            else:
                badge.setText(f"{cam_id}  ·  {fps:.1f} FPS")
                badge.setStyleSheet(self._TILE_BADGE_QSS_ONLINE)

    def _build_side_box(self) -> QWidget:
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
        self.fps_capture_spark = Sparkline(color="#62d2a2")
        self.fps_inference_spark = Sparkline(color="#5aa9e6")
        self.latency_spark = Sparkline(color="#f4b942")
        for spark in (self.fps_capture_spark, self.fps_inference_spark, self.latency_spark):
            spark.setFixedHeight(18)
        rows = [
            ("camera-video", "FPS captura", self.fps_capture, self.fps_capture_spark),
            ("activity", "FPS inferencia", self.fps_inference, self.fps_inference_spark),
            ("stopwatch", "Latencia", self.latency, self.latency_spark),
            ("memory", "RAM", self.ram, None),
            ("cpu", "VRAM", self.vram, None),
            ("thermometer-half", "SoC", self.temperature, None),
        ]
        for row, (icon_name, label_text, value_widget, spark) in enumerate(rows):
            icon_label = QLabel()
            icon_label.setPixmap(_icon(icon_name, size=14, color="muted").pixmap(14, 14))
            icon_label.setFixedSize(16, 16)
            key = QLabel(label_text)
            key.setStyleSheet("color:#8b95a1;")
            telemetry_grid.addWidget(icon_label, row, 0)
            telemetry_grid.addWidget(key, row, 1)
            telemetry_grid.addWidget(value_widget, row, 2)
            if spark is not None:
                telemetry_grid.addWidget(spark, row, 3)
        telemetry_grid.setColumnMinimumWidth(3, 70)
        telemetry_grid.setColumnStretch(3, 1)
        side_layout.addLayout(telemetry_grid)

        health_row = QWidget()
        health_row_layout = QHBoxLayout(health_row)
        health_row_layout.setContentsMargins(0, 6, 0, 0)
        health_row_layout.setSpacing(6)
        health_icon = QLabel()
        health_icon.setFixedSize(16, 16)
        health_icon.setPixmap(_icon("heart-pulse", size=16, color="info").pixmap(16, 16))
        health_label = QLabel("Health")
        health_label.setStyleSheet("color:#8b95a1;")
        health_row_layout.addWidget(health_icon)
        health_row_layout.addWidget(health_label)
        health_row_layout.addStretch(1)
        side_layout.addWidget(health_row)
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

        self.capture_button = QPushButton(" Tomar foto")
        self.capture_button.setIcon(_icon("camera", size=16))
        self.capture_button.clicked.connect(self._capture_component_photo)
        self.restart_button = QPushButton(" Reiniciar inferencia")
        self.restart_button.setIcon(_icon("arrow-repeat", size=16))
        self.restart_button.clicked.connect(self._restart_inference)
        side_layout.addWidget(self.capture_button)
        side_layout.addWidget(self.restart_button)

        side_box.setMinimumWidth(220)
        side_box.setMaximumWidth(320)
        return side_box

    def _install_fullscreen_shortcut(self) -> None:
        shortcut = QShortcut(QKeySequence("F11"), self)
        shortcut.activated.connect(self._toggle_fullscreen)

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _apply_lite_stylesheet(self) -> None:
        # Pi has the slow VC4 GPU — drop borders/radii on heavy frames.
        self.setStyleSheet(
            (self.styleSheet() or "")
            + " QFrame { border-radius: 4px; } QPushButton { padding: 6px 10px; }"
        )

    def _apply_env_settings(self, values: dict) -> None:
        self._settings = Settings.from_mapping(values)
        self._model_path = self._resolve_model_path(self._settings.model_path)
        self._output_dispatcher.update_config(InferenceOutputConfig.from_mapping(values))
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
        self.forge_panel.set_status("Configuración Forge cargada desde .env")
        theme = str(values.get("UI_THEME", "dark")).strip().lower()
        self.dark_mode_switch.setChecked(theme != "light")
        for worker in self._inference_workers:
            worker.set_model_path(self._model_path)
        if self._model_path is not None:
            self._append_log(f"Model path selected: {self._model_path}")
        protocols = self._settings.output_config.enabled_protocols()
        if protocols:
            self._append_log("Inference outputs enabled: " + ", ".join(protocols))
        model_url = str(values.get("FORGE_MODEL_URL", "")).strip()
        model_asset_uuid = str(values.get("FORGE_MODEL_ASSET_UUID", "")).strip()
        self.forge_panel.set_model_download_available(bool(model_url or model_asset_uuid))
        if model_url and self._model_path is None:
            self._download_model_url(model_url)
        if model_asset_uuid and self._model_path is None:
            self._download_model_asset(model_asset_uuid)
        self._set_status("Configuration loaded from .env")
        self._append_log("Configuration loaded from .env")
        self._apply_dark_theme(self.dark_mode_switch.isChecked())

    def _test_forge_connection(self, values: dict) -> None:
        url = (values.get("FORGE_URL") or "").strip() or "https://forge.iinia.ai/api/swagger/"
        forge = ForgeManager(url, retry_attempts=1)
        token = values.get("FORGE_TOKEN", "").strip()
        user = values.get("FORGE_USERNAME", "").strip()
        password = values.get("FORGE_PASSWORD", "")
        if token:
            forge.set_token(token)
        elif user and password:
            forge.set_basic_auth(user, password)

        def _ping() -> object:
            forge.ping()
            return {"ok": True}

        def _ok(_payload: object) -> None:
            self.settings_panel.set_forge_test_result(True, url)
            if hasattr(self, "_toast"):
                self._toast.show("Conexión Forge OK", severity="success", ttl_ms=3000)

        def _err(detail: str) -> None:
            self.settings_panel.set_forge_test_result(False, detail or "Sin detalle")
            if hasattr(self, "_toast"):
                self._toast.show(f"Forge: {detail or 'error'}", severity="error", ttl_ms=4000)

        self._run_async(_ping, on_ok=_ok, on_error=_err, busy_text="Probando Forge…")

    def _open_settings_dialog(self) -> None:
        dialog = SettingsDialog(
            env_path=self.settings_panel.env_file.text().strip() or ".env",
            parent=self,
            ui_profile=self._hardware.ui_profile,
        )
        dialog.panel.env_changed.connect(self._apply_env_settings)
        dialog.panel.video_source_changed.connect(self._apply_video_source_config)
        dialog.panel.forge_test_requested.connect(self._test_forge_connection)
        result = dialog.exec()
        dialog.deleteLater()
        if result == QDialog.DialogCode.Accepted:
            self.settings_panel.load_env()

    def _apply_video_source_config(self, payload: dict) -> None:
        if not isinstance(payload, dict):
            return

        self._video_source_config = InferenceSourceConfig.from_mapping(payload)
        save_inference_source_config(VIDEO_SOURCE_PATH, self._video_source_config)
        self._set_status("Reiniciando fuente de video...")
        self._append_log("Video source configuration saved.")
        self._restart_count = 0
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
        raw = load_gpio_assignments()
        assignments: dict[str, dict[str, str]] = {}
        dirty = False
        for project_id, mapping in raw.items():
            cleaned: dict[str, str] = {}
            for raw_label, raw_port in mapping.items():
                label = self._normalize_label_name(raw_label)
                port = str(raw_port).strip()
                if not label or not port:
                    dirty = True
                    continue
                cleaned[label] = port
            if list(cleaned.keys()) != list(mapping.keys()):
                dirty = True
            if cleaned:
                assignments[str(project_id)] = cleaned
        if dirty:
            try:
                save_gpio_assignments(assignments)
            except OSError:
                pass
        return assignments

    def _save_gpio_assignments(self) -> None:
        save_gpio_assignments(self._gpio_assignments)

    def _bootstrap_from_env(self) -> None:
        if self.forge_panel.username.text().strip() or self.forge_panel.token.text().strip():
            self._refresh_forge_lists()
        self._verify_credentials_async()

    def _verify_credentials_async(self) -> None:
        if self.forge_panel.username.text().strip() or self.forge_panel.token.text().strip():
            self._run_async(
                self._forge.ping,
                on_ok=lambda _: self._append_log(f"Forge ping OK ({self._forge.base_url})"),
                on_error=lambda err: self._append_log(f"Forge ping failed: {err}"),
                busy_text="Verifying Forge credentials...",
            )

    def _set_status(self, text: str) -> None:
        self.status_banner.setText(text)
        if not hasattr(self, "status_banner_icon"):
            return
        lower = text.lower()
        if any(token in lower for token in ("error", "fail", "frozen", "abort")):
            icon_name, icon_color = "x-circle", "danger"
        elif any(token in lower for token in ("ok", "ready", "loaded", "activo", "guardado")):
            icon_name, icon_color = "check-circle", "accent"
        else:
            icon_name, icon_color = "info-circle", "info"
        self.status_banner_icon.setPixmap(_icon(icon_name, size=16, color=icon_color).pixmap(16, 16))

    def _handle_worker_frozen(self, camera_id: str) -> None:
        frozen = getattr(self, "_frozen_cameras", set())
        frozen = set(frozen)
        frozen.add(camera_id)
        self._frozen_cameras = frozen
        self._report_error(
            f"Inference frozen ({camera_id})",
            RuntimeError("watchdog will restart worker"),
        )
        self._refresh_pool_banner()

    def _refresh_pool_banner(self) -> None:
        if not hasattr(self, "pool_banner"):
            return
        workers = self._inference_workers
        if len(workers) <= 1:
            if hasattr(self, "pool_row"):
                self.pool_row.setVisible(False)
            return
        frozen = getattr(self, "_frozen_cameras", set())
        if hasattr(self, "pool_row"):
            self.pool_row.setVisible(True)
        if hasattr(self, "pool_banner_icon"):
            if frozen:
                self.pool_banner_icon.setPixmap(_icon("exclamation-triangle", size=16, color="warning").pixmap(16, 16))
            else:
                self.pool_banner_icon.setPixmap(_icon("diagram-3", size=16, color="info").pixmap(16, 16))
        parts: list[str] = []
        for worker in workers:
            cam_id = worker.camera_id
            mark = "⚠" if cam_id in frozen else "●"
            parts.append(f"{mark} {cam_id}")
        active = sum(1 for w in workers if w.camera_id not in frozen)
        summary = f"Cámaras activas: {active}/{len(workers)}  ·  " + "  ".join(parts)
        self.pool_banner.setText(summary)
        self.pool_banner.setVisible(True)

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
        if hasattr(self, "stream_banner_icon"):
            if active:
                icon_name, icon_color = ("broadcast", "info") if kind == "RTSP" else ("camera-video", "accent")
            elif source.get("source"):
                icon_name, icon_color = "exclamation-triangle", "warning"
            else:
                icon_name, icon_color = "slash-circle", "danger"
            self.stream_banner_icon.setPixmap(_icon(icon_name, size=16, color=icon_color).pixmap(16, 16))
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

    def _download_model_url(self, url: str) -> None:
        if not self._begin_model_download():
            return
        target_dir = self._model_target_dir()
        target_dir.mkdir(parents=True, exist_ok=True)
        parsed = urllib.parse.urlparse(url)
        name = Path(parsed.path).name or "forge_model.pt"
        if not name.endswith(".pt"):
            name = f"{name}.pt"
        target = target_dir / name

        def download() -> Path:
            data = self._forge._request("GET", url, binary=True)
            target.write_bytes(bytes(data))
            return target

        self._run_async(
            download,
            on_ok=self._finish_model_download,
            on_error=lambda err: self._fail_model_download("Forge model URL download failed", err),
            busy_text="Downloading model .pt from Forge URL...",
        )

    def _download_forge_project_model(self, project_id: int) -> None:
        model_url = self.settings_panel.forge_model_url.text().strip()
        if model_url:
            self._download_model_url(model_url)
            return
        model_asset_uuid = self.settings_panel.forge_model_asset_uuid.text().strip()
        if model_asset_uuid:
            self._download_model_asset(model_asset_uuid)
            return
        if project_id < 0:
            self._append_log("Select a Forge project first.")
            return
        if not self._begin_model_download():
            return
        target_dir = self._model_target_dir()
        self._run_async(
            lambda: self._forge.download_project_model(project_id, target_dir),
            on_ok=self._finish_model_download,
            on_error=lambda err: self._fail_model_download("Forge project model download failed", err),
            busy_text=f"Downloading project {project_id} model .pt...",
        )

    def _download_model_asset(self, asset_uuid: str) -> None:
        if not self._begin_model_download():
            return
        target_dir = self._model_target_dir()
        self._run_async(
            lambda: self._forge.download_asset(asset_uuid, target_dir),
            on_ok=self._finish_model_download,
            on_error=lambda err: self._fail_model_download("Forge model asset download failed", err),
            busy_text="Downloading model .pt from Forge asset...",
        )

    def _model_target_dir(self) -> Path:
        path = Path(self.settings_panel.model_dir.text().strip() or "models")
        return path.parent if path.suffix == ".pt" else path

    def _begin_model_download(self) -> bool:
        if self._model_download_inflight:
            self._append_log("Model download already in progress; ignoring duplicate request.")
            return False
        self._model_download_inflight = True
        return True

    def _finish_model_download(self, path: object) -> None:
        self._model_download_inflight = False
        self._use_downloaded_model(path)

    def _fail_model_download(self, context: str, message: str) -> None:
        self._model_download_inflight = False
        self._report_error(context, RuntimeError(message))

    def _use_downloaded_model(self, path: object) -> None:
        model_path = Path(path)
        self._model_path = model_path
        self.settings_panel.model_dir.setText(str(model_path))
        for worker in self._inference_workers:
            worker.set_model_path(model_path)
        self._append_log(f"Forge model downloaded: {model_path}")
        self._set_status(f"Model downloaded: {model_path.name}")
        QTimer.singleShot(0, self._restart_inference)

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
            last_project = get_last_project_id()
            if last_project is None or not self.forge_panel.select_project_by_id(last_project):
                self.forge_panel.projects.setCurrentRow(0)
        self._on_forge_project_selected()
        last_camera = get_last_camera_id()
        if last_camera is not None:
            self.forge_panel.select_camera_by_id(last_camera)
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
        try:
            set_last_project_id(self.forge_panel.selected_project_id())
        except OSError as exc:
            log.warning("Could not persist last project: %s", exc)

    def _sync_selected_camera_assignments(self) -> None:
        assignments = self._current_camera_assignments()
        self.forge_panel.set_assigned(assignments)
        self.forge_panel.set_gpio_assignments(self._current_gpio_assignments())
        self._gpio_worker.set_assignments(self._current_gpio_assignments())
        item = self.forge_panel.cameras.currentItem()
        if item is not None:
            cam_id = item.data(Qt.ItemDataRole.UserRole)
            try:
                set_last_camera_id(int(cam_id) if cam_id is not None else None)
            except (OSError, TypeError, ValueError) as exc:
                log.warning("Could not persist last camera: %s", exc)

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
        self._toast.show(f"{len(removed)} GPIO desvinculadas", severity="warn")
        self._push_assignment_history(f"Bulk clear {len(removed)}")

    def _on_gpio_labels_dropped(self, port: str, labels: list[str]) -> None:
        project_id = self.forge_panel.selected_project_id()
        if project_id is None:
            self._toast.show("Selecciona un proyecto primero", severity="warn")
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
        n = len(cleaned_labels)
        preview = ", ".join(cleaned_labels[:3]) + ("…" if n > 3 else "")
        self._toast.show(f"{n} label{'s' if n != 1 else ''} → {port}  ({preview})", severity="success")
        self._push_assignment_history(f"Drop {n} → {port}")

    def _camera_display_name(self, camera_id: int) -> str:
        for i in range(self.forge_panel.cameras.count()):
            item = self.forge_panel.cameras.item(i)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == camera_id:
                return item.text()
        return f"cam {camera_id}"

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
        cam_name = self._camera_display_name(camera_id)
        n = len(cleaned_labels)
        self._toast.show(f"{n} label{'s' if n != 1 else ''} → {cam_name}", severity="success")
        self._push_assignment_history(f"Drop {n} → {cam_name}")
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
        for worker in self._inference_workers:
            worker.set_known_labels(self._known_labels)
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

    def _unwire_threads(self) -> None:
        for worker in getattr(self, "_inference_workers", []):
            for signal in (
                worker.frame_ready,
                worker.source_ready,
                worker.telemetry_ready,
                worker.log_message,
                worker.detection_event,
                worker.detections_payload,
                worker.model_loaded,
                worker.frozen,
            ):
                try:
                    signal.disconnect()
                except Exception:
                    pass
        for watchdog in getattr(self, "_watchdogs", []):
            for signal in (watchdog.log_message, watchdog.restart_requested):
                try:
                    signal.disconnect()
                except Exception:
                    pass
        try:
            self._gpio_worker.log_message.disconnect()
        except Exception:
            pass

    def _wire_threads(self) -> None:
        primary = self._inference_workers[0]
        primary.source_ready.connect(self._on_source_ready)
        primary.telemetry_ready.connect(self._update_telemetry)
        primary.model_loaded.connect(lambda model: self._set_status(f"Model: {model}"))

        tiles = getattr(self, "_tiles", None) or [self.video_widget]
        for index, worker in enumerate(self._inference_workers):
            tile = tiles[index] if index < len(tiles) else self.video_widget
            worker.frame_ready.connect(tile.set_frame)
            worker.frame_ready.connect(
                lambda frame, cam=worker.camera_id: self._publish_inference_outputs(frame, cam)
            )
            worker.frame_ready.connect(lambda _frame, idx=index: self._on_tile_frame(idx))
            worker.log_message.connect(self._append_log)
            worker.detection_event.connect(self._gpio_worker.enqueue_detection)
            worker.frozen.connect(
                lambda cam=worker.camera_id: self._handle_worker_frozen(cam)
            )
        self._gpio_worker.log_message.connect(self._append_log)
        for watchdog in self._watchdogs:
            watchdog.log_message.connect(self._append_log)
            watchdog.restart_requested.connect(self._restart_inference)

    def _start_threads(self) -> None:
        self._append_log(f"Selected backend: {self._hardware.info.camera_backend} / {self._hardware.info.gpio_backend}")
        self._append_log(f"Video input mode: {self._video_source_config.mode}")
        self._append_log(f"Recommended model format: {self._hardware.info.recommended_model_format}")
        if len(self._inference_workers) > 1:
            cam_list = ", ".join(w.camera_id for w in self._inference_workers)
            self._append_log(f"Multi-camera pool active ({len(self._inference_workers)}): {cam_list}")
        self._refresh_pool_banner()
        self._output_dispatcher.start()
        self._gpio_worker.start()
        for worker in self._inference_workers:
            worker.start()
        for watchdog in self._watchdogs:
            watchdog.start()

    def _append_log(self, message: str) -> None:
        self.console.appendPlainText(message)
        self.statusBar().showMessage(message, 5000)
        log.info(message)

    def _publish_inference_outputs(self, frame: object, camera_id: str) -> None:
        if isinstance(frame, dict):
            self._output_dispatcher.publish(inference_payload_from_frame(frame, camera_id=camera_id))

    def _update_telemetry(self, telemetry: dict) -> None:
        self._latest_telemetry = dict(telemetry)
        capture_fps = float(telemetry.get('capture_fps', 0.0))
        inference_fps = float(telemetry.get('inference_fps', 0.0))
        latency_ms = float(telemetry.get('latency_ms', 0.0))
        self.fps_capture.setText(f"{capture_fps:.1f}")
        self.fps_inference.setText(f"{inference_fps:.1f}")
        self.latency.setText(f"{latency_ms:.1f} ms")
        self.ram.setText(f"{telemetry.get('ram_mb', 0.0):.0f} MB")
        self.vram.setText(f"{telemetry.get('vram_mb', 0.0):.0f} MB")
        self.temperature.setText(f"{telemetry.get('soc_temp_c', 0.0):.1f} °C")
        self.health_bar.setValue(min(100, max(0, 100 - int(latency_ms))))
        if hasattr(self, "fps_capture_spark"):
            self.fps_capture_spark.push(capture_fps)
            self.fps_inference_spark.push(inference_fps)
            self.latency_spark.push(latency_ms)
        self._refresh_live_summary()
        try:
            self._telemetry_log.maybe_record(self._latest_telemetry)
        except OSError as exc:
            log.warning("telemetry log write failed: %s", exc)

    _MAX_RESTARTS = 5

    def _restart_inference(self) -> None:
        self._restart_count = getattr(self, "_restart_count", 0) + 1
        if self._restart_count > self._MAX_RESTARTS:
            self._append_log(
                f"Watchdog: aborting auto-restart after {self._MAX_RESTARTS} attempts."
                " Inference will stay stopped — review the source/model and restart the app."
            )
            return
        self._append_log(
            f"Restarting inference pool (attempt {self._restart_count}/{self._MAX_RESTARTS})..."
        )
        self._unwire_threads()
        for watchdog in self._watchdogs:
            watchdog.request_stop()
        for worker in self._inference_workers:
            if worker.isRunning():
                worker.request_stop()
                worker.wait(2000)
        for watchdog in self._watchdogs:
            watchdog.wait(1000)

        self._inference_workers = self._create_inference_workers()
        self._inference_worker = self._inference_workers[0]
        self._watchdogs = [Watchdog(worker, parent=self) for worker in self._inference_workers]
        self._watchdog = self._watchdogs[0]
        self._frozen_cameras = set()
        self._rebuild_video_view()
        self._wire_threads()
        for watchdog in self._watchdogs:
            watchdog.start()
        for worker in self._inference_workers:
            worker.start()
        self._refresh_pool_banner()

    def closeEvent(self, event) -> None:  # noqa: N802
        self.shutdown()
        super().closeEvent(event)

    def shutdown(self) -> None:
        """Idempotent teardown: stop threads, flush configs, release captures."""
        if getattr(self, "_shutdown_started", False):
            return
        self._shutdown_started = True

        try:
            self.forge_panel.save_state()
        except Exception as exc:
            self._append_log(f"Forge panel state save failed: {exc}")
        try:
            save_inference_source_config(VIDEO_SOURCE_PATH, self._video_source_config)
        except OSError as exc:
            self._append_log(f"Video source config save failed: {exc}")

        for async_worker in list(self._workers):
            try:
                async_worker.cancel()
            except RuntimeError:
                pass
        for async_worker in list(self._workers):
            if async_worker.isRunning():
                async_worker.wait(1500)

        for watchdog in self._watchdogs:
            watchdog.request_stop()
        self._output_dispatcher.stop()
        self._gpio_worker.request_stop()
        for worker in self._inference_workers:
            worker.request_stop()
        for watchdog in self._watchdogs:
            watchdog.wait(1500)
        self._gpio_worker.wait(1500)
        for worker in self._inference_workers:
            worker.wait(2500)
        try:
            self._gpio_worker._backend.close()
        except Exception as exc:
            log.warning("GPIO backend close failed: %s", exc)


def main() -> int:
    parser = argparse.ArgumentParser(description="EdgeVision Control Hub")
    parser.add_argument("--headless", action="store_true", help="Run without opening the Qt UI")
    parser.add_argument(
        "--health",
        action="store_true",
        help="Validate config + ping Forge and exit (0=healthy, 1=unhealthy)",
    )
    args = parser.parse_args()

    settings = Settings.load(".env")
    log_path = configure_logging(log_dir=Path(settings.log_dir) if settings.log_dir else None)
    log.info("EdgeVision Control Hub starting (log file: %s)", log_path)

    if args.health:
        return run_healthcheck(settings)
    if args.headless:
        return run_headless(settings)

    problems = settings.validate()
    for problem in problems:
        log.warning("settings: %s", problem)

    app = QApplication([])
    app.setFont(QFont("Inter", 10))
    hardware = _hardware_for(settings)
    window = MainWindow(hardware, settings=settings)
    window.show()
    install_signal_handlers(app.quit)
    app.aboutToQuit.connect(window.shutdown)
    return app.exec()


def _hardware_for(settings: Settings) -> HardwareManager:
    forced = settings.hardware_override or None
    if settings.simulation_mode:
        return HardwareManager(force_simulation=True)
    if forced:
        return HardwareManager(forced_kind=forced)
    return HardwareManager()


def run_healthcheck(settings: Settings | None = None) -> int:
    """Validate config + ping Forge. Returns 0 if healthy, 1 otherwise."""
    settings = settings or Settings.load(".env")
    problems: list[str] = list(settings.validate())

    if settings.has_forge_credentials and settings.forge_url:
        forge = ForgeManager(settings.forge_url, retry_attempts=settings.http_retry_attempts)
        if settings.forge_token:
            forge.set_token(settings.forge_token)
        elif settings.forge_username and settings.forge_password:
            forge.set_basic_auth(settings.forge_username, settings.forge_password)
        try:
            forge.ping()
            print("forge: ok")
        except Exception as exc:
            problems.append(f"forge ping failed: {exc}")

    if problems:
        for problem in problems:
            print(f"unhealthy: {problem}")
        return 1
    print("healthy")
    return 0


def run_headless(settings: Settings | None = None) -> int:
    settings = settings or Settings.load(".env")
    for problem in settings.validate():
        print(f"warning: {problem}")
    hardware = _hardware_for(settings)
    print("EdgeVision Control Hub headless mode")
    print(f"Hardware: {hardware.info.name}")
    print(f"Recommended model format: {hardware.info.recommended_model_format}")
    print(f"Forge URL: {settings.forge_url}")
    for i in range(3):
        print(f"Cycle {i + 1}: capture -> inference -> gpio dispatch")
        time.sleep(0.2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
