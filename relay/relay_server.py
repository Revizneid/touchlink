"""TouchLink Relay — máy chủ trung gian chạy trên VPS (kết nối qua internet).

Máy tính kết nối ra relay (outbound), điện thoại kết nối tới relay và ghép cặp
theo mã máy (ID). Relay KHÔNG biết mật khẩu: nó chuyển mật khẩu về máy tính để
máy tính tự xác minh.

Chạy:  python relay_server.py --port 8430 [--web ../web]
Khuyến nghị đặt sau reverse proxy có TLS (wss://).

Biến môi trường (hoặc tham số CLI):
  PORT                 Cổng lắng nghe (mặc định 8430)
  RELAY_MAX_CONNS_IP   Kết nối WS tối đa/phút/IP (mặc định 20)
  RELAY_MAX_CONN_ID    Lần connect tới 1 ID/phút/IP (mặc định 10)
  RELAY_MAX_CONN_TOTAL Lần connect tới 1 ID/phút/ID (mặc định 30)
  RELAY_MAX_AUTH_FAIL  Auth thất bại tối đa trước khi khóa (mặc định 5)
  RELAY_AUTH_BAN_S     Giây khóa sau khi vượt ngưỡng auth fail (mặc định 180)
  RELAY_MAX_CONNS_TOTAL Kết nối đồng thời tối đa/IP (mặc định 10)
  RELAY_METRICS_TOKEN  Token bảo vệ /metrics (tùy chọn)
  RELAY_TRUSTED_PROXY  "1" để tin tưởng X-Forwarded-For (mặc định 0)
  RELAY_ANONYMIZE_LOGS "1" để ẩn octet cuối IP trong log (mặc định 0)
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import json
import logging
import os
import random
import re
import sys
import time
from typing import Any

from aiohttp import WSMsgType, web

# ---------------------------------------------------------------------------
# Hằng số giới hạn kích thước
# ---------------------------------------------------------------------------
MAX_JSON_SIZE: int = 64 * 1024        # 64 KB — JSON message tối đa
MAX_FRAME_SIZE: int = 4 * 1024 * 1024 # 4 MB  — binary frame tối đa
DEVICE_ID_RE = re.compile(r"^[2-9]{9}$")  # 9 chữ số 2-9 (theo gen_device_id)

# Thông báo chung cho mọi lỗi kết nối viewer (chống dò ID)
_UNAVAILABLE_MSG = "Máy tính không khả dụng"

# ---------------------------------------------------------------------------
# Logging có cấu trúc (JSON lines)
# ---------------------------------------------------------------------------

class _JsonFormatter(logging.Formatter):
    """Formatter xuất log dạng JSON Lines — không log nội dung nhạy cảm."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        doc: dict[str, Any] = {
            "t": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "msg": record.getMessage(),
        }
        if hasattr(record, "extra"):
            doc.update(record.extra)  # type: ignore[arg-type]
        return json.dumps(doc, ensure_ascii=False)


def _make_logger(anonymize: bool) -> logging.Logger:
    logger = logging.getLogger("touchlink.relay")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(_JsonFormatter())
        logger.addHandler(h)
    logger.anonymize = anonymize  # type: ignore[attr-defined]
    return logger


def _mask_ip(ip: str, anonymize: bool) -> str:
    """Ẩn octet cuối (IPv4) hoặc phần cuối (IPv6) nếu --anonymize-logs."""
    if not anonymize:
        return ip
    if ":" in ip:  # IPv6
        parts = ip.split(":")
        return ":".join(parts[:-1]) + ":xxxx"
    parts = ip.split(".")
    if len(parts) == 4:
        return ".".join(parts[:3]) + ".x"
    return ip


def _log(logger: logging.Logger, level: str, msg: str, **extra: Any) -> None:
    record = logging.LogRecord(
        name=logger.name, level=getattr(logging, level),
        pathname="", lineno=0, msg=msg, args=(), exc_info=None,
    )
    record.extra = extra  # type: ignore[attr-defined]
    logger.handle(record)


# ---------------------------------------------------------------------------
# Sliding-window rate limiter (pure asyncio, không cần thư viện ngoài)
# ---------------------------------------------------------------------------

