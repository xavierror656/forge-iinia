"""Bulk auto-assignment dialog driven by a regex/prefix pattern."""

from __future__ import annotations

import re

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from ui.icons import icon as _icon


TARGET_GPIO = "gpio"
TARGET_CAMERA = "camera"


class AutoAssignDialog(QDialog):
    def __init__(
        self,
        *,
        labels: list[str],
        gpio_options: list[str],
        camera_options: list[tuple[int, str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Auto-asignar por patrón")
        self.setWindowIcon(_icon("shuffle", size=24))
        self.resize(500, 520)
        self._all_labels = list(labels)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.pattern = QLineEdit()
        self.pattern.setPlaceholderText("p.ej. tornillo_  o  ^(tuerca|perno)")
        self.pattern.textChanged.connect(self._refresh_matches)
        self.is_regex = QRadioButton("Regex")
        self.is_prefix = QRadioButton("Prefijo (case-insensitive)")
        self.is_prefix.setChecked(True)
        mode_group = QButtonGroup(self)
        mode_group.addButton(self.is_prefix)
        mode_group.addButton(self.is_regex)
        mode_box = QWidget()
        mode_layout = QVBoxLayout(mode_box)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.addWidget(self.is_prefix)
        mode_layout.addWidget(self.is_regex)
        self.is_prefix.toggled.connect(self._refresh_matches)
        self.is_regex.toggled.connect(self._refresh_matches)

        self.target_combo = QComboBox()
        for port in gpio_options:
            self.target_combo.addItem(_icon("plug", size=16), f"GPIO · {port}", (TARGET_GPIO, port))
        for cam_id, cam_name in camera_options:
            self.target_combo.addItem(_icon("camera-video", size=16), f"Cámara · {cam_name} (#{cam_id})", (TARGET_CAMERA, cam_id))

        form.addRow("Patrón", self.pattern)
        form.addRow("Modo", mode_box)
        form.addRow("Destino", self.target_combo)
        layout.addLayout(form)

        self.match_label = QLabel("0 coincidencias")
        self.match_label.setStyleSheet("color:#9fb2c8;")
        layout.addWidget(self.match_label)

        self.match_list = QListWidget()
        self.match_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        layout.addWidget(self.match_list, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        if (ok_button := buttons.button(QDialogButtonBox.StandardButton.Ok)) is not None:
            ok_button.setIcon(_icon("check-lg", size=16))
        if (cancel_button := buttons.button(QDialogButtonBox.StandardButton.Cancel)) is not None:
            cancel_button.setIcon(_icon("x-lg", size=16))
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Asignar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._refresh_matches()

    def _refresh_matches(self) -> None:
        self.match_list.clear()
        pattern = self.pattern.text().strip()
        if not pattern:
            self.match_label.setText("0 coincidencias")
            return
        try:
            if self.is_regex.isChecked():
                rx = re.compile(pattern, re.IGNORECASE)
                matches = [label for label in self._all_labels if rx.search(label)]
            else:
                p = pattern.lower()
                matches = [label for label in self._all_labels if label.lower().startswith(p)]
        except re.error as exc:
            self.match_label.setText(f"Regex inválida: {exc}")
            return

        for label in matches:
            item = QListWidgetItem(label)
            item.setSelected(True)
            self.match_list.addItem(item)
        self.match_label.setText(f"{len(matches)} coincidencias")

    def selection(self) -> tuple[str, object, list[str]]:
        target_payload = self.target_combo.currentData()
        if not isinstance(target_payload, tuple):
            return ("", None, [])
        labels = [self.match_list.item(i).text() for i in range(self.match_list.count())
                  if self.match_list.item(i).isSelected()]
        return (target_payload[0], target_payload[1], labels)
