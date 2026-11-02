### 2026-10-24 — WP-020 session 1 (backend): work item engine + incidents API

- **Stopped at:** backend complete and committed on `feat/wp-020-work-items-incidents` (pushed, no
  PR yet). Next: session 2 (frontend + the two fixes), then the PR. Nothing in the frontend uses the
  new API yet; no screen changed.
- **Built:** `backend/app/modules/work_items` (domain: lifecycle, classification, types; infra:
  tables; service: catalogue seeding, access/D-052, work items, settings, realtime; api: router
  factory), `app/shared/richtext.py` (nh3), shared changes (history sources/kinds/automation_ref and
  time-ordered paging; type-keyed display counters; `ResourceType.group_scope_extra`;
  `LiveList(unassigned_by_site=…)`; `list_query(extra_parameters=…)`; `ModuleSpec.router_features`),
  migrations 0011 (history, counters) and 0012 (work items), import-linter layers contract.
- **Tests:** 876 passed, coverage 94.8 %; `tests/db/test_incidents_api.py` (30 tests incl. D-052
  three rules + 404, D-053, realtime audiences, 100k-row perf), `work_items/tests/test_domain.py`
  (24), `tests/test_richtext.py` (4). ruff, mypy strict, import-linter, OpenAPI diff (no breaking
  change), event schema check green. Frontend lint/typecheck/unit tests green (no UI changes).
- **Decisions:** D-051..D-056 recorded; ADR-026; CLAUDE.md §3 (nh3, Tiptap, aioboto3 later).
- **Deviations from the plan:** no separate `work_item_lifecycles` table (one life cycle per type
  until the designer); the record channel is `t:{tenant}:wi:{id}` as planned; the reserved
  `requests.*` permissions stay (relabelled in session 2) because many policy tests use them;
  WI-020 AC3 (purge after retention) deferred until the audit log (WP-018).
- **Decision IDs:** main already held D-039..D-050 (parity answers, PR #34), so this session's
  rows were renumbered D-051..D-056 and main was merged in; overlapping points cite main's D-040
  (Tiptap timing), D-041 (editable defaults) and D-045 (per-type counters).
- **Dev data:** none touched. Migrations ran only on throwaway `supportx_test_*` databases; the dev
  database is still at 0010 (run `make db-migrate` to apply 0011–0012; expand-only).
