### 2026-10-28 — WP-035-FIX: the reports QA findings (lane C)
- Every finding of ~/Desktop/qa-wp035/QA-REPORT.md fixed at its cause, each with a test named
  after its ID (`backend/tests/test_qa_wp035.py`, `packages/charts/src/qa-wp035.test.ts`,
  `reports.test.tsx` "QA WP-035", `test_report_exports.py::test_bug_01_...`):
  - BUG-01: one rule names every field (the record's own label, else the report's), 12 report
    field labels added, custom field headers from metadata in the reader's language; a test
    proves no export header reads "Unknown value".
  - BUG-02, BUG-04, BUG-05 (direction, systemic): WeasyPrint draws SVG text unshaped, so PDF
    charts keep shapes and digits in SVG and every name in HTML with an explicit direction;
    the server's `label()` isolates (FSI/PDI) every filled value in Arabic and Urdu (exports,
    report mails, notifications); PDF titles, headers and cells isolated; the console's chart
    states `dir`; `useIsolate`, `useJoinParts` and `useListFormat` (Intl.ListFormat, "أو" for
    "is one of") on the report screens; filter words name groups, sites and people, never ids.
  - BUG-03: RTL mirroring no longer adds a legend (one measure has none); doughnut slices clear
    of the legend. BUG-06: names shortened in the middle (graphemes), whole in tooltips and
    tables. BUG-07: every option shows its whole label (one global rule; lists keep the box's
    width so long lists stay virtual and accessible). BUG-08: "Changed from <built-in>" with
    Reset and Save as my report.
  - ENV-01: `make worker-consumers-pdf` (the dev worker with PDFs), the glib path for
    WeasyPrint on macOS, a dev-setup note.
- WP-029-FIX lessons (D-105) on the report screens: refusals once at the form (FormProblem),
  failures as the error toast with the reference; a refused report run is a notice, a failed
  one the toast; the folder dialog no longer calls every failure a taken name.
- Checks: backend 1600 passed (+ the 4 logging tests separately), ruff, mypy, import contracts;
  frontend eslint, typecheck, prettier, every package's tests (console 273).
