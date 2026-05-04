"""Typed exceptions for Forge REST clients.

Replaces generic ``RuntimeError`` so callers can branch on HTTP status
(re-auth on 401, retry on 5xx, surface body on 4xx) without parsing strings.
"""

from __future__ import annotations


class APIError(RuntimeError):
    """Base error for any REST backend used by the hub."""

    service: str = "api"

    def __init__(
        self,
        status: int,
        body: str,
        *,
        endpoint: str = "",
        method: str = "",
    ) -> None:
        self.status = status
        self.body = body
        self.endpoint = endpoint
        self.method = method.upper()
        location = f"{self.method} {endpoint}".strip() or "<unknown>"
        super().__init__(f"{self.service} API error {status} on {location}: {body}")

    @property
    def is_auth_error(self) -> bool:
        return self.status in (401, 403)

    @property
    def is_client_error(self) -> bool:
        return 400 <= self.status < 500

    @property
    def is_server_error(self) -> bool:
        return 500 <= self.status < 600

    @property
    def is_retryable(self) -> bool:
        return self.is_server_error or self.status in (408, 425, 429)


class ForgeAPIError(APIError):
    service = "Forge"


class NetworkError(RuntimeError):
    """Raised when the request never reaches the server (DNS, timeout, refused)."""

    def __init__(self, message: str, *, endpoint: str = "", method: str = "") -> None:
        self.endpoint = endpoint
        self.method = method.upper()
        location = f"{self.method} {endpoint}".strip() or "<unknown>"
        super().__init__(f"network error on {location}: {message}")
