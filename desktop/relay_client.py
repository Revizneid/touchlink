"""Kết nối ra relay server để nhận kết nối từ xa qua internet (outbound only).

Sprint 0.3:
- Tự kết nối lại với backoff + jitter (1–30s, cap 30s)
- Trạng thái rõ ràng: stopped / connecting / registered / retrying / error
  được broadcast qua core.broadcast_event("relay", status)
- Tích hợp consent: hỏi người dùng trước khi cho viewer vào (nếu cấu hình bật)
"""
from __future__ import annotations

import asyncio
import base64
import json
import random

import aiohttp
import core
import secure
from aiohttp import WSMsgType
from protocol import CAPS, PROTOCOL_VERSION
from security.audit import AuditLogger as _AuditLogger

# Singleton audit logger dùng chung với core (sẽ ghi vào cùng file JSONL)
_audit: _AuditLogger = _AuditLogger()

# Thứ tự backoff (giây): 1, 2, 4, 8, 15, 30
_BACKOFF_BASE = 1
_BACKOFF_MAX  = 30
_JITTER_MAX   = 3.0  # giây jitter ngẫu nhiên cộng thêm để tránh thundering herd
_CONNECT_TIMEOUT_S = 60
_WS_CLOSE_TIMEOUT_S = 60


def _next_backoff(current: float) -> float:
    """Tính backoff tiếp theo: nhân đôi + jitter, cap tại _BACKOFF_MAX."""
    return min(current * 2, _BACKOFF_MAX) + random.uniform(0, _JITTER_MAX)


def normalize_relay_url(url: str) -> str:
    """Chuẩn hóa URL relay: hỗ trợ http/https/ws/wss và đảm bảo có /ws."""
    u = (url or "").strip()
    if not u:
        return ""
    if u.lower().startswith("http://"):
        u = "ws://" + u[7:]
    elif u.lower().startswith("https://"):
        u = "wss://" + u[8:]
    elif not u.lower().startswith(("ws://", "wss://")):
        u = "wss://" + u
    u = u.rstrip("/")
    if not u.lower().endswith("/ws"):
        u = u + "/ws"
    return u


