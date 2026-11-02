# Lanes

Three lanes work in parallel (product owner, 2026-10-27). Each lane keeps **its own row** up to
date at every start and finish of a work package. Rules: see "Coordination rules" below.

## Lanes

| Lane | Area | Current WP | Branch | Worktree | Claimed migration | Claimed decisions |
|---|---|---|---|---|---|---|
| A | Incidents chain (WP-021 fix → WP-029 rules → WP-020f → WP-020d/e → WP-025 SLA) | WP-020f merged (#100, #105, #107), 0034 fix (#116), entry points (#110), list format (this PR); WP-020d (#114) and WP-020e (#120) built, QA next; then WP-025 | `feat/wp-020d`, `feat/wp-020e` | main folder (`supportx-v2`) | 0034 (merged); 0038 (WP-020d), 0039 (WP-020e) | D-105, D-107, D-111, D-112, D-113; ADR-035 |
| B | Identity, mail, notifications | Worker resilience #102 and WP-039-FIX #104 (CI, then merge); WP-024 email channel session 1 in progress (mailboxes, IMAP fetch, mail page, threading; waits on lane A's #105 for the incident side) | `fix/worker-resilience`, `fix/wp-039-qa`, `feat/wp-024-email` | `../supportx-v2-resil`, `../supportx-v2-w39fix`, `../supportx-v2-mail` | 0024, 0026, 0032, 0033 (merged); WP-024 next free after lane C's 0035 | D-098, D-099, D-103, D-104, D-106 |
| C | Reports, dashboards and knowledge (knowledge moved from lane B, D-108) | WP-033 session 3b (approval inbox, knowledge settings, the e2e round for s2 + s3a + 3b; D-120) building; in the queue plan: #137, #126 then #135, #136, #128, #125, #149 (6a, on #132), #138 then #139 | `feat/wp-033-s3b` (on `feat/wp-033-s3a`), `feat/wp-033-s3a`, `feat/wp-033-s2`, `feat/dashboard-widget-library`, `fix/wp036-qa`, `feat/header-context`, `ci/openapi-schema-names`, `fix/export-plain-labels` | `../supportx-v2-s3b`, `../supportx-v2-s3a`, `../supportx-v2-lanec`, `../supportx-v2-lanec2`, `../supportx-v2-wp036qa`, `../supportx-v2-plainx` | 0027, 0029, 0031, 0035, 0036 (merged); 0041 knowledge review (re-pointed only if the queue rejects it); 0046 knowledge types and article counter (3b) | D-100, D-101, D-108, D-110, D-114, D-117, D-119, D-120; ADR-033, ADR-034 |

Next free decision on the latest main at commit time; on a clash the later lane renumbers.

## Dev-stack QA lock

Only one lane runs QA against the shared Compose stack, or restarts shared services, at a time.
Take the lock by writing your lane here (and telling the other lanes); release it by clearing it.

| Holder | Since | Purpose |
|---|---|---|
| (free) | | |

The shared stack (API :8000, workers, console 5173, portal 5174) runs from `../supportx-v2-stack`,
a clean detached worktree at origin/main, never from a lane's working branch (2026-10-28). The lock
holder updates it with `git fetch && git -C ../supportx-v2-stack checkout --detach origin/main`; the
API and Vite reload by themselves, the workers need a restart (`make worker-<name>` there). k3d stays
stopped unless the lock holder needs it.

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
   A full `make check` is a heavy suite: its `tests/integration/*` log the seeded users into the
   shared dev Keycloak and use the dev database, so two runs at once race (lane A's 6
   `login_failed` failures, 2026-10-27). Tell the other lanes before starting one and never run
   two at once. Testcontainers database tests stay lock-free.
7. Shared files (DECISIONS.md, PROGRESS.md, labels, CLAUDE.md): small additive edits; on
   conflicts keep both sides.
8. Stay in your lane's code; if you must change another lane's module, tell that lane first and
   keep it minimal. Lane C reads incident data through read-only paths lane A provides; it does
   not change incident code.
9. Never stop or change another lane's processes, containers or data without agreement; never
   touch non-SupportX containers.
10. Standing merge approval as before (all required checks green, latest main merged in, no
    force push).
