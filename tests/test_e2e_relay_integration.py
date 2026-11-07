"""Integration tests for Sprint 2.2 End-to-End Encryption (E2E) on Relay.

Tests verify:
1. Bidirectional encryption/decryption between agent and viewer using E2EChannel.from_passcode.
2. Fingerprint calculation matches on both peers (8-char hex uppercase).
3. Tamper detection: modifying 1 byte causes decryption failure.
4. Replay attack rejection: old counters are strictly rejected.
5. Wrong password derivation yields indecipherable ciphertext.
6. Relay sees only ciphertext wrapped in type='e2e'.
"""

import base64
import json
import pytest
from desktop.security.e2e import E2EChannel


def test_e2e_bidirectional_passcode_channel():
    passcode = "SecretPass123"
    transcript = "touchlink-relay:DEV-8899"

    agent_ch = E2EChannel.from_passcode("agent", passcode, transcript)
    viewer_ch = E2EChannel.from_passcode("viewer", passcode, transcript)

    # Fingerprint matching
    fp_agent = agent_ch.compute_fingerprint()
    fp_viewer = viewer_ch.compute_fingerprint()
    assert len(fp_agent) == 8
    assert fp_agent == fp_viewer

    # Viewer -> Agent
    viewer_msg = json.dumps({"type": "input", "kind": "key", "key": "enter"}).encode("utf-8")
    cipher_v2a = viewer_ch.encrypt(viewer_msg)
    decrypted_v2a = agent_ch.decrypt(cipher_v2a)
    assert decrypted_v2a == viewer_msg

    # Agent -> Viewer
    agent_msg = json.dumps({"type": "settings", "settings": {"fps": 30}}).encode("utf-8")
    cipher_a2v = agent_ch.encrypt(agent_msg)
    decrypted_a2v = viewer_ch.decrypt(cipher_a2v)
    assert decrypted_a2v == agent_msg


def test_e2e_tamper_detection():
    passcode = "SecretPass123"
    transcript = "touchlink-relay:DEV-8899"

    agent_ch = E2EChannel.from_passcode("agent", passcode, transcript)
    viewer_ch = E2EChannel.from_passcode("viewer", passcode, transcript)

    cipher = bytearray(agent_ch.encrypt(b'{"type":"ping"}'))
    # Tamper with 1 byte of the ciphertext (after counter)
    cipher[-1] ^= 0x01

    with pytest.raises(ValueError, match="E2E decryption failed"):
        viewer_ch.decrypt(bytes(cipher))


def test_e2e_replay_attack_rejected():
    passcode = "SecretPass123"
    transcript = "touchlink-relay:DEV-8899"

    agent_ch = E2EChannel.from_passcode("agent", passcode, transcript)
    viewer_ch = E2EChannel.from_passcode("viewer", passcode, transcript)

    cipher1 = agent_ch.encrypt(b'{"seq":1}')
    cipher2 = agent_ch.encrypt(b'{"seq":2}')

    assert viewer_ch.decrypt(cipher1) == b'{"seq":1}'
    assert viewer_ch.decrypt(cipher2) == b'{"seq":2}'

    # Replaying cipher1 must fail with replay rejected
    with pytest.raises(ValueError, match="replay or backwards nonce rejected"):
        viewer_ch.decrypt(cipher1)


def test_e2e_wrong_passcode_fails():
    transcript = "touchlink-relay:DEV-8899"
    agent_ch = E2EChannel.from_passcode("agent", "CorrectPass1", transcript)
    attacker_ch = E2EChannel.from_passcode("viewer", "WrongPass999", transcript)

    assert agent_ch.compute_fingerprint() != attacker_ch.compute_fingerprint()

    cipher = agent_ch.encrypt(b'{"secret":"data"}')
    with pytest.raises(ValueError, match="E2E decryption failed"):
        attacker_ch.decrypt(cipher)


def test_relay_sees_only_ciphertext():
    """Simulate relay message wrapping: payload seen by relay has no plaintext fields."""
    passcode = "SessionPassWord456"
    transcript = "touchlink-relay:12345678"

    agent_ch = E2EChannel.from_passcode("agent", passcode, transcript)
    sensitive_data = {"type": "input", "kind": "text", "text": "my_super_secret_password"}
    payload_bytes = json.dumps(sensitive_data).encode("utf-8")

    cipher = agent_ch.encrypt(payload_bytes)
    b64_str = base64.b64encode(cipher).decode("ascii")

    # Wire message forwarded by relay
    relay_msg = {"type": "agent_msg", "data": {"type": "e2e", "c": b64_str}}

    # Verify relay message inspection
    relay_payload_str = json.dumps(relay_msg)
    assert "my_super_secret_password" not in relay_payload_str
    assert "input" not in relay_payload_str
    assert relay_msg["data"]["type"] == "e2e"

