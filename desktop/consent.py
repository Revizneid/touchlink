"""desktop/consent.py — Hộp thoại xác nhận kết nối mới từ viewer.

Khi bật "Yêu cầu xác nhận khi có kết nối mới" (mặc định BẬT cho relay):
- Hiện hộp thoại Cho phép / Chỉ xem / Từ chối
- Timeout 30 giây → tự động từ chối

Headless: từ chối ngay lập tức với log cảnh báo (không thể hiện GUI).

API:
    consent.ask(viewer_name, is_relay, callback)
    callback(result: str) với result ∈ {"allow", "view_only", "deny"}

Tests: mock UI qua monkey-patch của `_show_dialog`.
"""
from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable

import core

CONSENT_TIMEOUT_S = 30  # giây trước khi tự động từ chối

# Kết quả
ALLOW    = "allow"
VIEW_ONLY = "view_only"
DENY     = "deny"


# ---------------------------------------------------------------------------
# Cấu hình
# ---------------------------------------------------------------------------

def is_consent_required(cfg: dict, is_relay: bool) -> bool:
    """Kiểm tra tùy chọn 'Yêu cầu xác nhận khi có kết nối mới'.

    Mặc định: BẬT với kết nối qua relay, TẮT với LAN.
    Người dùng có thể override trong settings.
    """
    key = "consent_relay" if is_relay else "consent_lan"
    if key in cfg:
        return bool(cfg[key])
    # Default: bật relay, tắt LAN
    return is_relay


# ---------------------------------------------------------------------------
# Mock-able dialog function (để test)
# ---------------------------------------------------------------------------

