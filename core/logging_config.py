"""Centralized ``logging`` setup.

A single rotating file handler keeps the last few MB of activity on disk so
field issues can be diagnosed after the fact. The console handler stays at
INFO so the existing in-app log panel keeps working.

Call :func:`configure` once at process start. Re-calling it is a no-op so
tests and the headless mode can both initialize logging safely.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

DEFAULT_LOG_DIR = Path(
    os.environ.get("EDGEVISION_LOG_DIR")
    or (Path.home() / ".cache" / "edgevision")
)
LOG_FILE_NAME = "edgevision.log"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
MAX_BYTES = 2_000_000
BACKUP_COUNT = 5

_configured = False


def configure(
    *,
    level: int = logging.INFO,
    log_dir: Path | None = None,
    console: bool = True,
) -> Path:
    """Idempotent root-logger setup. Returns the active log file path."""
    global _configured
    target_dir = Path(log_dir or DEFAULT_LOG_DIR)
    target_path = target_dir / LOG_FILE_NAME
    if _configured:
        return target_path

    target_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    root = logging.getLogger()
    root.setLevel(level)

    file_handler = RotatingFileHandler(
        target_path,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    if console:
        stream = logging.StreamHandler()
        stream.setLevel(level)
        stream.setFormatter(formatter)
        root.addHandler(stream)

    _configured = True
    return target_path


def reset_for_tests() -> None:
    """Clear the configured flag and detach our handlers — only used by tests."""
    global _configured
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    _configured = False
