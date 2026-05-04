"""Video source discovery and persistence."""

from __future__ import annotations

import json
import platform
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import cv2

from core.hardware_manager import HardwareManager

VIDEO_SOURCE_PATH = Path("configs/inference_source.json")


@dataclass(slots=True)
class VideoSourceChoice:
    kind: str
    label: str
    source: str
    backend: str = ""
    available: bool = True

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class InferenceSourceConfig:
    version: int = 1
    mode: str = "auto"
    rtsp_url: str = ""
    rtsp_username: str = ""
    rtsp_password: str = ""
    default_rtsp_camera: str = ""
    rtsp_cameras: list[dict[str, Any]] = field(default_factory=list)
    camera_source: str = ""
    camera_label: str = ""
    camera_backend: str = ""
    local_cameras: list[dict[str, Any]] = field(default_factory=list)
    last_resolved_source: str = ""
    last_resolved_label: str = ""
    last_resolved_kind: str = ""
    last_resolved_backend: str = ""
    discovered_sources: list[dict[str, Any]] = field(default_factory=list)

    @staticmethod
    def _text(value: object) -> str:
        return str(value).strip() if value is not None else ""

    @classmethod
    def from_mapping(cls, payload: dict[str, Any] | None) -> InferenceSourceConfig:
        data = payload if isinstance(payload, dict) else {}
        discovered: list[dict[str, Any]] = []
        raw_discovered = data.get("discovered_sources")
        if isinstance(raw_discovered, list):
            for item in raw_discovered:
                if isinstance(item, dict):
                    discovered.append(
                        {
                            "kind": cls._text(item.get("kind")),
                            "label": cls._text(item.get("label")),
                            "source": cls._text(item.get("source")),
                            "backend": cls._text(item.get("backend")),
                            "available": bool(item.get("available", True)),
                        }
                    )

        local_cameras = cls._normalize_local_cameras(data.get("local_cameras"))

        rtsp_cameras = cls._normalize_rtsp_cameras(data.get("rtsp_cameras"))
        legacy_rtsp = cls._normalize_rtsp_camera(
            {
                "name": data.get("default_rtsp_camera") or data.get("rtsp_name") or "RTSP 1",
                "url": data.get("rtsp_url"),
                "username": data.get("rtsp_username"),
                "password": data.get("rtsp_password"),
                "enabled": True,
            },
            fallback_name="RTSP 1",
        )
        if not rtsp_cameras and legacy_rtsp is not None:
            rtsp_cameras = [legacy_rtsp]

        default_rtsp_name = cls._text(data.get("default_rtsp_camera"))
        default_camera = cls._default_rtsp_camera(rtsp_cameras, default_rtsp_name)
        if default_camera is None and legacy_rtsp is not None:
            default_camera = legacy_rtsp

        rtsp_url = cls._text(data.get("rtsp_url"))
        rtsp_username = cls._text(data.get("rtsp_username"))
        rtsp_password = cls._text(data.get("rtsp_password"))
        if default_camera is not None:
            rtsp_url = cls._text(default_camera.get("url")) or rtsp_url
            rtsp_username = cls._text(default_camera.get("username")) or rtsp_username
            rtsp_password = cls._text(default_camera.get("password")) or rtsp_password
            if not default_rtsp_name:
                default_rtsp_name = cls._text(default_camera.get("name"))

        return cls(
            version=int(data.get("version", 1) or 1),
            mode=cls._normalize_mode(data.get("mode", "auto")),
            rtsp_url=rtsp_url,
            rtsp_username=rtsp_username,
            rtsp_password=rtsp_password,
            default_rtsp_camera=default_rtsp_name,
            rtsp_cameras=rtsp_cameras,
            camera_source=cls._text(data.get("camera_source")),
            camera_label=cls._text(data.get("camera_label")),
            camera_backend=cls._text(data.get("camera_backend")),
            local_cameras=local_cameras,
            last_resolved_source=cls._text(data.get("last_resolved_source")),
            last_resolved_label=cls._text(data.get("last_resolved_label")),
            last_resolved_kind=cls._text(data.get("last_resolved_kind")),
            last_resolved_backend=cls._text(data.get("last_resolved_backend")),
            discovered_sources=discovered,
        )

    def to_mapping(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def _normalize_mode(value: object) -> str:
        mode = str(value).strip().lower()
        if mode not in {"auto", "webcam", "csi", "rtsp"}:
            return "auto"
        return mode

    @staticmethod
    def _normalize_rtsp_camera(item: dict[str, Any], *, fallback_name: str = "RTSP") -> dict[str, Any] | None:
        url = InferenceSourceConfig._text(item.get("url") or item.get("rtsp_url"))
        if not url:
            return None
        name = InferenceSourceConfig._text(item.get("name") or item.get("label")) or fallback_name
        enabled_raw = item.get("enabled", True)
        if isinstance(enabled_raw, str):
            enabled = enabled_raw.strip().lower() not in {"false", "0", "no", "off"}
        else:
            enabled = bool(enabled_raw)
        return {
            "name": name,
            "url": url,
            "username": InferenceSourceConfig._text(item.get("username") or item.get("rtsp_username")),
            "password": InferenceSourceConfig._text(item.get("password") or item.get("rtsp_password")),
            "enabled": enabled,
        }

    @staticmethod
    def _normalize_local_camera(item: dict[str, Any], *, fallback_name: str = "Cámara") -> dict[str, Any] | None:
        source = InferenceSourceConfig._text(item.get("source"))
        if not source:
            return None
        kind_raw = InferenceSourceConfig._text(item.get("kind")).lower()
        if kind_raw not in {"webcam", "csi"}:
            kind_raw = "csi" if "!" in source or source.startswith("nvarguscamerasrc") else "webcam"
        backend_raw = InferenceSourceConfig._text(item.get("backend")).lower()
        if not backend_raw:
            backend_raw = "gstreamer" if kind_raw == "csi" else "v4l2"
        name = InferenceSourceConfig._text(item.get("name") or item.get("label")) or fallback_name
        enabled_raw = item.get("enabled", True)
        if isinstance(enabled_raw, str):
            enabled = enabled_raw.strip().lower() not in {"false", "0", "no", "off"}
        else:
            enabled = bool(enabled_raw)
        return {
            "name": name,
            "kind": kind_raw,
            "source": source,
            "backend": backend_raw,
            "enabled": enabled,
        }

    @classmethod
    def _normalize_local_cameras(cls, payload: object) -> list[dict[str, Any]]:
        cameras: list[dict[str, Any]] = []
        if not isinstance(payload, list):
            return cameras
        for index, item in enumerate(payload):
            if isinstance(item, dict):
                camera = cls._normalize_local_camera(item, fallback_name=f"Cámara {index + 1}")
                if camera is not None:
                    cameras.append(camera)
        return cameras

    @classmethod
    def _normalize_rtsp_cameras(cls, payload: object) -> list[dict[str, Any]]:
        cameras: list[dict[str, Any]] = []
        if not isinstance(payload, list):
            return cameras
        for index, item in enumerate(payload):
            if isinstance(item, dict):
                camera = cls._normalize_rtsp_camera(item, fallback_name=f"RTSP {index + 1}")
                if camera is not None:
                    cameras.append(camera)
        return cameras

    @staticmethod
    def _default_rtsp_camera(cameras: list[dict[str, Any]], default_name: str) -> dict[str, Any] | None:
        if default_name:
            for camera in cameras:
                if str(camera.get("name", "")).strip() == default_name:
                    return camera
        for camera in cameras:
            if bool(camera.get("enabled", True)):
                return camera
        return cameras[0] if cameras else None


def load_inference_source_config(path: Path = VIDEO_SOURCE_PATH) -> InferenceSourceConfig:
    path = Path(path)
    if not path.exists():
        return InferenceSourceConfig()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return InferenceSourceConfig()
    return InferenceSourceConfig.from_mapping(payload if isinstance(payload, dict) else {})


def save_inference_source_config(path: Path, config: InferenceSourceConfig) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config.to_mapping(), indent=2, ensure_ascii=False), encoding="utf-8")


