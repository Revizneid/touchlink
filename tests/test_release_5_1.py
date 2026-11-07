"""Tests for Sprint 5.1 — PyInstaller spec validation and release manifest."""
import ast
import json
from pathlib import Path

from desktop.release import build_release_manifest, compute_sha256, write_sha256sums


def test_release_manifest_and_hashes(tmp_path):
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"hello-touchlink")

    manifest = build_release_manifest(
        version="1.2.3",
        artifacts=[{"name": artifact.name, "path": str(artifact)}],
        project_name="TouchLink",
    )

    assert manifest["version"] == "1.2.3"
    assert manifest["project"] == "TouchLink"
    assert manifest["artifacts"][0]["sha256"] == compute_sha256(artifact)
    assert manifest["sbom"]["bomFormat"] == "CycloneDX"

    sums_path = tmp_path / "SHA256SUMS"
    write_sha256sums([artifact], sums_path)

    lines = sums_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert lines[0].startswith(compute_sha256(artifact)[:8])

    payload = json.loads(manifest["sbom_json"])
    assert payload["bomFormat"] == "CycloneDX"


def test_pyinstaller_spec_is_valid_python():
    """TouchLink.spec must be parseable Python (no syntax errors)."""
    repo = Path(__file__).resolve().parents[1]
    for spec_name in ("TouchLink.spec", "TouchLinkSvc.spec"):
        spec_path = repo / spec_name
        assert spec_path.exists(), f"{spec_name} not found"
        source = spec_path.read_text(encoding="utf-8")
        # Should parse without SyntaxError
        ast.parse(source, filename=spec_name)


def test_spec_declares_required_datas_and_pathex():
    """TouchLink.spec should include web/ and assets/ datas and pathex=['desktop']."""
    repo = Path(__file__).resolve().parents[1]
    source = (repo / "TouchLink.spec").read_text(encoding="utf-8")
    assert "('web', 'web')" in source
    assert "('assets', 'assets')" in source
    assert "'desktop'" in source  # pathex


def test_spec_excludes_bloat_packages():
    """TouchLink.spec should exclude test/dev/science packages for size."""
    repo = Path(__file__).resolve().parents[1]
    source = (repo / "TouchLink.spec").read_text(encoding="utf-8")
    for pkg in ("pytest", "scipy", "pandas", "matplotlib", "flask", "django"):
        assert f"'{pkg}'" in source, f"{pkg} should be in excludes"


def test_inno_setup_version_matches_3_0():
    """Inno Setup .iss should reference version 3.0.0."""
    repo = Path(__file__).resolve().parents[1]
    iss = repo / "installers" / "TouchLink.iss"
    assert iss.exists()
    text = iss.read_text(encoding="utf-8")
    assert '"3.0.0"' in text
    assert "TouchLinkSvc" in text  # service exe included
