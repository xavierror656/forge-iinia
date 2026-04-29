"""Minimal CVAT REST client for project sync and export downloads."""

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
class CvatProject:
    id: int
    name: str
    status: str = ""


@dataclass(slots=True)
class CvatJob:
    id: int
    task_id: int
    name: str = ""


class CvatManager:
    """Small CVAT API wrapper.

    Uses token auth when available, otherwise falls back to username/password login.
    """

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._token: str | None = None
        self._username: str | None = None
        self._password: str | None = None

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        raw_data: bytes | None = None,
        content_type: str | None = None,
        query: dict[str, Any] | None = None,
        binary: bool = False,
        headers: dict[str, str] | None = None,
    ) -> Any:
        if path.startswith("http://") or path.startswith("https://"):
            url = path
        else:
            url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"

        data = None
        request_headers = {"Accept": "application/vnd.cvat+json"}
        if headers:
            request_headers.update(headers)
        if self._token:
            request_headers["Authorization"] = f"Token {self._token}"
        elif self._username and self._password:
            raw = f"{self._username}:{self._password}".encode("utf-8")
            request_headers["Authorization"] = f"Basic {base64.b64encode(raw).decode('ascii')}"

        if raw_data is not None:
            data = raw_data
            if content_type:
                request_headers["Content-Type"] = content_type
        elif payload is not None:
            data = json.dumps(payload).encode("utf-8")
            request_headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data, method=method.upper(), headers=request_headers)
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
            raise RuntimeError(f"CVAT API error {exc.code}: {body}") from exc

    def login(self, username: str, password: str) -> None:
        response = self._request("POST", "/api/auth/login", payload={"username": username, "password": password})
        token = response.get("key") if isinstance(response, dict) else None
        if token:
            self._token = token

    def set_token(self, token: str) -> None:
        self._token = token.strip()

    def set_basic_auth(self, username: str, password: str) -> None:
        self._username = username.strip()
        self._password = password

    @staticmethod
    def _items(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, dict):
            results = payload.get("results")
            if isinstance(results, list):
                return [item for item in results if isinstance(item, dict)]
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

    def list_projects(self) -> list[CvatProject]:
        projects: list[CvatProject] = []
        for item in self._collect_items("/api/projects"):
            projects.append(CvatProject(id=int(item["id"]), name=item.get("name", ""), status=item.get("status", "")))
        return projects

    def list_jobs(self, task_id: int | None = None) -> list[CvatJob]:
        query = {"task_id": task_id} if task_id else None
        jobs: list[CvatJob] = []
        for item in self._collect_items("/api/jobs", query=query):
            jobs.append(CvatJob(id=int(item["id"]), task_id=int(item.get("task_id", 0)), name=item.get("name", "")))
        return jobs

    def export_project_dataset(self, project_id: int, export_format: str = "CVAT for images 1.1") -> bytes:
        query = {"format": export_format}
        return self._request("GET", f"/api/projects/{project_id}/dataset/export", query=query, binary=True)

    def export_task_dataset(self, task_id: int, export_format: str = "CVAT for images 1.1") -> bytes:
        query = {"format": export_format}
        return self._request("GET", f"/api/tasks/{task_id}/dataset/export", query=query, binary=True)

    def download_export_to_dir(self, *, project_id: int | None = None, task_id: int | None = None, export_format: str, out_dir: Path) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        if project_id is not None:
            data = self.export_project_dataset(project_id, export_format=export_format)
            name = f"project_{project_id}_{self._slug(export_format)}.zip"
        elif task_id is not None:
            data = self.export_task_dataset(task_id, export_format=export_format)
            name = f"task_{task_id}_{self._slug(export_format)}.zip"
        else:
            raise ValueError("project_id or task_id is required")

        target = out_dir / name
        target.write_bytes(data)
        return target

    def upload_images_to_task(self, task_id: int, image_paths: list[Path]) -> None:
        boundary = base64.urlsafe_b64encode(Path().cwd().as_posix().encode()).decode("ascii")[:24]
        parts: list[bytes] = []
        for path in image_paths:
            parts.extend(
                [
                    f"--{boundary}\r\n".encode(),
                    f'Content-Disposition: form-data; name="client_files"; filename="{path.name}"\r\n'.encode(),
                    b"Content-Type: image/png\r\n\r\n",
                    path.read_bytes(),
                    b"\r\n",
                ]
            )
        parts.append(f"--{boundary}--\r\n".encode())
        data = b"".join(parts)
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        self._request(
            "POST",
            f"/api/tasks/{task_id}/data",
            headers=headers,
            raw_data=data,
            binary=False,
        )

    @staticmethod
    def _slug(text: str) -> str:
        return "".join(ch.lower() if ch.isalnum() else "_" for ch in text).strip("_")
