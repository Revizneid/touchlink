"""desktop/overlay.py — Thanh overlay 'đang được điều khiển' và hotkey khẩn cấp.

Luôn nổi (topmost), không lấy focus, hiển thị tên/IP viewer đã che bớt.
Khi headless: chỉ in cảnh báo console, không tạo Tk window.

Phím nóng khẩn cấp: Ctrl+Alt+Shift+F12 (RegisterHotKey WinAPI).
"""
from __future__ import annotations

import ctypes
import platform
import threading
import time
from typing import Callable

import core


# ---------------------------------------------------------------------------
# Ẩn octet cuối IP để không lộ IP đầy đủ trên thanh overlay
# ---------------------------------------------------------------------------

def _mask_name(raw: str) -> str:
    """'Relay viewer (1.2.3.4)' → 'Relay viewer (1.2.3.x)'."""
    import re
    return re.sub(r'(\d+\.\d+\.\d+\.)\d+', r'\g<1>x', raw)


# ---------------------------------------------------------------------------
# Hotkey khẩn cấp Ctrl+Alt+Shift+F12
# ---------------------------------------------------------------------------

_WM_HOTKEY = 0x0312
_HOTKEY_ID  = 0xBEEF  # ID tùy chọn, không xung đột với app khác

_MOD_ALT   = 0x0001
_MOD_CTRL  = 0x0002
_MOD_SHIFT = 0x0004
_VK_F12    = 0x7B

_hotkey_registered = False
_hotkey_thread: threading.Thread | None = None


def _register_hotkey(callback: Callable[[], None]) -> None:
    """Đăng ký hotkey toàn cục trong thread riêng (Windows-only).

    Thread này chạy một message loop đơn giản để nhận WM_HOTKEY.
    Gọi callback trong thread khi hotkey được nhấn.
    """
    global _hotkey_registered, _hotkey_thread
    if platform.system() != "Windows":
        return
    if _hotkey_thread and _hotkey_thread.is_alive():
        return

    def _loop():
        global _hotkey_registered
        user32 = ctypes.windll.user32
        mods = _MOD_CTRL | _MOD_ALT | _MOD_SHIFT
        ok = user32.RegisterHotKey(None, _HOTKEY_ID, mods, _VK_F12)
        if not ok:
            core.log("Overlay: không đăng ký được hotkey Ctrl+Alt+Shift+F12 (có thể bị app khác giữ)")
            return
        _hotkey_registered = True
        core.log("Overlay: đã đăng ký hotkey khẩn cấp Ctrl+Alt+Shift+F12")
        msg = ctypes.wintypes.MSG()
        while True:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret == 0 or ret == -1:
                break
            if msg.message == _WM_HOTKEY and msg.wParam == _HOTKEY_ID:
                core.log("Overlay: hotkey Ctrl+Alt+Shift+F12 — ngắt toàn bộ viewer")
                callback()
        user32.UnregisterHotKey(None, _HOTKEY_ID)
        _hotkey_registered = False

    _hotkey_thread = threading.Thread(target=_loop, daemon=True, name="tl-hotkey")
    _hotkey_thread.start()


# ---------------------------------------------------------------------------
# Overlay Tkinter
# ---------------------------------------------------------------------------

