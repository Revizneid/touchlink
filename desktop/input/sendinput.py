"""Windows input injection using ctypes SendInput.

An toàn: không log nhạy cảm, không dùng pyautogui, không có sleep cố định.
"""
from __future__ import annotations

import ctypes
import threading
from abc import ABC, abstractmethod
from ctypes import wintypes

PUL = ctypes.POINTER(ctypes.c_ulong)

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_UNICODE = 0x0004

MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
WHEEL_DELTA = 120

KEYMAP = {
    "enter": {"vk": 0x0D, "scan": 0x1C},
    "return": {"vk": 0x0D, "scan": 0x1C},
    "backspace": {"vk": 0x08, "scan": 0x0E},
    "tab": {"vk": 0x09, "scan": 0x0F},
    "escape": {"vk": 0x1B, "scan": 0x01},
    "esc": {"vk": 0x1B, "scan": 0x01},
    "space": {"vk": 0x20, "scan": 0x39},
    "up": {"vk": 0x26, "scan": 0x48, "extended": True},
    "down": {"vk": 0x28, "scan": 0x50, "extended": True},
    "left": {"vk": 0x25, "scan": 0x4B, "extended": True},
    "right": {"vk": 0x27, "scan": 0x4D, "extended": True},
    "arrowup": {"vk": 0x26, "scan": 0x48, "extended": True},
    "arrowdown": {"vk": 0x28, "scan": 0x50, "extended": True},
    "arrowleft": {"vk": 0x25, "scan": 0x4B, "extended": True},
    "arrowright": {"vk": 0x27, "scan": 0x4D, "extended": True},
    "home": {"vk": 0x24, "scan": 0x47, "extended": True},
    "end": {"vk": 0x23, "scan": 0x4F, "extended": True},
    "pageup": {"vk": 0x21, "scan": 0x49, "extended": True},
    "pagedown": {"vk": 0x22, "scan": 0x51, "extended": True},
    "insert": {"vk": 0x2D, "scan": 0x52, "extended": True},
    "delete": {"vk": 0x2E, "scan": 0x53, "extended": True},
    "win": {"vk": 0x5B, "scan": 0x5B},
    "meta": {"vk": 0x5B, "scan": 0x5B},
    "command": {"vk": 0x5B, "scan": 0x5B},
    "ctrl": {"vk": 0x11, "scan": 0x1D},
    "control": {"vk": 0x11, "scan": 0x1D},
    "alt": {"vk": 0x12, "scan": 0x38},
    "shift": {"vk": 0x10, "scan": 0x2A},
    "apps": {"vk": 0x5D, "scan": 0x5D, "extended": True},
    "menu": {"vk": 0x5D, "scan": 0x5D, "extended": True},
    "capslock": {"vk": 0x14, "scan": 0x3A},
    "printscreen": {"vk": 0x2C, "scan": 0x37, "extended": True},
    "numpadenter": {"vk": 0x0D, "scan": 0x9C, "extended": True},
    "volumemute": {"vk": 0xAD, "scan": 0x00},
    "volumedown": {"vk": 0xAE, "scan": 0x00},
    "volumeup": {"vk": 0xAF, "scan": 0x00},
    "playpause": {"vk": 0xB3, "scan": 0x00},
    "nexttrack": {"vk": 0xB0, "scan": 0x00},
    "prevtrack": {"vk": 0xB1, "scan": 0x00},
    "stop": {"vk": 0xB2, "scan": 0x00},
}
for idx in range(1, 13):
    KEYMAP[f"f{idx}"] = {"vk": 0x70 + idx - 1, "scan": 0x3B + idx - 1}

MODS = {"ctrl": "ctrl", "control": "ctrl", "alt": "alt", "shift": "shift", "win": "win", "meta": "win", "command": "win"}


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", PUL),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", PUL),
    ]


class _INPUTunion(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUTunion)]


def get_system_metrics(index: int) -> int:
    try:
        return ctypes.windll.user32.GetSystemMetrics(index)
    except Exception:
        return 0


