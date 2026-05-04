"""Bootstrap Icons provider for EdgeVision Control Hub.

Icons sourced from Bootstrap Icons v1.11.3 (MIT license).
https://github.com/twbs/icons
"""

from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree as ET

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QImage, QColor, QPen, QBrush, QPolygonF
from PyQt6.QtCore import QPointF, QRectF
from PyQt6.QtWidgets import QApplication

ICONS_DIR = Path(__file__).resolve().parent / "icons"

ICON_PALETTE = {
    "dark": {"primary": "#e6eaf2", "accent": "#62d2a2", "danger": "#e66b6b", "warning": "#f4b942", "info": "#5aa9e6", "muted": "#6c7680"},
    "light": {"primary": "#1a1f36", "accent": "#1e7e5a", "danger": "#c41e1e", "warning": "#b8860b", "info": "#2b6cb0", "muted": "#8e96a5"},
}

_CACHE: dict[str, QPixmap] = {}

_NS = "http://www.w3.org/2000/svg"


def _current_theme() -> str:
    app = QApplication.instance()
    if app is None:
        return "dark"
    sheet = app.styleSheet() or ""
    return "light" if sheet == "" else "dark"


def _palette() -> dict[str, str]:
    return ICON_PALETTE.get(_current_theme(), ICON_PALETTE["dark"])


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


def _parse_svg(svg_str: str) -> tuple[float, float, float, float, list[dict]]:
    root = ET.fromstring(svg_str)
    vb = root.get("viewBox") or "0 0 16 16"
    parts = vb.split()
    vb_x = float(parts[0]) if parts else 0
    vb_y = float(parts[1]) if len(parts) > 1 else 0
    vb_w = float(parts[2]) if len(parts) > 2 else 16
    vb_h = float(parts[3]) if len(parts) > 3 else 16

    elements: list[dict] = []
    for el in root.iter():
        tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if tag in ("svg", "g", "defs", "title"):
            continue
        elem: dict = {"tag": tag}
        for attr, val in el.attrib.items():
            attr_name = attr.split("}")[-1] if "}" in attr else attr
            elem[attr_name] = val
        elements.append(elem)
    return vb_x, vb_y, vb_w, vb_h, elements


def _num(val: str | None, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _parse_path_data(d: str) -> list[tuple[str, list[float]]]:
    parts = re.findall(r"([A-Za-z])\s*([0-9.\-e,\s]+)", d, re.IGNORECASE)
    commands: list[tuple[str, list[float]]] = []
    for cmd, nums in parts:
        vals = [float(x) for x in re.findall(r"-?[0-9.]+(?:e[+\-]?\d+)?", nums)]
        commands.append((cmd, vals))
    return commands


def _render_svg_to_pixmap(
    svg_str: str, target_size: int, hex_color: str
) -> QPixmap:
    try:
        vb_x, vb_y, vb_w, vb_h, elements = _parse_svg(svg_str)
    except Exception:
        pix = QPixmap(target_size, target_size)
        pix.fill(Qt.GlobalColor.transparent)
        return pix

    if vb_w <= 0 or vb_h <= 0:
        vb_w = 16
        vb_h = 16

    scale_x = target_size / vb_w
    scale_y = target_size / vb_h
    color = QColor(hex_color)

    image = QImage(target_size, target_size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    def _to_pt(x: float, y: float) -> QPointF:
        return QPointF((x - vb_x) * scale_x, (y - vb_y) * scale_y)

    def _to_rect(x: float, y: float, w: float, h: float) -> QRectF:
        return QRectF(
            (x - vb_x) * scale_x,
            (y - vb_y) * scale_y,
            w * scale_x,
            h * scale_y,
        )

    for elem in elements:
        tag = elem["tag"]
        fill = elem.get("fill", "").strip()
        stroke = elem.get("stroke", "").strip()
        stroke_w = _num(elem.get("stroke-width"), 1.0)
        opacity = elem.get("opacity", "").strip()

        if fill and fill != "none" and fill != "currentColor":
            try:
                brush_color = QColor(fill)
            except Exception:
                brush_color = color
        elif fill == "none":
            brush_color = None
        else:
            brush_color = color

        if stroke and stroke != "none":
            try:
                pen_color = QColor(stroke)
            except Exception:
                pen_color = color
        else:
            pen_color = None

        if brush_color is not None and opacity:
            try:
                brush_color.setAlphaF(float(opacity))
            except (ValueError, TypeError):
                pass

        if tag in ("rect", "rect"):
            x = _num(elem.get("x"))
            y = _num(elem.get("y"))
            w = _num(elem.get("width"))
            h = _num(elem.get("height"))
            if brush_color is not None:
                painter.setBrush(QBrush(brush_color))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRect(_to_rect(x, y, w, h))
        elif tag in ("circle", "ellipse"):
            cx = _num(elem.get("cx"))
            cy = _num(elem.get("cy"))
            r = _num(elem.get("r"))
            rx = _num(elem.get("rx"), r)
            ry = _num(elem.get("ry"), r)
            if brush_color is not None:
                painter.setBrush(QBrush(brush_color))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(
                    _to_pt(cx - rx, cy - ry),
                    rx * scale_x * 2,
                    ry * scale_y * 2,
                )
        elif tag == "path":
            d = elem.get("d", "")
            commands = _parse_path_data(d)
            if not commands:
                continue
            pen = QPen(color) if pen_color is None else QPen(pen_color)
            pen.setWidthF(max(0.5, stroke_w * min(scale_x, scale_y) * 0.85))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            if brush_color is not None:
                painter.setBrush(QBrush(brush_color))
            else:
                painter.setBrush(Qt.BrushStyle.NoBrush)

            path_painter = painter
            for cmd, vals in commands:
                if cmd.upper() == "M":
                    pt = _to_pt(vals[0], vals[1])
                    path_painter.drawPath(path_painter.path() if hasattr(path_painter, 'path') else None)

    painter.end()

    pix = QPixmap.fromImage(image)
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