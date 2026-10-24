"""Điều khiển chuột/bàn phím Windows.

- Chuột + phím thường: pyautogui (ctypes SendInput bên dưới).
- Gõ văn bản Unicode (tiếng Việt): SendInput KEYEVENTF_UNICODE.
- Cuộn dọc/ngang: SendInput mouse wheel.
"""
import ctypes
import time
from ctypes import wintypes

import pyautogui

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.0

SAFE_TEST = False  # True = chỉ đếm, KHÔNG đụng vào máy thật (dùng để kiểm thử)

stats = {"injected": 0, "skipped": 0}

KEYMAP = {
    "enter": "enter", "backspace": "backspace", "delete": "delete", "tab": "tab",
    "escape": "esc", "esc": "esc",
    "arrowup": "up", "arrowdown": "down", "arrowleft": "left", "arrowright": "right",
    "up": "up", "down": "down", "left": "left", "right": "right",
    "home": "home", "end": "end", "pageup": "pageup", "pagedown": "pagedown",
    "insert": "insert", "win": "win", "meta": "win", "command": "win",
    "ctrl": "ctrl", "control": "ctrl", "alt": "alt", "shift": "shift",
    "space": "space", "capslock": "capslock", "printscreen": "printscreen",
    "apps": "apps", "menu": "apps",
    "volumeup": "volumeup", "volumedown": "volumedown", "volumemute": "volumemute",
    "playpause": "playpause", "play": "playpause", "nexttrack": "nexttrack",
    "prevtrack": "prevtrack", "stop": "stop",
}
for _i in range(1, 13):
    KEYMAP["f%d" % _i] = "f%d" % _i

MODS = {"ctrl": "ctrl", "control": "ctrl", "alt": "alt", "shift": "shift", "win": "win", "meta": "win"}

# --- SendInput structures ---
PUL = ctypes.POINTER(ctypes.c_ulong)


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", PUL)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", PUL)]


class _INPUTunion(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUTunion)]


INPUT_KEYBOARD = 1
INPUT_MOUSE = 0
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_KEYUP = 0x0002
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
WHEEL_DELTA = 120


def _mark():
    stats["injected" if not SAFE_TEST else "skipped"] += 1


def _send_unicode_unit(unit: int, up: bool):
    flags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0)
    extra = ctypes.c_ulong(0)
    ii = INPUT(type=INPUT_KEYBOARD,
               union=_INPUTunion(ki=KEYBDINPUT(0, unit, flags, 0, ctypes.pointer(extra))))
    ctypes.windll.user32.SendInput(1, ctypes.byref(ii), ctypes.sizeof(INPUT))


def type_text(text: str):
    """Gõ chuỗi Unicode (hỗ trợ tiếng Việt) qua SendInput."""
    _mark()
    if SAFE_TEST or not text:
        return
    for ch in text:
        if ch == "\n":
            pyautogui.press("enter")
            continue
        if ch == "\t":
            pyautogui.press("tab")
            continue
        if ch == "\r":
            continue
        try:
            units = ch.encode("utf-16-le")
            downs = [int.from_bytes(units[i:i + 2], "little") for i in range(0, len(units), 2)]
            for u in downs:
                _send_unicode_unit(u, False)
            for u in downs:
                _send_unicode_unit(u, True)
            time.sleep(0.002)
        except Exception:
            pass


def tap_key(key: str, mods=()):
    """Nhấn 1 phím kèm tổ hợp phím điều chỉnh."""
    _mark()
    if SAFE_TEST:
        return
    keys = [MODS[m] for m in mods if m in MODS]
    mapped = KEYMAP.get(str(key).lower())
    if mapped is None:
        if len(str(key)) == 1:
            mapped = str(key).lower()
        else:
            return
    try:
        for m in keys:
            pyautogui.keyDown(m)
        pyautogui.press(mapped)
    finally:
        for m in reversed(keys):
            try:
                pyautogui.keyUp(m)
            except Exception:
                pass


def _wheel(amount: int, horizontal: bool):
    flags = MOUSEEVENTF_HWHEEL if horizontal else MOUSEEVENTF_WHEEL
    extra = ctypes.c_ulong(0)
    data = wintypes.DWORD(int(amount) * WHEEL_DELTA & 0xFFFFFFFF)
    ii = INPUT(type=INPUT_MOUSE,
               union=_INPUTunion(mi=MOUSEINPUT(0, 0, data.value, flags, 0, ctypes.pointer(extra))))
    ctypes.windll.user32.SendInput(1, ctypes.byref(ii), ctypes.sizeof(INPUT))


def mouse(action: str, x=None, y=None, button="left", clicks=1, amount=0, horizontal=False):
    """action: move|down|up|click|scroll. x,y là tọa độ pixels thật của màn hình."""
    _mark()
    if SAFE_TEST:
        return
    try:
        if action == "move":
            if x is not None and y is not None:
                pyautogui.moveTo(x, y)
        elif action == "moverel":
            pyautogui.moveRel(int(x or 0), int(y or 0))
        elif action == "down":
            if x is not None and y is not None:
                pyautogui.mouseDown(x, y, button=button)
            else:
                pyautogui.mouseDown(button=button)
        elif action == "up":
            if x is not None and y is not None:
                pyautogui.mouseUp(x, y, button=button)
            else:
                pyautogui.mouseUp(button=button)
        elif action == "click":
            kw = {"button": button, "clicks": max(1, int(clicks or 1))}
            if kw["clicks"] > 1:
                kw["interval"] = 0.06
            if x is not None and y is not None:
                pyautogui.click(x, y, **kw)
            else:
                pyautogui.click(**kw)
        elif action == "scroll":
            if horizontal:
                _wheel(amount, True)
            else:
                _wheel(amount, False)
    except Exception:
        pass
