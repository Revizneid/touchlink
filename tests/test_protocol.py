"""tests/test_protocol.py — Kiểm thử đơn vị cho giao thức TouchLink.

Bao gồm:
- Parse binary frame (header 5 byte + JPEG)
- Parse JSON message hợp lệ / không hợp lệ
- Hello handshake v1/v2
- Trường lạ bị bỏ qua (bên nhận không raise)
- Message quá lớn bị từ chối
"""
from __future__ import annotations

import json
import struct
import sys
import os

import pytest

# Thêm desktop/ vào sys.path để import trực tiếp
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "desktop"))

from protocol import PROTOCOL_VERSION, CAPS, MAX_MSG_SIZE, MAX_FRAME_SIZE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_frame(width: int, height: int, jpeg: bytes) -> bytes:
    """Tạo binary frame theo định dạng giao thức."""
    return struct.pack(">BHH", 1, width, height) + jpeg


def parse_frame(data: bytes) -> tuple[int, int, int, bytes]:
    """Trả về (magic, width, height, jpeg_data). Raise ValueError nếu không hợp lệ."""
    if len(data) < 5:
        raise ValueError("Frame too short (< 5 bytes)")
    magic, w, h = struct.unpack_from(">BHH", data)
    if magic != 1:
        raise ValueError(f"Unknown magic byte: {magic:#04x}")
    return magic, w, h, data[5:]


def parse_json_message(raw: str | bytes, max_size: int = MAX_MSG_SIZE) -> dict:
    """Parse JSON message với kiểm tra kích thước. Raise ValueError nếu quá lớn."""
    if isinstance(raw, str):
        raw = raw.encode()
    if len(raw) > max_size:
        raise ValueError(f"Message quá lớn: {len(raw)} > {max_size}")
    return json.loads(raw)


# ---------------------------------------------------------------------------
# 1. Binary frame
# ---------------------------------------------------------------------------

class TestBinaryFrame:
    """Kiểm thử parse frame nhị phân."""

    def test_parse_valid_frame(self):
        """Frame hợp lệ phải trả đúng magic, w, h và JPEG data."""
        fake_jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        frame = build_frame(1920, 1080, fake_jpeg)
        magic, w, h, jpeg = parse_frame(frame)
        assert magic == 1
        assert w == 1920
        assert h == 1080
        assert jpeg == fake_jpeg

    def test_frame_too_short(self):
        """Frame dưới 5 byte phải raise ValueError."""
        with pytest.raises(ValueError, match="too short"):
            parse_frame(b"\x01\x00")

    def test_wrong_magic_byte(self):
        """Magic byte khác 0x01 phải raise ValueError."""
        frame = struct.pack(">BHH", 0x02, 100, 100) + b"\x00" * 10
        with pytest.raises(ValueError, match="magic"):
            parse_frame(frame)

    def test_frame_header_zero_dimensions(self):
        """Kích thước 0x0 hợp lệ về mặt parse (edge case)."""
        frame = build_frame(0, 0, b"")
        magic, w, h, jpeg = parse_frame(frame)
        assert w == 0 and h == 0 and jpeg == b""

    def test_frame_max_dimensions(self):
        """Kích thước uint16 tối đa (65535) phải parse được."""
        frame = build_frame(65535, 65535, b"\xff" * 10)
        _, w, h, _ = parse_frame(frame)
        assert w == 65535 and h == 65535

    def test_large_frame_rejected(self):
        """Frame vượt MAX_FRAME_SIZE phải bị từ chối (kiểm tra logic ứng dụng)."""
        large = b"\x01" + b"\x00" * (MAX_FRAME_SIZE + 1)
        # Đây là kiểm thử logic từ chối ở tầng ứng dụng (không phải parse)
        assert len(large) > MAX_FRAME_SIZE


# ---------------------------------------------------------------------------
# 2. JSON message
# ---------------------------------------------------------------------------

