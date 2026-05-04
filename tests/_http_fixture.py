"""Tiny in-process HTTP server for client tests.

Avoids adding ``responses`` or ``pytest-httpserver`` as dev deps; we only
need a stub server that takes a routing table.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit


@dataclass(slots=True)
class StubResponse:
    status: int = 200
    body: Any = b""
    content_type: str = "application/json"

    def encoded(self) -> bytes:
        if isinstance(self.body, (bytes, bytearray)):
            return bytes(self.body)
        if isinstance(self.body, str):
            return self.body.encode("utf-8")
        return json.dumps(self.body).encode("utf-8")


@dataclass(slots=True)
class RecordedRequest:
    method: str
    path: str
    query: dict[str, list[str]]
    headers: dict[str, str]
    body: bytes


Router = Callable[[RecordedRequest], StubResponse]


class StubServer:
    def __init__(self, router: Router) -> None:
        self._router = router
        self.requests: list[RecordedRequest] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: Any) -> None:
                return None

            def _serve(self, method: str) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length > 0 else b""
                split = urlsplit(self.path)
                request = RecordedRequest(
                    method=method,
                    path=split.path,
                    query=parse_qs(split.query),
                    headers={k.lower(): v for k, v in self.headers.items()},
                    body=body,
                )
                outer.requests.append(request)
                response = outer._router(request)
                payload = response.encoded()
                self.send_response(response.status)
                self.send_header("Content-Type", response.content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self) -> None:
                self._serve("GET")

            def do_POST(self) -> None:
                self._serve("POST")

            def do_PATCH(self) -> None:
                self._serve("PATCH")

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> "StubServer":
        self._thread.start()
        return self

    def __exit__(self, *_exc: Any) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=1.0)


def json_route(table: dict[tuple[str, str], StubResponse], default_status: int = 404) -> Router:
    def route(request: RecordedRequest) -> StubResponse:
        key = (request.method.upper(), request.path)
        if key in table:
            return table[key]
        return StubResponse(status=default_status, body={"error": "not found"})

    return route
