# Events: outbox, relay, JetStream and consumers

WP-007. Rules: CLAUDE.md rule b (transactional outbox), architecture.md §4.2, §6.5, §8, ADR-003,
ADR-019. Code: `backend/app/shared/events/` (envelope, registry, outbox writer, consumer
declarations), `backend/workers/` (relay, consumer worker, CLI).

## How an event travels

1. **A service changes data and records an event in the same transaction.**
   `record_event(session, UserLoggedIn(...), aggregate_id=user_id)` inserts one row into
   `outbox_events`. If the transaction rolls back, the row is gone too: no event is ever sent for
   a change that did not happen, and none is lost for a change that did.
2. **The commit wakes the relay.** A trigger on `outbox_events` runs `NOTIFY supportx_outbox`.
   PostgreSQL delivers that notification only when the transaction commits.
3. **The relay publishes.** It takes up to 200 unpublished rows (`FOR UPDATE SKIP LOCKED`),
   publishes each to NATS JetStream on `events.<tenant_id>.<module>.<entity>.<action>` with the
   header `Nats-Msg-Id = event_id`, waits for every acknowledgement, then sets `published_at` on
   exactly those rows and commits. If no notification arrives it still looks every 2 seconds.
4. **JetStream stores it** in the `SUPPORTX_EVENTS` stream (kept 7 days). A second message with an
   event ID it has already seen in the last 5 minutes is dropped.
5. **Consumers react independently.** Each durable consumer (declared by a module) receives the
   event, runs its handler in the event's tenant, and acknowledges. Realtime fan-out (WP-011),
   search indexing, workflows and analytics will all be consumers like this.
6. **Housekeeping.** Published outbox rows are deleted by the relay after 72 hours
   (`SUPPORTX_OUTBOX_RETENTION_HOURS`). Unpublished rows are never deleted: the database refuses.
   In the same pass (WP-012) the relay deletes expired idempotency keys and consumer records
   (`processed_events`) older than 30 days (`SUPPORTX_PROCESSED_EVENTS_RETENTION_DAYS`, at least
   7: the stream keeps events 7 days, so a redelivery could still need a younger record). The
   relay's RLS policies on those two tables show it only rows past those limits, so it cannot
   remove anything younger whatever the setting says.

Measured on the dev stack (1,000 events, one transaction each): commit → consumer received
p50 0.9 ms, p95 1.3 ms, p99 2.4 ms. One relay published 10,000 queued events at about 20,900
events/s. CI prints its own numbers in the backend job summary.

## The envelope

Every event is this JSON (`EventEnvelope`), stored in the outbox and published byte for byte:

| Field | Meaning |
|---|---|
| `event_id` | UUIDv7, also the NATS message ID used for deduplication |
| `event_type` | `<module>.<entity>.<action>`, e.g. `identity_access.user.logged_in` |
| `schema_version` | version of the payload schema (starts at 1) |
| `tenant_id` | the tenant; the session's tenant, enforced by RLS |
| `actor` | `{"type": "user", "id": "<user id>"}` or `{"type": "system", "id": "<component>"}` |
| `occurred_at` | UTC time of the change |
| `aggregate_type`, `aggregate_id`, `aggregate_version` | what changed, and its version after the change |
| `correlation_id` | the API request ID (`X-Request-ID`) |
| `causation_id` | the event that caused this one, when a consumer emits it |
| `traceparent` | W3C trace context, so one trace links the click to every consumer |
| `payload` | the event's own fields: IDs, codes, changed field names. Never personal data. |

## Subjects and streams

```
events.<tenant_id>.<module>.<entity>.<action>              all domain events   (SUPPORTX_EVENTS)
replay.<consumer>.<tenant_id>.<module>.<entity>.<action>   a replayed dead letter, for one consumer
dlq.<consumer>.<tenant_id>.<module>.<entity>.<action>      dead letters        (SUPPORTX_DLQ, 30 days)
```

