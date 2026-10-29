# Release process and AV false-positive mitigation

## Scope

This project follows a reproducible release flow for the Windows desktop build and any portable archive shipped to users.

## Requirements for each release

1. Run the full test matrix on Windows for Python 3.10, 3.11, and 3.12.
2. Generate a CycloneDX SBOM and SHA256 checksums for every shipped artifact.
3. Ensure the Windows EXE or portable zip is signed using a trusted code-signing certificate or a managed signing service.
4. Publish the release only after the dependency audit and security scan pass.
5. Record the build tooling versions used for the release and any AV false-positive findings.

## Reproducible build checklist

- Pin Python to the intended version in CI.
- Pin the packaging and build tools in the workflow so the release is reproducible.
- Record the exact toolchain version and the output hash in the release notes.
- Prefer a single, stable build path over ad hoc packaging changes.

## False-positive reduction plan

- Use a signed and timestamped binary.
- Keep the package lean and avoid embedding unexpected or opaque payloads.
- Publish a SHA256 hash so users can validate the download.
- Keep the release notes transparent about the build path and the vendor metadata.
- Use VirusTotal as a final check for high-risk distributions and document the result.

## Required artifact set

Each GitHub release should contain:

- portable zip archive
- signed Windows executable or installer when available
- `SHA256SUMS`
- `sbom.json` (CycloneDX)
- release notes with the version and changelog

## Key management

Private signing keys must never be stored in the repository. They should be kept in a protected secret store, a hardware security module, or a managed signing provider.
