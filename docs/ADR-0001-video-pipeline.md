# ADR-0001: Video pipeline direction for Sprint 3.1

## Status
Accepted for the current pathfinder implementation.

## Context
The project needs a transport abstraction before WebRTC is introduced. The existing relay and LAN WebSocket paths are already working, but WebRTC requires a clean interface so the core code can stop depending on one concrete transport.

## Decision
Use a `Transport` abstraction with three current implementations:
- `LanWsTransport`
- `RelayWsTransport`
- `WebRtcTransport` (with graceful failure if `aiortc` is not installed)

For the initial spike, the system will intentionally prefer a clean compatibility layer over fully integrated peer-to-peer encoding. The first WebRTC path will use a single video track and a `ctrl` data channel abstraction. The default codec decision is to support H.264 when available, with VP8 as a fallback for compatibility.

## Consequences
- Core logic can evolve without being tied to one transport.
- Tests can validate interface behavior without requiring a live browser or RTC library.
- Real-time optimization and codec tuning can be handled in later Sprints after the abstraction is stable.
