"""Optional inference output adapters.

Each adapter is best-effort: failures are logged through the callback but never
block the UI/inference loop. Third-party industrial clients are imported lazily
so deployments can enable only the protocols they actually install.
"""

from __future__ import annotations

import json
import queue
import socket
import threading
import time
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass


def _as_bool(value: object, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "y"}


def _as_int(value: object, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


@dataclass(slots=True)
class InferenceOutputConfig:
    mqtt_enabled: bool = False
    mqtt_host: str = ""
    mqtt_port: int = 1883
    mqtt_topic: str = "edgevision/inference"

    http_enabled: bool = False
    http_url: str = ""

    websocket_enabled: bool = False
    websocket_url: str = ""

    tcp_enabled: bool = False
    tcp_host: str = ""
    tcp_port: int = 9000

    udp_enabled: bool = False
    udp_host: str = ""
    udp_port: int = 9001

    modbus_enabled: bool = False
    modbus_host: str = ""
    modbus_port: int = 502
    modbus_unit_id: int = 1
    modbus_count_register: int = 0
    modbus_active_coil: int = 0

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> InferenceOutputConfig:
        return cls(
            mqtt_enabled=_as_bool(values.get("OUTPUT_MQTT_ENABLED")),
            mqtt_host=str(values.get("OUTPUT_MQTT_HOST", "")).strip(),
            mqtt_port=_as_int(values.get("OUTPUT_MQTT_PORT"), 1883),
            mqtt_topic=str(values.get("OUTPUT_MQTT_TOPIC", "edgevision/inference")).strip() or "edgevision/inference",
            http_enabled=_as_bool(values.get("OUTPUT_HTTP_ENABLED")),
            http_url=str(values.get("OUTPUT_HTTP_URL", "")).strip(),
            websocket_enabled=_as_bool(values.get("OUTPUT_WEBSOCKET_ENABLED")),
            websocket_url=str(values.get("OUTPUT_WEBSOCKET_URL", "")).strip(),
            tcp_enabled=_as_bool(values.get("OUTPUT_TCP_ENABLED")),
            tcp_host=str(values.get("OUTPUT_TCP_HOST", "")).strip(),
            tcp_port=_as_int(values.get("OUTPUT_TCP_PORT"), 9000),
            udp_enabled=_as_bool(values.get("OUTPUT_UDP_ENABLED")),
            udp_host=str(values.get("OUTPUT_UDP_HOST", "")).strip(),
            udp_port=_as_int(values.get("OUTPUT_UDP_PORT"), 9001),
            modbus_enabled=_as_bool(values.get("OUTPUT_MODBUS_ENABLED")),
            modbus_host=str(values.get("OUTPUT_MODBUS_HOST", "")).strip(),
            modbus_port=_as_int(values.get("OUTPUT_MODBUS_PORT"), 502),
            modbus_unit_id=_as_int(values.get("OUTPUT_MODBUS_UNIT_ID"), 1),
            modbus_count_register=_as_int(values.get("OUTPUT_MODBUS_COUNT_REGISTER"), 0),
            modbus_active_coil=_as_int(values.get("OUTPUT_MODBUS_ACTIVE_COIL"), 0),
        )

    def as_env_dict(self) -> dict[str, str]:
        return {
            "OUTPUT_MQTT_ENABLED": "true" if self.mqtt_enabled else "false",
            "OUTPUT_MQTT_HOST": self.mqtt_host,
            "OUTPUT_MQTT_PORT": str(self.mqtt_port),
            "OUTPUT_MQTT_TOPIC": self.mqtt_topic,
            "OUTPUT_HTTP_ENABLED": "true" if self.http_enabled else "false",
            "OUTPUT_HTTP_URL": self.http_url,
            "OUTPUT_WEBSOCKET_ENABLED": "true" if self.websocket_enabled else "false",
            "OUTPUT_WEBSOCKET_URL": self.websocket_url,
            "OUTPUT_TCP_ENABLED": "true" if self.tcp_enabled else "false",
            "OUTPUT_TCP_HOST": self.tcp_host,
            "OUTPUT_TCP_PORT": str(self.tcp_port),
            "OUTPUT_UDP_ENABLED": "true" if self.udp_enabled else "false",
            "OUTPUT_UDP_HOST": self.udp_host,
            "OUTPUT_UDP_PORT": str(self.udp_port),
            "OUTPUT_MODBUS_ENABLED": "true" if self.modbus_enabled else "false",
            "OUTPUT_MODBUS_HOST": self.modbus_host,
            "OUTPUT_MODBUS_PORT": str(self.modbus_port),
            "OUTPUT_MODBUS_UNIT_ID": str(self.modbus_unit_id),
            "OUTPUT_MODBUS_COUNT_REGISTER": str(self.modbus_count_register),
            "OUTPUT_MODBUS_ACTIVE_COIL": str(self.modbus_active_coil),
        }

    def enabled_protocols(self) -> list[str]:
        protocols: list[str] = []
        if self.mqtt_enabled and self.mqtt_host:
            protocols.append("mqtt")
        if self.http_enabled and self.http_url:
            protocols.append("http")
        if self.websocket_enabled and self.websocket_url:
            protocols.append("websocket")
        if self.tcp_enabled and self.tcp_host:
            protocols.append("tcp")
        if self.udp_enabled and self.udp_host:
            protocols.append("udp")
        if self.modbus_enabled and self.modbus_host:
            protocols.append("modbus")
        return protocols


class InferenceOutputDispatcher:
    def __init__(
        self,
        config: InferenceOutputConfig | None = None,
        *,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self._config = config or InferenceOutputConfig()
        self._log = log or (lambda _message: None)
        self._events: "queue.Queue[dict | None]" = queue.Queue(maxsize=128)
        self._stop_requested = threading.Event()
        self._thread = threading.Thread(target=self._run, name="inference-output", daemon=True)
        self._mqtt_client = None

    def start(self) -> None:
        if not self._thread.is_alive():
            self._thread.start()

    def stop(self) -> None:
        self._stop_requested.set()
        self._events.put(None)
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._close_mqtt()

    def update_config(self, config: InferenceOutputConfig) -> None:
        old_mqtt = (self._config.mqtt_host, self._config.mqtt_port)
        self._config = config
        if old_mqtt != (config.mqtt_host, config.mqtt_port):
            self._close_mqtt()

    def publish(self, payload: dict) -> None:
        if not self._config.enabled_protocols():
            return
        try:
            self._events.put_nowait(dict(payload))
        except queue.Full:
            self._log("Inference output queue full; dropping payload.")

    def _run(self) -> None:
        while not self._stop_requested.is_set():
            payload = self._events.get()
            if payload is None:
                return
            self._dispatch(payload)

    def _dispatch(self, payload: dict) -> None:
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        cfg = self._config
        if cfg.mqtt_enabled and cfg.mqtt_host:
            self._safe("mqtt", lambda: self._send_mqtt(body))
        if cfg.http_enabled and cfg.http_url:
            self._safe("http", lambda: self._send_http(body))
        if cfg.websocket_enabled and cfg.websocket_url:
            self._safe("websocket", lambda: self._send_websocket(body))
        if cfg.tcp_enabled and cfg.tcp_host:
            self._safe("tcp", lambda: self._send_tcp(body))
        if cfg.udp_enabled and cfg.udp_host:
            self._safe("udp", lambda: self._send_udp(body))
        if cfg.modbus_enabled and cfg.modbus_host:
            self._safe("modbus", lambda: self._send_modbus(payload))

    def _safe(self, protocol: str, send: Callable[[], None]) -> None:
        try:
            send()
        except Exception as exc:
            self._log(f"Inference {protocol} output failed: {exc}")

    def _send_mqtt(self, body: bytes) -> None:
        cfg = self._config
        if self._mqtt_client is None:
            import paho.mqtt.client as mqtt  # type: ignore[import-not-found]

            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            client.connect(cfg.mqtt_host, cfg.mqtt_port, 60)
            client.loop_start()
            self._mqtt_client = client
        self._mqtt_client.publish(cfg.mqtt_topic, body.decode("utf-8"), qos=1)

    def _close_mqtt(self) -> None:
        client = self._mqtt_client
        self._mqtt_client = None
        if client is None:
            return
        try:
            client.loop_stop()
            client.disconnect()
        except Exception:
            pass

    def _send_http(self, body: bytes) -> None:
        request = urllib.request.Request(
            self._config.http_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=2.0) as response:
            response.read(1)

    def _send_websocket(self, body: bytes) -> None:
        import websocket  # type: ignore[import-not-found]

        ws = websocket.create_connection(self._config.websocket_url, timeout=2.0)
        try:
            ws.send(body.decode("utf-8"))
        finally:
            ws.close()

    def _send_tcp(self, body: bytes) -> None:
        with socket.create_connection((self._config.tcp_host, self._config.tcp_port), timeout=2.0) as sock:
            sock.sendall(body + b"\n")

    def _send_udp(self, body: bytes) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(2.0)
            sock.sendto(body, (self._config.udp_host, self._config.udp_port))

    def _send_modbus(self, payload: dict) -> None:
        cfg = self._config
        detections = payload.get("detections")
        count = len(detections) if isinstance(detections, list) else 0
        active = count > 0
        try:
            from pymodbus.client import ModbusTcpClient  # type: ignore[import-not-found]
        except Exception as exc:
            raise RuntimeError("install pymodbus to enable Modbus TCP output") from exc

        client = ModbusTcpClient(cfg.modbus_host, port=cfg.modbus_port, timeout=2.0)
        try:
            if not client.connect():
                raise RuntimeError(f"cannot connect to {cfg.modbus_host}:{cfg.modbus_port}")
            try:
                client.write_register(cfg.modbus_count_register, count, slave=cfg.modbus_unit_id)
                client.write_coil(cfg.modbus_active_coil, active, slave=cfg.modbus_unit_id)
            except TypeError:
                client.write_register(cfg.modbus_count_register, count, unit=cfg.modbus_unit_id)
                client.write_coil(cfg.modbus_active_coil, active, unit=cfg.modbus_unit_id)
        finally:
            client.close()


def inference_payload_from_frame(frame: Mapping[str, object], *, camera_id: str) -> dict:
    detections = frame.get("detections")
    if not isinstance(detections, list):
        detections = []
    return {
        "timestamp": time.time(),
        "camera_id": camera_id,
        "source": frame.get("source", ""),
        "source_label": frame.get("source_label", ""),
        "simulation": bool(frame.get("simulation", False)),
        "frame_size": frame.get("frame_size"),
        "detections": detections,
    }
