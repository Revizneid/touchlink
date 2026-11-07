from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

logger = logging.getLogger(__name__)

_VERSION_PART_RE = re.compile(r"\d+")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Manifest signing & verification (Sprint 5.2 — unchanged API)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Auto-update runtime (Sprint 5.2 — download, verify, apply)
# ---------------------------------------------------------------------------

UPDATE_CHECK_INTERVAL_S = 6 * 3600  # 6 hours
_DEFAULT_UPDATE_URL = "https://api.github.com/repos/touchlink/touchlink/releases/latest"

# Size limits to prevent downloading maliciously large payloads
MAX_MANIFEST_SIZE = 64 * 1024        # 64 KB
MAX_UPDATE_SIZE = 100 * 1024 * 1024  # 100 MB


def compute_sha256(path: str | Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_for_update(
    update_url: str,
    public_key: Ed25519PublicKey,
    current_version: str,
    *,
    timeout: float = 30.0,
    http_get=None,
) -> dict[str, Any] | None:
    """Fetch the update manifest and verify its signature.

    Returns the verified manifest dict if a valid newer version is available,
    or None if up to date / unreachable / invalid.

    ``http_get`` is an optional callable(url, timeout) -> bytes for testing.
    """
    try:
        if http_get is not None:
            raw = http_get(update_url, timeout)
        else:
            import urllib.request
            req = urllib.request.Request(
                update_url,
                headers={"Accept": "application/json", "User-Agent": f"TouchLink/{current_version}"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read(MAX_MANIFEST_SIZE)

        manifest = json.loads(raw)
        if not isinstance(manifest, dict):
            return None

        if verify_manifest(manifest, public_key, current_version=current_version):
            return manifest
    except Exception as exc:
        logger.debug("Update check failed: %s", exc)
    return None


def download_update(
    download_url: str,
    expected_sha256: str,
    dest_dir: str | Path,
    *,
    timeout: float = 120.0,
    http_get=None,
    progress_cb=None,
) -> Path:
    """Download an update archive and verify its SHA-256 hash.

    Returns the path to the downloaded file.
    Raises ValueError if the hash does not match.
    Raises OSError / urllib errors on network failure.

    ``http_get`` is an optional callable(url, timeout) -> bytes for testing.
    ``progress_cb`` is an optional callable(bytes_downloaded, total_bytes) for UI.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    filename = download_url.rsplit("/", 1)[-1] or "update.zip"
    # Sanitize filename — only allow safe chars
    filename = re.sub(r"[^a-zA-Z0-9._-]", "_", filename)
    dest_path = dest_dir / filename

    if http_get is not None:
        data = http_get(download_url, timeout)
        dest_path.write_bytes(data)
    else:
        import urllib.request
        req = urllib.request.Request(
            download_url,
            headers={"User-Agent": "TouchLink-Updater"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            total = int(resp.headers.get("Content-Length", 0) or 0)
            if total > MAX_UPDATE_SIZE:
                raise ValueError(f"Update too large: {total} bytes > {MAX_UPDATE_SIZE}")
            downloaded = 0
            with open(dest_path, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if downloaded > MAX_UPDATE_SIZE:
                        dest_path.unlink(missing_ok=True)
                        raise ValueError("Update exceeded max size during download")
                    if progress_cb:
                        progress_cb(downloaded, total)

    actual = compute_sha256(dest_path)
    if actual.lower() != expected_sha256.lower():
        dest_path.unlink(missing_ok=True)
        raise ValueError(
            f"SHA-256 mismatch: expected {expected_sha256}, got {actual}"
        )

    return dest_path


def apply_update(
    archive_path: str | Path,
    install_dir: str | Path,
    *,
    backup: bool = True,
) -> Path:
    """Extract an update archive into the install directory.

    If ``backup`` is True, existing files are backed up to a sibling directory
    ``<install_dir>.bak`` before overwriting.

    Returns the install directory path.
    Raises on extraction or I/O error.
    """
    import zipfile

    archive_path = Path(archive_path)
    install_dir = Path(install_dir)

    if not archive_path.exists():
        raise FileNotFoundError(f"Archive not found: {archive_path}")
    if not zipfile.is_zipfile(archive_path):
        raise ValueError(f"Not a valid zip archive: {archive_path}")

    # Validate archive contents — reject path traversal
    with zipfile.ZipFile(archive_path, "r") as zf:
        for info in zf.infolist():
            target = (install_dir / info.filename).resolve()
            if not str(target).startswith(str(install_dir.resolve())):
                raise ValueError(f"Path traversal detected: {info.filename}")

    # Backup existing installation
    backup_dir = None
    if backup and install_dir.exists():
        backup_dir = install_dir.with_suffix(".bak")
        if backup_dir.exists():
            shutil.rmtree(backup_dir, ignore_errors=True)
        shutil.copytree(install_dir, backup_dir, dirs_exist_ok=True)

    # Extract update
    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            zf.extractall(install_dir)
    except Exception:
        # Rollback on failure
        if backup_dir and backup_dir.exists():
            shutil.rmtree(install_dir, ignore_errors=True)
            shutil.copytree(backup_dir, install_dir, dirs_exist_ok=True)
        raise

    return install_dir


class AutoUpdater:
    """Background auto-update checker.

    Usage::

        updater = AutoUpdater(
            update_url="https://example.com/manifest.json",
            public_key=my_ed25519_public_key,
            current_version="3.0.0",
            install_dir=Path(sys.executable).parent,
        )
        updater.start()        # starts background thread
        updater.stop()         # graceful shutdown
    """

    def __init__(
        self,
        update_url: str,
        public_key: Ed25519PublicKey,
        current_version: str,
        install_dir: str | Path,
        *,
        check_interval: float = UPDATE_CHECK_INTERVAL_S,
        on_update_available=None,
        on_update_applied=None,
        on_error=None,
    ):
        self.update_url = update_url
        self.public_key = public_key
        self.current_version = current_version
        self.install_dir = Path(install_dir)
        self.check_interval = check_interval
        self.on_update_available = on_update_available
        self.on_update_applied = on_update_applied
        self.on_error = on_error
        self._stop = False
        self._thread = None

    def start(self):
        import threading
        self._stop = False
        self._thread = threading.Thread(target=self._run, daemon=True, name="auto-updater")
        self._thread.start()

    def stop(self):
        self._stop = True

    def _run(self):
        import time
        while not self._stop:
            try:
                manifest = check_for_update(
                    self.update_url, self.public_key, self.current_version
                )
                if manifest:
                    logger.info("Update available: %s", manifest.get("version"))
                    if self.on_update_available:
                        self.on_update_available(manifest)
            except Exception as exc:
                logger.debug("Auto-update check error: %s", exc)
                if self.on_error:
                    self.on_error(exc)

            # Sleep in small increments so stop() is responsive
            elapsed = 0.0
            while elapsed < self.check_interval and not self._stop:
                time.sleep(min(30.0, self.check_interval - elapsed))
                elapsed += 30.0


__all__ = [
    "sign_manifest",
    "verify_manifest",
    "compute_sha256",
    "check_for_update",
    "download_update",
    "apply_update",
    "AutoUpdater",
    "UPDATE_CHECK_INTERVAL_S",
]
