"""Import/export of the assignment configuration."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml


@dataclass
class ConfigBundle:
    cameras: dict[str, list[str]]
    gpios: dict[str, dict[str, str]]


def export_yaml(bundle: ConfigBundle) -> str:
    payload = {
        "version": 1,
        "camera_assignments": bundle.cameras,
        "gpio_assignments": bundle.gpios,
    }
    return yaml.safe_dump(payload, sort_keys=True, allow_unicode=True)


def export_json(bundle: ConfigBundle) -> str:
    return json.dumps(
        {
            "version": 1,
            "camera_assignments": bundle.cameras,
            "gpio_assignments": bundle.gpios,
        },
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
    )


def export_csv(bundle: ConfigBundle) -> str:
    """Flat row-per-label CSV: label, camera_id, project_id, gpio_port."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["label", "camera_id", "project_id", "gpio_port"])

    cam_for_label: dict[str, list[str]] = {}
    for cam_id, labels in bundle.cameras.items():
        for label in labels:
            cam_for_label.setdefault(label, []).append(cam_id)

    gpio_for_label: dict[str, list[tuple[str, str]]] = {}
    for project_id, mapping in bundle.gpios.items():
        for label, port in mapping.items():
            gpio_for_label.setdefault(label, []).append((project_id, port))

    all_labels = set(cam_for_label) | set(gpio_for_label)
    for label in sorted(all_labels):
        cams = cam_for_label.get(label) or [""]
        gpios = gpio_for_label.get(label) or [("", "")]
        for cam_id in cams:
            for project_id, port in gpios:
                writer.writerow([label, cam_id, project_id, port])
    return output.getvalue()


def import_text(text: str, *, suffix: str = ".yaml") -> ConfigBundle:
    suffix = suffix.lower()
    if suffix in {".yaml", ".yml"}:
        data = yaml.safe_load(text)
    elif suffix == ".json":
        data = json.loads(text)
    elif suffix == ".csv":
        return _import_csv(text)
    else:
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError:
            data = json.loads(text)

    if not isinstance(data, dict):
        raise ValueError("Formato no reconocido")
    cameras = data.get("camera_assignments") or {}
    gpios = data.get("gpio_assignments") or {}
    if not isinstance(cameras, dict) or not isinstance(gpios, dict):
        raise ValueError("Estructura inválida")
    return ConfigBundle(
        cameras={str(k): [str(x) for x in (v or [])] for k, v in cameras.items()},
        gpios={
            str(pid): {str(label): str(port) for label, port in (mapping or {}).items()}
            for pid, mapping in gpios.items()
        },
    )


def _import_csv(text: str) -> ConfigBundle:
    cameras: dict[str, list[str]] = {}
    gpios: dict[str, dict[str, str]] = {}
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        label = (row.get("label") or "").strip()
        if not label:
            continue
        cam_id = (row.get("camera_id") or "").strip()
        if cam_id:
            cameras.setdefault(cam_id, [])
            if label not in cameras[cam_id]:
                cameras[cam_id].append(label)
        project_id = (row.get("project_id") or "").strip()
        port = (row.get("gpio_port") or "").strip()
        if project_id and port:
            gpios.setdefault(project_id, {})[label] = port
    return ConfigBundle(cameras=cameras, gpios=gpios)


def write_path(path: Path, bundle: ConfigBundle) -> None:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        text = export_csv(bundle)
    elif suffix == ".json":
        text = export_json(bundle)
    else:
        text = export_yaml(bundle)
    path.write_text(text, encoding="utf-8")


def read_path(path: Path) -> ConfigBundle:
    path = Path(path)
    return import_text(path.read_text(encoding="utf-8"), suffix=path.suffix)


def filter_known_labels(bundle: ConfigBundle, known: Iterable[str]) -> tuple[ConfigBundle, list[str]]:
    """Drop labels that don't appear in `known`. Returns cleaned bundle + ignored list."""
    known_set = {str(label).strip() for label in known}
    ignored: set[str] = set()

    clean_cameras: dict[str, list[str]] = {}
    for cam_id, labels in bundle.cameras.items():
        kept = []
        for label in labels:
            if label in known_set:
                kept.append(label)
            else:
                ignored.add(label)
        if kept:
            clean_cameras[cam_id] = kept

    clean_gpios: dict[str, dict[str, str]] = {}
    for pid, mapping in bundle.gpios.items():
        cleaned = {}
        for label, port in mapping.items():
            if label in known_set:
                cleaned[label] = port
            else:
                ignored.add(label)
        if cleaned:
            clean_gpios[pid] = cleaned

    return ConfigBundle(cameras=clean_cameras, gpios=clean_gpios), sorted(ignored)
