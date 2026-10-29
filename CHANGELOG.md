# Changelog

## 3.0.0

### Added
- release automation and signed manifest validation
- SHA256 artifact generation and CycloneDX SBOM output
- installer and update policy for safe per-user installation
- release docs and acceptance checklist
- English README and architecture overview

### Changed
- version metadata bumped to 3.0.0
- release automation now enforces explicit install and integrity checks
- project docs now reflect the public release gate and security expectations

### Security
- prevented downgrade acceptance in signed update manifests
- reduced ambiguity in release artifact integrity verification
