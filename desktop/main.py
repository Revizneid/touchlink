"""TouchLink — điều khiển máy tính từ điện thoại.

Chạy:  python -m desktop.main [--headless] [--safe-test] [--port N] [--password MK] ...
"""
import argparse
import asyncio
import ctypes
import json
import os
import queue
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as cfgmod
import core
import input_control as inp
import relay_client
import secure
import server as server_mod
import util
from aiohttp import web
from auth import RateLimiter


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
    p.add_argument("--doctor", action="store_true", help="In báo cáo khởi động và kiểm tra môi trường")
    p.add_argument("--json", action="store_true", help="Xuất JSON khi dùng --doctor")
    p.add_argument("--exit-after", type=float, default=None, metavar="SECONDS",
                   help="Thoát sau N giây kể từ khi server sẵn sàng")
    p.add_argument("--print-ready", action="store_true",
                   help="In ra dấu READY khi server đã sẵn sàng")
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
            print(f"Mật khẩu mới: {pw}")
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
    core.log(f"Server LAN chạy tại http://0.0.0.0:{port}")
    core.broadcast_event("server", True)
    core.broadcast_event("history", ("server", "Server LAN chạy ở cổng %d" % port))
    stream_task = asyncio.create_task(core.stream_loop())
    try:
        await relay_client.start_if_enabled(cfg)
    except Exception as e:
        core.log(f"Relay khởi động lỗi: {e}")
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
        core.log(f"Async thread dừng: {e!r}")
        started_evt.set()


def _doctor_report():
    report = {"summary": {"pass": 0, "warn": 0, "fail": 0}, "checks": []}

    def add_check(name, ok, details, level="pass"):
        record = {"name": name, "ok": bool(ok), "level": level, "details": details}
        report["checks"].append(record)
        if level == "pass":
            report["summary"]["pass"] += 1
        elif level == "warn":
            report["summary"]["warn"] += 1
        else:
            report["summary"]["fail"] += 1

    add_check("python", sys.version_info >= (3, 10), sys.version, "pass")
    try:
        import tkinter  # noqa: F401
        add_check("tkinter", True, "Tkinter import OK", "pass")
    except Exception as exc:
        add_check("tkinter", False, str(exc), "warn")
    try:
        import aiohttp  # noqa: F401
        add_check("aiohttp", True, "aiohttp import OK", "pass")
    except Exception as exc:
        add_check("aiohttp", False, str(exc), "fail")
    try:
        import capture  # noqa: F401
        add_check("capture", True, "capture package import OK", "pass")
    except Exception as exc:
        add_check("capture", False, str(exc), "fail")
    try:
        import server  # noqa: F401
        add_check("server", True, "server module import OK", "pass")
    except Exception as exc:
        add_check("server", False, str(exc), "fail")
    add_check("startup_flags", True, "supports --doctor, --json, --exit-after, --print-ready", "pass")
    return report


def run_headless(cfg, events_q, exit_after=None, print_ready=False):
    if print_ready:
        print("READY touchlink headless port={}".format(cfg.get("port", cfgmod.DEFAULT_PORT)), flush=True)
    print("=" * 56)
    print("TouchLink v{} (headless{})".format(cfgmod.VERSION, ", SAFE-TEST" if inp.SAFE_TEST else ""))
    print("Device code: {}".format(cfg["device_id"]))
    print(f"Password: {util.password_plain(cfg)}")
    for u in util.build_urls(cfg):
        print(f"Address: {u}")
    print("=" * 56)
    print("[Headless] Overlay is not visible when running --headless.")
    print("[Headless] Hotkey Ctrl+Alt+Shift+F12 remains active for emergency disconnect.", flush=True)
    deadline = None if exit_after is None else time.monotonic() + float(exit_after)
    try:
        while True:
            timeout = 1.0
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    print(f"[Headless] exit-after reached ({exit_after}s)", flush=True)
                    return 0
                timeout = min(1.0, max(0.1, remaining))
            try:
                kind, data = events_q.get(timeout=timeout)
            except queue.Empty:
                continue
            if kind == "log":
                print("  -", data, flush=True)
            elif kind == "clients":
                n = int(data)
                if n > 0:
                    print("  WARNING: %d viewer(s) are controlling this machine!" % n, flush=True)
                else:
                    print("  viewers: 0", flush=True)
            elif kind == "chat":
                print("  [chat] {}: {}".format(*data), flush=True)
    except KeyboardInterrupt:
        return 0


def run_gui(cfg, events_q):
    import gui
    gui.run_gui(cfg, events_q)


def main():
    args = parse_args()
    if args.version:
        print("TouchLink", cfgmod.VERSION)
        return 0
    if args.doctor:
        report = _doctor_report()
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print("TouchLink doctor")
            for check in report["checks"]:
                status = "PASS" if check["level"] == "pass" else "WARN" if check["level"] == "warn" else "FAIL"
                print(f"- {status}: {check['name']} :: {check['details']}")
            print(f"Summary: pass={report['summary']['pass']} warn={report['summary']['warn']} fail={report['summary']['fail']}")
        return 0
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

    if args.print_ready:
        print("READY touchlink port={} headless={}".format(cfg.get("port", cfgmod.DEFAULT_PORT), bool(args.headless)), flush=True)

    if args.headless:
        cfg["_headless"] = True
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
            print(f"[Headless] overlay hotkey lỗi: {e}", flush=True)
        return run_headless(cfg, events_q, exit_after=args.exit_after, print_ready=False)
    else:
        cfg["_headless"] = False
        try:
            run_gui(cfg, events_q)
        except Exception as e:
            print(f"GUI lỗi ({e!r}) — chuyển sang headless.")
            return run_headless(cfg, events_q, exit_after=args.exit_after, print_ready=args.print_ready)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
