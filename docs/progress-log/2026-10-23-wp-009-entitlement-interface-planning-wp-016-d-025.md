### 2026-10-23 — WP-009 entitlement interface (+ planning: WP-016, D-025)
- Part A: WP-016 "Authorization policy layer" (§11.2) added before WP-012 (WP-012 now depends on
  it); D-025 records it and that D-030..D-051 are released. WP-008 session-log entry moved to its
  newest-first place.
- `licensing` module (ADR-021, `docs/architecture/entitlements.md`): catalogue as code (3
  editions, 25 features, 5 counted limits, rate multipliers; en/ar labels CI-checked);
  `Entitlement` with derived state active / grace / read_only / invalid (expiry, suspension,
  WP-013 `degraded_since`), maintenance window; licence document parser (§13.3, whole-day UTC
  terms, canonical `signed_payload`). Interface: has_feature, require_feature, check_limit,
  remaining, hold_limit, reserve_capacity, current_state, summary.
- Providers (config `SUPPORTX_ENTITLEMENT_PROVIDER`): `subscription` (migration 0005
  `tenant_subscriptions`, platform table: app SELECT of its own row only, RLS guard allowlist),
  `licence_file` (unsigned accepted in dev/test only; production refuses to start; signed files
  wait for WP-013), `StaticProvider` for tests. Providers read through the caller's session.
- Enforcement: `ModuleSpec(feature=..., usage_counters=...)`; the registry adds a route guard to
  every module route (`app/core/entitlements.py`): 403 `entitlement_required` (params feature),
  403 `read_only_mode` for POST/PUT/PATCH/DELETE (params reason; `@read_only_exempt`,
  `@entitlement_exempt` for exports/health/login), grace headers `SupportX-Licence-*` for tenant
  admins (`TenantContext.roles` added). Technician seats reserved at JIT provisioning under a
  per-tenant advisory lock (`technician_limit_reached`, browser `?auth_error=`); requesters
  unlimited; existing technicians never re-checked. Rate-limit budgets ×1/×2/×4 by edition.
- Valkey cache per tenant with generation counter; `licensing.entitlement.changed` (outbox) →
  consumer `licensing__invalidate_cache`. `GET /api/v1/entitlements` (edition, features, limits
  with usage for staff, state, term; no secrets).
- Guards: AST test fails on deployment-mode references outside licensing; import-linter contract
  "Only the licensing module touches entitlement providers" (proven to break on a planted import).
- Dev: `make db-seed` → Demo Company Enterprise, Other Company Professional with 2 technician
  seats; `make dev-subscription TENANT=.. ARGS=..` changes a dev plan (row + event). Test tenants
  get an Enterprise plan by default; every test app gets a random Valkey prefix.
- Tests: 598 backend (coverage 97.5%), incl. 20-way provisioning race (exactly 5 of 20 at limit
  5), same user ×10 in parallel takes one seat, read-only on every write method, grace headers,
  both providers gating identically, production rejects unsigned licence, cross-tenant RLS on
  subscriptions, end-to-end cache invalidation over outbox → NATS → consumer → Valkey. The race
  test found a real pool-starvation deadlock (provider opening a second connection while holding
  the seat lock); fixed by reading through the caller's session. Verified live on the dev stack
  with real Keycloak logins (seat block, no lock-out, grace headers, read-only, ~1 s plan refresh).
- Follow-ups: UI use of `/entitlements` (menus, banners; WP-010/015) and live refresh via WP-011;
  counters for assets, desks, MSP customers, monthly AI-run meter; installation-wide on-prem
  counts; soft-deleted users must retake a seat on return; WP-013 verifier, fingerprint,
  15-minute re-check; admin targeting via WP-016.
