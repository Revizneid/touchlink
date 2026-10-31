"""MssCapturer — fallback dùng thư viện mss + Pillow.

Giữ toàn bộ hành vi của capture.py cũ; wrap vào giao diện Capturer.
"""
from __future__ import annotations

import logging
import threading

import mss
from PIL import Image

from .base import Frame, Rect

logger = logging.getLogger(__name__)

_local = threading.local()


def _get_sct() -> mss.base.MSSBase:
    """Lấy instance mss riêng cho thread hiện tại."""
    if not hasattr(_local, "sct"):
        _local.sct = mss.mss()
    return _local.sct


def list_monitors() -> list[dict]:
    """Trả về danh sách màn hình cho GUI.

    Index 0 = toàn bộ desktop ảo, 1..n = từng màn hình.
    """
    try:
        with mss.mss() as sct:
            mons = sct.monitors
    except Exception:
        return [{"index": 0, "label": "Mặc định", "left": 0, "top": 0,
                 "width": 0, "height": 0}]
    out = []
    for i, m in enumerate(mons):
        if m["width"] <= 0 or m["height"] <= 0:
            continue
        label = ("Toàn bộ màn hình" if i == 0
                 else "Màn hình %d (%dx%d)" % (i, m["width"], m["height"]))
        out.append({"index": i, "label": label, "left": m["left"],
                    "top": m["top"], "width": m["width"], "height": m["height"]})
    return out


class MssCapturer:
    """Capturer dùng mss (GDI/BitBlt) — tương thích mọi môi trường Windows."""

    name: str = "mss"

    def __init__(self) -> None:
        self._monitor_idx: int = 1
        self._sct: mss.base.MSSBase | None = None

    def start(self, monitor: int) -> None:
        """Khởi động; lưu index màn hình để dùng trong grab()."""
        self._monitor_idx = monitor
        # mss được tạo lười (lazy) trong thread gọi grab()
        logger.debug("MssCapturer.start monitor=%d", monitor)

    def grab(self) -> Frame | None:
        """Chụp một frame bằng mss. Thread-safe (mỗi thread có instance riêng)."""
        sct = _get_sct()
        mons = sct.monitors
        idx = (self._monitor_idx
               if 0 <= self._monitor_idx < len(mons)
               else (1 if len(mons) > 1 else 0))
        mon = mons[idx]
        raw = sct.grab(mon)
        # mss trả BGRA → dùng rawmode BGRX của Pillow
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        import numpy as np
        arr = np.array(img)
        return Frame(
            data=arr,
            width=img.width,
            height=img.height,
            mon_left=mon["left"],
            mon_top=mon["top"],
            mon_width=mon["width"],
            mon_height=mon["height"],
        )

    def dirty_rects(self) -> list[Rect]:
        """mss không cung cấp dirty-rect; trả về list rỗng để tile engine so hash."""
        return []

    def stop(self) -> None:
        """Giải phóng instance mss của thread hiện tại nếu có."""
        sct = getattr(_local, "sct", None)
        if sct is not None:
            try:
                sct.close()
            except Exception:
                pass
            _local.sct = None
        logger.debug("MssCapturer.stop")


def grab_jpeg(monitor: int, scale: int, quality: int):
    """API tương thích ngược với capture.py cũ.

    Trả về (jpeg_bytes, meta_dict). Thread-safe.
    """
    import io
    sct = _get_sct()
    mons = sct.monitors
    idx = monitor if 0 <= monitor < len(mons) else (1 if len(mons) > 1 else 0)
    mon = mons[idx]
    raw = sct.grab(mon)
    img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    if scale and scale < 100:
        w = max(1, img.width * scale // 100)
        h = max(1, img.height * scale // 100)
        resample = getattr(Image, "Resampling", Image).BILINEAR
        img = img.resize((w, h), resample)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=int(quality))
    return buf.getvalue(), {
        "left": mon["left"], "top": mon["top"],
        "width": mon["width"], "height": mon["height"],
        "fw": img.width, "fh": img.height,
    }
