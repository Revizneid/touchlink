"""File transfer protocol helpers for Sprint 4.2.

The goal here is to keep the data model and safety checks explicit: each transfer has a
bounded size, SHA-256 integrity validation, safe sanitization of the destination file name,
and a strict allowlist for the destination directory.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

DANGEROUS_EXTENSIONS = {
    ".exe",
    ".bat",
    ".cmd",
    ".ps1",
    ".vbs",
    ".js",
    ".msi",
    ".scr",
    ".lnk",
}
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", "COM1", "COM2", "LPT1", "LPT2"}
MAX_FILE_BYTES = 500 * 1024 * 1024
DEFAULT_CHUNK_BYTES = 64 * 1024


def sanitize_file_name(name: str) -> str:
    """Return a sanitized file name that is safe to place on disk."""
    if not name:
        raise ValueError("file name is required")
    raw = str(name).replace("\\", "/")
    base = os.path.basename(raw)
    if not base or base in {".", ".."}:
        base = "download_file"
    base = base.strip().strip(".")
    base = re.sub(r"[^A-Za-z0-9._ -]", "", base)
    base = base.strip().strip()
    if not base:
        base = "download_file"
    stem, ext = os.path.splitext(base)
    if stem.upper() in WINDOWS_RESERVED:
        raise ValueError("reserved Windows device name is not allowed")
    if ext.lower() in DANGEROUS_EXTENSIONS:
        raise ValueError("dangerous file extension is not allowed")
    return base


def validate_file_offer(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    transfer_id = str(payload.get("id") or "")
    name = str(payload.get("name") or "")
    size = payload.get("size")
    sha256 = str(payload.get("sha256") or "")
    if not transfer_id or not name:
        return False
    try:
        size_value = int(size)
    except (TypeError, ValueError):
        return False
    if size_value <= 0 or size_value > MAX_FILE_BYTES:
        return False
    try:
        sanitize_file_name(name)
    except ValueError:
        return False
    return re.fullmatch(r"[0-9a-fA-F]{64}", sha256)


def build_file_offer(transfer_id: str, file_name: str, file_size: int, sha256_hex: str) -> dict[str, Any]:
    if not validate_file_offer({
        "id": transfer_id,
        "name": file_name,
        "size": file_size,
        "sha256": sha256_hex,
    }):
        raise ValueError("invalid file offer")
    return {
        "type": "file_offer",
        "id": str(transfer_id),
        "name": sanitize_file_name(file_name),
        "size": int(file_size),
        "sha256": str(sha256_hex).lower(),
        "chunk_size": DEFAULT_CHUNK_BYTES,
    }


def is_valid_destination(destination: str | os.PathLike[str], allowlist: Sequence[str | os.PathLike[str]] | None = None) -> bool:
    try:
        target = Path(destination).expanduser().resolve(strict=False)
    except Exception:
        return False
    roots = allowlist or []
    if not roots:
        return True
    for root in roots:
        try:
            root_path = Path(root).expanduser().resolve(strict=False)
        except Exception:
            continue
        try:
            target.relative_to(root_path)
            return True
        except ValueError:
            continue
    return False


class FileTransferSession:
    """Simple session object for ordered chunked transfers with SHA-256 validation."""

    def __init__(
        self,
        *,
        transfer_id: str,
        file_name: str,
        file_size: int,
        expected_sha256: str,
        destination_dir: str | os.PathLike[str],
        allowlist: Sequence[str | os.PathLike[str]] | None = None,
        chunk_size: int | None = None,
        max_total_bytes: int = MAX_FILE_BYTES,
    ):
        self.transfer_id = str(transfer_id)
        self.file_name = sanitize_file_name(file_name)
        self.file_size = int(file_size)
        self.expected_sha256 = str(expected_sha256).lower()
        self.destination_dir = str(destination_dir)
        self.allowlist = list(map(str, allowlist or [self.destination_dir]))
        self.chunk_size = int(chunk_size or max(1, min(DEFAULT_CHUNK_BYTES, max(1, self.file_size // 2))))
        self.max_total_bytes = int(max_total_bytes)
        self._chunks: dict[int, bytes] = {}
        self._hash = hashlib.sha256()
        self._received_bytes = 0
        self._complete = False
        self._last_seq = -1

        if self.file_size <= 0 or self.file_size > self.max_total_bytes:
            raise ValueError("file size is out of range")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", self.expected_sha256):
            raise ValueError("expected SHA-256 is invalid")
        if not is_valid_destination(self.destination_dir, self.allowlist):
            raise ValueError("destination is outside the allowlist")

    @property
    def is_complete(self) -> bool:
        return self._complete and self._received_bytes == self.file_size and self._hash.hexdigest() == self.expected_sha256

    def accept(self) -> dict[str, Any]:
        return {"type": "file_accept", "id": self.transfer_id}

    def reject(self, reason: str = "rejected") -> dict[str, Any]:
        return {"type": "file_reject", "id": self.transfer_id, "reason": reason}

    def _max_seq(self) -> int:
        if self.file_size <= 0:
            return 0
        return max(1, math.ceil(self.file_size / max(1, self.chunk_size)))

    def _safe_chunk(self, seq: int, data: bytes) -> bool:
        if seq < 0 or seq >= self._max_seq():
            return False
        if not isinstance(data, (bytes, bytearray, memoryview)):
            return False
        payload = bytes(data)
        if len(payload) > self.chunk_size:
            return False
        return not self._received_bytes + len(payload) > self.file_size + self.chunk_size

    def receive_chunk(self, seq: int, data: bytes, *, expect_final: bool = False) -> bool:
        if not self._safe_chunk(seq, data):
            return False

        payload = bytes(data)
        if seq in self._chunks:
            return True

        self._chunks[seq] = payload
        self._received_bytes += len(payload)
        self._hash.update(payload)
        self._last_seq = max(self._last_seq, int(seq))

        if expect_final:
            if self._received_bytes != self.file_size:
                self._complete = False
                return False
            if self._hash.hexdigest() != self.expected_sha256:
                self._complete = False
                return False
            self._complete = True
            return True

        return True

    def build_ack(self, seq: int) -> dict[str, Any]:
        return {"type": "file_ack", "id": self.transfer_id, "seq": int(seq)}

    def build_done(self) -> dict[str, Any]:
        return {"type": "file_done", "id": self.transfer_id, "sha256": self.expected_sha256, "complete": self.is_complete}


__all__ = [
    "DANGEROUS_EXTENSIONS",
    "DEFAULT_CHUNK_BYTES",
    "MAX_FILE_BYTES",
    "FileTransferSession",
    "build_file_offer",
    "is_valid_destination",
    "sanitize_file_name",
    "validate_file_offer",
]
