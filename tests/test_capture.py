"""Unit tests cho capture package: TileEngine, dirty-rect, fallback logic.

Chạy::

    pytest tests/test_capture.py -v

Không cần GPU hay màn hình thật — dùng numpy array giả.
"""
from __future__ import annotations

import struct
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

# Thêm desktop/ vào sys.path
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "desktop"))

# ---------------------------------------------------------------------------
# Import module cần test
# ---------------------------------------------------------------------------
from capture.tile_engine import TileEngine, scale_frame, TILE_SIZE_DEFAULT, _HEADER_FMT, _TILE_FMT
from capture.base import Frame, Rect


def _solid_frame(h: int, w: int, color: tuple[int, int, int]) -> np.ndarray:
    """Tạo frame màu solid (H, W, 3) uint8."""
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    arr[:, :] = color
    return arr


def _parse_tile_payload(payload: bytes):
    """Giải mã payload 0x02, trả về (fw, fh, tile_size, tiles=[{tx,ty,jpeg}])."""
    assert payload[0:1] == b"\x02", "Không phải 0x02 frame"
    fw = struct.unpack_from(">H", payload, 1)[0]
    fh = struct.unpack_from(">H", payload, 3)[0]
    tile_size = struct.unpack_from(">H", payload, 5)[0]
    n_tiles = struct.unpack_from(">H", payload, 7)[0]
    offset = 9
    tiles = []
    for _ in range(n_tiles):
        tx = struct.unpack_from(">H", payload, offset)[0]
        ty = struct.unpack_from(">H", payload, offset + 2)[0]
        jlen = struct.unpack_from(">I", payload, offset + 4)[0]
        offset += 8
        jpeg = payload[offset:offset + jlen]
        offset += jlen
        tiles.append({"tx": tx, "ty": ty, "jpeg": jpeg})
    return fw, fh, tile_size, tiles


# ===========================================================================
# Tests TileEngine
# ===========================================================================

class TestTileEngineStatic(unittest.TestCase):
    """Màn hình tĩnh: không gửi gì sau keyframe đầu."""

    def setUp(self):
        self.engine = TileEngine(tile_size=64)

    def test_first_frame_is_keyframe(self):
        """Frame đầu tiên phải là keyframe 0x01."""
        arr = _solid_frame(128, 128, (100, 100, 100))
        payload = self.engine.process(arr, quality=75, force_keyframe=False,
                                       keyframe_interval=60.0)
        self.assertIsNotNone(payload)
        self.assertEqual(payload[0:1], b"\x01", "Frame đầu phải là 0x01")

    def test_static_returns_none(self):
        """Frame giống hệt: process() phải trả None."""
        arr = _solid_frame(128, 128, (200, 50, 50))
        # Gửi keyframe trước
        self.engine.process(arr, quality=75, force_keyframe=True,
                             keyframe_interval=60.0)
        # Frame y hệt → None
        payload = self.engine.process(arr, quality=75, force_keyframe=False,
                                       keyframe_interval=60.0)
        self.assertIsNone(payload, "Màn hình tĩnh phải trả None")

    def test_static_multiple_frames_none(self):
        """5 frame liên tiếp không đổi → tất cả phải là None (sau keyframe)."""
        arr = _solid_frame(64, 64, (0, 128, 255))
        self.engine.process(arr, quality=75, force_keyframe=True,
                             keyframe_interval=60.0)
        for _ in range(5):
            result = self.engine.process(arr, quality=75, force_keyframe=False,
                                          keyframe_interval=60.0)
            self.assertIsNone(result)