class SlidingWindow:
    """Sliding window counter — mỗi key có một deque timestamp.

    Thread-safety: chỉ gọi từ asyncio event loop (single-thread).
    """

    def __init__(self, max_calls: int, window_s: float) -> None:
        self.max_calls = max_calls
        self.window_s = window_s
        self._calls: dict[str, collections.deque[float]] = {}

    def _clean(self, key: str, now: float) -> None:
        dq = self._calls.get(key)
        if dq is None:
            return
        cutoff = now - self.window_s
        while dq and dq[0] < cutoff:
            dq.popleft()

    def hit(self, key: str) -> bool:
        """Ghi nhận 1 lần gọi. Trả True nếu đang trong giới hạn, False nếu vượt."""
        now = time.monotonic()
        self._clean(key, now)
        dq = self._calls.setdefault(key, collections.deque())
        if len(dq) >= self.max_calls:
            return False
        dq.append(now)
        return True

    def count(self, key: str) -> int:
        """Số lần gọi trong cửa sổ hiện tại."""
        now = time.monotonic()
        self._clean(key, now)
        return len(self._calls.get(key, []))

    def reset(self, key: str) -> None:
        self._calls.pop(key, None)


class BanList:
    """Danh sách khoá (IP, ID) với thời gian hết hạn."""

    def __init__(self) -> None:
        self._bans: dict[str, float] = {}  # key -> expire monotonic time

    def ban(self, key: str, duration_s: float) -> None:
        self._bans[key] = time.monotonic() + duration_s

    def is_banned(self, key: str) -> bool:
        exp = self._bans.get(key)
        if exp is None:
            return False
        if time.monotonic() >= exp:
            self._bans.pop(key, None)
            return False
        return True

    def remaining(self, key: str) -> float:
        exp = self._bans.get(key)
        if exp is None:
            return 0.0
        return max(0.0, exp - time.monotonic())


# ---------------------------------------------------------------------------
# Trạng thái toàn cục relay
# ---------------------------------------------------------------------------

class RelayState:
    """Trạng thái toàn cục: agents, limiters, bans, metrics."""

    def __init__(self, cfg: "RelayConfig") -> None:
        self.cfg = cfg
        # agents: device_id -> {"ws", "viewer", "bound", "device", "ip"}
        self.agents: dict[str, dict[str, Any]] = {}
        # Kết nối đồng thời / IP
        self.active_conns: dict[str, int] = {}

        # Rate limiters
        self.rl_ws_new = SlidingWindow(cfg.max_conns_ip, 60)      # WS mới/phút/IP
        self.rl_connect_ip = SlidingWindow(cfg.max_conn_id, 60)   # connect/phút/IP
        self.rl_connect_id = SlidingWindow(cfg.max_conn_total, 60) # connect/phút/ID
        self.rl_auth_fail = SlidingWindow(cfg.max_auth_fail, cfg.auth_window_s)

        self.bans = BanList()

        # Exponential backoff toàn cục khi nhiều auth fail
        self._global_fail_count: int = 0
        self._global_backoff: float = 0.0
        self._global_backoff_until: float = 0.0

        # Metrics
        self.m_total_conns: int = 0
        self.m_rejected: int = 0
        self.m_auth_fails: int = 0
        self.m_current_agents: int = 0
        self.m_current_viewers: int = 0

    def register_conn(self, ip: str) -> None:
        self.active_conns[ip] = self.active_conns.get(ip, 0) + 1
        self.m_total_conns += 1

    def unregister_conn(self, ip: str) -> None:
        n = self.active_conns.get(ip, 0)
        if n <= 1:
            self.active_conns.pop(ip, None)
        else:
            self.active_conns[ip] = n - 1

    def record_auth_fail(self, ip: str, device_id: str) -> None:
        key = f"{ip}:{device_id}"
        self.rl_auth_fail.hit(key)
        self.m_auth_fails += 1
        self._global_fail_count += 1
        # Exponential backoff: tăng độ trễ toàn cục
        if self._global_fail_count % 10 == 0:
            self._global_backoff = min(self._global_backoff * 2 + 1.0, 60.0)
            self._global_backoff_until = time.monotonic() + self._global_backoff

    def global_backoff_delay(self) -> float:
        remaining = self._global_backoff_until - time.monotonic()
        return max(0.0, remaining)

    def metrics_dict(self) -> dict[str, Any]:
        return {
            "total_connections": self.m_total_conns,
            "rejected": self.m_rejected,
            "auth_fails": self.m_auth_fails,
            "current_agents": self.m_current_agents,
            "current_viewers": self.m_current_viewers,
            "active_ips": len(self.active_conns),
        }


