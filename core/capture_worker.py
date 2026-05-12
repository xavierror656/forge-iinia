"""Async per-camera capture thread with exponential-backoff reconnection.

Used by both headless.py and main.py so that camera I/O never blocks inference.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

from core.video_source import VideoSourceChoice, open_capture

log = logging.getLogger(__name__)


class CaptureWorker(threading.Thread):
    """Reads frames from a single source into a 1-slot buffer continuously.

    Callers read latest_frame() without waiting on camera I/O.
    On stream loss the worker reconnects with exponential backoff (2s → 4s → … → 60s).
    """

    _INITIAL_BACKOFF: float = 2.0
    _MAX_BACKOFF: float = 60.0

    def __init__(
        self,
        source: VideoSourceChoice,
        *,
        is_jetson: bool = False,
        camera_id: str = "0",
    ) -> None:
        super().__init__(name=f"capture-{camera_id}", daemon=True)
        self._source = source
        self._is_jetson = is_jetson
        self._camera_id = camera_id
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._latest: Any = None
        self._connected = False

    # ------------------------------------------------------------------
    # Public API

    @property
    def camera_id(self) -> str:
        return self._camera_id

    @property
    def connected(self) -> bool:
        return self._connected

    def latest_frame(self) -> Any:
        """Return the most recent decoded frame, or None if not yet available."""
        with self._lock:
            return self._latest

    def stop(self) -> None:
        self._stop_event.set()

    # ------------------------------------------------------------------
    # Thread body

    def run(self) -> None:
        backoff = self._INITIAL_BACKOFF
        while not self._stop_event.is_set():
            cap = open_capture(self._source, is_jetson=self._is_jetson)
            if cap is None:
                self._connected = False
                log.warning(
                    "cam %s (%s): no disponible, reintentando en %.0fs",
                    self._camera_id, self._source.source, backoff,
                )
                self._stop_event.wait(timeout=backoff)
                backoff = min(backoff * 2.0, self._MAX_BACKOFF)
                continue

            log.info("cam %s: abierta → %s", self._camera_id, self._source.source)
            self._connected = True
            backoff = self._INITIAL_BACKOFF  # reset on successful connection
            failures = 0

            while not self._stop_event.is_set():
                ok, frame = cap.read()
                if not ok or frame is None:
                    failures += 1
                    if failures >= 5:
                        log.warning("cam %s: stream perdido, reconectando...", self._camera_id)
                        break
                    continue
                failures = 0
                with self._lock:
                    self._latest = frame

            cap.release()
            self._connected = False

        log.info("cam %s: capture worker detenido", self._camera_id)
