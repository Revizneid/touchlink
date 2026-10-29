"""Compatibility layer for Windows input injection.

This module preserves the legacy TouchLink API while delegating to the new
ctypes-based backend in the input package.
"""
from __future__ import annotations

from input.sendinput import (
    InputBackend,
    KEYMAP,
    MODS,
    SafeBackend,
    WindowsSendInputBackend,
    normalize_absolute_xy,
    resolve_key,
)

SAFE_TEST = False
stats = {"injected": 0, "skipped": 0}
_backend = None


def _mark():
    key = "skipped" if SAFE_TEST else "injected"
    stats[key] += 1


def _get_backend() -> InputBackend:
    global _backend
    if _backend is None:
        _backend = SafeBackend() if SAFE_TEST else WindowsSendInputBackend()
    return _backend


def type_text(text: str):
    """Gõ chuỗi Unicode, bao gồm tiếng Việt và surrogate pair."""
    _mark()
    if SAFE_TEST or not text:
        return
    _get_backend().type_text(text)


def tap_key(key: str, mods=()):
    """Nhấn phím đơn lẻ hoặc kèm modifier."""
    _mark()
    if SAFE_TEST:
        return
    backend = _get_backend()
    names = [str(m).lower() for m in (mods or ()) if str(m).lower() in MODS]
    target = str(key).lower()
    if target not in KEYMAP and len(target) != 1:
        return
    for mod in names:
        backend.key_down(mod)
    try:
        backend.key_down(target if target in KEYMAP else target)
        backend.key_up(target if target in KEYMAP else target)
    finally:
        for mod in reversed(names):
            backend.key_up(mod)


def mouse(action: str, x=None, y=None, button="left", clicks=1, amount=0, horizontal=False):
    """action: move|moverel|down|up|click|scroll."""
    _mark()
    if SAFE_TEST:
        return
    backend = _get_backend()
    if action == "move":
        if x is not None and y is not None:
            backend.move_absolute(int(x), int(y))
    elif action == "moverel":
        backend.move_relative(int(x or 0), int(y or 0))
    elif action == "down":
        backend.mouse_down(str(button))
    elif action == "up":
        backend.mouse_up(str(button))
    elif action == "click":
        backend.click(str(button), max(1, int(clicks or 1)))
    elif action == "scroll":
        backend.wheel(int(amount or 0), bool(horizontal))


def release_all():
    """Nhả phím/nút chuột đang giữ để tránh kẹt input."""
    if SAFE_TEST:
        return
    try:
        _get_backend().release_all()
    except Exception:
        pass
