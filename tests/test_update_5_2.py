import datetime as dt

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from desktop.update import sign_manifest, verify_manifest


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
