"""TouchLink v2.0 — giao diện desktop (tkinter, dark navy/blue control center)."""
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import qrcode
from PIL import ImageTk

import config as cfgmod
import capture
import core
import relay_client
import secure
from util import build_urls, lan_ips, password_plain

C = {
    "bg":    "#071426",
    "side":  "#0B1930",
    "card":  "#102442",
    "elev":  "#142B4C",
    "prim":  "#2675F5",
    "acc":   "#4EA1FF",
    "text":  "#F3F7FF",
    "dim":   "#A9BCD7",
    "line":  "#244269",
    "ok":    "#32D583",
    "warn":  "#F5B942",
    "err":   "#F97066",
    "hov":   "#1A3358",
    "primh": "#3B87FF",
}
F = "Segoe UI"
MONO = "Consolas"

NAV = [
    ("dash",   "🖥", "Điều khiển từ xa"),
    ("screen", "📺", "Màn hình chờ"),
    ("hist",   "🕘", "Lịch sử kết nối"),
    ("dev",    "📱", "Danh sách thiết bị"),
    ("set",    "⚙", "Cài đặt"),
]


class TouchLinkGUI(tk.Tk):
    def __init__(self, cfg, events_q):
        super().__init__()
        self.cfg = cfg
        self.events_q = events_q
        self.title("TouchLink v%s — Điều khiển máy tính từ điện thoại" % cfgmod.VERSION)
        self.geometry("1120x730")
        self.minsize(960, 660)
        self.configure(bg=C["bg"])

        self.server_running = False
        self.relay_status = "stopped"
        self.viewer_count = 0
        self.auto_scroll = tk.BooleanVar(value=True)
        self.show_pw = tk.BooleanVar(value=False)
        self._qr_img = None
        self._prev_img = None
        self._prev_running = False
        self._page_key = None

        self._style()
        self._build_header()
        self._build_body()
        self._toast_after = None
        self.after(250, self._poll)
        self.show_page("dash")
        core.log("TouchLink v%s sẵn sàng." % cfgmod.VERSION)

    # ---------- styling ----------
    def _style(self):
        s = ttk.Style(self)
        try:
            s.theme_use("clam")
        except Exception:
            pass
        s.configure("TCombobox", fieldbackground=C["elev"], background=C["card"],
                    foreground=C["text"], arrowcolor=C["text"], bordercolor=C["line"],
                    lightcolor=C["card"], darkcolor=C["card"], borderwidth=1)
        s.map("TCombobox", fieldbackground=[("readonly", C["elev"])],
              foreground=[("readonly", C["text"])])
        s.configure("TEntry", fieldbackground=C["elev"], foreground=C["text"],
                    insertcolor=C["text"], bordercolor=C["line"], lightcolor=C["card"],
                    darkcolor=C["card"])
        s.map("TEntry", fieldbackground=[("readonly", C["elev"])],
              foreground=[("readonly", C["text"])])
        s.configure("TSpinbox", fieldbackground=C["elev"], background=C["card"],
                    foreground=C["text"], arrowcolor=C["text"], bordercolor=C["line"],
                    lightcolor=C["card"], darkcolor=C["card"])
        s.configure("TCheckbutton", background=C["card"], foreground=C["text"],
                    focuscolor=C["card"])
        s.map("TCheckbutton", background=[("active", C["card"])])
        s.configure("Treeview", background=C["elev"], fieldbackground=C["elev"],
                    foreground=C["text"], bordercolor=C["line"], rowheight=26)
        s.configure("Treeview.Heading", background=C["card"], foreground=C["dim"],
                    bordercolor=C["line"], relief="flat")
        s.map("Treeview", background=[("selected", C["prim"])])
        s.configure("Vertical.TScrollbar", background=C["elev"], troughcolor=C["card"],
                    bordercolor=C["card"], arrowcolor=C["dim"])
        self.option_add("*TCombobox*Listbox.background", C["elev"])
        self.option_add("*TCombobox*Listbox.foreground", C["text"])
        self.option_add("*TCombobox*Listbox.selectBackground", C["prim"])
        self.option_add("*TCombobox*Listbox.selectForeground", C["text"])

    # ---------- widgets helpers ----------
    def card(self, parent):
        return tk.Frame(parent, bg=C["card"], highlightbackground=C["line"],
                        highlightthickness=1, padx=16, pady=14)

    def btn(self, parent, text, cmd, primary=False, width=None):
        b = tk.Button(parent, text=text, command=cmd, font=(F, 9),
                      bg=C["prim"] if primary else C["elev"],
                      fg="#FFFFFF" if primary else C["text"],
                      activebackground=C["primh"] if primary else C["hov"],
                      activeforeground="#FFFFFF", relief="flat", bd=0,
                      cursor="hand2", padx=12, pady=6, width=width)
        hov = C["primh"] if primary else C["hov"]
        b.bind("<Enter>", lambda e: b.configure(bg=hov))
        b.bind("<Leave>", lambda e: b.configure(bg=C["prim"] if primary else C["elev"]))
        return b

    def field_label(self, parent, text):
        return tk.Label(parent, text=text, font=(F, 9), fg=C["dim"], bg=C["card"],
                        anchor="w")

    def dot(self, parent, color):
        cv = tk.Canvas(parent, width=10, height=10, bg=parent["bg"],
                       highlightthickness=0)
        cv.create_oval(1, 1, 9, 9, fill=color, outline="")
        return cv

    def toast(self, msg, kind="info"):
        color = {"ok": C["ok"], "err": C["err"], "warn": C["warn"]}.get(kind, C["acc"])
        frame = tk.Frame(self, bg=C["elev"], highlightbackground=color,
                         highlightthickness=1)
        tk.Label(frame, text=" " + msg + " ", font=(F, 9), fg=C["text"],
                 bg=C["elev"], padx=12, pady=8).pack()
        frame.place(relx=1.0, x=-18, y=18, anchor="ne")
        if getattr(self, "_toast_frame", None):
            try:
                self._toast_frame.destroy()
            except Exception:
                pass
        self._toast_frame = frame
        if self._toast_after:
            self.after_cancel(self._toast_after)
        self._toast_after = self.after(2800, frame.destroy)

    # ---------- header ----------
    def _build_header(self):
        bar = tk.Frame(self, bg=C["side"], height=56)
        bar.pack(fill="x", side="top")
        bar.pack_propagate(False)
        badge = tk.Label(bar, text="TL", font=(F, 13, "bold"), fg="#FFFFFF",
                         bg=C["prim"], width=3, pady=6)
        badge.pack(side="left", padx=(14, 10), pady=10)
        tk.Label(bar, text="TouchLink", font=(F, 13, "bold"), fg=C["text"],
                 bg=C["side"]).pack(side="left")
        tk.Label(bar, text="v%s" % cfgmod.VERSION, font=(F, 9), fg=C["dim"],
                 bg=C["side"]).pack(side="left", padx=(8, 0))
        self.hdr_dot = self.dot(bar, C["warn"])
        self.hdr_dot.pack(side="left", padx=(16, 5))
        self.hdr_status = tk.Label(bar, text="Đang khởi động…", font=(F, 9),
                                   fg=C["dim"], bg=C["side"])
        self.hdr_status.pack(side="left")
        self.btn(bar, "Trợ giúp", self._help).pack(side="right", padx=(8, 14), pady=12)
        self.btn(bar, "Cài đặt", lambda: self.show_page("set")).pack(
            side="right", padx=4, pady=12)

    def _help(self):
        messagebox.showinfo(
            "TouchLink — Trợ giúp",
            "1. Điện thoại cùng Wi-Fi: quét mã QR hoặc mở địa chỉ LAN, nhập ID + mật khẩu.\n"
            "2. Qua internet: mở https://touchlink.vercel.app, chọn 'Qua relay', "
            "nhập ID + mật khẩu (app mặc định đã bật relay công cộng).\n"
            "3. Cài đặt stream (FPS/chất lượng/màn hình) áp dụng ngay cho người xem.\n\n"
            "Lưu ý: Ctrl+Alt+Del / màn hình khóa / UAC không điều khiển được từ xa.")

    # ---------- sidebar + pages ----------
    def _build_body(self):
        body = tk.Frame(self, bg=C["bg"])
        body.pack(fill="both", expand=True)
        side = tk.Frame(body, bg=C["side"], width=214)
        side.pack(fill="y", side="left")
        side.pack_propagate(False)
        self._nav_btns = {}
        for key, icon, label in NAV:
            b = tk.Label(side, text="  %s   %s" % (icon, label), font=(F, 10),
                         fg=C["dim"], bg=C["side"], anchor="w", pady=11, cursor="hand2")
            b.pack(fill="x", padx=10, pady=3)
            b.bind("<Button-1>", lambda e, k=key: self.show_page(k))
            b.bind("<Enter>", lambda e, w=b: w.configure(bg=C["hov"]) if self._page_key != getattr(w, "page_key", None) else None)
            b.bind("<Leave>", lambda e, w=b: w.configure(bg=C["side"]) if self._page_key != getattr(w, "page_key", None) else None)
            b.page_key = key
            self._nav_btns[key] = b
        tk.Frame(side, bg=C["line"], height=1).pack(fill="x", padx=10, pady=8)
        tk.Label(side, text="%s (máy này)" % os.environ.get("COMPUTERNAME", "PC"),
                 font=(F, 9), fg=C["dim"], bg=C["side"], anchor="w").pack(
            fill="x", padx=14, pady=4)
        tk.Label(side, text="ID: %s" % self.cfg.get("device_id", "—"), font=(MONO, 9),
                 fg=C["acc"], bg=C["side"], anchor="w").pack(fill="x", padx=14, pady=(0, 10))

        self.container = tk.Frame(body, bg=C["bg"])
        self.container.pack(fill="both", expand=True)
        self._page_key = None
        self.pages = {}
        self._build_page_dash()
        self._build_page_screen()
        self._build_page_hist()
        self._build_page_dev()
        self._build_page_set()

    def show_page(self, key):
        if self._page_key == key:
            return
        self._stop_preview()
        for k, p in self.pages.items():
            p.pack_forget()
        self._page_key = key
        for k, b in self._nav_btns.items():
            active = (k == key)
            b.configure(bg=C["elev"] if active else C["side"],
                        fg=C["text"] if active else C["dim"],
                        font=(F, 10, "bold") if active else (F, 10))
        self.pages[key].pack(fill="both", expand=True)
        if key == "screen":
            self._start_preview()
        if key == "dev":
            self._refresh_devices()

    def _page(self, key):
        f = tk.Frame(self.container, bg=C["bg"], padx=18, pady=16)
        self.pages[key] = f
        return f

    # ---------- page: dashboard ----------
    def _build_page_dash(self):
        page = self._page("dash")
        page.columnconfigure(0, weight=5, uniform="cards")
        page.columnconfigure(1, weight=4, uniform="cards")
        page.rowconfigure(0, weight=1)
        page.rowconfigure(1, weight=0)

        # === CARD A: điều khiển từ xa ===
        a = self.card(page)
        a.grid(row=0, column=0, sticky="nsew", padx=(0, 9))
        a.columnconfigure(0, weight=1)
        head = tk.Frame(a, bg=C["card"])
        head.grid(row=0, column=0, sticky="ew")
        tk.Label(head, text="🖥  Điều khiển từ xa", font=(F, 12, "bold"), fg=C["text"],
                 bg=C["card"]).pack(side="left")
        tk.Label(head, text="ID và mật khẩu để kết nối với máy này", font=(F, 9),
                 fg=C["dim"], bg=C["card"]).pack(side="left", padx=(10, 0))

        self.field_label(a, "ID máy tính").grid(row=1, column=0, sticky="w", pady=(12, 3))
        row = tk.Frame(a, bg=C["card"])
        row.grid(row=2, column=0, sticky="ew")
        row.columnconfigure(0, weight=1)
        self.var_id = tk.StringVar(value=str(self.cfg.get("device_id", "")))
        ent = ttk.Entry(row, textvariable=self.var_id, font=(MONO, 13, "bold"),
                        state="readonly", width=14)
        ent.grid(row=0, column=0, sticky="ew", ipady=5)
        self.btn(row, "📋 Copy", lambda: self._copy(self.var_id.get(), "Đã copy ID"),
                 width=9).grid(row=0, column=1, padx=(8, 0))

        self.field_label(a, "Mật khẩu").grid(row=3, column=0, sticky="w", pady=(12, 3))
        row = tk.Frame(a, bg=C["card"])
        row.grid(row=4, column=0, sticky="ew")
        row.columnconfigure(0, weight=1)
        self.var_pw = tk.StringVar(value=password_plain(self.cfg))
        self.ent_pw = ttk.Entry(row, textvariable=self.var_pw, font=(MONO, 13, "bold"),
                                width=14)
        self.ent_pw.configure(show="•")
        self.ent_pw.grid(row=0, column=0, sticky="ew", ipady=5)
        self.btn(row, "👁", self._toggle_pw, width=4).grid(row=0, column=1, padx=(8, 0))
        self.btn(row, "📋", lambda: self._copy(self.var_pw.get(), "Đã copy mật khẩu"),
                 width=4).grid(row=0, column=2, padx=(6, 0))

        row = tk.Frame(a, bg=C["card"])
        row.grid(row=5, column=0, sticky="w", pady=(12, 0))
        self.btn(row, "🔄 Tạo mật khẩu mới", self._regen_pw, primary=True).pack(side="left")
        self.btn(row, "Sao chép thông tin", self._copy_info).pack(side="left", padx=8)

        self.field_label(a, "Địa chỉ mở trên điện thoại (cùng Wi-Fi)").grid(
            row=6, column=0, sticky="w", pady=(14, 3))
        row = tk.Frame(a, bg=C["card"])
        row.grid(row=7, column=0, sticky="ew")
        row.columnconfigure(0, weight=1)
        self.var_url = tk.StringVar(value=" ".join(build_urls(self.cfg)))
        lbl = tk.Label(row, textvariable=self.var_url, font=(MONO, 10), fg=C["acc"],
                       bg=C["elev"], padx=10, pady=8, anchor="w")
        lbl.grid(row=0, column=0, sticky="ew")
        self.btn(row, "📋", lambda: self._copy(self.var_url.get().split()[0],
                 "Đã copy địa chỉ"), width=4).grid(row=0, column=1, padx=(8, 0))

        self.field_label(a, "Trạng thái kết nối").grid(row=8, column=0, sticky="w",
                                                      pady=(14, 5))
        srow = tk.Frame(a, bg=C["card"])
        srow.grid(row=9, column=0, sticky="ew")
        self.dots = {}
        self.slbls = {}
        for i, (key, label) in enumerate([
                ("server", "Server LAN"), ("relay", "Relay internet"),
                ("viewers", "Người xem"), ("reg", "Đăng ký relay")]):
            cell = tk.Frame(srow, bg=C["elev"], padx=10, pady=6,
                            highlightbackground=C["line"], highlightthickness=1)
            cell.grid(row=0, column=i, padx=(0, 8), sticky="w")
            self.dots[key] = self.dot(cell, C["dim"])
            self.dots[key].pack(side="left")
            self.slbls[key] = tk.Label(cell, text=label, font=(F, 8), fg=C["dim"],
                                       bg=C["elev"], anchor="w")
            self.slbls[key].pack(side="left", padx=6)
        self._update_status_badges()

        # === CARD B: QR + cài đặt + relay ===
        b = self.card(page)
        b.grid(row=0, column=1, sticky="nsew", padx=(9, 0))
        b.columnconfigure(0, weight=1)
        head = tk.Frame(b, bg=C["card"])
        head.grid(row=0, column=0, sticky="ew")
        tk.Label(head, text="🔳  Quét mã QR", font=(F, 12, "bold"), fg=C["text"],
                 bg=C["card"]).pack(side="left")
        tk.Label(head, text="Mở nhanh từ điện thoại", font=(F, 9), fg=C["dim"],
                 bg=C["card"]).pack(side="left", padx=(10, 0))

        qwrap = tk.Frame(b, bg="#FFFFFF", padx=8, pady=8)
        qwrap.grid(row=1, column=0, pady=(12, 4))
        self.qr_lbl = tk.Label(qwrap, bg="#FFFFFF")
        self.qr_lbl.pack()
        tk.Label(b, text="Quét bằng camera điện thoại (cùng Wi-Fi)", font=(F, 8),
                 fg=C["dim"], bg=C["card"]).grid(row=2, column=0)
        self.btn(b, "🔄 Làm mới QR", self._make_qr).grid(row=3, column=0, pady=(6, 4))

        tk.Frame(b, bg=C["line"], height=1).grid(row=4, column=0, sticky="ew", pady=12)
        self.field_label(b, "Cài đặt stream").grid(row=5, column=0, sticky="w")
        grid = tk.Frame(b, bg=C["card"])
        grid.grid(row=6, column=0, sticky="ew")
        grid.columnconfigure(1, weight=1)
        grid.columnconfigure(3, weight=1)
        tk.Label(grid, text="FPS", font=(F, 9), fg=C["dim"], bg=C["card"]).grid(
            row=0, column=0, sticky="w", pady=3)
        self.cb_fps = ttk.Combobox(grid, values=[str(x) for x in range(3, 31)],
                                   width=6, state="readonly")
        self.cb_fps.set(str(core.settings["fps"]))
        self.cb_fps.grid(row=0, column=1, sticky="w", padx=6)
        tk.Label(grid, text="Chất lượng JPEG", font=(F, 9), fg=C["dim"],
                 bg=C["card"]).grid(row=0, column=2, sticky="w", padx=(12, 0))
        self.cb_q = ttk.Combobox(grid, values=[str(x) for x in range(30, 95, 5)],
                                 width=6, state="readonly")
        self.cb_q.set(str(core.settings["quality"]))
        self.cb_q.grid(row=0, column=3, sticky="w", padx=6)
        tk.Label(grid, text="Màn hình", font=(F, 9), fg=C["dim"], bg=C["card"]).grid(
            row=1, column=0, sticky="w", pady=3)
        self.mons = capture.list_monitors()
        self.cb_mon = ttk.Combobox(grid, values=["%d — %s" % (m["index"], m["label"])
                                                 for m in self.mons],
                                   state="readonly")
        cur = next((i for i, m in enumerate(self.mons)
                    if m["index"] == core.settings["monitor"]), 0)
        self.cb_mon.current(cur)
        self.cb_mon.grid(row=1, column=1, columnspan=3, sticky="ew", padx=6)
        self.var_cbsync = tk.BooleanVar(value=bool(core.settings["clipboard_sync"]))
        ttk.Checkbutton(grid, text="Đồng bộ clipboard", variable=self.var_cbsync).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=4)
        self.btn(grid, "Áp dụng", self._apply_settings, primary=True).grid(
            row=2, column=3, sticky="e", pady=4)

        tk.Frame(b, bg=C["line"], height=1).grid(row=7, column=0, sticky="ew", pady=12)
        row = tk.Frame(b, bg=C["card"])
        row.grid(row=8, column=0, sticky="ew")
        tk.Label(row, text="🌐  Relay (kết nối qua internet)", font=(F, 11, "bold"),
                 fg=C["text"], bg=C["card"]).pack(side="left")
        self.field_label(b, "Địa chỉ relay WebSocket").grid(row=9, column=0, sticky="w",
                                                           pady=(8, 3))
        self.var_relay = tk.StringVar(value=str(self.cfg.get("relay_url", "")))
        tk.Entry(b, textvariable=self.var_relay, font=(F, 9), bg=C["elev"],
                 fg=C["text"], insertbackground=C["text"], relief="flat").grid(
            row=10, column=0, sticky="ew", ipady=6, ipadx=6)
        row = tk.Frame(b, bg=C["card"])
        row.grid(row=11, column=0, sticky="ew", pady=8)
        self.var_relay_on = tk.BooleanVar(value=bool(self.cfg.get("relay_enabled")))
        ttk.Checkbutton(row, text="Bật relay", variable=self.var_relay_on).pack(side="left")
        self.btn(row, "Áp dụng relay", self._apply_relay, primary=True).pack(
            side="right")

        # === activity log ===
        lg = self.card(page)
        lg.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(14, 0))
        lg.rowconfigure(1, weight=1)
        lg.columnconfigure(0, weight=1)
        head = tk.Frame(lg, bg=C["card"])
        head.grid(row=0, column=0, sticky="ew")
        tk.Label(head, text="📜  Nhật ký hoạt động", font=(F, 11, "bold"), fg=C["text"],
                 bg=C["card"]).pack(side="left")
        ttk.Checkbutton(head, text="Tự cuộn", variable=self.auto_scroll).pack(
            side="right", padx=8)
        self.btn(head, "Xóa log", self._clear_log).pack(side="right")
        self.txt_log = tk.Text(lg, height=8, state="disabled", font=(MONO, 9),
                               bg=C["elev"], fg=C["text"], relief="flat", padx=10,
                               pady=8, wrap="none")
        self.txt_log.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        for tag, color in (("time", C["dim"]), ("info", C["text"]), ("ok", C["ok"]),
                           ("warn", C["warn"]), ("err", C["err"]), ("acc", C["acc"])):
            self.txt_log.tag_configure(tag, foreground=color)

    def _make_qr(self):
        url = build_urls(self.cfg)[0] + "/?id=" + str(self.cfg.get("device_id", ""))
        try:
            img = qrcode.make(url).resize((150, 150))
            self._qr_img = ImageTk.PhotoImage(img)
            self.qr_lbl.configure(image=self._qr_img)
        except Exception as e:
            self.toast("QR lỗi: %s" % e, "err")

    def _toggle_pw(self):
        self.show_pw.set(not self.show_pw.get())
        self.ent_pw.configure(show="" if self.show_pw.get() else "•")

    def _copy(self, text, msg):
        self.clipboard_clear()
        self.clipboard_append(text)
        self.toast(msg, "ok")

    def _copy_info(self):
        urls = build_urls(self.cfg)
        txt = ("TouchLink\nID: %s\nMật khẩu: %s\nLAN: %s\n?id=%s\nMobile web: "
               "https://touchlink.vercel.app" % (
                   self.var_id.get(), self.var_pw.get(), urls[0],
                   self.var_id.get()))
        self.clipboard_clear()
        self.clipboard_append(txt)
        self.toast("Đã sao chép thông tin kết nối", "ok")

    def _regen_pw(self):
        if not messagebox.askyesno("TouchLink", "Sinh lại mật khẩu mới?"):
            return
        self.cfg["password_enc"] = secure.protect(cfgmod.gen_password())
        cfgmod.save(self.cfg)
        self.var_pw.set(password_plain(self.cfg))
        core.log("Đã sinh mật khẩu mới.")
        core.broadcast_event("history", ("setting", "Sinh mật khẩu mới"))
        self.toast("Đã tạo mật khẩu mới", "ok")

    def _apply_settings(self):
        try:
            core.settings["fps"] = int(self.cb_fps.get())
            core.settings["quality"] = int(self.cb_q.get())
            if self.cb_mon.current() >= 0:
                core.settings["monitor"] = self.mons[self.cb_mon.current()]["index"]
            core.settings["clipboard_sync"] = bool(self.var_cbsync.get())
            self.cfg.update(core.settings)
            cfgmod.save(self.cfg)
            core.broadcast_event("settings", dict(core.settings))
            core.log("Đã áp dụng cài đặt: fps=%s quality=%s scale=%s monitor=%s" % (
                core.settings["fps"], core.settings["quality"],
                core.settings["scale"], core.settings["monitor"]))
            core.broadcast_event("history", ("setting",
                "Áp dụng: fps=%s, quality=%s, monitor=%s" % (
                    core.settings["fps"], core.settings["quality"],
                    core.settings["monitor"])))
            self.toast("Đã áp dụng cài đặt", "ok")
        except Exception as e:
            self.toast("Cài đặt lỗi: %s" % e, "err")

    def _apply_relay(self):
        self.cfg["relay_url"] = self.var_relay.get().strip()
        self.cfg["relay_enabled"] = bool(self.var_relay_on.get())
        cfgmod.save(self.cfg)
        url = self.cfg["relay_url"]
        if self.cfg["relay_enabled"]:
            if not url.lower().startswith(("ws://", "wss://")):
                self.toast("URL relay phải bắt đầu bằng ws:// hoặc wss://", "err")
                return
        loop = core.get_loop()
        if loop and loop.is_running():
            try:
                import asyncio
                if self.var_relay_on.get():
                    asyncio.run_coroutine_threadsafe(
                        relay_client.relay_client.start(self.cfg, self.events_q), loop)
                    self.toast("Đang kết nối relay…", "warn")
                else:
                    asyncio.run_coroutine_threadsafe(
                        relay_client.relay_client.stop(), loop)
                    self.toast("Đã tắt relay", "ok")
            except Exception as e:
                self.toast("Relay lỗi: %s" % e, "err")

    def _clear_log(self):
        self.txt_log.configure(state="normal")
        self.txt_log.delete("1.0", "end")
        self.txt_log.configure(state="disabled")

    # ---------- page: màn hình chờ ----------
    def _build_page_screen(self):
        page = self._page("screen")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        head = tk.Frame(page, bg=C["bg"])
        head.grid(row=0, column=0, sticky="ew")
        tk.Label(head, text="📺  Màn hình chờ", font=(F, 12, "bold"), fg=C["text"],
                 bg=C["bg"]).pack(side="left")
        tk.Label(head, text="Xem trước màn hình đang được chia sẻ (2 khung/giây)",
                 font=(F, 9), fg=C["dim"], bg=C["bg"]).pack(side="left", padx=(10, 0))
        self.prev_lbl = tk.Label(page, bg="#000000", text="Đang tải…", fg=C["dim"])
        self.prev_lbl.grid(row=1, column=0, sticky="nsew", pady=(12, 0))

    def _start_preview(self):
        if self._prev_running:
            return
        self._prev_running = True
        self._prev_pil = None
        threading.Thread(target=self._preview_worker, daemon=True).start()
        self._preview_tick()

    def _stop_preview(self):
        self._prev_running = False

    def _preview_worker(self):
        import io
        from PIL import Image
        while self._prev_running:
            try:
                jpeg, m = __import__("capture").grab_jpeg(
                    int(core.settings["monitor"]), 40, 55)
                self._prev_pil = Image.open(io.BytesIO(jpeg))
            except Exception:
                pass
            time.sleep(0.5)

    def _preview_tick(self):
        if not self._prev_running:
            return
        img = getattr(self, "_prev_pil", None)
        if img is not None:
            w = max(200, self.prev_lbl.winfo_width() or 720)
            ratio = w / img.width
            h = int(img.height * ratio)
            self._prev_img = ImageTk.PhotoImage(
                img.resize((w, h)).convert("RGB"))
            self.prev_lbl.configure(image=self._prev_img, text="")
        self.after(500, self._preview_tick)

    # ---------- page: lịch sử ----------
    def _build_page_hist(self):
        page = self._page("hist")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(0, weight=1)
        box = self.card(page)
        box.grid(row=0, column=0, sticky="nsew")
        box.rowconfigure(1, weight=1)
        box.columnconfigure(0, weight=1)
        head = tk.Frame(box, bg=C["card"])
        head.grid(row=0, column=0, sticky="ew")
        tk.Label(head, text="🕘  Lịch sử kết nối", font=(F, 12, "bold"), fg=C["text"],
                 bg=C["card"]).pack(side="left")
        tk.Label(head, text="Sự kiện thật: người xem, relay, cài đặt", font=(F, 9),
                 fg=C["dim"], bg=C["card"]).pack(side="left", padx=(10, 0))
        self.tree_hist = ttk.Treeview(box, columns=("t", "k", "m"), show="headings",
                                      height=16)
        self.tree_hist.heading("t", text="Thời gian")
        self.tree_hist.heading("k", text="Loại")
        self.tree_hist.heading("m", text="Sự kiện")
        self.tree_hist.column("t", width=110, anchor="w")
        self.tree_hist.column("k", width=120, anchor="w")
        self.tree_hist.column("m", width=560, anchor="w")
        self.tree_hist.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        kind_vn = {"viewer": "Người xem", "relay": "Relay", "setting": "Cài đặt",
                   "server": "Máy chủ", "chat": "Chat"}
        self._hist_add_row = lambda rec: self.tree_hist.insert(
            "", "end", values=(time.strftime("%H:%M:%S"),
                               kind_vn.get(rec[0], rec[0]), rec[1]))

    # ---------- page: thiết bị ----------
    def _build_page_dev(self):
        page = self._page("dev")
        page.columnconfigure(0, weight=1)
        page.columnconfigure(1, weight=1)
        page.rowconfigure(1, weight=1)
        box = self.card(page)
        box.grid(row=0, column=0, columnspan=2, sticky="nsew")
        box.columnconfigure(0, weight=1)
        tk.Label(box, text="📱  Danh sách thiết bị", font=(F, 12, "bold"), fg=C["text"],
                 bg=C["card"]).pack(anchor="w")
        tk.Label(box, text="Máy tính này và các thiết bị đang kết nối (dữ liệu thật)",
                 font=(F, 9), fg=C["dim"], bg=C["card"]).pack(anchor="w")
        grid = tk.Frame(box, bg=C["card"])
        grid.pack(fill="x", pady=10)
        info = ("Máy: %s\nID: %s\nPhiên bản: v%s\nLAN: %s\nRelay: %s" % (
            os.environ.get("COMPUTERNAME", "PC"), self.cfg.get("device_id", "—"),
            cfgmod.VERSION, ", ".join(build_urls(self.cfg)),
            self.cfg.get("relay_url", "—")))
        tk.Label(grid, text=info, font=(MONO, 10), fg=C["text"], bg=C["elev"],
                 justify="left", padx=12, pady=10).pack(side="left", fill="x",
                                                        expand=True)
        row = tk.Frame(page, bg=C["bg"])
        row.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(14, 0))
        row.columnconfigure(0, weight=1)
        row.rowconfigure(0, weight=1)
        box2 = self.card(row)
        box2.grid(row=0, column=0, sticky="nsew")
        box2.rowconfigure(1, weight=1)
        box2.columnconfigure(0, weight=1)
        tk.Label(box2, text="Người xem đang kết nối", font=(F, 11, "bold"),
                 fg=C["text"], bg=C["card"]).pack(anchor="w")
        self.lbl_viewers = tk.Label(box2, text="—", font=(MONO, 10), fg=C["dim"],
                                    bg=C["card"], justify="left", anchor="nw")
        self.lbl_viewers.pack(fill="both", expand=True, pady=(8, 0))

    def _refresh_devices(self):
        if self._page_key != "dev":
            return
        conns = core.clients_snapshot()
        if conns:
            self.lbl_viewers.configure(text="\n".join(
                "• %s  (từ %s)" % (n, s) for n, s in conns), fg=C["text"])
        else:
            self.lbl_viewers.configure(
                text="Không có ai đang xem.\nMở https://touchlink.vercel.app trên "
                     "điện thoại và nhập ID + mật khẩu.", fg=C["dim"])
        self.after(1000, self._refresh_devices)

    # ---------- page: cài đặt ----------
    def _build_page_set(self):
        page = self._page("set")
        page.columnconfigure(0, weight=1)
        box = self.card(page)
        box.grid(row=0, column=0, sticky="new")
        box.columnconfigure(0, weight=1)
        tk.Label(box, text="⚙  Cài đặt", font=(F, 12, "bold"), fg=C["text"],
                 bg=C["card"]).pack(anchor="w")
        tk.Label(box, text="Cổng LAN server (khởi động lại app để áp dụng)",
                 font=(F, 9), fg=C["dim"], bg=C["card"]).pack(anchor="w",
                                                              pady=(10, 3))
        row = tk.Frame(box, bg=C["card"])
        row.pack(fill="x")
        self.var_port = tk.StringVar(value=str(self.cfg.get("port", cfgmod.DEFAULT_PORT)))
        ttk.Entry(row, textvariable=self.var_port, font=(MONO, 11), width=10).pack(
            side="left", ipady=4)
        self.btn(row, "Lưu cổng", self._save_port, primary=True).pack(
            side="left", padx=8)
        self.btn(row, "Mở thư mục cấu hình", self._open_cfgdir).pack(side="left", padx=4)
        tk.Label(box, text="config.json nằm cạnh TouchLink.exe (chứa ID, mật khẩu mã "
                 "hóa, cổng, relay). Xóa file này = sinh lại ID/mật khẩu mới.",
                 font=(F, 9), fg=C["dim"], bg=C["card"], justify="left",
                 wraplength=760).pack(anchor="w", pady=(10, 0))
        tk.Label(box, text="TouchLink v%s — mã nguồn: "
                 "github.com/Revizneid/touchlink — mobile web: "
                 "touchlink.vercel.app" % cfgmod.VERSION,
                 font=(F, 9), fg=C["dim"], bg=C["card"]).pack(anchor="w", pady=(12, 0))
        if core.settings.get("_safe_test"):
            tk.Label(box, text="⚠ Đang chạy SAFE-TEST: thao tác điều khiển KHÔNG được "
                     "thực thi thật.", font=(F, 9, "bold"), fg=C["warn"],
                     bg=C["card"]).pack(anchor="w", pady=(10, 0))

    def _save_port(self):
        try:
            port = int(self.var_port.get())
            if not (1024 <= port <= 65535):
                raise ValueError
        except Exception:
            self.toast("Cổng không hợp lệ (1024–65535)", "err")
            return
        self.cfg["port"] = port
        cfgmod.save(self.cfg)
        core.broadcast_event("history", ("setting", "Lưu cổng server: %d" % port))
        self.toast("Đã lưu cổng %d — khởi động lại app để áp dụng" % port, "ok")

    def _open_cfgdir(self):
        try:
            os.startfile(cfgmod.BASE_DIR)  # noqa: chỉ Windows
        except Exception as e:
            self.toast("Không mở được thư mục: %s" % e, "err")

    # ---------- status badges ----------
    def _update_status_badges(self):
        def set_badge(key, color, label):
            self.dots[key].delete("all")
            self.dots[key].create_oval(1, 1, 9, 9, fill=color, outline="")
            self.slbls[key].configure(text=label)

        if self.server_running:
            set_badge("server", C["ok"], "Server LAN :%s" % self.cfg.get("port"))
        else:
            set_badge("server", C["err"], "Server lỗi")
        relay_map = {
            "registered": (C["ok"], "Relay: kết nối"),
            "connecting": (C["warn"], "Relay: đang nối"),
            "retrying": (C["warn"], "Relay: thử lại"),
            "error": (C["err"], "Relay: lỗi"),
            "stopped": (C["dim"], "Relay: tắt"),
        }
        color, label = relay_map.get(self.relay_status, (C["dim"], "Relay: tắt"))
        set_badge("relay", color, label)
        if self.viewer_count > 0:
            set_badge("viewers", C["ok"], "Người xem: %d" % self.viewer_count)
        else:
            set_badge("viewers", C["dim"], "Người xem: 0")
        if self.relay_status == "registered":
            set_badge("reg", C["ok"], "ID đã đăng ký")
        else:
            set_badge("reg", C["dim"], "ID chưa đăng ký")
        self.hdr_dot.delete("all")
        hdr_color = C["ok"] if (self.server_running and self.relay_status in
                                ("registered", "stopped")) else C["warn"]
        self.hdr_dot.create_oval(1, 1, 9, 9, fill=hdr_color, outline="")
        self.hdr_status.configure(
            text="Đang hoạt động" if self.server_running else "Đang khởi động…",
            fg=C["text"] if self.server_running else C["dim"])

    # ---------- event polling ----------
    def _classify(self, text):
        low = text.lower()
        if "lỗi" in low or "error" in low:
            return "err"
        if "viewer kết nối" in low or "đã đăng ký" in low:
            return "ok"
        if "rời khỏi" in low or "relay" in low:
            return "acc"
        return "info"

    def _poll(self):
        try:
            for _ in range(300):
                kind, data = self.events_q.get_nowait()
                if kind == "log":
                    tag = self._classify(str(data))
                    self.txt_log.configure(state="normal")
                    self.txt_log.insert("end", "[%s] " % time.strftime("%H:%M:%S"),
                                        "time")
                    self.txt_log.insert("end", str(data) + "\n", tag)
                    if int(self.txt_log.index("end-1c").split(".")[0]) > 500:
                        self.txt_log.delete("1.0", "60.0")
                    self.txt_log.configure(state="disabled")
                    if self.auto_scroll.get():
                        self.txt_log.see("end")
                elif kind == "clients":
                    self.viewer_count = int(data)
                    self._update_status_badges()
                elif kind == "relay":
                    self.relay_status = str(data)
                    self._update_status_badges()
                elif kind == "server":
                    self.server_running = bool(data)
                    self._update_status_badges()
                elif kind == "chat":
                    self.toast("💬 %s: %s" % data)
                elif kind == "history":
                    self._hist_add_row(data)
                elif kind == "settings":
                    pass
        except queue.Empty:
            pass
        self.after(250, self._poll)


def run_gui(cfg, events_q):
    app = TouchLinkGUI(cfg, events_q)
    app._make_qr()
    app.mainloop()
    os._exit(0)
