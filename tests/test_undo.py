from core.undo import AssignmentHistory, Snapshot


def test_undo_redo_round_trip():
    applied: list[Snapshot] = []
    h = AssignmentHistory(on_apply=applied.append)
    h.initialize({"1": ["a"]}, {"3": {"a": "GPIO12"}})
    h.push("add b", {"1": ["a", "b"]}, {"3": {"a": "GPIO12"}})
    h.push("add gpio", {"1": ["a", "b"]}, {"3": {"a": "GPIO12", "b": "GPIO13"}})

    assert h.can_undo()
    assert h.undo() == "add b"
    assert applied[-1].cameras == {"1": ["a", "b"]}

    assert h.can_redo()
    assert h.redo() == "add gpio"
    assert applied[-1].gpios == {"3": {"a": "GPIO12", "b": "GPIO13"}}


def test_push_clears_redo_stack():
    h = AssignmentHistory(on_apply=lambda _s: None)
    h.initialize({}, {})
    h.push("first", {"1": ["a"]}, {})
    h.undo()
    assert h.can_redo()
    h.push("diverge", {"2": ["b"]}, {})
    assert not h.can_redo()


def test_undo_is_no_op_when_empty():
    applied: list[Snapshot] = []
    h = AssignmentHistory(on_apply=applied.append)
    h.initialize({}, {})
    assert h.undo() is None
    assert applied == []


def test_snapshots_are_deep_copies():
    cams = {"1": ["a"]}
    h = AssignmentHistory(on_apply=lambda _s: None)
    h.initialize(cams, {})
    cams["1"].append("b")
    h.push("step", {"1": ["c"]}, {})
    h.undo()
    h._current.cameras["1"].append("mutation")  # type: ignore[union-attr]
    assert cams == {"1": ["a", "b"]}
