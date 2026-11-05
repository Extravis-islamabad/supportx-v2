### 2026-11-05 — WP-058a sessions 2-6: releases complete (lane C, #219)

- **S2, templates (0093):**
  - A template picks the release's path, and holds rules per stage: shown, required to leave,
    read-only. They are checked on save.
  - Standard and emergency templates are seeded.
  - Read-only per stage is enforced through the API.
  - A release type sets its default template and risk.
  - Releases can be copied.
- **S3, required fields and stage access (0094):**
  - Required-to-leave is checked on every path, and a move can carry the values.
  - Stage access is an `AccessRule` in identity_access's one policy layer (lane B reviewed). It
    narrows editing and moves, never visibility. An empty rule restricts nobody, and those who
    configure the service desk always pass.
  - A group change takes effect without signing in again.
- **S4, roles and record parts (0095; lane A checked the tables for changes):**
  - Roles are held by people or groups, with eligibility through the policy layer. Holders are
    part of the own scope (`ResourceType.owner_extra`), so they reach the release in lists, on
    the record, live and in search.
  - Plan sections each have their own If-Match.
  - The engine stamps actual stage dates, and corrections need a reason.
  - Stages record outcomes; downtime windows name the affected services and CIs.
- **S5, approvals, review and sub-releases (0098):**
  - Stage approvals run on the WP-030 engine: up to five levels of people, groups and roles,
    each decided by any, all or majority (an exact split rejects).
  - Named approvers decide by being named; `releases.approve` (admins by default) is for the
    rest. A role nobody holds goes to the approval administrators, with the reason shown.
  - The review stage has its sections and its result.
  - Sub-releases: one parent, no loops, and no deployment before the sub-releases pass testing.
- **S6, the console:**
  - The releases list with the emergency flag, the new-release form, and the record with its
    rail, a move dialog that asks only for what the move needs, and its tabs. All live.
  - Console tests, and the `releases.spec` e2e with axe in English and Arabic.
  - `docs/guides/releases.md`.
- **Also this session:**
  - The Visual matrix is green for the first time (run 41950850981, 1,380 shots). Its hangs
    came from stale selectors with no timeouts (#226), and the selector fix is on its own
    branch.
  - The visual majors were graded by the coordinator; lane C's are fixed on that branch.
  - Reviews: #220 (announcements) approved after fixes.
- **Parked:** recorded in PROGRESS under WP-058a, for WP-058b, WP-062b and WP-063.
