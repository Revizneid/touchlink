"""Tests for Sprint 5.2 — Ed25519 manifest + auto-update runtime."""
import datetime as dt
import hashlib
import json
import zipfile
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from desktop.update import (
    AutoUpdater,
    apply_update,
    check_for_update,
    compute_sha256,
    download_update,
    sign_manifest,
    verify_manifest,
)


def test_signed_update_manifest_rejects_downgrade_and_bad_signature():
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    now = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)

    base_manifest = {
        "version": "1.2.3",
        "channel": "stable",
        "download_url": "https://example.com/TouchLink-1.2.3.zip",
        "sha256": "a" * 64,
        "published_at": "2026-01-01T00:00:00+00:00",
        "expires_at": "2026-12-31T00:00:00+00:00",
    }
    signed = sign_manifest(base_manifest, private_key)

    assert verify_manifest(signed, public_key, current_version="1.2.2", now=now) is True
    assert verify_manifest(signed, public_key, current_version="1.2.3", now=now) is False
    assert verify_manifest({**signed, "version": "1.2.4"}, public_key, current_version="1.2.3", now=now) is False

    tampered = dict(signed)
    tampered["sha256"] = "b" * 64
    assert verify_manifest(tampered, public_key, current_version="1.2.2", now=now) is False


def test_check_for_update_returns_manifest_on_valid(tmp_path):
    """check_for_update should return manifest when signature is valid."""
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    manifest = sign_manifest({
        "version": "4.0.0",
        "sha256": "c" * 64,
        "download_url": "https://example.com/update.zip",
        "published_at": "2026-01-01T00:00:00+00:00",
    }, private_key)

    raw_json = json.dumps(manifest).encode()

    def mock_get(url, timeout):
        return raw_json

    result = check_for_update(
        "https://example.com/manifest.json",
        public_key,
        "3.0.0",
        http_get=mock_get,
    )
    assert result is not None
    assert result["version"] == "4.0.0"


def test_check_for_update_returns_none_on_invalid():
    """check_for_update returns None when manifest is invalid."""
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    def mock_get(url, timeout):
        return b'{"invalid": true}'

    result = check_for_update(
        "https://example.com/manifest.json",
        public_key,
        "3.0.0",
        http_get=mock_get,
    )
    assert result is None


def test_check_for_update_returns_none_on_network_error():
    """check_for_update returns None gracefully on network error."""
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    def mock_get(url, timeout):
        raise ConnectionError("no network")

    result = check_for_update(
        "https://example.com/manifest.json",
        public_key,
        "3.0.0",
        http_get=mock_get,
    )
    assert result is None


def test_download_update_verifies_sha256(tmp_path):
    """download_update should verify hash and reject mismatches."""
    content = b"fake-update-binary-content-v4"
    expected_sha = hashlib.sha256(content).hexdigest()

    def mock_get(url, timeout):
        return content

    result = download_update(
        "https://example.com/TouchLink-4.0.0.zip",
        expected_sha,
        tmp_path,
        http_get=mock_get,
    )
    assert result.exists()
    assert compute_sha256(result) == expected_sha


def test_download_update_rejects_bad_hash(tmp_path):
    """download_update should raise ValueError on hash mismatch."""
    def mock_get(url, timeout):
        return b"corrupted-content"

    import pytest
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        download_update(
            "https://example.com/bad.zip",
            "0" * 64,  # wrong hash
            tmp_path,
            http_get=mock_get,
        )


def test_apply_update_extracts_and_backs_up(tmp_path):
    """apply_update should extract files and create a backup."""
    install_dir = tmp_path / "app"
    install_dir.mkdir()
    (install_dir / "old_file.txt").write_text("old")

    # Create a valid zip
    archive = tmp_path / "update.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("new_file.txt", "new content")
        zf.writestr("config.txt", "config data")

    result = apply_update(archive, install_dir, backup=True)
    assert result == install_dir
    assert (install_dir / "new_file.txt").read_text() == "new content"
    assert (install_dir / "config.txt").read_text() == "config data"
    # Backup should exist
    backup_dir = install_dir.with_suffix(".bak")
    assert backup_dir.exists()
    assert (backup_dir / "old_file.txt").read_text() == "old"


def test_apply_update_rejects_path_traversal(tmp_path):
    """apply_update should reject archives with path traversal."""
    install_dir = tmp_path / "app"
    install_dir.mkdir()

    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../../etc/passwd", "pwned")

    import pytest
    with pytest.raises(ValueError, match="Path traversal"):
        apply_update(archive, install_dir)


def test_apply_update_rejects_non_zip(tmp_path):
    """apply_update should reject non-zip files."""
    install_dir = tmp_path / "app"
    install_dir.mkdir()

    fake = tmp_path / "notzip.bin"
    fake.write_bytes(b"this is not a zip")

    import pytest
    with pytest.raises(ValueError, match="Not a valid zip"):
        apply_update(fake, install_dir)


def test_auto_updater_starts_and_stops():
    """AutoUpdater should start/stop without errors."""
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    updater = AutoUpdater(
        update_url="https://example.com/manifest.json",
        public_key=public_key,
        current_version="3.0.0",
        install_dir=".",
        check_interval=0.1,
    )
    updater.start()
    import time
    time.sleep(0.05)
    updater.stop()
    assert updater._stop is True
