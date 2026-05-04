import pytest

from core.api_errors import ForgeAPIError, NetworkError
from core.http_retry import call_with_retry


def test_succeeds_on_first_try():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        return "ok"

    result = call_with_retry(fn, attempts=3, sleep=lambda _s: None)
    assert result == "ok"
    assert calls["n"] == 1


def test_retries_on_5xx_then_succeeds():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ForgeAPIError(503, "down", endpoint="/x")
        return "ok"

    result = call_with_retry(fn, attempts=3, sleep=lambda _s: None)
    assert result == "ok"
    assert calls["n"] == 3


def test_does_not_retry_on_401():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise ForgeAPIError(401, "denied", endpoint="/x")

    with pytest.raises(ForgeAPIError):
        call_with_retry(fn, attempts=3, sleep=lambda _s: None)
    assert calls["n"] == 1


def test_retries_network_error():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] < 2:
            raise NetworkError("dns fail", endpoint="/x")
        return "ok"

    result = call_with_retry(fn, attempts=3, sleep=lambda _s: None)
    assert result == "ok"
    assert calls["n"] == 2


def test_gives_up_after_attempts():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise ForgeAPIError(503, "down", endpoint="/x")

    with pytest.raises(ForgeAPIError):
        call_with_retry(fn, attempts=2, sleep=lambda _s: None)
    assert calls["n"] == 2


def test_attempts_zero_raises_value_error():
    with pytest.raises(ValueError):
        call_with_retry(lambda: None, attempts=0)
