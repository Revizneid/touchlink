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
