### 2026-11-23 — WP-047a S2a, service request approval stages (lane A)

Migration 0194 (on 0193). REQ-SR-029 (multi-stage), -030 (parallel), -031 (approver kinds) and
-032 (conditional stages). Plan: `~/Extravis/plans/wp-047a-s2-plan-lane-a.md`, with the
coordinator's S2 conditions 1-6 and snapshot conditions 1-4, and lane B's notes on the owner
ports.

## What was built

- **The stage model** (service_catalog): `ApprovalStage` gains a rule, a parallel group and a
  condition; `ItemRules.stages`; up to 10 stages for requests (`MAX_STAGES`); every check in
  `stages_problems`. The condition language moved from form_rules to `app/shared/conditions.py`,
  so form rules and stages share one validator (only work_items used it: no rule 8 notice).
  An item saved before S2a reads as its one stage (`stages_of`), with no data step.
- **The snapshot** (work_items `domain/stage_snapshot.py`): `{"v": 1, "stages": [...]}` on
  `work_items.approval_stages`. It holds only configuration: codes, IDs, switches and the
  condition. A stored value of another version or shape is refused, not guessed at.
- **The engine** (`domain/request_stages.py`, `service/request_stages.py`):
  - steps from neighbouring parallel groups;
  - each stage settled by the level engine's `level_outcome`;
  - skipped stages pass at once;
  - a rejected step withdraws its others;
  - the last step finishes the request through `_finish`, as today.
  - The approver kinds resolve through organization's public ports (`unit_heads`,
    `users_in_groups`, `active_groups`) and lane B's new `owners_of` in assets and cmdb.
- **Erasure**: a `stage_snapshots` phase in `work_items.references`, after approvals are
  rerouted, plus a test that JSON-held person IDs have a required port.
- **Editions**: `uses_stages` names each Professional part by its REQ. Saving is gated on the
  server (`catalog`), and so is raising a request on a still-staged item after a downgrade.
- **UI**: the Approval tab's stage editor (`StagesEditor.tsx`, helpers in `stages.ts`); the
  request's Approvals tab shows stage numbers, "runs in parallel", and skipped stages with
  their condition in words (question labels and option words; the language's own and/or
  lists). Labels in en/ar/ur.

## Process notes

- Merging main into S2a after #578: the reverse-applied patch left intent-to-add index entries,
  and the following `git apply --3way` recreated the new files empty and dropped the modified
  files' changes. The patch file was intact, so nothing was lost: I cleared the 14 empty
  placeholders, checked the tree was clean, and re-applied. Two conflicts with S1 (the
  service_catalog exports and `CatalogItemOut.of`) were resolved keeping both sides. The lesson
  is in lane A's memory.
- `ApprovalIO.approvers` stays required as before, so the API change is additive (new optional
  fields and `stages`).

## Checks (local)

- Backend: ruff, mypy (whole app, 1131 files), import-linter (22 kept); unit tests 359+ (domain
  stages, snapshot, assign, editions), label guards (enum, audit actions, erasure counts).
- Frontend: typecheck and lint for the whole workspace; labels 66, console catalog and requests
  34 (two new editor tests, one new skipped-stage test), portal 73.
- DB tests (written, run in the next heavy slot on lane A's throwaway Postgres):
  - `tests/db/test_request_stages_api.py`: old shape unchanged, three stages in order, parallel
    rejection, skipped stage with condition, all skipped, requester left out and audited,
    nobody goes to the administrators, erasure, Essentials, downgrade;
  - `tests/db/test_request_stages_migration.py`: 0194 up, down, up;
  - `tests/db/test_approver_owners_ports.py`: holders only, owner person and group, deleted rows,
    tenant B.

## Follow-ups

- A tenant chair for request stages (D-146). Today a majority tie rejects.
- The CI owner names nobody until WP-053 S5 links CIs to requests.
- The editor edits one condition per stage; combined conditions are kept and shown.
- S2b: automatic approval (REQ-SR-033) and modify approvers (REQ-SR-042, a new right; lane B
  blocks the role defaults).
