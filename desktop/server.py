"""HTTP + WebSocket server chạy trên PC (chế độ LAN)."""
import asyncio
import json
import os

from aiohttp import WSMsgType, web

import core
from auth import RateLimiter

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")


def _lan_ip():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def make_app(cfg):
    limiter = RateLimiter()
    core.limiter = limiter
    routes = web.RouteTableDef()

    async def index(_request):
        return web.FileResponse(os.path.join(WEB_DIR, "index.html"))

    @routes.get("/api/info")
    async def api_info(_request):
        return web.json_response({
            "app": "touchlink",
            "version": core.VERSION,
            "device_id": cfg.get("device_id", ""),
            "hostname": os.environ.get("COMPUTERNAME", ""),
            "monitors": __import__("capture").list_monitors(),
            "relay_enabled": bool(cfg.get("relay_enabled")),
            "safe_test": core.inp.SAFE_TEST,
        })

    @routes.get("/api/debug")
    async def api_debug(_request):
        return web.json_response({
            "clients": len(core.clients),
            "events": core.counters["events"],
            "frames": core.counters["frames"],
            "auth_fails": core.counters["auth_fails"],
            "input_stats": dict(core.inp.stats),
            "settings": dict(core.settings),
        })

    @routes.get("/ws")
    async def ws_handler(request):
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=2 * 1024 * 1024)
        await ws.prepare(request)
        peer = request.remote or "?"
        conn = core.ClientConn(
            name="LAN " + peer,
            send_json=ws.send_json,
            send_bytes=ws.send_bytes,
            close=ws.close,
        )
        # --- bắt tay xác thực ---
        try:
            first = await asyncio.wait_for(ws.receive(), timeout=15)
        except asyncio.TimeoutError:
            await ws.close()
            return ws
        if first.type != WSMsgType.TEXT:
            await ws.close()
            return ws
        try:
            auth_msg = json.loads(first.data)
        except Exception:
            await ws.close()
            return ws
        if auth_msg.get("type") != "auth":
            await ws.send_json({"type": "auth_fail", "message": "Thiếu xác thực"})
            await ws.close()
            return ws
        if limiter.is_banned(peer):
            await ws.send_json({"type": "auth_fail",
                                "message": "Đang bị khóa %ds do thử sai nhiều lần"
                                           % limiter.ban_remaining(peer)})
            await ws.close()
            return ws
        ok = await core.verify_and_accept(conn, auth_msg)
        if not ok:
            limiter.fail(peer)
            await ws.close()
            return ws
        limiter.reset(peer)
        await conn.send_json(core.auth_ok_payload())
        await core.add_client(conn)
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except Exception:
                        continue
                    await core.handle_client_message(conn, data)
                elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                    break
        finally:
            await core.remove_client(conn)
        return ws

    app = web.Application()
    app.add_routes(routes)
    if os.path.isdir(WEB_DIR):
        app.router.add_get("/", index)
        app.router.add_get("/sw.js", lambda r: web.FileResponse(os.path.join(WEB_DIR, "sw.js")))
        app.router.add_static("/static/", WEB_DIR)
    return app
