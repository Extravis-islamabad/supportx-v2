### 2026-11-10 — WP-045b changes: risk, advisory boards, approvals, re-approval (lane A)

Branch feat/wp-045b, built on #299 (WP-045a). Plan: ~/Desktop/wp-045-plan.md D8 to D11. Spec:
file 05, REQ-CHG-039 to -042, -053, -056 to -060. Migrations 0116, 0117 and 0118, from the
coordinator.

**Done**

- **S1, risk:** the domain (`domain/change_risk.py`), the questionnaire API and the risk columns
  (0116).
- **S2, boards:** `change_boards` and `change_board_members`, both with RLS; the admin API;
  seeds; the choice by mapping (`domain/change_boards.py`).
- **S3, approvals:**
  - boards on approval levels, with `board_id` and `board_reason` on each approval row;
  - the strict segregation setting and the "every matching board" setting;
  - the submit preview and the `change.approval_rerouted` audit;
  - the guide, docs/guides/change-approvals.md.
- **S4, re-approval:**
  - snapshots (0118) and the policy setting;
  - `changes-since` and the warning preview;
  - the send-back (`stages.send_back`; `_save_system_entry` is shared with the standard-change
    conversion);
  - advisory votes (`work_item_approvals.advisory`);
  - the emergency override (`changes.emergency_override`, `pir_required`);
  - `work_items.change.approval_notice` in the outbox.
- Lane C agreed to the changes in their stage-approval code (rule 8). The chair's tie-break
  stays theirs.

**Tests:** tests/db/test_change_boards_api.py (14), test_change_approval_settings.py (3),
test_change_reapproval_api.py (6), and the domain tests for risk, boards and re-approval. The
change and release approval suites and the label, event, permission and migration contracts
pass. Under the Mac's high load, test files ran one at a time.

**Not yet**

- Sending the notices: the change notifications, WP-056.
- The chair's tie-break (D-146), when lane C's WP-048b S2 lands.
- CIs and services in the snapshot, with the CMDB.
- The change screens, on UI pass 3's templates.
