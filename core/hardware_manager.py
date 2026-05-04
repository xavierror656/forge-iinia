"""Hardware abstraction layer for EdgeVision Control Hub.

This module isolates platform-specific capabilities behind a common interface.
It supports Jetson, Raspberry Pi, and a development/mock backend.
"""

from __future__ import annotations

import abc
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

HardwareKind = Literal["jetson", "raspberry", "development"]
UIProfile = Literal["multi", "single", "desktop"]


@dataclass(frozen=True, slots=True)
class HardwareInfo:
    """Normalized hardware metadata used by the application."""

    kind: HardwareKind
    name: str
    simulation: bool
    camera_backend: str
    gpio_backend: str
    telemetry_backend: str
    gstreamer_pipeline: str
    recommended_model_format: str
    deployment_note: str
    ui_profile: UIProfile
    max_active_cameras: int


class HardwareProvider(abc.ABC):
    """Abstract base class for hardware-specific integrations."""

    kind: HardwareKind

    @abc.abstractmethod
    def info(self) -> HardwareInfo:
        """Return a normalized snapshot of the current hardware profile."""

    @abc.abstractmethod
    def temperature_sources(self) -> tuple[str, ...]:
        """Return sensor paths or labels used for thermal telemetry."""

    @abc.abstractmethod
    def default_camera_source(self) -> str:
        """Return the best default camera/video source identifier."""

    @abc.abstractmethod
    def supports_tensor_rt(self) -> bool:
        """Return whether the backend can execute TensorRT engines."""

    def is_simulation(self) -> bool:
        return self.info().simulation


class JetsonProvider(HardwareProvider):
    kind: HardwareKind = "jetson"

    def info(self) -> HardwareInfo:
        return HardwareInfo(
            kind=self.kind,
            name="NVIDIA Jetson",
            simulation=False,
            camera_backend="gstreamer:nvarguscamerasrc",
            gpio_backend="native-gpio",
            telemetry_backend="jetson-telemetry",
            gstreamer_pipeline=(
                "nvarguscamerasrc ! video/x-raw(memory:NVMM), width=1280, height=720, "
                "framerate=30/1 ! nvvidconv ! video/x-raw, format=BGRx ! videoconvert ! appsink"
            ),
            recommended_model_format=".engine",
            deployment_note="Jetson: prefer TensorRT engine exports and GStreamer with nvarguscamerasrc.",
            ui_profile="multi",
            max_active_cameras=0,
        )

    def temperature_sources(self) -> tuple[str, ...]:
        return (
            "/sys/devices/virtual/thermal/thermal_zone0/temp",
            "/sys/devices/virtual/thermal/thermal_zone1/temp",
        )

    def default_camera_source(self) -> str:
        return self.info().gstreamer_pipeline

    def supports_tensor_rt(self) -> bool:
        return True


class RaspberryProvider(HardwareProvider):
    kind: HardwareKind = "raspberry"

    def info(self) -> HardwareInfo:
        return HardwareInfo(
            kind=self.kind,
            name="Raspberry Pi",
            simulation=False,
            camera_backend="gstreamer:v4l2src",
            gpio_backend="native-gpio",
            telemetry_backend="linux-telemetry",
            gstreamer_pipeline=(
                "v4l2src device=/dev/video0 ! video/x-raw, width=1280, height=720, "
                "framerate=30/1 ! videoconvert ! appsink"
            ),
            recommended_model_format=".imx",
            deployment_note="Raspberry Pi AI Camera: prefer IMX500 exports; otherwise use v4l2src for development.",
            ui_profile="single",
            max_active_cameras=1,
        )

    def temperature_sources(self) -> tuple[str, ...]:
        return (
            "/sys/class/thermal/thermal_zone0/temp",
        )

    def default_camera_source(self) -> str:
        return self.info().gstreamer_pipeline

    def supports_tensor_rt(self) -> bool:
        return False


class DevelopmentProvider(HardwareProvider):
    kind: HardwareKind = "development"

    def info(self) -> HardwareInfo:
        return HardwareInfo(
            kind=self.kind,
            name="Development / Mock",
            simulation=True,
            camera_backend="video-file-or-webcam",
            gpio_backend="mock-gpio",
            telemetry_backend="mock-telemetry",
            gstreamer_pipeline=(
                "filesrc location=sample.mp4 ! decodebin ! videoconvert ! appsink"
            ),
            recommended_model_format=".pt/.onnx",
            deployment_note="Development: use local files, webcam, or prerecorded videos for validation.",
            ui_profile="desktop",
            max_active_cameras=0,
        )

    def temperature_sources(self) -> tuple[str, ...]:
        return tuple()

    def default_camera_source(self) -> str:
        return self.info().gstreamer_pipeline

    def supports_tensor_rt(self) -> bool:
        return False


class HardwareManager:
    """Factory and convenience methods for runtime hardware selection."""

    def __init__(
        self,
        forced_kind: HardwareKind | None = None,
        *,
        force_simulation: bool = False,
    ) -> None:
        if force_simulation:
            forced_kind = "development"
        self._provider = self._create_provider(forced_kind)

    @staticmethod
    def _read_text(path: str) -> str:
        try:
            return Path(path).read_text(encoding="utf-8", errors="ignore").strip()
        except OSError:
            return ""

    @classmethod
    def _detect_kind(cls) -> HardwareKind:
        machine = platform.machine().lower()
        model_text = " ".join(
            filter(
                None,
                (
                    cls._read_text("/proc/device-tree/model"),
                    cls._read_text("/sys/firmware/devicetree/base/model"),
                    cls._read_text("/proc/cpuinfo"),
                ),
            )
        ).lower()

        if any(token in machine for token in ("aarch64", "arm64")) and (
            "nvidia" in model_text or "jetson" in model_text or Path("/etc/nv_tegra_release").exists()
        ):
            return "jetson"

        if "raspberry" in model_text or "raspberry pi" in model_text:
            return "raspberry"

        if Path("/proc/device-tree/model").exists() and "bcm" in model_text:
            return "raspberry"

        return "development"

    @classmethod
    def _create_provider(cls, forced_kind: HardwareKind | None) -> HardwareProvider:
        kind = forced_kind or cls._detect_kind()
        if kind == "jetson":
            return JetsonProvider()
        if kind == "raspberry":
            return RaspberryProvider()
        return DevelopmentProvider()

    @property
    def provider(self) -> HardwareProvider:
        return self._provider

    @property
    def info(self) -> HardwareInfo:
        return self._provider.info()

    def default_camera_source(self) -> str:
        return self._provider.default_camera_source()

    def supports_tensor_rt(self) -> bool:
        return self._provider.supports_tensor_rt()

    def temperature_sources(self) -> tuple[str, ...]:
        return self._provider.temperature_sources()

    def is_simulation(self) -> bool:
        return self._provider.is_simulation()

    @property
    def ui_profile(self) -> UIProfile:
        return self._provider.info().ui_profile

    @property
    def max_active_cameras(self) -> int:
        """Return 0 for unlimited, or the hardware camera worker limit."""
        return self._provider.info().max_active_cameras
