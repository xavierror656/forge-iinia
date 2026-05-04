"""Plain dataclasses for inference / telemetry state.

These have no Qt dependency so they can be imported from tests without
spinning up an event loop.
"""

from __future__ import annotations

from dataclasses import dataclass


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
    """Tracks consecutive-frame latching for a single label.

    Counts ``fires`` (transitions to latched) and ``misses`` (streak broken
    before reaching threshold) so the UI / telemetry log can surface a
    quality signal — high misses means the model flickers.
    """

    label: str
    consecutive_frames: int = 0
    threshold: int = 3
    latched: bool = False
    fires: int = 0
    misses: int = 0

    def register(self, detected: bool) -> bool:
        if detected:
            self.consecutive_frames += 1
        else:
            if 0 < self.consecutive_frames < self.threshold and not self.latched:
                self.misses += 1
            self.consecutive_frames = 0
            self.latched = False

        if self.consecutive_frames >= self.threshold and not self.latched:
            self.latched = True
            self.fires += 1
            return True

        return False
