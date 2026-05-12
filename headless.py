"""Headless inference runner — sin GUI, inferencia FP32 completa, GPIO + protocolos de red.

Uso:
    uv run python headless.py
    uv run python headless.py --env .env.local
    uv run python headless.py --model models/forge_project_5.pt --conf 0.25 --imgsz 640
    uv run python headless.py --print-detections
    uv run python headless.py --print-detections --detections-format json
"""

from __future__ import annotations

import argparse
import json
import logging
import queue
import signal
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")  # must be set before cv2 import

import cv2
import torch

cv2.setLogLevel(3)  # also silence at runtime (belt-and-suspenders)

from core.config_store import load_gpio_assignments, get_last_project_id
from core.gpio_backend import select_backend
from core.gpio_dispatch import GPIODispatcher
from core.hardware_manager import HardwareManager
from core.logging_config import configure as configure_logging
from core.output_adapters import InferenceOutputDispatcher, inference_payload_from_frame
from core.settings import Settings
from core.video_source import (
    VIDEO_SOURCE_PATH,
    load_inference_source_config,
    open_capture,
    resolve_video_source_candidates,
)

log = logging.getLogger("headless")


# ---------------------------------------------------------------------------
# GPIO worker thread
# ---------------------------------------------------------------------------

class GPIOWorker(threading.Thread):
    def __init__(self, hardware: HardwareManager, settings: Settings) -> None:
        super().__init__(name="gpio-worker", daemon=True)
        self._hardware = hardware
        self._simulation = hardware.is_simulation()
        self._backend = select_backend(simulation=self._simulation)
        self._dispatcher = GPIODispatcher(dedupe_seconds=settings.gpio_dedupe_seconds)
        self._dispatcher_lock = threading.Lock()
        self._events: queue.Queue[tuple[str, str, bool]] = queue.Queue()
        self._pulse_seconds = max(0.0, float(settings.gpio_pulse_seconds))
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def enqueue(self, label: str, camera_id: str, active: bool) -> None:
        self._events.put((label, camera_id, active))

    def set_assignments(self, assignments: dict[str, str]) -> None:
        with self._dispatcher_lock:
            self._dispatcher.set_assignments(assignments)

    def run(self) -> None:
        log.info("GPIO worker started (backend=%s, sim=%s)", self._backend.name, self._simulation)
        while not self._stop_event.is_set():
            try:
                label, camera_id, active = self._events.get(timeout=0.25)
            except queue.Empty:
                continue

            with self._dispatcher_lock:
                decision = self._dispatcher.decide(label, camera_id, active)

            if not decision.fire:
                continue

            port = decision.port
            cam_tag = f" (cam {camera_id})" if camera_id else ""
            if port and active:
                driven = self._backend.pulse(port, self._pulse_seconds)
                outcome = "ok" if driven else "no-driver"
                if self._simulation:
                    log.info("[SIM] GPIO %s -> %s on %s%s", label, active, port, cam_tag)
                else:
                    log.info("GPIO %s -> %s on %s via %s (%s)%s", label, active, port, self._backend.name, outcome, cam_tag)
            elif not port:
                log.debug("GPIO event %s -> %s — sin puerto asignado%s", label, active, cam_tag)


# ---------------------------------------------------------------------------
# Watchdog thread
# ---------------------------------------------------------------------------

class Watchdog(threading.Thread):
    def __init__(self, get_heartbeat: Any, timeout_s: float, on_freeze: Any) -> None:
        super().__init__(name="watchdog", daemon=True)
        self._get_heartbeat = get_heartbeat
        self._timeout_s = timeout_s
        self._on_freeze = on_freeze
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        while not self._stop_event.wait(timeout=0.5):
            age = time.monotonic() - self._get_heartbeat()
            if age > self._timeout_s:
                log.warning("Watchdog: inference freeze detected (%.1fs). Reiniciando...", age)
                self._on_freeze()
                return


# ---------------------------------------------------------------------------
# Inference worker thread
# ---------------------------------------------------------------------------

