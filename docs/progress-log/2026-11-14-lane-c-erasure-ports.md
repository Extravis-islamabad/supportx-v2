# 2026-11-14 — lane C: GDPR erasure ports (ADR-052 S2, migration 0165)

Plan approved by the coordinator 2026-11-14 (migration 0165, a guard test on the new hard
deletes, lane B blocks).

## Built

- **Ports** (one file per module, `service/person_data.py`, registered at module import, each
  added to `REQUIRED_PORTS`):
  - `knowledge` (540): votes deleted; topics and articles move to the successor; their
    never-submitted drafts are blanked (title "-", a check forbids blank) and soft-deleted;
    articles they created that are left with no live version are soft-deleted.
  - `analytics.recipients` (140): they leave other people's scheduled report recipient lists.
  - `analytics` (550): favourites, dashboard preferences and report exports deleted (an export's
    file first; no file store = `erasure_storage_unavailable`, retried); private dashboards
    deleted; shared or group dashboards, reports and folders move; schedules move and are paused
    (`owner_changed`), because a schedule mails with its owner's access (ADR-047 §5).
  - `announcements` (560): follows and dismissals deleted; owned announcements move.
  - `ai` (950, derived band): the text of their AI calls cleared through `ai/service/erasure.py`
    (audited, idempotent); the rows stay as the usage and cost record (D-131; lane B, #502).
- Every moved or removed object writes its module's ordinary event (rule c); counts only.
- **Migration 0165**: DELETE on kb_votes, dashboard_preferences, report_exports, dashboards
  (grants only; the downgrade restores the earlier grants).
- **Guard**: `tests/test_erasure_deletes.py` scans the app for `delete(Model)` or
  `DELETE FROM` on those tables outside the two ports.
- `ErasureStepFailed` exported from `app.modules.identity_access` (lane B's module).
- Lane B's tests widened for phased ports (call order compares runs; the idempotency test
  covers `LANE_B_PORTS`; lane C's are in `tests/db/test_erasure_ports_lane_c.py`).
- Labels en/ar/ur: 18 `erasure_count.*` kinds, `report_schedule_result.owner_changed`,
  `errors.erasure_storage_unavailable`.

## Tests

- `tests/db/test_erasure_ports_lane_c.py` (3): every port to the end; nothing of theirs left;
  the successor holds what moved; the other tenant untouched; twice = zero counts; outbox
  events written; the export file deleted or the step retried; RLS.
- Lane B's erasure suites: 52 passed.

## Open

- 0165 re-points onto the head at its turn in the migration queue.