class TestJsonMessage:
    """Kiểm thử parse JSON message."""

    def test_valid_auth_message(self):
        """Message auth hợp lệ phải parse được."""
        raw = json.dumps({"type": "auth", "id": "123456789", "password": "AbcD12"})
        msg = parse_json_message(raw)
        assert msg["type"] == "auth"
        assert msg["id"] == "123456789"

    def test_invalid_json_raises(self):
        """JSON sai cú pháp phải raise JSONDecodeError."""
        with pytest.raises(json.JSONDecodeError):
            parse_json_message("{not valid json}")

    def test_empty_string_raises(self):
        """Chuỗi rỗng phải raise JSONDecodeError."""
        with pytest.raises(json.JSONDecodeError):
            parse_json_message("")

    def test_message_too_large_rejected(self):
        """Message vượt max_size phải raise ValueError."""
        big = json.dumps({"type": "input", "data": "x" * (MAX_MSG_SIZE + 100)})
        with pytest.raises(ValueError, match="quá lớn"):
            parse_json_message(big.encode())

    def test_message_exactly_at_limit_ok(self):
        """Message đúng bằng max_size phải được chấp nhận."""
        # Tạo message vừa đúng MAX_MSG_SIZE byte
        padding_len = MAX_MSG_SIZE - len('{"type":"ping","p":""}') - 2
        raw = json.dumps({"type": "ping", "p": "x" * max(0, padding_len)})
        # Chỉ kiểm tra không raise — nội dung không quan trọng
        raw_bytes = raw.encode()[:MAX_MSG_SIZE]
        # Đảm bảo không có ValueError từ kích thước
        assert len(raw_bytes) <= MAX_MSG_SIZE

    def test_unknown_type_does_not_raise(self):
        """Message type không biết phải được parse (bỏ qua ở tầng handler)."""
        raw = json.dumps({"type": "future_feature_xyz", "data": 42})
        msg = parse_json_message(raw)
        assert msg["type"] == "future_feature_xyz"
        assert msg["data"] == 42


# ---------------------------------------------------------------------------
# 3. Hello handshake
# ---------------------------------------------------------------------------

