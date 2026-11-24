### 2026-11-24 — WP-053 S5, lane A's part: CIs on work items and the downtime event (0199)

**Scope:** what lane B's WP-053 S5b and S5c need from work_items, in one PR after WP-047a S3a
(the coordinator's order; migration 0199). The shapes were agreed with lane B before building.

**Built:**
- **`work_items.downtime.changed` v1** on every downtime save and remove. One row:
  - work_item_id, type, downtime_id, version;
  - phase, kind;
  - starts_at and ends_at (UTC);
  - ci_ids, service_ids;
  - source_work_item_id, deleted.

  It carries no state and no free text. The registry needs `<module>.<entity>.<action>`, so the
  name is `downtime.changed`; lane B was told.
- **Incidents record the actual downtime they caused** (REQ-CMDB-020 AC3; the coordinator's OK):
  - the same routes, history and event as changes and releases;
  - actual phase only, with kinds from the shared codes;
  - refused once the incident is closed;
  - the incident becomes `source_work_item_id`.

  Every type now checks a downtime's newly named CIs with `cmdb.can_link`.
- **`work_item_cis` (RLS) and `work_items.ci_link.changed` v1:**
  - the link event carries IDs only, plus the record's type and version;
  - GET/POST/DELETE `/{type}/{id}/cis` cover incidents, requests, problems, changes and
    releases;
  - create accepts `ci_ids` and links them `at_creation`, even with no CI field on the form
    (REQ-SR-019 AC1);
  - history holds the CI's ID and is named per reader at read time through `cmdb.ci_refs`, so a
    hidden or gone CI reads masked;
  - the cmdb merge port `repoint_ci_links` is registered.
- **Waiting:** the open and total counts adapter waits for lane B's #605 (the widened
  `OpenCountsPort`) on main.

**Checks run:**
- `tests/test_*.py` and the work_items and cmdb module tests: 1,202 passed;
- lint-imports: 22 kept;
- events-check: no breaking change;
- label tests: 106 passed;
- the route map.

The DB tests and the label commit run in the heavy slot.
