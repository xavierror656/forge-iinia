"""Generic async worker utilities for Qt threads."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QObject, QThread, pyqtSignal


class AsyncWorker(QThread):
    """Run a callable off the UI thread and emit result or error.

    Sets a thread-local cancellation flag during shutdown; the wrapped
    callable can check ``AsyncWorker.is_cancelled()`` for cooperative exits,
    but for short HTTP calls we just stop dispatching emits so a result that
    arrives after shutdown is dropped instead of touching destroyed widgets.
    """

    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    _local = threading.local()

    def __init__(self, fn: Callable[[], Any], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._fn = fn
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @classmethod
    def is_cancelled(cls) -> bool:
        return bool(getattr(cls._local, "cancelled", False))

    def run(self) -> None:
        AsyncWorker._local.cancelled = False
        try:
            result = self._fn()
        except Exception as exc:  # pragma: no cover - defensive async wrapper
            if not self._cancelled:
                self.failed.emit(str(exc))
            return
        finally:
            AsyncWorker._local.cancelled = False
        if not self._cancelled:
            self.finished_ok.emit(result)
