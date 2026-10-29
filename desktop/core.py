"""Lõi dùng chung: trạng thái kết nối, xử lý message từ viewer, vòng lặp stream.

Được server.py (LAN) và relay_client.py (qua internet) cùng sử dụng.
"""
import asyncio
import hashlib
import platform
import queue
import struct
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import config as cfgmod
import secure
from adaptive import AdaptiveController
from capture import (
    grab_jpeg,
    list_monitors,
    make_capturer,
    TileEngine,
    scale_frame,
    TILE_SIZE_DEFAULT,
    Frame,
)
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
adaptive = AdaptiveController()

_loop = None
_pool = None
_last_clip_hash = None
screen_locked = False
_svc_ok = None  # None = chưa thử; True/False = service TouchLinkSvc có/không
_svc_checked_at = 0.0

# --- Capture backend (DXGI hoặc MSS) ---
_capturer: Any = None           # instance Capturer
_capturer_lock = threading.Lock()
_capturer_monitor: int = -1     # monitor index đang dùng

# Khoảng gian keyframe toàn khung (giây)
_KEYFRAME_INTERVAL: float = 10.0
# Giới hạn kích thước payload nhị phân (8 MiB)
_MAX_FRAME_BYTES: int = 8 * 1024 * 1024


def svc_available(force=False):
    """Service TouchLinkSvc có chạy không (cache 10 giây)."""
    global _svc_ok, _svc_checked_at
    now = time.time()
    if force or _svc_ok is None or now - _svc_checked_at > 10:
        try:
            import svcpipe
            _svc_ok = svcpipe.ping() is not None
        except Exception:
            _svc_ok = False
        _svc_checked_at = now
    return _svc_ok


def _svc_mark_down():
    global _svc_ok, _svc_checked_at
    _svc_ok = False
    _svc_checked_at = time.time()


