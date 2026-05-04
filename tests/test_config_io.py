from pathlib import Path

import pytest

from core.config_io import (
    ConfigBundle,
    export_csv,
    export_json,
    export_yaml,
    filter_known_labels,
    import_text,
    read_path,
    write_path,
)


def make_bundle() -> ConfigBundle:
    return ConfigBundle(
        cameras={"1": ["barril", "tapa"]},
        gpios={"3": {"barril": "GPIO12", "tapa": "GPIO13"}},
    )


def test_yaml_round_trip():
    bundle = make_bundle()
    text = export_yaml(bundle)
    parsed = import_text(text, suffix=".yaml")
    assert parsed.cameras == bundle.cameras
    assert parsed.gpios == bundle.gpios


def test_json_round_trip():
    bundle = make_bundle()
    parsed = import_text(export_json(bundle), suffix=".json")
    assert parsed.cameras == bundle.cameras
    assert parsed.gpios == bundle.gpios


def test_csv_round_trip():
    bundle = make_bundle()
    parsed = import_text(export_csv(bundle), suffix=".csv")
    assert parsed.cameras == bundle.cameras
    assert parsed.gpios == bundle.gpios


def test_import_text_rejects_non_dict():
    with pytest.raises(ValueError):
        import_text("- just-a-list", suffix=".yaml")


def test_filter_known_labels_drops_unknowns():
    bundle = make_bundle()
    bundle.cameras["1"].append("ghost")
    bundle.gpios["3"]["ghost"] = "GPIO99"
    cleaned, ignored = filter_known_labels(bundle, known=["barril", "tapa"])
    assert "ghost" not in cleaned.cameras["1"]
    assert "ghost" not in cleaned.gpios["3"]
    assert ignored == ["ghost"]


def test_write_path_picks_format_by_suffix(tmp_path: Path):
    bundle = make_bundle()
    yaml_path = tmp_path / "out.yaml"
    json_path = tmp_path / "out.json"
    csv_path = tmp_path / "out.csv"
    write_path(yaml_path, bundle)
    write_path(json_path, bundle)
    write_path(csv_path, bundle)

    assert read_path(yaml_path).cameras == bundle.cameras
    assert read_path(json_path).gpios == bundle.gpios
    assert read_path(csv_path).cameras == bundle.cameras
