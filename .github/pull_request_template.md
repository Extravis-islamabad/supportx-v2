## What and why

<!-- One logical change (CLAUDE.md §9). Link the work package, e.g. WP-004. -->

## Definition of done (CLAUDE.md §10)

Tick each item, or strike it through and explain why it does not apply.

- [ ] Works in SaaS and on-prem profiles; licensing only via the entitlement interface (no deployment-mode branches)
- [ ] Data shown on screen updates live, with no refresh
- [ ] All visible text uses labels, in English and Arabic, and works in RTL (Urdu too from Stage 2)
- [ ] API documented; permissions enforced; events emitted via the outbox; audit recorded
- [ ] Tests at the right layers (domain, service with Testcontainers, RLS and outbox where relevant, e2e for critical journeys)
- [ ] Dashboards/alerts exist for new services; user docs updated
- [ ] `make check` is green locally (ruff, mypy, tsc, ESLint, Prettier, import-linter, tests)
- [ ] `docs/PROGRESS.md` updated

## Non-negotiable rules touched (CLAUDE.md §5)

- [ ] New tables have `tenant_id`, an RLS policy and an RLS test
- [ ] Editable records have `version`; updates use If-Match; creates accept Idempotency-Key
- [ ] No module imports another module's internals (import-linter contract added for new modules)
- [ ] No new dependency outside CLAUDE.md §3 (or approved and listed below)

## New dependencies

<!-- Name, licence, why. Write "None" if there are none. -->
