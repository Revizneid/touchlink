"""TouchLink — điều khiển máy tính từ điện thoại.

Chạy:  python main.py [--headless] [--safe-test] [--port N] [--password MK] ...
"""
import argparse
import asyncio
import ctypes
import os
import queue
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import aiohttp
from aiohttp import web

import config as cfgmod
import capture
import core
import overlay as overlay_mod
import secure
import util
from auth import RateLimiter
import input_control as inp
import relay_client
import server as server_mod


def set_dpi_aware():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def parse_args():
    p = argparse.ArgumentParser(description="TouchLink desktop")
    p.add_argument("--headless", action="store_true", help="Chạy không GUI (console log)")
    p.add_argument("--safe-test", action="store_true",
                   help="KHÔNG điều khiển chuột/phím thật (chỉ ghi nhận) — dùng khi kiểm thử")
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--password", default=None, help="Đặt lại mật khẩu")
    p.add_argument("--fps", type=int, default=None)
    p.add_argument("--quality", type=int, default=None)
    p.add_argument("--scale", type=int, default=None)
    p.add_argument("--monitor", type=int, default=None)
    p.add_argument("--relay-url", default=None)
    p.add_argument("--relay", action="store_true", help="Bật kết nối relay")
    p.add_argument("--no-relay", action="store_true", help="Tắt kết nối relay")
    p.add_argument("--reset", action="store_true", help="Sinh lại mã máy + mật khẩu")
    p.add_argument("--version", action="store_true")
    return p.parse_args()


def prepare_config(args):
    cfg = cfgmod.load()
    changed = False
    if args.reset or not cfg.get("device_id"):
        cfg["device_id"] = cfgmod.gen_device_id()
        changed = True
    if args.password:
        cfg["password_enc"] = secure.protect(args.password)
        changed = True
    if not cfg.get("password_enc"):
        pw = cfgmod.gen_password()
        cfg["password_enc"] = secure.protect(pw)
        changed = True
        if args.headless:
            print("Mật khẩu mới: %s" % pw)
    for key, val in (("port", args.port), ("relay_url", args.relay_url)):
        if val is not None:
            cfg[key] = val
            changed = True
    if args.fps is not None:
        cfg["fps"] = args.fps; changed = True
    if args.quality is not None:
        cfg["quality"] = args.quality; changed = True
    if args.scale is not None:
        cfg["scale"] = args.scale; changed = True
    if args.monitor is not None:
        cfg["monitor"] = args.monitor; changed = True
    if args.relay:
        cfg["relay_enabled"] = True; changed = True
    if args.no_relay:
        cfg["relay_enabled"] = False; changed = True
    if changed:
        cfgmod.save(cfg)
    return cfg


async def async_main(cfg, events_q, started_evt):
    core.init(cfg, events_q, RateLimiter())
    core.set_loop(asyncio.get_running_loop())
    app = server_mod.make_app(cfg)
    runner = web.AppRunner(app)
    await runner.setup()
    # Cổng ưu tiên = cfg['port']; nếu bận (app đang chạy lần 2, TIME_WAIT...) tự chuyển +1
    base_port = int(cfg.get("port", cfgmod.DEFAULT_PORT))
    port = None
    for p in range(base_port, base_port + 20):
        try:
            site = web.TCPSite(runner, "0.0.0.0", p)
            await site.start()
            port = p
            break
        except OSError:
            continue
    if port is None:
        core.log("LỖI: không mở được cổng nào từ %d tới %d (đều đang bận)"
                 % (base_port, base_port + 19))
        core.broadcast_event("server", False)
        core.broadcast_event("history", ("server", "Không mở được cổng (bận)"))
        started_evt.set()
        return
    if port != base_port:
        core.log("Cổng %d đang bận (có thể TouchLink đang chạy) → tự dùng cổng %d"
                 % (base_port, port))
    cfg["port"] = port  # chỉ trong bộ nhớ — GUI/QR hiện đúng cổng thật
    core.log("Server LAN chạy tại http://0.0.0.0:%s" % port)
    core.broadcast_event("server", True)
    core.broadcast_event("history", ("server", "Server LAN chạy ở cổng %d" % port))
    stream_task = asyncio.create_task(core.stream_loop())
    try:
        await relay_client.start_if_enabled(cfg)
    except Exception as e:
        core.log("Relay khởi động lỗi: %s" % e)
    started_evt.set()
    try:
        await asyncio.Event().wait()  # chạy mãi
    except asyncio.CancelledError:
        pass
    finally:
        stream_task.cancel()


