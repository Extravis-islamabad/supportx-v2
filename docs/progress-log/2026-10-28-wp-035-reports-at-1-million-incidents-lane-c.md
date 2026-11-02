### 2026-10-28 — WP-035: reports at 1 million incidents (lane C)
- `report-scale.yml` (nightly 03:41 UTC and manual, rows as input) runs
  `tests/db/test_reports_scale.py`: 1M incidents generated inside PostgreSQL, every built-in
  report plus widget totals, admin and group-scoped technician, strict 2 s target; the
  technician never sees another group's numbers. Timings in the job summary and a 90-day artifact.
- First run (40644943080, 1,000,000 incidents, strict 2 s): all 49 timed queries pass. Slowest
  median 0.73 s (admin, received per month), "open by" reports 0.33-0.37 s, widget totals 0.23 s,
  30-day reports 0.02-0.07 s, drill-down list page 0.008 s; load 118 s.
