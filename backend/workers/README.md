# workers

Separate deployables (ADR-001) that share the `app` code. Since WP-007
(docs/architecture/events.md):

| Package | Run | Does |
|---|---|---|
| `outbox_relay/` | `make worker-relay` | Publishes committed outbox rows to NATS JetStream (role `supportx_relay`, direct to PostgreSQL), purges old published rows. |
| `consumers/` | `make worker-consumers` | Runs every module-declared `ConsumerSpec` as a durable pull consumer: idempotency, retries, dead letters. |
| `realtime_fanout/` | `make worker-fanout` | Routes events to Centrifugo channels (module `RealtimeRoute`s), merges bursts, rate-limits per tenant, cuts connections whose access changed (WP-011, docs/architecture/realtime.md). |
| `custom_field_indexes/` | `make worker-indexes` | Builds the custom field indexes admins ask for (D-088), CREATE INDEX CONCURRENTLY as `supportx_migrator`, one at a time (advisory lock), with live progress on the field. The migrate Job runs one pass as a fallback. |
| `events_cli.py` | `make events-tail`, `events-stats`, `dlq-list`, `dlq-replay` | Operator commands. |
| `bus.py` | (startup) | Creates/updates the streams and the heartbeat bucket. |

Only code here may use the NATS client (import-linter contract). Temporal workers arrive later.
