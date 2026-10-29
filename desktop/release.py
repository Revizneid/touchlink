from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


DEFAULT_PROJECT_NAME = "TouchLink"


def compute_sha256(path: str | Path) -> str:
    target = Path(path)
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_artifact(artifact: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(artifact, str):
        path = Path(artifact)
        return {"name": path.name, "path": str(path), "sha256": compute_sha256(path)}
    if isinstance(artifact, dict):
        raw_path = artifact.get("path") or artifact.get("file")
        if raw_path is None:
            raise ValueError("artifact dict must include a path/file field")
        path = Path(raw_path)
        name = str(artifact.get("name") or path.name)
        return {"name": name, "path": str(path), "sha256": compute_sha256(path)}
    raise TypeError("artifact must be filepath or dict with path/file metadata")


def build_sbom(project_name: str, version: str, artifacts: Sequence[str | dict[str, Any]]) -> dict[str, Any]:
    normalized = [_normalize_artifact(item) for item in artifacts]
    metadata = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tools": [{"vendor": "TouchLink", "name": "release-builder", "version": version}],
        "component": {"type": "application", "name": project_name, "version": version},
    }
    components = [
        {
            "type": "library",
            "name": item["name"],
            "version": version,
            "hashes": [{"alg": "SHA-256", "value": item["sha256"]}],
        }
        for item in normalized
    ]
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": metadata,
        "components": components,
    }


def build_release_manifest(
    version: str,
    artifacts: Sequence[str | dict[str, Any]],
    project_name: str = DEFAULT_PROJECT_NAME,
    release_notes: str = "",
) -> dict[str, Any]:
    normalized = [_normalize_artifact(item) for item in artifacts]
    sbom = build_sbom(project_name, version, normalized)
    return {
        "version": str(version),
        "project": str(project_name),
        "artifacts": normalized,
        "release_notes": release_notes,
        "sbom": sbom,
        "sbom_json": json.dumps(sbom, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
    }


def write_sha256sums(artifacts: Iterable[str | Path], output_path: str | Path) -> Path:
    target = Path(output_path)
    lines = []
    for artifact in artifacts:
        resolved = Path(artifact)
        digest = compute_sha256(resolved)
        lines.append(f"{digest}  {resolved.name}")
    target.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return target


def _cli() -> None:
    parser = argparse.ArgumentParser(description="TouchLink release metadata generator")
    parser.add_argument("--version", default="3.0.0")
    parser.add_argument("--project", default=DEFAULT_PROJECT_NAME)
    parser.add_argument("--notes", default="")
    parser.add_argument("--artifact", action="append", default=[])
    parser.add_argument("--output", default="release-manifest.json")
    args = parser.parse_args()

    manifest = build_release_manifest(args.version, args.artifact, project_name=args.project, release_notes=args.notes)
    Path(args.output).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    _cli()
