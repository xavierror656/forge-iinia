"""Runtime telemetry collection for inference workers."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path

from core.hardware_manager import HardwareManager


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

    def snapshot(self, *, elapsed_seconds: float) -> TelemetrySnapshot:
        fps = 1.0 / max(0.001, elapsed_seconds)
        return TelemetrySnapshot(
            capture_fps=fps,
            inference_fps=fps,
            latency_ms=elapsed_seconds * 1000.0,
            ram_mb=self._process_ram_mb(),
            vram_mb=0.0,
            soc_temp_c=self._soc_temp_c(),
            provider_name=self._hardware.info.name,
        )

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
