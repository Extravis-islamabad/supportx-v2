### 2026-10-28 — WP-036: live dashboards, sessions 1-2 (lane C)
- See WP-036 above. Tests: backend `tests/db/test_dashboards_api.py` (10, incl. RLS of three
  tables, built-ins run for every viewer, homes per role, sharing, copy, If-Match, events);
  console `pages/dashboards/dashboards.test.tsx` (9: rules, home, picker, filter bar, edit mode,
  un-shared, Arabic); e2e `dashboards.spec.ts` (live in two browsers within 2 s, technician home,
  shared dashboard reaches the picker, Arabic, axe). Shared: the report viewer's result view and
  live refresh are reused (`Results`, `useLiveReportRefresh`); `reports.view` now also shows the
  Dashboards entry (admin.test expectation updated).
