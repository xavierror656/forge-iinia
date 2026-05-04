"""Reversible operations for camera/GPIO assignments."""

from __future__ import annotations

import copy
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class Snapshot:
    label: str
    cameras: dict[str, list[str]] = field(default_factory=dict)
    gpios: dict[str, dict[str, str]] = field(default_factory=dict)


class AssignmentHistory:
    """Stack-based undo/redo for the two assignment dicts.

    Stores immutable snapshots; on undo the caller-provided callback receives
    the snapshot to apply (replace state, persist to disk, push to UI).
    """

    def __init__(self, *, capacity: int = 50, on_apply: Callable[[Snapshot], None]) -> None:
        self._undo: deque[Snapshot] = deque(maxlen=capacity)
        self._redo: deque[Snapshot] = deque(maxlen=capacity)
        self._on_apply = on_apply
        self._current: Snapshot | None = None

    def initialize(self, cameras: dict[str, list[str]], gpios: dict[str, dict[str, str]]) -> None:
        self._current = Snapshot(label="initial", cameras=copy.deepcopy(cameras), gpios=copy.deepcopy(gpios))
        self._undo.clear()
        self._redo.clear()

    def push(self, label: str, cameras: dict[str, list[str]], gpios: dict[str, dict[str, str]]) -> None:
        if self._current is not None:
            self._undo.append(self._current)
        self._current = Snapshot(label=label, cameras=copy.deepcopy(cameras), gpios=copy.deepcopy(gpios))
        self._redo.clear()

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> str | None:
        if not self._undo or self._current is None:
            return None
        self._redo.append(self._current)
        self._current = self._undo.pop()
        self._on_apply(self._current)
        return self._current.label

    def redo(self) -> str | None:
        if not self._redo or self._current is None:
            return None
        self._undo.append(self._current)
        self._current = self._redo.pop()
        self._on_apply(self._current)
        return self._current.label
