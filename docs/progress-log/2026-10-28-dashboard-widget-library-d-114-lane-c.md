### 2026-10-28 — Dashboard widget library (D-114, lane C)

- Product owner request after using the dashboards: "Add widget" opens a searchable catalogue
  by module and section (43 curated widgets plus every built-in report); SLA and approval widgets
  appear under "coming later" with the package that brings them.
- Engine: flow report (created, resolved, backlog per day/week/month), `@my_groups` and `@me`
  resolved on the server for every run, records widgets (short lists through the entity's own
  list API), four new measures (overdue, due today, awaiting first response, reopened).
- Built-in Service desk (17 widgets) and My work (9) are placed from the catalogue.
- Tests: 8 DB tests (flow numbers per day and per viewer, `@my_groups`, records checks, every
  catalogue widget runs in a technician's scope), 5 Vitest, one e2e journey; label tests cover
  every widget, section and measure in en/ar/ur.
- Backlog per bucket uses each record's own timestamps (no history replay); a cancellation
  counts from its last status change. Recorded in D-114.
