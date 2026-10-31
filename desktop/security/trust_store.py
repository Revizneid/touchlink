"""Persistent trust store for paired devices.

The store is a JSON document encrypted with the Windows DPAPI where available,
then persisted to disk. The in-memory path is also supported for tests.
"""

from __future__ import annotations

import base64
import builtins
import json
import os
import time
from collections.abc import Iterable
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from desktop.secure import protect, unprotect


class DeviceTrustStore:
    def __init__(self, path: str | None = None):
        self.path = path or None
        self._devices: dict[str, dict[str, Any]] = {}
        if self.path and os.path.exists(self.path):
            self._load()

    def _load(self):
        if not self.path or not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                payload = fh.read()
            plaintext = unprotect(payload) if payload.startswith("plain:") is False else payload[6:]
            data = json.loads(plaintext)
            if isinstance(data, dict):
                self._devices = {str(k): v for k, v in data.get("devices", {}).items()}
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            self._devices = {}

    def _save(self):
        if not self.path:
            return
        payload = json.dumps({"devices": self._devices}, sort_keys=True)
        encoded = protect(payload)
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(encoded)

    def add_trusted_device(
        self,
        device_id: str,
        device_name: str,
        public_key_b64: str,
        permission: str = "control",
        expires_at: float | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        entry = {
            "device_id": str(device_id),
            "device_name": str(device_name),
            "public_key_b64": str(public_key_b64),
            "permission": "control" if permission == "control" else "view_only",
            "created_at": time.time(),
            "last_seen": time.time(),
            "expires_at": expires_at,
            "revoked": False,
            "notes": notes or "",
        }
        self._devices[str(device_id)] = entry
        self._save()
        return dict(entry)

    def get(self, device_id: str) -> dict[str, Any] | None:
        entry = self._devices.get(str(device_id))
        if entry is None or bool(entry.get("revoked")):
            return None
        if entry.get("expires_at") is not None and time.time() > float(entry["expires_at"]):
            self._devices.pop(str(device_id), None)
            self._save()
            return None
        return dict(entry)

    def revoke(self, device_id: str) -> bool:
        entry = self._devices.get(str(device_id))
        if entry is None:
            return False
        entry["revoked"] = True
        self._devices.pop(str(device_id), None)
        self._save()
        return True

    def list(self) -> builtins.list[dict[str, Any]]:
        return [dict(v) for v in sorted(self._devices.values(), key=lambda x: x.get("device_name", ""))]

    def update_last_seen(self, device_id: str):
        entry = self._devices.get(str(device_id))
        if entry is not None:
            entry["last_seen"] = time.time()
            self._save()

    def verify_signed_nonce(self, device_id: str, nonce: bytes | str, signature: bytes) -> bool:
        entry = self.get(device_id)
        if entry is None:
            return False
        try:
            public_key_bytes = base64.b64decode(entry["public_key_b64"])
            public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
            public_key.verify(signature, (nonce.decode("utf-8") if isinstance(nonce, (bytes, bytearray)) else str(nonce)).encode("utf-8"))
            return True
        except (TypeError, ValueError):
            return False

    def trusted_device_ids(self) -> Iterable[str]:
        return list(self._devices.keys())
