"""Forge operations panel for project and camera assignment."""

from __future__ import annotations

import ast
import base64
import json
from pathlib import Path

from PyQt6.QtCore import QMetaObject, QMimeData, QPoint, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QDrag, QFont, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSplitter,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTabWidget,
    QToolButton,
    QTextEdit,
    QVBoxLayout,
    QSpinBox,
    QWidget,
)


from core.config_store import UI_STATE_PATH  # re-exported for compatibility
from ui.forge_graph import ForgeGraphWidget
from ui.icons import icon as _icon


def _label_text(value: object) -> str:
    if isinstance(value, dict):
        name = value.get("name")
        if name is None:
            return ""
        text = str(name).strip()
        return text

    text = str(value).strip()
    if not text:
        return ""
    if text.startswith("{") and text.endswith("}"):
        try:
            parsed = ast.literal_eval(text)
        except (ValueError, SyntaxError):
            return text
        if isinstance(parsed, dict):
            name = parsed.get("name")
            if name is not None:
                parsed_name = str(name).strip()
                if parsed_name:
                    return parsed_name
    return text


def _short_label(text: str, limit: int = 18) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _label_prefix(name: str) -> str:
    for sep in ("_", "-", " ", "."):
        if sep in name:
            return name.split(sep, 1)[0].lower()
    return name[:1].lower() or "·"


def _label_item_icon(name: str, camera_for_label: dict[str, list[str]], gpio_for_label: dict[str, str]) -> tuple[str, str]:
    has_camera = bool(camera_for_label.get(name))
    has_gpio = bool(gpio_for_label.get(name))
    if has_camera and has_gpio:
        return ("check-lg", "accent")
    if has_camera:
        return ("camera-video", "info")
    if has_gpio:
        return ("plug", "warning")
    return ("tag", "muted")


def _group_header_icon(group_mode: str) -> tuple[str, str]:
    return {
        "prefix": ("tags", "primary"),
        "type": ("tag", "primary"),
        "status": ("activity", "info"),
    }.get(group_mode, ("list", "muted"))


class IconChip(QWidget):
    def __init__(
        self,
        text: str,
        icon_name: str,
        *,
        icon_color: str = "primary",
        bg_color: str | None = None,
        fg_color: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._icon_name = icon_name
        self._icon_color = icon_color
        self._theme = "dark"
        from ui.theme import tokens as _t
        t = _t("dark")
        self._bg_color = bg_color or t["surface2"]
        self._fg_color = fg_color or t["muted"]

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(6)

        self._icon_label = QLabel()
        self._icon_label.setFixedSize(14, 14)
        self._text_label = QLabel()
        self._text_label.setStyleSheet("background: transparent; font-weight: 600; font-size: 11px;")

        layout.addWidget(self._icon_label)
        layout.addWidget(self._text_label)

        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.set_content(text)

    def set_content(
        self,
        text: str,
        *,
        icon_name: str | None = None,
        icon_color: str | None = None,
        bg_color: str | None = None,
        fg_color: str | None = None,
    ) -> None:
        if icon_name is not None:
            self._icon_name = icon_name
        if icon_color is not None:
            self._icon_color = icon_color
        if bg_color is not None:
            self._bg_color = bg_color
        if fg_color is not None:
            self._fg_color = fg_color

        self._text_label.setText(text)
        self._icon_label.setPixmap(_icon(self._icon_name, size=14, color=self._icon_color).pixmap(14, 14))
        self._text_label.setStyleSheet(
            f"background: transparent; color: {self._fg_color}; font-weight: 600; font-size: 11px;"
        )
        self.setStyleSheet(f"background: {self._bg_color}; border-radius: 12px;")

    def set_theme(self, theme: str) -> None:
        from ui.theme import tokens as _t
        t = _t(theme)
        self._theme = theme
        self._bg_color = t["surface2"]
        self._fg_color = t["muted"]
        self.set_content(self._text_label.text())


class ColorChipDelegate(QStyledItemDelegate):
    """Paints a colored dot next to the label text instead of using item background."""

    DOT_RADIUS = 6
    DOT_PADDING = 10

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._header_font = QFont()
        self._header_font.setBold(True)
        self._theme = "dark"

    def set_theme(self, theme: str) -> None:
        self._theme = theme

    def _t(self) -> dict:
        from ui.theme import tokens as _tok
        return _tok(self._theme)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:  # noqa: D401
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        t = self._t()

        is_header = bool(index.data(Qt.ItemDataRole.UserRole + 1))
        if is_header:
            painter.save()
            painter.fillRect(option.rect, QColor(t["bg"]))
            painter.setFont(self._header_font)
            painter.setPen(QPen(QColor(t["muted"])))
            x_offset = 10
            decoration = index.data(Qt.ItemDataRole.DecorationRole)
            if decoration is not None and hasattr(decoration, "pixmap"):
                pixmap = decoration.pixmap(14, 14)
                if not pixmap.isNull():
                    painter.drawPixmap(option.rect.left() + x_offset, option.rect.center().y() - 7, pixmap)
                    x_offset += 20
            text_rect = option.rect.adjusted(x_offset, 0, -6, 0)
            painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), index.data())
            painter.restore()
            return

        data = index.data(Qt.ItemDataRole.UserRole)
        color_hex = ""
        if isinstance(data, dict):
            color_hex = str(data.get("color", "")).strip()

        widget = option.widget
        style = widget.style() if widget else None
        opt.text = ""
        if style is not None:
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)
        else:
            painter.fillRect(option.rect, opt.backgroundBrush)

        rect: QRect = option.rect
        cx = rect.left() + self.DOT_PADDING
        cy = rect.center().y()

        if color_hex:
            color = QColor(color_hex)
            if not color.isValid():
                color = QColor(t["muted"])
        else:
            color = QColor(t["hover"])

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(QBrush(color))
        painter.setPen(QPen(QColor(t["bg"]), 1))
        painter.drawEllipse(QPoint(cx, cy), self.DOT_RADIUS, self.DOT_RADIUS)
        painter.restore()

        text = index.data() or ""
        text_rect = rect.adjusted(self.DOT_PADDING * 2 + self.DOT_RADIUS, 0, -8, 0)
        painter.save()
        if option.state & QStyle.StateFlag.State_Selected:
            painter.setPen(QPen(QColor(t["surface"])))
        else:
            painter.setPen(QPen(QColor(t["text"])))
        painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text)
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:  # noqa: N802
        size = super().sizeHint(option, index)
        is_header = bool(index.data(Qt.ItemDataRole.UserRole + 1))
        size.setHeight(28 if is_header else 26)
        return size


