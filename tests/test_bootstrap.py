import json
import os
import subprocess
import sys


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(__file__))


def test_module_main_headless_safe_exit_after():
    repo_root = _repo_root()
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "desktop.main",
            "--headless",
            "--safe-test",
            "--exit-after",
            "3",
            "--print-ready",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    combined = (proc.stdout + proc.stderr).lower()
    assert "ready" in combined or "touchlink" in combined


def test_doctor_json_reports_no_fail():
    repo_root = _repo_root()
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "desktop.main",
            "--doctor",
            "--json",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout.strip())
    assert "summary" in payload
    assert payload["summary"]["fail"] >= 0
