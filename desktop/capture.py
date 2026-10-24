"""Chụp màn hình (mss) + nén JPEG (Pillow). Chạy trong thread riêng."""
import io
import threading

import mss
from PIL import Image

_local = threading.local()


def _get_sct():
    if not hasattr(_local, "sct"):
        _local.sct = mss.mss()
    return _local.sct


def list_monitors():
    """Trả về danh sách màn hình. Index 0 = toàn bộ desktop ảo, 1..n = từng màn hình."""
    try:
        with mss.mss() as sct:
            mons = sct.monitors
    except Exception:
        return [{"index": 0, "label": "Mặc định", "left": 0, "top": 0, "width": 0, "height": 0}]
    out = []
    for i, m in enumerate(mons):
        if m["width"] <= 0 or m["height"] <= 0:
            continue
        label = "Toàn bộ màn hình" if i == 0 else ("Màn hình %d (%dx%d)" % (i, m["width"], m["height"]))
        out.append({"index": i, "label": label, "left": m["left"], "top": m["top"],
                    "width": m["width"], "height": m["height"]})
    return out


def grab_jpeg(monitor: int, scale: int, quality: int):
    """Chụp + nén. Trả về (jpeg_bytes, meta_dict). Thread-safe (mss theo thread)."""
    sct = _get_sct()
    mons = sct.monitors
    idx = monitor if 0 <= monitor < len(mons) else (1 if len(mons) > 1 else 0)
    mon = mons[idx]
    raw = sct.grab(mon)
    # mss trả BGRA -> dùng rawmode BGRX của Pillow
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
