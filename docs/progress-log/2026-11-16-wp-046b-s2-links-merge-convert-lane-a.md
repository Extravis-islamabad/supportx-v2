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
- Console: hooks; the Links tab links a child and resolves children; `MergeConvert.tsx`: the
  merge dialog (preview counts, a tick to confirm a wider audience), the merged or converted
  banner with undo, the convert dialog (INC→SR: catalog item and answers; SR→INC: template),
  and an old number leading to the new record in Ctrl+K.
- 2026-11-17 (after Haider's stop and start):
  - lane B's #525 findings: both records locked in ID order for merge, undo and convert;
    followers counted in the audience;
  - follower notices: a follower who may not open the incident hears its public side;
  - the survivor's requester is named only to followers in the same department (the
    coordinator's default, until the product owner answers). One rule: `requester_names.named_to`.
    Named approvers keep the name. The overlay goes through an optional notifications port,
    `RecipientVariables`.
- Tests: `test_incident_children` (5), `test_incident_merge` (7), `test_record_convert` (5);
  console `mergeConvert.test.tsx` (4).
