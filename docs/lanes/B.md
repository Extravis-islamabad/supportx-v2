# Lane B

This lane's own file (D-127): only this lane edits it, at every start and finish of a
work package. The index and the rules are in [`docs/LANES.md`](../LANES.md).

## Area

Identity, mail, notifications, CI

## Current WP

WP-014b session 1 merged (#192, replacing #189; ADR-038), plus connector defaults (#185, D-041). Now: WP-040 AD/LDAP (#175, D-130) into the queue after #178; the WP-014b node-loss test (#193, draft). Queue after WP-014b: QA round, WP-013 (licence core, private repo: Haider), WP-014c. WP-037/038 are lane C's; lane B reviews their security parts. Parked: the e2e frozen-page watchdog (branch ci/e2e-timeout-capture, low priority).

## Branch

`feat/wp-040-ldap` (#175); `feat/wp-014b-node-loss` (#193); `feat/wp-014b-ha` (#189, superseded, kept until Haider decides)

## Worktree

`../supportx-v2-entra`, `../supportx-v2-nodeloss`, `../supportx-v2-ha`

## Claimed migration

0024, 0026, 0032, 0033, 0037, 0042, 0043, 0045, 0049, 0052, 0053 (merged); 0056 AD/LDAP directories (#175; was 0055, which lane C's #176 took), 0057 connector settings (D-041, next) (revises main's head 0051 after #159; lane A's 0054 (#172) and 0058 (#178) also follow 0051, so whoever merges second re-points)

## Claimed decisions

D-098, D-099, D-103, D-104, D-106, D-109, D-116, D-118, D-123, D-127, D-130 (AD/LDAP federation account, #175) (D-126 reserved: the Dependabot rule, waiting for the product owner)
