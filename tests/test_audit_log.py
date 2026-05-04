import json
import threading
from pathlib import Path

from core.audit_log import AuditLog


def test_record_appends_jsonl_with_required_fields(tmp_path: Path):
    log = AuditLog(tmp_path / "events.jsonl")
    log.record(
        kind="gpio",
        label="barril",
        active=True,
        port="GPIO12",
        camera_id="3",
        score=0.92,
        frame_id=42,
    )
    log.record(kind="gpio", label="barril", active=False, port="GPIO12", camera_id="3")

    lines = (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["label"] == "barril"
    assert first["active"] is True
    assert first["port"] == "GPIO12"
    assert first["score"] == 0.92
    assert first["frame_id"] == 42
    assert isinstance(first["ts"], float)


def test_read_all_skips_corrupt_lines(tmp_path: Path):
    target = tmp_path / "events.jsonl"
    target.write_text(
        '{"ts":1, "label":"x", "active":true}\n'
        "not-json-at-all\n"
        '{"ts":2, "label":"y", "active":false}\n',
        encoding="utf-8",
    )
    rows = AuditLog(target).read_all()
    assert [r["label"] for r in rows] == ["x", "y"]


def test_concurrent_writes_do_not_interleave(tmp_path: Path):
    log = AuditLog(tmp_path / "events.jsonl")

    def writer(label: str) -> None:
        for i in range(50):
            log.record(kind="gpio", label=label, active=bool(i % 2))

    threads = [threading.Thread(target=writer, args=(f"lab{i}",)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    rows = log.read_all()
    assert len(rows) == 4 * 50
    # Each line must be valid JSON — i.e. no torn/interleaved writes.
    for row in rows:
        assert "label" in row and "active" in row
