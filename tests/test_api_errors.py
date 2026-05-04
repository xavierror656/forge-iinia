import pytest

from core.api_errors import APIError, ForgeAPIError, NetworkError


def test_classification_predicates():
    err = ForgeAPIError(401, "denied", endpoint="/api/projects", method="get")
    assert err.is_auth_error
    assert err.is_client_error
    assert not err.is_server_error
    assert not err.is_retryable


def test_5xx_is_retryable():
    err = ForgeAPIError(503, "down", endpoint="/api/x")
    assert err.is_server_error
    assert err.is_retryable


@pytest.mark.parametrize("status", [408, 425, 429])
def test_special_4xx_status_codes_are_retryable(status):
    err = ForgeAPIError(status, "")
    assert err.is_retryable


def test_message_includes_method_and_endpoint():
    err = ForgeAPIError(500, "boom", endpoint="/api/x", method="post")
    assert "POST /api/x" in str(err)
    assert "Forge API error 500" in str(err)


def test_subclasses_are_apierror():
    assert issubclass(ForgeAPIError, APIError)


def test_network_error_carries_endpoint():
    err = NetworkError("DNS fail", endpoint="/api/x", method="GET")
    assert "/api/x" in str(err)
    assert "DNS fail" in str(err)
