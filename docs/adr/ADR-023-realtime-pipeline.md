# ADR-023: Realtime pipeline: per-channel tokens, module-declared routes, windowed fan-out

- **Status:** Accepted
- **Date:** 2026-10-23
- **Source:** architecture.md §8; ADR-005; WP-011
- **Owner:** Haider (Product Owner)

## Context

ADR-005 chose Centrifugo with API-issued tokens and a fan-out consumer. WP-011 had to decide how
channels are authorised, how events become screen updates without leaking data, how access
changes reach open connections, and how bursts stay cheap.

## Decision

1. **Channel names are exactly §8.1** (`t:{tenant}:{kind}[:{key}]`). Centrifugo's namespace
   separator is moved to `|`, so every `t:` channel uses one set of options (history 100 / 300 s,
   forced recovery, presence); join/leave messages are switched on per subscription by the token
   (record channels only). Two platform kinds are added: `broadcast` (tenant-wide notices) and
   `queue` list channels split by audience (everyone, `.site.{id}`, `.group.{id}`, `.signal`).
2. **Tokens.** `POST /api/v1/realtime/connection-token` (signed-in user; `sub` = `{tenant}:{user}`,
   15 min) and `POST /api/v1/realtime/subscription-token` (one channel, 5 min) signed with the
   key Centrifugo verifies (HS256, audience and issuer checked). A subscription token is signed
   only after the owning module's `ChannelSpec.authorize` (the WP-016 policy layer) allows it.
3. **Modules declare realtime** in `ModuleSpec`: `channels` (who may join) and `realtime`
   (`RealtimeRoute`: event types → publications + users whose access changed). Payloads carry
   type, IDs, changed field names, version and actor ID only; rule-bound audiences get the
   ID-free `.signal` channel.
4. **Fan-out worker** (`workers/realtime_fanout`): a WP-007 durable consumer processed in windows
   (`realtime_coalesce_ms`, 250 ms): list messages for the same channel merge into one, record
   messages merge fields; a per-tenant token bucket bounds publications; publishes go through
   Centrifugo's batch API with idempotency keys derived from the event IDs; new consumers start at
   the stream end. Routes invalidate the caches their message makes stale before publishing.
5. **Revocation is a disconnect** with code 4000 (reconnect) for every user whose access changed
   (roles, role edits, memberships, status, plan); the client reconnects with fresh tokens and is
   refused channels it lost. Logout and tenant switch cut the old connection from the BFF.
6. **Client:** centrifuge-js (D-030), WebSocket → HTTP streaming → SSE, then timed polling after
   10 s without a connection; unrecoverable gaps become a "refresh" message; the TanStack Query
   cache is refreshed per message (only the named entries).

## Consequences

- **Positive:** one declaration per module makes its screens live; no data in messages; access
  changes take effect on open connections within about 0.3 s; bursts cost one message per list.
- **Negative:** messages wait up to one window (≈250 ms) to be merged; rate-limited and in-flight
  messages live in the worker's memory (a crash loses at most UI hints, which screens reconcile on
  reconnect); a role change briefly reconnects the affected users.

## Notes

Measured on the dev stack (WP-011): commit → other browser p95 275 ms (200 changes); 2,000
connections × 200 changes: p95 353 ms, no delivery lost.
