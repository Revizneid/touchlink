# TouchLink v3.0.0

TouchLink is a secure remote-control application for Windows desktops. It supports LAN and relay modes, mobile-first control, consent enforcement, E2E relay encryption, and safe Windows session wake flows.

## Highlights

- Desktop agent for Windows with screen capture and input injection
- Mobile web client as a PWA
- Relay and LAN transport modes
- Pairing/trust flow and explicit consent before new viewers connect
- End-to-end encrypted relay traffic when both peers support the secure protocol
- Signed release workflow and SHA256 artifact validation

## Quick start

1. Install the dependencies: `pip install -r desktop/requirements.txt`
2. Launch the desktop app: `python desktop/main.py`
3. Connect from a phone using either LAN or relay mode
4. Accept the consent prompt on the desktop when a new viewer connects

## Security model

- The relay is treated as untrusted transport and does not receive plaintext session content when E2E mode is enabled.
- The desktop agent verifies the viewer before granting control.
- Resume tokens and multi-step auth help avoid repeated manual re-entry during reconnects.
- Release artifacts are signed and published with checksums for integrity verification.

## Documentation

- [README.md](README.md) — Vietnamese overview
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — architecture summary
- [docs/ACCEPTANCE.md](docs/ACCEPTANCE.md) — acceptance checklist
- [docs/SECURITY.md](docs/SECURITY.md) — security model
- [docs/PROTOCOL.md](docs/PROTOCOL.md) — protocol reference
- [docs/RELEASE.md](docs/RELEASE.md) — release policy
