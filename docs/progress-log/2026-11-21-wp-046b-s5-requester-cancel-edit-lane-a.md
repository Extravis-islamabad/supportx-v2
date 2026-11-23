### 2026-11-21 — WP-046b S5: requester cancel and edit rules (lane A)

REQ-INC-148, migration 0184. The plan was approved by the coordinator: Q1 the asks table (0184),
Q2 unassigned asks go to the group's members who may edit, else the type's SDMs, and Q3 both
settings off by default. Off was checked against main: the requester role holds no `incidents.*`
grant, and the portal's incident routes are report, reply and confirm or reject a fix. Lane C
blocks.

## Done

- **0184:** `work_item_type_settings.requester_cancel` (off, direct, ask; default off) and
  `requester_edit_fields` (default none); `work_item_cancellation_requests`, with at most one
  pending per record, RLS, the actor audit and soft delete.
- **Service (`requester_requests`):**
  - cancel, either direct (the system move as the requester, with their words) or by asking;
  - withdraw;
  - decide: the assignee, else whoever may edit; approve runs the ordinary cancel as the decider,
    asking for the cancel's own reason code when it needs one; decline sends the note as a
    public reply;
  - edit, only the allowed fields, with If-Match.
- **Routes:**
  - portal: `POST …/cancel`, `DELETE …/cancel-request`, `PATCH /portal/incidents/{id}`;
  - staff: `GET` and `POST …/cancellation-request[/decide]`;
  - the settings API.
- **Events:** `work_items.cancellation_request.created` and `.decided`, carrying IDs only.
  Labels in en/ar/ur.
- **Console and portal:**
  - the portal's cancel or ask, withdraw and edit;
  - the record's strip with Approve and Decline;
  - the admin card on General.

## Checks

- Backend, on a standalone throwaway Postgres and Valkey (the shared-stack freeze; both
  removed):
  - S5's API (6) and migration test, plus the portal and incident-settings suites: 44 passed;
  - tests/test_*.py: 752 passed;
  - the domain tests (16) and the label tests.
- Console and portal Vitest: strip 3, portal 4, admin card 1, plus the neighbouring suites.
- tsc, ESLint, Prettier, ruff, mypy, import contracts, the route map and event schemas are clean.

## Open

- Requester editing of impact, urgency and custom fields in the portal: the API takes them,
  but the form shows subject and description first.
