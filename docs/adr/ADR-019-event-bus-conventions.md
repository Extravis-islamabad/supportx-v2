# ADR-019: Event bus conventions: outbox relay role, subjects, deduplication, dead letters

- **Status:** Accepted
- **Date:** 2026-10-23
- **Source:** architecture.md §4.2, §6.5, §8; ADR-003; WP-007
- **Owner:** Haider (Product Owner)

## Context

ADR-003 chose NATS JetStream fed by a transactional outbox. WP-007 had to fix how the relay reads
every tenant's outbox without weakening tenant isolation, how subjects are named, how duplicates
and failures are handled, and how the API is kept from publishing directly.

## Decision

1. **Relay database role.** A dedicated `supportx_relay` role (defined in
   `backend/tooling/sql/roles.sql`), NOT BYPASSRLS. It reads `outbox_events` of every tenant via
   RLS policies scoped `TO supportx_relay` only, may update only the delivery columns, may delete
   only published rows (policy `published_at IS NOT NULL`), and has no grant on any other table.
   The RLS guard enforces this allowlist in CI.
2. **Relay mechanics.** Direct PostgreSQL connection (not PgBouncer), LISTEN/NOTIFY with a polling
   fallback, batches with `FOR UPDATE SKIP LOCKED` (several relays may run), rows marked published
   only after JetStream acknowledges; `Nats-Msg-Id = event_id` with a 5-minute duplicate window.
3. **Subjects.** `events.<tenant_id>.<module>.<entity>.<action>`; `replay.<consumer>.…` for
   replaying a dead letter to one consumer; `dlq.<consumer>.…` in a separate `SUPPORTX_DLQ` stream.
4. **Consumers.** Durable pull consumers declared by modules (`ModuleSpec.consumers`), idempotency
   via `processed_events` written in the handler's transaction, server `max_deliver` unlimited and
   dead-lettering done by the worker after N attempts with exponential backoff.
5. **No NATS in request code.** An import-linter contract forbids `nats` in `app/`, except the
   read-only readiness probes. Stream setup is code (`workers/bus.py`), run at worker start.
6. **Worker health.** Workers write heartbeats to a NATS KV bucket; `/ready` reports them as
   informational checks that never make the API unready.
7. **Retention.** Outbox rows are purged by the relay 72 h after publishing (periodic task inside
   the relay until Temporal schedules exist).

## Consequences

- **Positive:** At-least-once delivery with exactly-once effect for database consumers; the relay
  cannot see business data; failures are visible (DLQ, heartbeats, metrics) and replayable.
- **Negative:** Global ordering is not guaranteed across several relays or retries; consumers must
  use `aggregate_version`. `processed_events` grows until a retention job exists (follow-up).
  A relay down longer than the duplicate window plus a crash between publish and mark can deliver
  a duplicate into the stream; consumers are idempotent, so the effect is still once.

## Notes

Details and how-tos: `docs/architecture/events.md`.