Why the tenant comes right after `events`: one wildcard selects a whole tenant
(`events.<tenant_id>.>`). The realtime fan-out in WP-011 filters on it and maps events to that
tenant's Centrifugo channels without opening payloads, and NATS permissions can later be written
per tenant. The event type follows as three tokens, so consumers can filter by module
(`events.*.work_items.>`) or exact event (`events.*.work_items.ticket.assigned`).

Streams and the heartbeat bucket are created or updated by code (`workers/bus.py`) every time a
worker starts. Nobody creates them by hand.

## Database roles

| Role | Can read | Can write | Cannot |
|---|---|---|---|
| `supportx_app` (API, consumers) | its own tenant's business rows; its tenant's `processed_events` | business rows of its tenant; INSERT into `outbox_events` for its tenant only; INSERT `processed_events` | read, update or delete any outbox row (even its own); write another tenant's rows; TRUNCATE; bypass RLS |
| `supportx_relay` (outbox relay) | every tenant's `outbox_events` rows; expired `idempotency_keys`; `processed_events` older than 7 days | `published_at`, `publish_attempts`, `last_error`, `updated_at` on outbox rows; DELETE of *published* outbox rows, of expired idempotency keys and of consumer records older than 7 days | read or write any other table (`users`, `tenants`, business tables, ...); see or delete younger keys or consumer records; insert or alter events; delete unpublished events; bypass RLS |
| `supportx_migrator` | (owner, RLS forced) | DDL via migrations | runtime use |

**How the relay reads across tenants safely.** It does *not* have `BYPASSRLS`. Instead the
migration adds three RLS policies on `outbox_events` that apply `TO supportx_relay` only: SELECT
and UPDATE with `USING (true)`, and DELETE with `USING (published_at IS NOT NULL)`. Combined with
table and column grants on that one table and no grants anywhere else, the role can see every
tenant's events and nothing else. `BYPASSRLS` would have been simpler but would silently cover
any table the role was ever granted by mistake. `make db-guard` (and CI) fails if the relay gets
any other right, or if a policy without a tenant check applies to anyone but the relay. Tests in
`backend/tests/events/test_outbox.py` prove the relay cannot read `users` or any business table.

The relay connects straight to PostgreSQL, not through PgBouncer: `LISTEN` needs a real session.

## Reliability

| What fails | What happens |
|---|---|
| Transaction rolls back | Outbox row rolls back too; nothing is published. |
| Relay crashes after JetStream acknowledged but before marking rows | Rows are still unpublished; the next relay publishes them again; JetStream answers "duplicate" (same `Nats-Msg-Id`) and stores nothing new. |
| NATS down, or a publish fails | Row stays unpublished, `publish_attempts` and `last_error` are updated, it is retried on the next pass. |
| Two or more relays | `SKIP LOCKED` gives each a different batch; tested with 2 relays × 2,000 events: every event once, none lost. |
| Consumer crashes mid-handler | Its transaction (claim + effects) rolls back; JetStream redelivers after `ack_wait` (30 s); the handler runs again. |
| Consumer crashes after commit, before ack | Redelivery finds the claim in `processed_events` and is acknowledged without running the handler. |
| Handler keeps failing | Retried with exponential backoff (1 s, 2 s, 4 s ... max 60 s); after 5 attempts the message goes to the DLQ with the error. |
| Message is not an event at all | Straight to the DLQ (retrying cannot help). |

### Ordering (honestly)

- **Ordered:** with one relay, events reach the stream in event-ID order, and changes to the same
  aggregate are in commit order (the second transaction waits for the first's row lock, so it
  creates its event later). One consumer handles its messages one at a time in stream order.
- **Not ordered:** with several relays, batches interleave. A retried message is redelivered after
  its backoff, so later messages may be handled first. Events of different aggregates, or from API
  pods with skewed clocks, have no guaranteed order. Use `aggregate_version` to detect and ignore
  stale events instead of assuming order.

## Adding a new event

