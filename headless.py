"""Headless inference runner — sin GUI, inferencia FP32 completa, GPIO + protocolos de red.

Uso:
    uv run python headless.py
    uv run python headless.py --preview --print-detections
    uv run python headless.py --model models/forge_project_5.pt --conf 0.25 --imgsz 640
    uv run python headless.py --export-trt          # exporta el modelo a TensorRT y sale
    uv run python headless.py --export-trt --int8   # INT8 (mayor throughput, requiere calibración)

Arquitectura:
    CaptureWorker  × N  →  frames en buffer 1-slot con backoff automático
    BatchInferenceWorker    →  model.predict([f0, f1, …]) en una sola llamada GPU
    GPIOWorker              →  despacha eventos GPIO
    Watchdog                →  reinicia BatchInferenceWorker si se congela
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")  # must be set before cv2 import

import cv2
import torch

cv2.setLogLevel(3)  # silence V4L2 backend probe warnings

from core.capture_worker import CaptureWorker
from core.config_store import get_last_project_id, load_gpio_assignments
from core.gpio_backend import select_backend
from core.gpio_dispatch import GPIODispatcher
from core.hardware_manager import HardwareManager
from core.logging_config import configure as configure_logging
from core.model_manager import export_tensorrt, load_model
from core.output_adapters import InferenceOutputDispatcher, inference_payload_from_frame
from core.settings import Settings
from core.video_source import (
    VIDEO_SOURCE_PATH,
    load_inference_source_config,
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
        log.info("GPIO worker iniciado (backend=%s, sim=%s)", self._backend.name, self._simulation)
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
                    log.info("[SIM] GPIO %s → %s on %s%s", label, active, port, cam_tag)
                else:
                    log.info(
                        "GPIO %s → %s on %s via %s (%s)%s",
                        label, active, port, self._backend.name, outcome, cam_tag,
                    )
            elif not port:
                log.debug("GPIO %s → %s — sin puerto%s", label, active, cam_tag)


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
                log.warning("Watchdog: freeze detectado (%.1fs). Reiniciando...", age)
                self._on_freeze()
                return


# ---------------------------------------------------------------------------
# Batch inference worker
# ---------------------------------------------------------------------------

class BatchInferenceWorker(threading.Thread):
    """Runs model.predict() on all camera frames in a single batched call."""

    def __init__(
        self,
        *,
        model: Any,
        capture_workers: list[CaptureWorker],
        gpio_worker: GPIOWorker,
        output_dispatcher: InferenceOutputDispatcher,
        conf: float,
        imgsz: int,
        print_detections: bool = False,
        detections_format: str = "human",
        preview_queues: dict[str, "queue.Queue[Any]"] | None = None,
    ) -> None:
        super().__init__(name="batch-inference", daemon=True)
        self._model = model
        self._captures = capture_workers
        self._gpio = gpio_worker
        self._output = output_dispatcher
        self._conf = conf
        self._imgsz = imgsz
        self._print_detections = print_detections
        self._detections_format = detections_format
        self._preview_queues: dict[str, queue.Queue[Any]] = preview_queues or {}
        self._device = "cuda:0" if torch.cuda.is_available() else "cpu"
        self._stop_event = threading.Event()
        self._heartbeat = time.monotonic()
        # Per-camera active label state for GPIO edge detection
        self._active_states: dict[str, dict[str, bool]] = {}

    def stop(self) -> None:
        self._stop_event.set()

    def heartbeat(self) -> float:
        return self._heartbeat

    # -- helpers ---------------------------------------------------------------

    def _parse_result(self, result: Any) -> list[dict]:
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

    def _dispatch_gpio(self, detections: list[dict], cam_id: str) -> None:
        states = self._active_states.setdefault(cam_id, {})
        current = {d["label"] for d in detections}
        fired: set[str] = set()
        for d in detections:
            lbl = d["label"]
            if lbl not in fired:
                fired.add(lbl)
                if not states.get(lbl):
                    states[lbl] = True
                    self._gpio.enqueue(lbl, cam_id, True)
        for lbl in list(states):
            if states[lbl] and lbl not in current:
                states[lbl] = False
                self._gpio.enqueue(lbl, cam_id, False)

    def _draw_boxes(self, frame: Any, detections: list[dict]) -> Any:
        out = frame.copy()
        for d in detections:
            x1, y1, x2, y2 = (int(v) for v in d["bbox"])
            label = f"{d['label']} {d['confidence']:.0%}"
            cv2.rectangle(out, (x1, y1), (x2, y2), (0, 255, 0), 2)
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
            cv2.rectangle(out, (x1, y1 - th - 6), (x1 + tw + 4, y1), (0, 255, 0), -1)
            cv2.putText(out, label, (x1 + 2, y1 - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1, cv2.LINE_AA)
        return out

    def _print_frame_detections(self, detections: list[dict], cam_id: str) -> None:
        ts = time.strftime("%H:%M:%S")
        if self._detections_format == "json":
            record = {"ts": ts, "cam": cam_id, "count": len(detections), "detections": detections}
            sys.stdout.write(json.dumps(record) + "\n")
            sys.stdout.flush()
        else:
            if not detections:
                return
            labels = ", ".join(f"{d['label']} ({d['confidence']:.0%})" for d in detections)
            sys.stdout.write(f"[{ts}][cam {cam_id}] {len(detections)} det — {labels}\n")
            sys.stdout.flush()

    # -- main loop -------------------------------------------------------------

    def _step(self) -> None:
        self._heartbeat = time.monotonic()

        # Collect latest frames from all cameras that have one ready
        batch_frames: list[Any] = []
        batch_ids: list[str] = []
        for cw in self._captures:
            frame = cw.latest_frame()
            if frame is not None:
                batch_frames.append(frame)
                batch_ids.append(cw.camera_id)

        if not batch_frames:
            time.sleep(0.005)
            return

        # Single batched GPU call for all cameras
        try:
            results = self._model.predict(
                batch_frames,
                verbose=False,
                conf=self._conf,
                imgsz=self._imgsz,
                device=self._device,
            )
        except Exception as exc:
            log.warning("Batch inference fallida: %s", exc)
            return

        for result, cam_id, frame in zip(results, batch_ids, batch_frames):
            detections = self._parse_result(result)

            self._dispatch_gpio(detections, cam_id)

            h, w = frame.shape[:2]
            payload = inference_payload_from_frame(
                {
                    "detections": detections,
                    "source": "",
                    "source_label": "",
                    "simulation": False,
                    "frame_size": (w, h),
                },
                camera_id=cam_id,
            )
            self._output.publish(payload)

            if cam_id in self._preview_queues:
                annotated = self._draw_boxes(frame, detections)
                try:
                    self._preview_queues[cam_id].put_nowait((cam_id, annotated))
                except queue.Full:
                    pass

            if self._print_detections:
                self._print_frame_detections(detections, cam_id)

    def run(self) -> None:
        self._heartbeat = time.monotonic()
        log.info(
            "Batch inference iniciado — %d cámara(s), conf=%.2f, imgsz=%d, device=%s",
            len(self._captures), self._conf, self._imgsz, self._device,
        )
        while not self._stop_event.is_set():
            try:
                self._step()
            except Exception as exc:
                log.error("Error en batch step: %s", exc, exc_info=True)
                time.sleep(0.5)
        log.info("Batch inference detenido")


# ---------------------------------------------------------------------------
# Platform-specific runners
# ---------------------------------------------------------------------------

def _run_jetson(
    *,
    args: Any,
    settings: Settings,
    hardware: HardwareManager,
    model_path: Path,
    preloaded_model: Any,
    gpio_worker: GPIOWorker,
    output_dispatcher: InferenceOutputDispatcher,
    candidates: list[Any],
    watchdog_timeout: float,
    stop_event: threading.Event,
) -> None:
    """Jetson path: async CaptureWorker × N + single BatchInferenceWorker."""
    capture_workers = [
        CaptureWorker(src, is_jetson=True, camera_id=str(idx))
        for idx, src in enumerate(candidates)
    ]

    preview_queues: dict[str, queue.Queue[Any]] = (
        {str(idx): queue.Queue(maxsize=1) for idx in range(len(capture_workers))}
        if args.preview and capture_workers else {}
    )

    def _make_batch_worker() -> BatchInferenceWorker:
        return BatchInferenceWorker(
            model=preloaded_model,
            capture_workers=capture_workers,
            gpio_worker=gpio_worker,
            output_dispatcher=output_dispatcher,
            conf=args.conf,
            imgsz=args.imgsz,
            print_detections=args.print_detections,
            detections_format=args.detections_format,
            preview_queues=preview_queues,
        )

    batch_worker = _make_batch_worker()

    def on_freeze() -> None:
        nonlocal batch_worker
        log.warning("Reiniciando batch inference worker...")
        batch_worker.stop()
        batch_worker.join(timeout=3.0)
        batch_worker = _make_batch_worker()
        batch_worker.start()

    watchdog = Watchdog(
        get_heartbeat=batch_worker.heartbeat,
        timeout_s=watchdog_timeout,
        on_freeze=on_freeze,
    )

    gpio_worker.start()
    for cw in capture_workers:
        cw.start()
    batch_worker.start()
    watchdog.start()

    log.info(
        "Jetson: %d cámara(s), batch inference, modelo=%s, conf=%.2f, imgsz=%d",
        len(capture_workers), model_path.name, args.conf, args.imgsz,
    )

    if args.preview and preview_queues:
        while not stop_event.is_set():
            for cam_id, pq in preview_queues.items():
                try:
                    cid, frame = pq.get_nowait()
                    cv2.imshow(f"Cam {cid}", frame)
                except queue.Empty:
                    pass
            if cv2.waitKey(1) & 0xFF == ord("q"):
                stop_event.set()
                break
        cv2.destroyAllWindows()
    else:
        stop_event.wait()

    watchdog.stop()
    batch_worker.stop()
    for cw in capture_workers:
        cw.stop()
    gpio_worker.stop()
    batch_worker.join(timeout=5.0)
    for cw in capture_workers:
        cw.join(timeout=3.0)
    gpio_worker.join(timeout=3.0)


def _run_simple(
    *,
    args: Any,
    settings: Settings,
    hardware: HardwareManager,
    model_path: Path,
    preloaded_model: Any,
    gpio_worker: GPIOWorker,
    output_dispatcher: InferenceOutputDispatcher,
    candidates: list[Any],
    watchdog_timeout: float,
    stop_event: threading.Event,
) -> None:
    """Non-Jetson path: simple per-camera inference loop, blocking capture.read().

    Placeholder for future Raspberry Pi / OpenVINO support.
    Each platform (raspi, openvino) will add its own runner here when ready.
    """
    import cv2 as _cv2

    device = "cpu"

    gpio_worker.start()
    log.info(
        "Simple: %d cámara(s), modelo=%s, conf=%.2f, imgsz=%d, device=%s",
        len(candidates), model_path.name, args.conf, args.imgsz, device,
    )

    active_states: dict[str, dict[str, bool]] = {}

    def _dispatch_gpio(detections: list[dict], cam_id: str) -> None:
        states = active_states.setdefault(cam_id, {})
        current = {d["label"] for d in detections}
        for d in detections:
            lbl = d["label"]
            if not states.get(lbl):
                states[lbl] = True
                gpio_worker.enqueue(lbl, cam_id, True)
        for lbl in list(states):
            if states[lbl] and lbl not in current:
                states[lbl] = False
                gpio_worker.enqueue(lbl, cam_id, False)

    while not stop_event.is_set():
        for idx, src in enumerate(candidates):
            from core.video_source import open_capture
            cap = open_capture(src, is_jetson=False)
            if cap is None:
                time.sleep(2.0)
                continue
            log.info("cam %s: abierta → %s", idx, src.source)
            failures = 0
            while not stop_event.is_set():
                ok, frame = cap.read()
                if not ok or frame is None:
                    failures += 1
                    if failures >= 5:
                        break
                    continue
                failures = 0
                if preloaded_model is None:
                    continue
                try:
                    results = preloaded_model.predict(
                        frame, verbose=False, conf=args.conf,
                        imgsz=args.imgsz, device=device,
                    )
                except Exception as exc:
                    log.warning("Inferencia fallida: %s", exc)
                    continue
                if not results:
                    continue
                cam_id = str(idx)
                boxes = getattr(results[0], "boxes", None)
                names = getattr(results[0], "names", {}) or {}
                detections: list[dict] = []
                if boxes is not None:
                    try:
                        for bbox, cls_id, conf_v in zip(
                            boxes.xyxy.cpu().tolist(),
                            boxes.cls.cpu().tolist(),
                            boxes.conf.cpu().tolist(),
                        ):
                            lbl = str(names.get(int(cls_id), int(cls_id)))
                            detections.append({
                                "label": lbl,
                                "confidence": round(float(conf_v), 4),
                                "bbox": [round(float(v), 2) for v in bbox[:4]],
                                "class_id": int(cls_id),
                            })
                    except Exception:
                        pass
                _dispatch_gpio(detections, cam_id)
                h, w = frame.shape[:2]
                output_dispatcher.publish(inference_payload_from_frame(
                    {"detections": detections, "source": "", "source_label": "",
                     "simulation": False, "frame_size": (w, h)},
                    camera_id=cam_id,
                ))
                if args.print_detections and detections:
                    ts = time.strftime("%H:%M:%S")
                    labels = ", ".join(f"{d['label']} ({d['confidence']:.0%})" for d in detections)
                    sys.stdout.write(f"[{ts}][cam {cam_id}] {len(detections)} det — {labels}\n")
                    sys.stdout.flush()
                if args.preview:
                    _cv2.imshow(f"Cam {cam_id}", frame)
                    if _cv2.waitKey(1) & 0xFF == ord("q"):
                        stop_event.set()
                        break
            cap.release()
        if not candidates:
            stop_event.wait(timeout=5.0)

    if args.preview:
        _cv2.destroyAllWindows()
    gpio_worker.stop()
    gpio_worker.join(timeout=3.0)


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
    parser.add_argument("--env", default=".env")
    parser.add_argument("--model", default="", help="Ruta al modelo (override del .env)")
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--watchdog-timeout", type=float, default=0.0,
                        help="Watchdog timeout en segundos (0 = usar valor del .env)")
    parser.add_argument("--preview", action="store_true",
                        help="Muestra preview con bounding boxes via OpenCV (requiere display)")
    parser.add_argument("--print-detections", action="store_true",
                        help="Imprime detecciones a stdout en tiempo real")
    parser.add_argument("--detections-format", default="human", choices=["human", "json"])
    parser.add_argument("--export-trt", action="store_true",
                        help="Exporta el modelo a TensorRT .engine y sale")
    parser.add_argument("--half", action="store_true", default=True,
                        help="FP16 para export TensorRT (default: True)")
    parser.add_argument("--int8", action="store_true",
                        help="INT8 para export TensorRT (mayor throughput)")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    settings = Settings.load(args.env)
    configure_logging(log_dir=settings.log_dir or None, level=args.log_level)

    for p in settings.validate():
        log.warning("Config: %s", p)

    if settings.simulation_mode:
        hardware = HardwareManager(force_simulation=True)
    elif (forced := settings.hardware_override or None):
        hardware = HardwareManager(forced_kind=forced)
    else:
        hardware = HardwareManager()
    log.info("Hardware: %s (sim=%s)", hardware.info.name, hardware.is_simulation())

    model_path = Path(args.model) if args.model else _find_model(settings)
    log.info("Modelo: %s", model_path)

    # TensorRT export — Jetson/CUDA only
    if args.export_trt:
        if hardware.info.kind != "jetson":
            log.error("--export-trt solo está disponible en Jetson (CUDA requerido)")
            sys.exit(1)
        try:
            engine_path = export_tensorrt(
                model_path,
                half=args.half,
                int8=args.int8,
                imgsz=args.imgsz,
            )
            print(f"Engine listo: {engine_path}")
        except Exception as exc:
            log.error("Export fallido: %s", exc)
            sys.exit(1)
        return

    # Load model once in main thread — all workers share the same instance
    try:
        _device = "cuda:0" if torch.cuda.is_available() else "cpu"
        preloaded_model = load_model(model_path, device=_device)
    except Exception as exc:
        log.error("Error cargando modelo: %s", exc)
        preloaded_model = None

    output_dispatcher = InferenceOutputDispatcher(
        settings.output_config,
        log=lambda msg: log.info("[output] %s", msg),
    )
    output_dispatcher.start()
    protocols = settings.output_config.enabled_protocols()
    log.info("Protocolos activos: %s", protocols or ["ninguno"])

    gpio_worker = GPIOWorker(hardware, settings)

    try:
        all_assignments = load_gpio_assignments()
        project_id = get_last_project_id()
        gpio_assignments: dict[str, str] = {}
        if project_id is not None:
            gpio_assignments = all_assignments.get(str(project_id), {})
        if not gpio_assignments and all_assignments:
            gpio_assignments = next(iter(all_assignments.values()), {})
        if gpio_assignments:
            gpio_worker.set_assignments(gpio_assignments)
            log.info("GPIO: %d labels (proyecto %s)", len(gpio_assignments), project_id)
        else:
            log.info("GPIO: sin assignments configurados")
    except Exception as exc:
        log.debug("GPIO assignments no disponibles: %s", exc)

    # Resolve camera candidates once — filter to available capture devices only
    source_cfg = load_inference_source_config(VIDEO_SOURCE_PATH)
    try:
        all_candidates, _ = resolve_video_source_candidates(source_cfg, hardware)
        candidates = [c for c in all_candidates if c.available] or all_candidates
    except Exception:
        candidates = []

    if candidates:
        log.info("Cámaras: %s", [c.source for c in candidates])
    else:
        log.warning("Sin fuentes de video — solo GPIO/protocolos activos")

    is_jetson = hardware.info.kind == "jetson"

    watchdog_timeout = (
        args.watchdog_timeout if args.watchdog_timeout > 0
        else settings.watchdog_timeout_seconds
    )

    stop_event = threading.Event()

    def shutdown(signum: int, frame: Any) -> None:
        log.info("Señal %d — deteniendo...", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    if is_jetson:
        _run_jetson(
            args=args,
            settings=settings,
            hardware=hardware,
            model_path=model_path,
            preloaded_model=preloaded_model,
            gpio_worker=gpio_worker,
            output_dispatcher=output_dispatcher,
            candidates=candidates,
            watchdog_timeout=watchdog_timeout,
            stop_event=stop_event,
        )
    else:
        log.info("Plataforma no-Jetson — usando modo simple (sin batch/async/TensorRT)")
        _run_simple(
            args=args,
            settings=settings,
            hardware=hardware,
            model_path=model_path,
            preloaded_model=preloaded_model,
            gpio_worker=gpio_worker,
            output_dispatcher=output_dispatcher,
            candidates=candidates,
            watchdog_timeout=watchdog_timeout,
            stop_event=stop_event,
        )

    output_dispatcher.stop()
    log.info("EdgeVision headless detenido.")


if __name__ == "__main__":
    main()
