"""Append-only JSONL of telemetry snapshots.

Sparklines in the UI live in RAM and disappear at restart. This module keeps
a rolling on-disk record so post-mortems can correlate FPS / latency / temp
with audit-log triggers.

Reuses the same rotation strategy as :class:`core.audit_log.AuditLog`.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

DEFAULT_TELEMETRY_PATH = Path("captures/telemetry.jsonl")
DEFAULT_MAX_BYTES = 5_000_000
DEFAULT_BACKUP_COUNT = 3
DEFAULT_INTERVAL_SECONDS = 5.0


class TelemetryLog:
    def __init__(
        self,
        path: Path = DEFAULT_TELEMETRY_PATH,
        *,
        max_bytes: int = DEFAULT_MAX_BYTES,
        backup_count: int = DEFAULT_BACKUP_COUNT,
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
    ) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._max_bytes = max(0, int(max_bytes))
        self._backup_count = max(0, int(backup_count))
        self._interval = max(0.0, float(interval_seconds))
        self._last_write_at = 0.0
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def _rotate_if_needed(self) -> None:
        if self._max_bytes <= 0 or not self._path.exists():
            return
        try:
            size = self._path.stat().st_size
        except OSError:
            return
        if size < self._max_bytes:
            return
        for index in range(self._backup_count, 0, -1):
            src = self._path.with_suffix(self._path.suffix + f".{index}")
            dst = self._path.with_suffix(self._path.suffix + f".{index + 1}")
            if src.exists():
                if index == self._backup_count:
                    src.unlink(missing_ok=True)
                else:
                    src.rename(dst)
        if self._backup_count > 0:
            self._path.rename(self._path.with_suffix(self._path.suffix + ".1"))
        else:
            self._path.unlink(missing_ok=True)

    def maybe_record(self, snapshot: dict[str, Any], now: float | None = None) -> bool:
        ts = now if now is not None else time.time()
        if self._interval > 0 and (ts - self._last_write_at) < self._interval:
            return False
        return self._write(snapshot, ts)

    def record(self, snapshot: dict[str, Any], now: float | None = None) -> bool:
        ts = now if now is not None else time.time()
        return self._write(snapshot, ts)

    def _write(self, snapshot: dict[str, Any], ts: float) -> bool:
        entry = {"ts": float(ts), **snapshot}
        line = json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._lock:
            self._rotate_if_needed()
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line)
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except OSError:
                    pass
            self._last_write_at = ts
        return True
