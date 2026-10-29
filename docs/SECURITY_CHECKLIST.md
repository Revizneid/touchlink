# SECURITY CHECKLIST

## Required controls

- [x] Relay traffic uses end-to-end encryption and strong replay protection.
- [x] Device pairing uses trust-store entries with permission control and view-only support.
- [x] Connection policy blocks access when no user is present.
- [x] Consent and view-only controls are enforced before granting remote control.
- [x] Audit logging records events without leaking sensitive content.
- [x] Pipe operations are restricted to an explicit allowlist.
- [ ] Windows service should be hardened with process validation and a restrictive ACL on the named pipe.
- [ ] Remote unlock features remain disabled by default and emit audit records when enabled.
- [ ] Bandit and pip-audit should be run in CI before release.

## Current status

This repository already includes the core security primitives for E2E relay encryption, pairing, consent, and audit logging. The remaining Windows-specific service hardening items are intentionally gated behind host-level APIs and should be validated on a real Windows machine during deployment.

## Residual risks

- Windows-only ACL and process validation must be confirmed on the target host.
- Review of Event Log and service privilege minimization should be completed on the final deployment image.
- Fuzzing and abuse testing should be repeated at release time.
