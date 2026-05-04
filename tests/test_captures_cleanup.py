import time
from pathlib import Path

from core.captures_cleanup import cleanup_captures


def _touch(path: Path, *, size: int, mtime: float) -> Path:
    path.write_bytes(b"x" * size)
    import os

    os.utime(path, (mtime, mtime))
    return path


def test_cleanup_returns_zero_on_missing_dir(tmp_path: Path):
    removed, freed = cleanup_captures(tmp_path / "does-not-exist")
    assert removed == 0
    assert freed == 0


def test_files_older_than_max_age_are_removed(tmp_path: Path):
    now = 10_000_000.0
    old = _touch(tmp_path / "old.png", size=50, mtime=now - 60 * 60 * 24 * 60)  # 60 days old
    new = _touch(tmp_path / "new.png", size=50, mtime=now - 60 * 60 * 24)  # 1 day old
    removed, freed = cleanup_captures(
        tmp_path,
        max_total_bytes=10_000_000,
        max_age_seconds=60 * 60 * 24 * 30,
        now=now,
    )
    assert not old.exists()
    assert new.exists()
    assert removed == 1
    assert freed == 50


def test_total_size_cap_evicts_oldest_first(tmp_path: Path):
    now = 1_000_000.0
    a = _touch(tmp_path / "a.png", size=400, mtime=now - 100)
    b = _touch(tmp_path / "b.png", size=400, mtime=now - 50)
    c = _touch(tmp_path / "c.png", size=400, mtime=now - 10)
    removed, freed = cleanup_captures(
        tmp_path,
        max_total_bytes=500,
        max_age_seconds=60 * 60 * 24 * 365 * 10,
        now=now,
    )
    assert not a.exists()
    assert not b.exists()
    assert c.exists()
    assert removed == 2
    assert freed == 800


def test_audit_log_files_are_protected(tmp_path: Path):
    now = 1_000_000.0
    audit = _touch(tmp_path / "events.jsonl", size=400, mtime=now - 60 * 60 * 24 * 365)
    audit_rot = _touch(tmp_path / "events.jsonl.1", size=400, mtime=now - 60 * 60 * 24 * 365)
    capture = _touch(tmp_path / "component_1.png", size=400, mtime=now - 60 * 60 * 24 * 365)
    cleanup_captures(
        tmp_path,
        max_total_bytes=0,
        max_age_seconds=0,
        now=now,
    )
    assert audit.exists()
    assert audit_rot.exists()
    assert not capture.exists()
