### 2026-11-10 — D-154: assignment stays in the group; a request's tasks start the work and name who (lane A)

Branch feat/d154-assign-and-tasks. Migration 0125. Decision D-154 (Haider, through the coordinator).

**Done**

- **a (QA10-P1-07):** for everyone and all work-item types, the assignee is in the record's group. Someone of another group is assigned only by moving the record to their group in the same request.
  - The engine's `<type>.assign_outside_group` action and its labels are gone; 0125 drops every role grant of it, counted per tenant.
  - The assign dialog lists everyone, the group's people first; the others are marked "not in this group".
  - Picking someone outside the group shows why. Their group is picked when they are in several, and the button reads "Move to <group> and assign to <person>". The hand-over warning and the follow default are unchanged.
  - The assignees API returns each person's `group_ids`.
- **c (QA10-P4-40a):** a New or Assigned service request moves to In progress when its technician or someone of its group ticks a fulfilment task.
  - The move is recorded as automatic, rule `first_task`. Nobody is assigned by it.
  - Tenant switch `first_task_starts_work` (on; audited with the request settings), on the request settings page.
- **d (QA10-P4-40b):** `work_item_tasks.done_by`. A done task shows "Done by <name>", tracked in its history and cleared when the task is opened again.

**Tests**

- API: the D-154 test (a technician, a lead and an admin, each refused out of group and accepted when the group moves too), the REQ-INC-053 test (the lead is refused now), and the D-052 visibility test (an older record seeded by SQL).
- Fulfilment: first task by its group, nobody assigned, done_by set and cleared; the switch off.
- 0125's migration test, across two tenants and the downgrade.
- Console: the dialog's combined action, Done by, and the settings switch.

**Open**

- E1 in Haider's screen round (a request fulfilled with nobody on it) is the next bundle.