class InferenceWorker(threading.Thread):
    def __init__(
        self,
        *,
        model_path: Path,
        settings: Settings,
        hardware: HardwareManager,
        gpio_worker: GPIOWorker,
        output_dispatcher: InferenceOutputDispatcher,
        conf: float,
        imgsz: int,
        camera_id: str = "0",
        video_source: Any = None,
        print_detections: bool = False,
        detections_format: str = "human",
        preview_queue: "queue.Queue[Any] | None" = None,
        preloaded_model: Any = None,
    ) -> None:
        super().__init__(name=f"inference-{camera_id}", daemon=True)
        self._model_path = model_path
        self._settings = settings
        self._hardware = hardware
        self._gpio = gpio_worker
        self._output = output_dispatcher
        self._conf = conf
        self._imgsz = imgsz
        self._camera_id = camera_id
        self._video_source = video_source
        self._print_detections = print_detections
        self._detections_format = detections_format
        self._preview_queue = preview_queue
        self._stop_event = threading.Event()
        self._heartbeat = time.monotonic()
        self._model: Any = preloaded_model
        self._capture: cv2.VideoCapture | None = None
        self._device = "cuda:0" if torch.cuda.is_available() else "cpu"
        self._read_failures = 0
        self._active_states: dict[str, bool] = {}

    def stop(self) -> None:
        self._stop_event.set()

    def heartbeat(self) -> float:
        return self._heartbeat

    # -- model -----------------------------------------------------------------

    def _load_model(self) -> None:
        if self._model is not None:
            return  # already provided by caller
        if not self._model_path.exists():
            log.error("Modelo no encontrado: %s", self._model_path)
            return
        try:
            from ultralytics import YOLO
            self._model = YOLO(str(self._model_path))
            self._model.to(self._device)
            log.info("Modelo cargado: %s (device=%s, FP32)", self._model_path.name, self._device)
        except Exception as exc:
            log.error("Error cargando modelo: %s", exc)
            self._model = None

    # -- capture ---------------------------------------------------------------

    def _open_capture(self) -> cv2.VideoCapture | None:
        if self._video_source is None:
            return None
        cap = open_capture(self._video_source, is_jetson=self._hardware.info.kind == "jetson")
        if cap is not None:
            log.info("Fuente de video abierta: %s (%s)", self._video_source.label, self._video_source.source)
        return cap

    # -- preview ---------------------------------------------------------------

    def _draw_boxes(self, frame: Any, detections: list[dict]) -> Any:
        out = frame.copy()
        for d in detections:
            x1, y1, x2, y2 = (int(v) for v in d["bbox"])
            label = f"{d['label']} {d['confidence']:.0%}"
            cv2.rectangle(out, (x1, y1), (x2, y2), (0, 255, 0), 2)
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
            cv2.rectangle(out, (x1, y1 - th - 6), (x1 + tw + 4, y1), (0, 255, 0), -1)
            cv2.putText(out, label, (x1 + 2, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1, cv2.LINE_AA)
        return out

    # -- detection output ------------------------------------------------------

    def _print_frame_detections(self, detections: list[dict]) -> None:
        ts = time.strftime("%H:%M:%S")
        if self._detections_format == "json":
            record = {
                "ts": ts,
                "cam": self._camera_id,
                "count": len(detections),
                "detections": detections,
            }
            sys.stdout.write(json.dumps(record) + "\n")
            sys.stdout.flush()
        else:
            if not detections:
                return
            labels = ", ".join(
                f"{d['label']} ({d['confidence']:.0%})" for d in detections
            )
            sys.stdout.write(f"[{ts}][cam {self._camera_id}] {len(detections)} det — {labels}\n")
            sys.stdout.flush()

    # -- inference step --------------------------------------------------------

    def _run_detections(self, frame: Any) -> list[dict]:
        if self._model is None or frame is None:
            return []
        try:
            results = self._model.predict(
                frame,
                verbose=False,
                conf=self._conf,
                imgsz=self._imgsz,
                device=self._device,
            )
        except Exception as exc:
            log.warning("Inferencia fallida: %s", exc)
            return []
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
            cls_vals = boxes.cls.cpu().tolist()
            conf_vals = boxes.conf.cpu().tolist()
        except Exception:
            return []
        for bbox, cls_id, confidence in zip(xyxy, cls_vals, conf_vals):
            label = str(names.get(int(cls_id), int(cls_id)))
            detections.append({
                "label": label,
                "confidence": round(float(confidence), 4),
                "bbox": [round(float(v), 2) for v in bbox[:4]],
                "class_id": int(cls_id),
            })
        return detections

    def _dispatch_gpio(self, detections: list[dict]) -> None:
        current_labels = {d["label"] for d in detections}
        fired: set[str] = set()
        for d in detections:
            label = d["label"]
            if label not in fired:
                fired.add(label)
                if not self._active_states.get(label):
                    self._active_states[label] = True
                    self._gpio.enqueue(label, self._camera_id, True)
        for label in list(self._active_states):
            if self._active_states[label] and label not in current_labels:
                self._active_states[label] = False
                self._gpio.enqueue(label, self._camera_id, False)

    def _step(self) -> None:
        self._heartbeat = time.monotonic()

        if self._capture is None:
            self._capture = self._open_capture()
            if self._capture is None:
                log.debug("Sin fuente de video disponible, reintentando...")
                time.sleep(2.0)
                return

        ok, frame = self._capture.read()
        if not ok or frame is None:
            self._read_failures += 1
            if self._read_failures >= 3:
                log.warning("Fuente de video perdida, reintentando...")
                self._capture.release()
                self._capture = None
                self._read_failures = 0
            return
        self._read_failures = 0

        detections = self._run_detections(frame)
        self._dispatch_gpio(detections)

        h, w = frame.shape[:2]
        payload = inference_payload_from_frame(
            {
                "detections": detections,
                "source": "",
                "source_label": "",
                "simulation": False,
                "frame_size": (w, h),
            },
            camera_id=self._camera_id,
        )
        self._output.publish(payload)

        if self._preview_queue is not None:
            annotated = self._draw_boxes(frame, detections)
            try:
                self._preview_queue.put_nowait((self._camera_id, annotated))
            except queue.Full:
                pass

        if self._print_detections:
            self._print_frame_detections(detections)
        elif detections:
            labels_str = ", ".join(f"{d['label']} {d['confidence']:.2f}" for d in detections[:5])
            log.debug("[cam %s] %d detecciones: %s", self._camera_id, len(detections), labels_str)

    # -- thread loop -----------------------------------------------------------

    def run(self) -> None:
        self._heartbeat = time.monotonic()  # reset so watchdog doesn't fire during model load
        self._load_model()
        self._heartbeat = time.monotonic()  # reset again after load; inference loop starts now
        log.info("Worker de inferencia iniciado (cam=%s, conf=%.2f, imgsz=%d)", self._camera_id, self._conf, self._imgsz)
        while not self._stop_event.is_set():
            try:
                self._step()
            except Exception as exc:
                log.error("Error en step de inferencia: %s", exc, exc_info=True)
                time.sleep(0.5)
        if self._capture is not None:
            self._capture.release()
        log.info("Worker de inferencia detenido (cam=%s)", self._camera_id)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _find_model(settings: Settings) -> Path:
    model_dir = Path(settings.model_dir)
    for ext in ("*.engine", "*.pt", "*.onnx"):
        matches = sorted(model_dir.glob(ext))
        if matches:
            return matches[0]
    return model_dir / "model.pt"


def main() -> None:
    parser = argparse.ArgumentParser(description="EdgeVision headless inference runner")
    parser.add_argument("--env", default=".env", help="Ruta al archivo .env (default: .env)")
    parser.add_argument("--model", default="", help="Ruta al modelo (override del .env)")
    parser.add_argument("--conf", type=float, default=0.25, help="Umbral de confianza (default: 0.25)")
    parser.add_argument("--imgsz", type=int, default=640, help="Tamaño de imagen para inferencia (default: 640)")
    parser.add_argument("--watchdog-timeout", type=float, default=0.0, help="Watchdog timeout en segundos (0 = usar valor del .env)")
    parser.add_argument("--preview", action="store_true", help="Muestra preview con bounding boxes via OpenCV (requiere display)")
    parser.add_argument("--print-detections", action="store_true", help="Imprime detecciones a stdout en tiempo real")
    parser.add_argument("--detections-format", default="human", choices=["human", "json"], help="Formato de salida de detecciones (default: human)")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    settings = Settings.load(args.env)
    configure_logging(log_dir=settings.log_dir or None, level=args.log_level)

    problems = settings.validate()
    if problems:
        for p in problems:
            log.warning("Config: %s", p)

    forced = settings.hardware_override or None
    if settings.simulation_mode:
        hardware = HardwareManager(force_simulation=True)
    elif forced:
        hardware = HardwareManager(forced_kind=forced)
    else:
        hardware = HardwareManager()
    log.info("Hardware: %s (sim=%s)", hardware.info.name, hardware.is_simulation())

    model_path = Path(args.model) if args.model else _find_model(settings)
    log.info("Modelo: %s", model_path)

    # Load model once in main thread — avoids 4 simultaneous loads blocking the GIL
    preloaded_model: Any = None
    if model_path.exists():
        try:
            from ultralytics import YOLO
            _device = "cuda:0" if torch.cuda.is_available() else "cpu"
            preloaded_model = YOLO(str(model_path))
            preloaded_model.to(_device)
            log.info("Modelo cargado: %s (device=%s, FP32)", model_path.name, _device)
        except Exception as exc:
            log.error("Error cargando modelo: %s", exc)
    else:
        log.error("Modelo no encontrado: %s", model_path)

    output_dispatcher = InferenceOutputDispatcher(
        settings.output_config,
        log=lambda msg: log.info("[output] %s", msg),
    )
    output_dispatcher.start()
    protocols = settings.output_config.enabled_protocols()
    log.info("Protocolos activos: %s", protocols or ["ninguno"])

    gpio_worker = GPIOWorker(hardware, settings)

    # Load GPIO assignments for the last active project
    try:
        all_assignments = load_gpio_assignments()
        project_id = get_last_project_id()
        gpio_assignments: dict[str, str] = {}
        if project_id is not None:
            gpio_assignments = all_assignments.get(str(project_id), {})
        if not gpio_assignments and all_assignments:
            # Fallback: use first available project
            gpio_assignments = next(iter(all_assignments.values()), {})
        if gpio_assignments:
            gpio_worker.set_assignments(gpio_assignments)
            log.info("GPIO assignments cargados: %d labels (proyecto %s)", len(gpio_assignments), project_id)
        else:
            log.info("Sin GPIO assignments configurados")
    except Exception as exc:
        log.debug("No se pudieron cargar GPIO assignments: %s", exc)

    # Resolve camera candidates once — each worker gets its own pre-resolved source.
    # Filter to available=True only: resolve_video_source_candidates appends unavailable
    # discovered devices (/dev/videoN control nodes) as fallback, which we don't want.
    source_cfg = load_inference_source_config(VIDEO_SOURCE_PATH)
    try:
        all_candidates, _ = resolve_video_source_candidates(source_cfg, hardware)
        candidates = [c for c in all_candidates if c.available]
        if not candidates:
            candidates = all_candidates  # last resort: use all if none marked available
    except Exception:
        candidates = []

    if candidates:
        log.info("Fuentes de video: %s", [c.source for c in candidates])
    else:
        log.warning("Sin fuentes de video configuradas — arrancando sin cámara")

    # One preview queue per worker (maxsize=1 so main thread always gets latest frame)
    preview_queues: list["queue.Queue[Any]"] = (
        [queue.Queue(maxsize=1) for _ in candidates] if args.preview else []
    )

    watchdog_timeout = args.watchdog_timeout if args.watchdog_timeout > 0 else settings.watchdog_timeout_seconds

    workers: list[InferenceWorker] = []

    def _make_worker(idx: int, source: Any) -> InferenceWorker:
        pq = preview_queues[idx] if preview_queues else None
        return InferenceWorker(
            model_path=model_path,
            settings=settings,
            hardware=hardware,
            gpio_worker=gpio_worker,
            output_dispatcher=output_dispatcher,
            conf=args.conf,
            imgsz=args.imgsz,
            camera_id=str(idx),
            video_source=source,
            print_detections=args.print_detections,
            detections_format=args.detections_format,
            preview_queue=pq,
            preloaded_model=preloaded_model,
        )

    for idx, src in enumerate(candidates or [None]):
        workers.append(_make_worker(idx, src))

    watchdogs: list[Watchdog] = []
    for w in workers:
        def make_on_freeze(worker: InferenceWorker, widx: int) -> Any:
            def on_freeze() -> None:
                log.warning("Reiniciando worker %s...", worker.name)
                worker.stop()
                worker.join(timeout=3.0)
                new_w = _make_worker(widx, worker._video_source)
                new_w.start()
                workers[widx] = new_w
            return on_freeze

        wd = Watchdog(
            get_heartbeat=w.heartbeat,
            timeout_s=watchdog_timeout,
            on_freeze=make_on_freeze(w, workers.index(w)),
        )
        watchdogs.append(wd)

    # Shutdown handler
    stop_event = threading.Event()

    def shutdown(signum: int, frame: Any) -> None:
        log.info("Señal %d recibida — deteniendo...", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Start everything
    gpio_worker.start()
    for w in workers:
        w.start()
    for wd in watchdogs:
        wd.start()

    log.info(
        "EdgeVision headless iniciado — %d cámara(s), modelo=%s, conf=%.2f, imgsz=%d",
        len(workers), model_path.name, args.conf, args.imgsz,
    )

    # Preview loop runs in main thread (cv2.imshow is not thread-safe with Qt backend)
    if args.preview and preview_queues:
        while not stop_event.is_set():
            for idx, pq in enumerate(preview_queues):
                try:
                    cam_id, frame = pq.get_nowait()
                    cv2.imshow(f"Cam {cam_id}", frame)
                except queue.Empty:
                    pass
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                stop_event.set()
                break
        cv2.destroyAllWindows()
    else:
        stop_event.wait()

    log.info("Deteniendo workers...")
    for wd in watchdogs:
        wd.stop()
    for w in workers:
        w.stop()
    gpio_worker.stop()

    for w in workers:
        w.join(timeout=5.0)
    gpio_worker.join(timeout=3.0)

    output_dispatcher.stop()
    log.info("EdgeVision headless detenido.")


if __name__ == "__main__":
    main()
