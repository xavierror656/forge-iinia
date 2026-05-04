from pathlib import Path

from core.settings import Settings


def test_os_environ_overrides_env_file(tmp_path: Path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("FORGE_URL=https://from-file.test/\n", encoding="utf-8")
    monkeypatch.setenv("FORGE_URL", "https://from-environ.test/")
    settings = Settings.load(env_file)
    assert settings.forge_url == "https://from-environ.test/"


def test_local_env_overrides_main_env(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("FORGE_URL=https://main.test/\n", encoding="utf-8")
    local_file = tmp_path / ".env.local"
    local_file.write_text("FORGE_URL=https://local.test/\n", encoding="utf-8")
    settings = Settings.load(env_file)
    assert settings.forge_url == "https://local.test/"


def test_local_env_does_not_have_to_exist(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("FORGE_URL=https://only.test/\n", encoding="utf-8")
    settings = Settings.load(env_file)
    assert settings.forge_url == "https://only.test/"


def test_validate_flags_missing_credentials_when_not_simulating(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SIMULATION_MODE=false\nFORGE_URL=https://x.test/\n",
        encoding="utf-8",
    )
    problems = Settings.load(env_file).validate()
    assert any("credentials" in p for p in problems)


def test_validate_passes_in_simulation_with_no_credentials(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("SIMULATION_MODE=true\n", encoding="utf-8")
    assert Settings.load(env_file).validate() == []


def test_validate_rejects_negative_gpio_pulse(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("GPIO_PULSE_SECONDS=-1\n", encoding="utf-8")
    problems = Settings.load(env_file).validate()
    assert any("GPIO_PULSE_SECONDS" in p for p in problems)


def test_validate_rejects_zero_watchdog_timeout(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("WATCHDOG_TIMEOUT_SECONDS=0\n", encoding="utf-8")
    problems = Settings.load(env_file).validate()
    assert any("WATCHDOG_TIMEOUT_SECONDS" in p for p in problems)


def test_hardware_override_accepted(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("HARDWARE_OVERRIDE=jetson\n", encoding="utf-8")
    assert Settings.load(env_file).hardware_override == "jetson"


def test_unknown_hardware_override_falls_back_to_default(tmp_path: Path, caplog):
    env_file = tmp_path / ".env"
    env_file.write_text("HARDWARE_OVERRIDE=banana\n", encoding="utf-8")
    settings = Settings.load(env_file)
    assert settings.hardware_override == ""


def test_operational_constants_are_typed(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GPIO_PULSE_SECONDS=0.25\n"
        "GPIO_DEDUPE_SECONDS=0.5\n"
        "HTTP_RETRY_ATTEMPTS=7\n"
        "WATCHDOG_TIMEOUT_SECONDS=4.5\n",
        encoding="utf-8",
    )
    settings = Settings.load(env_file)
    assert settings.gpio_pulse_seconds == 0.25
    assert settings.gpio_dedupe_seconds == 0.5
    assert settings.http_retry_attempts == 7
    assert settings.watchdog_timeout_seconds == 4.5


def test_garbage_numeric_values_fall_back_to_defaults(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("GPIO_PULSE_SECONDS=not-a-number\n", encoding="utf-8")
    assert Settings.load(env_file).gpio_pulse_seconds == 0.1


def test_unknown_edgevision_keys_are_warned_about(tmp_path: Path, caplog):
    env_file = tmp_path / ".env"
    env_file.write_text("FORGE_URLZ=typo-here\nUNRELATED_KEY=ignored\n", encoding="utf-8")
    with caplog.at_level("WARNING", logger="core.settings"):
        Settings.load(env_file)
    # FORGE_URLZ should produce a warning; UNRELATED_KEY shouldn't.
    assert any("FORGE_URLZ" in record.message for record in caplog.records)
    assert not any("UNRELATED_KEY" in record.message for record in caplog.records)


def test_capture_path_and_model_path_helpers(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("MODEL_DIR=/opt/m\nCAPTURE_DIR=/opt/c\n", encoding="utf-8")
    settings = Settings.load(env_file)
    assert settings.model_path == Path("/opt/m")
    assert settings.capture_path == Path("/opt/c")
