### 2026-11-24 — WP-047a S2b, automatic approval and adjusting a running approval (lane A)

Migration 0195 (on 0194). REQ-SR-033 (automatic approval) and REQ-SR-042 (technicians adjust
a running approval). Draft #593. Plan: `~/Extravis/plans/wp-047a-s2-plan-lane-a.md` ("S2b
plan"), approved by the coordinator with Q1, Q2 and conditions 1-5. Lane B's review conditions
are L1-L6.

## What was built

- **Automatic approval** (`domain/request_stages.py` `open_with_earlier`,
  `first_matching_rule`, `matched_keys`; `service/request_stages.py` `_open_one`):
  - "Approved earlier" is resolved into the snapshot at submission (the item's switch, else
    the tenant's).
  - It only counts people's own decisions on earlier stages, and only for candidates `assign`
    found eligible now.
  - A rule match writes one automatic row, plus a history line and an audit entry naming the
    rule and its keys.
- **Adjusting** (`service/approver_changes.py`, `api/approver_change_routes.py`): four actions,
  with If-Match on the request and a required reason. The right is declared in work_items, and
  vendor support never gets it (lane B's file, one line, OK'd). Ad hoc on requests reuses the
  incident path, with purpose `ad_hoc`.
- **UI:**
  - the request's Approvals panel: the automatic reasons in words, and the four actions,
    disabled with the reason without the right;
  - names through `useHiddenPersonLabel` (D-180);
  - the stage editor's "Automatic approval" section, with rule names per language and a
    "requester's groups" field;
  - the tenant switch on Requests settings.
  - Labels are in en, ar and ur.

## Tests

- 15 new DB tests and 3 Vitests; domain tests for the automatic rules, the snapshot and the
  catalog checks.
- Related DB suites 77 + 44 + 18, `tests/test_*.py` 789, app tests 2092, Vitest 43. All pass
  locally (throwaway Postgres and Valkey, heavy slot 22:39-23:04Z).

## Decisions and notes

- A reminder is limited per request (once every 10 minutes, at most 10), stricter than lane
  B's "per stage", and counted from the record's history.
- A revoked link answers `action_link_revoked` (409, "no longer valid"), as lane B's L4 asks.
- An S2a gap is fixed: a single stage's condition, approver kinds and rules weren't run through
  `stages_problems` before saving.