def _show_dialog(viewer_name: str, is_relay: bool, timeout_s: int) -> str:
    """Hiển thị hộp thoại Tk trong main thread và chờ kết quả.

    Trả về: 'allow', 'view_only', 'deny' (nếu timeout hoặc đóng → 'deny').
    Được monkey-patch trong tests để không cần GUI thật.
    """
    try:
        import tkinter as tk
        from tkinter import font as tkfont
    except ImportError:
        return DENY

    result: list[str] = [DENY]
    done = threading.Event()

    def _make_ui():
        win = tk.Toplevel()
        win.title("TouchLink — Yêu cầu kết nối")
        win.attributes("-topmost", True)
        win.resizable(False, False)
        win.grab_set()  # modal

        BG = "#0f172a"; FG = "#f1f5f9"; ACCENT = "#3b82f6"
        WARN = "#f59e0b"; DENY_C = "#ef4444"
        win.configure(bg=BG)

        BOLD = ("Segoe UI", 11, "bold")
        NORM = ("Segoe UI", 10)

        # Đặt giữa màn hình
        win.update_idletasks()
        sw = win.winfo_screenwidth(); sh = win.winfo_screenheight()

        tk.Label(win, text="🔔  Yêu cầu kết nối mới", bg=BG, fg=WARN,
                 font=("Segoe UI", 13, "bold"), pady=10).pack(fill="x", padx=20)
        src = ("Relay (internet)" if is_relay else "Mạng LAN")
        tk.Label(win, text=f"Nguồn: {src}", bg=BG, fg="#94a3b8", font=NORM).pack()
        tk.Label(win, text=viewer_name, bg=BG, fg=FG, font=BOLD, pady=4).pack()
        tk.Label(win, text="muốn xem và điều khiển máy tính này.", bg=BG, fg=FG,
                 font=NORM).pack(pady=(0, 8))

        # Đồng hồ đếm ngược
        var_t = tk.StringVar(value="Tự từ chối sau %ds" % timeout_s)
        tk.Label(win, textvariable=var_t, bg=BG, fg="#64748b", font=("Segoe UI", 9)).pack()

        sep = tk.Frame(win, bg="#1e293b", height=1)
        sep.pack(fill="x", padx=16, pady=8)

        # Các nút
        btn_frame = tk.Frame(win, bg=BG)
        btn_frame.pack(fill="x", padx=20, pady=(0, 16))

        def _set(r):
            result[0] = r
            done.set()
            try:
                win.after(0, win.destroy)
            except Exception:
                pass

        def _style(bg, fg="#fff"):
            return {"bg": bg, "fg": fg, "font": ("Segoe UI", 10, "bold"),
                        "relief": "flat", "padx": 14, "pady": 6, "cursor": "hand2",
                        "borderwidth": 0, "highlightthickness": 0}

        tk.Button(btn_frame, text="✓ Cho phép", command=lambda: _set(ALLOW),
                  **_style(ACCENT)).pack(side="left", expand=True, fill="x", padx=(0,4))
        tk.Button(btn_frame, text="👁 Chỉ xem", command=lambda: _set(VIEW_ONLY),
                  **_style("#6366f1")).pack(side="left", expand=True, fill="x", padx=4)
        tk.Button(btn_frame, text="✗ Từ chối", command=lambda: _set(DENY),
                  **_style(DENY_C)).pack(side="left", expand=True, fill="x", padx=(4,0))

        # Căn giữa màn hình
        win.update_idletasks()
        w = win.winfo_reqwidth(); h = win.winfo_reqheight()
        win.geometry("%dx%d+%d+%d" % (max(360, w), h,
                                       (sw - max(360, w)) // 2, (sh - h) // 2))

        # Đếm ngược
        remaining = [timeout_s]
        def _countdown():
            if done.is_set():
                return
            remaining[0] -= 1
            if remaining[0] <= 0:
                var_t.set("Tự động từ chối!")
                _set(DENY)
            else:
                var_t.set("Tự từ chối sau %ds" % remaining[0])
                try:
                    win.after(1000, _countdown)
                except Exception:
                    pass
        win.after(1000, _countdown)

        win.protocol("WM_DELETE_WINDOW", lambda: _set(DENY))
        win.wait_window()

    # Chạy trong main (Tk) thread nếu được gọi từ thread khác
    import threading as _th
    if _th.current_thread() is _th.main_thread():
        _make_ui()
    else:
        # Schedule về Tk main loop
        try:
            import tkinter as tk
            r = tk.Tk()
            r.withdraw()
            r.after(0, _make_ui)
            # Dùng after_idle để wait
            # Tuy nhiên nếu không có Tk root có sẵn, ta phải tạo mới
            r.mainloop()
        except Exception:
            return DENY
    return result[0]


# ---------------------------------------------------------------------------
# Public API — thread-safe, dùng asyncio callback
# ---------------------------------------------------------------------------

def ask(
    viewer_name: str,
    is_relay: bool,
    cfg: dict,
    headless: bool,
    loop: asyncio.AbstractEventLoop,
    callback: Callable[[str], None],
) -> None:
    """Hỏi người dùng trong background thread; gọi callback với kết quả.

    callback được gọi thread-safely qua loop.call_soon_threadsafe.
    Nếu headless: từ chối ngay lập tức (không GUI).
    """
    if headless:
        core.log(f"Consent: headless mode → tự động từ chối viewer '{viewer_name}'")
        loop.call_soon_threadsafe(callback, DENY)
        return

    if not is_consent_required(cfg, is_relay):
        loop.call_soon_threadsafe(callback, ALLOW)
        return

    def _run():
        try:
            res = _show_dialog(viewer_name, is_relay, CONSENT_TIMEOUT_S)
        except Exception as e:
            core.log(f"Consent dialog lỗi: {e}")
            res = DENY
        core.log(f"Consent: '{viewer_name}' → {res}")
        loop.call_soon_threadsafe(callback, res)

    t = threading.Thread(target=_run, daemon=True, name="tl-consent")
    t.start()


# ---------------------------------------------------------------------------
# Async wrapper tiện dụng
# ---------------------------------------------------------------------------

async def ask_async(
    viewer_name: str,
    is_relay: bool,
    cfg: dict,
    headless: bool,
) -> str:
    """Async version — await để lấy kết quả."""
    loop = asyncio.get_running_loop()
    fut: asyncio.Future[str] = loop.create_future()

    def _cb(result: str) -> None:
        if not fut.done():
            fut.set_result(result)

    ask(viewer_name, is_relay, cfg, headless, loop, _cb)
    return await fut