def normalize_absolute_xy(x: int | float, y: int | float, left: int = 0, top: int = 0, width: int = 1, height: int = 1):
    """Chuẩn hóa tọa độ tuyệt đối thành 0..65535 cho MOUSEEVENTF_ABSOLUTE."""
    width = max(1, int(width))
    height = max(1, int(height))
    xr = max(0, min(int(x), left + width))
    yr = max(0, min(int(y), top + height))
    nx = int((xr - left) / max(1, width) * 65535.0)
    ny = int((yr - top) / max(1, height) * 65535.0)
    return max(0, min(nx, 65535)), max(0, min(ny, 65535))


def resolve_key(name: str | int):
    """Từ tên JSON hoặc VK -> cấu hình dùng cho SendInput."""
    if isinstance(name, int):
        return {"vk": int(name), "scan": 0, "extended": False}
    key = str(name).strip().lower().replace(" ", "")
    if not key:
        return {"vk": 0, "scan": 0, "extended": False}
    if key in KEYMAP:
        data = dict(KEYMAP[key])
        data.setdefault("extended", False)
        return data
    if len(key) == 1:
        code = ord(key)
        if 0xD800 <= code <= 0xDBFF:
            code = 0xD800
        return {"vk": 0, "scan": code & 0xFFFF, "extended": False}
    return {"vk": 0, "scan": 0, "extended": False}


