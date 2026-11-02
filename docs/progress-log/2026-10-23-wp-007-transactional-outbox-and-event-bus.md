### 2026-10-23 — WP-007 transactional outbox and event bus
- `app/shared/events`: `EventEnvelope` (UUIDv7 event_id, type, schema_version, tenant, actor,
  occurred_at, aggregate type/id/version, correlation/causation IDs, traceparent, payload);
  `DomainEvent` classes in each module's `events.py`, listed in `ModuleSpec(events=…)`;
  `EventRegistry` enforces `<module>.<entity>.<action>` and unique (type, version); unregistered
  events cannot be written. `record_event()` inserts into `outbox_events` in the caller's
  transaction. `ModuleSpec.event_handlers` replaced by `events` + `consumers`.
- Migration 0003: `outbox_events` (RLS; app role INSERT only), `processed_events` (RLS), NOTIFY
  trigger, relay policies `TO supportx_relay`. New role `supportx_relay` in `tooling/sql`
  (NOBYPASSRLS; outbox only). RLS guard checks relay grants (table + column) and allowlisted
  cross-tenant policies. `make db-bootstrap` (run by `db-migrate`) adds missing roles to an
  existing dev volume. ADR-019 records the conventions; ADR-018 note (dev logger lives in system).
- Workers: `outbox_relay` (LISTEN/NOTIFY + poll, SKIP LOCKED batches, Nats-Msg-Id dedupe, mark
  after ack, 72 h purge of published rows), `consumers` (durable pull consumers from modules,
  processed_events claim in the handler transaction, tenant SET LOCAL, exponential backoff, DLQ
  after N attempts, per-consumer replay subject), `bus.py` (streams + heartbeat KV as code),
  heartbeats → `/ready` informational checks (`outbox_relay`, `event_consumers`, `degraded`),
  OpenTelemetry metrics. Import-linter contract: no `nats` in `app/` except readiness probes.
- identity_access events: user.provisioned, user.updated (changed field names), user.logged_in,
  user.logged_out, session.tenant_switched (target tenant only). Dev-only
  `system__dev_event_logger` consumer. Event-type labels en/ar + CI test.
- Schemas exported to `docs/architecture/event-schemas.json`; `make events-check` (lint) and a CI
  step against the target branch fail on breaking changes.
- Make: worker-relay, worker-consumers, events-tail, events-stats, dlq-list, dlq-replay,
  events-schemas, events-check, db-bootstrap. Docs: `docs/architecture/events.md`, dev-setup.
- Tests: 362 backend (coverage 97%): atomicity, crash-after-publish dedupe, consumer crash
  before commit and before ack, poison → DLQ → replay, 2 parallel relays × 2,000 events, RLS for
  app and relay roles, worker entry points. Dev stack: latency p50 0.9 / p95 1.3 / p99 2.4 ms
  (1,000 events), relay ~20,900 events/s (10,000). CI starts NATS JetStream; NATS tests required.
  Verified live: real Keycloak login/logout → events in events-tail and the consumer log.
- Follow-ups: retention job for `processed_events`; Prometheus scrape endpoint (WP-014; exporter
  dependency needs approval); move the outbox purge to a Temporal schedule once Temporal workers
  exist; audit-trail consumer for auth events (audit module).
