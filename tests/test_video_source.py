from core.hardware_manager import HardwareManager
from core.video_source import InferenceSourceConfig, resolve_video_source_candidates


def test_raspberry_limits_rtsp_candidates_to_one():
    config = InferenceSourceConfig(
        mode="rtsp",
        rtsp_cameras=[
            {"name": "Cam 1", "url": "rtsp://10.0.0.1/live", "enabled": True},
            {"name": "Cam 2", "url": "rtsp://10.0.0.2/live", "enabled": True},
        ],
    )

    candidates, _discovered = resolve_video_source_candidates(
        config,
        HardwareManager(forced_kind="raspberry"),
    )

    assert [candidate.label for candidate in candidates] == ["Cam 1"]


def test_jetson_keeps_multiple_rtsp_candidates():
    config = InferenceSourceConfig(
        mode="rtsp",
        rtsp_cameras=[
            {"name": "Cam 1", "url": "rtsp://10.0.0.1/live", "enabled": True},
            {"name": "Cam 2", "url": "rtsp://10.0.0.2/live", "enabled": True},
        ],
    )

    candidates, _discovered = resolve_video_source_candidates(
        config,
        HardwareManager(forced_kind="jetson"),
    )

    assert [candidate.label for candidate in candidates] == ["Cam 1", "Cam 2"]


def test_rtsp_backend_prefers_gstreamer_only_on_jetson():
    config = InferenceSourceConfig(
        mode="rtsp",
        rtsp_cameras=[{"name": "Cam 1", "url": "rtsp://10.0.0.1/live", "enabled": True}],
    )

    jetson_candidates, _ = resolve_video_source_candidates(
        config,
        HardwareManager(forced_kind="jetson"),
    )
    raspberry_candidates, _ = resolve_video_source_candidates(
        config,
        HardwareManager(forced_kind="raspberry"),
    )

    assert jetson_candidates[0].backend == "gstreamer"
    assert raspberry_candidates[0].backend == "ffmpeg"
