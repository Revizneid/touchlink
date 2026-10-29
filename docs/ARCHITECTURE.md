# TouchLink architecture

## Overview

TouchLink has three major runtime layers:

1. Desktop agent: captures frames, authenticates viewers, enforces consent, and sends input to the host system.
2. Relay service: routes sessions between peers while remaining untrusted for content confidentiality.
3. Mobile/PWA client: renders the remote desktop and sends control events.

## Runtime flow

```text
Browser / phone PWA -> Relay or LAN -> Desktop agent -> capture + input + consent -> host Windows session
```

## Key concerns

- Confidentiality: with E2E enabled, the relay only sees ciphertext.
- Consent: every new connection is gated by an explicit allow/deny/view-only decision.
- Availability: reconnect backoff, resume tokens, and rate limiting recover from transient failures.
- Security: DPAPI, signed manifests, signed signaling, and strict validation reduce the risk of downgrade and tampering.

## Important modules

- desktop/core.py: session coordination and state management
- desktop/protocol.py: protocol capability negotiation
- desktop/security/*: pairing, trust, E2E, and verification primitives
- desktop/secure.py: protected config and resume-token handling
- relay/relay_server.py: public relay service and rate limiting
- web/app.js: mobile control and viewport logic

## Release assumptions

The build and deployment path is intentionally fail-closed: the user must see a signed update and must approve it before installation proceeds. This keeps the final public release aligned with the project’s threat model.
