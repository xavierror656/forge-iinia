from pathlib import Path

from core.settings import Settings


def test_defaults_when_env_missing(tmp_path: Path, monkeypatch):
    for key in (
        "FORGE_URL", "FORGE_USERNAME", "FORGE_PASSWORD", "FORGE_TOKEN",
        "MODEL_DIR", "CAPTURE_DIR", "SIMULATION_MODE",
    ):
        monkeypatch.delenv(key, raising=False)
    settings = Settings.load(tmp_path / "missing.env")
    assert settings.forge_url.startswith("https://")
    assert settings.simulation_mode is True
    assert settings.has_forge_credentials is False


def test_env_file_overrides(tmp_path: Path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "FORGE_URL=https://example.test/\n"
        "FORGE_USERNAME=alice\n"
        "FORGE_PASSWORD=secret\n"
        "FORGE_MODEL_URL=https://example.test/model.pt\n"
        "FORGE_MODEL_ASSET_UUID=00000000-0000-0000-0000-000000000000\n"
        "SIMULATION_MODE=false\n"
        "CUSTOM_FLAG=1\n",
        encoding="utf-8",
    )
    for key in ("FORGE_URL", "SIMULATION_MODE"):
        monkeypatch.delenv(key, raising=False)
    settings = Settings.load(env_path)
    assert settings.forge_url == "https://example.test/"
    assert settings.forge_model_url == "https://example.test/model.pt"
    assert settings.forge_model_asset_uuid == "00000000-0000-0000-0000-000000000000"
    assert settings.has_forge_credentials is True
    assert settings.simulation_mode is False
    assert settings.extras.get("CUSTOM_FLAG") == "1"


def test_as_env_dict_is_round_trippable(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("FORGE_URL", raising=False)
    settings = Settings.load(tmp_path / "missing.env")
    flat = settings.as_env_dict()
    assert flat["FORGE_URL"] == settings.forge_url
    assert flat["SIMULATION_MODE"] in {"true", "false"}


def test_output_settings_are_typed(tmp_path: Path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "OUTPUT_MQTT_ENABLED=true\n"
        "OUTPUT_MQTT_HOST=broker.local\n"
        "OUTPUT_MQTT_PORT=1884\n"
        "OUTPUT_MODBUS_ENABLED=true\n"
        "OUTPUT_MODBUS_HOST=plc.local\n"
        "OUTPUT_MODBUS_COUNT_REGISTER=12\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("OUTPUT_MQTT_HOST", raising=False)
    settings = Settings.load(env_path)
    assert settings.output_config.mqtt_enabled is True
    assert settings.output_config.mqtt_host == "broker.local"
    assert settings.output_config.mqtt_port == 1884
    assert settings.output_config.modbus_count_register == 12
    assert "mqtt" in settings.output_config.enabled_protocols()
    assert "modbus" in settings.output_config.enabled_protocols()
