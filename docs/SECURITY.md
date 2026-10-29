# TouchLink Security model

## Threat model

- Relay is untrusted: it may be honest-but-curious or actively malicious.
- Eavesdroppers can read the TCP/TLS stream between viewer and relay, but not the local machine memory.
- A stolen device may try to replay old packets or brute-force weak passcodes.
- The fixed password remains a fallback for local LAN only and must be explicitly enabled.

## Sprint 2.2: relay E2E

When both endpoints advertise `e2e-v1`, the channel must upgrade to an end-to-end encrypted session before the first user payload is sent.

The current implementation uses only standard cryptographic primitives from `cryptography`:

- X25519 ephemeral key agreement for per-session shared secret.
- Ed25519 identity signatures for transcript binding and MITM rejection.
- HKDF-SHA256 for deriving the AES-256-GCM key and nonce material.
- AES-256-GCM for authenticated encryption of every message.

Each encrypted payload includes a monotonic 64-bit counter as part of the message, and the receiver rejects duplicates or decreasing counters. The relay only sees ciphertext bytes and therefore cannot read the user data.

## One-time passcode

For first-time connection flows without a paired trust store, the default passcode is:

- 10 chars
- alphabet without ambiguous glyphs (`ABCDEFGHJKLMNPQRSTUVWXYZ23456789`)
- valid for 600 seconds
- single-use only

This is designed for human verification and session bootstrap rather than long-lived credential storage.

## Fixed password restriction

The fixed password mode is intentionally limited to LAN-only deployments and must be enabled manually. It is explicitly treated as a local fallback, not a remote-safe default.

## Relay requirement

When `require_e2e` is enabled (default for relay mode), peers without `e2e-v1` are rejected. This prevents downgrade attacks and makes the relay-only encryption mandatory in public deployments.

## Security notes

- Do not invent custom encryption primitives; use only standard library-backed primitives.
- Keep the passcode and transcript separate; a leaked transcript does not reveal the symmetric key without the passcode or session secret.
- Fail closed: failed signature verification, replayed counters, or bit-flipped ciphertext result in session rejection.
