import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication

from ui.forge_graph import ForgeGraphWidget


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _nodes_by_meta(graph: ForgeGraphWidget) -> dict[tuple[str, str], object]:
    return {
        (str(meta.get("kind", "")), str(meta.get("port") or meta.get("name") or meta.get("id") or "")): node
        for node in graph._graph.all_nodes()
        for meta in [graph._node_meta.get(node.id, {})]
    }


def test_graph_emits_camera_and_gpio_assignments(qapp):
    graph = ForgeGraphWidget()
    seen: list[tuple[dict, dict]] = []
    graph.assignments_changed.connect(lambda cameras, gpio: seen.append((cameras, gpio)))

    graph.set_cameras([{"id": 1, "name": "Cam 1"}])
    graph.set_labels([{"name": "A"}])
    graph.set_gpio_assignments({})
    nodes = _nodes_by_meta(graph)

    nodes[("camera", "Cam 1")].output(0).connect_to(nodes[("label", "A")].input(0))
    nodes[("label", "A")].output(0).connect_to(nodes[("gpio", "GPIO2")].input(0))

    assert seen[-1] == ({"1": ["A"]}, {"A": "GPIO2"})


def test_graph_keeps_multiple_gpio_ports(qapp):
    graph = ForgeGraphWidget()
    seen: list[tuple[dict, dict]] = []
    graph.assignments_changed.connect(lambda cameras, gpio: seen.append((cameras, gpio)))

    graph.set_labels([{"name": "A"}, {"name": "B"}])
    graph.set_gpio_assignments({"A": "GPIO2", "B": "GPIO3"})
    graph._emit_assignments_from_graph()

    assert seen[-1][1] == {"A": "GPIO2", "B": "GPIO3"}


def test_graph_node_selection_signals(qapp):
    graph = ForgeGraphWidget()
    labels: list[str] = []
    graph.label_selected.connect(labels.append)
    graph.set_labels([{"name": "A"}])

    nodes = _nodes_by_meta(graph)
    graph._emit_node_selected(nodes[("label", "A")])

    assert labels == ["A"]


def test_graph_position_persistence(qapp):
    graph = ForgeGraphWidget()
    graph.set_cameras([{"id": 1, "name": "Cam 1"}])
    graph.set_labels([{"name": "A"}])

    # Simulate user moving a node.
    graph._saved_positions["label:A"] = [999.0, 888.0]

    graph._do_refresh()

    nodes = _nodes_by_meta(graph)
    pos = nodes[("label", "A")].pos()
    assert abs(pos[0] - 999.0) < 1 and abs(pos[1] - 888.0) < 1