def build_rtsp_url(url: str, username: str = "", password: str = "") -> str:
    cleaned = str(url).strip()
    if not cleaned:
        return ""

    if "@" in cleaned and cleaned.startswith("rtsp://"):
        return cleaned

    parts = urlsplit(cleaned if "://" in cleaned else f"rtsp://{cleaned}")
    if not username and not password:
        return urlunsplit(parts)

    netloc = parts.hostname or ""
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    auth = quote(username, safe="")
    if password:
        auth = f"{auth}:{quote(password, safe='')}"
    if auth:
        netloc = f"{auth}@{netloc}"
    return urlunsplit((parts.scheme or "rtsp", netloc, parts.path, parts.query, parts.fragment))


def normalize_rtsp_url(url: str, username: str = "", password: str = "") -> tuple[str, str]:
    """Return a canonical RTSP URL or an error message."""
    built = build_rtsp_url(url, username, password)
    if not built:
        return "", "La URL RTSP no puede estar vacía."

    parts = urlsplit(built)
    if parts.scheme.lower() != "rtsp":
        return "", "La URL debe usar el esquema rtsp://"
    if not parts.hostname:
        return "", "La URL RTSP necesita un host válido."
    return built, ""


def friendly_rtsp_name(url: str) -> str:
    normalized, _error = normalize_rtsp_url(url)
    if not normalized:
        return "RTSP"
    parts = urlsplit(normalized)
    host = parts.hostname or "RTSP"
    if parts.port:
        host = f"{host}:{parts.port}"
    path = parts.path.strip("/")
    if path:
        tail = path.split("/")[-1].strip()
        if tail and tail.lower() not in {host.lower(), "stream", "live"}:
            return f"{host} · {tail}"
    return host


