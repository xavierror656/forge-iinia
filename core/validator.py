"""Validation rules for the assignment configuration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Warning:
    severity: str  # "warn" | "info"
    code: str
    message: str
    target: str = ""  # label or port or camera


def validate(
    *,
    project_labels: list[str],
    camera_assignments: dict[str, list[str]],
    gpio_assignments_for_project: dict[str, str],
    cameras: dict[int, str] | None = None,
) -> list[Warning]:
    out: list[Warning] = []
    label_set = {label.strip() for label in project_labels if label and label.strip()}

    cam_for_label: dict[str, list[str]] = {}
    for cam_id, labels in camera_assignments.items():
        for label in labels:
            if label in label_set:
                cam_for_label.setdefault(label, []).append(cam_id)

    for label, port in gpio_assignments_for_project.items():
        if not port:
            continue
        if label not in label_set:
            out.append(Warning(
                severity="warn",
                code="gpio_unknown_label",
                message=f"GPIO {port} apunta a label '{label}' que no existe en el proyecto",
                target=label,
            ))
            continue
        if label not in cam_for_label:
            out.append(Warning(
                severity="warn",
                code="gpio_without_camera",
                message=f"'{label}' está en {port} pero ninguna cámara lo detecta",
                target=label,
            ))

    if cameras is not None:
        for camera_id, name in cameras.items():
            assigned = camera_assignments.get(str(camera_id), [])
            if not assigned:
                out.append(Warning(
                    severity="info",
                    code="camera_empty",
                    message=f"Cámara '{name}' no tiene labels asignadas",
                    target=str(camera_id),
                ))

    for label in label_set:
        if label not in cam_for_label and label not in gpio_assignments_for_project:
            out.append(Warning(
                severity="info",
                code="label_unused",
                message=f"Label '{label}' no está en ninguna cámara ni GPIO",
                target=label,
            ))

    return out


def summarize(warnings: list[Warning]) -> str:
    if not warnings:
        return "Sin advertencias"
    by_severity: dict[str, int] = {}
    for w in warnings:
        by_severity[w.severity] = by_severity.get(w.severity, 0) + 1
    parts = [f"{count} {sev}" for sev, count in sorted(by_severity.items())]
    return "Validación: " + ", ".join(parts)
