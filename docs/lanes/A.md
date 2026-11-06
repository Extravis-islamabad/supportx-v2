# Lane A

This lane's own file (D-127): only this lane edits it, at every start and finish of a
work package. The index and the rules are in [`docs/LANES.md`](../LANES.md).

## Area

Incidents chain (WP-021 fix → WP-029 rules → WP-020f → WP-020d/e → WP-025 SLA)

## Current WP

**PAUSED for Haider's full QA stop (2026-11-06).** After the QA round: the QA fixes first (one
fix PR per module, tests named after the bug IDs), then the resume point below.

**Resume point: WP-044c S1 in #240 (draft), branch `feat/wp-044c`.**
- Done: the problem views (known errors, accepted due for review); Tasks, Worklogs and History
  tabs on the problem page (the parts and history hooks take the type's prefix).
- Also done in S1: list views, search, widths, print, assign, Create problem from the bulk bar.
- Next in S1: REQ-PRB-021 (migration number asked) and REQ-PRB-022 (on #258's layout); then S2 (D14 permissions and the narrow incident-side
  read, D15 notifications, report source, counters, portal requester view), S3 (D16 repeat
  rules, D17 API check, Arabic e2e).

Merged: WP-031 (#200), WP-032 S1-S2 (#220), WP-044a (#211), WP-044b (#222), #229 (seed fix).
In the queue: #230 (D-143/D-144), #239 (e2e D-132 link fix). Waiting: WP-032 S3 preview (on
lane B's backend, 0084). Then WP-045 (plan approved: 0099-0103, D-144/D-145, ADR-042).

## Branch

`feat/wp-044c` (#240, draft)

## Worktree

scratchpad/wp044b (on `feat/wp-044c`)

## Claimed migration

0038, 0039, 0040, 0044, 0047, 0054, 0058, 0059, 0060 (merged); 0073, 0074, 0076, 0077, 0089, 0096, 0097, 0078, 0104 (merged); each re-points onto main's head before merge

## Claimed decisions

D-105, D-115, D-129, D-132, D-133, D-138, D-140, D-143, D-144; ADR-039, ADR-040
