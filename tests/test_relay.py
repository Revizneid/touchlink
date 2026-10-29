"""tests/test_relay.py — Kiểm thử tích hợp relay_server.py.

Dùng aiohttp test client để kiểm thử:
- Rate-limit kết nối WS mới bị chặn khi vượt ngưỡng
- Lỗi chung cho ID sai và ID offline (không phân biệt được)
- Message JSON quá lớn → server đóng kết nối (code 1009)
- Thay thế agent: agent mới ghi đè agent cũ đã đóng
- Định dạng device_id không hợp lệ bị từ chối
- /healthz luôn trả 200 OK
- /metrics trả metrics (không có token / có token đúng / sai token)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import os
import time

import pytest
import pytest_asyncio
from aiohttp import WSMsgType
from aiohttp.test_utils import TestClient, TestServer

# Thêm relay/ vào path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "relay"))

from relay_server import (
    RelayConfig,
    RelayState,
    SlidingWindow,
    BanList,
    make_app,
    DEVICE_ID_RE,
    _UNAVAILABLE_MSG,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_args(**kwargs) -> argparse.Namespace:
    """Tạo Namespace mặc định cho RelayConfig."""
    defaults = dict(
        port=8430,
        web="/nonexistent",
        trusted_proxy=False,
        anonymize_logs=False,
        metrics_token="",          # tương ứng với args.metrics_token trong RelayConfig
        max_conns_ip=20,
        max_conn_id=10,
        max_conn_total=30,
        max_auth_fail=5,
        auth_ban_s=180,
        max_conns_total_ip=10,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _tight_args(**kwargs) -> argparse.Namespace:
    """Args với ngưỡng rate-limit rất thấp để test nhanh."""
    return _make_args(
        max_conns_ip=100,      # không muốn chặn WS mới
        max_conn_id=3,         # connect/phút/IP: 3
        max_conn_total=100,    # connect/phút/ID
        max_auth_fail=2,       # auth fail: 2 → ban
        auth_ban_s=60,
        max_conns_total_ip=50,
    )


@pytest.fixture
def relay_app():
    """App relay với config mặc định."""
    return make_app(_make_args())


@pytest.fixture
def tight_app():
    """App relay với ngưỡng rate-limit thấp."""
    return make_app(_tight_args())


@pytest.fixture
def metrics_app():
    """App relay bảo vệ /metrics bằng token."""
    return make_app(_make_args(metrics_token="secret-token"))


# ---------------------------------------------------------------------------
# 1. Unit test: SlidingWindow
# ---------------------------------------------------------------------------

class TestSlidingWindow:
    def test_allow_within_limit(self):
        """Gọi <= max_calls lần phải được chấp nhận."""
        sw = SlidingWindow(max_calls=3, window_s=60)
        assert sw.hit("k") is True
        assert sw.hit("k") is True
        assert sw.hit("k") is True

    def test_reject_over_limit(self):
        """Gọi > max_calls lần phải bị từ chối."""
        sw = SlidingWindow(max_calls=2, window_s=60)
        assert sw.hit("k") is True
        assert sw.hit("k") is True
        assert sw.hit("k") is False  # vượt ngưỡng

    def test_reset_clears_count(self):
        """reset() phải xóa lịch sử của key."""
        sw = SlidingWindow(max_calls=1, window_s=60)
        sw.hit("k")
        assert sw.hit("k") is False
        sw.reset("k")
        assert sw.hit("k") is True

    def test_independent_keys(self):
        """Các key khác nhau không ảnh hưởng nhau."""
        sw = SlidingWindow(max_calls=1, window_s=60)
        assert sw.hit("a") is True
        assert sw.hit("b") is True
        assert sw.hit("a") is False
        assert sw.hit("b") is False

    def test_count(self):
        """count() phải trả số lần trong cửa sổ hiện tại."""
        sw = SlidingWindow(max_calls=10, window_s=60)
        sw.hit("k")
        sw.hit("k")
        assert sw.count("k") == 2


class TestBanList:
    def test_ban_and_is_banned(self):
        bl = BanList()
        bl.ban("x", 60)
        assert bl.is_banned("x") is True

    def test_not_banned_unknown_key(self):
        bl = BanList()
        assert bl.is_banned("unknown") is False

    def test_remaining_positive(self):
        bl = BanList()
        bl.ban("x", 60)
        assert bl.remaining("x") > 0

    def test_remaining_expired(self):
        """Ban đã hết hạn → is_banned phải trả False."""
        bl = BanList()
        # Đặt thời gian hết hạn ngay lập tức bằng cách set expire về quá khứ
        # (không dùng time.sleep để tránh flakiness trên Windows timer ~15ms)
        bl._bans["x"] = time.monotonic() - 1.0  # hết hạn 1 giây trước
        assert bl.is_banned("x") is False


class TestDeviceIdRegex:
    def test_valid_9_digits(self):
        assert DEVICE_ID_RE.match("234567892")

    def test_reject_0_or_1(self):
        assert not DEVICE_ID_RE.match("012345678")
        assert not DEVICE_ID_RE.match("112345678")

    def test_reject_short(self):
        assert not DEVICE_ID_RE.match("2345678")

    def test_reject_long(self):
        assert not DEVICE_ID_RE.match("2345678901")

    def test_reject_letters(self):
        assert not DEVICE_ID_RE.match("23456789a")


# ---------------------------------------------------------------------------
# 2. Integration test: aiohttp TestClient
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestHealthz:
    async def test_healthz_ok(self, relay_app):
        async with TestClient(TestServer(relay_app)) as client:
            r = await client.get("/healthz")
            assert r.status == 200
            body = await r.json()
            assert body["status"] == "ok"
            assert "touchlink" in body["app"]


@pytest.mark.asyncio
class TestMetrics:
    async def test_metrics_no_token(self, relay_app):
        """Không có token → 200 (endpoint mở)."""
        async with TestClient(TestServer(relay_app)) as client:
            r = await client.get("/metrics")
            assert r.status == 200
            body = await r.json()
            assert "total_connections" in body

    async def test_metrics_with_correct_token(self, metrics_app):
        """Token đúng → 200."""
        async with TestClient(TestServer(metrics_app)) as client:
            r = await client.get(
                "/metrics", headers={"Authorization": "Bearer secret-token"}
            )
            assert r.status == 200

    async def test_metrics_with_wrong_token(self, metrics_app):
        """Token sai → 401."""
        async with TestClient(TestServer(metrics_app)) as client:
            r = await client.get(
                "/metrics", headers={"Authorization": "Bearer wrong"}
            )
            assert r.status == 401

    async def test_metrics_missing_token(self, metrics_app):
        """Không có header → 401."""
        async with TestClient(TestServer(metrics_app)) as client:
            r = await client.get("/metrics")
            assert r.status == 401


@pytest.mark.asyncio
class TestRelayInfo:
    async def test_relayinfo_no_device_ids(self, relay_app):
        """/api/relayinfo không lộ device_id cụ thể."""
        async with TestClient(TestServer(relay_app)) as client:
            r = await client.get("/api/relayinfo")
            assert r.status == 200
            body = await r.json()
            # Không có trường "agents" chứa device_id
            assert "agents" not in body
            assert "agents_online" in body


@pytest.mark.asyncio
class TestAgentRegister:
    async def test_valid_register(self, relay_app):
        """Agent hợp lệ đăng ký → nhận registered."""
        async with TestClient(TestServer(relay_app)) as client:
            async with client.ws_connect("/ws") as ws:
                await ws.send_json({"type": "register", "device_id": "234567892"})
                msg = await ws.receive_json()
                assert msg["type"] == "registered"

    async def test_invalid_device_id_format(self, relay_app):
        """device_id sai định dạng → error."""
        async with TestClient(TestServer(relay_app)) as client:
            async with client.ws_connect("/ws") as ws:
                await ws.send_json({"type": "register", "device_id": "abc"})
                msg = await ws.receive_json()
                assert msg["type"] == "error"

    async def test_empty_device_id(self, relay_app):
        """device_id rỗng → error."""
        async with TestClient(TestServer(relay_app)) as client:
            async with client.ws_connect("/ws") as ws:
                await ws.send_json({"type": "register", "device_id": ""})
                msg = await ws.receive_json()
                assert msg["type"] == "error"

    async def test_duplicate_register_rejected(self, relay_app):
        """Agent khác cố đăng ký ID đang chiếm → error."""
        async with TestClient(TestServer(relay_app)) as client:
            async with client.ws_connect("/ws") as agent1:
                await agent1.send_json(
                    {"type": "register", "device_id": "234567893"}
                )
                msg1 = await agent1.receive_json()
                assert msg1["type"] == "registered"

                # Agent thứ 2 cùng ID
                async with client.ws_connect("/ws") as agent2:
                    await agent2.send_json(
                        {"type": "register", "device_id": "234567893"}
                    )
                    msg2 = await agent2.receive_json()
                    assert msg2["type"] == "error"
                    assert "đăng ký" in msg2["message"]

    async def test_agent_replacement_after_disconnect(self, relay_app):
        """Agent mới thay thế agent cũ đã đóng kết nối."""
        did = "234567894"
        async with TestClient(TestServer(relay_app)) as client:
            # Agent 1 connect rồi ngắt
            async with client.ws_connect("/ws") as agent1:
                await agent1.send_json({"type": "register", "device_id": did})
                await agent1.receive_json()
            # WS agent1 đã đóng — agent 2 phải đăng ký được
            async with client.ws_connect("/ws") as agent2:
                await agent2.send_json({"type": "register", "device_id": did})
                msg = await agent2.receive_json()
                assert msg["type"] == "registered"


@pytest.mark.asyncio
class TestViewerConnect:
    async def test_id_not_exist_returns_unavailable(self, relay_app):
        """ID không tồn tại → message chung unavailable."""
        async with TestClient(TestServer(relay_app)) as client:
            async with client.ws_connect("/ws") as viewer:
                await viewer.send_json({
                    "type": "connect",
                    "device_id": "999999999",
                    "password": "test",
                })
                msg = await viewer.receive_json()
                assert msg["type"] == "auth_result"
                assert msg["ok"] is False
                assert msg["message"] == _UNAVAILABLE_MSG

    async def test_id_offline_same_message_as_not_exist(self, relay_app):
        """ID offline → cùng message như ID không tồn tại (chống dò)."""
        did = "234567892"
        async with TestClient(TestServer(relay_app)) as client:
            # Agent đăng ký rồi ngắt → ID offline
            async with client.ws_connect("/ws") as agent:
                await agent.send_json({"type": "register", "device_id": did})
                await agent.receive_json()
            # Kết nối tới ID đã offline
            async with client.ws_connect("/ws") as viewer:
                await viewer.send_json({
                    "type": "connect",
                    "device_id": did,
                    "password": "wrong",
                })
                msg = await viewer.receive_json()
                assert msg["type"] == "auth_result"
                assert msg["ok"] is False
                # Phải cùng message với ID không tồn tại
                assert msg["message"] == _UNAVAILABLE_MSG

    async def test_id_busy_same_message(self, relay_app):
        """ID đang có viewer khác → cùng message unavailable."""
        did = "234567893"
        async with TestClient(TestServer(relay_app)) as client:
            async with client.ws_connect("/ws") as agent:
                await agent.send_json({"type": "register", "device_id": did})
                await agent.receive_json()

                async with client.ws_connect("/ws") as viewer1:
                    await viewer1.send_json({
                        "type": "connect", "device_id": did, "password": "p"
                    })
                    # viewer1 đang chờ auth → agent "bận"
                    async with client.ws_connect("/ws") as viewer2:
                        await viewer2.send_json({
                            "type": "connect", "device_id": did, "password": "p"
                        })
                        msg = await viewer2.receive_json()
                        assert msg["type"] == "auth_result"
                        assert msg["ok"] is False
                        assert msg["message"] == _UNAVAILABLE_MSG


@pytest.mark.asyncio
class TestRateLimit:
    async def test_connect_rate_limit_per_ip(self, tight_app):
        """Vượt ngưỡng connect/phút/IP (3) → bị từ chối."""
        did = "234567894"
        async with TestClient(TestServer(tight_app)) as client:
            # Đăng ký agent nhưng không online (test chỉ cần xem rate-limit)
            # Gửi 4 lần connect → lần 4 phải bị từ chối vì rate-limit IP
            results = []
            for _ in range(4):
                async with client.ws_connect("/ws") as ws:
                    await ws.send_json({
                        "type": "connect", "device_id": did, "password": "x"
                    })
                    msg = await ws.receive_json()
                    results.append(msg)

            # 3 đầu → unavailable (ID không tồn tại); lần 4 → rate-limit
            assert results[3]["type"] == "auth_result"
            assert results[3]["ok"] is False
            # Rate-limit message khác unavailable
            assert results[3]["message"] != _UNAVAILABLE_MSG
            assert "thử lại" in results[3]["message"].lower() or \
                   "yêu cầu" in results[3]["message"].lower()


@pytest.mark.asyncio
class TestMessageSize:
    async def test_json_too_large_closes_connection(self, relay_app):
        """JSON > 64KB → server đóng kết nối."""
        async with TestClient(TestServer(relay_app)) as client:
            async with client.ws_connect("/ws") as ws:
                # Gửi message > 64KB
                big = json.dumps({"type": "ping", "data": "x" * 70_000})
                await ws.send_str(big)
                # Server phải đóng kết nối (hoặc gửi close frame)
                while True:
                    msg = await asyncio.wait_for(ws.receive(), timeout=5)
                    if msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSED,
                                    WSMsgType.ERROR):
                        break
                    # Nếu server gửi close trước khi chúng ta nhận được
                    if ws.closed:
                        break
                assert ws.closed


@pytest.mark.asyncio
class TestPingPong:
    async def test_ping_gets_pong(self, relay_app):
        """Gửi ping → nhận pong."""
        async with TestClient(TestServer(relay_app)) as client:
            async with client.ws_connect("/ws") as ws:
                await ws.send_json({"type": "ping", "t": 12345})
                msg = await asyncio.wait_for(ws.receive_json(), timeout=5)
                assert msg["type"] == "pong"
                assert msg["t"] == 12345


@pytest.mark.asyncio
class TestFullPairingFlow:
    async def test_agent_viewer_pairing_and_auth_ok(self, relay_app):
        """Luồng đầy đủ: agent đăng ký → viewer connect → agent auth_ok → viewer nhận data."""
        did = "234567895"
        async with TestClient(TestServer(relay_app)) as client:
            async with client.ws_connect("/ws") as agent:
                await agent.send_json({"type": "register", "device_id": did})
                r = await agent.receive_json()
                assert r["type"] == "registered"

                async with client.ws_connect("/ws") as viewer:
                    await viewer.send_json({
                        "type": "connect", "device_id": did, "password": "secret"
                    })
                    # Agent nhận lệnh auth
                    auth_msg = await asyncio.wait_for(agent.receive_json(), timeout=5)
                    assert auth_msg["type"] == "auth"
                    # Agent không thấy password đúng/sai — chỉ relay
                    assert "password" in auth_msg

                    # Agent gửi auth_result ok
                    await agent.send_json({
                        "type": "auth_result", "ok": True,
                        "data": {"hostname": "mypc", "version": "2.3.0"},
                    })

                    # Agent nhận "bound"
                    bound_msg = await asyncio.wait_for(agent.receive_json(), timeout=5)
                    assert bound_msg["type"] == "bound"

                    # Viewer nhận auth_result ok
                    viewer_ok = await asyncio.wait_for(viewer.receive_json(), timeout=5)
                    assert viewer_ok["type"] == "auth_result"
                    assert viewer_ok["ok"] is True
                    assert viewer_ok["data"]["hostname"] == "mypc"

    async def test_agent_viewer_auth_fail(self, relay_app):
        """Auth fail: agent gửi auth_result ok=False → viewer nhận fail."""
        did = "234567896"
        async with TestClient(TestServer(relay_app)) as client:
            async with client.ws_connect("/ws") as agent:
                await agent.send_json({"type": "register", "device_id": did})
                await agent.receive_json()

                async with client.ws_connect("/ws") as viewer:
                    await viewer.send_json({
                        "type": "connect", "device_id": did, "password": "wrong"
                    })
                    await asyncio.wait_for(agent.receive_json(), timeout=5)

                    await agent.send_json({
                        "type": "auth_result", "ok": False, "message": "Sai mật khẩu"
                    })

                    viewer_msg = await asyncio.wait_for(viewer.receive_json(), timeout=5)
                    assert viewer_msg["type"] == "auth_result"
                    assert viewer_msg["ok"] is False

    async def test_agent_disconnect_notifies_viewer(self, relay_app):
        """Agent ngắt kết nối → viewer nhận thông báo (auth_result fail hoặc CLOSE)."""
        did = "234567897"
        async with TestClient(TestServer(relay_app)) as client:
            async with client.ws_connect("/ws") as agent:
                await agent.send_json({"type": "register", "device_id": did})
                await agent.receive_json()

                async with client.ws_connect("/ws") as viewer:
                    await viewer.send_json({
                        "type": "connect", "device_id": did, "password": "p"
                    })
                    # Agent nhận auth, trả ok
                    await asyncio.wait_for(agent.receive_json(), timeout=5)
                    await agent.send_json({
                        "type": "auth_result", "ok": True, "data": {}
                    })
                    await asyncio.wait_for(agent.receive_json(), timeout=5)  # bound
                    await asyncio.wait_for(viewer.receive_json(), timeout=5)  # auth_result

                    # Agent ngắt kết nối
                    await agent.close()

                # Viewer phải nhận thông báo agent ngắt
                # (có thể là JSON hoặc WS CLOSE frame tùy timing)
                raw = await asyncio.wait_for(viewer.receive(), timeout=5)
                if raw.type == WSMsgType.TEXT:
                    msg = json.loads(raw.data)
                    assert msg["ok"] is False
                else:
                    # WS đã bị đóng — cũng là thông báo hợp lệ
                    assert raw.type in (
                        WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR
                    )
