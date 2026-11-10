### 2026-11-10 — WP-064 session 1: every save of a record is one audit entry (lane B)

- **Hook:**
  - `app/shared/history` defines an `AuditSink` port; the audit module registers `LifecycleSink`
    at import, so modules add no calls.
  - Inside an `audited()` route, the request's saves wait. The route then writes one entry per
    record, led by its own code, with its details and reason, and no second entry.
  - Outside a route (workers, automation), the entry is written at once.
- **Chain format (ADR-045):**
  - `audit_entries.events` (migration 0122, `text[]` with a plain GIN index; no btree_gin) is
    hashed when set.
  - Older and non-save entries hash byte for byte as before.
  - Exports carry it in the entry, so the offline verifier needs no change.
- **Finding entries:** the filter DSL's `also_in`; the action filter and export filters match a
  code listed in a save's events.
- **Event tables** (`audit/domain/lifecycle.py`, pure):
  - assets: moved, relocated, product changed, trash and restore;
  - incidents, service requests, problems, changes and releases, from lane A's review:
    - statuses by category: work_items adds `status_category` to the sink's copy only, and a
      test shows it never reaches history;
    - due dates unless the SLA engine moved them;
    - SLA paused, resumed and breached;
    - access changes: assignment, followers, note visibility, stage roles;
    - links;
    - stage, risk and approval events for the staged types.
- **Subtype:** work_items registers a resolver (identity map first, then one read under RLS;
  None, never an error) instead of a subtype at about 30 call sites (lane A).
- **Labels:** 111 new codes in en/ar/ur, made from per-event templates.
- **Tests:**
  - unit: the table, the hash;
  - DB: one entry for create, delete and restore (assets and incidents), filters, worker saves,
    refused saves, the history guard, the resolver;
  - 249 pass across the work-item, portal, asset and audit suites.
- **Coordinator's conditions (2026-11-10)** are all covered: finders still find route codes;
  outcome, actor and reason are carried; one transaction; non-save actions write as before.
- **Files** stay the files module's `file.uploaded` / `file.deleted` entries (they name the
  owner record). S4 shows them in a record's list.
