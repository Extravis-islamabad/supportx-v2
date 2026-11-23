### 2026-11-12 — Asset import step B: one INSERT per table per batch (lane B)

- **Why:** after Step A (#439), a created asset still cost about 7.4 statements, all INSERTs
  (outbox ×2, field_changes, audit entry and queue, valuation, the asset). At 20,000 rows the
  dry run was 219.6 s against its 120 s target.
- **What:** `app/shared/db/deferred.py`: `async with deferred_writes(session)`, opened only by the
  import's batch savepoint. The writers (record_event, record_changes, audit `record`, assets
  valuations) hand their rows to the session's buffer, built exactly as today. At the end of the
  block it writes one multi-row INSERT per table (chunked under 32,767 parameters), FK order,
  outbox last. A dry run or an exception discards it. A nested savepoint's rollback cuts the
  buffer back to its mark.
- **Guard:** while rows wait, a SELECT on a buffered table, or a flush of those models that went
  around the buffer, raises in production too.
- **Order kept:** the relay reads the outbox ORDER BY id (UUIDv7 at the call); audit_seal()
  reads the queue by (occurred_at, entry_id), both set at the call. No entry hash reads the
  database at the call.
- **Tests:** test_deferred_writes.py checks that a batch writes what a row-by-row import writes
  (history, events, audit, valuations), and that the dry run equals the real run. Also covered:
  the savepoint truncate, the guard (read and bypass), chunking, one lifecycle entry per row,
  and a 150-row batch whose chain seals and verifies. One existing test sets BATCH_SECONDS 0.5,
  because 600 rows now fit in one transaction.
- **Also:** lane C's notes on #439: the comment on `hold` about a raw ROLLBACK TO SAVEPOINT, and
  the assets memo vs `transaction_memo` cross-reference.
