### 2026-11-13 — e2e smoke suite (@smoke), nightly and on demand

Branch ci/e2e-smoke-suite. Approved by the coordinator. No new tests and no dependencies.

**Done**
- 13 existing Playwright tests tagged `@smoke` (title tag, a one-line change each): login,
  sign-in security (REQ-SEC-029: the session ends, a fresh sign-in through Keycloak), incident
  create (`incidents.spec.ts`) and resolve (`closing.spec.ts`: no single test does both), a
  portal service request raised and tracked to Closed, live updates in two browsers, the
  realtime permission cut, files, API keys, a role change (`roles.spec.ts`: `users.spec.ts` has
  no role change), audit, read-only mode, knowledge search. About 4-5 minutes of tests.
- Stack smoke workflow: a `smoke` job ("e2e smoke (@smoke journeys)"), nightly on the existing
  cron and on a manual run with the new `suite: smoke` input (which skips the three full shards).
  Never on pull_request or merge_group; not a required check; no ruleset change. 20-minute job
  limit, the Playwright report always uploaded, the total and per-test times in the summary.
- `make e2e-smoke`; frontend/e2e/README.md and docs/dev-setup.md describe the suite.
- backend/tests/test_ci_triggers.py: the smoke job's triggers, not required, and 12 to 16 tagged
  tests covering every journey.

**Open**
- No e2e test asserts the BFF login-binding cookie itself (backend tests cover it); every
  tagged sign-in passes through it.
- `make help` lists no target with a digit in its name (`e2e`, `e2e-smoke`): its pattern is
  `^[a-z-]+:`. Left for the polish queue.
