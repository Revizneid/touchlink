"""Lõi dùng chung: trạng thái kết nối, xử lý message từ viewer, vòng lặp stream.

Được server.py (LAN) và relay_client.py (qua internet) cùng sử dụng.
"""
import asyncio
import hashlib
import platform
import queue
import struct
import time
from concurrent.futures import ThreadPoolExecutor

import config as cfgmod
import secure
from capture import grab_jpeg, list_monitors
import input_control as inp

VERSION = cfgmod.VERSION

# Trạng thái dùng chung (chỉ chạm từ event-loop thread trừ khi nói rõ)
clients = set()          # tập ClientConn đã xác thực
settings = {"fps": 12, "quality": 60, "scale": 100, "monitor": 1,
            "clipboard_sync": True, "keep_awake": True}
meta = {"left": 0, "top": 0, "width": 0, "height": 0, "fw": 0, "fh": 0}
cfg = {}                 # tham chiếu config (device_id, password_enc...)
events = None            # queue.Queue cho GUI
counters = {"events": 0, "frames": 0, "auth_fails": 0}
limiter = None           # RateLimiter, gắn từ server.py

_loop = None
_pool = None
_last_clip_hash = None
screen_locked = False


def _push_lock(locked):
    global screen_locked
    screen_locked = bool(locked)
    if _loop is not None and _loop.is_running():
        async def _b():
            await broadcast_json({"type": "screen_locked", "locked": bool(locked)})
        try:
            asyncio.run_coroutine_threadsafe(_b(), _loop)
        except Exception:
            pass


def _start_lock_watcher():
    """Phát hiện màn hình Windows bị khóa (không thể xem/điều khiển từ phiên
    người dùng do cơ chế bảo mật của Windows) và cảnh báo mọi viewer."""
    def _watch():
        global screen_locked
        import ctypes
        last = None
        while True:
            try:
                h = ctypes.windll.user32.OpenInputDesktop(0, True, 0x0101)
                locked = (h == 0)
                if h:
                    ctypes.windll.user32.CloseDesktop(h)
            except Exception:
                locked = False
            if locked != last:
                last = locked
                _push_lock(locked)
                if locked:
                    log("⚠ Màn hình máy tính đang BỊ KHÓA — Windows không cho xem/"
                        "điều khiển từ xa ở trạng thái này. Phải mở khóa trực tiếp.")
                    broadcast_event("history", ("server", "Màn hình bị khóa"))
                else:
                    log("Màn hình đã mở khóa.")
                    broadcast_event("history", ("server", "Màn hình mở khóa"))
            time.sleep(2)
    threading.Thread(target=_watch, daemon=True, name="touchlink-lock").start()


def init(cfg_ref, events_q, rate_limiter=None):
    global cfg, events, limiter, _pool
    cfg = cfg_ref
    events = events_q
    limiter = rate_limiter
    for k in ("fps", "quality", "scale", "monitor", "clipboard_sync", "keep_awake"):
        if k in cfg_ref:
            settings[k] = cfg_ref[k]
    settings["keep_awake"] = bool(settings.get("keep_awake", True))
    _pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="capture")
    log("TouchLink core sẵn sàng (safe_test=%s)" % inp.SAFE_TEST)
    try:
        _start_lock_watcher()
    except Exception as e:
        log("lock-watcher lỗi: %s" % e)
    try:
        import keepawake
        keepawake.set_awake(bool(settings["keep_awake"]))
        log("Giữ máy thức (ngăn sleep): %s" % ("bật" if settings["keep_awake"] else "tắt"))
        if keepawake.keeper.last_ok is False:
            log("CẢNH BÁO: Windows từ chối SetThreadExecutionState")
    except Exception as e:
        log("keep-awake lỗi: %s" % e)


def log(msg):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    try:
        print(line, flush=True)  # stdout có thể là None (exe GUI) hoặc không hỗ trợ UTF-8
    except Exception:
        pass
    if events is not None:
        try:
            events.put(("log", msg))
        except Exception:
            pass


def get_loop():
    return _loop


def set_loop(loop):
    global _loop
    _loop = loop


def broadcast_event(kind, data):
    if events is not None:
        try:
            events.put((kind, data))
        except Exception:
            pass


