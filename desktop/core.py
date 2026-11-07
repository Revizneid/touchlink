"""Lõi dùng chung: trạng thái kết nối, xử lý message từ viewer, vòng lặp stream.

Được server.py (LAN) và relay_client.py (qua internet) cùng sử dụng.
"""
import asyncio
import hashlib
import platform
import struct
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import config as cfgmod
import input_control as inp
import secure
from adaptive import AdaptiveController
from capture import (
    TILE_SIZE_DEFAULT,
    Frame,
    TileEngine,
    grab_jpeg,
    list_monitors,
    make_capturer,
    merge_tile_payloads,
    scale_frame,
)
from security.audit import AuditLogger as _AuditLogger

# Singleton audit logger — ghi sự kiện xác thực, phiên, và nhạy cảm.
# Không ghi nội dung phím/clipboard.
_audit: _AuditLogger = _AuditLogger()

VERSION = cfgmod.VERSION

from multi_viewer import MultiViewerSession

# Trạng thái dùng chung (chỉ chạm từ event-loop thread trừ khi nói rõ)
clients = set()          # tập ClientConn đã xác thực
multi_viewer_session = MultiViewerSession(max_viewers=4)
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
_file_sessions: dict[str, Any] = {}  # transfer_id -> FileTransferSession

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
    log(f"TouchLink core sẵn sàng (safe_test={inp.SAFE_TEST})")
    # Khởi tạo capturer DXGI/MSS ngay khi init để phát hiện sớm
    _ensure_capturer(int(settings["monitor"]))
    try:
        _start_lock_watcher()
    except Exception as e:
        log(f"lock-watcher lỗi: {e}")
    try:
        import keepawake
        keepawake.set_awake(bool(settings["keep_awake"]))
        log("Giữ máy thức (ngăn sleep): %s" % ("bật" if settings["keep_awake"] else "tắt"))
        if keepawake.keeper.last_ok is False:
            log("CẢNH BÁO: Windows từ chối SetThreadExecutionState")
    except Exception as e:
        log(f"keep-awake lỗi: {e}")


