"""Model loading and TensorRT export utilities."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import torch

log = logging.getLogger(__name__)


def load_model(model_path: Path, *, device: str = "") -> Any:
    """Load a YOLO model (.pt / .onnx / .engine) onto the given device."""
    if not device:
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
    if not model_path.exists():
        raise FileNotFoundError(f"Modelo no encontrado: {model_path}")
    from ultralytics import YOLO
    model = YOLO(str(model_path))
    model.to(device)
    log.info("Modelo cargado: %s (device=%s)", model_path.name, device)
    return model


def export_tensorrt(
    model_path: Path,
    *,
    half: bool = True,
    imgsz: int = 640,
    device: str = "0",
    int8: bool = False,
    workspace: int = 4,
) -> Path:
    """Export a .pt model to TensorRT .engine format.

    Args:
        model_path: Path to the .pt source model.
        half:       FP16 precision (fastest on Jetson with Tensor Cores).
        imgsz:      Input resolution — must match what you'll use at runtime.
        device:     GPU index string (e.g. "0").
        int8:       INT8 quantization — needs calibration data, higher throughput.
        workspace:  TensorRT workspace size in GB.

    Returns:
        Path to the generated .engine file (same directory as source model).
    """
    if not model_path.exists():
        raise FileNotFoundError(f"Modelo no encontrado: {model_path}")

    log.info(
        "Exportando TensorRT: %s  half=%s  int8=%s  imgsz=%d",
        model_path.name, half, int8, imgsz,
    )
    from ultralytics import YOLO
    model = YOLO(str(model_path))
    exported: str = model.export(
        format="engine",
        half=half,
        imgsz=imgsz,
        device=device,
        int8=int8,
        workspace=workspace,
    )
    out = Path(exported)
    size_mb = out.stat().st_size / 1_000_000
    log.info("Engine guardado: %s  (%.1f MB)", out, size_mb)
    return out
