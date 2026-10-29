"""Helpers for hardening the Windows service pipe and validating incoming commands."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, Iterable, Optional, Set

PIPE_ALLOWED_OPS: frozenset[str] = frozenset({"ping", "grab", "input"})
VALIDATE_PIPE_OPS = PIPE_ALLOWED_OPS
MAX_PIPE_REQUEST_BYTES = 1024 * 1024


def sanitize_pipe_operation(op: Any) -> Optional[Dict[str, Any]]:
    """Return a normalized operation dict only if it matches the explicit allowlist."""
    if not isinstance(op, dict):
        return None

    op_name = str(op.get("op", "")).strip()
    if op_name not in PIPE_ALLOWED_OPS:
        return None

    cleaned: Dict[str, Any] = {"op": op_name}
    for key, value in op.items():
        if key == "op":
            continue
        cleaned[key] = value

    try:
        payload = json.dumps(cleaned, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    except Exception:
        return None

    if len(payload) > MAX_PIPE_REQUEST_BYTES:
        return None

    return cleaned


def validate_pipe_client(
    *,
    client_exe_path: Optional[str] = None,
    install_root: Optional[str] = None,
    allowed_hashes: Optional[Iterable[str]] = None,
    allowed_basenames: Optional[Iterable[str]] = None,
) -> bool:
    """Accept only a trusted executable path or a hash that matches a known-good binary."""
    if not client_exe_path:
        return False

    raw_path = str(client_exe_path)
    absolute_path = os.path.abspath(raw_path)
    normalized_hashes: Set[str] = {str(h).lower() for h in (allowed_hashes or [])}
    normalized_names: Set[str] = {str(n).lower() for n in (allowed_basenames or [])}

    if normalized_hashes:
        raw_digest = hashlib.sha256(raw_path.encode("utf-8")).hexdigest()
        abs_digest = hashlib.sha256(absolute_path.encode("utf-8")).hexdigest()
        if raw_digest in normalized_hashes or abs_digest in normalized_hashes:
            return True

    basename = os.path.basename(raw_path).lower()
    if basename in normalized_names:
        return True

    if install_root and os.path.isdir(str(install_root)):
        try:
            common = os.path.commonpath([os.path.abspath(str(install_root)), path])
            if common == os.path.abspath(str(install_root)):
                return True
        except Exception:
            pass

    return False


def build_pipe_sddl(current_user_sid: Optional[str] = None) -> str:
    """Build a conservative SDDL for the pipe so only SYSTEM + Administrators + the install user can access it."""
    sddl = "D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;GA;;;IU)(A;;GR;;;DU)"
    if current_user_sid:
        sddl = f"D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;GA;;;IU)(A;;GA;;;{current_user_sid})(A;;GR;;;DU)"
    return sddl


__all__ = [
    "MAX_PIPE_REQUEST_BYTES",
    "PIPE_ALLOWED_OPS",
    "VALIDATE_PIPE_OPS",
    "build_pipe_sddl",
    "sanitize_pipe_operation",
    "validate_pipe_client",
]
