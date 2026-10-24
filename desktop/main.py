"""TouchLink — điều khiển máy tính từ điện thoại.

Chạy:  python main.py [--headless] [--safe-test] [--port N] [--password MK] ...
"""
import argparse
import asyncio
import ctypes
import os
import queue
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import aiohttp
from aiohttp import web

import config as cfgmod
import capture
import core
import secure
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


def lan_ips():
    ips = set()
    try:
        _host, _alias, addrs = socket.gethostbyname_ex(socket.gethostname())
        ips.update(a for a in addrs if not a.startswith("127."))
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    return sorted(ips)


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
    try:
        site = web.TCPSite(runner, "0.0.0.0", int(cfg.get("port", cfgmod.DEFAULT_PORT)))
        await site.start()
    except OSError as e:
        core.log("LỖI: không mở được cổng %s — %s" % (cfg.get("port"), e))
        started_evt.set()
        return
    core.log("Server LAN chạy tại http://0.0.0.0:%s" % cfg.get("port"))
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


def password_plain(cfg):
    return secure.unprotect(cfg.get("password_enc") or "") or "?"


def build_urls(cfg):
    urls = []
    for ip in lan_ips():
        urls.append("http://%s:%s" % (ip, cfg.get("port")))
    return urls or ["http://127.0.0.1:%s" % cfg.get("port")]


def run_headless(cfg, events_q):
    print("=" * 56)
    print("TouchLink v%s (headless%s)" % (cfgmod.VERSION, ", SAFE-TEST" if inp.SAFE_TEST else ""))
    print("Mã máy   : %s" % cfg["device_id"])
    print("Mật khẩu : %s" % password_plain(cfg))
    for u in build_urls(cfg):
        print("Địa chỉ  : %s" % u)
    print("=" * 56, flush=True)
    try:
        while True:
            kind, data = events_q.get()
            if kind == "log":
                print("  ·", data, flush=True)
            elif kind == "clients":
                print("  · viewers: %s" % data, flush=True)
            elif kind == "chat":
                print("  [chat] %s: %s" % data, flush=True)
    except KeyboardInterrupt:
        pass


