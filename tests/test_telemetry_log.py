import json
from pathlib import Path

from core.telemetry_log import TelemetryLog


def test_maybe_record_throttles_by_interval(tmp_path: Path):
    log = TelemetryLog(tmp_path / "t.jsonl", interval_seconds=5.0)
    assert log.maybe_record({"fps": 30}, now=1000.0) is True
    assert log.maybe_record({"fps": 31}, now=1002.0) is False
    assert log.maybe_record({"fps": 32}, now=1006.0) is True
    rows = (tmp_path / "t.jsonl").read_text().strip().splitlines()
    assert len(rows) == 2
    parsed = [json.loads(r) for r in rows]
    assert parsed[0]["fps"] == 30
    assert parsed[1]["fps"] == 32


def test_record_always_writes(tmp_path: Path):
    log = TelemetryLog(tmp_path / "t.jsonl", interval_seconds=60.0)
    log.record({"fps": 1}, now=1.0)
    log.record({"fps": 2}, now=1.0)
    rows = (tmp_path / "t.jsonl").read_text().strip().splitlines()
    assert len(rows) == 2


def test_rotation_when_size_exceeded(tmp_path: Path):
    log = TelemetryLog(tmp_path / "t.jsonl", max_bytes=200, backup_count=2, interval_seconds=0.0)
    for i in range(30):
        log.record({"i": i, "padding": "x" * 50})
    files = sorted(p.name for p in tmp_path.iterdir() if p.name.startswith("t.jsonl"))
    assert "t.jsonl" in files
    assert "t.jsonl.1" in files
