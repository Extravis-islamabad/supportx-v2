### 2026-10-24 — WP-020-FIX: the WP-020 QA findings

- **Scope:** every finding of the exploratory QA report (Desktop/qa-wp020/QA-REPORT.md):
  BUG-01..18, C1..C7 and the product owner's review of the create form. Each has a test named
  after its ID that failed first: backend `tests/db/test_incidents_api.py` (BUG-03, BUG-05,
  form defaults), `tests/db/test_auth_bff.py` (BUG-04), `tests/test_richtext.py` (C4); Vitest
  `apps/console/src/pages/incidents/qa-fixes.test.tsx`, `packages/ui/src/qa-fixes.test.tsx`,
  `packages/ui/src/units.test.ts` (C2), `packages/realtime/src/realtime.test.tsx` (BUG-13);
  Playwright `e2e/tests/qa-fixes.spec.ts` (BUG-04, BUG-07, BUG-13, BUG-16, C1, C2, C3, C5).
- **Server:** history pages name people in changed values; `users.ui_locale` (BUG-04);
  start work takes an unassigned incident first, disabled with `cannot_take` when the user
  may not take it; refused links keep their text; incident settings `default_impact` /
  `default_urgency`. Migration 0013 (expand only). D-075.
- **Screens:** Assign dialog built on open, re-reads the record, follows live changes for
  untouched fields; one request per write (single flight); clear Cancel wording; errors under
  their field; text in its own direction (`bdi`, `dir=auto`); subject 500 with a counter;
  inline edit focus, Enter, Escape; "Keep my changes" saves on top; header collapses below md;
  no body margin and a stable scrollbar gutter; fonts per language (Arabic Naskh, Urdu Nastaliq
  with taller lines); option names are labels (C7 check); required marks; tenant defaults in the
  form; scroll to top on navigation; presence initials and disconnect on page hide.
- **Tests:** backend 881 passed; frontend unit tests all green (console 68, ui 38, realtime 13,
  others); Playwright full suite 33/33 (incl. the QA spec, 6). `make check` green.
- **Not reproduced automatically:** the BUG-13 ghost does not appear in headless Chromium even
  without the fix (its WebSocket closes cleanly on reload); the unit tests prove the fix
  (explicit disconnect on page hide; initials from the name).
- **Dev data:** dev database migrated 0012 → 0013 (adds columns; existing incident settings got
  the defaults team / medium). QA data as listed under Open.
