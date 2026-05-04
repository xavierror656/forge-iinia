from core.gpio_backend import GpiozeroBackend, MockGPIOBackend, parse_port, select_backend


def test_parse_port_accepts_common_forms():
    assert parse_port("GPIO12") == 12
    assert parse_port("gpio 7") == 7
    assert parse_port("12") == 12
    assert parse_port("PIN5") == 5
    assert parse_port("") is None
    assert parse_port("none") is None


def test_mock_backend_records_pulses():
    mock = MockGPIOBackend()
    assert mock.pulse("GPIO12", 0.0) is True
    assert mock.pulse("GPIO13", 0.0) is True
    assert mock.events == [("GPIO12", 0.0), ("GPIO13", 0.0)]


class _FakeLine:
    def __init__(self, pin: int) -> None:
        self.pin = pin
        self.calls: list[str] = []

    def on(self) -> None:
        self.calls.append("on")

    def off(self) -> None:
        self.calls.append("off")

    def close(self) -> None:
        self.calls.append("close")


def test_gpiozero_backend_drives_lines():
    created: dict[int, _FakeLine] = {}

    def factory(pin: int) -> _FakeLine:
        line = _FakeLine(pin)
        created[pin] = line
        return line

    backend = GpiozeroBackend(output_factory=factory)
    assert backend.available is True
    assert backend.pulse("GPIO12", 0.0) is True
    assert created[12].calls == ["on", "off"]

    backend.pulse("12", 0.0)
    assert created[12].calls == ["on", "off", "on", "off"]

    backend.close()
    assert created[12].calls[-1] == "close"


def test_gpiozero_backend_rejects_bad_port():
    backend = GpiozeroBackend(output_factory=lambda pin: _FakeLine(pin))
    assert backend.pulse("none", 0.0) is False


def test_select_backend_returns_mock_in_simulation():
    backend = select_backend(simulation=True)
    assert backend.name == "mock"
