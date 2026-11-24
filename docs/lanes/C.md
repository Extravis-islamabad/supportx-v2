# Lane C

This lane's own file (D-127): only this lane edits it, at every start and finish of a
work package. The index and the rules are in [`docs/LANES.md`](../LANES.md).

## Area

Reports, dashboards and knowledge (knowledge moved from lane B, D-108); the public API and admin
setup (WP-041, WP-042, moved from lane B); AI (WP-037, WP-038, moved from lane B, 2026-11-03);
WP-057 security hardening. Lane C blocks files, permissions, outbound calls, CI and dependencies
(D-175).

## Current WP

**WP-057 S5c (2026-11-24):** roles and support groups from identity provider groups (REQ-SEC-014), migration
0201.
- The plan is approved by lane B (who blocks it, with six conditions) and by the coordinator.
- Step 0, lane B's real-Keycloak spike on the transport, comes first.
- Then S5c-1 (backend) and S5c-2 (screens).

**After S5c:** WP-057 S6, then the D-175 queue: WP-060, 061, 063, 059b/c, 062b, and the MVP gaps.

**Merged 2026-11-24:**
- #609: realtime `covers` plus the `channel-covers` rule;
- #613: the D-180 masked-names Vitest;
- #614: the reports-home CMDB tab.

**In the queue:** #616 (portal covers).

**Waiting on the product owner:** asset delete by vendor support (`assets.delete`, or
`assets.manage` never).

## Branch

- `fix/channel-covers-portal` (#616, queued)
- `chore/lane-c-ci-bundle-11-24` (this bundle: the route map's Feature column)

## Worktree

- `../supportx-v2-portalcovers`
- `../supportx-v2-cibundle`

## Claimed migration

- **Merged:** 0027, 0029, 0031, 0035, 0036, 0041, 0046, 0048, 0050, 0051, 0055, 0060, 0061,
  0066 to 0069 and 0071. Later ones are in each PR and in `backend/migrations/versions`.
- **Claimed:** 0201, WP-057 S5c-1 (`idp_group_mappings`, `access_sources`, `managed`).

## Claimed decisions

D-100, D-101, D-108, D-110, D-114, D-117, D-119 to D-121, D-124, D-125, D-128, D-183 (merged);
ADR-033, ADR-034.
