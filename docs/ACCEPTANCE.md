# Acceptance checklist for v3.0.0

## Scenario matrix

| Scenario | Expected result |
|---|---|
| Clean install | App installs per-user without requiring admin rights |
| Pairing | Device forms a trusted pairing relationship and session auth succeeds |
| Local LAN control | Mobile client can connect over local Wi-Fi and control the desktop |
| Cellular P2P | Mobile client can establish a connection in a peer path when available |
| TURN | Connection continues through TURN when the direct path is not usable |
| Relay E2E | Session data remains encrypted in transit and relay cannot inspect plaintext |
| Intermittent network | Reconnect logic resumes cleanly without forcing a fresh manual login |
| Remote unlock | Service-assisted unlock flow is available only when explicitly enabled |
| Device revocation | Revoked device access is denied and the session terminates |
| Uninstall | Install artifacts and service components are removed cleanly |

## Validation steps

1. Install the app on a Windows 10/11 host.
2. Open the mobile PWA and pair the device.
3. Verify control works over LAN.
4. Repeat the connection over relay and ensure encryption is active.
5. Drop the connection and verify automatic recovery.
6. Validate that a new viewer requires explicit consent.
7. Verify the service-assisted unlock path only works with the opt-in service component.
8. Uninstall the app and confirm clean removal.

## Pass criteria

- No severe TODO/FIXME remains in the release path.
- The full test suite passes.
- Release artifacts include SHA256 and SBOM output.
- The public release is signed and the hash is published.