1. In your module's `events.py`:
   ```python
   class TicketAssigned(DomainEvent):
       event_type: ClassVar[str] = "work_items.ticket.assigned"   # <module>.<entity>.<action>, past tense
       schema_version: ClassVar[int] = 1
       aggregate_type: ClassVar[str] = "ticket"

       ticket_id: uuid.UUID
       assignee_id: uuid.UUID | None
   ```
2. List it in the module's `ModuleSpec(events=[...])`. Unlisted events cannot be written
   (`UnregisteredEventError`).
3. Record it in the service, inside the transaction that makes the change:
   `await record_event(session, TicketAssigned(...), aggregate_id=ticket.id, aggregate_version=ticket.version)`.
4. Add labels `event_type.work_items.ticket.assigned` in `frontend/packages/labels` (en, ar).
5. `make events-schemas` and commit `docs/architecture/event-schemas.json`.

### Versioning

Within one `schema_version` only additive changes are allowed: new optional fields, new event
types, wording. Removing or retyping a field, adding a required field, or changing whether a field
is required is breaking: create a new class with the same `event_type` and `schema_version = 2`,
publish that, and keep v1 registered while consumers still read it. Published versions are never
deleted. `make events-check` (part of `make lint`) and CI compare against the target branch's
`event-schemas.json` and fail on a breaking change.

## Writing a consumer

```python
async def _index_ticket(event: EventEnvelope, session: AsyncSession | None) -> None:
    ticket = active_registry().parse(event)            # typed payload
    ...                                                # database work uses `session`

module = ModuleSpec(
    name="search",
    consumers=[ConsumerSpec(
        name="search__index_tickets",                  # <module>__<purpose>, unique
        event_types=("work_items.ticket.assigned",),   # exact types, or "work_items.>", or ">"
        handler=_index_ticket,
    )],
)
```

`make worker-consumers` creates the durable JetStream consumer and runs it.

### Idempotency rules

- A transactional consumer (the default) gets a session in the event's tenant
  (`SET LOCAL app.tenant_id`). The worker writes `(consumer, event_id)` to `processed_events` in
  that same transaction before calling you, so your database effects happen exactly once.
- Effects outside the database (email, HTTP calls) are not covered: make them idempotent yourself,
  for example with the event ID as an idempotency key.
- Never assume order; compare `aggregate_version`.
- Raise to retry. Do not catch and swallow errors you cannot handle.
- `transactional=False` is for handlers with no database work (logging). They get no session and
  no idempotency record.

## Debugging

| Command | Shows |
|---|---|
| `make events-tail` | Every new event, one line each (`since=10m`, `since=all`, `tenant=<id>`, `type=identity_access.>`) |
| `make worker-consumers` | In dev, the `system__dev_event_logger` consumer logs every event it receives |
| `make events-stats` | Stream sizes, dead-letter count, each live worker's heartbeat and counters |
| `make dlq-list` | Dead letters: consumer, event, attempts, error (`consumer=<name>` to filter) |
| `make dlq-replay seq=<n>` | Send one dead letter back to its consumer (`all=1 [consumer=<name>]` for many) |
| `GET /api/v1/ready` | `outbox_relay` and `event_consumers` checks from heartbeats; listed under `degraded` when down, never a 503 |

A replay goes to `replay.<consumer>...`, which only that consumer receives, and is removed from
the DLQ once JetStream accepts it. Fix the bug first, then replay.

Outbox rows stuck unpublished show `last_error`:
`psql ... -c "SELECT id, event_type, publish_attempts, last_error FROM outbox_events WHERE published_at IS NULL"`
(as the migrator or superuser).

## Metrics

OpenTelemetry instruments (Prometheus names after export):
`supportx_outbox_oldest_unpublished_age_seconds`, `supportx_relay_published_events_total`,
`supportx_relay_publish_failures_total`, `supportx_consumer_lag`, `supportx_dlq_messages`,
`supportx_consumer_processed_events_total`. `SUPPORTX_METRICS_EXPORTER=console` prints them; the
Prometheus scrape endpoint comes with WP-014. The same numbers are in the heartbeats.
