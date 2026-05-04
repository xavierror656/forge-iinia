from core.hardware_manager import HardwareManager


def test_jetson_uses_multi_ui_profile():
    hw = HardwareManager(forced_kind="jetson")
    assert hw.ui_profile == "multi"
    assert hw.info.ui_profile == "multi"


def test_raspberry_uses_single_ui_profile():
    hw = HardwareManager(forced_kind="raspberry")
    assert hw.ui_profile == "single"
    assert hw.info.ui_profile == "single"


def test_development_uses_desktop_ui_profile():
    hw = HardwareManager(forced_kind="development")
    assert hw.ui_profile == "desktop"
    assert hw.info.ui_profile == "desktop"


def test_force_simulation_lands_on_desktop():
    hw = HardwareManager(force_simulation=True)
    assert hw.ui_profile == "desktop"
    assert hw.is_simulation()
