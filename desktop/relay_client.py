"""Kết nối ra relay server để nhận kết nối từ xa qua internet (outbound only).

Sprint 0.3:
- Tự kết nối lại với backoff + jitter (1–30s, cap 30s)
- Trạng thái rõ ràng: stopped / connecting / registered / retrying / error
  được broadcast qua core.broadcast_event("relay", status)
- Tích hợp consent: hỏi người dùng trước khi cho viewer vào (nếu cấu hình bật)
"""
from __future__ import annotations

import asyncio
import json
import random

import aiohttp
from aiohttp import WSMsgType

import core
from protocol import PROTOCOL_VERSION, CAPS, HELLO_TIMEOUT


# Thứ tự backoff (giây): 1, 2, 4, 8, 15, 30
_BACKOFF_BASE = 1
_BACKOFF_MAX  = 30
_JITTER_MAX   = 3.0  # giây jitter ngẫu nhiên cộng thêm để tránh thundering herd


def _next_backoff(current: float) -> float:
    """Tính backoff tiếp theo: nhân đôi + jitter, cap tại _BACKOFF_MAX."""
    return min(current * 2, _BACKOFF_MAX) + random.uniform(0, _JITTER_MAX)


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
        core.log("Relay: đang kết nối tới %s" % cfg.get("relay_url"))
        self.task = asyncio.create_task(self._run(cfg))

    async def stop(self) -> None:
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except Exception:
                pass
            self.task = None
        await self._cleanup()
        self._set_status("stopped")
        core.log("Relay: đã ngắt kết nối")

    async def _cleanup(self) -> None:
        if self.conn:
            await core.remove_client(self.conn, "(relay ngắt)")
            self.conn = None
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
            self.ws = None
        if self.session:
            try:
                await self.session.close()
            except Exception:
                pass
            self.session = None
        # Không set stopped ở đây — _run() quyết định trạng thái tiếp theo

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _run(self, cfg: dict) -> None:
        backoff = float(_BACKOFF_BASE)
        while self.running:
            self._set_status("connecting", None)
            try:
                self.session = aiohttp.ClientSession()
                self.ws = await self.session.ws_connect(
                    cfg.get("relay_url"),
                    heartbeat=20,
                    timeout=aiohttp.ClientWSTimeout(ws_close=10),
                )
                await self.ws.send_json(
                    {"type": "register", "device_id": str(cfg.get("device_id", ""))}
                )
                # Chờ registered / error
                first = await asyncio.wait_for(self.ws.__anext__(), timeout=10)
                if first.type == WSMsgType.TEXT:
                    d = json.loads(first.data)
                    if d.get("type") == "registered":
                        pass  # OK
                    elif d.get("type") == "error":
                        raise RuntimeError(d.get("message", "relay error"))
                    # else: tiếp tục — có thể relay không gửi registered
                elif first.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                    raise ConnectionError("relay closed during register")

                backoff = float(_BACKOFF_BASE)
                self._last_err = None
                core.log("Relay: đã đăng ký mã máy %s" % cfg.get("device_id"))
                self._set_status("registered",
                                 "Đã đăng ký mã máy %s trên relay" % cfg.get("device_id"))

                # Vòng lặp nhận message
                async for msg in self.ws:
                    if msg.type == WSMsgType.TEXT:
                        await self._on_text(cfg, json.loads(msg.data))
                    elif msg.type == WSMsgType.BINARY:
                        if self.conn:
                            try:
                                await self.conn.send_bytes(msg.data)
                            except Exception:
                                pass
                    elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                        break

            except asyncio.CancelledError:
                raise
            except Exception as e:
                err = str(e)
                if err != self._last_err:
                    self._last_err = err
                    core.log("Relay: mất kết nối (%s)" % err)
            finally:
                await self._cleanup()

            if not self.running:
                break

            delay = self._retry_delay if self._retry_delay is not None else backoff
            self._retry_delay = None
            self._set_status("retrying",
                             "Relay: thử lại sau %.0fs" % delay)
            core.log("Relay: thử lại sau %.1fs" % delay)
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
                if inner.get("type") == "hello":
                    self.conn.peer_v = int(inner.get("v") or 1)
                    self.conn.peer_caps = list(inner.get("caps") or [])
                    core.log(
                        "Relay viewer hello: v=%d caps=%s"
                        % (self.conn.peer_v, self.conn.peer_caps)
                    )
                else:
                    asyncio.create_task(core.handle_client_message(self.conn, inner))
        elif t == "error":
            msg_text = str(data.get("message", "?"))
            if msg_text != self._last_err:
                self._last_err = msg_text
                core.log("Relay: %s" % msg_text)
                core.broadcast_event("history", ("relay", "Lỗi: %s" % msg_text))
            self._set_status("error")
            if "đã đăng ký" in msg_text or "đã có máy khác" in msg_text:
                self._retry_delay = 60.0

    async def _handle_auth(self, cfg: dict, data: dict) -> None:
        """Xử lý yêu cầu auth từ relay: hỏi consent (nếu bật), xác minh mật khẩu."""
        password = str(data.get("password") or "")
        viewer_ip = str(data.get("viewer_ip") or "relay viewer")

        # Xác minh mật khẩu trước
        ok = core.secure.verify_password(password, cfg.get("password_enc") or "")
        if not ok:
            core.counters["auth_fails"] += 1
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
        except Exception as e:
            core.log("Consent lỗi (%s) → cho phép" % e)
            result = "allow"

        if result == "deny":
            await self.ws.send_json(
                {"type": "auth_result", "ok": False, "message": "Người dùng từ chối kết nối"}
            )
            return

        # Tạo kết nối viewer
        conn = core.ClientConn(
            name="Relay viewer (%s)" % viewer_ip,
            send_json=lambda d: self._to_viewer_json(d),
            send_bytes=lambda b: self._to_viewer_bytes(b),
            close=lambda: self._unbind(),
        )
        # view_only: tắt input handling
        if result == "view_only":
            conn.view_only = True

        self.conn = conn
        await self.ws.send_json(
            {"type": "auth_result", "ok": True, "data": core.auth_ok_payload()}
        )
        # Hello handshake v2
        await self._to_viewer_json(
            {"type": "hello", "v": PROTOCOL_VERSION, "caps": CAPS}
        )
        conn.peer_v = 1
        conn.peer_caps: list[str] = []
        await core.add_client(conn)

    # ------------------------------------------------------------------
    # Helpers gửi message về viewer qua relay
    # ------------------------------------------------------------------

    async def _to_viewer_json(self, d: dict) -> None:
        if self.ws and not self.ws.closed:
            await self.ws.send_json({"type": "agent_msg", "data": d})

    async def _to_viewer_bytes(self, b: bytes) -> None:
        if self.ws and not self.ws.closed:
            await self.ws.send_bytes(b)

    async def _unbind(self) -> None:
        if self.ws and not self.ws.closed:
            try:
                await self.ws.send_json({"type": "unbind"})
            except Exception:
                pass


relay_client = RelayClient()


async def start_if_enabled(cfg: dict) -> None:
    if cfg.get("relay_enabled") and cfg.get("relay_url"):
        await relay_client.start(cfg, core.events)
