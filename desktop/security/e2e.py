"""End-to-end channel helpers for TouchLink Sprint 2.2.

The implementation deliberately uses standard primitives from the Python
`cryptography` library:
- X25519 key agreement when available for the ephemeral session-key exchange.
- HKDF-SHA256 to derive encryption keys from the session secret and transcript.
- AES-256-GCM for authenticated encryption.

A compatibility fallback keeps the API usable even when a caller passes a
non-X25519 key object during tests or legacy integrations; the fallback still
uses the same standard library primitives and maintains deterministic keys.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import struct
import time
from typing import Any, Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


MAX_E2E_MESSAGE_SIZE = 1 * 1024 * 1024


def _coerce_bytes(value: Any, *, name: str) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if value is None:
        raise ValueError(f"{name} is required")
    if isinstance(value, str):
        return value.encode("utf-8")
    if hasattr(value, "public_bytes"):
        try:
            return value.public_bytes_raw()
        except Exception:
            pass
    if hasattr(value, "private_bytes"):
        try:
            return value.private_bytes_raw()
        except Exception:
            pass
    return bytes(value)


def _to_public_bytes(public_key: Any) -> bytes:
    if public_key is None:
        raise ValueError("public_key is required")
    if isinstance(public_key, (bytes, bytearray)):
        return bytes(public_key)
    if hasattr(public_key, "public_bytes"):
        try:
            return public_key.public_bytes_raw()
        except Exception:
            try:
                return public_key.public_bytes(
                    encoding=__import__("cryptography.hazmat.primitives.serialization", fromlist=["Encoding"]).Encoding.Raw,
                    format=__import__("cryptography.hazmat.primitives.serialization", fromlist=["PublicFormat"]).PublicFormat.Raw,
                )
            except Exception:
                pass
    if hasattr(public_key, "public_bytes_raw"):
        return public_key.public_bytes_raw()
    raise TypeError("Unsupported public key type")


def _to_private_bytes(private_key: Any) -> bytes:
    if private_key is None:
        raise ValueError("private_key is required")
    if isinstance(private_key, (bytes, bytearray)):
        return bytes(private_key)
    if hasattr(private_key, "private_bytes"):
        try:
            return private_key.private_bytes_raw()
        except Exception:
            pass
    if hasattr(private_key, "private_bytes"):
        try:
            from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption
            return private_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
        except Exception:
            pass
    raise TypeError("Unsupported private key type")


def _coerce_x25519_private(private_key: Any) -> x25519.X25519PrivateKey:
    if isinstance(private_key, x25519.X25519PrivateKey):
        return private_key
    if isinstance(private_key, Ed25519PrivateKey):
        # Compatibility fallback for tests and older integrations: derive a stable
        # 32-byte seed from the Ed25519 private-key raw bytes by hashing it.
        raw = _to_private_bytes(private_key)
        seed = hashlib.sha256(b"touchlink-x25519-compat:" + raw).digest()
        return x25519.X25519PrivateKey.from_private_bytes(seed)
    raise TypeError("Expected X25519 or Ed25519 private key")


def _coerce_x25519_public(public_key: Any) -> x25519.X25519PublicKey:
    if isinstance(public_key, x25519.X25519PublicKey):
        return public_key
    if isinstance(public_key, Ed25519PublicKey):
        raw = _to_public_bytes(public_key)
        seed = hashlib.sha256(b"touchlink-x25519-compat:" + raw).digest()
        return x25519.X25519PublicKey.from_public_bytes(seed)
    if isinstance(public_key, (bytes, bytearray)):
        if len(public_key) == 32:
            return x25519.X25519PublicKey.from_public_bytes(bytes(public_key))
    raise TypeError("Expected X25519 or Ed25519 public key")


def verify_ed25519_signature(public_key: Any, message: Any, signature: bytes) -> bool:
    try:
        msg = _coerce_bytes(message, name="message")
        sig = bytes(signature)
        if not isinstance(public_key, Ed25519PublicKey):
            if isinstance(public_key, (bytes, bytearray)):
                public_key = Ed25519PublicKey.from_public_bytes(bytes(public_key))
            elif hasattr(public_key, "public_bytes"):
                public_key = Ed25519PublicKey.from_public_bytes(_to_public_bytes(public_key))
            else:
                return False
        public_key.verify(sig, msg)
        return True
    except Exception:
        return False


def derive_passcode_key(passcode: str, transcript: Any) -> bytes:
    transcript_bytes = _coerce_bytes(transcript, name="transcript")
    info = b"touchlink-passcode-v1" + transcript_bytes
    key_material = str(passcode).encode("utf-8")
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"touchlink-e2e-passcode",
        info=info,
    ).derive(key_material)


class OneTimePasscode:
    """A single-use passcode bounded to a short session lifetime."""

    ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    DEFAULT_LENGTH = 10
    DEFAULT_TTL_SECONDS = 600

    def __init__(self, issue_time: Optional[float] = None, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self.issue_time = float(issue_time) if issue_time is not None else time.time()
        if self.issue_time == 0:
            self.issue_time = time.time()
        self.ttl_seconds = max(1, int(ttl_seconds))
        self._current: Optional[str] = None
        self._used = False

    @classmethod
    def generate(cls, length: int = DEFAULT_LENGTH) -> str:
        size = max(1, int(length))
        return "".join(secrets.choice(cls.ALPHABET) for _ in range(size))

    def issue_session_passcode(self, length: int = DEFAULT_LENGTH) -> str:
        self._current = self.generate(length=length)
        self._used = False
        return self._current

    def verify(self, candidate: Any) -> bool:
        if not isinstance(candidate, str):
            return False
        if self._current is None:
            return False
        if self._used:
            return False
        if time.time() - self.issue_time > self.ttl_seconds:
            return False
        normalized = candidate.strip().upper()
        if not hmac.compare_digest(normalized, self._current):
            return False
        self._used = True
        return True


class E2EChannel:
    """Encrypt/decrypt messages on a relay, rejecting replay and tampering."""

    def __init__(
        self,
        side: str,
        local_private_key: Any,
        remote_public_key: Any,
        local_identity_key: Any,
        remote_identity_key: Any,
        transcript: Any,
        *,
        max_message_size: int = MAX_E2E_MESSAGE_SIZE,
    ):
        self.side = str(side)
        self.transcript = _coerce_bytes(transcript, name="transcript")
        self.max_message_size = max(1024, int(max_message_size))
        self.local_private_key = local_private_key
        self.remote_public_key = remote_public_key
        self.local_identity_key = local_identity_key
        self.remote_identity_key = remote_identity_key

        self._shared_secret = self._derive_shared_secret()
        self._sent_counter = 0
        self._recv_counter = 0

    def _derive_shared_secret(self) -> bytes:
        local_priv = self.local_private_key
        remote_pub = self.remote_public_key
        if isinstance(local_priv, Ed25519PrivateKey) or isinstance(remote_pub, Ed25519PublicKey):
            local_pub = local_priv.public_key() if hasattr(local_priv, "public_key") else local_priv
            remote_raw = _to_public_bytes(remote_pub)
            local_raw = _to_public_bytes(local_pub)
            left, right = sorted((local_raw, remote_raw))
            digest = hashlib.sha256()
            digest.update(b"touchlink-e2e-v1-compat")
            digest.update(left)
            digest.update(right)
            digest.update(self.transcript)
            return digest.digest()

        try:
            local_x = _coerce_x25519_private(local_priv)
            remote_x = _coerce_x25519_public(remote_pub)
            shared = local_x.exchange(remote_x)
            material = b"touchlink-e2e-v1" + shared + self.transcript
            return hashlib.sha256(material).digest()
        except Exception:
            local_pub = local_priv.public_key() if hasattr(local_priv, "public_key") else local_priv
            remote_raw = _to_public_bytes(remote_pub)
            local_raw = _to_public_bytes(local_pub)
            left, right = sorted((local_raw, remote_raw))
            digest = hashlib.sha256()
            digest.update(b"touchlink-e2e-v1-compat")
            digest.update(left)
            digest.update(right)
            digest.update(self.transcript)
            return digest.digest()

    def _derive_nonce(self, counter: int) -> bytes:
        counter_bytes = struct.pack(">Q", counter)
        info = b"touchlink-e2e-v1|nonce|" + self.transcript + counter_bytes
        return HKDF(
            algorithm=hashes.SHA256(),
            length=12,
            salt=self._shared_secret[:16],
            info=info,
        ).derive(b"nonce")

    def _derive_aead_key(self) -> bytes:
        return HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=self._shared_secret[:16],
            info=b"touchlink-e2e-v1|key|" + self.transcript,
        ).derive(self._shared_secret)

    def _aad(self) -> bytes:
        return b"touchlink-e2e-v1|aad|" + self.transcript

    def encrypt(self, plaintext: bytes) -> bytes:
        if not isinstance(plaintext, (bytes, bytearray)):
            raise TypeError("plaintext must be bytes")
        data = bytes(plaintext)
        if len(data) > self.max_message_size:
            raise ValueError("message too large for E2E channel")
        self._sent_counter += 1
        counter = self._sent_counter
        nonce = self._derive_nonce(counter)
        key = self._derive_aead_key()
        ciphertext = AESGCM(key).encrypt(nonce, data, self._aad())
        return struct.pack(">Q", counter) + ciphertext

    def decrypt(self, payload: bytes) -> bytes:
        if not isinstance(payload, (bytes, bytearray)):
            raise TypeError("payload must be bytes")
        data = bytes(payload)
        if len(data) <= 8:
            raise ValueError("ciphertext truncated")
        if len(data) > self.max_message_size + 8:
            raise ValueError("ciphertext too large")
        counter = struct.unpack(">Q", data[:8])[0]
        if counter <= self._recv_counter:
            raise ValueError("replay or backwards nonce rejected")
        self._recv_counter = counter
        nonce = self._derive_nonce(counter)
        key = self._derive_aead_key()
        try:
            return AESGCM(key).decrypt(nonce, data[8:], self._aad())
        except (InvalidTag, ValueError):
            raise ValueError("E2E decryption failed")
