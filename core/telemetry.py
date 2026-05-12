"""Runtime telemetry collection for inference workers."""

from __future__ import annotations

import os
import time
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path

from core.hardware_manager import HardwareManager

_WINDOW = 30  # frames to keep for rolling FPS


@dataclass(slots=True)
class TelemetrySnapshot:
    capture_fps: float = 0.0
    inference_fps: float = 0.0
    latency_ms: float = 0.0
    ram_mb: float = 0.0
    vram_mb: float = 0.0
    soc_temp_c: float = 0.0
    provider_name: str = ""

    def as_dict(self) -> dict[str, float | str]:
        return asdict(self)


class TelemetryCollector:
    def __init__(self, hardware: HardwareManager) -> None:
        self._hardware = hardware
        self._page_size = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096
        # Separate rolling windows for capture rate and inference latency
        self._frame_ts: deque[float] = deque(maxlen=_WINDOW)   # wall time of each captured frame
        self._infer_ts: deque[float] = deque(maxlen=_WINDOW)   # wall time after inference done
        self._infer_ms: deque[float] = deque(maxlen=_WINDOW)   # pure inference duration (ms)

    def record_capture(self) -> None:
        """Call immediately after a successful capture.read()."""
        self._frame_ts.append(time.perf_counter())

    def record_inference(self, inference_ms: float) -> None:
        """Call immediately after model.predict(), with its duration in ms."""
        self._infer_ts.append(time.perf_counter())
        self._infer_ms.append(inference_ms)

    def snapshot(self) -> TelemetrySnapshot:
        return TelemetrySnapshot(
            capture_fps=self._rolling_fps(self._frame_ts),
            inference_fps=self._rolling_fps(self._infer_ts),
            latency_ms=self._rolling_mean(self._infer_ms),
            ram_mb=self._process_ram_mb(),
            vram_mb=0.0,
            soc_temp_c=self._soc_temp_c(),
            provider_name=self._hardware.info.name,
        )

    @staticmethod
    def _rolling_fps(ts: deque[float]) -> float:
        if len(ts) < 2:
            return 0.0
        span = ts[-1] - ts[0]
        return (len(ts) - 1) / span if span > 0.001 else 0.0

    @staticmethod
    def _rolling_mean(vals: deque[float]) -> float:
        return sum(vals) / len(vals) if vals else 0.0

    def _process_ram_mb(self) -> float:
        statm = Path("/proc/self/statm")
        try:
            parts = statm.read_text(encoding="utf-8").split()
            resident_pages = int(parts[1]) if len(parts) > 1 else 0
            return (resident_pages * self._page_size) / (1024 * 1024)
        except (OSError, ValueError, IndexError):
            return 0.0

    def _soc_temp_c(self) -> float:
        for source in self._hardware.temperature_sources():
            path = Path(source)
            try:
                raw = path.read_text(encoding="utf-8", errors="ignore").strip()
            except OSError:
                continue
            try:
                value = float(raw)
            except ValueError:
                continue
            return value / 1000.0 if value > 200 else value
        return 0.0
