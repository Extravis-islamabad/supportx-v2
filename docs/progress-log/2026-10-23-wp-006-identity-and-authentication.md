### 2026-10-23 — WP-006 identity and authentication
- Part A: role/grant definitions now live once in `backend/tooling/sql/*.sql`, run by both the dev
  stack's PostgreSQL init (psql) and `tooling/db_bootstrap.py` (tests, CI). Proven with
  dev-reset → dev-up → dev-check → db-migrate. D-021 (cryptography), D-022 (openapi-typescript).
- Keycloak: realm export `deploy/compose/keycloak/supportx-realm.json` imported on dev-up
  (Organizations on, confidential `supportx-console` / `supportx-portal` clients with PKCE S256,
  `supportx_organizations` + `supportx_roles` claims, password policy, brute-force protection),
  orgs Demo Company / Other Company (`tenant_id` attribute), six test users (one Arabic, one
  multi-org, one without org). Client secrets are generated into `.env` and injected.
- BFF (`identity_access/bff`): /auth/login, /callback, /logout, /me, /switch-tenant. ID tokens
  verified (RS256 via JWKS + issuer/audience/expiry/nonce). Sessions in Valkey, AES-256-GCM,
  hashed keys; opaque HttpOnly SameSite=Lax cookie (`__Host-` + Secure in production); new ID on
  login and tenant switch; idle/absolute timeouts; silent refresh (refused → session ends);
  synchronizer CSRF token + Origin check; back-channel Keycloak logout. Browser login failures
  return to the app with `?auth_error=` (translated), API clients get problem details.
- Users table (migration 0002, RLS, guard passes), JIT provisioning, `supportx_stamp_actor`
  trigger fills created_by/updated_by from `app.user_id`. Tenant context now comes from the
  session; `X-Tenant-ID` only with SUPPORTX_DEV_TENANT_HEADER=true in dev/test, never production.
  Readiness checks Keycloak.
- Frontend: generated `api-client/src/schema.ts`, `apiFetch` (CSRF header on unsafe methods),
  `useSession`/`useLogout`; ui `SessionGate` (login redirect, user locale → RTL) and `AppHeader`
  (name, tenant, sign out) in console and portal; labels en/ar (+ur for auth basics).
- Tests: backend unit (domain, crypto, JWT, fake IdP), DB tests for the full BFF flow, real-Keycloak
  integration tests (each user, JIT, logout ends both sessions, Other Company isolation, no-org 403,
  production ignores the header, brute force + password policy); Playwright login journey; all
  run in CI (stack-smoke on auth/deploy PRs and nightly). Verified by hand in Chrome as well
  (fixed a header contrast bug and a raw-JSON error page found that way).
- Follow-ups: tenant switcher UI (endpoint exists); Keycloak production hardening (WP-014);
  auth audit events with the outbox (WP-007); `errors.field.*` labels (WP-010).
