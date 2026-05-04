"""Dedupe and routing logic for GPIO trigger events.

Lives outside the Qt thread so it can be unit-tested without spinning up
``QApplication``. ``GPIOWorker`` in ``main.py`` delegates here for the
non-IO decisions.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(slots=True)
class DispatchDecision:
    fire: bool
    label: str
    camera_id: str
    active: bool
    port: str
    reason: str  # "fired" | "deduped" | "released"


class GPIODispatcher:
    """Deduplicates label triggers across multiple cameras.

    The hub today only emits ``active=True`` events (one-shot fires when the
    detection state latches). When several cameras see the same label within
    a short window we don't want each to drive its own GPIO pulse, so this
    class drops re-fires of a label inside ``dedupe_seconds``.
    """

    def __init__(
        self,
        *,
        dedupe_seconds: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._dedupe = max(0.0, float(dedupe_seconds))
        self._clock = clock
        self._assignments: dict[str, str] = {}
        self._last_fire_at: dict[str, float] = {}

    def set_assignments(self, assignments: dict[str, str]) -> None:
        self._assignments = dict(assignments)

    def port_for(self, label: str) -> str:
        return self._assignments.get(label, "")

    def decide(self, label: str, camera_id: str, active: bool) -> DispatchDecision:
        port = self.port_for(label)
        if not active:
            return DispatchDecision(
                fire=False,
                label=label,
                camera_id=camera_id,
                active=False,
                port=port,
                reason="released",
            )
        now = self._clock()
        last = self._last_fire_at.get(label)
        if self._dedupe > 0 and last is not None and (now - last) < self._dedupe:
            return DispatchDecision(
                fire=False,
                label=label,
                camera_id=camera_id,
                active=True,
                port=port,
                reason="deduped",
            )
        self._last_fire_at[label] = now
        return DispatchDecision(
            fire=True,
            label=label,
            camera_id=camera_id,
            active=True,
            port=port,
            reason="fired",
        )
