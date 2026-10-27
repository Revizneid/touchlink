"""Kết nối ra relay server để nhận kết nối từ xa qua internet (outbound only)."""
import asyncio
import json

import aiohttp
from aiohttp import WSMsgType

import core


class RelayClient:
    def __init__(self):
        self.task = None
        self.running = False
        self.session = None
        self.ws = None
        self.conn = None
        self.status = "stopped"
        self._last_err = None
        self._retry_delay = None

    def _set_status(self, status, history_text=None):
        if self.status != status:
            self.status = status
            core.broadcast_event("relay", status)
            if history_text:
                core.broadcast_event("history", ("relay", history_text))

    async def start(self, cfg, events_q):
        if self.running:
            return
        self.running = True
        self._set_status("connecting")
        core.log("Relay: đang kết nối tới %s" % cfg.get("relay_url"))
        self.task = asyncio.create_task(self._run(cfg))

    async def stop(self):
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

    async def _cleanup(self):
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
        self._set_status("stopped")

    async def _run(self, cfg):
        backoff = 1
        while self.running:
            try:
                self.session = aiohttp.ClientSession()
                self.ws = await self.session.ws_connect(
                    cfg.get("relay_url"), heartbeat=20, timeout=aiohttp.ClientWSTimeout(ws_close=10))
                await self.ws.send_json({"type": "register", "device_id": str(cfg.get("device_id", ""))})
                self.status = "registered"
                backoff = 1
                self._last_err = None
                core.log("Relay: đã đăng ký mã máy %s" % cfg.get("device_id"))
                core.broadcast_event("relay", "registered")
                core.broadcast_event("history", ("relay",
                    "Đã đăng ký mã máy %s trên relay" % cfg.get("device_id")))
                async for msg in self.ws:
                    if msg.type == WSMsgType.TEXT:
                        await self._on_text(cfg, json.loads(msg.data))
                    elif msg.type == WSMsgType.BINARY:
                        # frame màn hình -> chuyển tiếp cho viewer (nếu có)
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
                core.log("Relay: mất kết nối (%s)" % e)
            finally:
                await self._cleanup()
            if not self.running:
                break
            self._set_status("retrying")
            await asyncio.sleep(self._retry_delay or backoff)
            self._retry_delay = None
            backoff = min(backoff * 2, 30)

    async def _on_text(self, cfg, data):
        t = data.get("type")
        if t == "auth":
            # relay chuyển yêu cầu đăng nhập của viewer về đây để máy tính tự xác minh
            password = str(data.get("password") or "")
            conn = core.ClientConn(
                name="Relay viewer",
                send_json=lambda d: self._to_viewer_json(d),
                send_bytes=lambda b: self._to_viewer_bytes(b),
                close=lambda: self._unbind(),
            )
            ok = core.secure.verify_password(password, cfg.get("password_enc") or "")
            if ok:
                self.conn = conn
                await self.ws.send_json({"type": "auth_result", "ok": True,
                                         "data": core.auth_ok_payload()})
                await core.add_client(conn)
            else:
                core.counters["auth_fails"] += 1
                await self.ws.send_json({"type": "auth_result", "ok": False,
                                         "message": "Sai mật khẩu"})
        elif t == "unbind":
            if self.conn:
                await core.remove_client(self.conn, "(relay unbind)")
                self.conn = None
        elif t == "viewer_msg":
            inner = data.get("data")
            if self.conn and isinstance(inner, dict):
                asyncio.create_task(core.handle_client_message(self.conn, inner))
        elif t == "error":
            msg = str(data.get("message", "?"))
            if msg != self._last_err:  # chỉ log 1 lần cho mỗi loại lỗi
                self._last_err = msg
                core.log("Relay: %s" % msg)
                core.broadcast_event("history", ("relay", "Lỗi: %s" % msg))
            self._set_status("error")
            if "đã đăng ký" in msg or "đã có máy khác" in msg:
                # bản TouchLink khác đang giữ ID này → thử lại chậm hơn
                self._retry_delay = 60

    async def _to_viewer_json(self, d):
        if self.ws and not self.ws.closed:
            await self.ws.send_json({"type": "agent_msg", "data": d})

    async def _to_viewer_bytes(self, b):
        if self.ws and not self.ws.closed:
            await self.ws.send_bytes(b)

    async def _unbind(self):
        if self.ws and not self.ws.closed:
            try:
                await self.ws.send_json({"type": "unbind"})
            except Exception:
                pass


relay_client = RelayClient()


async def start_if_enabled(cfg):
    if cfg.get("relay_enabled") and cfg.get("relay_url"):
        await relay_client.start(cfg, core.events)
