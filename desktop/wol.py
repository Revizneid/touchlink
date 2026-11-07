"""Wake-on-LAN helpers for Sprint 4.4.

These helpers keep the request validation and magic-packet generation explicit and
fail-closed. We do not open arbitrary sockets here; instead we provide the data model so
real LAN helper code can mount onto it later.
"""

from __future__ import annotations

import re
import socket
from typing import Any

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


def validate_wake_request(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    mac = str(payload.get("target_mac") or "")
    device_id = str(payload.get("device_id") or "")
    permission = str(payload.get("permission") or "")
    if not mac or not device_id or not permission:
        return False
    if not is_valid_mac_address(mac):
        return False
    return permission.lower() == "wake"


def build_wake_request(target_mac: str, device_id: str, *, permission: str = "wake") -> dict[str, Any]:
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


def get_local_mac_address() -> str:
    """Lấy địa chỉ MAC card mạng chính (dạng XX:XX:XX:XX:XX:XX) để hiển thị và chia sẻ với Relay cho tính năng WoL."""
    import uuid
    mac_num = uuid.getnode()
    mac_hex = f"{mac_num:012x}"
    return ":".join(mac_hex[i:i+2] for i in range(0, 12, 2)).upper()


def send_magic_packet(
    mac_address: str,
    broadcast_ip: str = "255.255.255.255",
    port: int = 9,
) -> bool:
    """Gửi UDP magic packet đến địa chỉ broadcast để đánh thức máy qua WoL."""
    try:
        packet = build_magic_packet(mac_address)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(packet, (str(broadcast_ip), int(port)))
        return True
    except Exception:
        return False


__all__ = [
    "build_magic_packet",
    "build_wake_request",
    "get_local_mac_address",
    "is_valid_mac_address",
    "send_magic_packet",
    "validate_wake_request",
]
