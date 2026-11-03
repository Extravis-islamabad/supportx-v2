# Lane A

This lane's own file (D-127): only this lane edits it, at every start and finish of a
work package. The index and the rules are in [`docs/LANES.md`](../LANES.md).

## Area

Incidents chain (WP-021 fix → WP-029 rules → WP-020f → WP-020d/e → WP-025 SLA)

## Current WP

**PAUSED 2026-11-04 (Haider, via the coordinator).** WP-025 sessions 3-4 in **#172** (queued on --auto; needs `gh pr update-branch 172` by Haider, then a one-line re-point of 0054 onto main's head 0051, cleared with the coordinator first). **WP-028 in #178** (draft, 824dc05): backend, portal UI, lane B parts all approved. Resume point: merge main (#159) into feat/wp-028, re-point 0058 onto 0051; then the e2e users per lane B's (a)+(b) (stack.ts is lane B's, they review), move realtime-security 124/148/186 and knowledge.spec:354 to the portal, e2e en/ar at 360x740 with axe, D5 after #172. Queue after: QA round (WP-020e + WP-025), WP-030, WP-031, WP-032.

## Branch

`feat/wp-028` (#178, draft); `feat/wp-025-s3` (#172, queued)

## Worktree

main folder (`supportx-v2`)

## Claimed migration

0038, 0039, 0040, 0044, 0047 (merged); 0054 (WP-025, #172); 0058 (WP-028, #178); both re-point onto main's head 0051 before merge

## Claimed decisions

D-105, D-115
