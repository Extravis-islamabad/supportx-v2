# Lanes

Three lanes work in parallel (product owner, 2026-10-27). Each lane keeps **its own row** up to
date at every start and finish of a work package. Rules: see "Coordination rules" below.

## Lanes

| Lane | Area | Current WP | Branch | Worktree | Claimed migration | Claimed decisions |
|---|---|---|---|---|---|---|
| A | Incidents chain (WP-021 fix → WP-029 rules → WP-020f → WP-020d/e → WP-025 SLA) | WP-021-FIX, then WP-029 | `fix/wp-021-qa` (then `feat/wp-029-rules`) | main folder (`supportx-v2`) | 0025 (WP-029) | D-096, D-097; ADR-034 |
| B | Identity, mail, notifications | WP-039 (session 1 PR, then session 2) | `feat/wp-039-identity` | `../supportx-v2-wp039` | 0024, 0026 | D-098, D-099 |
| C | Reports and dashboards | WP-035: sessions 1-3 merged (#73, #77, #84); session 4 scheduled reports (this PR) | `feat/wp-035-schedules` | `../supportx-v2-lanec` (also `../supportx-v2-lanec2`) | 0027, 0029 (merged), 0031 | D-100, D-101; ADR-033, ADR-034 |

Next free decision on the latest main at commit time; on a clash the later lane renumbers.

## Dev-stack QA lock

Only one lane runs QA against the shared Compose stack, or restarts shared services, at a time.
Take the lock by writing your lane here (and telling the other lanes); release it by clearing it.

| Holder | Since | Purpose |
|---|---|---|
| (free) | | |

The shared stack (API :8000, workers, console 5173, portal 5174) currently runs from lane A's
main folder. k3d stays stopped unless the lock holder needs it.

## Coordination rules

1. This file: each lane's current WP, branch and worktree, claimed migration, and the QA lock.
2. Every lane works in its own git worktree from the latest main; only lane A uses the main folder.
3. Migrations: one Alembic head always. Before opening a PR, merge the latest main and renumber
   your migration after the current head.
4. Decision numbers: the next free number on the latest main at commit time; on a conflict,
   renumber yours.
5. Shared dev stack: one lane at a time runs QA or restarts shared services (the lock above).
   Unit and database tests (Testcontainers) need no lock.
6. Keep k3d stopped unless you hold the lock and need it; stop it afterwards. No heavy test suites
   during another lane's QA. Never start containers you don't need. (MacBook Air M5, 24 GB,
   fanless: mind memory and CPU.)
7. Shared files (DECISIONS.md, PROGRESS.md, labels, CLAUDE.md): small additive edits; on
   conflicts keep both sides.
8. Stay in your lane's code; if you must change another lane's module, tell that lane first and
   keep it minimal. Lane C reads incident data through read-only paths lane A provides; it does
   not change incident code.
9. Never stop or change another lane's processes, containers or data without agreement; never
   touch non-SupportX containers.
10. Standing merge approval as before (all required checks green, latest main merged in, no
    force push).
