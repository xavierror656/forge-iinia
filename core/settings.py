"""Typed access to ``.env`` configuration.

Single source of truth for which env vars exist, their defaults, types,
and which combinations are valid. Loading order matches 12-factor:

    .env  →  .env.local  →  os.environ

with each step overriding the previous, so per-machine secrets in
``.env.local`` (gitignored) and CI overrides via ``os.environ`` work as
expected without editing the committed ``.env``.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Literal

from core.env_config import read_env_file
from core.output_adapters import InferenceOutputConfig

log = logging.getLogger(__name__)

HardwareOverride = Literal["jetson", "raspberry", "development", ""]


def _as_bool(value: str | bool | None, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on", "y"}


def _as_float(value: object, default: float) -> float:
    if value is None or value == "":
        return default
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def _as_int(value: object, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


@dataclass(slots=True)
class Settings:
    forge_url: str = "https://forge.iinia.ai/api/swagger/"
    forge_username: str = ""
    forge_password: str = ""
    forge_token: str = ""
    forge_model_url: str = ""
    forge_model_asset_uuid: str = ""
    model_dir: str = "models"
    capture_dir: str = "captures"
    simulation_mode: bool = True

    # Operational tuning — exposed so each deployment can tweak without code edits.
    hardware_override: HardwareOverride = ""
    log_dir: str = ""
    gpio_pulse_seconds: float = 0.1
    gpio_dedupe_seconds: float = 1.0
    http_retry_attempts: int = 3
    watchdog_timeout_seconds: float = 2.5
    output_config: InferenceOutputConfig = field(default_factory=InferenceOutputConfig)

    extras: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, values: Mapping[str, str]) -> Settings:
        known = {f.name for f in fields(cls)} - {"extras"}
        unknown: dict[str, str] = {}
        out = cls()
        for raw_key, raw_value in values.items():
            key = raw_key.strip().lower()
            value = raw_value.strip() if isinstance(raw_value, str) else raw_value
            if key == "simulation_mode":
                out.simulation_mode = _as_bool(value, True)
            elif key == "hardware_override":
                normalized = str(value).strip().lower()
                if normalized in ("jetson", "raspberry", "development", ""):
                    out.hardware_override = normalized  # type: ignore[assignment]
                else:
                    log.warning("Ignoring HARDWARE_OVERRIDE=%r (unknown value)", value)
            elif key == "gpio_pulse_seconds":
                out.gpio_pulse_seconds = _as_float(value, out.gpio_pulse_seconds)
            elif key == "gpio_dedupe_seconds":
                out.gpio_dedupe_seconds = _as_float(value, out.gpio_dedupe_seconds)
            elif key == "watchdog_timeout_seconds":
                out.watchdog_timeout_seconds = _as_float(value, out.watchdog_timeout_seconds)
            elif key == "http_retry_attempts":
                out.http_retry_attempts = max(1, _as_int(value, out.http_retry_attempts))
            elif raw_key.strip().upper().startswith("OUTPUT_"):
                continue
            elif key in known:
                setattr(out, key, value)
            else:
                unknown[raw_key] = raw_value
        out.output_config = InferenceOutputConfig.from_mapping(values)
        out.extras = unknown
        return out

    @classmethod
    def load(
        cls,
        env_path: Path | str = ".env",
        *,
        local_env_path: Path | str | None = None,
        include_os_environ: bool = True,
        warn_unknown: bool = True,
    ) -> Settings:
        """Load settings honoring 12-factor precedence.

        Resolution order (last wins): ``env_path`` → ``local_env_path``
        (defaults to ``<env_path>.local``) → ``os.environ``.
        """
        merged: dict[str, str] = {}
        primary = Path(env_path)
        merged.update(read_env_file(primary))

        local = Path(local_env_path) if local_env_path else primary.with_suffix(primary.suffix + ".local")
        if local.exists():
            merged.update(read_env_file(local))

        if include_os_environ:
            for key in cls._supported_env_keys():
                if key in os.environ:
                    merged[key] = os.environ[key]

        settings = cls.from_mapping(merged)

        if warn_unknown:
            for key in settings.extras:
                if key.startswith("EDGEVISION_") or key.startswith("FORGE_"):
                    log.warning("Unknown env key %r — typo? (ignored)", key)

        return settings

    @classmethod
    def _supported_env_keys(cls) -> tuple[str, ...]:
        return (
            "FORGE_URL",
            "FORGE_USERNAME",
            "FORGE_PASSWORD",
        "FORGE_TOKEN",
            "FORGE_MODEL_URL",
            "FORGE_MODEL_ASSET_UUID",
        "MODEL_DIR",
            "CAPTURE_DIR",
            "SIMULATION_MODE",
            "HARDWARE_OVERRIDE",
            "LOG_DIR",
            "GPIO_PULSE_SECONDS",
            "GPIO_DEDUPE_SECONDS",
            "HTTP_RETRY_ATTEMPTS",
            "WATCHDOG_TIMEOUT_SECONDS",
            "OUTPUT_MQTT_ENABLED",
            "OUTPUT_MQTT_HOST",
            "OUTPUT_MQTT_PORT",
            "OUTPUT_MQTT_TOPIC",
            "OUTPUT_HTTP_ENABLED",
            "OUTPUT_HTTP_URL",
            "OUTPUT_WEBSOCKET_ENABLED",
            "OUTPUT_WEBSOCKET_URL",
            "OUTPUT_TCP_ENABLED",
            "OUTPUT_TCP_HOST",
            "OUTPUT_TCP_PORT",
            "OUTPUT_UDP_ENABLED",
            "OUTPUT_UDP_HOST",
            "OUTPUT_UDP_PORT",
            "OUTPUT_MODBUS_ENABLED",
            "OUTPUT_MODBUS_HOST",
            "OUTPUT_MODBUS_PORT",
            "OUTPUT_MODBUS_UNIT_ID",
            "OUTPUT_MODBUS_COUNT_REGISTER",
            "OUTPUT_MODBUS_ACTIVE_COIL",
        )

    def validate(self) -> list[str]:
        """Return a list of problems. Empty list = configuration is usable."""
        problems: list[str] = []

        if not self.forge_url.strip():
            problems.append("FORGE_URL is empty")
        if not self.simulation_mode and not self.has_forge_credentials:
            problems.append(
                "Forge has no credentials (set FORGE_TOKEN or FORGE_USERNAME+FORGE_PASSWORD), "
                "or set SIMULATION_MODE=true to run without backend"
            )
        if self.gpio_pulse_seconds < 0:
            problems.append(f"GPIO_PULSE_SECONDS must be >= 0 (got {self.gpio_pulse_seconds})")
        if self.gpio_dedupe_seconds < 0:
            problems.append(f"GPIO_DEDUPE_SECONDS must be >= 0 (got {self.gpio_dedupe_seconds})")
        if self.watchdog_timeout_seconds <= 0:
            problems.append(
                f"WATCHDOG_TIMEOUT_SECONDS must be > 0 (got {self.watchdog_timeout_seconds})"
            )
        if self.http_retry_attempts < 1:
            problems.append(f"HTTP_RETRY_ATTEMPTS must be >= 1 (got {self.http_retry_attempts})")
        if self.output_config.mqtt_enabled and not self.output_config.mqtt_host:
            problems.append("OUTPUT_MQTT_HOST is required when OUTPUT_MQTT_ENABLED=true")
        if self.output_config.http_enabled and not self.output_config.http_url:
            problems.append("OUTPUT_HTTP_URL is required when OUTPUT_HTTP_ENABLED=true")
        if self.output_config.websocket_enabled and not self.output_config.websocket_url:
            problems.append("OUTPUT_WEBSOCKET_URL is required when OUTPUT_WEBSOCKET_ENABLED=true")
        if self.output_config.tcp_enabled and not self.output_config.tcp_host:
            problems.append("OUTPUT_TCP_HOST is required when OUTPUT_TCP_ENABLED=true")
        if self.output_config.udp_enabled and not self.output_config.udp_host:
            problems.append("OUTPUT_UDP_HOST is required when OUTPUT_UDP_ENABLED=true")
        if self.output_config.modbus_enabled and not self.output_config.modbus_host:
            problems.append("OUTPUT_MODBUS_HOST is required when OUTPUT_MODBUS_ENABLED=true")
        return problems

    def as_env_dict(self) -> dict[str, str]:
        out = {
            "FORGE_URL": self.forge_url,
            "FORGE_USERNAME": self.forge_username,
            "FORGE_PASSWORD": self.forge_password,
        "FORGE_TOKEN": self.forge_token,
            "FORGE_MODEL_URL": self.forge_model_url,
            "FORGE_MODEL_ASSET_UUID": self.forge_model_asset_uuid,
        "MODEL_DIR": self.model_dir,
            "CAPTURE_DIR": self.capture_dir,
            "SIMULATION_MODE": "true" if self.simulation_mode else "false",
            "HARDWARE_OVERRIDE": self.hardware_override or "",
            "LOG_DIR": self.log_dir,
            "GPIO_PULSE_SECONDS": str(self.gpio_pulse_seconds),
            "GPIO_DEDUPE_SECONDS": str(self.gpio_dedupe_seconds),
            "HTTP_RETRY_ATTEMPTS": str(self.http_retry_attempts),
            "WATCHDOG_TIMEOUT_SECONDS": str(self.watchdog_timeout_seconds),
        }
        out.update(self.output_config.as_env_dict())
        out.update(self.extras)
        return out

    @property
    def has_forge_credentials(self) -> bool:
        return bool(self.forge_token) or bool(self.forge_username and self.forge_password)

    @property
    def model_path(self) -> Path:
        return Path(self.model_dir) if self.model_dir else Path("models")

    @property
    def capture_path(self) -> Path:
        return Path(self.capture_dir) if self.capture_dir else Path("captures")
