from __future__ import annotations

import base64
import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

_VERSION_PART_RE = re.compile(r"\d+")


def _canonical_bytes(obj: Any) -> bytes:
    return json.dumps(obj, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode("utf-8")


def _version_tuple(raw: Any) -> tuple[int, ...]:
    text = str(raw or "0").strip().lower().lstrip("v")
    parts = _VERSION_PART_RE.findall(text)
    return tuple(int(part) for part in parts) if parts else (0,)


def _parse_time(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def sign_manifest(manifest: Mapping[str, Any], private_key: Ed25519PrivateKey) -> dict[str, Any]:
    payload = dict(manifest)
    payload.pop("signature", None)
    signature = private_key.sign(_canonical_bytes(payload))
    signed = dict(payload)
    signed["signature"] = base64.b64encode(signature).decode("ascii")
    return signed


def verify_manifest(
    manifest: Mapping[str, Any] | None,
    public_key: Ed25519PublicKey,
    *,
    current_version: str = "0.0.0",
    now: datetime | None = None,
) -> bool:
    if not isinstance(manifest, Mapping):
        return False

    version = str(manifest.get("version") or "")
    digest = str(manifest.get("sha256") or "")
    if not version or not digest:
        return False

    if not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
        return False

    signature_b64 = str(manifest.get("signature") or "")
    if not signature_b64:
        return False
    try:
        signature = base64.b64decode(signature_b64, validate=True)
    except ValueError:
        return False

    payload = dict(manifest)
    payload.pop("signature", None)
    try:
        public_key.verify(signature, _canonical_bytes(payload))
    except InvalidSignature:
        return False

    try:
        if _version_tuple(version) <= _version_tuple(current_version):
            return False
    except Exception:
        return False

    if now is None:
        now = datetime.now(timezone.utc)

    expires_at = _parse_time(manifest.get("expires_at"))
    if expires_at is not None and now > expires_at:
        return False

    published_at = _parse_time(manifest.get("published_at"))
    return not (published_at is not None and published_at > now)


__all__ = ["sign_manifest", "verify_manifest"]
