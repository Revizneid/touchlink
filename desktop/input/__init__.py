"""Input backend package for Windows input injection."""

from .sendinput import (
    KEYMAP,
    MODS,
    InputBackend,
    SafeBackend,
    WindowsSendInputBackend,
    normalize_absolute_xy,
    resolve_key,
)

__all__ = [
    "KEYMAP",
    "MODS",
    "InputBackend",
    "SafeBackend",
    "WindowsSendInputBackend",
    "normalize_absolute_xy",
    "resolve_key",
]
