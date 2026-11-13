### 2026-11-13 — Lane B polish 6

On branch fix/lane-b-polish-6 (worktree supportx-v2-polish6), from main. No migration, no new
dependency.

- **e2e sign-in wait:** `signIn` waited for the user menu after the Keycloak password step with
  Playwright's 5 s default, and a cold first console load in CI missed it (realtime-security
  @smoke setup, run 43423076862). One exported constant, `FIRST_LOAD_AFTER_SIGN_IN_MS` (30 s),
  now bounds that post-callback wait in `signIn` and in the specs' own post-callback waits
  (sign-in security, invitations, single sign-on, tenant branding). No security or timing
  assertion changed.
- **Route-permission map:** `@public_route` endpoints that take the BFF's `CurrentSession`
  (`/auth/me`, `/auth/logout`, `/auth/sessions`, `/auth/switch-tenant`, `/auth/account-action`)
  show as `session (BFF)` instead of `public`, found from the route's resolved dependency graph.
  The permission guard is unchanged; map regenerated.
- **CI backup store:** `ci-backup-store.sh up` starts a stopped store again instead of
  re-creating it, which removed its volume (the archive and the SSE key).
- **Database egress rule:** `networkPolicies.egress.database` selects `cnpg.io/cluster` in
  `<release>-pg` and `<release>-pg-restore` only, not every CloudNativePG cluster in the
  namespace; the restore runbook says to keep that restore name while the allow-list is on.
- **values.yaml:** the breached-password ConfigMap note now says a list above 1 MiB needs a data
  image.
- Already on main from polish 5, so not redone: ci-metrics' `unread` count for runs whose jobs
  can't be read, and chart-lint's check that the external-database refusal names
  `postgresql.external.caSecret`.
