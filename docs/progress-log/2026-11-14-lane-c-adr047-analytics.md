### 2026-11-14 — Lane C: ADR-047 analytics slice — field access in reports, dashboards and schedules

Agreed with lane A 2026-11-13; built on lane A's slice b1 (#503). No migration.

## Built

- `app/shared/reporting/ports.py`: `ReportingSource.withheld` (default empty, so other sources
  are unchanged). work_items' `WorkItemSource` fills it with the viewer's hidden and masked
  fields (lane A's code, rule 8).
- `analytics/service/compiler.py`: `check_withheld` refuses a definition that names a withheld
  field (filter, groupings, columns, sort) as `field_not_permitted`, before any other check.
- `analytics/service/exports.py`: a recipient's refusal is recorded as `field_not_permitted`
  (read from `instance_code`), not `report_not_allowed`.
- `analytics/service/schedules.py`: `_report_problem` pauses the schedule (`field_not_permitted`)
  when the owner may no longer see a field; the report-removed case shares the branch.
- Console: `Widget.tsx` shows `dashboards.widget_not_permitted` for `field_not_permitted` and
  `measure_not_permitted`.
- Labels en/ar/ur: `errors.field_not_permitted`, `report_schedule_result.field_not_permitted`,
  `dashboards.widget_not_permitted`.

## Tests

- `tests/db/test_report_field_access.py`: refusal for filter, column and sort (the admin's run
  works); a recipient without access gets no file and the admin does; the owner losing access
  pauses the schedule and nobody is mailed.
- `analytics/tests/test_domain.py`: the compiler check for every place a field is named,
  groupings included.

## Open

- The owner notice for skipped recipients: a notifications kind with lane A (coordinator,
  2026-11-14); no migration.