# ---------------------------------------------------------------------------
# Cấu hình
# ---------------------------------------------------------------------------

class RelayConfig:
    """Cấu hình relay — đọc từ CLI args + biến môi trường."""

    def __init__(self, args: argparse.Namespace) -> None:
        def _int(attr: str, env: str, default: int) -> int:
            v = os.environ.get(env)
            cli = getattr(args, attr, None)
            if cli is not None:
                return int(cli)
            if v is not None:
                return int(v)
            return default

        self.port: int = int(os.environ.get("PORT", args.port))
        self.web_dir: str = args.web
        self.trusted_proxy: bool = (
            os.environ.get("RELAY_TRUSTED_PROXY", "0") == "1"
            or getattr(args, "trusted_proxy", False)
        )
        self.anonymize_logs: bool = (
            os.environ.get("RELAY_ANONYMIZE_LOGS", "0") == "1"
            or getattr(args, "anonymize_logs", False)
        )
        # CLI arg ưu tiên trước env var
        _cli_token = getattr(args, "metrics_token", None) or ""
        self.metrics_token: str = _cli_token or os.environ.get("RELAY_METRICS_TOKEN", "")
        self.max_conns_ip: int = _int("max_conns_ip", "RELAY_MAX_CONNS_IP", 20)
        self.max_conn_id: int = _int("max_conn_id", "RELAY_MAX_CONN_ID", 10)
        self.max_conn_total: int = _int("max_conn_total", "RELAY_MAX_CONN_TOTAL", 30)
        self.max_auth_fail: int = _int("max_auth_fail", "RELAY_MAX_AUTH_FAIL", 5)
        self.auth_ban_s: int = _int("auth_ban_s", "RELAY_AUTH_BAN_S", 180)
        self.auth_window_s: float = 300.0  # 5 phút
        self.max_conns_total_ip: int = _int(
            "max_conns_total_ip", "RELAY_MAX_CONNS_TOTAL", 10
        )
        self.pair_timeout_s: float = 30.0  # ghép cặp tối đa 30s


# ---------------------------------------------------------------------------
# Lấy IP thật
# ---------------------------------------------------------------------------

def get_peer_ip(request: web.Request, trusted_proxy: bool, anonymize: bool) -> str:
    """Lấy IP client: tin X-Forwarded-For chỉ khi trusted_proxy=True."""
    if trusted_proxy:
        xff = request.headers.get("X-Forwarded-For", "")
        if xff:
            ip = xff.split(",")[0].strip()
            return _mask_ip(ip, anonymize)
        fwd = request.headers.get("Forwarded", "")
        m = re.search(r"for=[\"\[]?([^\]\";\s,]+)", fwd)
        if m:
            return _mask_ip(m.group(1).strip(), anonymize)
    peer = request.remote or "0.0.0.0"
    return _mask_ip(peer, anonymize)


# ---------------------------------------------------------------------------
# Helper: gửi JSON an toàn
# ---------------------------------------------------------------------------

async def _try_send(ws: web.WebSocketResponse, data: dict) -> None:
    try:
        await ws.send_json(data)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Delay giả lập đồng nhất cho mọi lỗi connect (chống dò ID)
# ---------------------------------------------------------------------------

async def _unavailable_delay() -> None:
    """Jitter 50–150ms để phản hồi lỗi connect luôn mất thời gian gần nhau."""
    await asyncio.sleep(random.uniform(0.05, 0.15))


# ---------------------------------------------------------------------------
# WebSocket handler chính
# ---------------------------------------------------------------------------