def log(msg):
    msg_str = str(msg)
    line = "[{}] {}".format(time.strftime("%H:%M:%S"), msg_str)
    try:
        print(line, flush=True)  # stdout có thể là None (exe GUI) hoặc không hỗ trợ UTF-8
    except UnicodeEncodeError:
        try:
            enc = sys.stdout.encoding or "utf-8"
            print(line.encode(enc, errors="replace").decode(enc), flush=True)
        except Exception:
            pass
    except Exception:
        pass
    if events is not None:
        try:
            events.put(("log", msg_str))
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
        self.rtc_session = None

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

        Nếu mailbox đã có frame chưa gửi (viewer chậm / lag):
        - Với tile 0x02: gộp dirty rect (merge_tile_payloads) giữa frame cũ và mới.
        - Nếu gộp không thành công hoặc vượt ngưỡng: gán frame mới và ép keyframe
          cho lần gửi tiếp theo để chống lệch hình.
        - Với viewer cũ (0x01): ghi đè frame mới nhất.
        """
        if not self.alive or data is None:
            return
        if len(data) > _MAX_FRAME_BYTES:
            log("offer_frame: payload quá lớn (%d B), bỏ qua" % len(data))
            return

        if self._frame is not None:
            if self.supports_tiles and self._frame[0:1] == b"\x02" and data[0:1] == b"\x02":
                merged = merge_tile_payloads(self._frame, data)
                if merged is not None:
                    self._frame = merged
                    self._frame_evt.set()
                    return
                # Gộp không thành công hoặc quá nhiều tile thay đổi -> ép keyframe kế tiếp
                self.request_keyframe()
            elif self.supports_tiles:
                self.request_keyframe()

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
                self.request_keyframe()
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


async def _broadcast_viewer_roles():
    """Gửi cập nhật danh sách viewer và ai đang là Controller tới mọi client."""
    for c in list(clients):
        try:
            r = getattr(c, "role", "viewer")
            await c.send_json({
                "type": "role",
                "role": r,
                "is_controller": (r == "controller"),
                "controller": multi_viewer_session.controller,
                "viewers": multi_viewer_session.list_viewers(),
            })
        except Exception:
            pass


async def add_client(conn):
    clients.add(conn)
    is_first = (len(multi_viewer_session.viewers) == 0)
    desired_role = "viewer" if getattr(conn, "view_only", False) else ("controller" if is_first else "viewer")
    multi_viewer_session.register_viewer(conn.name, role=desired_role)
    conn.role = multi_viewer_session.get_role(conn.name)

    conn.start_sender()
    broadcast_event("clients", len(clients))
    broadcast_event("log", "Viewer kết nối: %s (%s) (tổng %d)" % (conn.name, conn.role, len(clients)))
    broadcast_event("history", ("viewer", f"Kết nối: {conn.name} ({conn.role})"))
    await broadcast_json({"type": "clients", "n": len(clients)})
    await _broadcast_viewer_roles()
    # Audit: ghi sự kiện bắt đầu phiên
    try:
        _audit.record_event(
            event="session_start",
            device_id=getattr(conn, "device_id", conn.name),
            permission="view_only" if getattr(conn, "view_only", False) else "control",
            details={"viewer": conn.name, "role": conn.role},
        )
    except Exception:
        pass


def clients_snapshot():
    """Danh sách viewer đang kết nối cho GUI (an toàn gọi từ thread khác)."""
    return [
        (
            getattr(c, "name", "?"),
            getattr(c, "since", ""),
            getattr(c, "role", "viewer"),
            getattr(c, "role", "viewer") == "controller",
        )
        for c in list(clients)
    ]


def set_active_controller(name: str) -> bool:
    """Đổi active controller sang viewer được chỉ định (gọi từ GUI hoặc logic điều phối)."""
    if multi_viewer_session.set_controller(name):
        for c in list(clients):
            c.role = multi_viewer_session.get_role(c.name)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_broadcast_viewer_roles())
        except RuntimeError:
            pass
        return True
    return False


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
        multi_viewer_session.unregister_viewer(conn.name)
        if multi_viewer_session.controller:
            for c in list(clients):
                c.role = multi_viewer_session.get_role(c.name)

        if getattr(conn, "rtc_session", None) is not None:
            try:
                asyncio.create_task(conn.rtc_session.close())
            except Exception:
                pass
            conn.rtc_session = None
        broadcast_event("clients", len(clients))
        broadcast_event("log", "Viewer rời khỏi: %s %s (còn %d)" % (conn.name, reason, len(clients)))
        broadcast_event("history", ("viewer", f"Ngắt: {conn.name} {reason}"))
        await broadcast_json({"type": "clients", "n": len(clients)})
        await _broadcast_viewer_roles()
        # Audit: ghi sự kiện kết thúc phiên
        try:
            _audit.record_event(
                event="session_end",
                device_id=getattr(conn, "device_id", conn.name),
                details={"viewer": conn.name, "reason": reason or "normal"},
            )
        except Exception:
            pass
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
            try:
                _audit.record_event(
                    event="auth_ok",
                    device_id=device_id,
                    auth_method="resume_token",
                    details={"viewer": conn.name},
                )
            except Exception:
                pass
            return True
        counters["auth_fails"] += 1
        try:
            _audit.record_event(
                event="auth_fail",
                device_id=device_id,
                auth_method="resume_token",
                details={"viewer": conn.name, "reason": "invalid_or_expired"},
            )
        except Exception:
            pass
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
            _audit.record_event(
                event="auth_fail",
                device_id=device_id,
                auth_method="password",
                details={"viewer": conn.name, "reason": "wrong_id_or_password"},
            )
        except Exception:
            pass
        try:
            await conn.send_json({"type": "auth_fail", "message": "Sai mã máy hoặc mật khẩu"})
        except Exception:
            pass
        return False
    try:
        _audit.record_event(
            event="auth_ok",
            device_id=device_id,
            auth_method="password",
            details={"viewer": conn.name},
        )
    except Exception:
        pass
    return True


async def handle_client_message(conn, msg):
    """Xử lý 1 JSON message từ viewer (đã xác thực).

    Các loại message yêu cầu quyền điều khiển (input, clipboard_set, settings)
    bị chặn hoàn toàn ở server-side khi viewer ở chế độ view_only — KHÔNG phụ
    thuộc vào cờ phía client.
    """
    if not isinstance(msg, dict):
        return
    t = msg.get("type")
    counters["events"] += 1

    # --- Kiểm tra view_only: chặn mọi thao tác điều khiển ---
    _is_view_only = getattr(conn, "view_only", False)
    _CONTROL_TYPES = {"input", "clipboard_set", "settings", "file_offer", "file_chunk", "file_abort"}
    if _is_view_only and t in _CONTROL_TYPES:
        log(f"[view_only] Chặn message type='{t}' từ {conn.name}")
        await conn.send_json({
            "type": "error",
            "code": "view_only",
            "message": "Kết nối chỉ xem — thao tác điều khiển bị từ chối",
        })
        return

    if t == "input":
        await _handle_input(conn, msg)
    elif t == "request_controller":
        if _is_view_only:
            await conn.send_json({"type": "error", "message": "Phiên chỉ xem không được cấp quyền điều khiển"})
            return
        if multi_viewer_session.set_controller(conn.name):
            for c in list(clients):
                c.role = multi_viewer_session.get_role(c.name)
            log(f"Viewer {conn.name} được cấp quyền Controller chính")
            await _broadcast_viewer_roles()
    elif t == "release_controller":
        if multi_viewer_session.controller == conn.name:
            other = next((c for c in list(clients) if c != conn and not getattr(c, "view_only", False)), None)
            if other:
                multi_viewer_session.set_controller(other.name)
            else:
                conn.role = "viewer"
                multi_viewer_session.controller = None
            for c in list(clients):
                c.role = multi_viewer_session.get_role(c.name)
            await _broadcast_viewer_roles()
    elif t == "settings":
        await _handle_settings(conn, msg)
    elif t == "file_offer":
        await _handle_file_offer(conn, msg)
    elif t == "file_chunk":
        await _handle_file_chunk(conn, msg)
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
            log(f"{conn.name} hỗ trợ tile frame (0x02)")
        conn.request_keyframe()
    elif t == "keyframe":
        # Viewer yêu cầu keyframe toàn khung (ví dụ: sau khi mất gói)
        conn.request_keyframe()
    elif t == "rtc_offer":
        await _handle_rtc_offer(conn, msg)
    elif t == "rtc_ice":
        await _handle_rtc_ice(conn, msg)
    elif t == "rtc_bye":
        await _handle_rtc_bye(conn, msg)
    # bỏ qua các type khác


_latest_frame_arr = None


def get_latest_frame():
    """Lấy frame numpy RGB/BGR mới nhất từ capturer để cấp cho WebRTC track."""
    return _latest_frame_arr


async def _handle_rtc_offer(conn, msg):
    """Xử lý rtc_offer từ viewer (LAN hoặc qua Relay)."""
    offer_sdp = msg.get("sdp")
    if not offer_sdp:
        return
    log(f"Nhận rtc_offer từ {conn.name} — khởi tạo WebRtcPeerSession")
    try:
        from transport.webrtc import WebRtcPeerSession

        # WASAPI audio capturer: chỉ mở stream thu thật khi cfg cho phép audio
        audio_allowed = bool(cfg.get("audio_enabled", False)) if isinstance(cfg, dict) else False
        audio_capturer = None
        if audio_allowed:
            try:
                from audio import WasapiLoopbackCapturer
                if WasapiLoopbackCapturer.is_available():
                    audio_capturer = WasapiLoopbackCapturer()
                    audio_capturer.start()
                    log(f"Bắt đầu thu âm thanh WASAPI Loopback cho {conn.name}")
                    try:
                        _audit.record_event(
                            event="audio_stream_started",
                            device_id=getattr(conn, "device_id", conn.name),
                            details={"capturer": "wasapi_loopback"},
                        )
                    except Exception:
                        pass
            except Exception as exc:
                log(f"Không thể khởi tạo WASAPI audio: {exc}")
                audio_capturer = None

        session = WebRtcPeerSession(
            conn=conn,
            get_frame_fn=get_latest_frame,
            on_message_fn=handle_client_message,
            audio_capturer=audio_capturer,
            audio_allowed=audio_allowed,
        )
        answer_sdp = await session.handle_offer(str(offer_sdp))
        conn.rtc_session = session
        await conn.send_json({"type": "rtc_answer", "sdp": answer_sdp})
        log(f"Đã gửi rtc_answer tới {conn.name}")
        broadcast_event("history", ("webrtc", f"WebRTC kết nối: {conn.name}"))
    except Exception as e:
        log(f"Lỗi thiết lập WebRTC offer cho {conn.name}: {e}")
        await conn.send_json({"type": "rtc_error", "message": str(e)})


async def _handle_rtc_ice(conn, msg):
    """Xử lý rtc_ice candidate từ viewer."""
    session = getattr(conn, "rtc_session", None)
    if session:
        cand = msg.get("candidate")
        if cand:
            await session.add_ice_candidate(cand)


async def _handle_rtc_bye(conn, msg):
    """Xử lý rtc_bye ngắt luồng WebRTC và fallback về JPEG."""
    session = getattr(conn, "rtc_session", None)
    if session:
        await session.close()
        conn.rtc_session = None
        conn.request_keyframe()
        log(f"WebRTC phiên ngắt kết nối bởi {conn.name}")


async def _handle_file_offer(conn, msg):
    """Xử lý yêu cầu gửi file từ viewer."""
    import os
    from file_transfer import FileTransferSession, validate_file_offer
    if not validate_file_offer(msg):
        await conn.send_json({"type": "file_reject", "id": str(msg.get("id", "")), "reason": "invalid_offer"})
        return
    transfer_id = str(msg["id"])
    file_name = str(msg["name"])
    file_size = int(msg["size"])
    sha256 = str(msg["sha256"])

    dest_dir = getattr(conn, "download_dir", None) or os.path.join(os.path.expanduser("~"), "Downloads")
    os.makedirs(dest_dir, exist_ok=True)
    try:
        session = FileTransferSession(
            transfer_id=transfer_id,
            file_name=file_name,
            file_size=file_size,
            expected_sha256=sha256,
            destination_dir=dest_dir,
            allowlist=[dest_dir],
            chunk_size=int(msg.get("chunk_size") or 64 * 1024),
        )
        _file_sessions[transfer_id] = session
        log(f"Chấp nhận file offer: '{file_name}' ({file_size} bytes) từ {conn.name}")
        broadcast_event("history", ("file", f"Nhận file: {file_name} ({file_size} B)"))
        try:
            _audit.record_event(
                event="file_transfer_offer",
                device_id=getattr(conn, "device_id", conn.name),
                details={"file_name": file_name, "file_size": file_size},
            )
        except Exception:
            pass
        await conn.send_json(session.accept())
    except Exception as e:
        log(f"Từ chối file offer {transfer_id}: {e}")
        await conn.send_json({"type": "file_reject", "id": transfer_id, "reason": str(e)})


async def _handle_file_chunk(conn, msg):
    """Xử lý từng chunk dữ liệu của file."""
    import base64
    import os
    transfer_id = str(msg.get("id", ""))
    session = _file_sessions.get(transfer_id)
    if not session:
        await conn.send_json({"type": "file_reject", "id": transfer_id, "reason": "unknown_session"})
        return
    seq = int(msg.get("seq", 0))
    raw_b64 = msg.get("data", "")
    is_final = bool(msg.get("final", False))
    try:
        data = base64.b64decode(raw_b64)
    except Exception:
        await conn.send_json({"type": "file_reject", "id": transfer_id, "reason": "bad_base64"})
        return

    ok = session.receive_chunk(seq, data, expect_final=is_final)
    if not ok:
        await conn.send_json({"type": "file_reject", "id": transfer_id, "reason": "chunk_validation_failed"})
        _file_sessions.pop(transfer_id, None)
        return

    await conn.send_json(session.build_ack(seq))
    if session.is_complete:
        out_path = os.path.join(session.destination_dir, session.file_name)
        try:
            with open(out_path, "wb") as f:
                for s in range(len(session._chunks)):
                    f.write(session._chunks[s])
            log(f"Lưu file hoàn tất: {out_path}")
            broadcast_event("history", ("file", f"Đã lưu: {session.file_name}"))
            try:
                _audit.record_event(
                    event="file_transfer_complete",
                    device_id=getattr(conn, "device_id", conn.name),
                    details={"file_name": session.file_name, "size": session.file_size},
                )
            except Exception:
                pass
            await conn.send_json(session.build_done())
        except Exception as e:
            log(f"Lỗi ghi file {out_path}: {e}")
            await conn.send_json({"type": "file_reject", "id": transfer_id, "reason": "write_failed"})
        finally:
            _file_sessions.pop(transfer_id, None)


async def _handle_input(conn, msg):
    if getattr(conn, "role", "controller") == "viewer" or not multi_viewer_session.can_send_input(conn.name):
        log(f"[controller_only] Từ chối input từ viewer phụ {conn.name}")
        return

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
                px = meta["left"] + max(0, min(meta["width"] - 1, round(fx)))
                py = meta["top"] + max(0, min(meta["height"] - 1, round(fy)))
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
            from multi_viewer import DEFAULT_PROHIBITED
            current_set = {str(m).lower() for m in mods} | {key.lower()}
            prohibited_sets = [{part for part in item.split("+")} for item in DEFAULT_PROHIBITED]
            if current_set in prohibited_sets or key.lower() in DEFAULT_PROHIBITED:
                log(f"[macro_policy] Chặn phím cấm: {mods}+{key}")
                return
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
        log(f"Service input lỗi: {e}")
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
            log(f"Giữ máy thức (ngăn sleep): {state}")
            broadcast_event("history", ("setting", f"Ngăn máy tính sleep: {state}"))
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
        return f"(lỗi clipboard: {e})"


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
            log(f"Service grab lỗi ({e}) — tạm quay về chụp trực tiếp")
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
                log(f"capturer.stop() lỗi: {exc}")
            _capturer = None
        cap = make_capturer(prefer_dxgi=True)
        try:
            cap.start(monitor)
            _capturer = cap
            _capturer_monitor = monitor
            log("Capturer '%s' đã bắt đầu (monitor=%d)" % (cap.name, monitor))
        except Exception as exc:
            log(f"Capturer '{cap.name}' start lỗi ({exc}) → fallback MSS")
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
                global _latest_frame_arr
                _latest_frame_arr = arr
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
            log(f"stream_loop lỗi: {e}")
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
