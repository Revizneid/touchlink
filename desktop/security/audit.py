"""Local audit log for authentication and session events."""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping


_SENSITIVE_KEYS = ("password", "secret", "token", "clipboard", "keys", "payload", "pin", "code")


def _mask_ip(ip_value: Any) -> str:
    value = str(ip_value or "").strip()
    if not value:
        return "unknown"
    if ":" in value:
        try:
            left, right = value.split(":", 1)
            return f"{left[:2]}**:***" if left else "::1"
        except Exception:
            return "[redacted]"
    parts = value.split(".")
    if len(parts) == 4:
        return ".".join([parts[0], "*", "*", "*"])
    return "[redacted]" if value.startswith("server-") else value


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        cleaned: Dict[str, Any] = {}
        for key, inner in value.items():
            lowered = str(key).lower()
            if any(token in lowered for token in _SENSITIVE_KEYS):
                cleaned[key] = "[REDACTED]"
            else:
                cleaned[key] = _sanitize_value(inner)
        return cleaned

    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]

    if isinstance(value, str):
        redacted = value
        for token in ("password", "secret", "clipboard", "key", "token", "pin", "code"):
            redacted = re.sub(rf"(?i){token}", "[REDACTED]", redacted)
        return redacted

    return value


class AuditLogger:
    """Append-only JSONL logger, keeping only safe metadata and sanitized details."""

    def __init__(self, path: str | None = None):
        if path:
            self.path = path
        else:
            base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".touchlink")
            self.path = os.path.join(base, "TouchLink", "audit", "audit.jsonl")
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)

    def record_event(
        self,
        *,
        event: str,
        device_id: str | None = None,
        ip: str | None = None,
        auth_method: str | None = None,
        permission: str | None = None,
        session_id: str | None = None,
        details: Mapping[str, Any] | None = None,
        **extra: Any,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": str(event),
            "device_id": device_id,
            "ip": _mask_ip(ip),
            "auth_method": auth_method,
            "permission": permission,
            "session_id": session_id,
            "details": _sanitize_value(dict(details or {})),
        }
        payload.update({k: _sanitize_value(v) for k, v in extra.items() if k not in {"details"}})

        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n")
        return payload


__all__ = ["AuditLogger"]
