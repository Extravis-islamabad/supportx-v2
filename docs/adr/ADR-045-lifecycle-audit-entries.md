# ADR-045: Record lifecycle in the audit log — one entry per save through a history sink, its events inside the entry hash

- **Status:** Proposed (WP-064 S1)
- **Date:** 2026-11-10
- **Source:** WP-064; D-150; ADR-027; architecture.md §7.4; coordinator 2026-11-10 (the route
  entry rule, the migration number 0122, no btree_gin, events inside the hash)
- **Owner:** Haider (Product Owner)

## Context

D-150 puts the record lifecycle (create, status, assignment, priority, SLA, resolve, close,
reopen, approvals, links, trash, restore, attachments, permission-relevant fields) into the
tamper-evident audit log of ADR-027, with one entry per save listing every event that save
stands for. Saves happen in every module, through `app/shared/history.record_changes`, and some
routes already write their own entry with `audited(...)` for the same save (`incident.deleted`,
`asset.moved`, `service_request.approval_decided` ...).

## Decision

1. **One hook, a port.** `app/shared/history` defines an `AuditSink` port, and `record_changes`
   calls it for record types it handles, inside the save's transaction and after its history
   rows. The audit module implements and registers it when imported (as identity registers the
   people-names resolver), so the API and every worker that loads the modules have it. Modules
   add no calls (rule e holds: nothing imports audit).
2. **The event table is pure domain code** (`audit/domain/lifecycle.py`): per record type, the
   kinds of save and the field → event map. Each code is `<type>.<event>` in the audit
   catalogue with en/ar/ur labels. A save matching nothing is `<type>.updated`.
3. **One entry per save, merged with the route's.** Inside an `audited()` route, the route marks
   the session with its action before the endpoint runs. Saves made there wait, and when the
   endpoint finishes (still in the transaction) the route writes ONE entry per save:
   - its action is the route's code, and its `events` list the route's code first, then the
     save's lifecycle events;
   - the route's details and reason are carried, the reason outside the hash as before;
   - the route writes no second entry.
   Outside a route (workers, automation) the entry is written at once, from the worker. Refusals,
   `bulk_started`, reads and route actions without a save write as before. Both or neither are
   written, never one without the other: it is one transaction.
4. **`events` is a new column inside the entry hash** (migration 0122, `text[]`, a plain GIN
   index; btree_gin is not used, as a new extension can need a superuser). The canonical
   content includes `events` only when it is set. Every entry written before 0122, and every
   non-save entry, has `events` NULL and hashes byte for byte as before (ADR-027 unchanged for
   them). Editing or removing a save's events changes its entry hash, which the verifier and
   the offline export verifier catch. Exports carry `events` inside the exported entry, so
   `tools/verify_export.py` needs no change.
5. **Finding entries.** The shared filter DSL gains `also_in` for an ENUM field: the audit
   `action` filter matches `action = X OR events @> {X}` (`ne`/`not_in`: neither). The same
   rule applies to export filters. So every filter, saved search, export or report that found a
   route's code finds the save entry listing it.

## Consequences

- One INSERT per save more (plus personal rows only when a reason is given), in the save's own
  transaction. The sealer's throughput becomes a precondition for the L tier (WP-064 S3).
- `record_changes` learns the subtype of shared record types (`work_item` → `incident`,
  `problem` ...) through the `subtype` keyword, or a resolver the owning module registers.
- Before/after values stay in `field_changes`. A later session (S2) adds the change set's
  fingerprint, per-subject salts and erasure.
