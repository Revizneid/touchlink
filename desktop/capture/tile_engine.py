"""TileEngine — dirty-rect detection và JPEG encoding theo tile.

Thuật toán:
1. Chia frame thành tile NxN (mặc định 128×128).
2. Hash nhanh từng tile bằng numpy (xxhash-like: tổng XOR của uint64 view).
3. So sánh với frame trước → chỉ encode tile thay đổi bằng Pillow JPEG.
4. Trả về:
   - list[EncodedTile] cho frame 0x02 (chỉ tile dirty)
   - None nếu không có tile nào thay đổi (màn hình tĩnh)

Wire format 0x02 (big-endian):
  [1B type=0x02] [2B fw] [2B fh] [2B tile_size] [2B n_tiles]
  per tile: [2B tx] [2B ty] [4B jpeg_len] [jpeg_len B jpeg]
"""
from __future__ import annotations

import io
import struct
import time
from dataclasses import dataclass

import numpy as np
from PIL import Image

# struct format cho header 0x02: type(B), fw(H), fh(H), tile_sz(H), n_tiles(H)
_HEADER_FMT = struct.Struct(">BHHHH")
# struct format mỗi tile: tx(H), ty(H), jpeg_len(I)
_TILE_FMT = struct.Struct(">HHI")

# struct format 0x01 (toàn khung cũ): type(B), fw(H), fh(H)
_FULL_FRAME_HDR = struct.Struct(">BHH")

TILE_SIZE_DEFAULT = 128  # pixel


@dataclass
class EncodedTile:
    """Tile đã được mã hóa JPEG."""

    tx: int          # tọa độ x (pixel trong frame)
    ty: int          # tọa độ y (pixel trong frame)
    jpeg: bytes


