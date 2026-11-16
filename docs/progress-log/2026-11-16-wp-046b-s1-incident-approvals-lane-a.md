### 2026-11-16 — WP-046b S1: incident approvals and edit controls (lane A)

Plan approved by the coordinator 2026-11-14; lane B's conditions (decision links, segregation of
duties, every write path, the lock outranking the right) applied.

- Backend: `problem_approvals.request` made type-generic with a rule; `approvals._incident_vote`
  applies any/all/majority; incident notifications `incident.approval_requested` (approver,
  e-mail link) and `incident.approval_rejected` (technician); `work_items.update(reason=,
  facts=)` with `_may_edit_closed` and `_edit_reason`; audit `incident.closed_edited` and
  `incident.closed_edit_lock_changed`; `PUT /incidents/settings/closed-edit-lock` (RecentAuth);
  first-contact suggestion in `_status_change(actor=)`; migration 0169.
- Console: `IncidentApprovals` and `AskApprovalDialog`, the inline "Why" box, the closure
  settings, the first-contact row.
- Tests: `tests/db/test_incident_approvals.py` (7), `tests/db/test_incident_edit_controls.py`
  (5), console `approvals.test.tsx` (3).

Note: when segregation of duties refuses an e-mailed link, the shared link service answers
"no longer yours to decide", as for requests; nothing is decided.