def probe_rtsp_url(url: str, username: str = "", password: str = "", timeout_ms: int = 3000) -> tuple[bool, str]:
    normalized, error = normalize_rtsp_url(url, username, password)
    if error:
        return False, error

    cap = cv2.VideoCapture(normalized, cv2.CAP_FFMPEG)
    try:
        if hasattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC"):
            try:
                cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, float(timeout_ms))
            except Exception:
                pass
        if hasattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC"):
            try:
                cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, float(timeout_ms))
            except Exception:
                pass
        if not cap.isOpened():
            return False, "No se pudo abrir la cámara RTSP."
        for _ in range(2):
            ok, frame = cap.read()
            if ok and frame is not None and int(getattr(frame, "size", 0) or 0) > 0:
                return True, "Conexión RTSP OK."
        return False, "La cámara abrió pero no devolvió frames."
    finally:
        cap.release()


def _normalized_rtsp_cameras(config: InferenceSourceConfig) -> list[dict[str, Any]]:
    cameras: list[dict[str, Any]] = []
    for index, item in enumerate(config.rtsp_cameras):
        if isinstance(item, dict):
            camera = InferenceSourceConfig._normalize_rtsp_camera(item, fallback_name=f"RTSP {index + 1}")
            if camera is not None:
                cameras.append(camera)

    if not cameras:
        legacy = InferenceSourceConfig._normalize_rtsp_camera(
            {
                "name": config.default_rtsp_camera or "RTSP 1",
                "url": config.rtsp_url,
                "username": config.rtsp_username,
                "password": config.rtsp_password,
                "enabled": True,
            },
            fallback_name="RTSP 1",
        )
        if legacy is not None:
            cameras.append(legacy)

    default_name = config.default_rtsp_camera.strip()
    if default_name:
        cameras.sort(key=lambda camera: str(camera.get("name", "")).strip() != default_name)

    return cameras


_V4L2_DEVICE_RE = re.compile(r"^(?:/dev/video)?(\d+)$")


def _resolve_v4l2_capture_source(source: str) -> Any:
    match = _V4L2_DEVICE_RE.match(str(source).strip())
    if match:
        return int(match.group(1))
    return source


def _probe_capture(source: str, backend: int) -> bool:
    capture_source: Any = source
    if backend == cv2.CAP_V4L2:
        capture_source = _resolve_v4l2_capture_source(source)
    cap = cv2.VideoCapture(capture_source, backend)
    try:
        if not cap.isOpened():
            return False
        for _ in range(2):
            ok, frame = cap.read()
            if ok and frame is not None and int(getattr(frame, "size", 0) or 0) > 0:
                return True
        return False
    finally:
        cap.release()


def _device_sort_key(path: Path) -> tuple[int, str]:
    suffix = path.name.removeprefix("video")
    try:
        return int(suffix), path.name
    except ValueError:
        return 9999, path.name


def discover_video_sources(hardware: HardwareManager | None = None) -> list[VideoSourceChoice]:
    hardware = hardware or HardwareManager()
    choices: list[VideoSourceChoice] = []

    if platform.system().lower() == "linux":
        for device in sorted(Path("/dev").glob("video*"), key=_device_sort_key):
            source = str(device)
            available = _probe_capture(source, cv2.CAP_V4L2)
            choices.append(
                VideoSourceChoice(
                    kind="webcam",
                    label=f"Webcam {device.name}",
                    source=source,
                    backend="v4l2",
                    available=available,
                )
            )

        if hardware.info.kind in {"jetson", "raspberry"}:
            source = hardware.default_camera_source().strip()
            if source:
                available = _probe_capture(source, cv2.CAP_GSTREAMER)
                choices.append(
                    VideoSourceChoice(
                        kind="csi",
                        label=f"CSI {hardware.info.name}",
                        source=source,
                        backend="gstreamer",
                        available=available,
                    )
                )

    return choices


