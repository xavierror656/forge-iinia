"""Forge REST client for cameras, projects and component assignments."""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ForgeProject:
    id: int
    name: str


@dataclass(slots=True)
class ForgeCamera:
    id: int
    name: str
    components: list[str]


@dataclass(slots=True)
class ForgeLine:
    id: int
    name: str


class ForgeManager:
    """Small REST client for Forge swagger endpoints.

    Auth strategy is intentionally flexible because the exact backend auth
    scheme can vary between deployments.
    """

    def __init__(self, base_url: str) -> None:
        self.base_url = self._normalize_base_url(base_url)
        self._token: str | None = None
        self._username: str | None = None
        self._password: str | None = None

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        normalized = base_url.strip().rstrip("/")
        for suffix in ("/api/swagger", "/swagger"):
            if normalized.endswith(suffix):
                normalized = normalized[: -len(suffix)]
        return normalized.rstrip("/")

    def set_token(self, token: str) -> None:
        self._token = token.strip()

    def set_basic_auth(self, username: str, password: str) -> None:
        self._username = username.strip()
        self._password = password

    def _auth_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        elif self._username and self._password:
            raw = f"{self._username}:{self._password}".encode("utf-8")
            headers["Authorization"] = f"Basic {base64.b64encode(raw).decode('ascii')}"
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        binary: bool = False,
    ) -> Any:
        if path.startswith("http://") or path.startswith("https://"):
            url = path
        else:
            url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"

        headers = {"Accept": "application/vnd.cvat+json", **self._auth_headers()}
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data, method=method.upper(), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                body = response.read()
                if binary:
                    return body
                if not body:
                    return {}
                try:
                    return json.loads(body.decode("utf-8"))
                except json.JSONDecodeError:
                    return {"raw": body.decode("utf-8", errors="ignore")}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Forge API error {exc.code}: {body}") from exc

    @staticmethod
    def _items(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, dict):
            for key in ("results", "items", "data"):
                if isinstance(payload.get(key), list):
                    return [item for item in payload[key] if isinstance(item, dict)]
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        return []

    def _collect_items(self, path: str, *, query: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        next_path: str | None = path
        next_query = query
        while next_path:
            payload = self._request("GET", next_path, query=next_query)
            items.extend(self._items(payload))
            next_query = None
            if isinstance(payload, dict):
                next_value = payload.get("next")
                next_path = str(next_value) if next_value else None
            else:
                next_path = None
        return items

    def list_projects(self) -> list[ForgeProject]:
        items = self._collect_items("/api/projects")
        return [ForgeProject(id=int(item.get("id", 0)), name=item.get("name", "")) for item in items]

    def list_cameras(self) -> list[ForgeCamera]:
        cameras: list[ForgeCamera] = []
        for item in self._collect_items("/api/cameras"):
            components = item.get("components") or item.get("assigned_components") or item.get("labels") or []
            if isinstance(components, str):
                components = [c.strip() for c in components.split(",") if c.strip()]
            cameras.append(
                ForgeCamera(
                    id=int(item.get("id", 0)),
                    name=item.get("name", ""),
                    components=[str(c) for c in components],
                )
            )
        return cameras

    def list_lines(self) -> list[ForgeLine]:
        items = self._collect_items("/api/lines")
        return [ForgeLine(id=int(item.get("id", 0)), name=item.get("name", "")) for item in items]

    def list_labels(self, project_id: int) -> list[dict[str, Any]]:
        return self._collect_items("/api/labels", query={"project_id": project_id})

    def get_project(self, project_id: int) -> dict[str, Any]:
        payload = self._request("GET", f"/api/projects/{project_id}")
        return payload if isinstance(payload, dict) else {}

    def project_labels_preview(self, project_id: int) -> list[dict[str, Any]]:
        payload = self._request("GET", f"/api/projects/{project_id}/labels/preview")
        if isinstance(payload, dict):
            for key in ("results", "labels", "data"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        return []

    def project_label_stats(self, project_id: int) -> dict[str, Any]:
        payload = self._request("GET", f"/api/projects/{project_id}/label-stats")
        return payload if isinstance(payload, dict) else {"raw": payload}

    def project_preview(self, project_id: int) -> bytes:
        return self._request("GET", f"/api/projects/{project_id}/preview", binary=True)

    def create_camera(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._request("POST", "/api/cameras", payload=payload)
        return response if isinstance(response, dict) else {"raw": response}

    def update_camera(self, camera_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._request("PATCH", f"/api/cameras/{camera_id}", payload=payload)
        return response if isinstance(response, dict) else {"raw": response}

    def create_line(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._request("POST", "/api/lines", payload=payload)
        return response if isinstance(response, dict) else {"raw": response}

    def update_line(self, line_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._request("PATCH", f"/api/lines/{line_id}", payload=payload)
        return response if isinstance(response, dict) else {"raw": response}

    def send_conf(self, line_id: int, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self._request("POST", f"/api/lines/{line_id}/send_conf", payload=payload or {})
        return response if isinstance(response, dict) else {"raw": response}
