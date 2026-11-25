### 2026-11-25 — WP-053 S6: MonetX health, backend (lane B, 0207)

**Scope:** the first slice of `monitoring_integrations` (§6.1; ADR-017 / D-001: read only).
Plan: plans/wp-053-s6-plan-lane-b.md, approved by the coordinator with four conditions.

**Built:**
- **Migration 0207:** `monitoring_connections`, `monitoring_topology_runs`, `monitoring_devices`
  and `monitoring_links`, each with RLS and an RLS test. It also widens integrations'
  `connector_secrets.secret_type` check with `api_token` (expand only; the downgrade restores it
  and refuses while one remains). Lane A read that part.
- **Connections** under the new `monitoring.manage` (no role defaults; tenant admins), RecentAuth
  on the token, audited, gated by `Feature.MONETX_INTEGRATION` on the server. On SaaS a private
  MonetX shows the labelled "not reachable from SaaS yet" state (D-172).
- **The connectors catalogue:** a category → right override map owned by integrations; monitoring
  registers `monitoring.manage` for MONITORING. A right no module registers stops start-up; a
  category with no entry keeps `integrations.manage_<category>`.
- **Secrets:** only through integrations' public `secret_store` (never its tables). Owner-scoped:
  reads match ref, owner kind and owner ID; only `EXTERNAL_OWNER_KINDS` may store, read or forget;
  info is the type and set time only. Forgotten when the connection is deleted.
- **The MonetX client:** GET only through `shared/egress` with TLS verified; a contract test
  fails on any write verb. OpenAPI fixture plus FakeMonetX (D-172 d).
- **Topology import** (hourly plus run now) through cmdb's public `monitored_*` functions, as the
  sync identity, with `monetx` precedence; unseen devices go stale, then ended (never deleted);
  hand-made relationships kept.
- **Health:** `GET /monitoring/health?ci_ids=` (at most 200), visible CIs only (an unseen CI is
  absent), a 15 s Valkey single-flight cache, a breaker per connection (open: `unknown` with
  `monitoring_unreachable`), rate-limited per tenant; a change emits
  `monitoring_integrations.health.changed` with the state code only.

**Tests:** unit (breaker, state mapping, stale and ended, GET-only); DB 30/30 on a throwaway
Postgres (monitoring files plus the connector catalogue); `tests/test_*.py` 809 passed.

**Open:** the chips (second PR, lane C's design); the token's expiry once MonetX documents one.
