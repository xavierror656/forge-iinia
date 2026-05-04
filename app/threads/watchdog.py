"""Watchdog QThread that watches an inference worker's heartbeat."""

from __future__ import annotations

import time
from typing import Protocol

from PyQt6.QtCore import QObject, QThread, pyqtSignal


class _HasHeartbeat(Protocol):
    def heartbeat(self) -> float: ...


class Watchdog(QThread):
    restart_requested = pyqtSignal()
    log_message = pyqtSignal(str)

    def __init__(
        self,
        inference_worker: _HasHeartbeat,
        timeout_s: float = 2.5,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._inference_worker = inference_worker
        self._timeout_s = timeout_s
        self._stop_requested = False

    def request_stop(self) -> None:
        self._stop_requested = True

    def run(self) -> None:
        while not self._stop_requested:
            age = time.monotonic() - self._inference_worker.heartbeat()
            if age > self._timeout_s:
                self.log_message.emit("Watchdog detected inference freeze. Restart requested.")
                self.restart_requested.emit()
                return
            self.msleep(500)