async def ws_handler(
    request: web.Request,
    state: RelayState,
    logger: logging.Logger,
) -> web.WebSocketResponse:
    cfg = state.cfg
    anon = cfg.anonymize_logs
    ip = get_peer_ip(request, cfg.trusted_proxy, anon)

    # --- Giới hạn kết nối đồng thời/IP ---
    if state.active_conns.get(ip, 0) >= cfg.max_conns_total_ip:
        state.m_rejected += 1
        _log(logger, "WARNING", "reject_max_conns", ip=ip)
        raise web.HTTPTooManyRequests(reason="Quá nhiều kết nối từ IP này")

    # --- Rate-limit: WS mới/phút/IP ---
    if not state.rl_ws_new.hit(ip):
        state.m_rejected += 1
        _log(logger, "WARNING", "rate_limit_ws_new", ip=ip)
        raise web.HTTPTooManyRequests(reason="Quá nhiều kết nối mới — thử lại sau")

    ws = web.WebSocketResponse(
        heartbeat=25,
        max_msg_size=MAX_FRAME_SIZE,  # áp dụng cho cả binary; JSON check thủ công
    )
    await ws.prepare(request)
    state.register_conn(ip)

    role: str | None = None
    device_id: str | None = None
    rec: dict[str, Any] | None = None

    _log(logger, "INFO", "ws_connect", ip=ip)

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                # --- Giới hạn kích thước JSON ---
                if len(msg.data.encode()) > MAX_JSON_SIZE:
                    _log(logger, "WARNING", "msg_too_large", ip=ip,
                         size=len(msg.data.encode()))
                    await ws.close(code=1009, message=b"Message too large")
                    break

                try:
                    data: dict = json.loads(msg.data)
                except Exception:
                    continue
                if not isinstance(data, dict):
                    continue
                t = data.get("type")

                # ── REGISTER (agent) ──────────────────────────────────────
                if t == "register" and role is None:
                    did = str(data.get("device_id") or "").strip()
                    if not did:
                        await _try_send(ws, {"type": "error",
                                             "message": "Thiếu mã máy"})
                        continue
                    if not DEVICE_ID_RE.match(did):
                        await _try_send(ws, {"type": "error",
                                             "message": "Mã máy không hợp lệ"})
                        _log(logger, "WARNING", "invalid_device_id",
                             ip=ip, device_id=did[:20])
                        continue
                    # Kiểm tra agent cũ
                    old = state.agents.get(did)
                    if old and not old["ws"].closed and old["ws"] is not ws:
                        await _try_send(ws, {"type": "error",
                                             "message": "Mã máy đã có máy khác đăng ký"})
                        _log(logger, "WARNING", "register_conflict",
                             ip=ip, device_id=did)
                        continue
                    device_id = did
                    rec = {
                        "ws": ws, "viewer": None, "bound": False,
                        "device": did, "ip": ip,
                    }
                    state.agents[did] = rec
                    role = "agent"
                    state.m_current_agents += 1
                    await _try_send(ws, {"type": "registered"})
                    _log(logger, "INFO", "agent_registered", ip=ip,
                         device_id=did)

                # ── CONNECT (viewer) ──────────────────────────────────────
                elif t == "connect" and role is None:
                    did = str(data.get("device_id") or "").strip()
                    password = str(data.get("password") or "")

                    # Rate-limit: connect/phút/IP và /ID
                    if not state.rl_connect_ip.hit(ip):
                        state.m_rejected += 1
                        _log(logger, "WARNING", "rate_limit_connect_ip", ip=ip)
                        await _unavailable_delay()
                        await _try_send(ws, {
                            "type": "auth_result", "ok": False,
                            "message": "Quá nhiều yêu cầu — thử lại sau",
                        })
                        continue
                    if did and not state.rl_connect_id.hit(did):
                        state.m_rejected += 1
                        _log(logger, "WARNING", "rate_limit_connect_id",
                             device_id=did)
                        await _unavailable_delay()
                        await _try_send(ws, {
                            "type": "auth_result", "ok": False,
                            "message": "Quá nhiều yêu cầu — thử lại sau",
                        })
                        continue

                    # Ban list: (IP, ID)
                    ban_key = f"{ip}:{did}"
                    if state.bans.is_banned(ban_key):
                        state.m_rejected += 1
                        remain = int(state.bans.remaining(ban_key))
                        _log(logger, "WARNING", "connect_banned", ip=ip,
                             device_id=did, remain_s=remain)
                        await _unavailable_delay()
                        await _try_send(ws, {
                            "type": "auth_result", "ok": False,
                            "message": f"Bị khoá {remain}s do thử sai nhiều lần",
                        })
                        continue

                    # Global backoff
                    delay = state.global_backoff_delay()
                    if delay > 0:
                        await asyncio.sleep(min(delay, 60.0))

                    # Chống dò ID: mọi lỗi (ID lạ / offline / bận) → cùng message + delay
                    a = state.agents.get(did)
                    agent_ok = (
                        a is not None
                        and not a["ws"].closed
                        and a["viewer"] is None
                    )
                    if not agent_ok:
                        _log(logger, "INFO", "connect_unavailable", ip=ip,
                             device_id=did)
                        await _unavailable_delay()
                        await _try_send(ws, {
                            "type": "auth_result", "ok": False,
                            "message": _UNAVAILABLE_MSG,
                        })
                        continue

                    # Ghép cặp
                    device_id = did
                    role = "viewer"
                    rec = a
                    a["viewer"] = ws
                    a["viewer_ip"] = ip   # lưu để ghi nhận auth fail về sau
                    a["bound"] = False
                    state.m_current_viewers += 1
                    # Gửi password về agent để xác minh (relay không xem nội dung)
                    await _try_send(a["ws"], {"type": "auth", "password": password})
                    _log(logger, "INFO", "viewer_pairing", ip=ip,
                         device_id=did)

                    # Timeout ghép cặp (30s)
                    async def _pair_timeout(
                        _a: dict = a, _v: web.WebSocketResponse = ws,
                        _did: str = did,
                    ) -> None:
                        await asyncio.sleep(cfg.pair_timeout_s)
                        if _a.get("viewer") is _v and not _a.get("bound"):
                            _a["viewer"] = None
                            await _try_send(_v, {
                                "type": "auth_result", "ok": False,
                                "message": "Máy tính không phản hồi",
                            })
                            _log(logger, "WARNING", "pair_timeout", ip=ip,
                                 device_id=_did)

                    asyncio.create_task(_pair_timeout())

                # ── AUTH_RESULT (agent → relay → viewer) ──────────────────
                elif t == "auth_result" and role == "agent" and rec:
                    v = rec.get("viewer")
                    if v is None or v.closed:
                        continue
                    if data.get("ok"):
                        rec["bound"] = True
                        await _try_send(v, {
                            "type": "auth_result", "ok": True,
                            "data": data.get("data") or {},
                        })
                        await _try_send(ws, {"type": "bound"})
                        _log(logger, "INFO", "auth_ok",
                             device_id=device_id)
                    else:
                        # Ghi nhận auth fail để tính rate-limit và ban
                        viewer_ip = rec.get("viewer_ip", "?")
                        if device_id:
                            ban_key = f"{viewer_ip}:{device_id}"
                            state.record_auth_fail(viewer_ip, device_id)
                            fail_count = state.rl_auth_fail.count(ban_key)
                            if fail_count >= cfg.max_auth_fail:
                                state.bans.ban(ban_key, cfg.auth_ban_s)
                                _log(logger, "WARNING", "auth_ban",
                                     ip=viewer_ip, device_id=device_id,
                                     ban_s=cfg.auth_ban_s)
                        rec["viewer"] = None
                        await _try_send(v, {
                            "type": "auth_result", "ok": False,
                            "message": data.get("message") or "Sai mật khẩu",
                        })
                        _log(logger, "INFO", "auth_fail",
                             device_id=device_id)

                # ── VIEWER MESSAGE → AGENT ─────────────────────────────────
                elif role == "viewer" and rec and t != "connect":
                    await _try_send(rec["ws"], {"type": "viewer_msg", "data": data})

                # ── AGENT_MSG → VIEWER ────────────────────────────────────
                elif t == "agent_msg" and role == "agent" and rec:
                    v = rec.get("viewer")
                    if v is not None and not v.closed:
                        await _try_send(v, data.get("data") or {})

                # ── UNBIND (agent) ─────────────────────────────────────────
                elif t == "unbind" and role == "agent" and rec:
                    if rec.get("viewer") and not rec["viewer"].closed:
                        await _try_send(rec["viewer"], {"type": "unbind"})
                    rec["viewer"] = None

                # ── PING ──────────────────────────────────────────────────
                elif t == "ping":
                    await _try_send(ws, {"type": "pong", "t": data.get("t")})

            elif msg.type == WSMsgType.BINARY:
                # Frame từ agent → viewer
                if role == "agent" and rec:
                    if len(msg.data) > MAX_FRAME_SIZE:
                        _log(logger, "WARNING", "frame_too_large", ip=ip,
                             size=len(msg.data))
                        continue
                    v = rec.get("viewer")
                    if v is not None and not v.closed:
                        try:
                            await v.send_bytes(msg.data)
                        except Exception:
                            pass

            elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                break

    finally:
        state.unregister_conn(ip)
        if role == "agent" and device_id and state.agents.get(device_id) is rec:
            state.agents.pop(device_id, None)
            state.m_current_agents -= 1
            v = rec.get("viewer") if rec else None
            if v and not v.closed:
                await _try_send(v, {
                    "type": "auth_result", "ok": False,
                    "message": "Máy tính đã ngắt kết nối",
                })
            _log(logger, "INFO", "agent_disconnected", ip=ip,
                 device_id=device_id)
        elif role == "viewer" and rec:
            state.m_current_viewers -= 1
            if rec.get("viewer") is ws:
                rec["viewer"] = None
                if not rec["ws"].closed:
                    await _try_send(rec["ws"], {"type": "unbind"})
            _log(logger, "INFO", "viewer_disconnected", ip=ip,
                 device_id=device_id)

    return ws


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def make_app(args: argparse.Namespace) -> web.Application:
    cfg = RelayConfig(args)
    state = RelayState(cfg)
    logger = _make_logger(cfg.anonymize_logs)

    async def _ws(request: web.Request) -> web.WebSocketResponse:
        return await ws_handler(request, state, logger)

    routes = web.RouteTableDef()

    # /healthz — không lộ danh sách ID
    @routes.get("/healthz")
    async def healthz(_request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "app": "touchlink-relay"})

    # /metrics — bảo vệ bằng token tùy chọn
    @routes.get("/metrics")
    async def metrics(request: web.Request) -> web.Response:
        if cfg.metrics_token:
            auth = request.headers.get("Authorization", "")
            token = auth.removeprefix("Bearer ").strip()
            if token != cfg.metrics_token:
                raise web.HTTPUnauthorized(reason="Invalid token")
        return web.json_response(state.metrics_dict())

    # /api/relayinfo — số agents (không lộ device_id)
    @routes.get("/api/relayinfo")
    async def info(_request: web.Request) -> web.Response:
        return web.json_response({
            "app": "touchlink-relay",
            "agents_online": len(state.agents),
            "agents_busy": sum(
                1 for r in state.agents.values() if r.get("viewer")
            ),
        })

    routes.get("/ws")(_ws)

    app = web.Application()
    app.add_routes(routes)

    wd_path = os.path.abspath(args.web)
    if os.path.isdir(wd_path):
        async def index(_request: web.Request) -> web.Response:
            html_path = os.path.join(wd_path, "index.html")
            return web.Response(
                text=await _inject_mode(html_path),
                content_type="text/html",
            )
        app.router.add_get("/", index)
        app.router.add_static("/static/", wd_path)

    return app


