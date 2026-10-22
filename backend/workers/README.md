# workers

Separate deployables (ADR-001) that share the `app` code. Since WP-007
(docs/architecture/events.md):

| Package | Run | Does |
|---|---|---|
| `outbox_relay/` | `make worker-relay` | Publishes committed outbox rows to NATS JetStream (role `supportx_relay`, direct to PostgreSQL), purges old published rows. |
| `consumers/` | `make worker-consumers` | Runs every module-declared `ConsumerSpec` as a durable pull consumer: idempotency, retries, dead letters. |
| `events_cli.py` | `make events-tail`, `events-stats`, `dlq-list`, `dlq-replay` | Operator commands. |
| `bus.py` | (startup) | Creates/updates the streams and the heartbeat bucket. |

Only code here may use the NATS client (import-linter contract). Temporal workers arrive later.
