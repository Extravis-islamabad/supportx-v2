### 2026-10-28 — WP-035 QA round (lane C)
- Under the QA lock, Playwright (admin plus a group-scoped technician) and Chrome; report
  ~/Desktop/qa-wp035/QA-REPORT.md. Permissions hold everywhere (reports, drill-down, exports,
  scheduled mails, live totals). 8 bugs listed, not fixed: BUG-01 records exports head the ID and
  subject columns "Unknown value"; BUG-02 Arabic PDF chart labels drawn in reversed letter order;
  BUG-03..08 low (Arabic legend overlap, PDF header date order, Latin comma in Arabic filter
  words, PDF label cut-off, "Stacked ..." cut, built-in title kept after changes). The dev stack
  cannot make PDFs (worker without the `pdf` group; checked with the renderer instead).
  Dashboards are WP-036.
