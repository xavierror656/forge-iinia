"""Graceful-shutdown helpers.

When the hub is run as a systemd service or in a container the process is
killed with SIGTERM rather than via the window close button, so Qt's
``closeEvent`` never fires. This module installs signal handlers that turn
those signals into a normal application quit so cleanup runs.
"""

from __future__ import annotations

import signal
from collections.abc import Callable
from typing import Any


def install_signal_handlers(quit_fn: Callable[[], Any]) -> None:
    """Make SIGINT and SIGTERM call ``quit_fn`` exactly once.

    ``quit_fn`` should be a non-blocking call (e.g. ``QApplication.quit``)
    that lets the main loop unwind on its own.
    """
    handled = {"done": False}

    def _handler(signum: int, _frame: object) -> None:
        if handled["done"]:
            return
        handled["done"] = True
        quit_fn()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handler)
        except (OSError, ValueError):
            pass