class ClientConn:
    """Kết nối viewer — bọc qua WebSocket LAN hoặc đường hầm relay.

    Frame màn hình đi qua mailbox "chỉ giữ frame mới nhất": viewer chậm
    (mạng yếu) bỏ qua frame cũ, không bao giờ chặn viewer khác hay vòng
    chụp màn hình (head-of-line blocking).
    """

    def __init__(self, name, send_json, send_bytes, close):
        self.name = name
        self.since = time.strftime("%H:%M:%S")
        self._send_json = send_json
        self._send_bytes = send_bytes
        self._close = close
        self.alive = True
        self._frame = None
        self._frame_evt = asyncio.Event()
        self._sender_task = None

    def start_sender(self):
        if self._sender_task is None:
            self._sender_task = asyncio.get_running_loop().create_task(self._sender())

    def offer_frame(self, data):
        if not self.alive:
            return
        self._frame = data  # chỉ giữ frame mới nhất
        self._frame_evt.set()

    async def _sender(self):
        while self.alive:
            try:
                await self._frame_evt.wait()
            except asyncio.CancelledError:
                return
            if not self.alive:
                return
            self._frame_evt = asyncio.Event()
            data = self._frame
            self._frame = None
            try:
                await asyncio.wait_for(self.send_bytes(data), timeout=6)
            except Exception:
                asyncio.create_task(remove_client(self, "(kết nối chậm)"))
                return

    async def send_json(self, data):
        if self.alive:
            await self._send_json(data)

    async def send_bytes(self, data):
        if self.alive:
            await self._send_bytes(data)

    async def close(self):
        self.alive = False
        try:
            await self._close()
        except Exception:
            pass


async def add_client(conn):
    clients.add(conn)
    conn.start_sender()
    broadcast_event("clients", len(clients))
    broadcast_event("log", "Viewer kết nối: %s (tổng %d)" % (conn.name, len(clients)))
    broadcast_event("history", ("viewer", "Kết nối: %s" % conn.name))
    await broadcast_json({"type": "clients", "n": len(clients)})


def clients_snapshot():
    """Danh sách viewer đang kết nối cho GUI (an toàn gọi từ thread khác)."""
    return [(getattr(c, "name", "?"), getattr(c, "since", "")) for c in list(clients)]


async def remove_client(conn, reason=""):
    t = getattr(conn, "_sender_task", None)
    if t is not None:
        t.cancel()
    if conn in clients:
        clients.discard(conn)
        conn.alive = False
        broadcast_event("clients", len(clients))
        broadcast_event("log", "Viewer rời khỏi: %s %s (còn %d)" % (conn.name, reason, len(clients)))
        broadcast_event("history", ("viewer", "Ngắt: %s %s" % (conn.name, reason)))
        await broadcast_json({"type": "clients", "n": len(clients)})
    try:
        await conn.close()
    except Exception:
        pass


async def broadcast_json(data, exclude=None):
    for c in list(clients):
        if c is exclude:
            continue
        try:
            await asyncio.wait_for(c.send_json(data), timeout=3)
        except Exception:
            await remove_client(c, "(gửi lỗi)")


def auth_ok_payload():
    host = platform.node()
    return {
        "type": "auth_ok",
        "device_id": cfg.get("device_id", ""),
        "hostname": host,
        "version": VERSION,
        "settings": dict(settings),
        "monitors": list_monitors(),
        "screen_locked": bool(screen_locked),
        "safe_test": inp.SAFE_TEST,
    }


async def verify_and_accept(conn, auth_msg):
    """Kiểm tra ID + mật khẩu từ message đầu tiên. Trả về True nếu OK."""
    device_id = str(auth_msg.get("id") or auth_msg.get("device_id") or "")
    password = str(auth_msg.get("password") or "")
    ok = (device_id == str(cfg.get("device_id", "")) and
          secure.verify_password(password, cfg.get("password_enc") or ""))
    if not ok:
        counters["auth_fails"] += 1
        try:
            await conn.send_json({"type": "auth_fail", "message": "Sai mã máy hoặc mật khẩu"})
        except Exception:
            pass
        return False
    return True


async def handle_client_message(conn, msg):
    """Xử lý 1 JSON message từ viewer (đã xác thực)."""
    if not isinstance(msg, dict):
        return
    t = msg.get("type")
    counters["events"] += 1

    if t == "input":
        await _handle_input(msg)
    elif t == "settings":
        await _handle_settings(conn, msg)
    elif t == "clipboard_get":
        text = _clipboard_get()
        await conn.send_json({"type": "clipboard", "text": text})
    elif t == "clipboard_set":
        _clipboard_set(str(msg.get("text", "")))
        log("Nhận clipboard từ %s (%d ký tự)" % (conn.name, len(msg.get("text", ""))))
    elif t == "chat":
        text = str(msg.get("text", ""))[:500]
        await broadcast_json({"type": "chat", "from": conn.name, "text": text})
        broadcast_event("chat", (conn.name, text))
    elif t == "ping":
        await conn.send_json({"type": "pong", "t": msg.get("t")})
    # bỏ qua các type khác


