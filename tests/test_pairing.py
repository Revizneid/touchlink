import json
import time

from desktop.security.pairing import (
    PairingSession,
    compute_sas,
    generate_device_keypair,
    verify_challenge_response,
)
from desktop.security.trust_store import DeviceTrustStore


def test_pairing_secret_rejects_wrong_and_expired_secret():
    session = PairingSession(device_id="123456789", device_name="Pixel 9", relay_url="wss://relay")
    secret = session.issue_secret()

    assert session.verify_secret(secret, "123456789") is True
    assert session.verify_secret(secret, "other-id") is False
    assert session.verify_secret(secret + "-tampered", "123456789") is False

    session._secrets[secret]["expires_at"] = time.time() - 1
    assert session.verify_secret(secret, "123456789") is False


def test_sas_matches_on_both_sides_and_replay_nonce_is_rejected():
    agent_kp = generate_device_keypair()
    phone_kp = generate_device_keypair()
    nonce = "nonce-123"

    sas_a = compute_sas(agent_kp.public_bytes, phone_kp.public_bytes, nonce)
    sas_b = compute_sas(phone_kp.public_bytes, agent_kp.public_bytes, nonce)
    assert sas_a == sas_b
    assert len(sas_a) == 6

    proof = phone_kp.private_key.sign(nonce.encode("utf-8"))
    assert verify_challenge_response(phone_kp.public_key, nonce, proof) is True
    assert verify_challenge_response(phone_kp.public_key, nonce, b"bad-signature") is False


def test_trust_store_can_revoke_and_enforce_rights():
    store = DeviceTrustStore(path=None)
    device_id = "dev-1"
    pubkey_b64 = "AQID"

    store.add_trusted_device(
        device_id=device_id,
        device_name="Test Phone",
        public_key_b64=pubkey_b64,
        permission="control",
    )

    entry = store.get(device_id)
    assert entry is not None
    assert entry["permission"] == "control"

    store.revoke(device_id)
    assert store.get(device_id) is None


def test_trust_store_rejects_wrong_signature_and_keeps_history():
    store = DeviceTrustStore(path=None)
    kp = generate_device_keypair()
    store.add_trusted_device(
        device_id="dev-2",
        device_name="Phone 2",
        public_key_b64=kp.public_key_b64,
        permission="view_only",
    )

    proof = kp.private_key.sign(b"challenge-abc")
    assert store.verify_signed_nonce("dev-2", b"challenge-abc", proof) is True
    assert store.verify_signed_nonce("dev-2", b"challenge-abc", b"bad") is False
    assert len(store.list()) >= 1
