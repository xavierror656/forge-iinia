from core.gpio_dispatch import GPIODispatcher


def test_first_event_fires():
    clock = iter([10.0])
    d = GPIODispatcher(dedupe_seconds=1.0, clock=lambda: next(clock))
    d.set_assignments({"barril": "GPIO12"})

    decision = d.decide("barril", "cam-1", True)
    assert decision.fire is True
    assert decision.reason == "fired"
    assert decision.port == "GPIO12"
    assert decision.camera_id == "cam-1"


def test_second_camera_within_window_is_deduped():
    times = iter([100.0, 100.4, 102.0])
    d = GPIODispatcher(dedupe_seconds=1.0, clock=lambda: next(times))
    d.set_assignments({"barril": "GPIO12"})

    first = d.decide("barril", "cam-1", True)
    second = d.decide("barril", "cam-2", True)
    third = d.decide("barril", "cam-2", True)

    assert first.fire is True and first.reason == "fired"
    assert second.fire is False and second.reason == "deduped"
    assert third.fire is True and third.reason == "fired"


def test_release_event_never_fires():
    d = GPIODispatcher(dedupe_seconds=1.0)
    decision = d.decide("barril", "cam-1", False)
    assert decision.fire is False
    assert decision.reason == "released"


def test_distinct_labels_do_not_share_dedupe_state():
    times = iter([100.0, 100.1])
    d = GPIODispatcher(dedupe_seconds=5.0, clock=lambda: next(times))
    a = d.decide("barril", "cam-1", True)
    b = d.decide("tapa", "cam-1", True)
    assert a.fire is True
    assert b.fire is True


def test_dedupe_seconds_zero_disables_dedupe():
    times = iter([100.0, 100.0001])
    d = GPIODispatcher(dedupe_seconds=0.0, clock=lambda: next(times))
    a = d.decide("barril", "cam-1", True)
    b = d.decide("barril", "cam-2", True)
    assert a.fire is True
    assert b.fire is True


def test_port_is_empty_when_label_unmapped():
    d = GPIODispatcher(dedupe_seconds=0.0)
    decision = d.decide("ghost", "cam-1", True)
    assert decision.fire is True
    assert decision.port == ""
