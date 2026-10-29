"""Compatibility policy helpers for Sprint 3.4.

This module captures the browser and viewport constraints that affect iOS Safari and
Android Chrome when the web client is used as a PWA.
"""

from __future__ import annotations

from typing import Dict


def detect_browser_family(user_agent: str | None) -> str:
    """Return a coarse browser family: desktop, ios, android, mobile, unknown."""
    ua = (user_agent or "").lower()
    if "iphone" in ua or "ipad" in ua or "ipod" in ua:
        return "ios"
    if "android" in ua:
        return "android"
    if "mobile" in ua:
        return "mobile"
    if any(token in ua for token in ("windows", "macintosh", "linux", "x11")):
        return "desktop"
    return "desktop"


def build_mobile_viewport_policy(user_agent: str | None) -> Dict[str, object]:
    """Return a normalized compatibility profile for browser runtime behavior."""
    family = detect_browser_family(user_agent)
    if family == "ios":
        return {
            "family": "ios",
            "playsinline": True,
            "uses_visual_viewport": True,
            "hide_address_bar": True,
            "keyboard_adjustment": "visualViewport",
            "supports_wake_lock": False,
            "requires_fullscreen_hints": True,
        }
    if family == "android":
        return {
            "family": "android",
            "playsinline": True,
            "uses_visual_viewport": True,
            "hide_address_bar": False,
            "keyboard_adjustment": "viewport",
            "supports_wake_lock": True,
            "requires_fullscreen_hints": False,
        }
    return {
        "family": "desktop",
        "playsinline": False,
        "uses_visual_viewport": False,
        "hide_address_bar": False,
        "keyboard_adjustment": "none",
        "supports_wake_lock": False,
        "requires_fullscreen_hints": False,
    }


__all__ = ["build_mobile_viewport_policy", "detect_browser_family"]
