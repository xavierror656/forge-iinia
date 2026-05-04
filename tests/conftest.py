import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


_MANAGED_ENV_PREFIXES = ("EDGEVISION_", "FORGE_")
_MANAGED_ENV_KEYS = (
    "MODEL_DIR",
    "CAPTURE_DIR",
    "SIMULATION_MODE",
    "HARDWARE_OVERRIDE",
    "LOG_DIR",
    "GPIO_PULSE_SECONDS",
    "GPIO_DEDUPE_SECONDS",
    "HTTP_RETRY_ATTEMPTS",
    "WATCHDOG_TIMEOUT_SECONDS",
)


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """Strip env vars the app reads so tests start from a clean slate."""
    for key in list(os.environ):
        if key in _MANAGED_ENV_KEYS or any(key.startswith(p) for p in _MANAGED_ENV_PREFIXES):
            monkeypatch.delenv(key, raising=False)
    yield
