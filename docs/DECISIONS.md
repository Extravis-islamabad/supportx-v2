# Product owner decision log

Decisions made by the product owner that change or clarify the specs. Architecture-level choices
still live in `docs/adr/`; this log records *who decided what and where it was applied*. New
entries take the next free ID. Specs, ADRs and CLAUDE.md must be kept consistent with this log.

| ID | Date | Decision | Rationale | Affected docs |
|---|---|---|---|---|
| D-001 | 2026-10-22 | Monitoring-dependent features stay in scope: pre/post change health checks, live health on CMDB impact maps, wallboards with monitoring status. SupportX may **read** health, problems and topology from the MonetX API via the `monitoring_integrations` module, read-only. SupportX still performs no monitoring, polling of devices or alert correlation. | Keeps the NOC-native differentiators from product-plan.md §6 without moving monitoring into SupportX. ADR-017 is unchanged. | CLAUDE.md §1, ADR-017 (note), PROGRESS.md |
| D-002 | 2026-10-22 | architecture.md is authoritative over product-plan.md on every conflict, including roadmap timing: architecture.md §17 replaces product-plan.md §10. | One source of truth for engineering. | product-plan.md (banner), CLAUDE.md §1 |
| D-003 | 2026-10-22 | Local Kubernetes uses **k3d**. Not yet installed on the dev machine (Homebrew is also not installed). | Matches k3s used for single-node on-prem (architecture.md §5, §14.2). | CLAUDE.md §3, PROGRESS.md (WP-014) |
| D-004 | 2026-10-22 | Approved stack additions: Rust toolchain + PyO3/maturin, asyncpg, pydantic-settings, Nuitka, OpenFeature SDK, pgvector, PgBouncer, Jinja2 (sandboxed), pre-commit, ClamAV, pgBackRest, **Valkey (replaces Redis everywhere)**, React Native (mobile, later), Go (only if ADR-015 chooses a new agent). | All are named or implied by architecture.md; Valkey removes the Redis licence risk. | CLAUDE.md §3, ADR-012, PROGRESS.md |
| D-005 | 2026-10-22 | Migration from SupportX v1 is out of scope; v2 is a first build. | Focus on the ServiceDesk Plus migration path (architecture.md §18). | CLAUDE.md §2 |
| D-006 | 2026-10-22 | Definition of done: English and Arabic (RTL) from day one; Urdu mandatory from Stage 2. | Arabic is required by primary markets now; Urdu can follow. | CLAUDE.md §5d, §10 |
| D-007 | 2026-10-22 | The product owner owns all ADRs until a tech lead is appointed: Owner = "Haider (Product Owner)". | Every ADR needs an accountable owner. | docs/adr/*.md, docs/adr/README.md |
| D-008 | 2026-10-22 | The clickable prototype (WP-015) is built from the spec with Ant Design defaults; the product owner reviews screenshots. | No designer is assigned yet; unblocks WP-015. | PROGRESS.md (WP-015) |
| D-009 | 2026-10-22 | The BFF login layer lives inside the Core API at `backend/app/modules/identity_access/bff` (same deployable, same origin as the UI). | Fills the gap in architecture.md §11.1 / §4.1; simplest cookie and CSRF model. | CLAUDE.md §4, PROGRESS.md (WP-006) |
| D-010 | 2026-10-22 | Keycloak: one shared realm using Keycloak Organizations for tenants by default; a dedicated realm only for tenants that need custom SSO. | Realm-per-tenant does not scale to large SaaS tenant counts. | ADR-006 (revised), PROGRESS.md (WP-006) |
| D-011 | 2026-10-22 | ADR-012 also covers Redis licensing, resolved by D-004 (Valkey). ADR-012 stays Open for MinIO and Grafana. | Keep licence review scope explicit. | ADR-012 |