async def _handle_input(msg):
    inp_msg = msg.get("input") or msg
    kind = inp_msg.get("kind")
    if kind == "mouse":
        action = inp_msg.get("action", "move")
        if action == "move" and inp_msg.get("rel") is not None:
            try:
                dx, dy = inp_msg["rel"]
                inp.mouse("moverel", int(dx), int(dy))
            except Exception:
                pass
            return
        x, y = inp_msg.get("x"), inp_msg.get("y")
        px = py = None
        if x is not None and y is not None and meta["width"]:
            try:
                fx = float(x) * meta["width"] / max(1, meta["fw"])
                fy = float(y) * meta["height"] / max(1, meta["fh"])
                px = meta["left"] + max(0, min(meta["width"] - 1, int(round(fx))))
                py = meta["top"] + max(0, min(meta["height"] - 1, int(round(fy))))
            except Exception:
                return
        amount = int(inp_msg.get("amount", 0) or 0)
        hamount = int(inp_msg.get("hamount", 0) or 0)
        if action == "scroll":
            if amount:
                inp.mouse("scroll", px, py, amount=amount)
            if hamount:
                inp.mouse("scroll", px, py, amount=hamount, horizontal=True)
        else:
            inp.mouse(action, px, py,
                      button=inp_msg.get("button", "left"),
                      clicks=inp_msg.get("clicks", 1))
    elif kind == "key":
        key = str(inp_msg.get("key", ""))
        mods = inp_msg.get("mods") or []
        if key:
            inp.tap_key(key, mods)
    elif kind == "text":
        text = str(inp_msg.get("text", ""))[:2000]
        if text:
            inp.type_text(text)


async def _handle_settings(conn, msg):
    s = msg.get("settings") or {}
    changed_geom = False
    for k in ("fps", "quality", "scale", "monitor", "clipboard_sync", "keep_awake"):
        if k in s:
            try:
                v = int(s[k]) if k not in ("clipboard_sync", "keep_awake") else bool(s[k])
            except Exception:
                continue
            if k == "fps":
                v = max(2, min(30, v))
            elif k == "quality":
                v = max(20, min(95, v))
            elif k == "scale":
                v = max(30, min(100, v))
            if settings[k] != v:
                settings[k] = v
                if k in ("scale", "monitor"):
                    changed_geom = True
    cfg.update(settings)
    try:
        cfgmod.save(cfg)
    except Exception:
        pass
    if "keep_awake" in s:
        try:
            import keepawake
            keepawake.set_awake(bool(settings["keep_awake"]))
            state = "bật" if settings["keep_awake"] else "tắt"
            log("Giữ máy thức (ngăn sleep): %s" % state)
            broadcast_event("history", ("setting", "Ngăn máy tính sleep: %s" % state))
        except Exception:
            pass
    await broadcast_json({"type": "settings", "settings": dict(settings)})
    broadcast_event("settings", dict(settings))
    if changed_geom:
        await _send_meta_to_all()


async def _send_meta_to_all():
    # buộc frame kế tiếp mang meta mới; client tự đọc w/h từ header frame
    pass


def _clipboard_get():
    if inp.SAFE_TEST:
        return "[safe-test] clipboard bị tắt khi kiểm thử"
    try:
        import pyperclip
        return pyperclip.paste() or ""
    except Exception as e:
        return "(lỗi clipboard: %s)" % e


def _clipboard_set(text):
    if inp.SAFE_TEST:
        return
    try:
        import pyperclip
        pyperclip.copy(text)
    except Exception:
        pass


async def stream_loop():
    """Vòng lặp chính: chụp màn hình -> nén JPEG -> gửi tới mọi viewer."""
    global _last_clip_hash
    header_fmt = struct.Struct(">BHH")
    while True:
        try:
            interval = 1.0 / max(2, int(settings["fps"]))
            if clients:
                t0 = time.monotonic()
                mon = int(settings["monitor"])
                scale = int(settings["scale"])
                quality = int(settings["quality"])
                loop = asyncio.get_running_loop()
                jpeg, m = await loop.run_in_executor(_pool, grab_jpeg, mon, scale, quality)
                meta.update(m)
                payload = header_fmt.pack(1, m["fw"], m["fh"]) + jpeg
                counters["frames"] += 1
                # mailbox: mỗi viewer tự lấy frame mới nhất, không chặn nhau
                for c in list(clients):
                    c.offer_frame(payload)
                # đồng bộ clipboard nếu bật
                if settings.get("clipboard_sync"):
                    text = _clipboard_get()
                    if text and hashlib.md5(text.encode("utf-8", "ignore")).hexdigest() != _last_clip_hash:
                        _last_clip_hash = hashlib.md5(text.encode("utf-8", "ignore")).hexdigest()
                        await broadcast_json({"type": "clipboard", "text": text[:20000]})
                elapsed = time.monotonic() - t0
                await asyncio.sleep(max(0.001, interval - elapsed))
            else:
                _last_clip_hash = None
                await asyncio.sleep(0.15)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log("stream_loop lỗi: %s" % e)
            await asyncio.sleep(0.5)
