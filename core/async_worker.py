"""Generic async worker utilities for Qt threads."""

from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtCore import QObject, QThread, pyqtSignal


class AsyncWorker(QThread):
    """Run a callable off the UI thread and emit result or error."""

    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, fn: Callable[[], Any], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:
        try:
            self.finished_ok.emit(self._fn())
        except Exception as exc:  # pragma: no cover - defensive async wrapper
            self.failed.emit(str(exc))
