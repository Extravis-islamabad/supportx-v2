# Architecture Decision Records

Format: short MADR (Context, Decision, Consequences, Status). Source: architecture.md §19.
New decisions take the next free number and get a row here. Statuses: Open, Accepted,
Superseded by ADR-xxx.
Owner: the product owner owns all ADRs until a tech lead is appointed (D-007).

| ADR | Decision | Status | Owner |
|---|---|---|---|
| [ADR-001](ADR-001-modular-monolith.md) | Modular monolith with separate deployables | Accepted | Haider (Product Owner) |
| [ADR-002](ADR-002-ui-library-ant-design.md) | UI library: Ant Design 5 | Accepted | Haider (Product Owner) |
| [ADR-003](ADR-003-event-bus-nats-jetstream.md) | Event bus: NATS JetStream | Accepted | Haider (Product Owner) |
| [ADR-004](ADR-004-workflow-engine-temporal.md) | Workflow and timer engine: Temporal | Accepted | Haider (Product Owner) |
| [ADR-005](ADR-005-realtime-gateway-centrifugo.md) | Realtime gateway: Centrifugo | Accepted | Haider (Product Owner) |
| [ADR-006](ADR-006-identity-keycloak.md) | Identity provider: Keycloak, bundled (revised: shared realm + Organizations) | Accepted | Haider (Product Owner) |
| [ADR-007](ADR-007-multi-tenancy-shared-schema-rls.md) | Multi-tenancy: shared schema with PostgreSQL RLS | Accepted | Haider (Product Owner) |
| [ADR-008](ADR-008-analytics-clickhouse.md) | Analytics store: ClickHouse with PostgreSQL fallback | Accepted | Haider (Product Owner) |
| [ADR-009](ADR-009-licence-core-rust-nuitka.md) | Licence core in Rust and Nuitka-compiled backend | Accepted | Haider (Product Owner) |
| [ADR-010](ADR-010-data-grid-heavy-lists.md) | Data grid for heavy lists | Open | Haider (Product Owner) |
| [ADR-011](ADR-011-custom-function-sandbox.md) | Custom function sandbox technology | Open | Haider (Product Owner) |
| [ADR-012](ADR-012-bundled-component-licences.md) | Bundled component licences: Valkey, SeaweedFS on-prem, permissive on-prem monitoring | Accepted | Haider (Product Owner) |
| [ADR-013](ADR-013-local-llm-model.md) | Local LLM model family and sizing | Open | Haider (Product Owner) |
| [ADR-014](ADR-014-database-postgresql-only.md) | Database engines supported: PostgreSQL only | Accepted | Haider (Product Owner) |
| [ADR-015](ADR-015-discovery-agent-technology.md) | Discovery agent technology | Open | Haider (Product Owner) |
| [ADR-016](ADR-016-remote-control.md) | Remote control | Open | Haider (Product Owner) |
| [ADR-017](ADR-017-monitoring-boundary.md) | Monitoring boundary: MonetX owns correlation | Accepted | Haider (Product Owner) |
| [ADR-018](ADR-018-system-module.md) | `system` platform module for process health | Accepted | Haider (Product Owner) |
| [ADR-019](ADR-019-event-bus-conventions.md) | Event bus conventions: relay role, subjects, dedupe, dead letters | Accepted | Haider (Product Owner) |
| [ADR-020](ADR-020-api-conventions-storage.md) | API conventions: idempotency in PostgreSQL, signed keyset cursors, Valkey rate limits | Accepted | Haider (Product Owner) |
| [ADR-021](ADR-021-entitlement-interface.md) | Entitlement interface: providers, route guard, cached plans, locked seat counts | Accepted | Haider (Product Owner) |
| [ADR-022](ADR-022-authorization-policy-layer.md) | Authorization policy layer: SupportX-owned roles, scoped grants, one policy service | Accepted | Haider (Product Owner) |
| [ADR-023](ADR-023-realtime-pipeline.md) | Realtime pipeline: per-channel tokens, module-declared routes, windowed fan-out | Accepted | Haider (Product Owner) |
| [ADR-024](ADR-024-announcements-walking-skeleton.md) | Announcements walking skeleton: shared field history, status machines, clock-driven visibility | Accepted | Haider (Product Owner) |
| [ADR-025](ADR-025-deployment-helm-k8s.md) | Deployment: one Helm chart, CloudNativePG, Gateway API, migrate Job per revision, one host with paths | Accepted | Haider (Product Owner) |
| [ADR-026](ADR-026-work-item-engine.md) | Work item engine: shared table, types as registry entries, tenant life cycles, type-keyed counters, history children and automation trace | Accepted | Haider (Product Owner) |
| [ADR-027](ADR-027-audit-log.md) | Audit log: record then seal, per-tenant hash chain built in the database, signed anchors with key rotation, personal data outside the hash | Accepted | Haider (Product Owner) |
| [ADR-028](ADR-028-files.md) | Files: uploads stream through the API, per-tenant envelope encryption, scan before availability, image metadata stripped, real-type blocking | Accepted | Haider (Product Owner) |
| [ADR-029](ADR-029-search.md) | Search: PostgreSQL full-text and pg_trgm behind a search port, scope reused from the lists; OpenSearch and pgvector later as adapters | Accepted | Haider (Product Owner) |
| [ADR-030](ADR-030-custom-fields.md) | Custom fields: definitions in the metadata module, typed JSON values with guarded filter expressions, indexes built on request by the index worker | Accepted | Haider (Product Owner) |
| [ADR-031](ADR-031-tenant-branding-addresses.md) | Tenant branding and addresses: brand in the organization module, public versioned variants, sign-in page branded through the organization in context, the address picks the organization never the access, HTTP-token domain proof; certificates by a separate domain worker, never from an air-gapped install | Accepted | Haider (Product Owner) |
