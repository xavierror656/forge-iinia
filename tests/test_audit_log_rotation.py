from pathlib import Path

from core.audit_log import AuditLog


def test_audit_log_rotates_when_size_exceeded(tmp_path: Path):
    target = tmp_path / "events.jsonl"
    log = AuditLog(target, max_bytes=200, backup_count=2)
    for i in range(20):
        log.record(kind="gpio", label=f"label-{i}", active=True, port="GPIO12")

    rotated_1 = target.with_suffix(".jsonl.1")
    rotated_2 = target.with_suffix(".jsonl.2")
    assert target.exists()
    assert rotated_1.exists()
    assert rotated_2.exists() or not rotated_2.exists()
    assert target.stat().st_size <= 400


def test_audit_log_keeps_at_most_backup_count_files(tmp_path: Path):
    target = tmp_path / "events.jsonl"
    log = AuditLog(target, max_bytes=100, backup_count=2)
    for i in range(50):
        log.record(kind="gpio", label=f"l{i}", active=True)

    extras = sorted(p.name for p in tmp_path.iterdir() if p.name.startswith("events.jsonl"))
    assert "events.jsonl.3" not in extras