async def _inject_mode(html_path: str) -> str:
    """Nhúng cờ relay vào index.html để web UI tự bật chế độ relay."""
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()
    if "__TOUCHLINK_MODE" not in html:
        html = html.replace(
            "</head>",
            "<script>window.__TOUCHLINK_MODE='relay'</script>\n</head>",
            1,
        )
    return html


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="TouchLink relay server")
    ap.add_argument("--port", type=int, default=8430)
    ap.add_argument(
        "--web",
        default=os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web"
        ),
        help="Thư mục web UI để phục vụ kèm",
    )
    ap.add_argument(
        "--trusted-proxy", action="store_true",
        help="Tin tưởng header X-Forwarded-For (chỉ dùng sau reverse proxy tin cậy)",
    )
    ap.add_argument(
        "--anonymize-logs", action="store_true",
        help="Ẩn octet cuối IP trong log",
    )
    ap.add_argument(
        "--metrics-token", default="",
        help="Token bảo vệ endpoint /metrics (để trống = không bảo vệ)",
    )
    ap.add_argument("--max-conns-ip", type=int, default=None,
                    help="WS mới tối đa/phút/IP (mặc định 20)")
    ap.add_argument("--max-conn-id", type=int, default=None,
                    help="connect/phút/IP tối đa (mặc định 10)")
    ap.add_argument("--max-conn-total", type=int, default=None,
                    help="connect/phút/ID tối đa (mặc định 30)")
    ap.add_argument("--max-auth-fail", type=int, default=None,
                    help="Số lần auth fail trước khi khoá (mặc định 5)")
    ap.add_argument("--auth-ban-s", type=int, default=None,
                    help="Giây khoá sau auth fail (mặc định 180)")
    ap.add_argument("--max-conns-total-ip", type=int, default=None,
                    help="Kết nối đồng thời tối đa/IP (mặc định 10)")
    return ap


def main() -> None:
    args = _build_parser().parse_args()
    app = make_app(args)
    cfg = RelayConfig(args)
    print(f"TouchLink relay chạy tại ws://0.0.0.0:{cfg.port}/ws")
    web.run_app(app, host="0.0.0.0", port=cfg.port, print=None)


if __name__ == "__main__":
    main()