class TileEngine:
    """Quản lý dirty-rect và JPEG tile cho một viewer.

    Mỗi viewer có một TileEngine riêng để theo dõi trạng thái frame.
    Giữ hash của các tile frame trước để phát hiện thay đổi.
    """

    def __init__(self, tile_size: int = TILE_SIZE_DEFAULT) -> None:
        self.tile_size = tile_size
        self._prev_hashes: np.ndarray | None = None
        self._prev_shape: tuple[int, int] = (0, 0)
        self._last_keyframe_t: float = 0.0
        self._pad_buf: np.ndarray | None = None

    def reset(self) -> None:
        """Đặt lại trạng thái (dùng khi viewer mới vào hoặc đổi màn hình)."""
        self._prev_hashes = None
        self._prev_shape = (0, 0)
        self._last_keyframe_t = 0.0
        self._pad_buf = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(
        self,
        frame_rgb: np.ndarray,
        quality: int,
        *,
        force_keyframe: bool = False,
        keyframe_interval: float = 10.0,
    ) -> bytes | None:
        """Xử lý một frame, trả về payload nhị phân hoặc None (không thay đổi).

        Args:
            frame_rgb: numpy ndarray RGB shape (H, W, 3).
            quality: Chất lượng JPEG 20..95.
            force_keyframe: Buộc gửi toàn khung dù không có thay đổi.
            keyframe_interval: Gửi keyframe toàn khung sau N giây kể từ lần gần nhất.

        Returns:
            bytes payload (0x01 keyframe hoặc 0x02 tile) hoặc None nếu tĩnh.
        """
        h, w = frame_rgb.shape[:2]
        now = time.monotonic()
        need_keyframe = (
            force_keyframe
            or self._prev_hashes is None
            or self._prev_shape != (h, w)
            or (now - self._last_keyframe_t) >= keyframe_interval
        )

        if need_keyframe:
            self._prev_hashes = self._compute_hashes(frame_rgb)
            self._prev_shape = (h, w)
            self._last_keyframe_t = now
            return self._encode_full(frame_rgb, quality)

        # So sánh tile
        new_hashes = self._compute_hashes(frame_rgb)
        dirty_mask = new_hashes != self._prev_hashes
        n_dirty = int(dirty_mask.sum())

        if n_dirty == 0:
            return None  # màn hình tĩnh

        # Cập nhật hash cho tile dirty
        self._prev_hashes[dirty_mask] = new_hashes[dirty_mask]

        tiles = self._encode_dirty_tiles(frame_rgb, dirty_mask, quality)
        return self._pack_tile_payload(w, h, tiles)

    # ------------------------------------------------------------------
    # Encoding helpers
    # ------------------------------------------------------------------

    def _encode_full(self, frame_rgb: np.ndarray, quality: int) -> bytes:
        """Encode toàn khung thành payload 0x01."""
        h, w = frame_rgb.shape[:2]
        img = Image.fromarray(frame_rgb, "RGB")
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=quality, optimize=False)
        jpeg = buf.getvalue()
        return _FULL_FRAME_HDR.pack(0x01, w, h) + jpeg

    def _encode_dirty_tiles(
        self,
        frame_rgb: np.ndarray,
        dirty_mask: np.ndarray,
        quality: int,
    ) -> list[EncodedTile]:
        """Encode các tile có dirty_mask=True thành JPEG."""
        h, w = frame_rgb.shape[:2]
        ts = self.tile_size
        (w + ts - 1) // ts
        tiles: list[EncodedTile] = []

        # numpy nơi indices của tile dirty
        dirty_rows, dirty_cols = np.where(dirty_mask)
        for ri, ci in zip(dirty_rows.tolist(), dirty_cols.tolist()):
            x0 = ci * ts
            y0 = ri * ts
            x1 = min(x0 + ts, w)
            y1 = min(y0 + ts, h)
            tile_arr = frame_rgb[y0:y1, x0:x1]
            img = Image.fromarray(tile_arr, "RGB")
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=quality, optimize=False)
            tiles.append(EncodedTile(tx=x0, ty=y0, jpeg=buf.getvalue()))
        return tiles

    def _pack_tile_payload(
        self, fw: int, fh: int, tiles: list[EncodedTile]
    ) -> bytes:
        """Đóng gói tile thành payload 0x02."""
        parts: list[bytes] = [
            _HEADER_FMT.pack(0x02, fw, fh, self.tile_size, len(tiles))
        ]
        for t in tiles:
            parts.append(_TILE_FMT.pack(t.tx, t.ty, len(t.jpeg)))
            parts.append(t.jpeg)
        return b"".join(parts)

    # ------------------------------------------------------------------
    # Hash computation
    # ------------------------------------------------------------------

    def _compute_hashes(self, frame_rgb: np.ndarray) -> np.ndarray:
        """Tính hash nhanh và ổn định cho từng tile bằng numpy (vectorized XOR + SUM reduction).

        Thực thi zero-copy trong C của numpy (không lặp Python, không cấp phát bộ nhớ lại),
        đạt tốc độ <1ms cho frame Full HD.

        Returns:
            numpy array shape (rows, cols) dtype uint64.
        """
        h, w = frame_rgb.shape[:2]
        ts = self.tile_size
        rows = (h + ts - 1) // ts
        cols = (w + ts - 1) // ts

        ph = rows * ts
        pw = cols * ts
        if ph != h or pw != w:
            if self._pad_buf is None or self._pad_buf.shape != (ph, pw, 3):
                self._pad_buf = np.zeros((ph, pw, 3), dtype=np.uint8)
            self._pad_buf[:h, :w] = frame_rgb
            padded = self._pad_buf
        else:
            padded = frame_rgb

        r = padded.reshape(rows, ts, cols, ts * 3)
        u32 = r.view(np.uint32)
        x_tile = np.bitwise_xor.reduce(np.bitwise_xor.reduce(u32, axis=3), axis=1)
        s_tile = np.sum(np.sum(u32, axis=3, dtype=np.uint64), axis=1, dtype=np.uint64)
        return (s_tile << np.uint64(32)) ^ x_tile.astype(np.uint64)


