from core.validator import Warning, summarize, validate


def test_no_warnings_when_everything_assigned():
    out = validate(
        project_labels=["a", "b"],
        camera_assignments={"1": ["a", "b"]},
        gpio_assignments_for_project={"a": "GPIO12", "b": "GPIO13"},
    )
    assert out == []


def test_gpio_unknown_label_is_flagged():
    out = validate(
        project_labels=["a"],
        camera_assignments={"1": ["a"]},
        gpio_assignments_for_project={"ghost": "GPIO12"},
    )
    codes = [w.code for w in out]
    assert "gpio_unknown_label" in codes


def test_gpio_without_camera_is_flagged():
    out = validate(
        project_labels=["a"],
        camera_assignments={"1": []},
        gpio_assignments_for_project={"a": "GPIO12"},
    )
    codes = [w.code for w in out]
    assert "gpio_without_camera" in codes


def test_camera_empty_warning_uses_camera_id_target():
    out = validate(
        project_labels=["a"],
        camera_assignments={"1": ["a"], "2": []},
        gpio_assignments_for_project={"a": "GPIO12"},
        cameras={1: "Cam One", 2: "Cam Two"},
    )
    targets = {w.target for w in out if w.code == "camera_empty"}
    assert targets == {"2"}


def test_label_unused_warning():
    out = validate(
        project_labels=["a", "b"],
        camera_assignments={"1": ["a"]},
        gpio_assignments_for_project={"a": "GPIO12"},
    )
    codes = [w.code for w in out]
    assert "label_unused" in codes


def test_summarize_empty_and_grouped():
    assert summarize([]) == "Sin advertencias"
    summary = summarize([
        Warning(severity="warn", code="x", message="m1"),
        Warning(severity="warn", code="y", message="m2"),
        Warning(severity="info", code="z", message="m3"),
    ])
    assert "warn" in summary and "info" in summary