class TestTileEngineDirty(unittest.TestCase):
    """Dirty rect: chỉ gửi tile thay đổi."""

    def setUp(self):
        self.engine = TileEngine(tile_size=64)

    def test_changed_tile_detected(self):
        """Thay đổi một tile → payload 0x02 với đúng 1 tile."""
        h, w = 128, 128
        arr1 = _solid_frame(h, w, (10, 10, 10))
        # Keyframe
        self.engine.process(arr1, quality=75, force_keyframe=True,
                             keyframe_interval=60.0)
        # Thay đổi tile góc trên trái (0..63, 0..63)
        arr2 = arr1.copy()
        arr2[0:64, 0:64] = [200, 0, 0]
        payload = self.engine.process(arr2, quality=75, force_keyframe=False,
                                       keyframe_interval=60.0)
        self.assertIsNotNone(payload)
        self.assertEqual(payload[0:1], b"\x02", "Phải là 0x02 tile frame")
        fw, fh, tile_size, tiles = _parse_tile_payload(payload)
        self.assertEqual(fw, w)
        self.assertEqual(fh, h)
        self.assertEqual(len(tiles), 1, "Chỉ có 1 tile thay đổi")
        self.assertEqual(tiles[0]["tx"], 0)
        self.assertEqual(tiles[0]["ty"], 0)

    def test_all_tiles_changed_sends_all(self):
        """Thay đổi toàn bộ frame → tất cả tile được gửi."""
        h, w = 128, 128
        arr1 = _solid_frame(h, w, (0, 0, 0))
        self.engine.process(arr1, quality=75, force_keyframe=True,
                             keyframe_interval=60.0)
        arr2 = _solid_frame(h, w, (255, 255, 255))
        payload = self.engine.process(arr2, quality=75, force_keyframe=False,
                                       keyframe_interval=60.0)
        self.assertIsNotNone(payload)
        fw, fh, tile_size, tiles = _parse_tile_payload(payload)
        # 128/64 = 2 cols × 2 rows = 4 tile
        self.assertEqual(len(tiles), 4)

    def test_partial_dirty(self):
        """Chỉ tile cuối cùng thay đổi."""
        h, w = 128, 128
        arr1 = _solid_frame(h, w, (50, 50, 50))
        self.engine.process(arr1, quality=75, force_keyframe=True,
                             keyframe_interval=60.0)
        arr2 = arr1.copy()
        # Tile bottom-right (64:128, 64:128)
        arr2[64:128, 64:128] = [100, 200, 100]
        payload = self.engine.process(arr2, quality=75, force_keyframe=False,
                                       keyframe_interval=60.0)
        self.assertIsNotNone(payload)
        fw, fh, tile_size, tiles = _parse_tile_payload(payload)
        self.assertEqual(len(tiles), 1)
        self.assertEqual(tiles[0]["tx"], 64)
        self.assertEqual(tiles[0]["ty"], 64)

    def test_dirty_rect_empty_when_static(self):
        """Frame không đổi -> payload None, không phát sinh dirty tile."""
        arr = _solid_frame(128, 128, (32, 64, 96))
        self.engine.process(arr, quality=75, force_keyframe=True,
                             keyframe_interval=60.0)
        self.assertIsNone(
            self.engine.process(arr, quality=75, force_keyframe=False,
                                keyframe_interval=60.0)
        )


class TestTileEngineKeyframe(unittest.TestCase):
    """Keyframe định kỳ và force keyframe."""

    def test_force_keyframe_always_0x01(self):
        """force_keyframe=True phải trả 0x01 dù không có thay đổi."""
        engine = TileEngine(64)
        arr = _solid_frame(64, 64, (1, 2, 3))
        engine.process(arr, quality=75, force_keyframe=True, keyframe_interval=60.0)
        # Gọi lần nữa với force_keyframe
        payload = engine.process(arr, quality=75, force_keyframe=True,
                                  keyframe_interval=60.0)
        self.assertIsNotNone(payload)
        self.assertEqual(payload[0:1], b"\x01")

    def test_keyframe_interval(self):
        """Sau keyframe_interval giây → tự động gửi keyframe dù không đổi."""
        engine = TileEngine(64)
        arr = _solid_frame(64, 64, (10, 20, 30))
        engine.process(arr, quality=75, force_keyframe=True, keyframe_interval=60.0)
        # Giả lập time đã trôi qua: _last_keyframe_t = 0 (đã đặt) → dùng interval=0
        payload = engine.process(arr, quality=75, force_keyframe=False,
                                  keyframe_interval=0.0)  # 0 giây → luôn keyframe
        self.assertIsNotNone(payload)
        self.assertEqual(payload[0:1], b"\x01")

    def test_reset_forces_keyframe(self):
        """reset() → frame kế tiếp là keyframe."""
        engine = TileEngine(64)
        arr = _solid_frame(64, 64, (5, 5, 5))
        engine.process(arr, quality=75, force_keyframe=True, keyframe_interval=60.0)
        engine.process(arr, quality=75, force_keyframe=False,
                        keyframe_interval=60.0)  # None (static)
        engine.reset()
        payload = engine.process(arr, quality=75, force_keyframe=False,
                                  keyframe_interval=60.0)
        self.assertIsNotNone(payload)
        self.assertEqual(payload[0:1], b"\x01")


