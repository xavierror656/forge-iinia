"""Hardware-facing GPIO backends.

We don't ship our own pin driver; ``gpiozero`` already abstracts Jetson and
Raspberry Pi (with the ``lgpio`` or ``rpi.gpio`` pin factories underneath).
This module wraps it so the rest of the codebase can talk to GPIO through a
small, mockable interface and so a development machine without GPIO falls
back gracefully.

The backend exposes one operation: ``pulse(port, duration_s)``. Detection
events are one-shots (the ``DetectionState`` latches once and re-fires only
after a release), so we drive the line high for ``duration_s`` and back to
low — no need for a long-running active/inactive state machine here.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable
from typing import Protocol

log = logging.getLogger(__name__)

PORT_RE = re.compile(r"(?:GPIO)?\s*(\d+)", re.IGNORECASE)


def parse_port(port: str) -> int | None:
    """Extract a BCM pin number from strings like ``"GPIO12"`` or ``"12"``."""
    if not port:
        return None
    match = PORT_RE.search(port.strip())
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


class GPIOBackend(Protocol):
    name: str
    available: bool

    def pulse(self, port: str, duration_s: float = 0.1) -> bool: ...

    def close(self) -> None: ...


class MockGPIOBackend:
    """Always-available no-op backend for development machines and tests."""

    name = "mock"
    available = True

    def __init__(self) -> None:
        self.events: list[tuple[str, float]] = []

    def pulse(self, port: str, duration_s: float = 0.1) -> bool:
        self.events.append((port, duration_s))
        return True

    def close(self) -> None:
        return None


class GpiozeroBackend:
    """Drives real GPIO pins via the ``gpiozero`` library."""

    name = "gpiozero"

    def __init__(self, output_factory: Callable[[int], object] | None = None) -> None:
        self._lock = threading.Lock()
        self._lines: dict[int, object] = {}
        self._output_factory: Callable[[int], object] | None = (
            output_factory if output_factory is not None else self._default_factory()
        )
        self.available = self._output_factory is not None

    @staticmethod
    def _default_factory() -> Callable[[int], object] | None:
        try:
            from gpiozero import DigitalOutputDevice
        except Exception as exc:  # pragma: no cover - import guard
            log.info("gpiozero unavailable, GPIO will be inert: %s", exc)
            return None

        def make(pin: int) -> object:
            return DigitalOutputDevice(pin, active_high=True, initial_value=False)

        return make

    def _line_for(self, pin: int) -> object | None:
        line = self._lines.get(pin)
        if line is not None:
            return line
        if self._output_factory is None:
            return None
        try:
            line = self._output_factory(pin)
        except Exception as exc:  # pragma: no cover - hardware-dependent
            log.warning("Failed to acquire GPIO pin %s: %s", pin, exc)
            return None
        self._lines[pin] = line
        return line

    def pulse(self, port: str, duration_s: float = 0.1) -> bool:
        if not self.available:
            return False
        pin = parse_port(port)
        if pin is None:
            log.warning("Cannot parse GPIO port %r", port)
            return False
        with self._lock:
            line = self._line_for(pin)
            if line is None:
                return False
            try:
                line.on()  # type: ignore[attr-defined]
            except Exception as exc:  # pragma: no cover
                log.warning("GPIO pin %s on() failed: %s", pin, exc)
                return False
        time.sleep(max(0.0, float(duration_s)))
        with self._lock:
            try:
                line.off()  # type: ignore[attr-defined]
            except Exception as exc:  # pragma: no cover
                log.warning("GPIO pin %s off() failed: %s", pin, exc)
                return False
        return True

    def close(self) -> None:
        with self._lock:
            for line in self._lines.values():
                try:
                    line.close()  # type: ignore[attr-defined]
                except Exception:
                    pass
            self._lines.clear()


def select_backend(*, simulation: bool) -> GPIOBackend:
    """Return the right backend for the current environment."""
    if simulation:
        return MockGPIOBackend()
    real = GpiozeroBackend()
    if real.available:
        return real
    log.info("Falling back to MockGPIOBackend (gpiozero not available)")
    return MockGPIOBackend()