class InputBackend(ABC):
    @abstractmethod
    def move_absolute(self, x: int, y: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def move_relative(self, dx: int, dy: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def mouse_down(self, button: str = "left") -> None:
        raise NotImplementedError

    @abstractmethod
    def mouse_up(self, button: str = "left") -> None:
        raise NotImplementedError

    @abstractmethod
    def click(self, button: str = "left", clicks: int = 1) -> None:
        raise NotImplementedError

    @abstractmethod
    def wheel(self, amount: int = 0, horizontal: bool = False) -> None:
        raise NotImplementedError

    @abstractmethod
    def key_down(self, key: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def key_up(self, key: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def type_text(self, text: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def release_all(self) -> None:
        raise NotImplementedError


class SafeBackend(InputBackend):
    """Backend an toàn: ghi log thay vì chạm hệ thống."""

    def __init__(self):
        self.events: list[str] = []
        self.lock = threading.Lock()

    def _record(self, event: str) -> None:
        with self.lock:
            self.events.append(event)

    def move_absolute(self, x: int, y: int) -> None:
        self._record(f"move_absolute:{x},{y}")

    def move_relative(self, dx: int, dy: int) -> None:
        self._record(f"move_relative:{dx},{dy}")

    def mouse_down(self, button: str = "left") -> None:
        self._record(f"mouse_down:{button}")

    def mouse_up(self, button: str = "left") -> None:
        self._record(f"mouse_up:{button}")

    def click(self, button: str = "left", clicks: int = 1) -> None:
        self._record(f"click:{button}:{clicks}")

    def wheel(self, amount: int = 0, horizontal: bool = False) -> None:
        self._record(f"wheel:{amount}:{horizontal}")

    def key_down(self, key: str) -> None:
        self._record(f"key_down:{key}")

    def key_up(self, key: str) -> None:
        self._record(f"key_up:{key}")

    def type_text(self, text: str) -> None:
        self._record(f"type_text:{len(text)}")

    def release_all(self) -> None:
        self._record("release_all")


class WindowsSendInputBackend(InputBackend):
    """Backend thực thi bằng ctypes SendInput."""

    def __init__(self, user32=None):
        self.user32 = user32 or ctypes.windll.user32
        self._held_modifiers: set[str] = set()
        self._held_buttons: set[str] = set()

    def _send_keyboard(self, vk: int, scan: int, flags: int) -> None:
        extra = ctypes.c_ulong(0)
        ii = INPUT(
            type=INPUT_KEYBOARD,
            union=_INPUTunion(
                ki=KEYBDINPUT(vk, scan, flags, 0, ctypes.pointer(extra))
            ),
        )
        self.user32.SendInput(1, ctypes.byref(ii), ctypes.sizeof(INPUT))

    def _send_mouse(self, dx: int = 0, dy: int = 0, mouse_data: int = 0, flags: int = 0) -> None:
        extra = ctypes.c_ulong(0)
        ii = INPUT(
            type=INPUT_MOUSE,
            union=_INPUTunion(
                mi=MOUSEINPUT(dx, dy, mouse_data, flags, 0, ctypes.pointer(extra))
            ),
        )
        self.user32.SendInput(1, ctypes.byref(ii), ctypes.sizeof(INPUT))

    def _press_unicode(self, ch: str, is_up: bool) -> None:
        value = ord(ch)
        flags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if is_up else 0)
        self._send_keyboard(0, value, flags)

    def _send_key_event(self, key: str, down: bool) -> None:
        info = resolve_key(key)
        scan = int(info.get("scan", 0) or 0)
        vk = int(info.get("vk", 0) or 0)
        flags = 0
        if scan:
            flags |= KEYEVENTF_SCANCODE
        if info.get("extended"):
            flags |= KEYEVENTF_EXTENDEDKEY
        key_name = str(key).lower()
        if down and key_name in MODS:
            self._held_modifiers.add(key_name)
        elif not down and key_name in MODS:
            self._held_modifiers.discard(key_name)
        if down:
            self._send_keyboard(vk, scan, flags)
        else:
            self._send_keyboard(vk, scan, flags | KEYEVENTF_KEYUP)

    def move_absolute(self, x: int, y: int) -> None:
        left = int(get_system_metrics(-76))
        top = int(get_system_metrics(-77))
        width = max(1, int(get_system_metrics(78)))
        height = max(1, int(get_system_metrics(79)))
        nx, ny = normalize_absolute_xy(x, y, left, top, width, height)
        self._send_mouse(nx, ny, flags=MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK)

    def move_relative(self, dx: int, dy: int) -> None:
        self._send_mouse(int(dx), int(dy), flags=MOUSEEVENTF_MOVE | MOUSEEVENTF_VIRTUALDESK)

    def mouse_down(self, button: str = "left") -> None:
        button_name = str(button).lower()
        mapping = {"left": MOUSEEVENTF_LEFTDOWN, "right": MOUSEEVENTF_RIGHTDOWN, "middle": MOUSEEVENTF_MIDDLEDOWN}
        self._held_buttons.add(button_name)
        self._send_mouse(flags=mapping.get(button_name, MOUSEEVENTF_LEFTDOWN))

    def mouse_up(self, button: str = "left") -> None:
        button_name = str(button).lower()
        mapping = {"left": MOUSEEVENTF_LEFTUP, "right": MOUSEEVENTF_RIGHTUP, "middle": MOUSEEVENTF_MIDDLEUP}
        self._held_buttons.discard(button_name)
        self._send_mouse(flags=mapping.get(button_name, MOUSEEVENTF_LEFTUP))

    def click(self, button: str = "left", clicks: int = 1) -> None:
        for _ in range(max(1, int(clicks))):
            self.mouse_down(button)
            self.mouse_up(button)

    def wheel(self, amount: int = 0, horizontal: bool = False) -> None:
        if amount == 0:
            return
        self._send_mouse(mouse_data=int(amount * WHEEL_DELTA), flags=MOUSEEVENTF_HWHEEL if horizontal else MOUSEEVENTF_WHEEL)

    def key_down(self, key: str) -> None:
        self._send_key_event(str(key), True)

    def key_up(self, key: str) -> None:
        self._send_key_event(str(key), False)

    def type_text(self, text: str) -> None:
        if not text:
            return
        for ch in text:
            if ch == "\n":
                self.key_down("enter")
                self.key_up("enter")
                continue
            if ch == "\t":
                self.key_down("tab")
                self.key_up("tab")
                continue
            if ch == "\r":
                continue
            raw = ch.encode("utf-16-le")
            units = [int.from_bytes(raw[i:i + 2], "little") for i in range(0, len(raw), 2)]
            for unit in units:
                self._send_keyboard(0, unit, KEYEVENTF_UNICODE)
            for unit in units:
                self._send_keyboard(0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)

    def release_all(self) -> None:
        for key in list(self._held_modifiers):
            self.key_up(key)
        for button in list(self._held_buttons):
            self.mouse_up(button)
        self._held_modifiers.clear()
        self._held_buttons.clear()


__all__ = [
    "InputBackend",
    "SafeBackend",
    "WindowsSendInputBackend",
    "KEYMAP",
    "MODS",
    "normalize_absolute_xy",
    "resolve_key",
]
