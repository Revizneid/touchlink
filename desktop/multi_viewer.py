"""Multi-viewer and macro policy helpers for Sprint 4.3.

This module keeps the controller/viewer authorization model explicit and fail-closed:
- only the active controller may issue input
- multi-viewer access is capped by max_viewers
- macros are limited to safe, non-destructive input sequences
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional


DEFAULT_MACRO_ALLOWLIST = {"type", "key", "combo"}
DEFAULT_PROHIBITED = {"ctrl+alt+delete", "alt+tab", "win+l", "win+d", "win+r"}
MAX_MACRO_LENGTH = 512


@dataclass
class MacroPolicy:
    max_length: int = MAX_MACRO_LENGTH
    allowlist: set[str] = field(default_factory=lambda: DEFAULT_MACRO_ALLOWLIST.copy())
    prohibited: set[str] = field(default_factory=lambda: DEFAULT_PROHIBITED.copy())
    allow_open_app: bool = False
    max_rate_per_minute: int = 10

    def allows(self, action: str) -> bool:
        if not action or len(action) > self.max_length:
            return False
        normalized = action.strip().lower()
        if normalized in self.prohibited:
            return False
        if normalized.startswith("open:") and not self.allow_open_app:
            return False
        if normalized.startswith("type:"):
            return True
        if normalized.startswith("key:"):
            return True
        if normalized.startswith("combo:"):
            return True
        return False


def default_macro_policy() -> MacroPolicy:
    return MacroPolicy()


def evaluate_macro(policy: MacroPolicy | None, action: str) -> bool:
    if policy is None:
        policy = default_macro_policy()
    return bool(policy.allows(action))


def resolve_controller(viewers: Iterable[Dict[str, Any]]) -> Optional[str]:
    ordered = list(viewers or [])
    if not ordered:
        return None
    preferred = next((v.get("id") for v in ordered if str(v.get("role") or "").lower() == "controller"), None)
    if preferred is not None:
        return str(preferred)
    return str(ordered[0].get("id"))


class MultiViewerSession:
    """Very small session manager for controller + viewer topology."""

    def __init__(self, *, max_viewers: int = 4, controller: Optional[str] = None):
        self.max_viewers = max(1, int(max_viewers))
        self.controller = controller
        self.viewers: List[Dict[str, Any]] = []

    def register_viewer(self, viewer_id: str, *, role: str = "viewer") -> bool:
        if self.can_register(viewer_id):
            self.viewers.append({"id": str(viewer_id), "role": str(role).lower()})
            if self.controller is None and role.lower() == "controller":
                self.controller = str(viewer_id)
            return True
        return False

    def can_register(self, viewer_id: str) -> bool:
        if not viewer_id:
            return False
        if len(self.viewers) >= self.max_viewers:
            return False
        if any(str(v.get("id")) == str(viewer_id) for v in self.viewers):
            return False
        return True

    def set_controller(self, viewer_id: str) -> bool:
        if not viewer_id or not any(str(v.get("id")) == str(viewer_id) for v in self.viewers):
            return False
        self.controller = str(viewer_id)
        for v in self.viewers:
            v["role"] = "viewer"
        for v in self.viewers:
            if str(v.get("id")) == str(viewer_id):
                v["role"] = "controller"
                break
        return True

    def can_send_input(self, viewer_id: str) -> bool:
        if not self.controller:
            return True
        return str(viewer_id) == str(self.controller)


__all__ = [
    "MacroPolicy",
    "MultiViewerSession",
    "default_macro_policy",
    "evaluate_macro",
    "resolve_controller",
]
