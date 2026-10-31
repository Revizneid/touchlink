"""Pairing primitives for TouchLink 2.1.

This module provides a deterministic, testable Ed25519-based pairing flow:
- device key generation
- pairing secret issuance with expiry
- SAS derivation from the two public keys + nonce
- challenge/response signature verification
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def _coerce_public_key_bytes(public_key: Any) -> bytes:
    if isinstance(public_key, (bytes, bytearray)):
        data = bytes(public_key)
        if len(data) != 32:
            raise ValueError("Ed25519 public key must be 32 bytes")
        return data
    if hasattr(public_key, "public_bytes"):
        return public_key.public_bytes_raw()
    raise TypeError("Unsupported public key object")


@dataclass
class DeviceKeyPair:
    private_key: Ed25519PrivateKey
    public_key: Ed25519PublicKey

    @property
    def public_bytes(self) -> bytes:
        return self.public_key.public_bytes_raw()

    @property
    def public_key_b64(self) -> str:
        return base64.b64encode(self.public_bytes).decode("ascii")

    def sign(self, data: bytes) -> bytes:
        return self.private_key.sign(data)


def generate_device_keypair() -> DeviceKeyPair:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    return DeviceKeyPair(private_key=private_key, public_key=public_key)


def compute_sas(public_a: Any, public_b: Any, nonce: str) -> str:
    """Compute a 6-digit SAS from the two public keys and nonce.

    Return shape is a 6-digit numeric string, e.g. '123456'. The UI can format it
    as '123-456' for presentation.
    """
    a = _coerce_public_key_bytes(public_a)
    b = _coerce_public_key_bytes(public_b)
    if a > b:
        a, b = b, a
    digest = hashlib.sha256()
    digest.update(a)
    digest.update(b)
    digest.update((nonce or "").encode("utf-8"))
    value = int.from_bytes(digest.digest()[:4], byteorder="big", signed=False)
    return f"{value % 1000000:06d}"


def verify_challenge_response(public_key: Any, nonce: str, signature: bytes) -> bool:
    try:
        p = public_key
        if isinstance(p, (bytes, bytearray)):
            p = Ed25519PublicKey.from_public_bytes(bytes(p))
        elif hasattr(p, "public_bytes"):
            p = Ed25519PublicKey.from_public_bytes(p.public_bytes_raw())
        p.verify(signature, (nonce or "").encode("utf-8"))
        return True
    except (TypeError, ValueError, InvalidSignature):
        return False


class PairingSession:
    """Temporary device pairing session with one-time pairing_secret."""

    def __init__(self, device_id: str, device_name: str, relay_url: str = ""):
        self.device_id = str(device_id)
        self.device_name = str(device_name)
        self.relay_url = relay_url or ""
        self._secrets: dict[str, dict[str, Any]] = {}
        self._failures: dict[str, int] = {}

    def issue_secret(self, ttl_seconds: int = 120) -> str:
        secret = secrets.token_hex(16)
        expires_at = time.time() + max(1, int(ttl_seconds))
        self._secrets[secret] = {
            "device_id": self.device_id,
            "expires_at": expires_at,
            "used": False,
            "issued_at": time.time(),
        }
        self._failures.setdefault(secret, 0)
        return secret

    def verify_secret(self, secret: str, device_id: str) -> bool:
        if not secret:
            return False
        rec = self._secrets.get(secret)
        if rec is None:
            return False
        if rec.get("device_id") != str(device_id):
            self._failures[secret] = int(self._failures.get(secret, 0)) + 1
            self._prune_failures(secret)
            return False
        if time.time() > float(rec.get("expires_at", 0)):
            self._secrets.pop(secret, None)
            self._failures.pop(secret, None)
            return False
        if bool(rec.get("used")):
            self._secrets.pop(secret, None)
            return False
        rec["used"] = True
        self._secrets[secret] = rec
        return True

    def _prune_failures(self, secret: str):
        count = int(self._failures.get(secret, 0))
        if count >= 3:
            self._secrets.pop(secret, None)
            self._failures.pop(secret, None)

    def make_proof(self, secret: str, nonce: str) -> bytes:
        if not secret:
            raise ValueError("secret is required")
        return hmac.new(secret.encode("utf-8"), nonce.encode("utf-8"), hashlib.sha256).digest()

    def verify_proof(self, secret: str, nonce: str, proof: bytes) -> bool:
        return hmac.compare_digest(self.make_proof(secret, nonce), proof)
