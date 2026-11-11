### 2026-11-11 — Change screens, PR 2: approvals, the override, boards, QA flow 4 (lane A)

No migration. Builds on #372.

- **Approvals tab:**
  - each approval shows its board and why ("its rules matched this change" or "the default
    board"), the approver or the approval administrators, advisory votes (not counted) and the
    route reason;
  - Approve and Reject use the shared decision dialog and send the approval's If-Match;
  - "Changed since approval" lists, field by field, what each change does.
- **Before raising a stage:** the move dialog shows who would approve and who is left out, with
  the reason. The backend preview now returns their names (`people`).
- **Re-approval:** saving a new risk first asks `reapproval-preview`. If a stage would restart,
  a confirm names the stages.
- **Emergency override (D-144):**
  - offered under More only with `changes.emergency_override`, and only on a change sent back.
    The change details now carry `sent_back`;
  - needs a reason and says what happens: the change goes back without the new approval, the
    override is recorded, and the review becomes mandatory.
- **Schedule:** a stage that records an outcome takes it in a select. Implementation needs one
  before it completes.
- **Boards (template E, `/admin/change-boards`):**
  - boards in their order: name, rule, members (or "no members: the approval administrators
    decide");
  - add, edit, move up and down, and remove; the default board can never be removed;
  - members can be people or groups and can be optional; the chair is chosen from the people;
  - the mapping covers types, risk levels, sites and templates;
  - board responses now name their people (`people`);
  - needs `changes.manage_boards` or `settings.manage`, and the server audits every change.
- **Fix:** a staged move now says where it lands (`lands_in`). The dialog asks for the closure
  code when a move lands in closed after an automatic advance. "Review complete" closes a
  change, and before this a change could not be closed from the console. Releases benefit too.
- **Labels:** the shared dialog and the change screens use `staged.*` keys, copied from the
  release ones (lane C's review). `statusName`, `listValueName` and `stageName` live in
  `pages/staged/labels.ts`, re-exported from the release labels.
- **Tests:**
  - `approvals.test.tsx` (7 cases) and `changes.test.tsx` (6);
  - `test_changes_api.py::test_qa_flow_4_a_normal_change_end_to_end`;
  - the preview, boards and override DB tests extended;
  - `e2e/tests/changes.spec.ts`: flow 4 and the live list. These run in CI; they were not run
    locally.
