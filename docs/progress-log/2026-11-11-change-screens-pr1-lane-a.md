### 2026-11-11 — Change screens, PR 1: list, new change, the record (lane A)

Taken forward from WP-045d D19 at the coordinator's request, before WP-045c. No migration.

- **List (template C):** number, title with the emergency flag, path, stage and status. It is
  live on the list channel, and the views include a new **Pending approval**. Stage approvals
  never set the record's approval status, so that view also matches the stages' raising
  statuses (`CHANGE_AWAITING`). The list filter now accepts the staged types' own status codes;
  before, a change or release filtered by its own status was refused.
- **New change (template B):** the template (which sets the type and the path), title,
  description, requester and reason for change. When raised with `?from=`, it is prefilled and
  linked. It opens on the Risk tab, because the questionnaire is the template's and so needs
  the change to exist.
- **Record (template A):**
  - the stage rail (still the release copy until lane C's #370 lands) and the moves: one
    primary, the rest under More, and unavailable ones say why;
  - properties;
  - details: type, reason, and a risk override that requires a reason;
  - the risk questionnaire, scored as you answer and sent with the details' If-Match;
  - roles, plans (the backout plan is needed to send the plan for approval), and schedule and
    downtime, read-only;
  - history.
- **Shared:**
  - `api-client/staged.ts` has hooks by type, keyed like the release keys;
  - `pages/staged/MoveDialog.tsx` is the one move dialog, by type, as lane C asked. Releases'
    props, test IDs and behaviour are unchanged, and `releases.test.tsx` passes unchanged. A
    plan section a move needs is named in the dialog and written on the Plans tab.
- **Tests:**
  - `changes.test.tsx` (5 cases);
  - `test_changes_api.py`: a case for the Pending approval view and its filter equivalent;
  - shell e2e: Changes is now a real page, and CMDB the last placeholder.