def _choice_from_source(source: str, *, kind: str, label: str, backend: str = "") -> VideoSourceChoice:
    return VideoSourceChoice(kind=kind, label=label, source=source, backend=backend, available=True)


def resolve_video_source_candidates(
    config: InferenceSourceConfig,
    hardware: HardwareManager,
) -> tuple[list[VideoSourceChoice], list[VideoSourceChoice]]:
    discovered = discover_video_sources(hardware)
    candidates: list[VideoSourceChoice] = []
    seen: set[str] = set()

    def add(choice: VideoSourceChoice) -> None:
        if not choice.source or choice.source in seen:
            return
        seen.add(choice.source)
        candidates.append(choice)

    mode = InferenceSourceConfig._normalize_mode(config.mode)
    rtsp_cameras = _normalized_rtsp_cameras(config)
    local_cameras = [
        cam for cam in (
            InferenceSourceConfig._normalize_local_camera(item, fallback_name=f"Cámara {idx + 1}")
            for idx, item in enumerate(config.local_cameras)
            if isinstance(item, dict)
        )
        if cam is not None
    ]

    def add_rtsp_cameras() -> None:
        for camera in rtsp_cameras:
            if not bool(camera.get("enabled", True)):
                continue
            url, _error = normalize_rtsp_url(
                str(camera.get("url", "")),
                str(camera.get("username", "")),
                str(camera.get("password", "")),
            )
            if not url:
                continue
            label = str(camera.get("name", "")).strip() or friendly_rtsp_name(url)
            add(_choice_from_source(url, kind="rtsp", label=label, backend="ffmpeg"))

    def add_local_cameras() -> None:
        for camera in local_cameras:
            if not bool(camera.get("enabled", True)):
                continue
            kind = str(camera.get("kind", "webcam")).strip().lower() or "webcam"
            if mode == "webcam" and kind != "webcam":
                continue
            if mode == "csi" and kind != "csi":
                continue
            source = str(camera.get("source", "")).strip()
            if not source:
                continue
            backend = str(camera.get("backend", "")).strip().lower() or (
                "gstreamer" if kind == "csi" else "v4l2"
            )
            label = str(camera.get("name", "")).strip() or source
            add(_choice_from_source(source, kind=kind, label=label, backend=backend))

    if mode == "rtsp":
        add_rtsp_cameras()
        return candidates, discovered

    add_local_cameras()

    preferred_source = config.camera_source.strip()
    if preferred_source:
        preferred_label = config.camera_label.strip() or preferred_source
        preferred_backend = config.camera_backend.strip()
        if not preferred_backend:
            if preferred_source.startswith("rtsp://"):
                preferred_backend = "ffmpeg"
            elif preferred_source.startswith("/dev/video"):
                preferred_backend = "v4l2"
            else:
                preferred_backend = "gstreamer"
        add(_choice_from_source(preferred_source, kind=mode if mode != "auto" else "local", label=preferred_label, backend=preferred_backend))

    if mode in {"auto", "csi"} and hardware.info.kind in {"jetson", "raspberry"}:
        source = hardware.default_camera_source().strip()
        if source:
            add(_choice_from_source(source, kind="csi", label=f"CSI {hardware.info.name}", backend="gstreamer"))

    if mode in {"auto", "webcam"}:
        for choice in discovered:
            if choice.kind == "webcam" and choice.available:
                add(choice)
        for choice in discovered:
            if choice.kind == "webcam" and not choice.available:
                add(choice)

    if mode == "auto" and (config.rtsp_url.strip() or rtsp_cameras):
        add_rtsp_cameras()

    if not candidates:
        for choice in discovered:
            if choice.available:
                add(choice)
                break

    return candidates, discovered


def capture_backend_for(choice: VideoSourceChoice) -> int:
    backend = choice.backend.lower().strip()
    if backend == "ffmpeg":
        return cv2.CAP_FFMPEG
    if backend == "v4l2":
        return cv2.CAP_V4L2
    if backend == "gstreamer":
        return cv2.CAP_GSTREAMER
    return cv2.CAP_ANY
