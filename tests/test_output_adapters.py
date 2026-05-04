from core.output_adapters import InferenceOutputConfig, inference_payload_from_frame


def test_output_config_enabled_protocols_require_targets():
    config = InferenceOutputConfig.from_mapping(
        {
            "OUTPUT_MQTT_ENABLED": "true",
            "OUTPUT_MQTT_HOST": "broker.local",
            "OUTPUT_HTTP_ENABLED": "true",
            "OUTPUT_HTTP_URL": "",
            "OUTPUT_UDP_ENABLED": "true",
            "OUTPUT_UDP_HOST": "192.168.1.20",
        }
    )
    assert config.enabled_protocols() == ["mqtt", "udp"]


def test_inference_payload_from_frame_is_json_ready():
    payload = inference_payload_from_frame(
        {
            "source": "rtsp://camera/stream",
            "source_label": "Camara 1",
            "simulation": False,
            "frame_size": (1280, 720),
            "detections": [{"label": "person", "confidence": 0.9, "bbox": [1, 2, 3, 4]}],
        },
        camera_id="cam-1",
    )
    assert payload["camera_id"] == "cam-1"
    assert payload["detections"][0]["label"] == "person"
