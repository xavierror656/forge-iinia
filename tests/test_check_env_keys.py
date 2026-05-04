import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_env_keys.py"


def _run_in(workdir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=workdir,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )


def test_passes_when_no_env_present(tmp_path: Path):
    (tmp_path / ".env.example").write_text("FOO=1\nBAR=2\n", encoding="utf-8")
    # No .env file → script should pass.
    (tmp_path / "scripts").mkdir()
    target_script = tmp_path / "scripts" / "check_env_keys.py"
    target_script.write_text(SCRIPT.read_text(), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(target_script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0


def test_fails_when_env_has_extra_key(tmp_path: Path):
    (tmp_path / ".env.example").write_text("FOO=1\n", encoding="utf-8")
    (tmp_path / ".env").write_text("FOO=1\nGHOST=value\n", encoding="utf-8")
    (tmp_path / "scripts").mkdir()
    target_script = tmp_path / "scripts" / "check_env_keys.py"
    target_script.write_text(SCRIPT.read_text(), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(target_script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "GHOST" in result.stderr


def test_fails_when_env_missing_documented_key(tmp_path: Path):
    (tmp_path / ".env.example").write_text("FOO=1\nBAR=2\n", encoding="utf-8")
    (tmp_path / ".env").write_text("FOO=1\n", encoding="utf-8")
    (tmp_path / "scripts").mkdir()
    target_script = tmp_path / "scripts" / "check_env_keys.py"
    target_script.write_text(SCRIPT.read_text(), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(target_script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "BAR" in result.stderr