def run_gui(cfg, events_q):
    import tkinter as tk
    from tkinter import messagebox, ttk

    import qrcode
    from PIL import ImageTk

    root = tk.Tk()
    root.title("TouchLink — Điều khiển PC từ điện thoại")
    root.geometry("580x700")
    root.minsize(520, 620)

    pad = {"padx": 10, "pady": 4}

    def log_insert(line):
        txt_log.configure(state="normal")
        txt_log.insert("end", "[%s] %s\n" % (time.strftime("%H:%M:%S"), line))
        if int(txt_log.index("end-1c").split(".")[0]) > 400:
            txt_log.delete("1.0", "50.0")
        txt_log.see("end")
        txt_log.configure(state="disabled")

    frm_top = ttk.Frame(root)
    frm_top.pack(fill="x", **pad)

    ttk.Label(frm_top, text="TouchLink v%s" % cfgmod.VERSION,
              font=("Segoe UI", 14, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")

    ttk.Label(frm_top, text="Mã máy (ID):", font=("Segoe UI", 10)).grid(row=1, column=0, sticky="w", pady=(10, 0))
    var_id = tk.StringVar(value=cfg["device_id"])
    ttk.Entry(frm_top, textvariable=var_id, font=("Consolas", 15, "bold"), width=14,
              state="readonly").grid(row=2, column=0, sticky="w")

    ttk.Label(frm_top, text="Mật khẩu:", font=("Segoe UI", 10)).grid(row=3, column=0, sticky="w", pady=(8, 0))
    var_pw = tk.StringVar(value=password_plain(cfg))
    ttk.Entry(frm_top, textvariable=var_pw, font=("Consolas", 15, "bold"), width=14,
              state="readonly").grid(row=4, column=0, sticky="w")

    frm_btn = ttk.Frame(frm_top)
    frm_btn.grid(row=5, column=0, sticky="w", pady=(8, 0))

    def regenerate():
        if messagebox.askyesno("TouchLink", "Sinh lại mật khẩu mới? Viewer đang kết nối vẫn giữ phiên."):
            cfg["password_enc"] = secure.protect(cfgmod.gen_password())
            cfgmod.save(cfg)
            var_pw.set(password_plain(cfg))
            log_insert("Đã sinh mật khẩu mới.")

    ttk.Button(frm_btn, text="Tạo mật khẩu mới", command=regenerate).pack(side="left", padx=(0, 6))

    def copy_info():
        urls = build_urls(cfg)
        txt = "TouchLink\nID: %s\nMật khẩu: %s\nĐịa chỉ: %s\n?id=%s" % (
            var_id.get(), var_pw.get(), urls[0], var_id.get())
        root.clipboard_clear()
        root.clipboard_append(txt)
        log_insert("Đã sao chép thông tin kết nối.")

    ttk.Button(frm_btn, text="Sao chép thông tin", command=copy_info).pack(side="left")

    frm_qr = ttk.LabelFrame(frm_top, text="Quét bằng điện thoại")
    frm_qr.grid(row=1, column=1, rowspan=5, padx=(16, 0), pady=(10, 0), sticky="n")
    url = build_urls(cfg)[0] + "/?id=" + str(cfg["device_id"])
    try:
        img = qrcode.make(url).resize((170, 170))
        qr_img = ImageTk.PhotoImage(img)
        ttk.Label(frm_qr, image=qr_img).pack(padx=6, pady=6)
    except Exception as e:
        ttk.Label(frm_qr, text="QR lỗi: %s" % e).pack()

    ttk.Label(root, text="Địa chỉ mở trên điện thoại (cùng Wi-Fi):").pack(anchor="w", **pad)
    ttk.Label(root, text="   ".join(build_urls(cfg)), font=("Consolas", 10),
              foreground="#1d4ed8").pack(anchor="w", padx=12)

    frm_status = ttk.LabelFrame(root, text="Trạng thái")
    frm_status.pack(fill="x", **pad)
    var_viewers = tk.StringVar(value="Viewers: 0")
    var_relay_status = tk.StringVar(value="Relay: %s" % ("bật" if cfg.get("relay_enabled") else "tắt"))
    ttk.Label(frm_status, textvariable=var_viewers).pack(anchor="w", padx=8, pady=2)
    ttk.Label(frm_status, textvariable=var_relay_status).pack(anchor="w", padx=8, pady=2)

    frm_set = ttk.LabelFrame(root, text="Cài đặt")
    frm_set.pack(fill="x", **pad)
    grid = frm_set
    ttk.Label(grid, text="FPS:").grid(row=0, column=0, sticky="w", padx=6, pady=3)
    sp_fps = ttk.Spinbox(grid, from_=2, to=30, width=6)
    sp_fps.set(core.settings["fps"])
    ttk.Label(grid, text="Chất lượng JPEG:").grid(row=0, column=2, sticky="e", padx=6)
    sp_q = ttk.Spinbox(grid, from_=20, to=95, width=6)
    sp_q.set(core.settings["quality"])
    ttk.Label(grid, text="Thu nhỏ %:").grid(row=1, column=0, sticky="w", padx=6, pady=3)
    sp_s = ttk.Spinbox(grid, from_=30, to=100, width=6, increment=5)
    sp_s.set(core.settings["scale"])
    ttk.Label(grid, text="Màn hình:").grid(row=1, column=2, sticky="e", padx=6)
    mons = capture.list_monitors()
    cb_mon = ttk.Combobox(grid, values=[("%d — %s" % (m["index"], m["label"])) for m in mons],
                          width=26, state="readonly")
    cur = next((i for i, m in enumerate(mons) if m["index"] == core.settings["monitor"]), 0)
    cb_mon.current(cur)
    var_cbsync = tk.BooleanVar(value=core.settings["clipboard_sync"])
    cb_sync = ttk.Checkbutton(grid, text="Đồng bộ clipboard", variable=var_cbsync)

    def apply_settings():
        try:
            core.settings["fps"] = int(sp_fps.get())
            core.settings["quality"] = int(sp_q.get())
            core.settings["scale"] = int(sp_s.get())
            if cb_mon.current() >= 0:
                core.settings["monitor"] = mons[cb_mon.current()]["index"]
            core.settings["clipboard_sync"] = bool(var_cbsync.get())
            cfg.update(core.settings)
            cfgmod.save(cfg)
            log_insert("Đã áp dụng cài đặt: fps=%s quality=%s scale=%s monitor=%s" % (
                core.settings["fps"], core.settings["quality"], core.settings["scale"],
                core.settings["monitor"]))
        except Exception as e:
            messagebox.showerror("TouchLink", "Cài đặt lỗi: %s" % e)

    sp_fps.grid(row=0, column=1, padx=4)
    sp_q.grid(row=0, column=3, padx=4)
    sp_s.grid(row=1, column=1, padx=4)
    cb_mon.grid(row=1, column=3, padx=4)
    cb_sync.grid(row=2, column=0, columnspan=2, sticky="w", padx=6)
    ttk.Button(grid, text="Áp dụng", command=apply_settings).grid(row=2, column=3, padx=4, pady=3)

    frm_relay = ttk.LabelFrame(root, text="Relay (kết nối qua internet)")
    frm_relay.pack(fill="x", **pad)
    var_relay_url = tk.StringVar(value=cfg.get("relay_url", ""))
    ttk.Entry(frm_relay, textvariable=var_relay_url, width=44).pack(side="left", padx=6, pady=6)

    def apply_relay():
        cfg["relay_url"] = var_relay_url.get().strip()
        cfg["relay_enabled"] = bool(var_relay_on.get())
        cfgmod.save(cfg)
        loop = core.get_loop()
        if loop and loop.is_running():
            try:
                if var_relay_on.get():
                    asyncio.run_coroutine_threadsafe(
                        relay_client.relay_client.start(cfg, events_q), loop)
                else:
                    asyncio.run_coroutine_threadsafe(
                        relay_client.relay_client.stop(), loop)
            except Exception as e:
                log_insert("Relay lỗi: %s" % e)

    var_relay_on = tk.BooleanVar(value=bool(cfg.get("relay_enabled")))
    ttk.Checkbutton(frm_relay, text="Bật", variable=var_relay_on, command=apply_relay).pack(side="left", padx=4)
    ttk.Button(frm_relay, text="Áp dụng relay", command=apply_relay).pack(side="left", padx=4)

    frm_log = ttk.LabelFrame(root, text="Nhật ký")
    frm_log.pack(fill="both", expand=True, **pad)
    txt_log = tk.Text(frm_log, height=8, state="disabled", font=("Consolas", 9))
    txt_log.pack(fill="both", expand=True, padx=4, pady=4)

    def poll_events():
        try:
            for _ in range(200):
                kind, data = events_q.get_nowait()
                if kind == "log":
                    log_insert(str(data))
                elif kind == "clients":
                    var_viewers.set("Viewers: %s" % data)
                    var_relay_status.set("Relay: %s" % relay_client.relay_client.status)
                elif kind == "chat":
                    log_insert("[chat] %s: %s" % data)
        except queue.Empty:
            pass
        root.after(250, poll_events)

    log_insert("TouchLink sẵn sàng. Mở trên điện thoại: %s" % build_urls(cfg)[0])
    poll_events()
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()
    os._exit(0)


def main():
    args = parse_args()
    if args.version:
        print("TouchLink", cfgmod.VERSION)
        return
    set_dpi_aware()
    if args.safe_test:
        inp.SAFE_TEST = True
    events_q = queue.Queue()
    cfg = prepare_config(args)
    core.settings.update({k: cfg[k] for k in ("fps", "quality", "scale", "monitor", "clipboard_sync")
                          if k in cfg})

    started_evt = threading.Event()
    t = threading.Thread(target=run_async_thread, args=(cfg, events_q, started_evt), daemon=True)
    t.start()
    started_evt.wait(timeout=10)

    if args.headless:
        run_headless(cfg, events_q)
    else:
        try:
            run_gui(cfg, events_q)
        except Exception as e:
            print("GUI lỗi (%r) — chuyển sang headless." % e)
            run_headless(cfg, events_q)


if __name__ == "__main__":
    main()
