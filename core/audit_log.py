"""Append-only JSONL log of GPIO trigger events.

The hub fires GPIO outputs based on consecutive-frame detection. When a line
malfunctions in the field the only way to reconstruct what happened is the
sequence of triggers, so this module exists to make that record durable
without depending on the rolling UI console buffer.

Format: one JSON object per line, UTF-8, never rewritten (only appended)
so an interrupted process leaves a partial line at most. Readers should
ignore lines that fail to parse.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

DEFAULT_AUDIT_PATH = Path("captures/events.jsonl")
DEFAULT_MAX_BYTES = 5_000_000
DEFAULT_BACKUP_COUNT = 3


class AuditLog:
    def __init__(
        self,
        path: Path = DEFAULT_AUDIT_PATH,
        *,
        max_bytes: int = DEFAULT_MAX_BYTES,
        backup_count: int = DEFAULT_BACKUP_COUNT,
    ) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._max_bytes = max(0, int(max_bytes))
        self._backup_count = max(0, int(backup_count))
        self._path.parent.mkdir(parents=True, exist_ok=True)

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

    @property
    def path(self) -> Path:
        return self._path

    def record(
        self,
        *,
        kind: str,
        label: str,
        active: bool,
        port: str = "",
        camera_id: str = "",
        score: float | None = None,
        frame_id: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        entry: dict[str, Any] = {
            "ts": time.time(),
            "kind": kind,
            "label": label,
            "active": bool(active),
            "port": port,
            "camera_id": camera_id,
        }
        if score is not None:
            entry["score"] = float(score)
        if frame_id is not None:
            entry["frame_id"] = int(frame_id)
        if extra:
            for key, value in extra.items():
                if key not in entry:
                    entry[key] = value
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

    def read_all(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        out: list[dict[str, Any]] = []
        with self._path.open(encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    out.append(parsed)
        return out
