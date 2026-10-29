import hashlib
import os

from desktop.security.service_hardening import (
    PIPE_ALLOWED_OPS,
    VALIDATE_PIPE_OPS,
    build_pipe_sddl,
    sanitize_pipe_operation,
    validate_pipe_client,
)


def test_pipe_operations_are_whitelisted():
    assert "ping" in PIPE_ALLOWED_OPS
    assert "grab" in PIPE_ALLOWED_OPS
    assert "input" in PIPE_ALLOWED_OPS
    assert "shell" not in PIPE_ALLOWED_OPS
    assert sanitize_pipe_operation({"op": "ping"}) == {"op": "ping"}
    assert sanitize_pipe_operation({"op": "shell"}) is None
    assert sanitize_pipe_operation({"op": "grab", "monitor": 2})["monitor"] == 2


def test_pipe_client_validation_rejects_non_whitelisted_executable():
    base = os.path.abspath(os.getcwd())
    allowed = hashlib.sha256(b"/safe/path/TouchLink.exe").hexdigest()
    assert validate_pipe_client(
        client_exe_path="/safe/path/TouchLink.exe",
        install_root=base,
        allowed_hashes={allowed},
    ) is True
    assert validate_pipe_client(
        client_exe_path="/tmp/evil.exe",
        install_root=base,
        allowed_hashes={allowed},
    ) is False


def test_pipe_sddl_is_tightened_for_system_admins_and_user():
    sddl = build_pipe_sddl(current_user_sid="S-1-5-21-123-456-789")
    assert "D:" in sddl
    assert "SY" in sddl
    assert "BA" in sddl
    assert "IU" in sddl
    assert "DU" in sddl
    assert "D:P" in sddl
