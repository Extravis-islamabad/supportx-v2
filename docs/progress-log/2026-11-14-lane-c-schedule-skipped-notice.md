### 2026-11-14 — Lane C: the owner's notice for recipients a scheduled report left out (ADR-047 §5)

Follow-up to #508 (the coordinator, 2026-11-14; shape agreed with lane A). No migration.

## Built

- `analytics/service/schedules.py`: a recipient refused for a withheld field is **skipped**,
  not failed (lane B's #508 note). A run that skipped anyone raises
  `ReportScheduleRecipientsSkipped`: schedule, owner, run time, entity, the skipped IDs and the
  withheld field codes (each recipient's own `withheld` ∩ the report's fields). No values.
  `run_schedule` split into `_copy_for` and `_deliver` (size limits).
- `analytics/service/schedule_notifications.py`: record type `report_schedule`, recipient kind
  `schedule_owner` (whoever owns it now), event `report_schedule.recipients_skipped`.
  - Category STATUS; required, so preferences never mute it; in-app and e-mail.
  - Variables: name, skipped count, the fields named in the owner's language (custom names via
    the reporting names resolver).
  - Access FULL only for the current owner who may still schedule reports.
  - Registered at import (the consumers worker).
- Labels en/ar/ur: the event, area, recipient, three variables, the three message templates,
  and the audit event type.
- `docs/architecture/event-schemas.json` regenerated.

## Tests

- `tests/db/test_report_field_access.py`:
  - the run's event names the skipped technician and the field code, no values;
  - `last_failed` is 0;
  - the owner is told with the status category switched off;
  - nobody else is told;
  - a second delivery of the event tells nobody again.
