from pathlib import Path

from core.hardware_manager import HardwareManager
from core.telemetry import TelemetryCollector


class _TempHardware:
    def __init__(self, source: Path) -> None:
        self.info = HardwareManager(forced_kind="raspberry").info
        self._source = source

    def temperature_sources(self) -> tuple[str, ...]:
        return (str(self._source),)


def test_telemetry_snapshot_reports_fps_latency_and_provider():
    collector = TelemetryCollector(HardwareManager(forced_kind="development"))

    snapshot = collector.snapshot(elapsed_seconds=0.05)

    assert snapshot.capture_fps == 20.0
    assert snapshot.inference_fps == 20.0
    assert snapshot.latency_ms == 50.0
    assert snapshot.provider_name == "Development / Mock"
    assert snapshot.ram_mb >= 0.0


def test_telemetry_reads_millicelsius_temperature(tmp_path: Path):
    temp = tmp_path / "temp"
    temp.write_text("42000\n", encoding="utf-8")
    collector = TelemetryCollector(_TempHardware(temp))  # type: ignore[arg-type]

    assert collector.snapshot(elapsed_seconds=1.0).soc_temp_c == 42.0
