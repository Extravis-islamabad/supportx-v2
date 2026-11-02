# Lanes

Three lanes work in parallel (product owner, 2026-10-27). Each lane keeps **its own file** in
`docs/lanes/` up to date at every start and finish of a work package. Rules: see "Coordination
rules" below.

## Lanes

Each lane keeps its own file (D-127), so two lanes never edit the same lines:

- [Lane A](lanes/A.md): incidents chain
- [Lane B](lanes/B.md): identity, mail, notifications, CI
- [Lane C](lanes/C.md): reports, dashboards and knowledge

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

1. `docs/lanes/<lane>.md`: each lane's current WP, branch and worktree, claimed migration and
   decisions (only that lane edits it); this file: the index, the QA lock and these rules.
2. Every lane works in its own git worktree from the latest main; only lane A uses the main folder.
3. Migrations: one Alembic head always. Before opening a PR, merge the latest main and renumber
   your migration after the current head.
4. Decision numbers: the next free number on the latest main at commit time; on a conflict,
   renumber yours. Each decision is a new file `docs/decisions/D-NNN.md` and each session-log
   entry a new file in `docs/progress-log/` (D-123); never add rows to `DECISIONS.md` or entries
   to `PROGRESS.md`'s session log.
5. Shared dev stack: one lane at a time runs QA or restarts shared services (the lock above).
   Unit and database tests (Testcontainers) need no lock.
6. Keep k3d stopped unless you hold the lock and need it; stop it afterwards. No heavy test suites
   during another lane's QA. Never start containers you don't need. (MacBook Air M5, 24 GB,
   fanless: mind memory and CPU.)
   A full `make check` is a heavy suite: its `tests/integration/*` log the seeded users into the
   shared dev Keycloak and use the dev database, so two runs at once race (lane A's 6
   `login_failed` failures, 2026-10-27). Tell the other lanes before starting one and never run
   two at once. Testcontainers database tests stay lock-free.
7. Shared files (PROGRESS.md WP sections, labels, CLAUDE.md): small additive edits; on conflicts
   keep both sides. Generated files (OpenAPI, API types, the backend label JSON) are never
   committed and never hand-merged: `make generated` writes them (D-127).
8. Stay in your lane's code; if you must change another lane's module, tell that lane first and
   keep it minimal. Lane C reads incident data through read-only paths lane A provides; it does
   not change incident code.
9. Never stop or change another lane's processes, containers or data without agreement; never
   touch non-SupportX containers.
10. Standing merge approval as before (all required checks green, latest main merged in, no
    force push).
