### 2026-10-24 — WP-018 session 1 (backend core of the audit log)

- **Built:** see the WP-018 entry above. Decisions D-076 (product owner answers to the plan),
  ADR-027. The chain is written by the migrator-owned definer function `audit_seal()` instead of
  a separate `supportx_audit` login role (stronger, one less credential).
- **Core changes:** `app/core/errors.py` error observers (`register_error_observer`),
  `ModuleSpec.schedules` + `app/shared/schedules.py`, `recorded_change_ids()` in field history,
  `SUPPORTX_AUDIT_*` and `SUPPORTX_WORKER_SCHEDULES_ENABLED` settings, Auditor system role
  (`identity_access`), `migrations/env.py` skips audit partitions.
- **Not audited yet, with reason:** edits of closed incidents (closed records are read-only, 409
  `record_closed`) and due-date overrides (come with SLA, WP-025); their actions are catalogued.
- **Tests:** backend 876 → all green plus 25 domain, 20 API, 5 job, 4 route-table and 1 BFF audit
  tests. Lane A has not merged a migration since 0012, so ours stays 0013 for now.
