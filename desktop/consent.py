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

CONSENT_TIMEOUT_S = 30  # giây trước khi tự động từ chối (relay server cho phép 45s)

# Kết quả
ALLOW    = "allow"
VIEW_ONLY = "view_only"
DENY     = "deny"

# Handler đăng ký từ GUI chính (nếu GUI đang chạy)
_gui_handler: Callable[[str, bool, int, Callable[[str], None]], None] | None = None


def register_gui_handler(
    handler: Callable[[str, bool, int, Callable[[str], None]], None] | None,
) -> None:
    """Đăng ký GUI dialog handler từ luồng chính của Tkinter (TouchLinkGUI)."""
    global _gui_handler
    _gui_handler = handler


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
    """Hiển thị hộp thoại Tk và chờ kết quả.

    Trả về: 'allow', 'view_only', 'deny' (nếu timeout hoặc đóng → 'deny').
    Được monkey-patch trong tests để không cần GUI thật.
    """
    try:
        import tkinter as tk
    except ImportError:
        return DENY

    result: list[str] = [DENY]
    done = threading.Event()
    r_root: tk.Tk | None = None

    import threading as _th
    is_main = (_th.current_thread() is _th.main_thread())
    if not is_main:
        try:
            r_root = tk.Tk()
            r_root.withdraw()
        except Exception:
            return DENY

    win: tk.Toplevel | None = None

    def _set(r_val: str) -> None:
        if done.is_set():
            return
        result[0] = r_val
        done.set()
        if win is not None:
            try:
                win.destroy()
            except Exception:
                pass
        if r_root is not None:
            try:
                r_root.quit()
                r_root.destroy()
            except Exception:
                pass

    def _make_ui() -> None:
        nonlocal win
        try:
            win = tk.Toplevel(r_root) if r_root else tk.Toplevel()
            win.title("TouchLink — Yêu cầu kết nối")
            win.attributes("-topmost", True)
            win.resizable(False, False)
            try:
                win.grab_set()  # modal
            except Exception:
                pass

            BG = "#0f172a"; FG = "#f1f5f9"; ACCENT = "#3b82f6"
            WARN = "#f59e0b"; DENY_C = "#ef4444"
            win.configure(bg=BG)

            BOLD = ("Segoe UI", 11, "bold")
            NORM = ("Segoe UI", 10)

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
            sw = win.winfo_screenwidth(); sh = win.winfo_screenheight()
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
            if is_main:
                win.wait_window()
        except Exception:
            _set(DENY)

    if is_main:
        _make_ui()
    else:
        r_root.after(0, _make_ui)
        r_root.mainloop()

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
    """Hỏi người dùng; gọi callback với kết quả.

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

    # Nếu có GUI handler đăng ký từ luồng chính của Tkinter: dùng trực tiếp
    if _gui_handler is not None:
        try:
            _gui_handler(
                viewer_name,
                is_relay,
                CONSENT_TIMEOUT_S,
                lambda res: loop.call_soon_threadsafe(callback, res),
            )
            return
        except Exception as e:
            core.log(f"GUI consent handler lỗi ({e}) → fallback dialog")

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
