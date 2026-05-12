"""Node graph overview for Forge label routing."""

from __future__ import annotations

import base64

from PyQt6.QtCore import QMetaObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QDropEvent, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabBar,
    QRubberBand,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ui.theme import tokens

for _name in ("DeviceCoordinateCache", "ItemCoordinateCache", "NoCache"):
    if not hasattr(QGraphicsItem, _name) and hasattr(QGraphicsItem.CacheMode, _name):
        setattr(QGraphicsItem, _name, getattr(QGraphicsItem.CacheMode, _name))
for _target in (QGraphicsItem, QGraphicsPathItem, QGraphicsTextItem):
    for _name in (
        "ItemIsMovable",
        "ItemIsSelectable",
        "ItemIsFocusable",
        "ItemSendsGeometryChanges",
        "ItemSendsScenePositionChanges",
    ):
        if not hasattr(_target, _name) and hasattr(QGraphicsItem.GraphicsItemFlag, _name):
            setattr(_target, _name, getattr(QGraphicsItem.GraphicsItemFlag, _name))
    for _name in (
        "ItemSelectedChange",
        "ItemPositionChange",
        "ItemPositionHasChanged",
        "ItemScenePositionHasChanged",
    ):
        if not hasattr(_target, _name) and hasattr(QGraphicsItem.GraphicsItemChange, _name):
            setattr(_target, _name, getattr(QGraphicsItem.GraphicsItemChange, _name))
if not hasattr(QTreeWidgetItem, "UserType"):
    QTreeWidgetItem.UserType = QTreeWidgetItem.ItemType.UserType  # type: ignore[attr-defined]
for _name in ("BoundingRectViewportUpdate", "FullViewportUpdate", "MinimalViewportUpdate"):
    if not hasattr(QGraphicsView, _name) and hasattr(QGraphicsView.ViewportUpdateMode, _name):
        setattr(QGraphicsView, _name, getattr(QGraphicsView.ViewportUpdateMode, _name))
for _name in ("CacheNone", "CacheBackground"):
    if not hasattr(QGraphicsView, _name) and hasattr(QGraphicsView.CacheModeFlag, _name):
        setattr(QGraphicsView, _name, getattr(QGraphicsView.CacheModeFlag, _name))
if not hasattr(QRubberBand, "Rectangle"):
    QRubberBand.Rectangle = QRubberBand.Shape.Rectangle  # type: ignore[attr-defined]
for _name in ("LeftSide", "RightSide"):
    if not hasattr(QTabBar, _name) and hasattr(QTabBar.ButtonPosition, _name):
        setattr(QTabBar, _name, getattr(QTabBar.ButtonPosition, _name))
for _name in ("Antialiasing", "TextAntialiasing", "SmoothPixmapTransform"):
    if not hasattr(QPainter, _name) and hasattr(QPainter.RenderHint, _name):
        setattr(QPainter, _name, getattr(QPainter.RenderHint, _name))
for _name in ("SolidLine", "DashLine", "DotLine", "NoPen"):
    if not hasattr(Qt, _name) and hasattr(Qt.PenStyle, _name):
        setattr(Qt, _name, getattr(Qt.PenStyle, _name))
for _name in ("MiterJoin", "RoundJoin", "BevelJoin"):
    if not hasattr(Qt, _name) and hasattr(Qt.PenJoinStyle, _name):
        setattr(Qt, _name, getattr(Qt.PenJoinStyle, _name))
for _name in ("RoundCap", "SquareCap", "FlatCap"):
    if not hasattr(Qt, _name) and hasattr(Qt.PenCapStyle, _name):
        setattr(Qt, _name, getattr(Qt.PenCapStyle, _name))
for _name in ("NoBrush", "SolidPattern"):
    if not hasattr(Qt, _name) and hasattr(Qt.BrushStyle, _name):
        setattr(Qt, _name, getattr(Qt.BrushStyle, _name))
for _name in ("ScrollBarAlwaysOff", "ScrollBarAsNeeded", "ScrollBarAlwaysOn"):
    if not hasattr(Qt, _name) and hasattr(Qt.ScrollBarPolicy, _name):
        setattr(Qt, _name, getattr(Qt.ScrollBarPolicy, _name))
