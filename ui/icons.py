"""Bootstrap Icons provider for EdgeVision Control Hub.

Icons sourced from Bootstrap Icons v1.11.3 (MIT license).
https://github.com/twbs/icons
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QApplication

from ui.theme import normalize_theme, tokens

ICONS_DIR = Path(__file__).resolve().parent / "icons"

_CACHE: dict[str, QPixmap] = {}

def _current_theme() -> str:
    app = QApplication.instance()
    if app is None:
        return "dark"
    return normalize_theme(app.property("uiTheme"))


def _palette() -> dict[str, str]:
    t = tokens(_current_theme())
    return {
        "primary": t["text"],
        "accent": t["accent"],
        "danger": t["danger"],
        "warning": t["warning"],
        "info": t["info"],
        "muted": t["muted2"],
    }


def _svg_content(name: str) -> str | None:
    path = ICONS_DIR / f"{name}.svg"
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def _colorized_svg(name: str, color: str) -> str | None:
    svg = _svg_content(name)
    if svg is None:
        return None
    return svg.replace("currentColor", color)


def _render_svg_to_pixmap(
    svg_str: str, target_size: int, hex_color: str
) -> QPixmap:
    pix = QPixmap(target_size, target_size)
    pix.fill(Qt.GlobalColor.transparent)

    renderer = QSvgRenderer(svg_str.encode("utf-8"))
    if not renderer.isValid():
        return pix

    painter = QPainter(pix)
    try:
        renderer.render(painter)
    finally:
        painter.end()
    return pix


def pixmap(name: str, size: int = 18, color: str = "primary") -> QPixmap:
    cache_key = f"{name}:{size}:{color}:{_current_theme()}"
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    palette = _palette()
    hex_color = palette.get(color, palette["primary"])
    svg = _colorized_svg(name, hex_color)
    if svg is None:
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        return pix

    try:
        result = _render_svg_to_pixmap(svg, size, hex_color)
    except Exception:
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        return pix

    _CACHE[cache_key] = result
    return result


def icon(name: str, size: int = 18, color: str = "primary") -> QIcon:
    return QIcon(pixmap(name, size, color))


def clear_cache() -> None:
    _CACHE.clear()
