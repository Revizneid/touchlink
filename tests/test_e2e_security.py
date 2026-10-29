import base64
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from desktop.security.e2e import (
    E2EChannel,
    OneTimePasscode,
    derive_passcode_key,
    verify_ed25519_signature,
)


def test_e2e_channel_round_trip_and_rejects_bit_flip():
    agent_priv = Ed25519PrivateKey.generate()
    viewer_priv = Ed25519PrivateKey.generate()

    agent_pub = agent_priv.public_key()
    viewer_pub = viewer_priv.public_key()

    channel_a = E2EChannel(
        side="agent",
        local_private_key=agent_priv,
        remote_public_key=viewer_pub,
        local_identity_key=agent_priv,
        remote_identity_key=viewer_pub,
        transcript=b"touchlink-e2e-v1-test",
    )
    channel_b = E2EChannel(
        side="viewer",
        local_private_key=viewer_priv,
        remote_public_key=agent_pub,
        local_identity_key=viewer_priv,
        remote_identity_key=agent_pub,
        transcript=b"touchlink-e2e-v1-test",
    )

    plaintext = b'{"type": "screen", "frame": "abc123"}'
    payload = channel_a.encrypt(plaintext)
    assert payload != plaintext
    assert b"screen" not in payload
    assert channel_b.decrypt(payload) == plaintext

    tampered = bytearray(payload)
    tampered[-1] ^= 0xFF
    with pytest.raises(ValueError):
        channel_b.decrypt(bytes(tampered))


def test_e2e_rejects_replay_and_invalid_signature():
    agent_priv = Ed25519PrivateKey.generate()
    viewer_priv = Ed25519PrivateKey.generate()

    agent_pub = agent_priv.public_key()
    viewer_pub = viewer_priv.public_key()

    agent_channel = E2EChannel(
        side="agent",
        local_private_key=agent_priv,
        remote_public_key=viewer_pub,
        local_identity_key=agent_priv,
        remote_identity_key=viewer_pub,
        transcript=b"touchlink-mitm-test",
    )
    viewer_channel = E2EChannel(
        side="viewer",
        local_private_key=viewer_priv,
        remote_public_key=agent_pub,
        local_identity_key=viewer_priv,
        remote_identity_key=agent_pub,
        transcript=b"touchlink-mitm-test",
    )

    msg = agent_channel.encrypt(b"hello")
    assert viewer_channel.decrypt(msg) == b"hello"
    with pytest.raises(ValueError):
        viewer_channel.decrypt(msg)

    bad_sig = agent_priv.sign(b"not-the-real-message")
    assert verify_ed25519_signature(agent_pub, b"message", bad_sig) is False


def test_passcode_is_single_use_and_wrong_value_rejected():
    code = OneTimePasscode.generate(length=10)
    assert len(code) == 10
    assert all(ch in OneTimePasscode.ALPHABET for ch in code)

    session = OneTimePasscode(issue_time=0)
    token = session.issue_session_passcode()
    assert session.verify(token) is True
    assert session.verify(token) is False
    assert session.verify("WRONG") is False


def test_relay_sees_only_ciphertext():
    agent_key = Ed25519PrivateKey.generate()
    viewer_key = Ed25519PrivateKey.generate()
    channel = E2EChannel(
        side="agent",
        local_private_key=agent_key,
        remote_public_key=viewer_key.public_key(),
        local_identity_key=agent_key,
        remote_identity_key=viewer_key.public_key(),
        transcript=b"relay-ciphertext",
    )
    payload = channel.encrypt(b"password=super-secret")
    relay_view = {"type": "agent_msg", "data": base64.b64encode(payload).decode("ascii")}
    json_text = json.dumps(relay_view)
    assert "super-secret" not in json_text
    assert "password" not in json_text.lower()
    assert "super-secret" not in payload.decode("latin1", errors="ignore")


def test_passcode_derivation_uses_transcript_and_secret():
    transcript = b"session-abc"
    key1 = derive_passcode_key("M4K3X7P2Q9", transcript)
    key2 = derive_passcode_key("M4K3X7P2Q9", transcript)
    key3 = derive_passcode_key("M4K3X7P2Q9", b"different-transcript")
    assert key1 == key2
    assert key1 != key3
