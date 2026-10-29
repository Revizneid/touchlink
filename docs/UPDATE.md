# Safe update and installer policy

## Installer requirements

- Install per-user by default so no administrator privilege is required.
- The optional service component must be opt-in and disabled by default.
- Firewall rules must be restricted to Private networks and only created when the service option is selected.
- Uninstall must remove service registration, named pipes, and firewall rules.

## Update policy

- Updates are only accepted when the manifest signature validates with the embedded public key.
- The manifest must be newer than the currently installed version.
- Older versions and tampered payloads are rejected.
- Downloaded artifacts must match the SHA256 declared in the signed manifest.
- The user must approve the update before installation starts.
- Automatic background updates are never allowed for a high-privilege service component.

## Manifest structure

The signed update manifest is a JSON object with these fields:

- `version` — semantic version string, e.g. `1.2.3`
- `channel` — distribution channel, such as `stable`
- `download_url` — HTTPS URL for the artifact
- `sha256` — SHA256 of the downloaded package
- `published_at` — ISO-8601 timestamp
- `expires_at` — ISO-8601 expiration timestamp
- `signature` — base64-encoded Ed25519 signature over the canonical JSON body excluding the `signature` field

The signature is validated before any local install or upgrade is accepted.