class RelayClient:
    def __init__(self):
        self.task = None
        self.running = False
        self.session = None
        self.ws = None
        self.conn = None
        self.status = "stopped"
        self._last_err: str | None = None
        self._retry_delay: float | None = None  # override delay (e.g. ID đang bị giữ)
        self.e2e = None                         # E2EChannel cho phiên hiện tại
        self.e2e_fingerprint = ""               # Mã vân tay E2E 8 ký tự
        self._msg_queue: asyncio.Queue | None = None
        self._worker_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def _set_status(self, status: str, history_text: str | None = None) -> None:
        if self.status != status:
            self.status = status
            core.broadcast_event("relay", status)
            if history_text:
                core.broadcast_event("history", ("relay", history_text))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self, cfg: dict, events_q) -> None:
        if self.running:
            return
        self.running = True
        self._set_status("connecting")
        core.log("Relay: đang kết nối tới {}".format(cfg.get("relay_url")))
        self.task = asyncio.create_task(self._run(cfg))

    async def stop(self) -> None:
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
        await self._cleanup()
        self._set_status("stopped")
        core.log("Relay: đã ngắt kết nối")

    async def _cleanup(self) -> None:
        self.e2e = None
        self.e2e_fingerprint = ""
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
        self._msg_queue = None
        if self.conn:
            await core.remove_client(self.conn, "(relay ngắt)")
            self.conn = None
        if self.ws:
            try:
                await self.ws.close()
            except (ConnectionError, OSError):
                pass
            self.ws = None
        if self.session:
            try:
                await self.session.close()
            except (ConnectionError, OSError):
                pass
            self.session = None
        # Không set stopped ở đây — _run() quyết định trạng thái tiếp theo

    async def _process_viewer_queue(self) -> None:
        """Xử lý tuần tự các message từ viewer theo đúng thứ tự FIFO (không bị đảo lộn)."""
        while self.running and self._msg_queue is not None:
            try:
                msg = await self._msg_queue.get()
                if self.conn:
                    await core.handle_client_message(self.conn, msg)
                self._msg_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                core.log(f"Relay client message error: {e}")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _run(self, cfg: dict) -> None:
        backoff = float(_BACKOFF_BASE)
        while self.running:
            self._set_status("connecting", None)
            try:
                relay_url = normalize_relay_url(cfg.get("relay_url", ""))
                self.session = aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=_CONNECT_TIMEOUT_S)
                )
                self.ws = await self.session.ws_connect(
                    relay_url,
                    heartbeat=20,
                    timeout=aiohttp.ClientWSTimeout(
                        ws_close=_WS_CLOSE_TIMEOUT_S,
                    ),
                )
                from wol import get_local_mac_address
                local_mac = str(cfg.get("mac_address") or get_local_mac_address())
                await self.ws.send_json(
                    {
                        "type": "register",
                        "device_id": str(cfg.get("device_id", "")),
                        "mac_address": local_mac,
                    }
                )
                # Chờ registered / error
                first = await asyncio.wait_for(self.ws.__anext__(), timeout=_CONNECT_TIMEOUT_S)
                if first.type == WSMsgType.TEXT:
                    d = json.loads(first.data)
                    if d.get("type") == "registered":
                        pass  # OK
                    elif d.get("type") == "error":
                        err_msg = d.get("message", "relay error")
                        if "đã đăng ký" in err_msg or "đã có máy khác" in err_msg:
                            self._retry_delay = 10.0
                        raise RuntimeError(err_msg)
                    # else: tiếp tục — có thể relay không gửi registered
                elif first.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                    raise ConnectionError("relay closed during register")

                backoff = float(_BACKOFF_BASE)
                self._last_err = None
                core.log("Relay: đã đăng ký mã máy {}".format(cfg.get("device_id")))
                self._set_status("registered",
                                 "Đã đăng ký mã máy {} trên relay".format(cfg.get("device_id")))

                # Vòng lặp nhận message
                async for msg in self.ws:
                    if msg.type == WSMsgType.TEXT:
                        await self._on_text(cfg, json.loads(msg.data))
                    elif msg.type == WSMsgType.BINARY:
                        if self.conn:
                            try:
                                await self.conn.send_bytes(msg.data)
                            except ConnectionError:
                                pass
                    elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                        break

            except asyncio.CancelledError:
                raise
            except Exception as e:
                err = str(e)
                if err != self._last_err:
                    self._last_err = err
                    core.log(f"Relay: mất kết nối ({err})")
            finally:
                await self._cleanup()

            if not self.running:
                break

            delay = self._retry_delay if self._retry_delay is not None else backoff
            self._retry_delay = None
            self._set_status("retrying",
                             f"Relay: thử lại sau {delay:.0f}s")
            core.log(f"Relay: thử lại sau {delay:.1f}s")
            await asyncio.sleep(delay)
            backoff = _next_backoff(backoff)

        self._set_status("stopped")

    # ------------------------------------------------------------------
    # Xử lý message từ relay
    # ------------------------------------------------------------------

    async def _on_text(self, cfg: dict, data: dict) -> None:
        t = data.get("type")
        if t == "auth":
            await self._handle_auth(cfg, data)
        elif t == "unbind":
            if self.conn:
                await core.remove_client(self.conn, "(relay unbind)")
                self.conn = None
        elif t == "viewer_msg":
            inner = data.get("data")
            if self.conn and isinstance(inner, dict):
                # Giải mã nếu gói tin được bảo vệ E2E
                if inner.get("type") == "e2e" and self.e2e is not None:
                    try:
                        raw_cipher = base64.b64decode(inner.get("c", ""))
                        decrypted_bytes = self.e2e.decrypt(raw_cipher)
                        inner = json.loads(decrypted_bytes.decode("utf-8"))
                    except Exception as exc:
                        core.log(f"Relay E2E giải mã thất bại: {exc}")
                        return

                if inner.get("type") == "hello":
                    self.conn.peer_v = int(inner.get("v") or 1)
                    self.conn.peer_caps = list(inner.get("caps") or [])
                    self.conn.caps = list(inner.get("caps") or [])
                    core.log(f"Relay viewer hello: v={self.conn.peer_v} caps={self.conn.peer_caps}")
                    await core.handle_client_message(self.conn, inner)
                elif self._msg_queue is not None:
                    await self._msg_queue.put(inner)
                else:
                    await core.handle_client_message(self.conn, inner)
        elif t == "send_wol":
            # Yêu cầu phát WoL magic packet trong mạng LAN nội bộ
            target_mac = str(data.get("target_mac") or "").strip()
            if target_mac:
                from wol import send_magic_packet
                ok = send_magic_packet(target_mac)
                core.log(f"Đã phát WoL magic packet tới {target_mac} (kết quả: {ok})")
        elif t == "error":
            msg_text = str(data.get("message", "?"))
            if msg_text != self._last_err:
                self._last_err = msg_text
                core.log(f"Relay: {msg_text}")
                core.broadcast_event("history", ("relay", f"Lỗi: {msg_text}"))
            self._set_status("error")
            if "đã đăng ký" in msg_text or "đã có máy khác" in msg_text:
                self._retry_delay = 60.0

    async def _handle_auth(self, cfg: dict, data: dict) -> None:
        """Xử lý yêu cầu auth từ relay: hỏi consent (nếu bật), xác minh mật khẩu hoặc resume_token."""
        password = str(data.get("password") or "")
        resume_token = str(data.get("resume_token") or "")
        viewer_ip = str(data.get("viewer_ip") or "relay viewer")

        # Xác minh mật khẩu hoặc resume_token
        ok = False
        auth_method = "relay_password"
        if resume_token:
            auth_method = "resume_token"
            ok = secure.consume_resume_token(resume_token, str(cfg.get("device_id", "")))
        elif password:
            ok = secure.verify_password(password, cfg.get("password_enc") or "")

        if not ok:
            core.counters["auth_fails"] += 1
            try:
                _audit.record_event(
                    event="auth_fail",
                    ip=viewer_ip,
                    auth_method=auth_method,
                    details={"reason": "invalid_credentials"},
                )
            except Exception:
                pass
            await self.ws.send_json(
                {"type": "auth_result", "ok": False, "message": "Sai mật khẩu"}
            )
            return

        # Hỏi consent nếu cần
        try:
            import consent as consent_mod
            headless = cfg.get("_headless", False)
            result = await consent_mod.ask_async(
                viewer_name=viewer_ip,
                is_relay=True,
                cfg=cfg,
                headless=headless,
            )
        except (AttributeError, ImportError, OSError, RuntimeError, TypeError, ValueError) as e:
            core.log(f"Consent lỗi ({e}) → cho phép")
            result = "allow"

        if result == "deny":
            try:
                _audit.record_event(
                    event="consent_denied",
                    ip=viewer_ip,
                    auth_method=auth_method,
                    permission="deny",
                )
            except Exception:
                pass
            await self.ws.send_json(
                {"type": "auth_result", "ok": False, "message": "Người dùng từ chối kết nối"}
            )
            return

        # Tạo kết nối viewer
        conn = core.ClientConn(
            name=f"Relay viewer ({viewer_ip})",
            send_json=lambda d: self._to_viewer_json(d),
            send_bytes=lambda b: self._to_viewer_bytes(b),
            close=lambda: self._unbind(),
        )
        # view_only: tắt input handling
        if result == "view_only":
            conn.view_only = True

        self.conn = conn

        # Khởi tạo queue tuần tự cho viewer
        if self._worker_task:
            self._worker_task.cancel()
            self._worker_task = None
        self._msg_queue = asyncio.Queue()
        self._worker_task = asyncio.create_task(self._process_viewer_queue())

        # Thiết lập E2EChannel nếu có password
        transcript = f"touchlink-relay:{cfg.get('device_id', '')}"
        if password:
            try:
                from security.e2e import E2EChannel
                self.e2e = E2EChannel.from_passcode("agent", password, transcript)
                self.e2e_fingerprint = self.e2e.compute_fingerprint()
                core.log(f"Relay E2E kích hoạt (fingerprint: {self.e2e_fingerprint})")
                core.broadcast_event("history", ("relay", f"E2E bảo mật (Mã: {self.e2e_fingerprint})"))
            except Exception as exc:
                core.log(f"Không thể khởi tạo E2EChannel: {exc}")
                self.e2e = None
        else:
            self.e2e = None

        auth_payload = core.auth_ok_payload()
        if self.e2e is not None:
            auth_payload["e2e"] = True
            auth_payload["e2e_fingerprint"] = self.e2e_fingerprint
            auth_payload["transcript"] = transcript
        await self.ws.send_json(
            {"type": "auth_result", "ok": True, "data": auth_payload}
        )
        # Hello handshake v2
        await self._to_viewer_json(
            {"type": "hello", "v": PROTOCOL_VERSION, "caps": CAPS}
        )
        conn.peer_v = 1
        conn.peer_caps: list[str] = []
        # Audit: ghi sự kiện kết nối relay thành công
        try:
            _audit.record_event(
                event="auth_ok",
                ip=viewer_ip,
                auth_method="relay_password",
                permission=result,
                details={"view_only": result == "view_only", "e2e": self.e2e is not None},
            )
        except Exception:
            pass
        await core.add_client(conn)

    # ------------------------------------------------------------------
    # Helpers gửi message về viewer qua relay
    # ------------------------------------------------------------------

    async def _to_viewer_json(self, d: dict) -> None:
        if self.ws and not self.ws.closed:
            if self.e2e is not None:
                try:
                    payload_bytes = json.dumps(d, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
                    cipher = self.e2e.encrypt(payload_bytes)
                    b64 = base64.b64encode(cipher).decode("ascii")
                    await self.ws.send_json({"type": "agent_msg", "data": {"type": "e2e", "c": b64}})
                    return
                except Exception as exc:
                    core.log(f"Relay E2E mã hóa thất bại: {exc}")
            await self.ws.send_json({"type": "agent_msg", "data": d})

    async def _to_viewer_bytes(self, b: bytes) -> None:
        if self.ws and not self.ws.closed:
            await self.ws.send_bytes(b)

    async def _unbind(self) -> None:
        if self.ws and not self.ws.closed:
            try:
                await self.ws.send_json({"type": "unbind"})
            except (ConnectionError, OSError):
                pass


relay_client = RelayClient()


async def start_if_enabled(cfg: dict) -> None:
    if cfg.get("relay_enabled") and cfg.get("relay_url"):
        await relay_client.start(cfg, core.events)