for _name in ("LeftButton", "MiddleButton", "RightButton", "NoButton"):
    if not hasattr(Qt, _name) and hasattr(Qt.MouseButton, _name):
        setattr(Qt, _name, getattr(Qt.MouseButton, _name))
for _name in ("NoModifier", "AltModifier", "ControlModifier", "ShiftModifier"):
    if not hasattr(Qt, _name) and hasattr(Qt.KeyboardModifier, _name):
        setattr(Qt, _name, getattr(Qt.KeyboardModifier, _name))
for _name in ("KeepAspectRatio", "IgnoreAspectRatio"):
    if not hasattr(Qt, _name) and hasattr(Qt.AspectRatioMode, _name):
        setattr(Qt, _name, getattr(Qt.AspectRatioMode, _name))
for _name in ("SmoothTransformation", "FastTransformation"):
    if not hasattr(Qt, _name) and hasattr(Qt.TransformationMode, _name):
        setattr(Qt, _name, getattr(Qt.TransformationMode, _name))
for _name in ("WA_MacShowFocusRect", "WA_TranslucentBackground"):
    if not hasattr(Qt, _name) and hasattr(Qt.WidgetAttribute, _name):
        setattr(Qt, _name, getattr(Qt.WidgetAttribute, _name))
for _name in ("IBeamCursor", "ArrowCursor", "PointingHandCursor", "OpenHandCursor", "ClosedHandCursor"):
    if not hasattr(Qt, _name) and hasattr(Qt.CursorShape, _name):
        setattr(Qt, _name, getattr(Qt.CursorShape, _name))
for _name in ("NoTextInteraction", "TextEditorInteraction", "TextSelectableByMouse"):
    if not hasattr(Qt, _name) and hasattr(Qt.TextInteractionFlag, _name):
        setattr(Qt, _name, getattr(Qt.TextInteractionFlag, _name))

# NodeGraphQt was written for PyQt5 where QDropEvent.pos() existed as a method.
# In PyQt6 that was replaced by position().toPoint().
if not hasattr(QDropEvent, "pos"):
    QDropEvent.pos = lambda self: self.position().toPoint()  # type: ignore[attr-defined]

# PyQt5 exposed drop actions directly on Qt; PyQt6 moved them to Qt.DropAction.
for _name in ("CopyAction", "MoveAction", "LinkAction", "IgnoreAction"):
    if not hasattr(Qt, _name) and hasattr(Qt.DropAction, _name):
        setattr(Qt, _name, getattr(Qt.DropAction, _name))

try:  # NodeGraphQt is optional while this integration is evaluated.
    from NodeGraphQt import BaseNode, NodeGraph
except Exception:  # pragma: no cover - depends on optional runtime package
    BaseNode = None  # type: ignore[assignment]
    NodeGraph = None  # type: ignore[assignment]


if BaseNode is not None:

    class ForgeProjectNode(BaseNode):
        __identifier__ = "forge.graph"
        NODE_NAME = "Project"

        def __init__(self) -> None:
            super().__init__()
            self.add_output("cameras")

    class ForgeCameraNode(BaseNode):
        __identifier__ = "forge.graph"
        NODE_NAME = "Camera"

        def __init__(self) -> None:
            super().__init__()
            project = self.add_input("project")
            project.add_accept_port_type("cameras", "out", "forge.graph.ForgeProjectNode")
            self.add_output("labels")

    class ForgeLabelNode(BaseNode):
        __identifier__ = "forge.graph"
        NODE_NAME = "Label"

        def __init__(self) -> None:
            super().__init__()
            camera = self.add_input("camera")
            camera.add_accept_port_type("labels", "out", "forge.graph.ForgeCameraNode")
            self.add_output("gpio")

    class ForgeGpioPortNode(BaseNode):
        __identifier__ = "forge.graph"
        NODE_NAME = "GPIO Port"

        def __init__(self) -> None:
            super().__init__()
            labels = self.add_input("labels", multi_input=True)
            labels.add_accept_port_type("gpio", "out", "forge.graph.ForgeLabelNode")

