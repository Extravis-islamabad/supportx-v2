# ADR-020: API conventions: idempotency in PostgreSQL, signed keyset cursors, Valkey rate limits

- **Status:** Accepted
- **Date:** 2026-10-23
- **Source:** architecture.md §6.5, §10; WP-008
- **Owner:** Haider (Product Owner)

## Context

WP-008 planned Idempotency-Key handling "Valkey-backed". Storing the replay record in Valkey cannot
be atomic with the business write in PostgreSQL: a crash between the database commit and the
Valkey write lets a retry create a duplicate, and a Valkey write before the commit replays a
response for a change that rolled back. Cursor pagination and rate limiting also needed a design.

## Decision

1. **Idempotency records live in PostgreSQL** (`idempotency_keys`, tenant-scoped with RLS, primary
   key tenant + user + key, 24 h TTL). The key is claimed and the response stored inside the
   request's own transaction, so record and business change commit or roll back together, and a
   concurrent duplicate waits on the primary key and then replays the stored response.
2. **Cursors are keyset positions signed with HMAC-SHA256**, bound to endpoint, tenant, user, sort
   and filter fingerprint. The key comes from `SUPPORTX_CURSOR_SECRET`, else is derived from the
   session secret. No OFFSET pagination.
3. **Rate limits use Valkey** fixed windows, per user and per tenant per route group, budgets from
   a `RateLimitPolicyProvider` (settings now, licence entitlements via WP-009 later). If Valkey is
   unavailable the request is allowed (fail open) and a warning is logged.

## Consequences

- **Positive:** exactly-once creates even under crashes and concurrent retries; cursors cannot be
  forged or replayed across tenants; rate limits cost one Valkey round trip.
- **Negative:** idempotency adds one indexed row per keyed POST (expired rows need a cleanup job,
  recorded as a follow-up); fixed windows allow a burst of up to 2x the limit at a boundary;
  failing open means no rate limiting while Valkey is down.
