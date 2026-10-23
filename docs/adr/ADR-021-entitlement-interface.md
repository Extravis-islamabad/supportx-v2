# ADR-021: Entitlement interface: providers, route guard, cached plans, locked seat counts

- **Status:** Accepted
- **Date:** 2026-10-23
- **Source:** architecture.md §1.2, §13.1, §13.5, §13.6, §13.8; CLAUDE.md rule f; WP-009
- **Owner:** Haider (Product Owner)

## Context

Rule f needs one real seam: features gated only through `has_feature` / `check_limit` /
`remaining`, identical on SaaS and on-prem, enforced on the server. §13 describes the model and
states but not where plans live in SaaS, how module routes get gated, how limits stay correct
under concurrency, or how the on-prem licence core (WP-013, ADR-009) plugs in.

## Decision

1. **One `licensing` module owns every entitlement question.** Other code uses only its package
   interface; an import-linter contract forbids importing its providers, and an AST guard test
   fails on any deployment-mode reference (`saas`, `on_prem`, provider settings ...) outside it.
2. **Providers behind one protocol, chosen by configuration** (`SUPPORTX_ENTITLEMENT_PROVIDER`):
   `subscription` reads the platform table `tenant_subscriptions` (app role: SELECT of its own
   row only; plans written by platform tooling as the migrator role), `licence_file` reads the
   §13.3 licence. A tenant without a plan is entitled to nothing (fail closed). Unsigned licences
   are accepted in dev/test only; in production the API refuses to start. `LicenceVerifier` and
   `InstallationCheck` ports are where WP-013 plugs in.
3. **State is derived, not stored.** active / grace / read_only / invalid are computed from the
   term (and, from WP-013, the first failed binding check) at every check.
4. **Modules declare `feature=` in `ModuleSpec`**; the registry adds a route guard to every
   module route (feature check for all methods; read-only check for writes; grace headers for
   admins). Exceptions are explicit decorators (`@read_only_exempt`, `@entitlement_exempt`).
5. **Counted limits: owner counts, licensing enforces, under an advisory lock.** Modules register
   usage counters; `reserve_capacity` takes `pg_advisory_xact_lock(tenant, limit)` in the
   caller's transaction, then counts. Database providers read through the caller's session, so a
   lock holder never needs a second pooled connection (a 20-way race deadlocked PgBouncer before
   this rule).
6. **Per-tenant cache in Valkey with generations**, invalidated by `licensing.entitlement.changed`
   (outbox → consumer). Valkey failures fall back to the provider.
7. **Rate-limit budgets scale by edition** through the WP-008 policy-provider hook.

## Consequences

- **Positive:** modules are gated by one declaration; SaaS and on-prem share all enforcement code;
  limits cannot be exceeded by concurrent sign-ins; read-only mode never hides data; WP-013 only
  replaces two objects.
- **Negative:** every guarded request reads the cache (one Valkey round trip). On-prem limits are
  counted per tenant, not per installation (multi-tenant on-prem needs a platform usage counter).
  Default limits and multipliers are placeholders until commercial input.
- **Follow-ups:** WP-013 verifier, fingerprint and 15-minute re-check; usage counters for assets,
  desks, MSP customers and a monthly AI-run meter; UI menus/banners (WP-010/015) and live refresh
  via realtime (WP-011); admin targeting via the policy layer (WP-016).
