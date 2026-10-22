# ADR-003: Event bus: NATS JetStream

- **Status:** Accepted
- **Date:** 2026-10-22
- **Source:** architecture.md §4.1, §5, §6.5
- **Owner:** TBC

## Context

Every state change emits a domain event (P3). The bus must be light enough for a single-node on-prem install yet scale for SaaS, with replay and per-subject retention.

## Decision

Use NATS JetStream with per-tenant subjects and at-least-once delivery, fed by the transactional outbox relay. Kafka (heavier ops) and Redis Streams (weaker guarantees) were rejected.

## Consequences

- **Positive:** Small footprint, replay, retention per subject.
- **Negative:** Consumers must be idempotent (event IDs recorded).
- **Negative:** Team must learn JetStream operations (streams, consumers, retention).

## Notes

Accepted at bootstrap (architecture.md §19 listed it as *Proposed*); confirm owner at Stage 0 sign-off.
