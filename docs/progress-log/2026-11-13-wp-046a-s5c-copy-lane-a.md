# 2026-11-13 — WP-046a S5c part 2: copy an incident N times (lane A)

**Scope:** REQ-INC-033 (copy N times, with tasks and attachments when chosen), migration 0156
(coordinator's number; queue order 0154 → 0155 → 0156 → 0157).

**Done**
- `record_copies.copy_record`: N copies through the normal create, marked subjects, a
  `copied_from` history entry, tasks as new open tasks, the group only for those who may assign.
- `files.copy_to_records` (lane B's rules): source and target access before any read, 404 for a
  record the actor may not use, limits before any write (batch, 200 pairs, 100 MB, one quota lock),
  all or nothing under the uploads gate, `file.copied` audited with IDs only, each link naming its
  record. The copy's description is rewritten to its own files and sanitised again; images that did
  not come are removed. The response lists `files_not_copied`; the dialog says how many stayed.
- `copy_limit` per type (0156), on Admin › Incidents › Closing; the dialog shows the type's limit.
- 0156 also lets `files.source` be `copy`; its downgrade refuses while any tenant has a copied file
  or a changed limit.

**Found and fixed while testing:** copied links had no `record_type`/`record_id`, which the
`draft_has_no_record` check refuses; the target's owner from the access check now fills them.

**Tests:** test_record_copies_api.py (9: AC1-AC3, the type's own limit, attachments and images,
another tenant writes no rows or objects, an unusable target copies nothing, 25 MB x 2 in about 2 s),
test_record_copies_migration.py (up, down, refused twice), copyDialog.test.tsx (3), closing.test.tsx
(copy limit).

**Next:** the PR (draft; lane B blocks on the files part, lane C on the UI); queued after #468.
