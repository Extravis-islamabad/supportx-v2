# Lanes

Three lanes work in parallel (product owner, 2026-10-27). Each lane keeps **its own row** up to
date at every start and finish of a work package. Rules: see "Coordination rules" below.

## Lanes

| Lane | Area | Current WP | Branch | Worktree | Claimed migration | Claimed decisions |
|---|---|---|---|---|---|---|
| A | Incidents chain (WP-021 fix → WP-029 rules → WP-020f → WP-020d/e → WP-025 SLA) | WP-020f merged (#100, #105, #107), 0034 fix (#116), entry points (#110), list format (this PR); WP-020d merged (#114); WP-020e (#120) waits for the move; WP-020f QA fix round built (0040); WP-025 plan next | `feat/wp-020e`, `fix/wp-020f-qa` | main folder (`supportx-v2`) | 0034, 0038 (merged); 0039 (WP-020e), 0040 (WP-020f QA fix) | D-105, D-107, D-111, D-112, D-113; ADR-035 |
| B | Identity, mail, notifications | Worker resilience #102 and WP-039-FIX #104 (CI, then merge); WP-024 email channel session 1 in progress (mailboxes, IMAP fetch, mail page, threading; waits on lane A's #105 for the incident side) | `fix/worker-resilience`, `fix/wp-039-qa`, `feat/wp-024-email` | `../supportx-v2-resil`, `../supportx-v2-w39fix`, `../supportx-v2-mail` | 0024, 0026, 0032, 0033 (merged); WP-024 next free after lane C's 0035 | D-098, D-099, D-103, D-104, D-106 |
| C | Reports, dashboards and knowledge (knowledge moved from lane B, D-108) | WP-033 session 4 built (#153, stacked on 3b #151; D-121). Queue: batched QA and e2e for WP-033 s2-s4 (under the lock once on main), then WP-034 (knowledge search, suggestions, portal knowledge), WP-041 (public API: keys, scopes, docs) and WP-042 (admin setup, roles screens, preferences, licence page through the entitlement interface), both moved from lane B (product owner, 2026-11-02); each planned to the coordinator first | `feat/wp-033-s4` (on `feat/wp-033-s3b`), `feat/wp-033-s3b` (on `feat/wp-033-s3a`), `feat/wp-033-s3a`, `feat/wp-033-s2`, `feat/dashboard-widget-library`, `fix/wp036-qa`, `feat/header-context`, `ci/openapi-schema-names`, `fix/export-plain-labels` | `../supportx-v2-s4`, `../supportx-v2-s3b`, `../supportx-v2-s3a`, `../supportx-v2-lanec`, `../supportx-v2-lanec2`, `../supportx-v2-wp036qa`, `../supportx-v2-plainx` | 0027, 0029, 0031, 0035, 0036 (merged); 0041 knowledge review (re-pointed only if the queue rejects it); 0046 knowledge types and article counter (3b); 0048 kb_record_links and files.copied_from (s4) | D-100, D-101, D-108, D-110, D-114, D-117, D-119, D-120, D-121; ADR-033, ADR-034 |

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