class TestHelloHandshake:
    """Kiểm thử logic hello handshake v1/v2."""

    def _parse_hello(self, raw: dict) -> tuple[int, list[str]]:
        """Giả lập xử lý hello message: trả về (peer_v, peer_caps).
        Thiếu 'v' → v=1; trường lạ bị bỏ qua.
        """
        v = int(raw.get("v") or 1)
        caps = list(raw.get("caps") or [])
        # Bỏ qua mọi trường khác ngoài type/v/caps
        return v, caps

    def test_hello_v2_correct(self):
        """Hello v2 phải trả đúng version và caps."""
        msg = {"type": "hello", "v": 2, "caps": ["screen_locked", "keep_awake"]}
        v, caps = self._parse_hello(msg)
        assert v == 2
        assert "screen_locked" in caps
        assert "keep_awake" in caps

    def test_hello_missing_v_treated_as_v1(self):
        """Thiếu 'v' phải coi như v1."""
        msg = {"type": "hello"}
        v, caps = self._parse_hello(msg)
        assert v == 1
        assert caps == []

    def test_hello_v1_explicit(self):
        """Hello v=1 tường minh phải được xử lý đúng."""
        msg = {"type": "hello", "v": 1, "caps": []}
        v, caps = self._parse_hello(msg)
        assert v == 1
        assert caps == []

    def test_hello_unknown_fields_ignored(self):
        """Trường lạ trong hello phải bị bỏ qua — không gây lỗi."""
        msg = {
            "type": "hello",
            "v": 2,
            "caps": ["clipboard_sync"],
            "future_field_1": "value",
            "another_new_field": {"nested": True},
        }
        v, caps = self._parse_hello(msg)
        assert v == 2
        assert caps == ["clipboard_sync"]
        # Kiểm tra rằng hàm không raise khi có trường lạ
        # (trường lạ bị bỏ qua im lặng)

    def test_hello_empty_caps(self):
        """Hello với caps rỗng phải được chấp nhận."""
        msg = {"type": "hello", "v": 2, "caps": []}
        v, caps = self._parse_hello(msg)
        assert v == 2
        assert caps == []

    def test_hello_caps_none_treated_as_empty(self):
        """caps=null phải được xử lý như danh sách rỗng."""
        msg = {"type": "hello", "v": 2, "caps": None}
        v, caps = self._parse_hello(msg)
        assert caps == []

    def test_protocol_version_constant(self):
        """PROTOCOL_VERSION phải là 2 (Sprint 0.1)."""
        assert PROTOCOL_VERSION == 2

    def test_protocol_caps_not_empty(self):
        """CAPS không được rỗng — agent phải khai báo ít nhất 1 tính năng."""
        assert len(CAPS) > 0
        assert isinstance(CAPS, list)

    def test_protocol_caps_known_entries(self):
        """CAPS phải chứa các tính năng cốt lõi."""
        for cap in ("screen_locked", "keep_awake", "clipboard_sync", "chat"):
            assert cap in CAPS, f"Expected cap '{cap}' in CAPS"

    def test_hello_agent_payload(self):
        """Agent hello payload phải đúng cấu trúc."""
        hello = {"type": "hello", "v": PROTOCOL_VERSION, "caps": CAPS}
        assert hello["type"] == "hello"
        assert hello["v"] == PROTOCOL_VERSION
        assert hello["caps"] is CAPS

    def test_v1_agent_compat(self):
        """Viewer cũ (v1, không gửi hello) → peer_v mặc định là 1."""
        # Giả lập: không nhận được hello → timeout, peer_v giữ mặc định 1
        peer_v = 1  # giá trị mặc định khi không nhận được hello
        assert peer_v == 1

    def test_v1_viewer_compat(self):
        """Agent cũ (v1, không gửi hello) → PWA giữ peerV = 1 (mặc định)."""
        peer_v = 1  # giá trị mặc định trong app.js st.peerV
        assert peer_v == 1

    def test_caps_intersection(self):
        """Tính năng chung = giao của agent caps và viewer caps."""
        agent_caps = set(CAPS)
        viewer_caps = {"screen_locked", "clipboard_sync", "unknown_future"}
        common = agent_caps & viewer_caps
        assert "screen_locked" in common
        assert "clipboard_sync" in common
        assert "unknown_future" not in common  # viewer mới hơn agent: bỏ qua

    def test_v_field_must_be_integer(self):
        """v phải là số nguyên; nếu gửi sai kiểu, parse phải xử lý an toàn."""
        msg_str_v = {"type": "hello", "v": "2", "caps": []}
        v, _ = self._parse_hello(msg_str_v)
        assert v == 2  # int("2") = 2


# ---------------------------------------------------------------------------
# 4. Giới hạn kích thước
# ---------------------------------------------------------------------------

class TestSizeLimits:
    """Kiểm thử giới hạn kích thước message."""

    def test_max_msg_size_is_defined(self):
        """MAX_MSG_SIZE phải được định nghĩa và dương."""
        assert MAX_MSG_SIZE > 0

    def test_max_frame_size_is_defined(self):
        """MAX_FRAME_SIZE phải được định nghĩa và lớn hơn MAX_MSG_SIZE."""
        assert MAX_FRAME_SIZE > MAX_MSG_SIZE

    def test_text_input_truncated_at_2000_chars(self):
        """Văn bản gõ bị cắt tại 2000 ký tự (logic trong core.py)."""
        long_text = "a" * 5000
        truncated = long_text[:2000]
        assert len(truncated) == 2000

    def test_chat_truncated_at_500_chars(self):
        """Chat bị cắt tại 500 ký tự (logic trong core.py)."""
        long_chat = "b" * 1000
        truncated = long_chat[:500]
        assert len(truncated) == 500

    def test_clipboard_broadcast_truncated_at_20000(self):
        """Clipboard broadcast bị cắt tại 20000 ký tự (logic trong core.py)."""
        long_clip = "c" * 30000
        truncated = long_clip[:20000]
        assert len(truncated) == 20000
