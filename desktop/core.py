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
settings = {"fps": 12, "quality": 60, "scale": 100, "monitor": 1, "clipboard_sync": True}
meta = {"left": 0, "top": 0, "width": 0, "height": 0, "fw": 0, "fh": 0}
cfg = {}                 # tham chiếu config (device_id, password_enc...)
events = None            # queue.Queue cho GUI
counters = {"events": 0, "frames": 0, "auth_fails": 0}
limiter = None           # RateLimiter, gắn từ server.py

_loop = None
_pool = None
_last_clip_hash = None


def init(cfg_ref, events_q, rate_limiter=None):
    global cfg, events, limiter, _pool
    cfg = cfg_ref
    events = events_q
    limiter = rate_limiter
    for k in ("fps", "quality", "scale", "monitor", "clipboard_sync"):
        if k in cfg_ref:
            settings[k] = cfg_ref[k]
    _pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="capture")
    log("TouchLink core sẵn sàng (safe_test=%s)" % inp.SAFE_TEST)


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
    """Kết nối viewer — bọc qua WebSocket LAN hoặc đường hầm relay."""

    def __init__(self, name, send_json, send_bytes, close):
        self.name = name
        self._send_json = send_json
        self._send_bytes = send_bytes
        self._close = close
        self.alive = True

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
    broadcast_event("clients", len(clients))
    broadcast_event("log", "Viewer kết nối: %s (tổng %d)" % (conn.name, len(clients)))
    await broadcast_json({"type": "clients", "n": len(clients)})


async def remove_client(conn, reason=""):
    if conn in clients:
        clients.discard(conn)
        conn.alive = False
        broadcast_event("clients", len(clients))
        broadcast_event("log", "Viewer rời khỏi: %s %s (còn %d)" % (conn.name, reason, len(clients)))
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
            await c.send_json(data)
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
    for k in ("fps", "quality", "scale", "monitor", "clipboard_sync"):
        if k in s:
            try:
                v = int(s[k]) if k != "clipboard_sync" else bool(s[k])
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
                dead = []
                for c in list(clients):
                    try:
                        await asyncio.wait_for(c.send_bytes(payload), timeout=4)
                    except Exception:
                        dead.append(c)
                for c in dead:
                    await remove_client(c, "(chậm/không phản hồi)")
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