else:
    ForgeProjectNode = None  # type: ignore[assignment]
    ForgeCameraNode = None  # type: ignore[assignment]
    ForgeLabelNode = None  # type: ignore[assignment]
    ForgeGpioPortNode = None  # type: ignore[assignment]


class ForgeGraphWidget(QWidget):
    """Visualizes label-to-camera and label-to-GPIO routing as a node graph."""

    assignments_changed = pyqtSignal(dict, dict)
    label_selected = pyqtSignal(str)
    camera_selected = pyqtSignal(object)
    label_activated = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project_name = "Proyecto"
        self._labels: list[dict[str, str]] = []
        self._cameras: list[dict[str, object]] = []
        self._camera_for_label: dict[str, list[str]] = {}
        self._gpio_for_label: dict[str, str] = {}
        self._candidate_gpio_port = "GPIO2"
        self._graph = None
        self._node_meta: dict[str, dict[str, object]] = {}
        self._syncing = False
        self._saved_positions: dict[str, list[float]] = {}
        self._saved_viewport: tuple[float, float, float] | None = None
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(80)
        self._refresh_timer.timeout.connect(self._do_refresh)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(2)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(4)
        self.summary = QLabel("Graph overview")
        self.summary.setStyleSheet("font-size:10px;")
        self.summary.setFixedHeight(18)
        toolbar.addWidget(self.summary, 1)

        self.state_label = QLabel("Guardado")
        self.state_label.setStyleSheet("font-size:10px; font-weight:600;")
        self.state_label.setFixedHeight(18)
        toolbar.addWidget(self.state_label)

        self.fit_button = QPushButton("Fit")
        self.fit_button.setToolTip("Ajustar graph al viewport")
        self.fit_button.setFixedHeight(18)
        self.fit_button.setFixedWidth(34)
        self.fit_button.setStyleSheet("font-size:10px; padding:0 4px;")
        self.fit_button.clicked.connect(self.fit)
        toolbar.addWidget(self.fit_button)
        layout.addLayout(toolbar)

        if NodeGraph is None or BaseNode is None:
            message = QLabel(
                "NodeGraphQt no está instalado.\n\n"
                "Instala la dependencia en esta rama para activar el mapa visual:\n"
                "uv add NodeGraphQt"
            )
            message.setAlignment(Qt.AlignmentFlag.AlignCenter)
            message.setWordWrap(True)
            message.setStyleSheet(
                "padding:24px; border:1px dashed; border-radius:8px;"
            )
            layout.addWidget(message, 1)
            self.fit_button.setEnabled(False)
            return

        self._graph = NodeGraph()
        self._graph.register_nodes([ForgeProjectNode, ForgeCameraNode, ForgeLabelNode, ForgeGpioPortNode])
        self._graph.port_connected.connect(lambda *_args: self._emit_assignments_from_graph())
        self._graph.port_disconnected.connect(lambda *_args: self._emit_assignments_from_graph())
        self._graph.node_selected.connect(self._emit_node_selected)
        self._graph.node_double_clicked.connect(self._emit_node_activated)
        layout.addWidget(self._graph.widget, 1)

        # Guard against RuntimeError when a PortItem is deleted while a pipe
        # drag is still in progress (e.g. graph refreshed mid-drag).
        _orig_smme = self._graph.viewer().sceneMouseMoveEvent
        def _safe_smme(event: object) -> None:
            try:
                _orig_smme(event)
            except RuntimeError:
                self._reset_live_pipe()
        self._graph.viewer().sceneMouseMoveEvent = _safe_smme

    # -- public setters -------------------------------------------------------

    def set_project(self, name: str) -> None:
        self._project_name = name.strip() or "Proyecto"
        self._schedule_refresh()

    def set_labels(self, labels: list[dict[str, object]]) -> None:
        normalized: list[dict[str, str]] = []
        for item in labels:
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            normalized.append(
                {
                    "name": name,
                    "type": str(item.get("type", "")).strip(),
                    "color": str(item.get("color", "")).strip(),
                    "preview_base64": str(item.get("preview_base64", "")).strip(),
                }
            )
        self._labels = normalized
        self._schedule_refresh()

    def set_cameras(self, cameras: list[object]) -> None:
        normalized: list[dict[str, object]] = []
        seen: set[int | str] = set()
        for item in cameras:
            if isinstance(item, dict):
                name = str(item.get("name", "")).strip()
                camera_id = item.get("id")
            else:
                name = str(item).strip()
                camera_id = name
            if not name:
                continue
            key = camera_id if isinstance(camera_id, int) else name.lower()
            if key in seen:
                continue
            seen.add(key)
            normalized.append({"id": camera_id, "name": name})
        self._cameras = normalized
        self._schedule_refresh()

    def set_label_assignments(self, camera_for_label: dict[str, list[str]]) -> None:
        self._camera_for_label = {str(label): list(cameras) for label, cameras in camera_for_label.items()}
        self._schedule_refresh()

    def set_gpio_assignments(self, gpio_for_label: dict[str, str]) -> None:
        self._gpio_for_label = {str(label): str(port) for label, port in gpio_for_label.items() if str(port).strip()}
        self._schedule_refresh()

    def set_candidate_gpio_port(self, port: str) -> None:
        self._candidate_gpio_port = port.strip() or "GPIO2"
        self._schedule_refresh()

    # -- refresh --------------------------------------------------------------

    def _schedule_refresh(self) -> None:
        QMetaObject.invokeMethod(self._refresh_timer, "start", Qt.ConnectionType.QueuedConnection)

    def refresh(self) -> None:
        self._schedule_refresh()

    def _do_refresh(self) -> None:
        label_count = len(self._labels)
        camera_count = len(self._cameras)
        gpio_count = len(set(self._gpio_for_label.values()))
        self.summary.setText(f"{label_count} labels · {camera_count} cámaras · {gpio_count} GPIO")
        if self._graph is None:
            return

        # Persist positions and viewport before clearing.
        if self._node_meta:
            self._saved_positions = self._capture_node_positions()
            self._saved_viewport = self._capture_viewport()

        self._reset_live_pipe()
        self._syncing = True
        self._graph.clear_session()
        self._node_meta = {}

        ports = sorted({*self._gpio_for_label.values(), self._candidate_gpio_port})

        project_node = self._graph.create_node(
            "forge.graph.ForgeProjectNode",
            name=self._project_name,
            color=(57, 72, 96),
            pos=self._pos("project", (0, 0)),
        )
        self._set_node_meta(project_node, kind="project")

        camera_nodes: dict[str, object] = {}
        for index, camera in enumerate(self._cameras):
            camera_name = str(camera.get("name", "")).strip()
            if not camera_name:
                continue
            node = self._graph.create_node(
                "forge.graph.ForgeCameraNode",
                name=camera_name,
                color=(30, 82, 116),
                pos=self._pos(f"camera:{camera_name}", (260, index * 120)),
            )
            self._set_node_meta(node, kind="camera", id=camera.get("id"), name=camera_name)
            camera_nodes[camera_name.lower()] = node
            project_node.output(0).connect_to(node.input(0))

        label_nodes: dict[str, object] = {}
        for index, label in enumerate(self._labels):
            name = label["name"]
            color = label.get("color") or "#2f425d"
            node = self._graph.create_node(
                "forge.graph.ForgeLabelNode",
                name=name,
                color=self._rgb(color, fallback=(47, 66, 93)),
                pos=self._pos(f"label:{name}", (560, index * 125)),
            )
            self._set_node_meta(node, kind="label", name=name)
            self._set_label_node_preview(node, label.get("preview_base64", ""))
            label_nodes[name] = node

        gpio_nodes: dict[str, object] = {}
        for index, port in enumerate(ports):
            node = self._graph.create_node(
                "forge.graph.ForgeGpioPortNode",
                name=port,
                color=(118, 84, 24),
                pos=self._pos(f"gpio:{port}", (860, index * 120)),
            )
            self._set_node_meta(node, kind="gpio", port=port)
            gpio_nodes[port] = node

        for label_name, label_node in label_nodes.items():
            for camera in self._camera_for_label.get(label_name, []):
                camera_node = camera_nodes.get(camera.lower())
                if camera_node is not None:
                    camera_node.output(0).connect_to(label_node.input(0))
            port = self._gpio_for_label.get(label_name)
            gpio_node = gpio_nodes.get(port or "")
            if gpio_node is not None:
                label_node.output(0).connect_to(gpio_node.input(0))

        if self._saved_viewport is not None:
            self._restore_viewport(self._saved_viewport)
        else:
            self.fit()

        self._syncing = False

    # -- position / viewport persistence -------------------------------------

    def _pos(self, key: str, default: tuple[int, int]) -> list[float]:
        saved = self._saved_positions.get(key)
        return list(saved) if saved is not None else list(default)

    def _capture_node_positions(self) -> dict[str, list[float]]:
        positions: dict[str, list[float]] = {}
        for node in self._graph.all_nodes():
            meta = self._node_meta.get(node.id, {})
            kind = meta.get("kind")
            if kind == "project":
                key = "project"
            elif kind == "camera":
                key = f"camera:{meta.get('name', '')}"
            elif kind == "label":
                key = f"label:{meta.get('name', '')}"
            elif kind == "gpio":
                key = f"gpio:{meta.get('port', '')}"
            else:
                continue
            try:
                raw = node.pos()
                positions[key] = [float(raw[0]), float(raw[1])]
            except Exception:
                pass
        return positions

    def _capture_viewport(self) -> tuple[float, float, float] | None:
        try:
            zoom = self._graph.get_zoom()
            viewer = self._graph.viewer()
            center = viewer.mapToScene(viewer.viewport().rect().center())
            return (float(zoom), float(center.x()), float(center.y()))
        except Exception:
            return None

    def _restore_viewport(self, state: tuple[float, float, float]) -> None:
        zoom, cx, cy = state
        try:
            self._graph.set_zoom(zoom)
            self._graph.viewer().centerOn(cx, cy)
        except Exception:
            self.fit()

    def _reset_live_pipe(self) -> None:
        """Cancel any in-progress port drag so clear_session() can't leave dangling C++ refs."""
        if self._graph is None:
            return
        try:
            viewer = self._graph.viewer()
            lp = getattr(viewer, "_LIVE_PIPE", None)
            if lp is not None:
                lp.reset_path()
                lp.setVisible(False)
            if hasattr(viewer, "_start_port"):
                viewer._start_port = None
        except Exception:
            pass

    # -- internal helpers -----------------------------------------------------

    def _set_node_meta(self, node: object, **meta: object) -> None:
        node_id = getattr(node, "id", None)
        if isinstance(node_id, str):
            self._node_meta[node_id] = dict(meta)

    def _node_meta_for_port(self, port: object) -> dict[str, object]:
        node_fn = getattr(port, "node", None)
        if node_fn is None:
            return {}
        node = node_fn()
        node_id = getattr(node, "id", None)
        return self._node_meta.get(node_id, {}) if isinstance(node_id, str) else {}

    def _emit_assignments_from_graph(self) -> None:
        if self._syncing or self._graph is None:
            return
        self.mark_saving()

        camera_assignments: dict[str, list[str]] = {}
        gpio_assignments: dict[str, str] = {}

        for node in self._graph.all_nodes():
            meta = self._node_meta.get(node.id, {})
            kind = meta.get("kind")
            if kind == "camera":
                camera_id = meta.get("id")
                if camera_id is None:
                    continue
                labels: list[str] = []
                for connected in node.output(0).connected_ports():
                    label_meta = self._node_meta_for_port(connected)
                    if label_meta.get("kind") == "label":
                        label = str(label_meta.get("name", "")).strip()
                        if label:
                            labels.append(label)
                camera_assignments[str(camera_id)] = list(dict.fromkeys(labels))
            elif kind == "gpio":
                port = str(meta.get("port", "")).strip()
                if not port:
                    continue
                for connected in node.input(0).connected_ports():
                    label_meta = self._node_meta_for_port(connected)
                    if label_meta.get("kind") == "label":
                        label = str(label_meta.get("name", "")).strip()
                        if label:
                            gpio_assignments[label] = port

        self.assignments_changed.emit(camera_assignments, gpio_assignments)

    def fit(self) -> None:
        if self._graph is None:
            return
        self._graph.clear_selection()
        self._graph.fit_to_selection()

    def focus_label(self, name: str) -> None:
        """Select and center the label node matching *name*."""
        if not hasattr(self, "_graph") or self._graph is None:
            return
        target = name.strip()
        for node in self._graph.all_nodes():
            meta = self._node_meta.get(getattr(node, "id", None), {})
            if meta.get("kind") == "label" and str(meta.get("name", "")).strip() == target:
                try:
                    self._graph.clear_selection()
                    node.set_selected(True)
                    self._graph.viewer().centerOn(node.x_pos(), node.y_pos())
                except Exception:
                    pass
                return

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        t = tokens(theme)
        self.summary.setStyleSheet(f"color:{t['muted']}; font-size:10px;")
        if hasattr(self, "_graph"):
            if theme == "light":
                self._graph.set_background_color(235, 238, 244)
                self._graph.scene().grid_color = (200, 210, 220)
            else:
                self._graph.set_background_color(17, 20, 27)
                self._graph.scene().grid_color = (45, 55, 70)
            self._graph.scene().update()
        # Re-apply the current state label color
        text = self.state_label.text() if hasattr(self, "state_label") else ""
        if "Error" in text or "error" in text:
            self._apply_state_color(t["danger"])
        elif "Guardando" in text:
            self._apply_state_color(t["warning"])
        else:
            self._apply_state_color(t["accent"])

    def _apply_state_color(self, color: str) -> None:
        self.state_label.setStyleSheet(f"color:{color}; font-size:10px; font-weight:600;")

    def mark_saved(self) -> None:
        self.state_label.setText("Guardado")
        t = tokens(getattr(self, "_theme", "dark"))
        self._apply_state_color(t["accent"])

    def mark_saving(self) -> None:
        self.state_label.setText("Guardando...")
        t = tokens(getattr(self, "_theme", "dark"))
        self._apply_state_color(t["warning"])

    def mark_error(self, detail: str = "Error") -> None:
        self.state_label.setText(detail or "Error")
        t = tokens(getattr(self, "_theme", "dark"))
        self._apply_state_color(t["danger"])

    def _emit_node_selected(self, node: object) -> None:
        meta = self._meta_for_node(node)
        if meta.get("kind") == "label":
            self.label_selected.emit(str(meta.get("name", "")))
        elif meta.get("kind") == "camera":
            self.camera_selected.emit(meta.get("id"))

    def _emit_node_activated(self, node: object) -> None:
        meta = self._meta_for_node(node)
        if meta.get("kind") == "label":
            self.label_activated.emit(str(meta.get("name", "")))

    def _meta_for_node(self, node: object) -> dict[str, object]:
        node_id = getattr(node, "id", None)
        return self._node_meta.get(node_id, {}) if isinstance(node_id, str) else {}

    @staticmethod
    def _set_label_node_preview(node: object, preview_base64: str) -> None:
        if not preview_base64:
            return
        pixmap = QPixmap()
        try:
            ok = pixmap.loadFromData(base64.b64decode(preview_base64))
        except Exception:
            ok = False
        if not ok:
            return

        view = getattr(node, "view", None)
        icon_item = getattr(view, "icon_item", None)
        if view is None or icon_item is None:
            return

        preview = pixmap.scaled(
            118,
            70,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        icon_item.setPixmap(preview)

        try:
            view.width = max(float(getattr(view, "width", 0.0)), 170.0)
            view.height = max(float(getattr(view, "height", 0.0)), 118.0)
            rect = view.boundingRect()
            icon_item.setPos(rect.center().x() - preview.width() / 2, rect.top() + 30)
        except Exception:
            return

    @staticmethod
    def _rgb(hex_color: str, *, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
        text = hex_color.strip().lstrip("#")
        if len(text) != 6:
            return fallback
        try:
            return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
        except ValueError:
            return fallback
