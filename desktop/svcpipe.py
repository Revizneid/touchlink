"""Client named pipe để app chính (phiên người dùng) gọi TouchLinkSvc.

Khi màn hình Windows bị khóa, app không thể chụp/gửi input trực tiếp —
mọi thao tác được chuyển qua service SYSTEM (xem svc_main.py).
Gọi an toàn từ mọi thread; mỗi request tự mở/đóng pipe.
"""
import json
import struct

PIPE_NAME = r'\\.\pipe\TouchLinkSvc'

_win = False
try:
    import win32file
    import pywintypes
    _win = True
except Exception:
    _win = False


def _read_exact(h, n):
    out = b""
    while len(out) < n:
        _, data = win32file.ReadFile(h, n - len(out))
        if not data:
            raise ConnectionError("pipe đóng")
        out += data
    return out


def request(op, timeout_ms=6000):
    """Gửi 1 op JSON, trả (type_byte, payload_bytes). Ngoại lệ nếu service không có."""
    if not _win:
        raise OSError("Không phải Windows")
    h = win32file.CreateFile(PIPE_NAME,
                             win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                             0, None, win32file.OPEN_EXISTING, 0, None)
    try:
        win32file.WriteFile(h, (json.dumps(op) + "\n").encode("utf-8"))
        tb = _read_exact(h, 1)[0]
        ln = struct.unpack("<I", _read_exact(h, 4))[0]
        data = _read_exact(h, ln)
        return tb, data
    finally:
        try:
            win32file.CloseHandle(h)
        except Exception:
            pass


def ping():
    """Trả dict trạng thái service hoặc None nếu không gọi được."""
    try:
        tb, data = request({"op": "ping"}, timeout_ms=1500)
        if tb == 0x4A:  # 'J'
            return json.loads(data)
    except Exception:
        return None
    return None


def grab(monitor=1, scale=100, quality=60):
    """Chụp qua service. Trả (jpeg_bytes, meta_dict) như capture.grab_jpeg."""
    tb, data = request({"op": "grab", "monitor": monitor, "scale": scale,
                        "quality": quality}, timeout_ms=8000)
    if tb != 0x42:
        raise RuntimeError("grab lỗi: %s" % data[:200])
    meta_len = struct.unpack("<I", data[:4])[0]
    meta = json.loads(data[4:4 + meta_len])
    body = data[4 + meta_len:]
    # body = 5-byte header + jpeg — bỏ header, trả jpeg như capture.grab_jpeg
    jpeg = body[5:]
    return jpeg, meta


def send_input(inp_msg):
    """Gửi 1 op input (kind: mouse/key/text) sang service."""
    op = dict(inp_msg)
    op["op"] = "input"
    tb, data = request(op, timeout_ms=4000)
    if tb != 0x4A:
        raise RuntimeError("input lỗi")
    return json.loads(data)
