"""Connection policy evaluation for Sprint 2.3."""

from __future__ import annotations

from typing import Any, Dict


def evaluate_connection_policy(
    *,
    trusted_device: bool,
    source: str,
    is_relay: bool,
    active_user: bool,
    device_name: str | None = None,
    permission: str | None = None,
) -> Dict[str, Any]:
    """Decide whether a connection should be allowed, denied, or require consent.

    The policy is intentionally conservative and compatible with the Sprint 2.3 plan:
    - trusted LAN devices are allowed without additional prompts
    - unknown or relay-originated callers require a consent decision
    - when no user is present, the connection is rejected
    """
    normalized_source = str(source or "relay").strip().lower()
    if normalized_source not in {"lan", "relay"}:
        normalized_source = "relay" if bool(is_relay) else "lan"

    if not active_user:
        return {
            "decision": "deny",
            "requires_consent": False,
            "reason": "No active user is present; refusing connection.",
            "source": normalized_source,
            "trusted_device": bool(trusted_device),
            "device_name": device_name,
            "permission": permission,
        }

    if trusted_device and normalized_source == "lan":
        return {
            "decision": "allow",
            "requires_consent": False,
            "reason": "Trusted LAN device",
            "source": normalized_source,
            "trusted_device": True,
            "device_name": device_name,
            "permission": permission or "control",
        }

    if trusted_device and normalized_source == "relay":
        return {
            "decision": "allow",
            "requires_consent": False,
            "reason": "Trusted relay device already paired",
            "source": normalized_source,
            "trusted_device": True,
            "device_name": device_name,
            "permission": permission or "control",
        }

    if not trusted_device:
        return {
            "decision": "require_consent",
            "requires_consent": True,
            "reason": "Unknown device from relay or untrusted source; explicit consent required.",
            "source": normalized_source,
            "trusted_device": False,
            "device_name": device_name,
            "permission": permission or "view_only",
        }

    return {
        "decision": "allow",
        "requires_consent": False,
        "reason": "Policy default allow",
        "source": normalized_source,
        "trusted_device": bool(trusted_device),
        "device_name": device_name,
        "permission": permission or "control",
    }


__all__ = ["evaluate_connection_policy"]
