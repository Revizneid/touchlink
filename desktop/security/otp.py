"""TOTP helper implementing RFC 6238 with simple recovery-code support."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from typing import List


class TOTPSecret:
    def __init__(self, secret: str, issuer: str = "TouchLink"):
        self.secret = str(secret).strip().upper()
        self.issuer = issuer

    @classmethod
    def generate(cls, issuer: str = "TouchLink") -> "TOTPSecret":
        secret = base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")
        return cls(secret=secret, issuer=issuer)

    def provisioning_uri(self, account_name: str) -> str:
        label = f"{self.issuer}:{account_name}".replace(" ", "%20")
        return f"otpauth://totp/{label}?secret={self.secret}&issuer={self.issuer}"


def _decode_secret(secret: str) -> bytes:
    padded = str(secret).strip().upper()
    if len(padded) % 8:
        padded += "=" * (8 - (len(padded) % 8))
    return base64.b32decode(padded, casefold=True)


def generate_totp(secret: str, *, time_value: float | None = None, digits: int = 6, period: int = 30) -> str:
    """Generate a 6-digit TOTP code compatible with RFC 6238."""
    epoch = float(time_value if time_value is not None else time.time())
    counter = int(epoch // period)
    key = _decode_secret(secret)
    msg = counter.to_bytes(8, byteorder="big")
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = ((digest[offset] & 0x7F) << 24) | ((digest[offset + 1] & 0xFF) << 16) | (
        (digest[offset + 2] & 0xFF) << 8
    ) | (digest[offset + 3] & 0xFF)
    code = binary % (10 ** digits)
    return str(code).zfill(digits)


def validate_totp(secret: str, code: str, *, time_value: float | None = None, window: int = 1, digits: int = 6, period: int = 30) -> bool:
    if code is None:
        return False
    try:
        target = str(code).strip().zfill(digits)
        if len(target) != digits or not target.isdigit():
            return False
    except Exception:
        return False

    epoch = float(time_value if time_value is not None else time.time())
    counter = int(epoch // period)
    for offset in range(-window, window + 1):
        candidate = generate_totp(secret, time_value=(counter + offset) * period + (period // 2), digits=digits, period=period)
        if candidate == target:
            return True
    return False


def generate_recovery_codes(seed: str, count: int = 10) -> List[str]:
    """Generate a list of single-use recovery codes from a stable seed."""
    values: List[str] = []
    for i in range(count):
        token = hashlib.sha256(f"{seed}:{i}:{secrets.token_hex(8)}".encode("utf-8")).hexdigest()[:8].upper()
        values.append(token)
    return values


__all__ = [
    "TOTPSecret",
    "generate_recovery_codes",
    "generate_totp",
    "validate_totp",
]
