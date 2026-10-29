import pytest

from desktop.transport import LanWsTransport, RelayWsTransport, Transport, WebRtcTransport


def test_transport_interface_requires_implementation():
    with pytest.raises(TypeError):
        Transport()


def test_lan_and_relay_transports_expose_basic_api():
    lan = LanWsTransport()
    relay = RelayWsTransport()

    assert lan.start() is True
    assert relay.start() is True

    lan.send_data({"type": "hello"})
    relay.send_data({"type": "hello"})

    assert lan.stats()["transport"] == "lan_ws"
    assert relay.stats()["transport"] == "relay_ws"

    lan.close()
    relay.close()


def test_webrtc_transport_handles_missing_aiortc_cleanly():
    transport = WebRtcTransport()
    assert transport.is_available() is False
    with pytest.raises(RuntimeError):
        transport.start()
