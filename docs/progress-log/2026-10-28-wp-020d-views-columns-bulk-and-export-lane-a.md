### 2026-10-28 — WP-020d: views, columns, bulk and export (lane A)

- Built to the approved plan; defaults D-111 (approved with group sharing). Backend: new
  built-in views, saved views, list settings, list fields, view filters, bulk jobs (migration
  0038, renumbered after 0035 dashboards, 0036 knowledge and 0037 mailboxes). Console: column chooser, view editor with the shared
  filter builder, time range, search chips, page size, selection across pages, bulk dialog and
  progress, export. Draft PR #114; e2e and the QA round next, then WP-020e.
- Lane C found that migration 0034's data step changed no rows under FORCE RLS; confirmed with a
  test and fixed in #116 (loop per tenant).
- Merges now go through `gh pr merge` without `--admin` (branch protection: 8 required checks,
  no bypass, product owner 2026-10-28). Cross-lane reviews are posted as PR comments.
