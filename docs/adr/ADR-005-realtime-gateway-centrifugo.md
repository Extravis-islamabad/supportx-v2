# ADR-005: Realtime gateway: Centrifugo

- **Status:** Accepted
- **Date:** 2026-10-22
- **Source:** architecture.md §5, §8
- **Owner:** Haider (Product Owner)

## Context

Real-time everywhere is a core goal: every screen updates within 1 s of commit, up to 100,000 WebSocket connections per cluster, with presence and reconnect recovery.

## Decision

Use a Centrifugo cluster for WebSocket connections, channel subscriptions, presence and history. The Core API issues connection and per-channel subscription tokens after permission checks; a fan-out consumer publishes from NATS. A custom FastAPI WebSocket gateway was rejected.

## Consequences

- **Positive:** Purpose-built scaling, presence, history recovery, JWT channel auth.
- **Negative:** Another component to bundle and operate.
- **Negative:** Clients need fallbacks (SSE / HTTP streaming / polling) when WebSockets are blocked.

## Notes

Accepted at bootstrap (architecture.md §19 listed it as *Proposed*). Owner set by D-007 until a tech lead is appointed.
