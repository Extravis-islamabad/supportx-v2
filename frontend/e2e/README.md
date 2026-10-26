# e2e

Playwright journeys against the real dev stack (architecture.md §16.2; WP-010), with axe
accessibility checks (D-026).

```bash
make dev-up backend-env db-migrate db-seed       # once
make backend-dev                                  # API (terminal 1)
make worker-relay                                 # event relay (terminal 2)
make worker-consumers                             # event consumers (terminal 3)
make worker-fanout                                # live updates (terminal 3b)
cd frontend && pnpm --filter @supportx/console dev  # console (terminal 4)
make e2e
```

| Spec                        | Journey                                                                                                                                                                                                                                                                                                                         |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `login.spec.ts`             | Keycloak login, HttpOnly session cookie, logout ends both sessions                                                                                                                                                                                                                                                              |
| `shell.spec.ts`             | every sidebar section, command palette, 404, light/dark/high-contrast, Arabic RTL, axe on the main screens                                                                                                                                                                                                                      |
| `users.spec.ts`             | Admin › Users: infinite scroll over the cursor API, search, type filter, sort                                                                                                                                                                                                                                                   |
| `profile.spec.ts`           | My profile: inline field error, save, 409 conflict across two browser contexts (keep mine / reload theirs)                                                                                                                                                                                                                      |
| `roles.spec.ts`             | admin builds a custom role, assigns it to e2e.limited, whose open menus change live (no reload); removal too; role editor in Arabic + dark (axe)                                                                                                                                                                                |
| `read-only.spec.ts`         | Other Company expired with `make dev-subscription`: banner, disabled edit buttons, reads work; restored after                                                                                                                                                                                                                   |
| `realtime.spec.ts`          | two browsers: a user's change appears in the admin's list, profile save notice + presence, streaming fallback without WebSockets, polling when all transports are blocked                                                                                                                                                       |
| `realtime-security.spec.ts` | raw WebSocket attacks: forged / expired tokens, foreign channels, API refusals; a role change cuts the connection in under a second                                                                                                                                                                                             |
| `layouts.spec.ts`           | top bar / side bar / compact side bar: same menus, stored server-side (reload, second session live), axe in light/dark/high contrast and Arabic                                                                                                                                                                                 |
| `incident-settings.spec.ts` | WP-020c: a level added by an admin appears live on a technician's open form; an admin-built template (required impact details, hidden tags, urgency starting value) is used by a technician and named on the record; switching templates asks before clearing; settings screens and the form pass axe in light, dark and Arabic |

**Measurements (on demand, not in CI):** `pnpm --filter @supportx/e2e perf:latency` (200 saves,
commit → other browser, p50/p95/p99) and `pnpm --filter @supportx/e2e perf:load [2000] [200]`
(connections × changes on the users list, CPU/memory of Centrifugo and the fan-out worker).
Results land in `test-results/perf-*.json`.

**Test data (CLAUDE.md rule h, WP-010 rule 11).** `global-setup.ts` makes sure two suite-owned
Keycloak users exist in Demo Company (`e2e.tech@demo.test`, `e2e.admin@demo.test`,
`e2e.limited@demo.test`), gives them a
fresh random password for each run (never stored) and creates 40 requester rows named
`e2e-scroll-NN@demo.test` (`backend/tooling/e2e_fixtures.py`). Only these records are edited.
Seeded users are only signed in (the Arabic user, other@other.test, tech@demo.test).
The roles journey deletes its own `E2E …` roles before and after it runs (holders move to
Requester). `global-teardown.ts` deletes the scroll rows and puts Other Company back on its seeded plan.
