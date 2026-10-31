"""RTC signaling helpers for Sprint 3.2.

This layer is intentionally small and testable: it provides the message types,
SDP verification, and TURN credential generation required by the project plan.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass, field
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

RTC_SIGNAL_TYPES = {"rtc_offer", "rtc_answer", "rtc_ice", "rtc_bye"}
MAX_SIGNAL_BYTES = 1024 * 1024


@dataclass
class RTCSignalMessage:
    type: str
    device_id: str
    sdp: str | None = None
    candidate: str | None = None
    signature: str | None = None
    signer: str | None = None
    version: str = "rtc-v1"
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "type": self.type,
            "device_id": self.device_id,
            "version": self.version,
        }
        if self.sdp is not None:
            payload["sdp"] = self.sdp
        if self.candidate is not None:
            payload["candidate"] = self.candidate
        if self.signature is not None:
            payload["signature"] = self.signature
        if self.signer is not None:
            payload["signer"] = self.signer
        payload.update(self.extra)
        return payload


def sign_sdp(sdp: str, private_key: Ed25519PrivateKey) -> bytes:
    if not isinstance(sdp, str) or not sdp:
        raise ValueError("SDP must be a non-empty string")
    return private_key.sign(sdp.encode("utf-8"))


def verify_signed_sdp(sdp: str, signature: bytes | str, public_key: Ed25519PublicKey) -> bool:
    try:
        if isinstance(signature, str):
            signature = bytes.fromhex(signature)
        public_key.verify(signature, (sdp or "").encode("utf-8"))
        return True
    except (TypeError, ValueError, InvalidSignature):
        return False


def validate_webrtc_signal(message: Any) -> bool:
    if not isinstance(message, RTCSignalMessage):
        return False
    if message.type not in RTC_SIGNAL_TYPES:
        return False
    if len(str(message.device_id or "")) == 0:
        return False
    payload = message.to_dict()
    try:
        payload_bytes = str(payload).encode("utf-8")
    except Exception:
        return False
    if len(payload_bytes) > MAX_SIGNAL_BYTES:
        return False
    if message.type in {"rtc_offer", "rtc_answer"}:
        if not message.sdp:
            return False
        if not message.signature:
            return False
        if not message.signer:
            return False
        try:
            parsed_sig = bytes.fromhex(str(message.signature))
        except ValueError:
            return False
        if len(parsed_sig) != 64:
            return False
    return True


def create_turn_credential(secret: str, *, device_id: str, ttl_s: int = 300, now: float | None = None) -> dict[str, Any]:
    timestamp = int(now if now is not None else time.time())
    ttl = max(1, int(ttl_s))
    username = f"{timestamp}:{ttl}:{device_id}"
    credential = hmac.new(str(secret).encode("utf-8"), username.encode("utf-8"), hashlib.sha256).hexdigest()
    expires_at = timestamp + ttl
    return {
        "username": username,
        "credential": credential,
        "device_id": str(device_id),
        "expires_at": expires_at,
        "ttl_s": ttl,
    }


def verify_turn_credential(secret: str, username: str, credential: str, *, device_id: str, now: float | None = None) -> bool:
    if not username or not credential:
        return False
    try:
        ts_text, ttl_text, actual_device_id = username.split(":", 2)
        ts = int(ts_text)
        ttl = int(ttl_text)
    except ValueError:
        return False
    if actual_device_id != str(device_id):
        return False
    current = float(now if now is not None else time.time())
    if current > ts + ttl:
        return False
    expected = hmac.new(str(secret).encode("utf-8"), username.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, str(credential))


__all__ = [
    "MAX_SIGNAL_BYTES",
    "RTC_SIGNAL_TYPES",
    "RTCSignalMessage",
    "create_turn_credential",
    "sign_sdp",
    "validate_webrtc_signal",
    "verify_signed_sdp",
    "verify_turn_credential",
]
