# Security policy

## Supported versions

The project currently supports the latest release branch and the most recent prior patch branch for security fixes.

## Reporting vulnerabilities

Please report suspected vulnerabilities by email or through a private GitHub security advisory. Include the reproduction steps, affected component, and severity estimate.

## Security posture

- The relay is treated as untrusted transport.
- E2E mode is required for public relay use when supported by both peers.
- Session consent is enforced per new viewer.
- Signed release artifacts and manifest validation reduce malware and downgrade risk.
- Sensitive secrets must never be committed to the repository.

## Disclosure policy

We ask reporters to allow a reasonable remediation window before any public disclosure. The project will provide a response and a fix or mitigation plan as quickly as practical.
