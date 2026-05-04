"""Keyboard shortcuts dialog."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from ui.icons import icon as _icon


SHORTCUTS = [
    ("/", "Buscar labels en galería"),
    ("Ctrl+F", "Filtrar lista de labels"),
    ("Esc", "Limpiar filtros"),
    ("Ctrl+A", "Seleccionar todos los labels visibles"),
    ("Ctrl+K", "Paleta de comandos (buscar global)"),
    ("Ctrl+Z", "Deshacer última asignación"),
    ("Ctrl+Y / Ctrl+Shift+Z", "Rehacer asignación"),
    ("Ctrl+S", "Exportar configuración"),
    ("?", "Mostrar este atajo"),
    ("F5", "Refrescar Forge"),
]


class ShortcutsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Atajos de teclado")
        self.setWindowIcon(_icon("keyboard", size=24))
        self.resize(420, 360)
        layout = QVBoxLayout(self)
        title = QLabel("<b>Atajos disponibles</b>")
        title.setStyleSheet("color:#e6eaf2; font-size:14px;")
        layout.addWidget(title)
        for combo, description in SHORTCUTS:
            row = QLabel(f"<span style='color:#62d2a2; font-family:monospace;'>{combo}</span>"
                        f" &nbsp; <span style='color:#cfd6e1;'>{description}</span>")
            row.setTextFormat(Qt.TextFormat.RichText)
            layout.addWidget(row)
        layout.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        if (close_button := buttons.button(QDialogButtonBox.StandardButton.Close)) is not None:
            close_button.setIcon(_icon("x-lg", size=16))
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
