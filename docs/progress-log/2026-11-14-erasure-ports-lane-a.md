### 2026-11-14 — ADR-052 S2: lane A's erasure ports (lane A)

- **Migration 0166:** DELETE for the app role on eight private tables (followers, list settings,
  reminders, timers, views, reply templates, notification preferences, technician
  availability), guarded by tests/test_erasure_deletes_lane_a.py; `approver_erased` as an
  approval route reason (downgrade refused while used); requester and on-behalf indexes on
  work_items, built CONCURRENTLY.
- **Ports:** work_items.references (150) and .owned (550), notifications (560), integrations
  (570), automation (580), sla (190); all six required by the job. Batches of at most 500 rows
  with a `phase|after` cursor where a person can hold many rows.
- **Decisions applied:** lane B's five answers; the coordinator's approval rule (rerouted to the
  administrators, still pending, never granted, a required notice).
- **Kept on purpose:** IDs inside rule actions, workflow definitions and SLA escalation levels
  (they point at the anonymised row; at run time a person who left falls back to the group or
  the approval administrators). The directory link is WP-040's (lane B).
- **Tests:** db (work items ports: requester text, unassign, follows and addresses, idempotent,
  another tenant; approvals: rerouted, pending, notice event, both fallbacks required), the
  DELETE guard.
