import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication

from core.hardware_manager import HardwareManager
from core.settings import Settings
from main import MainWindow


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.mark.parametrize(
    "kind,expected_profile",
    [("jetson", "multi"), ("raspberry", "single"), ("development", "desktop")],
)
def test_main_window_builds_per_profile(qapp, kind, expected_profile):
    hw = HardwareManager(forced_kind=kind)
    settings = Settings(simulation_mode=True)
    window = MainWindow(hw, settings)
    try:
        assert hw.ui_profile == expected_profile
        assert window.video_widget is not None
        assert hasattr(window, "_tiles")
        assert window._tiles
        assert window.video_widget is window._tiles[0]
    finally:
        window.shutdown()
        window.deleteLater()


def test_single_profile_collapses_sidebar(qapp):
    hw = HardwareManager(forced_kind="raspberry")
    window = MainWindow(hw, Settings(simulation_mode=True))
    try:
        assert window._live_splitter.childrenCollapsible()
        sizes = window._live_splitter.sizes()
        assert sizes[1] == 0
    finally:
        window.shutdown()
        window.deleteLater()


def test_settings_panel_hides_rtsp_in_single():
    from ui.settings_panel import SettingsPanel

    panel = SettingsPanel(ui_profile="single")
    try:
        assert not panel.rtsp_box.isVisibleTo(panel)
        kinds = [panel.source_mode.itemData(i) for i in range(panel.source_mode.count())]
        assert "rtsp" not in kinds
    finally:
        panel.deleteLater()
