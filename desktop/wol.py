"""Wake-on-LAN helpers for Sprint 4.4.

These helpers keep the request validation and magic-packet generation explicit and
fail-closed. We do not open arbitrary sockets here; instead we provide the data model so
real LAN helper code can mount onto it later.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List


_MAC_RE = re.compile(r"^(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")


def is_valid_mac_address(value: str) -> bool:
    return bool(value and _MAC_RE.fullmatch(str(value).strip()))


def build_magic_packet(mac_address: str) -> bytes:
    value = str(mac_address or "").strip()
    if not is_valid_mac_address(value):
        raise ValueError("invalid MAC address")
    bytes_mac = bytes.fromhex(value.replace(":", ""))
    packet = b"\xff\xff\xff\xff\xff\xff" + (bytes_mac * 16)
    if len(packet) != 6 + (len(bytes_mac) * 16):
        raise ValueError("magic packet length mismatch")
    return packet


def validate_wake_request(payload: Dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    mac = str(payload.get("target_mac") or "")
    device_id = str(payload.get("device_id") or "")
    permission = str(payload.get("permission") or "")
    if not mac or not device_id or not permission:
        return False
    if not is_valid_mac_address(mac):
        return False
    if permission.lower() != "wake":
        return False
    return True


def build_wake_request(target_mac: str, device_id: str, *, permission: str = "wake") -> Dict[str, Any]:
    if not validate_wake_request({
        "target_mac": target_mac,
        "device_id": device_id,
        "permission": permission,
    }):
        raise ValueError("invalid wake request")
    return {
        "type": "wake_request",
        "target_mac": str(target_mac).strip(),
        "device_id": str(device_id),
        "permission": "wake",
    }


__all__ = ["build_magic_packet", "build_wake_request", "is_valid_mac_address", "validate_wake_request"]