class TestScaleFrame(unittest.TestCase):
    """scale_frame() trả kích thước đúng."""

    def test_scale_50(self):
        arr = _solid_frame(200, 300, (0, 0, 0))
        result = scale_frame(arr, 50)
        self.assertEqual(result.shape[:2], (100, 150))

    def test_scale_100_noop(self):
        arr = _solid_frame(100, 100, (0, 0, 0))
        result = scale_frame(arr, 100)
        self.assertIs(result, arr, "scale=100 phải trả chính array gốc")


class TestRect(unittest.TestCase):
    """Kiểm tra Rect.union()."""

    def test_union_basic(self):
        r1 = Rect(0, 0, 10, 10)
        r2 = Rect(5, 5, 10, 10)
        u = r1.union(r2)
        self.assertEqual(u.x, 0)
        self.assertEqual(u.y, 0)
        self.assertEqual(u.w, 15)
        self.assertEqual(u.h, 15)

    def test_union_contained(self):
        r1 = Rect(0, 0, 100, 100)
        r2 = Rect(10, 10, 20, 20)
        u = r1.union(r2)
        self.assertEqual(u.x, 0); self.assertEqual(u.y, 0)
        self.assertEqual(u.w, 100); self.assertEqual(u.h, 100)


# ===========================================================================
# Tests Fallback Logic (mock dxcam)
# ===========================================================================

class TestFactoryFallback(unittest.TestCase):
    """make_capturer() rơi về MSS khi DXGI lỗi."""

    def test_fallback_when_dxcam_missing(self):
        """Nếu import dxcam ném ImportError → trả MssCapturer."""
        import importlib
        # Tạm thời ẩn dxcam khỏi sys.modules
        original = sys.modules.get("dxcam", None)
        sys.modules["dxcam"] = None  # type: ignore
        try:
            # Reload factory để trigger import path
            import capture.factory as fmod
            import importlib
            importlib.reload(fmod)
            cap = fmod.make_capturer(prefer_dxgi=True)
            from capture.mss_capturer import MssCapturer
            self.assertIsInstance(cap, MssCapturer)
        finally:
            if original is None:
                sys.modules.pop("dxcam", None)
            else:
                sys.modules["dxcam"] = original

    def test_fallback_when_dxgi_start_raises(self):
        """Nếu dxcam.create() ném lỗi, start() phải raise để core fallback về MSS."""
        from capture.dxgi_capturer import DxgiCapturer
        cap = DxgiCapturer()
        with patch("dxcam.create", side_effect=RuntimeError("driver không hỗ trợ")):
            with self.assertRaises(RuntimeError):
                cap.start(1)

    def test_mss_capturer_smoke(self):
        """MssCapturer.start() / stop() không raise (dù grab() có thể None)."""
        from capture.mss_capturer import MssCapturer
        cap = MssCapturer()
        try:
            cap.start(1)
            # Grab có thể hoạt động hoặc không (CI không có màn hình)
            # Chỉ cần không crash
            cap.stop()
        except Exception as exc:
            self.skipTest("Môi trường không có màn hình: %s" % exc)


# ===========================================================================
# Kịch bản --safe-test: không có màn hình thật
# ===========================================================================

class TestTileEngineNonSquare(unittest.TestCase):
    """Frame không chia đều cho tile size."""

    def test_non_divisible_frame(self):
        """Frame 100x150, tile 64 — padding trong hash, không crash."""
        engine = TileEngine(64)
        arr = np.random.randint(0, 255, (100, 150, 3), dtype=np.uint8)
        payload = engine.process(arr, 75, force_keyframe=True,
                                  keyframe_interval=60.0)
        self.assertIsNotNone(payload)
        self.assertEqual(payload[0:1], b"\x01")

    def test_resolution_change_triggers_keyframe(self):
        """Thay đổi độ phân giải giữa chừng → tự reset → keyframe mới."""
        engine = TileEngine(64)
        arr1 = _solid_frame(128, 128, (0, 0, 0))
        engine.process(arr1, 75, force_keyframe=True, keyframe_interval=60.0)
        # Thay đổi resolution
        arr2 = _solid_frame(64, 64, (0, 0, 0))
        payload = engine.process(arr2, 75, force_keyframe=False,
                                  keyframe_interval=60.0)
        self.assertIsNotNone(payload)
        self.assertEqual(payload[0:1], b"\x01",
                         "Thay đổi kích thước phải gửi keyframe")


if __name__ == "__main__":
    unittest.main()
