### 2026-11-16 — WP-046b S2: links, merges and conversions (lane A)

Plan approved by the coordinator 2026-11-16 (0172); lane B's and the coordinator's conditions are
in the PR description, each with the test that holds it.

- Migration 0172: link kinds `child_of` (one parent: a partial unique index) and `converted_to`,
  the `convert` move, `work_item_aliases` (tenant first, RLS, soft delete). Re-pointed onto 0171.
- Services: `incident_children` (add, remove, open children, resolve children as a bulk job),
  `incident_merge` (preview with audience counts, merge, exact undo), `record_convert` (preview,
  convert through the create path, aliases), `approvals.withdraw_pending`, the timelines listing
  merged and converted entries by reference, seed version 6 (`converted`).
- Routes: `/incidents/{id}/children…`, `/merge-preview`, `/merge`, `/undo-merge` (RecentAuth),
  `/{incidents|service-requests}/{id}/convert-preview`, `/convert`, `/alias/{value}`.
- Right: `incidents.undo_merge` (service desk managers). Audit: `incident.merge_undone`,
  `incident.converted`, `service_request.converted`.
- Console: hooks; the Links tab links a child and resolves children. The merge and convert
  dialogs and the merged banner follow on the same PR.
- Tests: `test_incident_children` (5), `test_incident_merge` (3), `test_record_convert` (4).
