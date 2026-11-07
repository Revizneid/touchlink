import argparse
import pytest
from aiohttp.test_utils import TestClient, TestServer

from desktop.wol import (
    build_magic_packet,
    get_local_mac_address,
    is_valid_mac_address,
    send_magic_packet,
    validate_wake_request,
)
from relay.relay_server import _send_wol_packet, make_app


def test_magic_packet_and_wake_request_validation():
    packet = build_magic_packet("00:11:22:33:44:55")
    assert len(packet) == 6 + 16 * 6
    assert packet[:6] == b"\xff\xff\xff\xff\xff\xff"
    assert is_valid_mac_address("00:11:22:33:44:55") is True
    assert is_valid_mac_address("99:99:99:99:99") is False

    assert validate_wake_request({"target_mac": "00:11:22:33:44:55", "device_id": "123456789", "permission": "wake"}) is True
    assert validate_wake_request({"target_mac": "00:11:22:33:44:55", "device_id": "123456789", "permission": "guest"}) is False
    assert validate_wake_request({"target_mac": "ZZ:ZZ:ZZ:ZZ:ZZ:ZZ", "device_id": "123456789", "permission": "wake"}) is False


def test_get_local_mac_address():
    mac = get_local_mac_address()
    assert is_valid_mac_address(mac) is True
    assert len(mac) == 17
    assert mac.count(":") == 5


def test_send_magic_packet(monkeypatch):
    sent = []

    class DummySocket:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def setsockopt(self, level, optname, value):
            pass

        def sendto(self, data, addr):
            sent.append((data, addr))

    import socket
    monkeypatch.setattr(socket, "socket", DummySocket)
    res = send_magic_packet("00:11:22:33:44:55", broadcast_ip="192.168.1.255", port=9)
    assert res is True
    assert len(sent) == 1
    packet, addr = sent[0]
    assert len(packet) == 102
    assert addr == ("192.168.1.255", 9)

    # Invalid MAC returns False
    assert send_magic_packet("bad-mac") is False


def test_relay_wol_helper(monkeypatch):
    sent = []

    class DummySocket:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def setsockopt(self, level, optname, value):
            pass

        def sendto(self, data, addr):
            sent.append((data, addr))

    import socket
    monkeypatch.setattr(socket, "socket", DummySocket)

    ok = _send_wol_packet("00:11:22:33:44:55")
    assert ok is True
    assert len(sent) == 1
    assert sent[0][1] == ("255.255.255.255", 9)

    assert _send_wol_packet("invalid-mac") is False


@pytest.mark.asyncio
async def test_relay_http_wake_api(monkeypatch):
    monkeypatch.setattr("relay.relay_server._send_wol_packet", lambda *args, **kwargs: True)

    args = argparse.Namespace(
        port=8430,
        max_conns_ip=100,
        max_conn_id=50,
        max_conn_total=100,
        max_auth_fail=5,
        auth_ban_s=180,
        auth_window_s=600,
        pair_timeout_s=30,
        max_conns_total=10,
        metrics_token=None,
        trusted_proxy=False,
        anonymize_logs=False,
        web="",
    )
    app = make_app(args)
    async with TestClient(TestServer(app)) as client:
        # Test POST /api/wake with valid MAC
        resp = await client.post("/api/wake", json={"target_mac": "00:11:22:33:44:55", "device_id": "234567892"})
        assert resp.status == 200
        data = await resp.json()
        assert data["ok"] is True
        assert data["target_mac"] == "00:11:22:33:44:55"

        # Test POST /api/wake with invalid MAC
        bad_resp = await client.post("/api/wake", json={"target_mac": "invalid"})
        assert bad_resp.status == 400

        # Test WebSocket wake_request
        async with client.ws_connect("/ws") as ws:
            await ws.send_json({"type": "wake_request", "target_mac": "00:11:22:33:44:55", "device_id": "234567892"})
            res = await ws.receive_json()
            assert res["type"] == "wake_result"
            assert res["ok"] is True