def _push_lock(locked):
    global screen_locked
    screen_locked = bool(locked)
    svc = False
    if screen_locked:
        try:
            svc = svc_available(force=True)
        except Exception:
            svc = False
        if svc:
            log("Màn hình khóa → chuyển sang điều khiển qua service TouchLinkSvc")
            broadcast_event("history", ("server",
                "Màn hình khóa: điều khiển qua TouchLinkSvc"))
    if _loop is not None and _loop.is_running():
        async def _b():
            await broadcast_json({"type": "screen_locked",
                                  "locked": bool(locked), "svc": bool(svc)})
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
                        "điều khiển từ phiên người dùng.")
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
    # Khởi tạo capturer DXGI/MSS ngay khi init để phát hiện sớm
    _ensure_capturer(int(settings["monitor"]))
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

    Nếu viewer khai báo cap "tiles" trong hello → nhận frame 0x02 (dirty tile).
    Ngược lại → nhận frame 0x01 (toàn khung JPEG, tương thích cũ).
    """

    def __init__(self, name, send_json, send_bytes, close):
        self.name = name
        self.since = time.strftime("%H:%M:%S")
        self._send_json = send_json
        self._send_bytes = send_bytes
        self._close = close
        self.alive = True
        self.caps: list[str] = []          # ghi nhận sau khi nhận hello
        # Mailbox: chỉ giữ payload nhị phân mới nhất
        self._frame: bytes | None = None
        self._frame_evt = asyncio.Event()
        self._sender_task = None
        # TileEngine riêng cho viewer này
        self.tile_engine = TileEngine(TILE_SIZE_DEFAULT)
        # Cờ yêu cầu keyframe tiếp theo
        self._need_keyframe: bool = True

    @property
    def supports_tiles(self) -> bool:
        """Viewer có khai báo cap 'tiles' không."""
        return "tiles" in self.caps

    def request_keyframe(self) -> None:
        """Đặt cờ yêu cầu keyframe toàn khung cho lần gửi tiếp theo."""
        self._need_keyframe = True
        self.tile_engine.reset()

    def start_sender(self):
        if self._sender_task is None:
            self._sender_task = asyncio.get_running_loop().create_task(self._sender())

    def offer_frame(self, data: bytes | None) -> None:
        """Đẩy payload nhị phân vào mailbox.

        None có nghĩa: màn hình tĩnh, không gửi gì (heartbeat được
        xử lý riêng bởi stream_loop).
        """
        if not self.alive or data is None:
            return
        if len(data) > _MAX_FRAME_BYTES:
            log("offer_frame: payload quá lớn (%d B), bỏ qua" % len(data))
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
            if data is None:
                continue
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
    try:
        if hasattr(inp, "release_all"):
            inp.release_all()
    except Exception:
        pass
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
    cap_name = _capturer.name if _capturer is not None else "mss"
    return {
        "type": "auth_ok",
        "device_id": cfg.get("device_id", ""),
        "hostname": host,
        "version": VERSION,
        "settings": dict(settings),
        "monitors": list_monitors(),
        "screen_locked": bool(screen_locked),
        "svc_ok": bool(screen_locked and svc_available()),
        "safe_test": inp.SAFE_TEST,
        "capturer": cap_name,
        "resume_token": secure.issue_resume_token(cfg.get("device_id", ""), ttl_seconds=120),
        "adaptive": adaptive.state(),
    }


async def verify_and_accept(conn, auth_msg):
    """Kiểm tra ID + mật khẩu từ message đầu tiên. Trả về True nếu OK."""
    device_id = str(auth_msg.get("id") or auth_msg.get("device_id") or "")
    password = str(auth_msg.get("password") or "")
    resume_token = str(auth_msg.get("resume_token") or "")

    if resume_token:
        ok = secure.consume_resume_token(resume_token, device_id)
        if ok:
            return True
        counters["auth_fails"] += 1
        try:
            await conn.send_json({"type": "auth_fail", "message": "Resume token không hợp lệ hoặc đã hết hạn"})
        except Exception:
            pass
        return False

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
    elif t == "hello":
        # Viewer gửi hello sau auth_ok — ghi nhận caps
        caps = msg.get("caps") or []
        if isinstance(caps, list):
            conn.caps = [str(c) for c in caps]
        if conn.supports_tiles:
            log("%s hỗ trợ tile frame (0x02)" % conn.name)
        conn.request_keyframe()
    elif t == "keyframe":
        # Viewer yêu cầu keyframe toàn khung (ví dụ: sau khi mất gói)
        conn.request_keyframe()
    # bỏ qua các type khác


async def _handle_input(msg):
    inp_msg = msg.get("input") or msg
    kind = inp_msg.get("kind")
    if kind == "mouse":
        action = inp_msg.get("action", "move")
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
        if screen_locked and svc_available():
            op = {"kind": "mouse", "action": action, "button": inp_msg.get("button", "left"),
                  "clicks": inp_msg.get("clicks", 1), "_geom": dict(meta)}
            if action == "move" and inp_msg.get("rel") is not None:
                op["rel"] = inp_msg["rel"]
            else:
                op["x"], op["y"] = px, py
            if action == "scroll":
                op["amount"] = int(inp_msg.get("amount", 0) or 0)
                op["hamount"] = int(inp_msg.get("hamount", 0) or 0)
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: _svc_input(op))
            return
        if action == "move" and inp_msg.get("rel") is not None:
            try:
                dx, dy = inp_msg["rel"]
                inp.mouse("moverel", int(dx), int(dy))
            except Exception:
                pass
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
            if screen_locked and svc_available():
                await asyncio.get_running_loop().run_in_executor(
                    None, lambda: _svc_input({"kind": "key", "key": key, "mods": list(mods)}))
                return
            inp.tap_key(key, mods)
    elif kind == "text":
        text = str(inp_msg.get("text", ""))[:2000]
        if text:
            if screen_locked and svc_available():
                await asyncio.get_running_loop().run_in_executor(
                    None, lambda: _svc_input({"kind": "text", "text": text}))
                return
            inp.type_text(text)


def _svc_input(op):
    try:
        import svcpipe
        return svcpipe.send_input(op)
    except Exception as e:
        _svc_mark_down()
        log("Service input lỗi: %s" % e)
        return {"ok": False}


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
    """Khi đổi màn hình / scale: reset TileEngine mọi viewer → gửi keyframe."""
    for c in list(clients):
        c.request_keyframe()
    # Đổi capturer sang màn hình mới
    _ensure_capturer(int(settings["monitor"]))


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


def _grab_any(mon: int, scale: int, quality: int):
    """Chụp màn hình: qua service TouchLinkSvc khi màn hình khóa, không thì chụp trực tiếp.

    Hàm tương thích ngược — chỉ dùng cho service path và code cũ.
    Stream chính dùng _grab_frame() trả Frame object.
    """
    if screen_locked and svc_available():
        try:
            import svcpipe
            return svcpipe.grab(mon, scale, quality)
        except Exception as e:
            _svc_mark_down()
            log("Service grab lỗi (%s) — tạm quay về chụp trực tiếp" % e)
    return grab_jpeg(mon, scale, quality)


def _ensure_capturer(monitor: int) -> None:
    """Đảm bảo capturer đang chạy cho đúng monitor; khởi động lại nếu cần."""
    global _capturer, _capturer_monitor
    with _capturer_lock:
        if _capturer is not None and _capturer_monitor == monitor:
            return
        # Dừng capturer cũ
        if _capturer is not None:
            try:
                _capturer.stop()
            except Exception as exc:
                log("capturer.stop() lỗi: %s" % exc)
            _capturer = None
        cap = make_capturer(prefer_dxgi=True)
        try:
            cap.start(monitor)
            _capturer = cap
            _capturer_monitor = monitor
            log("Capturer '%s' đã bắt đầu (monitor=%d)" % (cap.name, monitor))
        except Exception as exc:
            log("Capturer '%s' start lỗi (%s) → fallback MSS" % (cap.name, exc))
            # Fallback tường minh về MSS
            from capture.mss_capturer import MssCapturer
            fallback = MssCapturer()
            fallback.start(monitor)
            _capturer = fallback
            _capturer_monitor = monitor
            log("Capturer 'mss' đã bắt đầu (fallback, monitor=%d)" % monitor)


def _grab_frame_raw(mon: int, scale: int) -> "Frame | None":
    """Chụp một frame thô bằng capturer hiện tại.

    Gọi từ thread pool (không phải event-loop).
    Trả về Frame hoặc None nếu chưa có dữ liệu.
    """
    import copy
    _ensure_capturer(mon)
    cap = _capturer
    if cap is None:
        return None
    frame = cap.grab()
    if frame is None:
        return None
    # Scale nếu cần
    if scale < 100:
        try:
            arr = scale_frame(frame.data, scale)
        except Exception:
            arr = frame.data
    else:
        arr = frame.data
    # Trả về Frame mới với data đã scale
    f2 = copy.copy(frame)
    f2.data = arr
    if scale < 100 and hasattr(arr, "shape"):
        f2.width = arr.shape[1]
        f2.height = arr.shape[0]
    return f2


async def stream_loop():
    """Vòng lặp chính: chụp màn hình → tile/JPEG → gửi tới mọi viewer.

    Luồng xử lý:
    1. Chụp Frame thô bằng capturer (DXGI/MSS) trong thread pool.
    2. Với mỗi viewer: TileEngine.process() tính payload riêng
       (0x02 tile hoặc 0x01 keyframe tuỳ caps viewer).
    3. Màn hình tĩnh: không offer_frame; chỉ gửi heartbeat ping 5 giây.
    4. Viewer không hỗ trợ tiles: luôn nhận 0x01 toàn khung từ TileEngine.
    """
    global _last_clip_hash
    import numpy as np
    _heartbeat_interval = 5.0  # giây
    _last_heartbeat = time.monotonic()

    while True:
        try:
            interval = 1.0 / max(2, int(settings["fps"]))
            if clients:
                t0 = time.monotonic()
                mon = int(settings["monitor"])
                scale = int(settings["scale"])
                quality = int(settings["quality"])
                loop = asyncio.get_running_loop()

                # --- Chụp frame trong thread pool ---
                if screen_locked and svc_available():
                    # Khi màn hình khóa: dùng service grab trả (jpeg_bytes, meta)
                    jpeg_meta = await loop.run_in_executor(
                        _pool, _grab_any, mon, scale, quality
                    )
                    if jpeg_meta is not None:
                        jpeg, m = jpeg_meta
                        meta.update(m)
                        header_fmt = struct.Struct(">BHH")
                        payload_full = header_fmt.pack(1, m["fw"], m["fh"]) + jpeg
                        counters["frames"] += 1
                        for c in list(clients):
                            c.offer_frame(payload_full)
                    elapsed = time.monotonic() - t0
                    await asyncio.sleep(max(0.001, interval - elapsed))
                    continue

                # --- Normal path: dùng capturer DXGI/MSS ---
                raw_frame: Frame | None = await loop.run_in_executor(
                    _pool, _grab_frame_raw, mon, scale
                )
                if raw_frame is None:
                    await asyncio.sleep(0.02)
                    continue

                # Cập nhật meta chung
                meta.update({
                    "left": raw_frame.mon_left,
                    "top": raw_frame.mon_top,
                    "width": raw_frame.mon_width,
                    "height": raw_frame.mon_height,
                    "fw": raw_frame.width,
                    "fh": raw_frame.height,
                })

                arr = raw_frame.data  # numpy RGB (H, W, 3)
                any_dirty = False

                for c in list(clients):
                    force_kf = c._need_keyframe
                    c._need_keyframe = False

                    if c.supports_tiles:
                        # Encode tile riêng cho viewer này
                        payload = await loop.run_in_executor(
                            _pool,
                            _encode_for_viewer,
                            c.tile_engine, arr, quality, force_kf,
                        )
                    else:
                        # Viewer cũ: luôn gửi 0x01 toàn khung
                        payload = await loop.run_in_executor(
                            _pool,
                            _encode_full_frame,
                            c.tile_engine, arr, quality, force_kf,
                        )

                    if payload is not None:
                        any_dirty = True
                        c.offer_frame(payload)

                if any_dirty:
                    counters["frames"] += 1

                # Heartbeat khi tĩnh
                now = time.monotonic()
                if not any_dirty and now - _last_heartbeat >= _heartbeat_interval:
                    _last_heartbeat = now
                    await broadcast_json({"type": "ping", "t": int(now * 1000)})
                elif any_dirty:
                    _last_heartbeat = now

                # Đồng bộ clipboard
                if settings.get("clipboard_sync"):
                    text = _clipboard_get()
                    if text:
                        h = hashlib.md5(text.encode("utf-8", "ignore")).hexdigest()
                        if h != _last_clip_hash:
                            _last_clip_hash = h
                            await broadcast_json(
                                {"type": "clipboard", "text": text[:20000]}
                            )

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


def _encode_for_viewer(
    engine: TileEngine,
    arr,
    quality: int,
    force_keyframe: bool,
) -> bytes | None:
    """Encode frame cho viewer hỗ trợ tiles (0x02 hoặc 0x01 keyframe).

    Gọi từ thread pool.
    """
    return engine.process(
        arr,
        quality,
        force_keyframe=force_keyframe,
        keyframe_interval=_KEYFRAME_INTERVAL,
    )


def _encode_full_frame(
    engine: TileEngine,
    arr,
    quality: int,
    force_keyframe: bool,
) -> bytes | None:
    """Encode toàn khung 0x01 cho viewer cũ (không hỗ trợ tiles).

    Gọi từ thread pool. Dùng TileEngine chỉ để detect tĩnh/động.
    """
    result = engine.process(
        arr,
        quality,
        force_keyframe=force_keyframe,
        keyframe_interval=_KEYFRAME_INTERVAL,
    )
    if result is None:
        return None  # tĩnh
    # Nếu kết quả là 0x02 tile → convert sang 0x01 toàn khung
    if result[0:1] == b'\x02':
        # Fallback: gửi keyframe toàn khung
        engine.reset()
        result = engine.process(
            arr, quality, force_keyframe=True,
            keyframe_interval=_KEYFRAME_INTERVAL,
        )
    return result
