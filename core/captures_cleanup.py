"""Disk-pressure cleanup for the ``captures/`` directory.

Captures accumulate forever — on a Jetson with 32 GB of eMMC the disk fills
in weeks. This module deletes the oldest matching files until the total
size is back under ``max_total_bytes`` and removes anything older than
``max_age_seconds``. The audit log file (``events.jsonl`` and its rotated
backups) is preserved.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from pathlib import Path

DEFAULT_MAX_TOTAL_BYTES = 500_000_000  # 500 MB
DEFAULT_MAX_AGE_SECONDS = 60 * 60 * 24 * 30  # 30 days
PROTECTED_PREFIXES = ("events.jsonl",)


def _candidate_files(directory: Path) -> Iterable[Path]:
    if not directory.exists():
        return ()
    return (
        p
        for p in directory.iterdir()
        if p.is_file() and not any(p.name.startswith(prefix) for prefix in PROTECTED_PREFIXES)
    )


def cleanup_captures(
    directory: Path,
    *,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    now: float | None = None,
) -> tuple[int, int]:
    """Returns (files_removed, bytes_removed)."""
    directory = Path(directory)
    if not directory.exists():
        return 0, 0

    cutoff = (now if now is not None else time.time()) - max_age_seconds
    removed = 0
    bytes_freed = 0

    files = list(_candidate_files(directory))
    for path in files:
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_mtime < cutoff:
            try:
                path.unlink()
                removed += 1
                bytes_freed += stat.st_size
            except OSError:
                continue

    files = list(_candidate_files(directory))
    sized: list[tuple[Path, int, float]] = []
    total = 0
    for path in files:
        try:
            stat = path.stat()
        except OSError:
            continue
        sized.append((path, stat.st_size, stat.st_mtime))
        total += stat.st_size

    if total <= max_total_bytes:
        return removed, bytes_freed

    sized.sort(key=lambda item: item[2])  # oldest first
    for path, size, _mtime in sized:
        if total <= max_total_bytes:
            break
        try:
            path.unlink()
        except OSError:
            continue
        removed += 1
        bytes_freed += size
        total -= size

    return removed, bytes_freed
