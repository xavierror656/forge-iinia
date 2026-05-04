import os
import subprocess
import sys
from pathlib import Path


def test_headless_runs_to_completion():
    repo = Path(__file__).resolve().parent.parent
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(
        [sys.executable, "main.py", "--headless"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "EdgeVision Control Hub headless mode" in result.stdout
    assert "Cycle 3:" in result.stdout
