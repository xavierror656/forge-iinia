"""Single point of access for the JSON configs under ``configs/``.

Centralizes path constants and read/write helpers so call sites stop
hardcoding ``Path("configs/foo.json")`` everywhere. Each helper is
fail-soft on read (returns empty dict) and atomic on write (tmp + rename)
to avoid corruption if the process is killed mid-write.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

CONFIGS_DIR = Path("configs")
GPIO_ASSIGNMENTS_PATH = CONFIGS_DIR / "forge_gpio_assignments.json"
INFERENCE_SOURCE_PATH = CONFIGS_DIR / "inference_source.json"
UI_STATE_PATH = CONFIGS_DIR / "ui_state.json"


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, ensure_ascii=False)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(serialized)
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def load_gpio_assignments() -> dict[str, dict[str, str]]:
    raw = read_json(GPIO_ASSIGNMENTS_PATH)
    out: dict[str, dict[str, str]] = {}
    for project_id, mapping in raw.items():
        if not isinstance(mapping, dict):
            continue
        cleaned: dict[str, str] = {}
        for label, port in mapping.items():
            label_str = str(label).strip()
            port_str = str(port).strip()
            if label_str and port_str:
                cleaned[label_str] = port_str
        if cleaned:
            out[str(project_id)] = cleaned
    return out


def save_gpio_assignments(assignments: dict[str, dict[str, str]]) -> None:
    write_json(GPIO_ASSIGNMENTS_PATH, dict(assignments))


def load_ui_state() -> dict[str, Any]:
    return read_json(UI_STATE_PATH)


def save_ui_state(state: dict[str, Any]) -> None:
    write_json(UI_STATE_PATH, state)


def get_last_project_id() -> int | None:
    raw = load_ui_state().get("last_project_id")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def set_last_project_id(project_id: int | None) -> None:
    state = load_ui_state()
    if project_id is None:
        state.pop("last_project_id", None)
    else:
        state["last_project_id"] = int(project_id)
    save_ui_state(state)


def get_last_camera_id() -> int | None:
    raw = load_ui_state().get("last_camera_id")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def set_last_camera_id(camera_id: int | None) -> None:
    state = load_ui_state()
    if camera_id is None:
        state.pop("last_camera_id", None)
    else:
        state["last_camera_id"] = int(camera_id)
    save_ui_state(state)