class EmptyMessageMixin:
    """Adds a centered placeholder message when the list is empty or fully filtered."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._empty_message: str = ""

    def setEmptyMessage(self, message: str) -> None:  # noqa: N802
        self._empty_message = message or ""
        self.viewport().update()

    def _has_visible_items(self) -> bool:
        for i in range(self.count()):
            item = self.item(i)
            if item is not None and not item.isHidden():
                return True
        return False

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if not self._empty_message or self._has_visible_items():
            return
        from ui.theme import tokens as _tok
        from PyQt6.QtWidgets import QApplication
        _theme = (QApplication.instance().property("uiTheme") or "dark") if QApplication.instance() else "dark"
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(_tok(_theme)["muted2"])))
        font = painter.font()
        font.setItalic(True)
        font.setPointSizeF(max(9.0, font.pointSizeF()))
        painter.setFont(font)
        rect = self.viewport().rect().adjusted(16, 16, -16, -16)
        painter.drawText(
            rect,
            int(Qt.AlignmentFlag.AlignCenter) | int(Qt.TextFlag.TextWordWrap),
            self._empty_message,
        )
        painter.end()


class PlainList(EmptyMessageMixin, QListWidget):
    pass


def _set_drop_active(widget: QListWidget, active: bool) -> None:
    widget.setProperty("dropActive", "true" if active else "false")
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)
    widget.update()


class DragListWidget(EmptyMessageMixin, QListWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDragDropMode(QListWidget.DragDropMode.DragOnly)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)

    def _selectable_items(self) -> list[QListWidgetItem]:
        items = [item for item in self.selectedItems() if not item.data(Qt.ItemDataRole.UserRole + 1)]
        if items:
            return items
        current = self.currentItem()
        if current and not current.data(Qt.ItemDataRole.UserRole + 1):
            return [current]
        return []

    def startDrag(self, supportedActions):  # noqa: N802
        items = self._selectable_items()
        if not items:
            return
        labels = [_label_text(item.data(Qt.ItemDataRole.UserRole) or item.text()) for item in items]
        labels = [label for label in labels if label.strip()]
        if not labels:
            return
        mime = QMimeData()
        mime.setText("\n".join(labels))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(self._build_drag_pixmap(len(labels), labels[0]))
        drag.setHotSpot(QPoint(20, 16))
        drag.exec(supportedActions)

    @staticmethod
    def _build_drag_pixmap(count: int, sample: str) -> QPixmap:
        text = f"{count} labels" if count > 1 else _short_label(sample, 24)
        width = max(120, 16 + len(text) * 7)
        pixmap = QPixmap(width, 32)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        from ui.theme import tokens as _tok
        from PyQt6.QtWidgets import QApplication
        _theme = (QApplication.instance().property("uiTheme") or "dark") if QApplication.instance() else "dark"
        _tc = _tok(_theme)
        painter.setBrush(QBrush(QColor(_tc["hover"])))
        painter.setPen(QPen(QColor(_tc["info"]), 1))
        painter.drawRoundedRect(0, 0, width - 1, 31, 8, 8)
        painter.setPen(QPen(QColor(_tc["text"])))
        painter.drawText(pixmap.rect(), int(Qt.AlignmentFlag.AlignCenter), text)
        painter.end()
        return pixmap


class CameraListWidget(EmptyMessageMixin, QListWidget):
    labels_dropped = pyqtSignal(int, list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QListWidget.DragDropMode.DropOnly)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasText():
            _set_drop_active(self, True)
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasText():
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        _set_drop_active(self, False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        _set_drop_active(self, False)
        if not event.mimeData().hasText():
            super().dropEvent(event)
            return
        pos = event.position().toPoint() if hasattr(event, "position") else QPoint()
        item = self.itemAt(pos) or self.currentItem()
        if item is None:
            return
        camera_id = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(camera_id, int):
            return
        labels = [line.strip() for line in event.mimeData().text().splitlines() if line.strip()]
        if labels:
            self.labels_dropped.emit(camera_id, labels)
            event.acceptProposedAction()
            return
        super().dropEvent(event)


class PortListWidget(EmptyMessageMixin, QListWidget):
    labels_dropped = pyqtSignal(str, list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QListWidget.DragDropMode.DropOnly)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasText():
            _set_drop_active(self, True)
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasText():
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        _set_drop_active(self, False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        _set_drop_active(self, False)
        if not event.mimeData().hasText():
            super().dropEvent(event)
            return
        pos = event.position().toPoint() if hasattr(event, "position") else QPoint()
        item = self.itemAt(pos) or self.currentItem()
        if item is None:
            return
        port = str(item.data(Qt.ItemDataRole.UserRole) or item.text().split(" ", 1)[0]).strip()
        labels = [line.strip() for line in event.mimeData().text().splitlines() if line.strip()]
        if labels and port:
            self.labels_dropped.emit(port, labels)
            event.acceptProposedAction()
            return
        super().dropEvent(event)


class CollapsibleSection(QWidget):
    def __init__(
        self,
        title: str,
        summary: str = "",
        expanded: bool = True,
        icon_name: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._title = title
        self._summary = summary

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.header = QToolButton()
        self.header.setCheckable(True)
        self.header.setChecked(expanded)
        self.header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.header.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        if icon_name:
            self.header.setIcon(_icon(icon_name, size=16))
            self.header.setIconSize(QSize(16, 16))
        self.header.toggled.connect(self._sync_state)
        self.header.setStyleSheet(
            """
            QToolButton {
                padding: 8px 10px;
                border: 1px solid #2a313a;
                border-radius: 8px;
                background: #141820;
                color: #e6eaf2;
                font-weight: 600;
                text-align: left;
            }
            QToolButton:hover { background: #1b2028; }
            """
        )

        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(4, 4, 4, 4)
        self.content_layout.setSpacing(6)

        layout.addWidget(self.header)
        layout.addWidget(self.content)
        self._sync_state()

    def _update_text(self) -> None:
        text = self._title if not self._summary else f"{self._title} · {self._summary}"
        self.header.setText(text)

    def _sync_state(self, *_args) -> None:
        expanded = self.header.isChecked()
        self.content.setVisible(expanded)
        self.header.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self._update_text()

    def set_summary(self, summary: str) -> None:
        self._summary = summary
        self._update_text()

    def set_expanded(self, expanded: bool) -> None:
        self.header.setChecked(expanded)
        self._sync_state()

    def is_expanded(self) -> bool:
        return self.content.isVisible()


class LabelPreviewCard(QFrame):
    clicked = pyqtSignal(dict)

    def __init__(self, data: dict[str, object], parent: QWidget | None = None, *, theme: str = "dark") -> None:
        super().__init__(parent)
        self._data = data
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.image = QLabel()
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumHeight(96)

        crop = str(data.get("preview_base64", "")).strip()
        pixmap = QPixmap()
        if crop and pixmap.loadFromData(base64.b64decode(crop)):
            self.image.setPixmap(pixmap.scaled(220, 96, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        else:
            self.image.setText("No crop")

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)
        self._color_dot = QLabel()
        self._color_dot.setFixedSize(10, 10)
        self._label_color = str(data.get("color", "")).strip() or "#3a4452"
        self.title = QLabel(str(data.get("name", "")))
        self.title.setStyleSheet("font-weight: 600;")
        title_row.addWidget(self._color_dot)
        title_row.addWidget(self.title, 1)

        self.subtitle = QLabel(str(data.get("type", "") or ""))
        layout.addWidget(self.image)
        layout.addLayout(title_row)
        layout.addWidget(self.subtitle)

        self.set_theme(theme)

    def set_theme(self, theme: str) -> None:
        from ui.theme import tokens as _tokens
        t = _tokens(theme)
        self.image.setStyleSheet(
            f"background:{t['surface2']}; border-radius:6px; color:{t['muted']};"
        )
        self._color_dot.setStyleSheet(
            f"background:{self._label_color}; border-radius:5px; border:1px solid {t['border']};"
        )
        self.subtitle.setStyleSheet(f"color:{t['muted']}; font-size:11px;")

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.clicked.emit(self._data)
        super().mousePressEvent(event)


class LabelGalleryStatsBar(QWidget):
    """Compact statistics summary shown above the label gallery grid."""

    _BAR_WIDTH = 18

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 8)
        layout.setSpacing(3)

        self._header = QLabel()
        self._header.setStyleSheet("font-size:11px; font-weight:600;")
        layout.addWidget(self._header)

        self._cam_bar = QLabel()
        self._cam_bar.setStyleSheet("font-size:10px; font-family:monospace;")
        layout.addWidget(self._cam_bar)

        self._gpio_bar = QLabel()
        self._gpio_bar.setStyleSheet("font-size:10px; font-family:monospace;")
        layout.addWidget(self._gpio_bar)

        self._status_row = QLabel()
        self._status_row.setStyleSheet("font-size:10px;")
        self._status_row.setWordWrap(True)
        layout.addWidget(self._status_row)

        self._types_row = QLabel()
        self._types_row.setStyleSheet("font-size:10px;")
        self._types_row.setWordWrap(True)
        layout.addWidget(self._types_row)

        self.set_theme("dark")

    def update_stats(
        self,
        items: list[dict],
        camera_for_label: dict[str, list[str]],
        gpio_for_label: dict[str, str],
        visible_count: int | None = None,
    ) -> None:
        total = len(items)
        if total == 0:
            self.setVisible(False)
            return

        names = [str(item.get("name", "")) for item in items]
        with_cam = sum(1 for n in names if camera_for_label.get(n))
        with_gpio = sum(1 for n in names if gpio_for_label.get(n))
        both = sum(1 for n in names if camera_for_label.get(n) and gpio_for_label.get(n))
        partial = with_cam + with_gpio - 2 * both
        none_ = total - with_cam - with_gpio + both

        types: dict[str, int] = {}
        for item in items:
            t = str(item.get("type", "")).strip() or "—"
            types[t] = types.get(t, 0) + 1

        shown = f"  ·  {visible_count} visibles" if visible_count is not None and visible_count != total else ""
        self._header.setText(f"{total} labels{shown}  ·  {len(types)} tipo{'s' if len(types) != 1 else ''}")

        self._cam_bar.setText(self._bar("📷 cám ", with_cam, total))
        self._gpio_bar.setText(self._bar("⚡ gpio", with_gpio, total))

        status_parts = []
        if both:
            status_parts.append(f"✓ {both} completos")
        if partial:
            status_parts.append(f"◑ {partial} parciales")
        if none_:
            status_parts.append(f"○ {none_} sin asignar")
        self._status_row.setText("  ·  ".join(status_parts))

        sorted_types = sorted(types.items(), key=lambda kv: -kv[1])
        type_parts = [f"{t} ({n})" for t, n in sorted_types[:7]]
        if len(sorted_types) > 7:
            type_parts.append(f"+{len(sorted_types) - 7} más")
        self._types_row.setText("  ·  ".join(type_parts))

        self.setVisible(True)

    def set_theme(self, theme: str) -> None:
        from ui.theme import tokens as _tokens
        t = _tokens(theme)
        self.setStyleSheet(
            f"background:{t['surface2']}; border:1px solid {t['border']}; border-radius:6px;"
        )
        self._header.setStyleSheet(f"color:{t['muted']}; font-size:11px; font-weight:600;")
        self._cam_bar.setStyleSheet(f"color:{t['info']}; font-size:10px; font-family:monospace;")
        self._gpio_bar.setStyleSheet(f"color:{t['warning']}; font-size:10px; font-family:monospace;")
        self._status_row.setStyleSheet(f"color:{t['muted2']}; font-size:10px;")
        self._types_row.setStyleSheet(f"color:{t['muted2']}; font-size:10px;")

    def _bar(self, label: str, value: int, total: int) -> str:
        ratio = value / total if total else 0.0
        filled = round(ratio * self._BAR_WIDTH)
        empty = self._BAR_WIDTH - filled
        pct = f"{ratio:.0%}"
        return f"{label}  {'█' * filled}{'░' * empty}  {value}/{total} ({pct})"


class LabelGalleryWidget(QWidget):
    selected = pyqtSignal(dict)

    COLUMNS = 3

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[dict[str, object]] = []
        self._cards: list[LabelPreviewCard] = []
        self._filter_text = ""
        self._name_whitelist: set[str] | None = None
        self._camera_for_label: dict[str, list[str]] = {}
        self._gpio_for_label: dict[str, str] = {}
        self._theme = "dark"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.stats_bar = LabelGalleryStatsBar()
        layout.addWidget(self.stats_bar)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.content = QWidget()
        self.grid = QGridLayout(self.content)
        self.grid.setSpacing(8)
        self.grid.setContentsMargins(4, 4, 4, 4)
        self.scroll.setWidget(self.content)
        layout.addWidget(self.scroll, 1)

    def set_items(self, items: list[dict]) -> None:
        self._items = list(items)
        self.refresh()

    def set_filter(self, text: str) -> None:
        self._filter_text = text.strip().lower()
        self.refresh()

    def set_name_whitelist(self, names: set[str] | None) -> None:
        self._name_whitelist = {n.lower() for n in names} if names is not None else None
        self.refresh()

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        self.stats_bar.set_theme(theme)
        for card in self._cards:
            card.set_theme(theme)

    def set_assignment_context(
        self,
        camera_for_label: dict[str, list[str]],
        gpio_for_label: dict[str, str],
    ) -> None:
        self._camera_for_label = camera_for_label
        self._gpio_for_label = gpio_for_label
        self._refresh_stats()

    def refresh(self) -> None:
        while self.grid.count():
            child = self.grid.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._cards.clear()
        visible_items = [item for item in self._items if self._matches(item)]
        for index, item in enumerate(visible_items):
            card = LabelPreviewCard(item, theme=self._theme)
            card.clicked.connect(self.selected.emit)
            self._cards.append(card)
            self.grid.addWidget(card, index // self.COLUMNS, index % self.COLUMNS)
        if visible_items:
            self.selected.emit(visible_items[0])
        self._refresh_stats(visible_count=len(visible_items))

    def _refresh_stats(self, visible_count: int | None = None) -> None:
        shown = visible_count if visible_count is not None else len(self._items)
        self.stats_bar.update_stats(
            self._items,
            self._camera_for_label,
            self._gpio_for_label,
            visible_count=shown if shown != len(self._items) else None,
        )

    def _matches(self, item: dict[str, object]) -> bool:
        if self._name_whitelist is not None:
            name = str(item.get("name", "")).lower()
            if name and name not in self._name_whitelist:
                return False
        if not self._filter_text:
            return True
        haystack = " ".join(
            str(item.get(key, ""))
            for key in ("name", "type", "color")
        ).lower()
        return self._filter_text in haystack



from ui.forge.dialogs import CameraCreateDialog, ForgeConfigDialog  # re-exports


class ForgePanel(QWidget):
    connect_requested = pyqtSignal(str, str, str)
    refresh_requested = pyqtSignal()
    assign_requested = pyqtSignal(int, int, list)
    send_conf_requested = pyqtSignal(int)
    project_changed = pyqtSignal(int)
    label_selected = pyqtSignal(dict)
    camera_labels_dropped = pyqtSignal(int, list)
    gpio_labels_dropped = pyqtSignal(str, list)
    bulk_clear_requested = pyqtSignal(list)
    help_requested = pyqtSignal()
    download_model_requested = pyqtSignal(int)
    graph_assignments_changed = pyqtSignal(dict, dict)

    FILTER_ALL = "all"
    FILTER_NO_CAMERA = "no_camera"
    FILTER_NO_GPIO = "no_gpio"
    FILTER_ASSIGNED = "assigned"

    def __init__(self, parent: QWidget | None = None, *, ui_profile: str = "desktop") -> None:
        super().__init__(parent)
        self._ui_profile = ui_profile
        self._label_source: list[str | dict] = []
        self._camera_for_label: dict[str, list[str]] = {}
        self._gpio_for_label: dict[str, str] = {}
        self._label_for_camera: dict[str, set[str]] = {}
        self._filter_mode: str = self.FILTER_ALL
        self._group_mode: str = "none"
        self._current_orientation: Qt.Orientation | None = None
        self.graph_view: ForgeGraphWidget | None = None
        self._label_tab_index: int = -1
        self._label_refresh_timer = QTimer(self)
        self._label_refresh_timer.setSingleShot(True)
        self._label_refresh_timer.setInterval(60)
        self._label_refresh_timer.timeout.connect(self._do_label_refresh)
        self._build_ui()
        self._install_shortcuts()
        self._restore_state()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        self.base_url = QLineEdit("https://forge.iinia.ai/api/swagger/")
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.token = QLineEdit()
        self.token.setPlaceholderText("Token opcional")

        self.connect_button = QPushButton(" Conectar")
        self.connect_button.setIcon(_icon("plug", size=16))
        self.connect_button.setToolTip("Abrir configuración Forge")
        self.refresh_button = QPushButton(" Refrescar")
        self.refresh_button.setIcon(_icon("arrow-clockwise", size=16))
        self.refresh_button.setToolTip("Recargar proyectos, cámaras y líneas")
        self.help_button = QPushButton()
        self.help_button.setText("?")
        self.help_button.setToolTip("Atajos de teclado (F1)")
        self.help_button.setFixedWidth(32)
        self.help_button.clicked.connect(self.help_requested.emit)
        self.coverage_label = QLabel("0 labels")
        self.coverage_label.setVisible(False)

        self.projects = PlainList()
        self.cameras = CameraListWidget()
        self.lines = PlainList()
        self.labels = DragListWidget()
        self.labels.setItemDelegate(ColorChipDelegate(self.labels))
        self.labels.setUniformItemSizes(False)
        self.labels.itemClicked.connect(self._on_label_item_clicked)
        self.assigned = PlainList()
        self.gpio_ports = PortListWidget()
        self.projects.setEmptyMessage("Sin proyectos.\nPulsa Refrescar Forge.")
        self.cameras.setEmptyMessage("Sin cámaras.\nSelecciona un proyecto o crea una.")
        self.lines.setEmptyMessage("Sin líneas registradas.")
        self.labels.setEmptyMessage("Sin labels.\nSelecciona un proyecto.")
        self.assigned.setEmptyMessage("Sin asignaciones.\nArrastra labels a una cámara.")
        self.gpio_ports.setEmptyMessage("Sin puertos GPIO usados.\nArrastra labels aquí.")
        self.gpio_port = QComboBox()
        self.gpio_port.setEditable(True)
        self.gpio_port.addItems([f"GPIO{n}" for n in range(2, 28)])
        for widget in (self.projects, self.cameras, self.lines, self.assigned, self.gpio_ports):
            widget.setSpacing(4)

        self.line_name = QLineEdit()
        self.line_name.setPlaceholderText("New line name")
        self.component_filter = QLineEdit()
        self.component_filter.setPlaceholderText("Filtrar / pegar labels")
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(150)
        self._search_timer.timeout.connect(lambda: self.filter_label_views(self.label_search.text()))
        self.component_filter.textChanged.connect(lambda _: self._search_timer.start())

        self.create_camera_button = QPushButton(" Crear cámara")
        self.create_camera_button.setIcon(_icon("camera-video", size=16, color="accent"))
        self.create_line_button = QPushButton(" Crear línea")
        self.create_line_button.setIcon(_icon("plus-circle", size=16, color="accent"))
        self.assign_button = QPushButton(" Vincular cámara + GPIO")
        self.assign_button.setIcon(_icon("lightning-charge", size=16, color="warning"))
        self.assign_button.setToolTip(
            "Vincula las labels seleccionadas a la cámara y al puerto GPIO seleccionados"
        )
        self.bulk_clear_button = QPushButton(" Limpiar GPIO")
        self.bulk_clear_button.setIcon(_icon("trash3", size=16, color="danger"))
        self.bulk_clear_button.setToolTip("Quita la asignación GPIO de las labels seleccionadas (doble click para confirmar)")
        self._arm_button(
            self.bulk_clear_button,
            normal_text=" Limpiar GPIO",
            armed_text=" Confirmar limpieza",
            action=self._emit_bulk_clear,
        )
        self.send_conf_button = QPushButton(" Enviar conf a línea")
        self.send_conf_button.setIcon(_icon("send", size=16, color="info"))
        self.send_conf_button.setToolTip("Envía la configuración a la línea seleccionada (doble click para confirmar)")
        self._arm_button(
            self.send_conf_button,
            normal_text=" Enviar conf a línea",
            armed_text=" Confirmar envío",
            action=self._emit_send_conf,
        )
        self.download_model_button = QPushButton(" Descargar .pt")
        self.download_model_button.setIcon(_icon("box-arrow-down", size=16, color="accent"))
        self.download_model_button.setToolTip("Descarga el .pt del proyecto Forge seleccionado")
        self.download_model_button.clicked.connect(self._emit_download_model)

        self.preview_status = QTextEdit()
        self.preview_status.setReadOnly(True)
        self.preview_status.setVisible(False)

        self.project_summary = QTextEdit()
        self.project_summary.setReadOnly(True)
        self.project_summary.setMaximumHeight(140)
        self.project_summary.setPlaceholderText("Project stats / preview...")

        self.label_gallery = LabelGalleryWidget()
        self.label_gallery.selected.connect(self._on_gallery_label_selected)
        self.label_search = QLineEdit()
        self.label_search.setPlaceholderText("Buscar label, color o tipo  (presiona / para enfocar)")
        self.label_search.textChanged.connect(lambda _: self._search_timer.start())
        self.label_detail = QLabel("Select a label to inspect")
        self.label_detail.setWordWrap(True)
        self.label_detail_image = QLabel()
        self.label_detail_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label_detail_image.setMinimumHeight(180)

        self.project_preview = QLabel("Preview del proyecto")
        self.project_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.project_preview.setMinimumHeight(220)

        self.graph_view = ForgeGraphWidget()
        self.graph_view.setContentsMargins(0, 0, 0, 0)
        self.graph_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.graph_view.assignments_changed.connect(self.graph_assignments_changed.emit)
        self.graph_view.label_selected.connect(self._select_label_by_name)
        self.graph_view.label_activated.connect(self._activate_label_from_graph)
        self.graph_view.camera_selected.connect(self._select_camera_by_id)
        self.graph_view.set_candidate_gpio_port(self.gpio_port.currentText().strip())
        self.gpio_port.currentTextChanged.connect(lambda port: self.graph_view.set_candidate_gpio_port(port))

        self.gpio_preview = QLabel("GPIO preview")
        self.gpio_preview.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.gpio_preview.setWordWrap(True)
        self.gpio_preview.setTextFormat(Qt.TextFormat.PlainText)
        self.gpio_preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.gpio_preview.setMinimumHeight(120)

        self.labels_hint = QLabel("0 labels")

        self._build_filter_chips()
        self._build_group_combo()

        self.project_combo = QComboBox()
        self.project_combo.setMinimumContentsLength(18)
        self.project_combo.currentIndexChanged.connect(self._on_project_combo_changed)
        self.camera_combo = QComboBox()
        self.camera_combo.setMinimumContentsLength(18)
        self.camera_combo.currentIndexChanged.connect(self._on_camera_combo_changed)
        self.line_combo = QComboBox()
        self.line_combo.setMinimumContentsLength(16)
        self.line_combo.currentIndexChanged.connect(self._on_line_combo_changed)

        self.projects.setVisible(False)
        self.lines.setVisible(False)

        labels_box = QWidget(self)
        labels_layout = QVBoxLayout(labels_box)
        labels_layout.setContentsMargins(0, 0, 0, 0)
        labels_layout.setSpacing(6)
        header_row = QHBoxLayout()
        header_row.addWidget(QLabel("Labels"))
        header_row.addStretch(1)
        header_row.addWidget(QLabel("Group:"))
        header_row.addWidget(self.group_combo)
        labels_layout.addLayout(header_row)
        labels_layout.addLayout(self.filter_chip_layout)
        labels_layout.addWidget(self.component_filter)
        labels_layout.addWidget(self.labels_hint)
        labels_layout.addWidget(self.labels, 1)

        right_tabs = QTabWidget()
        right_tabs.setTabPosition(QTabWidget.TabPosition.North)

        cameras_tab = QWidget()
        cameras_layout = QVBoxLayout(cameras_tab)
        cameras_layout.setContentsMargins(4, 4, 4, 4)
        cameras_layout.setSpacing(6)
        cameras_hint = QLabel("Arrastra labels desde la columna izquierda hacia una cámara.")
        self._cameras_hint = cameras_hint
        cameras_hint.setWordWrap(True)
        cameras_layout.addWidget(cameras_hint)
        cameras_layout.addWidget(self.cameras, 1)

        gpio_tab = QWidget()
        gpio_layout = QVBoxLayout(gpio_tab)
        gpio_layout.setContentsMargins(4, 4, 4, 4)
        gpio_layout.setSpacing(8)
        ports_header = QLabel("Puertos GPIO en uso")
        ports_header.setStyleSheet("font-weight:600;")
        self._ports_header = ports_header
        gpio_layout.addWidget(ports_header)
        gpio_layout.addWidget(self.gpio_ports, 1)
        self.assigned.setVisible(False)
        self.gpio_preview.setVisible(False)

        gallery_tab = QWidget()
        gallery_layout = QVBoxLayout(gallery_tab)
        gallery_layout.setContentsMargins(4, 4, 4, 4)
        gallery_layout.setSpacing(6)
        gallery_layout.addWidget(self.label_search)
        gallery_layout.addWidget(self.label_gallery, 1)

        label_tab = QWidget()
        label_layout = QVBoxLayout(label_tab)
        label_layout.setContentsMargins(4, 4, 4, 4)
        label_layout.setSpacing(6)
        label_layout.addWidget(self.label_detail_image)
        label_layout.addWidget(self.label_detail)
        label_layout.addStretch(1)

        project_tab = QWidget()
        project_layout = QVBoxLayout(project_tab)
        project_layout.setContentsMargins(4, 4, 4, 4)
        project_layout.setSpacing(6)
        project_layout.addWidget(QLabel("Vista previa"))
        project_layout.addWidget(self.project_preview, 1)
        project_layout.addWidget(QLabel("Resumen del proyecto"))
        project_layout.addWidget(self.project_summary)

        manual_tab = QWidget()
        manual_layout = QVBoxLayout(manual_tab)
        manual_layout.setContentsMargins(0, 0, 0, 0)
        manual_layout.setSpacing(6)
        manual_hint = QLabel(
            "Fallback manual: usa estas listas mientras el Graph editable se estabiliza."
        )
        self._manual_hint = manual_hint
        manual_hint.setWordWrap(True)
        manual_tabs = QTabWidget()
        manual_gpio_row = QWidget()
        manual_gpio_layout = QHBoxLayout(manual_gpio_row)
        manual_gpio_layout.setContentsMargins(4, 0, 4, 0)
        manual_gpio_layout.setSpacing(6)
        manual_gpio_label = QLabel("GPIO manual")
        manual_gpio_label.setStyleSheet("font-weight:600; font-size:11px;")
        self._manual_gpio_label = manual_gpio_label
        manual_gpio_layout.addWidget(manual_gpio_label)
        manual_gpio_layout.addWidget(self.gpio_port)
        manual_gpio_layout.addWidget(self.assign_button)
        manual_gpio_layout.addWidget(self.bulk_clear_button)
        manual_gpio_layout.addStretch(1)
        manual_tabs.addTab(cameras_tab, _icon("camera-video", size=16), "Cámaras")
        manual_tabs.addTab(gpio_tab, _icon("cpu", size=16), "GPIO")
        manual_layout.addWidget(manual_hint)
        manual_layout.addWidget(manual_gpio_row)
        manual_layout.addWidget(manual_tabs, 1)

        right_tabs.addTab(self.graph_view, _icon("diagram-3", size=16), "Graph")
        right_tabs.addTab(manual_tab, _icon("sliders", size=16), "Manual")
        right_tabs.addTab(gallery_tab, _icon("grid-3x3-gap", size=16), "Galería")
        self._label_tab_index = right_tabs.count()
        right_tabs.addTab(label_tab, _icon("tag", size=16), "Label")
        right_tabs.addTab(project_tab, _icon("folder", size=16), "Proyecto")
        self.manual_tabs = manual_tabs
        self.right_tabs = right_tabs

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(labels_box)
        self.splitter.addWidget(right_tabs)
        self._apply_layout_orientation(initial=True)

        self.projects.currentRowChanged.connect(lambda r: self._sync_combo_index(self.project_combo, r))
        self.projects.currentRowChanged.connect(lambda _r: self._sync_graph_project())
        self.cameras.currentRowChanged.connect(lambda r: self._sync_combo_index(self.camera_combo, r))
        self.lines.currentRowChanged.connect(lambda r: self._sync_combo_index(self.line_combo, r))
        self.cameras.currentItemChanged.connect(lambda *_: self._apply_camera_whitelist_to_gallery())

        toolbar = self._build_top_toolbar()
        status_row = self._build_status_row()
        search_row = self._build_global_search()
        selector_row = self._build_selector_row()

        root.addWidget(toolbar)
        root.addWidget(status_row)
        root.addWidget(search_row)
        root.addWidget(selector_row)
        root.addWidget(self.splitter, 1)

    _SELECTOR_LABEL_QSS = "color:#8b95a1; font-weight:600; font-size:11px;"

    def set_theme(self, theme: str) -> None:
        from ui.theme import tokens as _tokens
        t = _tokens(theme)

        _list_qss = f"""
            QListWidget {{
                border: 1px solid {t['border']};
                border-radius: 6px;
                background: {t['surface']};
            }}
            QListWidget[dropActive="true"] {{
                border: 1px dashed {t['info']};
                background: {t['hover']};
            }}
            QListWidget::item {{
                margin: 2px;
                padding: 6px 8px;
                border: 1px solid {t['border']};
                border-radius: 6px;
                background: {t['surface2']};
            }}
            QListWidget::item:selected {{
                background: {t['hover']};
                border-color: {t['info']};
            }}
        """
        for widget in (self.projects, self.cameras, self.lines, self.assigned, self.gpio_ports):
            widget.setStyleSheet(_list_qss)

        self.labels.setStyleSheet(
            f"QListWidget {{ background:{t['surface']}; border:1px solid {t['border']}; border-radius:6px; }}"
            f"QListWidget::item {{ padding:0px; }}"
            f"QListWidget::item:selected {{ background:{t['hover']}; }}"
        )

        _panel_qss = f"padding:8px; border:1px solid {t['border']}; border-radius:8px; background:{t['surface']}; color:{t['text']};"
        self.label_detail.setStyleSheet(_panel_qss)
        self.label_detail_image.setStyleSheet(
            f"background:{t['surface2']}; border:1px solid {t['border']}; border-radius:8px; color:{t['muted']};"
        )
        self.gpio_preview.setStyleSheet(
            f"padding:8px; border:1px solid {t['border']}; border-radius:8px; background:{t['surface']}; color:{t['text']};"
        )
        self.project_preview.setStyleSheet(
            f"background:{t['surface']}; color:{t['muted']}; border:1px solid {t['border']}; border-radius:8px;"
        )
        self.labels_hint.setStyleSheet(f"color:{t['muted']}; font-size:11px;")
        self.coverage_label.setStyleSheet(f"color:{t['muted2']}; font-size:11px;")

        if self.graph_view is not None:
            self.graph_view.setStyleSheet("")
            self.graph_view.set_theme(theme)
        self.label_gallery.set_theme(theme)

        # Toolbar bars — must setStyleSheet directly on the bar widget (not via parent cascade)
        _bar_qss = f"background:{t['panel']}; border:1px solid {t['border']}; border-radius:8px;"
        if hasattr(self, "_top_toolbar_bar"):
            self._top_toolbar_bar.setStyleSheet(f"QWidget#forgeTopBar {{ {_bar_qss} }}")
        if hasattr(self, "_selector_bar"):
            self._selector_bar.setStyleSheet(f"QWidget#forgeSelectorBar {{ {_bar_qss} }}")

        # Selector row labels
        _lbl_qss = f"color:{t['muted']}; font-weight:600; font-size:11px;"
        for lbl in getattr(self, "_selector_labels", []):
            lbl.setStyleSheet(_lbl_qss)

        # Status row
        if hasattr(self, "connection_url_pill"):
            self.connection_url_pill.setStyleSheet(
                f"QLabel {{ padding:4px 10px; border-radius:12px; background:{t['surface2']}; color:{t['muted']}; font-size:11px; }}"
            )
        for chip in (
            getattr(self, "connection_pill", None),
            getattr(self, "labels_chip", None),
            getattr(self, "cameras_chip", None),
            getattr(self, "gpio_chip", None),
        ):
            if chip is not None:
                chip.set_theme(theme)

        # Hint labels
        _hint_qss = f"color:{t['muted']}; font-size:11px;"
        for lbl in (
            getattr(self, "_cameras_hint", None),
            getattr(self, "_manual_hint", None),
        ):
            if lbl is not None:
                lbl.setStyleSheet(_hint_qss)
        if hasattr(self, "_ports_header"):
            self._ports_header.setStyleSheet(f"font-weight:600; color:{t['muted']};")
        if hasattr(self, "_manual_gpio_label"):
            self._manual_gpio_label.setStyleSheet(f"color:{t['muted']}; font-weight:600; font-size:11px;")

        # Label list delegate
        if hasattr(self, "labels") and hasattr(self.labels.itemDelegate(), "set_theme"):
            self.labels.itemDelegate().set_theme(theme)
            self.labels.viewport().update()

    def _build_selector_row(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("forgeSelectorBar")
        self._selector_bar = bar
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(6)

        proj_label = QLabel("Proyecto")
        layout.addWidget(proj_label)
        layout.addWidget(self.project_combo)

        layout.addSpacing(4)
        cam_label = QLabel("Cámara")
        layout.addWidget(cam_label)
        layout.addWidget(self.camera_combo)
        layout.addWidget(self.create_camera_button)

        layout.addSpacing(4)
        line_label = QLabel("Línea")
        layout.addWidget(line_label)
        layout.addWidget(self.line_combo)
        self.line_name.setMinimumWidth(120)
        layout.addWidget(self.line_name)
        layout.addWidget(self.create_line_button)

        layout.addStretch(1)
        self._selector_labels = [proj_label, cam_label, line_label]
        return bar

    def _on_project_combo_changed(self, index: int) -> None:
        if index < 0:
            return
        if self.projects.currentRow() != index:
            self.projects.setCurrentRow(index)

    def _on_camera_combo_changed(self, index: int) -> None:
        if index < 0:
            return
        if self.cameras.currentRow() != index:
            self.cameras.setCurrentRow(index)

    def _on_line_combo_changed(self, index: int) -> None:
        if index < 0:
            return
        if self.lines.currentRow() != index:
            self.lines.setCurrentRow(index)

    def _sync_combo_index(self, combo: QComboBox, row: int) -> None:
        if combo.currentIndex() == row or row < 0:
            return
        combo.blockSignals(True)
        combo.setCurrentIndex(row)
        combo.blockSignals(False)

    def _sync_combo_to_list(self, combo: QComboBox, list_widget: QListWidget) -> None:
        combo.blockSignals(True)
        combo.clear()
        for i in range(list_widget.count()):
            item = list_widget.item(i)
            if item is None:
                continue
            combo.addItem(item.text(), item.data(Qt.ItemDataRole.UserRole))
        combo.blockSignals(False)

    def _sync_graph_project(self) -> None:
        if not self.graph_view is not None:
            return
        item = self.projects.currentItem()
        if item is None:
            self.graph_view.set_project("Proyecto")
            return
        text = item.text().split(":", 1)[1].strip() if ":" in item.text() else item.text().strip()
        self.graph_view.set_project(text)

    def _select_camera_by_id(self, camera_id: object) -> None:
        try:
            target = int(camera_id)
        except (TypeError, ValueError):
            return
        self.select_camera_by_id(target)

    def _select_label_by_name(self, name: str) -> None:
        target = name.strip()
        if not target:
            return
        for index in range(self.labels.count()):
            item = self.labels.item(index)
            data = item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(data, dict):
                continue
            if str(data.get("name", "")).strip() == target:
                self.labels.setCurrentItem(item)
                self._on_label_item_clicked(item)
                return

    def _activate_label_from_graph(self, name: str) -> None:
        self._select_label_by_name(name)
        if self._label_tab_index >= 0:
            self.right_tabs.setCurrentIndex(self._label_tab_index)

    def _build_top_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("forgeTopBar")
        self._top_toolbar_bar = bar
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        layout.addWidget(self.connect_button)
        layout.addWidget(self.refresh_button)
        layout.addWidget(self._toolbar_separator())
        layout.addWidget(self.send_conf_button)
        layout.addWidget(self.download_model_button)
        layout.addStretch(1)
        layout.addWidget(self.help_button)
        return bar

    def _build_status_row(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(8)

        self.connection_pill = IconChip(
            "Sin conexión",
            "question-circle",
            icon_color="muted",
            bg_color="#1b2028",
            fg_color="#9fb2c8",
        )
        self.connection_pill.setToolTip("Estado de conexión a Forge")

        self.connection_url_pill = QLabel("—")
        self.connection_url_pill.setStyleSheet(
            "QLabel { padding:4px 10px; border-radius:12px; font-size:11px; }"
        )
        self.connection_url_pill.setMaximumWidth(360)
        self.connection_url_pill.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.labels_chip = IconChip("0 labels", "tag", icon_color="accent", fg_color="#9fb2c8")
        self.labels_chip.setToolTip("Número total de labels disponibles en el proyecto activo.")

        self.cameras_chip = IconChip("0 / 0 cám", "camera-video", icon_color="info", fg_color="#9fb2c8")
        self.cameras_chip.setToolTip("Labels asignadas a alguna cámara / total.")

        self.gpio_chip = IconChip("0 / 0 gpio", "plug", icon_color="warning", fg_color="#9fb2c8")
        self.gpio_chip.setToolTip("Labels enrutadas a un puerto GPIO / total.")

        layout.addWidget(self.connection_pill)
        layout.addWidget(self.connection_url_pill, 1)
        layout.addStretch(0)
        layout.addWidget(self.labels_chip)
        layout.addWidget(self.cameras_chip)
        layout.addWidget(self.gpio_chip)
        return row

    _COMPACT_WIDTH_THRESHOLD = 1100

    def _apply_layout_orientation(self, *, initial: bool = False) -> None:
        if not hasattr(self, "splitter"):
            return
        if self._ui_profile == "single":
            target = Qt.Orientation.Vertical
        else:
            target = (
                Qt.Orientation.Vertical
                if self.width() < self._COMPACT_WIDTH_THRESHOLD
                else Qt.Orientation.Horizontal
            )
        if target == self._current_orientation and not initial:
            return
        self.splitter.setOrientation(target)
        count = self.splitter.count()
        for i in range(count):
            self.splitter.setStretchFactor(i, 1)
        if target == Qt.Orientation.Vertical:
            self.splitter.setSizes([200, 700] if count == 2 else [300] * count)
        else:
            self.splitter.setSizes([280, 1020] if count == 2 else [500] * count)
        self._current_orientation = target

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_layout_orientation()

    def _build_global_search(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(6)

        icon_label = QLabel()
        icon_label.setPixmap(_icon("search", size=14, color="muted").pixmap(14, 14))
        icon_label.setFixedSize(18, 18)
        layout.addWidget(icon_label)

        self.global_search = QLineEdit()
        self.global_search.setPlaceholderText(
            "Buscar proyecto, cámara, línea o label...  (/ para enfocar)"
        )
        self.global_search.setClearButtonEnabled(True)
        self.global_search.textChanged.connect(self._on_global_search_changed)
        layout.addWidget(self.global_search, 1)
        return row

    def _on_global_search_changed(self, text: str) -> None:
        text = (text or "").strip()
        self._filter_simple_list(self.projects, text)
        self._filter_simple_list(self.cameras, text)
        self._filter_simple_list(self.lines, text)
        self._filter_simple_list(self.assigned, text)
        if hasattr(self, "label_search") and self.label_search.text() != text:
            self.label_search.blockSignals(True)
            self.label_search.setText(text)
            self.label_search.blockSignals(False)
            self.filter_label_views(text)

    @staticmethod
    def _filter_simple_list(widget: QListWidget, needle: str) -> None:
        needle_lower = needle.lower()
        for i in range(widget.count()):
            item = widget.item(i)
            if item is None:
                continue
            if not needle_lower:
                item.setHidden(False)
                continue
            haystack = (item.text() or "").lower()
            tooltip = (item.toolTip() or "").lower()
            item.setHidden(needle_lower not in haystack and needle_lower not in tooltip)

    @staticmethod
    def _toolbar_separator() -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Plain)
        sep.setStyleSheet("")
        return sep

    _CONN_STYLES = {
        "connected": ("Conectado", "#1c3328", "#62d2a2", "check-circle", "accent"),
        "connecting": ("Conectando…", "#1b2028", "#f4b942", "arrow-repeat", "warning"),
        "disconnected": ("Sin conexión", "#1b2028", "#9fb2c8", "question-circle", "muted"),
        "error": ("Error", "#3a1f24", "#e66b6b", "x-circle", "danger"),
    }

    def set_connection_state(self, state: str, *, url: str = "") -> None:
        text, bg, fg, icon_name, icon_color = self._CONN_STYLES.get(state, self._CONN_STYLES["disconnected"])
        if hasattr(self, "connection_pill"):
            self.connection_pill.set_content(text, icon_name=icon_name, icon_color=icon_color, bg_color=bg, fg_color=fg)
            self.connection_pill.setToolTip(f"Estado de conexión a Forge: {text}")
        if url and hasattr(self, "connection_url_pill"):
            self.connection_url_pill.setText(self._truncate_url(url))
            self.connection_url_pill.setToolTip(url)

    @staticmethod
    def _truncate_url(url: str, limit: int = 48) -> str:
        u = url.strip()
        if len(u) <= limit:
            return u
        return u[: limit - 3] + "…"

    def _build_filter_chips(self) -> None:
        self.filter_chip_layout = QHBoxLayout()
        self.filter_chip_layout.setContentsMargins(0, 0, 0, 0)
        self.filter_chip_layout.setSpacing(4)
        self._filter_group = QButtonGroup(self)
        self._filter_group.setExclusive(True)
        self._filter_buttons: dict[str, QToolButton] = {}
        chips = [
            (self.FILTER_ALL, "Todos", "grid-3x3-gap", "primary"),
            (self.FILTER_NO_CAMERA, "Sin cámara", "camera-video", "danger"),
            (self.FILTER_NO_GPIO, "Sin GPIO", "plug", "warning"),
            (self.FILTER_ASSIGNED, "Asignados", "check-lg", "accent"),
        ]
        for mode, label, icon_name, color in chips:
            btn = QToolButton()
            btn.setText(label)
            btn.setCheckable(True)
            btn.setAutoExclusive(False)
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            btn.setIcon(_icon(icon_name, size=14, color=color))
            btn.setIconSize(QSize(14, 14))
            btn.setStyleSheet(
                """
                QToolButton {
                    padding: 4px 10px;
                    border: 1px solid #2a313a;
                    border-radius: 12px;
                    background: #141820;
                    color: #cfd6e1;
                }
                QToolButton:checked {
                    background: #243043;
                    border-color: #4d6b8a;
                    color: #ffffff;
                }
                QToolButton:hover { background: #1b2028; }
                """
            )
            btn.clicked.connect(lambda _checked=False, m=mode: self._set_filter_mode(m))
            self._filter_group.addButton(btn)
            self._filter_buttons[mode] = btn
            self.filter_chip_layout.addWidget(btn)
        self.filter_chip_layout.addStretch(1)
        self._filter_buttons[self.FILTER_ALL].setChecked(True)

    def _build_group_combo(self) -> None:
        self.group_combo = QComboBox()
        self.group_combo.addItem(_icon("slash-circle", size=16), "Sin agrupar", "none")
        self.group_combo.addItem(_icon("tag", size=16), "Por prefijo", "prefix")
        self.group_combo.addItem(_icon("tags", size=16), "Por tipo", "type")
        self.group_combo.addItem(_icon("activity", size=16), "Por estado", "status")
        self.group_combo.currentIndexChanged.connect(self._on_group_changed)

    def _install_shortcuts(self) -> None:
        focus_search = QShortcut(QKeySequence("/"), self)
        focus_search.activated.connect(
            lambda: self.global_search.setFocus() if hasattr(self, "global_search") else self.label_search.setFocus()
        )
        focus_search.setContext(Qt.ShortcutContext.WindowShortcut)

        focus_filter = QShortcut(QKeySequence(Qt.Modifier.CTRL | Qt.Key.Key_F), self)
        focus_filter.activated.connect(lambda: self.component_filter.setFocus())

        clear = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        clear.activated.connect(self._clear_filters)

        select_all = QShortcut(QKeySequence(Qt.Modifier.CTRL | Qt.Key.Key_A), self.labels)
        select_all.activated.connect(self._select_all_visible_labels)
        select_all.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)

    def _clear_filters(self) -> None:
        if hasattr(self, "global_search"):
            self.global_search.clear()
        self.label_search.clear()
        self.component_filter.clear()
        self._set_filter_mode(self.FILTER_ALL)

    def _select_all_visible_labels(self) -> None:
        self.labels.clearSelection()
        for i in range(self.labels.count()):
            item = self.labels.item(i)
            if item.isHidden() or item.data(Qt.ItemDataRole.UserRole + 1):
                continue
            item.setSelected(True)

    def _set_filter_mode(self, mode: str) -> None:
        self._filter_mode = mode
        for key, btn in self._filter_buttons.items():
            btn.setChecked(key == mode)
        self.filter_label_views(self.label_search.text())

    def _on_group_changed(self, _index: int) -> None:
        self._group_mode = self.group_combo.currentData() or "none"
        self.set_labels(self._label_source)

    def set_status(self, text: str) -> None:
        self.preview_status.setPlainText(text)
        if not hasattr(self, "connection_pill"):
            return
        lower = text.lower()
        if "ready" in lower or "refreshed" in lower or "ok" in lower:
            self.set_connection_state("connected")
        elif "error" in lower or "failed" in lower or "no disponible" in lower:
            self.set_connection_state("error")
        elif "conectando" in lower or "loading" in lower:
            self.set_connection_state("connecting")

    def set_summary(self, text: str) -> None:
        self.project_summary.setPlainText(text)

    def set_projects(self, items: list[tuple[int, str]]) -> None:
        self.projects.clear()
        for project_id, name in items:
            item = QListWidgetItem(f"{project_id}: {name}")
            item.setData(Qt.ItemDataRole.UserRole, project_id)
            item.setIcon(_icon("folder", size=16, color="muted"))
            self.projects.addItem(item)
        if hasattr(self, "project_combo"):
            self._sync_combo_to_list(self.project_combo, self.projects)
        self._sync_graph_project()

    def select_project_by_id(self, project_id: int) -> bool:
        for index in range(self.projects.count()):
            item = self.projects.item(index)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == project_id:
                self.projects.setCurrentRow(index)
                return True
        return False

    def select_camera_by_id(self, camera_id: int) -> bool:
        for index in range(self.cameras.count()):
            item = self.cameras.item(index)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == camera_id:
                self.cameras.setCurrentRow(index)
                return True
        return False

    def set_cameras(self, items: list[tuple[int, str, list[str]]]) -> None:
        self.cameras.clear()
        graph_cameras: list[dict[str, object]] = []
        for camera_id, name, components in items:
            if name.strip():
                graph_cameras.append({"id": camera_id, "name": name.strip()})
            count = len(components)
            suffix = f"  ({count})" if count else ""
            item = QListWidgetItem(f"{camera_id}: {name}{suffix}")
            item.setData(Qt.ItemDataRole.UserRole, camera_id)
            item.setIcon(_icon("camera-video", size=16, color="accent" if count else "muted"))
            tooltip = f"Drop labels here to assign to {name}"
            if components:
                preview = ", ".join(components[:8])
                if len(components) > 8:
                    preview += f" (+{len(components) - 8})"
                tooltip += f"\nLabels: {preview}"
            item.setToolTip(tooltip)
            item.setSizeHint(item.sizeHint() * 1.3)
            self.cameras.addItem(item)
        if hasattr(self, "camera_combo"):
            self._sync_combo_to_list(self.camera_combo, self.cameras)
        if self.graph_view is not None:
            self.graph_view.set_cameras(graph_cameras)

    def set_lines(self, items: list[tuple[int, str]]) -> None:
        self.lines.clear()
        for line_id, name in items:
            item = QListWidgetItem(f"{line_id}: {name}")
            item.setData(Qt.ItemDataRole.UserRole, line_id)
            item.setIcon(_icon("diagram-3", size=16, color="info"))
            item.setSizeHint(item.sizeHint() * 1.2)
            self.lines.addItem(item)
        if hasattr(self, "line_combo"):
            self._sync_combo_to_list(self.line_combo, self.lines)

    def _label_dict(self, label: object) -> dict:
        if isinstance(label, dict):
            data = dict(label)
            data["name"] = str(data.get("name", "")).strip()
            return data
        text = str(label).strip()
        return {"name": text, "type": "", "color": "", "preview_base64": ""}

    def set_labels(self, labels: list[str] | list[dict]) -> None:
        previous_selected = {item.data(Qt.ItemDataRole.UserRole)["name"] for item in self.labels.selectedItems() if isinstance(item.data(Qt.ItemDataRole.UserRole), dict)}
        self._label_source = list(labels)
        self.labels.clear()
        normalized = [d for label in labels for d in [self._label_dict(label)] if d["name"]]
        if self.graph_view is not None:
            self.graph_view.set_labels(normalized)

        groups = self._group_labels(normalized)
        for header, members in groups:
            if header:
                head_item = QListWidgetItem(header)
                head_item.setFlags(Qt.ItemFlag.NoItemFlags)
                head_item.setData(Qt.ItemDataRole.UserRole + 1, True)
                icon_name, icon_color = _group_header_icon(self._group_mode)
                head_item.setIcon(_icon(icon_name, size=14, color=icon_color))
                self.labels.addItem(head_item)
            for data in members:
                self._append_label_item(data, restore_selection=previous_selected)

        self.labels_hint.setText(
            f"{len(normalized)} labels (drag a cámaras/GPIO · Ctrl+A para todos los visibles · / para buscar)"
        )
        self._schedule_label_refresh()

    def _append_label_item(self, data: dict, *, restore_selection: set[str]) -> None:
        name = data.get("name", "")
        item = QListWidgetItem(name)
        item.setData(Qt.ItemDataRole.UserRole, data)
        icon_name, icon_color = _label_item_icon(name, self._camera_for_label, self._gpio_for_label)
        item.setIcon(_icon(icon_name, size=16, color=icon_color))
        if name in restore_selection:
            item.setSelected(True)
        self.labels.addItem(item)

    def _group_labels(self, labels: list[dict]) -> list[tuple[str, list[dict]]]:
        if self._group_mode == "none" or not labels:
            return [("", labels)]
        buckets: dict[str, list[dict]] = {}
        if self._group_mode == "prefix":
            for data in labels:
                key = _label_prefix(data.get("name", ""))
                buckets.setdefault(key, []).append(data)
        elif self._group_mode == "type":
            for data in labels:
                key = (str(data.get("type", "")).strip() or "—").lower()
                buckets.setdefault(key, []).append(data)
        elif self._group_mode == "status":
            for data in labels:
                name = data.get("name", "")
                has_cam = bool(self._camera_for_label.get(name))
                has_gpio = bool(self._gpio_for_label.get(name))
                if has_cam and has_gpio:
                    key = "asignados"
                elif has_cam or has_gpio:
                    key = "parciales"
                else:
                    key = "sin asignar"
                buckets.setdefault(key, []).append(data)
        else:
            return [("", labels)]

        ordered = sorted(buckets.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        return [(f"{key.upper()}  ({len(members)})", members) for key, members in ordered]

    def _schedule_label_refresh(self) -> None:
        QMetaObject.invokeMethod(self._label_refresh_timer, "start", Qt.ConnectionType.QueuedConnection)

    def _do_label_refresh(self) -> None:
        self._refresh_label_tooltips()
        self._update_coverage()
        self.filter_label_views(self.label_search.text())

    def _refresh_label_tooltips(self) -> None:
        for i in range(self.labels.count()):
            item = self.labels.item(i)
            data = item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(data, dict):
                continue
            name = data.get("name", "")
            cam_list = self._camera_for_label.get(name, [])
            gpio = self._gpio_for_label.get(name, "")
            icon_name, icon_color = _label_item_icon(name, self._camera_for_label, self._gpio_for_label)
            item.setIcon(_icon(icon_name, size=16, color=icon_color))
            tooltip_lines = [f"<b>{name}</b>"]
            if data.get("type"):
                tooltip_lines.append(f"Tipo: {data.get('type')}")
            if data.get("color"):
                tooltip_lines.append(f"Color: {data.get('color')}")
            if cam_list:
                tooltip_lines.append("Cámaras: " + ", ".join(cam_list[:6]) + (f" (+{len(cam_list) - 6})" if len(cam_list) > 6 else ""))
            else:
                tooltip_lines.append("<i>Sin cámara asignada</i>")
            if gpio:
                tooltip_lines.append(f"GPIO: {gpio}")
            else:
                tooltip_lines.append("<i>Sin GPIO asignado</i>")
            item.setToolTip("<br>".join(tooltip_lines))

    def filter_labels(self, text: str) -> None:
        self.filter_label_views(self.label_search.text() or text)

    def _apply_camera_whitelist_to_gallery(self) -> None:
        item = self.cameras.currentItem()
        if item is None:
            self.label_gallery.set_name_whitelist(None)
            return
        cam_name = item.text().split(":", 1)[-1].strip().lower()
        names = self._label_for_camera.get(cam_name, set())
        self.label_gallery.set_name_whitelist(names if names else set())

    def filter_label_views(self, text: str) -> None:
        needle = text.strip().lower()
        component_needle = self.component_filter.text().strip().lower()
        last_visible_index = -1
        active_group_visible = False
        group_indexes: list[int] = []

        for i in range(self.labels.count()):
            item = self.labels.item(i)
            is_header = bool(item.data(Qt.ItemDataRole.UserRole + 1))
            if is_header:
                if last_visible_index >= 0 and not active_group_visible:
                    self.labels.item(last_visible_index).setHidden(True)
                last_visible_index = i
                active_group_visible = False
                group_indexes.append(i)
                item.setHidden(False)
                continue
            data = item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(data, dict):
                item.setHidden(True)
                continue
            name = data.get("name", "")
            haystack = " ".join(str(data.get(key, "")) for key in ("name", "type", "color")).lower()
            text_match = (not needle or needle in haystack) and (not component_needle or component_needle in haystack)
            mode_match = self._matches_filter_mode(name)
            visible = text_match and mode_match
            item.setHidden(not visible)
            if visible:
                active_group_visible = True

        if last_visible_index >= 0 and not active_group_visible:
            self.labels.item(last_visible_index).setHidden(True)

        self.label_gallery.set_filter(needle or component_needle)
        visible_items = [self.labels.item(i) for i in range(self.labels.count())
                         if not self.labels.item(i).isHidden() and not self.labels.item(i).data(Qt.ItemDataRole.UserRole + 1)]
        current = self.labels.currentItem()
        if visible_items and (current is None or current.isHidden() or current.data(Qt.ItemDataRole.UserRole + 1)):
            self.labels.setCurrentItem(visible_items[0])
            self._on_label_item_clicked(visible_items[0])

        self.labels_hint.setText(
            f"{len(visible_items)} de {sum(1 for i in range(self.labels.count()) if not self.labels.item(i).data(Qt.ItemDataRole.UserRole + 1))} labels"
        )

    def _matches_filter_mode(self, name: str) -> bool:
        if self._filter_mode == self.FILTER_ALL:
            return True
        has_cam = bool(self._camera_for_label.get(name))
        has_gpio = bool(self._gpio_for_label.get(name))
        if self._filter_mode == self.FILTER_NO_CAMERA:
            return not has_cam
        if self._filter_mode == self.FILTER_NO_GPIO:
            return not has_gpio
        if self._filter_mode == self.FILTER_ASSIGNED:
            return has_cam and has_gpio
        return True

    def _selection_summary(self, item: QListWidgetItem | None) -> str:
        if item is None:
            return ""
        text = item.text().strip()
        if ":" in text:
            text = text.split(":", 1)[1].strip()
        if "[" in text:
            text = text.split("[", 1)[0].strip()
        if len(text) > 42:
            text = text[:39].rstrip() + "..."
        return text

    def set_assigned(self, labels: list[str]) -> None:
        self.assigned.clear()
        for label in labels:
            text = _label_text(label)
            if text:
                item = QListWidgetItem(text)
                item.setIcon(_icon("check-lg", size=16, color="accent"))
                self.assigned.addItem(item)

    def set_gpio_assignments(self, assignments: dict[str, str]) -> None:
        port_map: dict[str, list[str]] = {}
        for label, port in sorted(assignments.items()):
            port_text = str(port).strip()
            text = _label_text(label)
            if text and port_text:
                port_map.setdefault(port_text, []).append(text)

        _gpio_ports = [f"GPIO{n}" for n in range(2, 28)]
        if self.gpio_ports.count() == len(_gpio_ports):
            for idx, port in enumerate(_gpio_ports):
                item = self.gpio_ports.item(idx)
                labels = port_map.get(port, [])
                count = len(labels)
                suffix = f"  ·  {count} labels" if count else "  ·  vacío"
                item.setText(f"{port}{suffix}")
                item.setIcon(_icon("plug", size=16, color="warning" if labels else "muted"))
                tooltip = f"Drop labels here to assign to {port}"
                if labels:
                    tooltip += "\n" + "\n".join(f"• {label}" for label in labels)
                item.setToolTip(tooltip)
        else:
            self.gpio_ports.clear()
            for port in _gpio_ports:
                labels = port_map.get(port, [])
                count = len(labels)
                suffix = f"  ·  {count} labels" if count else "  ·  vacío"
                item = QListWidgetItem(f"{port}{suffix}")
                item.setData(Qt.ItemDataRole.UserRole, port)
                item.setIcon(_icon("plug", size=16, color="warning" if labels else "muted"))
                tooltip = f"Drop labels here to assign to {port}"
                if labels:
                    tooltip += "\n" + "\n".join(f"• {label}" for label in labels)
                item.setToolTip(tooltip)
                item.setSizeHint(item.sizeHint() * 1.25)
                self.gpio_ports.addItem(item)

        if port_map:
            lines = []
            for port, labels in sorted(port_map.items()):
                preview = ", ".join(_short_label(label) for label in labels[:5])
                if len(labels) > 5:
                    preview += f" (+{len(labels) - 5})"
                lines.append(f"{port}  →  {preview}")
            if len(lines) > 12:
                hidden = len(lines) - 12
                lines = lines[:12] + [f"+{hidden} más puertos"]
            self.gpio_preview.setText("\n".join(lines))
        else:
            self.gpio_preview.setText("Drop labels onto a GPIO port")

        self._gpio_for_label = {str(label): str(port) for label, port in assignments.items() if str(port).strip()}
        if self.graph_view is not None:
            self.graph_view.set_gpio_assignments(self._gpio_for_label)
        self.label_gallery.set_assignment_context(self._camera_for_label, self._gpio_for_label)
        self._schedule_label_refresh()

    def set_label_assignments(self, camera_for_label: dict[str, list[str]]) -> None:
        self._camera_for_label = {name: list(cams) for name, cams in (camera_for_label or {}).items()}
        index: dict[str, set[str]] = {}
        for label, cams in self._camera_for_label.items():
            for cam in cams:
                index.setdefault(cam.lower(), set()).add(label.lower())
        self._label_for_camera = index
        if self.graph_view is not None:
            self.graph_view.set_label_assignments(self._camera_for_label)
        self.label_gallery.set_assignment_context(self._camera_for_label, self._gpio_for_label)
        self._schedule_label_refresh()

    def _update_coverage(self) -> None:
        total = with_camera = with_gpio = 0
        for i in range(self.labels.count()):
            item = self.labels.item(i)
            if item.data(Qt.ItemDataRole.UserRole + 1):
                continue
            total += 1
            data = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(data, dict):
                name = data.get("name", "")
                if self._camera_for_label.get(name):
                    with_camera += 1
                if self._gpio_for_label.get(name):
                    with_gpio += 1
        self.coverage_label.setText(f"{total} labels · cám {with_camera}/{total} · gpio {with_gpio}/{total}")

        if not hasattr(self, "labels_chip"):
            return
        unassigned_cam = total - with_camera
        unassigned_gpio = total - with_gpio
        self.labels_chip.set_content(
            f"{total} labels",
            icon_name="tag",
            icon_color="accent",
            bg_color="#1b2028",
            fg_color="#9fb2c8",
        )
        self.cameras_chip.set_content(
            f"{with_camera} / {total} cám",
            icon_name="camera-video",
            icon_color="info",
            bg_color="#1b2028",
            fg_color="#9fb2c8",
        )
        self.cameras_chip.setToolTip(
            f"{with_camera} labels enrutadas a una cámara · {unassigned_cam} pendientes."
        )

        ratio = (with_gpio / total) if total else 1.0
        if total == 0:
            color_bg, color_fg = "#1b2028", "#9fb2c8"
        elif ratio < 0.5:
            color_bg, color_fg = "#3a1f24", "#e9a4a4"
        elif ratio < 1.0:
            color_bg, color_fg = "#332a16", "#f4cd6b"
        else:
            color_bg, color_fg = "#1c3328", "#88e0b3"
        self.gpio_chip.set_content(
            f"{with_gpio} / {total} gpio",
            icon_name="plug",
            icon_color="warning",
            bg_color=color_bg,
            fg_color=color_fg,
        )
        self.gpio_chip.setToolTip(
            f"{with_gpio} labels enrutadas a un puerto GPIO · {unassigned_gpio} pendientes."
        )

    def set_label_previews(self, items: list[dict]) -> None:
        self._label_source = list(items)
        self.label_gallery.set_assignment_context(self._camera_for_label, self._gpio_for_label)
        self.label_gallery.set_items(items)
        if items:
            self.set_selected_label_preview(items[0])
        else:
            self.label_detail.setText("Select a label to inspect")
            self.label_detail_image.clear()

    def set_selected_label_preview(self, item: dict) -> None:
        if not isinstance(item, dict):
            return
        name = str(item.get("name", "")).strip()
        label_type = str(item.get("type", "")).strip()
        color = str(item.get("color", "")).strip()
        crop = str(item.get("preview_base64", "")).strip()
        cams = self._camera_for_label.get(name, [])
        gpio = self._gpio_for_label.get(name, "")
        text = "\n".join([
            f"Name: {name}",
            f"Type: {label_type or 'n/a'}",
            f"Color: {color or 'n/a'}",
            f"Cámaras: {', '.join(cams) if cams else '—'}",
            f"GPIO: {gpio or '—'}",
        ])
        self.label_detail.setText(text)
        pixmap = QPixmap()
        if crop and pixmap.loadFromData(base64.b64decode(crop)):
            self.label_detail_image.setPixmap(
                pixmap.scaled(
                    420,
                    180,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        else:
            self.label_detail_image.setText("No crop available")

    def _on_gallery_label_selected(self, item: dict) -> None:
        self.set_selected_label_preview(item)
        self.label_selected.emit(item)

    def _on_label_item_clicked(self, item: QListWidgetItem) -> None:
        if item.data(Qt.ItemDataRole.UserRole + 1):
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(data, dict):
            self.set_selected_label_preview(data)
            self.label_selected.emit(data)
            name = str(data.get("name", "")).strip()
            if name and self.graph_view is not None:
                self.right_tabs.setCurrentIndex(0)
                self.graph_view.focus_label(name)

    def _emit_bulk_clear(self) -> None:
        labels = self.selected_labels()
        if labels:
            self.bulk_clear_requested.emit(labels)

    def _emit_send_conf(self) -> None:
        line_id = self.selected_line_id()
        if line_id is not None:
            self.send_conf_requested.emit(line_id)

    def _emit_download_model(self) -> None:
        project_id = self.selected_project_id()
        self.download_model_requested.emit(project_id if project_id is not None else -1)

    def set_model_download_available(self, available: bool) -> None:
        self.download_model_button.setEnabled(True)
        self.download_model_button.setToolTip(
            "Descarga el modelo .pt desde la URL/asset configurado"
            if available
            else "Descarga el .pt del proyecto Forge seleccionado"
        )

    _ARMED_STYLE = (
        "QPushButton { padding: 6px 12px; border-radius: 6px;"
        " background: #c84a4a; color: white; font-weight: 600;"
        " border: 1px solid #d65a5a; }"
        " QPushButton:hover { background: #d65a5a; }"
    )

    def _arm_button(self, button: QPushButton, *, normal_text: str, armed_text: str, action) -> None:
        state = {"armed": False, "timer": None}
        normal_style = button.styleSheet()

        def disarm() -> None:
            state["armed"] = False
            button.setText(normal_text)
            button.setStyleSheet(normal_style)

        def on_click() -> None:
            if state["armed"]:
                disarm()
                action()
                return
            state["armed"] = True
            button.setText(armed_text)
            button.setStyleSheet(self._ARMED_STYLE)
            timer = state.get("timer")
            if timer is not None:
                timer.stop()
            t = QTimer(button)
            t.setSingleShot(True)
            t.setInterval(3000)
            t.timeout.connect(lambda: state["armed"] and disarm())
            state["timer"] = t
            t.start()

        button.clicked.connect(on_click)

    def set_project_preview(self, image_data: bytes | None) -> None:
        if not image_data:
            self.project_preview.setText("Preview del proyecto")
            self.project_preview.setPixmap(QPixmap())
            return
        pixmap = QPixmap()
        if pixmap.loadFromData(image_data):
            self.project_preview.setPixmap(
                pixmap.scaled(
                    self.project_preview.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self.project_preview.setText("")
        else:
            self.project_preview.setText("No se pudo cargar preview")
            self.project_preview.setPixmap(QPixmap())

    def connection_values(self) -> dict[str, str]:
        return {
            "base_url": self.base_url.text().strip(),
            "username": self.username.text().strip(),
            "password": self.password.text().strip(),
            "token": self.token.text().strip(),
        }

    def set_connection_values(self, *, base_url: str = "", username: str = "", password: str = "", token: str = "") -> None:
        self.base_url.setText(base_url)
        self.username.setText(username)
        self.password.setText(password)
        self.token.setText(token)
        if base_url and hasattr(self, "connection_url_pill"):
            self.connection_url_pill.setText(self._truncate_url(base_url))
            self.connection_url_pill.setToolTip(base_url)

    def selected_gpio_port(self) -> str:
        return self.gpio_port.currentText().strip()

    def selected_camera_id(self) -> int | None:
        item = self.cameras.currentItem()
        if not item:
            return None
        raw = item.data(Qt.ItemDataRole.UserRole)
        return int(raw) if isinstance(raw, int) else None

    def selected_project_id(self) -> int | None:
        item = self.projects.currentItem()
        if not item:
            return None
        raw = item.data(Qt.ItemDataRole.UserRole)
        return int(raw) if isinstance(raw, int) else None

    def selected_line_id(self) -> int | None:
        item = self.lines.currentItem()
        if not item:
            return None
        raw = item.data(Qt.ItemDataRole.UserRole)
        return int(raw) if isinstance(raw, int) else None

    def line_options(self) -> list[tuple[int, str]]:
        options: list[tuple[int, str]] = []
        for i in range(self.lines.count()):
            item = self.lines.item(i)
            line_id = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(line_id, int):
                text = item.text().split(":", 1)[1].strip() if ":" in item.text() else item.text()
                options.append((line_id, text))
        return options

    def selected_labels(self) -> list[str]:
        selected = []
        for item in self.labels.selectedItems():
            if item.data(Qt.ItemDataRole.UserRole + 1):
                continue
            data = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(data, dict):
                name = str(data.get("name", "")).strip()
                if name:
                    selected.append(name)
            else:
                selected.append(item.text())
        if selected:
            return list(dict.fromkeys(selected))
        item = self.labels.currentItem()
        if not item or item.data(Qt.ItemDataRole.UserRole + 1):
            return []
        data = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(data, dict):
            name = str(data.get("name", "")).strip()
            return [name] if name else []
        return [item.text()]

    def _restore_state(self) -> None:
        try:
            if not UI_STATE_PATH.exists():
                return
            payload = json.loads(UI_STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(payload, dict):
            return
        sizes = payload.get("forge_splitter_sizes")
        saved_orientation = payload.get("forge_splitter_orientation")
        if (
            isinstance(sizes, list)
            and all(isinstance(v, int) for v in sizes)
            and len(sizes) == self.splitter.count()
            and saved_orientation == self.splitter.orientation().value
        ):
            self.splitter.setSizes(sizes)
        group = payload.get("group_mode")
        if isinstance(group, str):
            idx = self.group_combo.findData(group)
            if idx >= 0:
                self.group_combo.setCurrentIndex(idx)
        filter_mode = payload.get("filter_mode")
        if isinstance(filter_mode, str) and filter_mode in self._filter_buttons:
            self._set_filter_mode(filter_mode)
        tab_index = payload.get("right_tab_index")
        if isinstance(tab_index, int) and 0 <= tab_index < self.right_tabs.count():
            self.right_tabs.setCurrentIndex(tab_index)

    def save_state(self) -> None:
        try:
            UI_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            payload: dict = {}
            if UI_STATE_PATH.exists():
                try:
                    existing = json.loads(UI_STATE_PATH.read_text(encoding="utf-8"))
                    if isinstance(existing, dict):
                        payload = existing
                except Exception:
                    payload = {}
            payload["forge_splitter_sizes"] = self.splitter.sizes()
            payload["forge_splitter_orientation"] = self.splitter.orientation().value
            payload["group_mode"] = self._group_mode
            payload["filter_mode"] = self._filter_mode
            payload["right_tab_index"] = self.right_tabs.currentIndex()
            UI_STATE_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
