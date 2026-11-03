# Lane C

This lane's own file (D-127): only this lane edits it, at every start and finish of a
work package. The index and the rules are in [`docs/LANES.md`](../LANES.md).

## Area

Reports, dashboards and knowledge (knowledge moved from lane B, D-108); the public API and admin
setup (WP-041, WP-042, moved from lane B); AI (WP-037, WP-038, moved from lane B, 2026-11-03).

## Current WP

**Paused** (product owner, 2026-11-04) after the console UI pass (#159, D-124) merged. Resume
queue, in order: (1) knowledge e2e specs 139/276/347, red on main too; (2) the label split
(`refactor/labels-per-module`, re-run on fresh main, all lanes told before it is queued); (3)
WP-041 public API (#176, draft: backend, outbox events and live list built; screens and D-128 to
do); (4) WP-042 S1 (plan approved); (5) WP-034 S1 (#158, built; knowledge screens onto the D-124
layout); (6) WP-037 then WP-038, each planned to the coordinator first. Urdu for the 370 older
keys before the pilot.

## Branch

`refactor/labels-per-module`, `feat/wp-034-knowledge-search` (#158), `feat/wp-041-public-api`
(#176)

## Worktree

`../supportx-v2-labels`, `../supportx-v2-wp034`, `../supportx-v2-wp041` (`../supportx-v2-uipass`
done: #159 merged)

## Claimed migration

0027, 0029, 0031, 0035, 0036, 0041, 0046, 0048, 0051 (merged); 0050 knowledge search and votes
(#158); 0055 API keys (#176, follows 0051)

## Claimed decisions

D-100, D-101, D-108, D-110, D-114, D-117, D-119, D-120, D-121 (merged); D-124 console UI pass
(merged); D-125 WP-034 (#158); D-128 WP-041; ADR-033, ADR-034