class ControlOverlay:
    """Thanh overlay luôn nổi — Tk Toplevel, không lấy focus.

    Dùng trong chế độ GUI. Trong headless: chỉ log console.
    """

    def __init__(self, root, headless: bool = False) -> None:
        self._root = root
        self._headless = headless
        self._win: object = None   # Tk Toplevel
        self._visible = False
        self._disconnect_cb: Callable | None = None
        self._after_id = None

        if not headless:
            self._build()
        _register_hotkey(self._on_hotkey)

    # ------------------------------------------------------------------
    # Xây dựng cửa sổ Tk
    # ------------------------------------------------------------------

    def _build(self) -> None:
        try:
            import tkinter as tk
            win = tk.Toplevel(self._root)
            win.title("TouchLink")
            win.overrideredirect(True)   # không có thanh tiêu đề
            win.attributes("-topmost", True)
            win.attributes("-alpha", 0.93)
            win.resizable(False, False)
            # Không cho cửa sổ nhận focus
            win.wm_attributes("-toolwindow", True)

            # --- Style ---
            BG = "#1e293b"
            ACCENT = "#f59e0b"
            FG = "#f1f5f9"

            frame = tk.Frame(win, bg=BG, padx=10, pady=6)
            frame.pack(fill="x")

            # Biểu tượng + tiêu đề
            tk.Label(frame, text="🔴", bg=BG, font=("Segoe UI", 10)).pack(side="left")
            self._lbl = tk.Label(
                frame, text="TouchLink: đang được điều khiển",
                bg=BG, fg=FG, font=("Segoe UI", 9, "bold"), padx=6
            )
            self._lbl.pack(side="left")

            # Nút Ngắt kết nối
            btn = tk.Button(
                frame,
                text="Ngắt kết nối",
                bg=ACCENT, fg="#000", font=("Segoe UI", 9, "bold"),
                relief="flat", padx=10, pady=2,
                cursor="hand2",
                command=self._on_disconnect_btn,
            )
            btn.pack(side="right")

            win.withdraw()  # ẩn lúc đầu
            self._win = win

            # Đặt vị trí góc trên phải màn hình (sau khi build xong)
            win.update_idletasks()
            self._reposition()

        except Exception as e:
            core.log("Overlay: không khởi tạo được cửa sổ (%s)" % e)
            self._win = None

    def _reposition(self) -> None:
        """Đặt overlay ở góc trên phải màn hình."""
        if self._win is None:
            return
        try:
            import tkinter as tk
            sw = self._root.winfo_screenwidth()
            self._win.update_idletasks()
            w = self._win.winfo_reqwidth()
            h = self._win.winfo_reqheight()
            margin = 8
            x = sw - w - margin
            y = margin
            self._win.geometry("+%d+%d" % (x, y))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # API công khai
    # ------------------------------------------------------------------

    def set_disconnect_callback(self, cb: Callable) -> None:
        """Đăng ký callback được gọi khi người dùng nhấn Ngắt / hotkey."""
        self._disconnect_cb = cb

    def show(self, viewer_names: list[str]) -> None:
        """Hiện overlay khi có ≥1 viewer đã xác thực."""
        if self._headless:
            names = ", ".join(_mask_name(n) for n in viewer_names)
            core.log("⚠ CẢNH BÁO: Máy đang được điều khiển từ xa! Viewer: %s" % names)
            return
        if self._win is None:
            return
        names = ", ".join(_mask_name(n) for n in viewer_names)
        label = "TouchLink: đang được điều khiển từ %s" % (names or "thiết bị khác")
        try:
            self._lbl.config(text=label)
            self._win.deiconify()
            self._win.lift()
            self._win.attributes("-topmost", True)
            self._reposition()
            self._visible = True
        except Exception as e:
            core.log("Overlay show lỗi: %s" % e)

    def hide(self) -> None:
        """Ẩn overlay khi không còn viewer nào."""
        if self._headless:
            return
        if self._win is None:
            return
        try:
            self._win.withdraw()
            self._visible = False
        except Exception:
            pass

    def update_viewers(self, viewer_names: list[str]) -> None:
        """Cập nhật trạng thái dựa vào danh sách viewer hiện tại."""
        if viewer_names:
            self.show(viewer_names)
        else:
            self.hide()

    # ------------------------------------------------------------------
    # Sự kiện nội bộ
    # ------------------------------------------------------------------

    def _on_disconnect_btn(self) -> None:
        core.log("Overlay: người dùng nhấn Ngắt kết nối")
        self._do_disconnect()

    def _on_hotkey(self) -> None:
        """Gọi từ hotkey thread — schedule về Tk thread nếu cần."""
        if self._headless:
            core.log("Hotkey khẩn cấp: đang ngắt toàn bộ viewer...")
            self._do_disconnect()
        else:
            try:
                self._root.after(0, self._do_disconnect)
            except Exception:
                self._do_disconnect()

    def _do_disconnect(self) -> None:
        """Ngắt toàn bộ viewer — gọi callback từ GUI."""
        if self._disconnect_cb:
            try:
                self._disconnect_cb()
            except Exception as e:
                core.log("Overlay disconnect callback lỗi: %s" % e)


# ---------------------------------------------------------------------------
# Singleton — được khởi tạo từ gui.py
# ---------------------------------------------------------------------------

_overlay: ControlOverlay | None = None


def init(root, headless: bool = False) -> ControlOverlay:
    global _overlay
    _overlay = ControlOverlay(root, headless=headless)
    return _overlay


def get() -> ControlOverlay | None:
    return _overlay
