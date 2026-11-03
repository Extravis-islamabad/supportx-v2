# Lane C

This lane's own file (D-127): only this lane edits it, at every start and finish of a
work package. The index and the rules are in [`docs/LANES.md`](../LANES.md).

## Area

Reports, dashboards and knowledge (knowledge moved from lane B, D-108); the public API and admin
setup (WP-041, WP-042, moved from lane B); AI (WP-037, WP-038, moved from lane B, 2026-11-03).

## Current WP

Console UI pass (#159, D-124) going into the queue. Then, in order: the label split
(`refactor/labels-per-module`, D-127 follow-up, built); WP-041 public API (plan approved, key
design approved by the product owner, building); WP-042 S1 (plan approved); WP-034 S1 (#158,
built; the knowledge screens move onto the D-124 layout once #159 is on main); WP-037 then WP-038,
each planned to the coordinator first. Urdu for the 370 older keys before the pilot.

## Branch

`feat/console-ui-pass` (#159), `refactor/labels-per-module`, `feat/wp-034-knowledge-search`
(#158), `feat/wp-041-public-api`

## Worktree

`../supportx-v2-uipass`, `../supportx-v2-labels`, `../supportx-v2-wp034`, `../supportx-v2-wp041`

## Claimed migration

0027, 0029, 0031, 0035, 0036, 0041, 0046, 0048 (merged); 0051 side menu default (#159, follows
0048); 0050 knowledge search and votes (#158); 0055 API keys (WP-041)

## Claimed decisions

D-100, D-101, D-108, D-110, D-114, D-117, D-119, D-120, D-121 (merged); D-124 console UI pass
(#159); D-125 WP-034 (#158); D-128 WP-041; ADR-033, ADR-034
