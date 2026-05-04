from app.state import DetectionState


def test_fires_after_threshold_consecutive_frames():
    state = DetectionState(label="x", threshold=3)
    assert state.register(True) is False
    assert state.register(True) is False
    assert state.register(True) is True
    assert state.fires == 1
    assert state.misses == 0
    assert state.latched is True


def test_miss_counted_when_streak_breaks_before_threshold():
    state = DetectionState(label="x", threshold=3)
    state.register(True)
    state.register(True)
    state.register(False)  # streak broken at 2/3
    assert state.misses == 1
    assert state.fires == 0


def test_no_miss_when_no_active_streak():
    state = DetectionState(label="x", threshold=3)
    state.register(False)
    state.register(False)
    assert state.misses == 0


def test_no_miss_after_latch():
    state = DetectionState(label="x", threshold=2)
    state.register(True)
    state.register(True)  # latched
    state.register(False)
    assert state.misses == 0
    assert state.fires == 1


def test_re_fires_after_release():
    state = DetectionState(label="x", threshold=2)
    state.register(True)
    state.register(True)
    state.register(False)
    state.register(True)
    fired = state.register(True)
    assert fired is True
    assert state.fires == 2