def run_async_thread(cfg, events_q, started_evt):
    try:
        asyncio.run(async_main(cfg, events_q, started_evt))
    except Exception as e:
        core.log("Async thread dừng: %r" % e)
        started_evt.set()


def run_headless(cfg, events_q):
    print("=" * 56)
    print("TouchLink v%s (headless%s)" % (cfgmod.VERSION, ", SAFE-TEST" if inp.SAFE_TEST else ""))
    print("Mã máy   : %s" % cfg["device_id"])
    print("Mật khẩu : %s" % util.password_plain(cfg))
    for u in util.build_urls(cfg):
        print("Địa chỉ  : %s" % u)
    print("=" * 56)
    print("[Headless] ⚠ Overlay không hiện khi chạy --headless.")
    print("[Headless] Hotkey Ctrl+Alt+Shift+F12 vẫn hoạt động (ngắt viewer khẩn cấp).", flush=True)
    try:
        while True:
            kind, data = events_q.get()
            if kind == "log":
                print("  ·", data, flush=True)
            elif kind == "clients":
                n = int(data)
                if n > 0:
                    print("  ⚠ CảNH BÁO: đang có %d viewer điều khiển máy tính này!" % n, flush=True)
                else:
                    print("  · viewers: 0", flush=True)
            elif kind == "chat":
                print("  [chat] %s: %s" % data, flush=True)
    except KeyboardInterrupt:
        pass


def run_gui(cfg, events_q):
    import gui
    gui.run_gui(cfg, events_q)


def main():
    args = parse_args()
    if args.version:
        print("TouchLink", cfgmod.VERSION)
        return
    try:  # exe windowed: stdout có thể None/cp1252 — ép UTF-8 để in tiếng Việt
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if args.headless and getattr(sys, "frozen", False):
        # exe --windowed không có console: cấp một console thật cho chế độ headless
        try:
            import ctypes
            ctypes.windll.kernel32.AllocConsole()
            sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace")
            sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace")
            sys.stdin = open("CONIN$", "r", encoding="utf-8", errors="replace")
        except Exception:
            pass
    set_dpi_aware()
    if args.safe_test:
        inp.SAFE_TEST = True
    events_q = queue.Queue()
    cfg = prepare_config(args)
    core.settings.update({k: cfg[k] for k in ("fps", "quality", "scale", "monitor",
                                              "clipboard_sync") if k in cfg})
    if inp.SAFE_TEST:
        core.settings["_safe_test"] = True

    started_evt = threading.Event()
    t = threading.Thread(target=run_async_thread, args=(cfg, events_q, started_evt),
                         daemon=True)
    t.start()
    started_evt.wait(timeout=10)

    if args.headless:
        cfg["_headless"] = True
        # Hotkey khẩn cấp ngay cả trong headless (overlay_mod không cần Tk root)
        try:
            import overlay as overlay_mod

            def _headless_disconnect():
                loop = core.get_loop()
                if loop and loop.is_running():
                    import asyncio
                    asyncio.run_coroutine_threadsafe(
                        _disconnect_all(loop), loop)

            async def _disconnect_all(loop):
                for c in list(core.clients):
                    try:
                        await core.remove_client(c, "(ngắt khẩn headless)")
                    except Exception:
                        pass

            overlay_mod._register_hotkey(_headless_disconnect)
        except Exception as e:
            print("[Headless] overlay hotkey lỗi: %s" % e, flush=True)
        run_headless(cfg, events_q)
    else:
        cfg["_headless"] = False
        try:
            run_gui(cfg, events_q)
        except Exception as e:
            print("GUI lỗi (%r) — chuyển sang headless." % e)
            run_headless(cfg, events_q)


if __name__ == "__main__":
    main()