def scale_frame(frame_rgb: np.ndarray, scale: int) -> np.ndarray:
    """Co/dãn frame nếu scale < 100.

    Args:
        frame_rgb: numpy array RGB (H, W, 3).
        scale: Phần trăm, 30..100.

    Returns:
        numpy array sau khi resize (hoặc chính frame nếu scale=100).
    """
    if scale >= 100:
        return frame_rgb
    h, w = frame_rgb.shape[:2]
    nw = max(1, w * scale // 100)
    nh = max(1, h * scale // 100)
    img = Image.fromarray(frame_rgb, "RGB")
    resample = getattr(Image, "Resampling", Image).BILINEAR
    img = img.resize((nw, nh), resample)
    return np.array(img)


def unpack_tile_payload(
    payload: bytes,
) -> tuple[int, int, int, dict[tuple[int, int], bytes]]:
    """Giải mã payload 0x02 thành (fw, fh, tile_size, dict[(tx, ty)] = jpeg_bytes).

    Raises:
        ValueError: Nếu payload không đúng định dạng 0x02.
    """
    if len(payload) < _HEADER_FMT.size or payload[0] != 0x02:
        raise ValueError("Payload không phải là 0x02 tile frame")
    _, fw, fh, tile_sz, n_tiles = _HEADER_FMT.unpack_from(payload, 0)
    offset = _HEADER_FMT.size
    tiles: dict[tuple[int, int], bytes] = {}
    for _ in range(n_tiles):
        if offset + _TILE_FMT.size > len(payload):
            raise ValueError("Payload bị cắt cụt ở phần header tile")
        tx, ty, jlen = _TILE_FMT.unpack_from(payload, offset)
        offset += _TILE_FMT.size
        if offset + jlen > len(payload):
            raise ValueError("Payload bị cắt cụt ở phần dữ liệu JPEG")
        tiles[(tx, ty)] = payload[offset:offset + jlen]
        offset += jlen
    return fw, fh, tile_sz, tiles


def merge_tile_payloads(
    payload_old: bytes,
    payload_new: bytes,
    max_tile_ratio: float = 0.6,
) -> bytes | None:
    """Gộp hai payload tile 0x02 khi viewer chậm (drop frame trong mailbox).

    Quy tắc:
    - Nếu payload_old hoặc payload_new không phải 0x02 (ví dụ 0x01 keyframe), trả về None
      để caller xử lý gửi keyframe trực tiếp.
    - Nếu resolution (fw, fh) hoặc tile_size khác nhau, trả về None (ép keyframe).
    - Tile mới ghi đè tile cũ có cùng (tx, ty).
    - Nếu tổng số tile vượt quá max_tile_ratio * total_tiles của màn hình, trả về None
      (để gửi keyframe toàn khung 0x01 hiệu quả hơn).
    - Trả về payload 0x02 đã gộp hoặc None nếu cần ép keyframe.
    """
    if not payload_old:
        return payload_new if payload_new and payload_new[0] == 0x02 else None
    if not payload_new:
        return payload_old if payload_old and payload_old[0] == 0x02 else None
    if payload_old[0] != 0x02 or payload_new[0] != 0x02:
        return None
    try:
        fw1, fh1, ts1, tiles1 = unpack_tile_payload(payload_old)
        fw2, fh2, ts2, tiles2 = unpack_tile_payload(payload_new)
    except Exception:
        return None

    if (fw1, fh1, ts1) != (fw2, fh2, ts2):
        return None

    # Merge: tile mới ghi đè tile cũ
    merged_tiles = dict(tiles1)
    merged_tiles.update(tiles2)

    total_cols = (fw1 + ts1 - 1) // ts1
    total_rows = (fh1 + ts1 - 1) // ts1
    total_possible_tiles = max(1, total_cols * total_rows)

    if len(merged_tiles) > total_possible_tiles * max_tile_ratio:
        return None  # Ép keyframe nếu có quá nhiều tile thay đổi

    encoded_list = [
        EncodedTile(tx=tx, ty=ty, jpeg=jpeg)
        for (tx, ty), jpeg in merged_tiles.items()
    ]
    # Sắp xếp theo (ty, tx) để payload có thứ tự ổn định
    encoded_list.sort(key=lambda t: (t.ty, t.tx))

    parts: list[bytes] = [
        _HEADER_FMT.pack(0x02, fw1, fh1, ts1, len(encoded_list))
    ]
    for t in encoded_list:
        parts.append(_TILE_FMT.pack(t.tx, t.ty, len(t.jpeg)))
        parts.append(t.jpeg)
    return b"".join(parts)

