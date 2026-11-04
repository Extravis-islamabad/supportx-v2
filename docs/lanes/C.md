# Lane C

This lane's own file (D-127): only this lane edits it, at every start and finish of a
work package. The index and the rules are in [`docs/LANES.md`](../LANES.md).

## Area

Reports, dashboards and knowledge (knowledge moved from lane B, D-108); the public API and admin
setup (WP-041, WP-042, moved from lane B); AI (WP-037, WP-038, moved from lane B, 2026-11-03).

## Current WP

WP-042 sessions 1 to 3 built on #183: setup home and menu, licence page, roles screens and
group roles, instance settings, personal preferences, announcement audiences. Reviewed by lane B
(identity parts) and lane A (role defaults, config rights). WP-037 S1 (#188, AI gateway) is ready
for review. #158 (WP-034 S1) is queued. Next: WP-038 (AI on incidents, plan approved,
2 sessions), started on a fresh branch from main only once #188 has merged. Urdu for the 370
older keys before the pilot.

## Branch

`feat/wp-042-admin-setup` (#183), `feat/wp-037-ai-gateway` (#188),
`feat/wp-034-knowledge-search` (#158, queued)

## Worktree

`../supportx-v2-wp042`, `../supportx-v2-wp037`, `../supportx-v2-wp034` (`../supportx-v2-wp041`
done: #176 merged)

## Claimed migration

0027, 0029, 0031, 0035, 0036, 0041, 0046, 0048, 0051, 0055 (merged); 0050 knowledge search and
votes (#158, follows 0055); 0060 AI gateway (#188); 0061 group roles, 0066 tenant settings, 0067
user preferences, 0068 announcement audiences, 0071 layout preferences nullable (#183); 0069 AI summaries (WP-038)

## Claimed decisions

D-100, D-101, D-108, D-110, D-114, D-117, D-119, D-120, D-121 (merged); D-124 console UI pass
(merged); D-125 WP-034 (#158); D-128 WP-041; ADR-033, ADR-034
