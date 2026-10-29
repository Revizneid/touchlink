import json
import os
import tempfile
import time

from desktop.security.audit import AuditLogger
from desktop.security.otp import TOTPSecret, generate_recovery_codes, generate_totp, validate_totp
from desktop.security.policy import evaluate_connection_policy


def test_connection_policy_matrix():
    trusted_lan = evaluate_connection_policy(
        trusted_device=True,
        source="lan",
        is_relay=False,
        active_user=True,
    )
    assert trusted_lan["decision"] == "allow"
    assert trusted_lan["requires_consent"] is False

    untrusted_relay = evaluate_connection_policy(
        trusted_device=False,
        source="relay",
        is_relay=True,
        active_user=True,
    )
    assert untrusted_relay["decision"] in {"require_consent", "deny"}
    assert untrusted_relay["requires_consent"] is True

    headless_relay = evaluate_connection_policy(
        trusted_device=False,
        source="relay",
        is_relay=True,
        active_user=False,
    )
    assert headless_relay["decision"] == "deny"


def test_totp_round_trip_and_recovery_codes():
    secret = TOTPSecret.generate()
    code = generate_totp(secret.secret)
    assert validate_totp(secret.secret, code) is True
    assert validate_totp(secret.secret, str(int(code) + 1)) is False

    codes = generate_recovery_codes("device-42")
    assert len(codes) == 10
    assert len(set(codes)) == 10
    assert all(len(c) == 8 for c in codes)


def test_audit_logger_redacts_sensitive_data(tmp_path):
    log_path = tmp_path / "audit.jsonl"
    logger = AuditLogger(path=str(log_path))
    logger.record_event(
        event="session.started",
        device_id="dev-1",
        ip="10.0.0.5",
        auth_method="totp",
        permission="view_only",
        session_id="sess-7",
        details={
            "clipboard": "secret-value",
            "keys": "should-not-be-kept",
            "message": "user typed password in clear",
        },
    )

    data = log_path.read_text(encoding="utf-8")
    assert "session.started" in data
    assert "dev-1" in data
    assert "secret-value" not in data
    assert "password" not in data.lower()
    assert "should-not-be-kept" not in data

    row = json.loads(data.strip().splitlines()[-1])
    assert row["event"] == "session.started"
    assert row["permission"] == "view_only"
    assert row["auth_method"] == "totp"
