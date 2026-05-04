import json
from pathlib import Path
from unittest.mock import patch

from core import config_store


def test_load_gpio_assignments_filters_invalid_entries(tmp_path: Path):
    payload = {
        "3": {"barril": "GPIO12", "": "GPIO13", "tapa": ""},
        "4": "not-a-mapping",
        "5": {"valido": "GPIO20"},
    }
    target = tmp_path / "forge_gpio_assignments.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    with patch.object(config_store, "GPIO_ASSIGNMENTS_PATH", target):
        loaded = config_store.load_gpio_assignments()
    assert loaded == {"3": {"barril": "GPIO12"}, "5": {"valido": "GPIO20"}}


def test_save_gpio_assignments_is_atomic(tmp_path: Path):
    target = tmp_path / "forge_gpio_assignments.json"
    with patch.object(config_store, "GPIO_ASSIGNMENTS_PATH", target):
        config_store.save_gpio_assignments({"3": {"a": "GPIO1"}})
    parsed = json.loads(target.read_text(encoding="utf-8"))
    assert parsed == {"3": {"a": "GPIO1"}}
    siblings = list(target.parent.iterdir())
    assert siblings == [target]


def test_read_json_returns_empty_dict_on_missing_or_bad_file(tmp_path: Path):
    missing = tmp_path / "missing.json"
    assert config_store.read_json(missing) == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not-valid-json", encoding="utf-8")
    assert config_store.read_json(bad) == {}
    not_dict = tmp_path / "list.json"
    not_dict.write_text("[1, 2, 3]", encoding="utf-8")
    assert config_store.read_json(not_dict) == {}
