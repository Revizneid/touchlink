"""TouchLink Relay — máy chủ trung gian chạy trên VPS (kết nối qua internet).

Máy tính kết nối ra relay (outbound), điện thoại kết nối tới relay và ghép cặp
theo mã máy (ID). Relay KHÔNG biết mật khẩu: nó chuyển mật khẩu về máy tính để
máy tính tự xác minh.

Chạy:  python relay_server.py --port 8430 [--web ../web]
Khuyến nghị đặt sau reverse proxy có TLS (wss://).
"""
import argparse
import asyncio
import json
import os

from aiohttp import WSMsgType, web

agents = {}  # device_id -> {"ws": ws, "viewer": ws|None, "bound": bool, "device": str}


def web_dir(args):
    d = os.path.abspath(args.web)
    return d if os.path.isdir(d) else None


async def inject_mode(html_path):
    """Nhúng cờ relay vào index.html để web UI tự bật chế độ 'qua trung gian'."""
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()
    if "__TOUCHLINK_MODE" not in html:
        html = html.replace("</head>",
                            "<script>window.__TOUCHLINK_MODE='relay'</script>\n</head>", 1)
    return html


async def ws_handler(request):
    ws = web.WebSocketResponse(heartbeat=25, max_msg_size=8 * 1024 * 1024)
    await ws.prepare(request)
    role = None
    device_id = None
    rec = None

    async def try_send(target, data):
        try:
            await target.send_json(data)
        except Exception:
            pass

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                except Exception:
                    continue
                t = data.get("type")

                if t == "register" and role is None:
                    device_id = str(data.get("device_id") or "").strip()
                    if not device_id:
                        await try_send(ws, {"type": "error", "message": "Thiếu mã máy"})
                        continue
                    old = agents.get(device_id)
                    if old and not old["ws"].closed and old["ws"] is not ws:
                        await try_send(ws, {"type": "error", "message": "Mã máy đã có máy khác đăng ký"})
                        continue
                    rec = {"ws": ws, "viewer": None, "bound": False, "device": device_id}
                    agents[device_id] = rec
                    role = "agent"
                    await try_send(ws, {"type": "registered"})

                elif t == "connect" and role is None:
                    device_id = str(data.get("device_id") or "").strip()
                    password = str(data.get("password") or "")
                    a = agents.get(device_id)
                    if not a or a["ws"].closed:
                        await try_send(ws, {"type": "auth_result", "ok": False,
                                            "message": "Máy tính không trực tuyến"})
                        continue
                    if a["viewer"] is not None:
                        await try_send(ws, {"type": "auth_result", "ok": False,
                                            "message": "Máy đang có người xem khác"})
                        continue
                    role = "viewer"
                    rec = a
                    a["viewer"] = ws
                    a["bound"] = False
                    await try_send(a["ws"], {"type": "auth", "password": password})
                    # hẹn giờ: máy tính không trả lời trong 12s -> hủy ghép cặp
                    async def _timeout(a=a, v=ws):
                        await asyncio.sleep(12)
                        if a.get("viewer") is v and not a.get("bound"):
                            a["viewer"] = None
                            await try_send(v, {"type": "auth_result", "ok": False,
                                               "message": "Máy tính không phản hồi"})
                    asyncio.create_task(_timeout())

                elif t == "auth_result" and role == "agent" and rec:
                    v = rec.get("viewer")
                    if v is None or v.closed:
                        continue
                    if data.get("ok"):
                        rec["bound"] = True
                        await try_send(v, {"type": "auth_result", "ok": True,
                                           "data": data.get("data") or {}})
                        await try_send(ws, {"type": "bound"})
                    else:
                        rec["viewer"] = None
                        await try_send(v, {"type": "auth_result", "ok": False,
                                           "message": data.get("message") or "Sai mật khẩu"})

                elif role == "viewer" and rec and t != "connect":
                    # mọi message khác của viewer (input/settings/clipboard/chat/ping)
                    # -> bọc lại và chuyển nguyên về máy tính
                    await try_send(rec["ws"], {"type": "viewer_msg", "data": data})

                elif t == "agent_msg" and role == "agent" and rec:
                    v = rec.get("viewer")
                    if v is not None and not v.closed:
                        await try_send(v, data.get("data") or {})

                elif t == "unbind" and role == "agent" and rec:
                    if rec.get("viewer") and not rec["viewer"].closed:
                        await try_send(rec["viewer"], {"type": "unbind"})
                    rec["viewer"] = None

                elif t == "ping":
                    await try_send(ws, {"type": "pong", "t": data.get("t")})

            elif msg.type == WSMsgType.BINARY and role == "agent" and rec:
                v = rec.get("viewer")
                if v is not None and not v.closed:
                    try:
                        await v.send_bytes(msg.data)
                    except Exception:
                        pass
            elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                break
    finally:
        if role == "agent" and device_id and agents.get(device_id) is rec:
            agents.pop(device_id, None)
            v = rec.get("viewer") if rec else None
            if v and not v.closed:
                await try_send(v, {"type": "auth_result", "ok": False,
                                   "message": "Máy tính đã ngắt kết nối"})
        elif role == "viewer" and rec:
            if rec.get("viewer") is ws:
                rec["viewer"] = None
                if not rec["ws"].closed:
                    await try_send(rec["ws"], {"type": "unbind"})
    return ws


def make_app(args):
    routes = web.RouteTableDef()

    @routes.get("/api/relayinfo")
    async def info(_request):
        return web.json_response({
            "app": "touchlink-relay",
            "agents": [{"device_id": d, "busy": bool(r.get("viewer"))} for d, r in agents.items()],
        })

    routes.get("/ws")(ws_handler)

    app = web.Application()
    app.add_routes(routes)
    wd = web_dir(args)
    if wd:
        async def index(_request):
            return web.Response(text=await inject_mode(os.path.join(wd, "index.html")),
                                content_type="text/html")
        app.router.add_get("/", index)
        app.router.add_static("/static/", wd)
    return app


def main():
    ap = argparse.ArgumentParser(description="TouchLink relay server")
    ap.add_argument("--port", type=int, default=8430)
    ap.add_argument("--web", default=os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "web"), help="Thư mục web UI để phục vụ kèm")
    args = ap.parse_args()
    port = int(os.environ.get("PORT", args.port))  #Render/Heroku-style hosting
    app = make_app(args)
    print("TouchLink relay chạy tại ws://0.0.0.0:%s/ws" % port)
    if web_dir(args):
        print("Web UI: http://0.0.0.0:%s/" % port)
    web.run_app(app, host="0.0.0.0", port=port, print=None)


if __name__ == "__main__":
    main()
