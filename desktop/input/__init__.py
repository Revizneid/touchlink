"""Input backend package for Windows input injection."""

from .sendinput import (
    InputBackend,
    SafeBackend,
    WindowsSendInputBackend,
    KEYMAP,
    MODS,
    normalize_absolute_xy,
    resolve_key,
)

__all__ = [
    "InputBackend",
    "SafeBackend",
    "WindowsSendInputBackend",
    "KEYMAP",
    "MODS",
    "normalize_absolute_xy",
    "resolve_key",
]
