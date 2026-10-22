# Architecture Decision Records

Format: short MADR (Context, Decision, Consequences, Status). Source: architecture.md §19.
New decisions take the next free number and get a row here. Statuses: Open, Accepted,
Superseded by ADR-xxx.

| ADR | Decision | Status |
|---|---|---|
| [ADR-001](ADR-001-modular-monolith.md) | Modular monolith with separate deployables | Accepted |
| [ADR-002](ADR-002-ui-library-ant-design.md) | UI library: Ant Design 5 | Accepted |
| [ADR-003](ADR-003-event-bus-nats-jetstream.md) | Event bus: NATS JetStream | Accepted |
| [ADR-004](ADR-004-workflow-engine-temporal.md) | Workflow and timer engine: Temporal | Accepted |
| [ADR-005](ADR-005-realtime-gateway-centrifugo.md) | Realtime gateway: Centrifugo | Accepted |
| [ADR-006](ADR-006-identity-keycloak.md) | Identity provider: Keycloak, bundled | Accepted |
| [ADR-007](ADR-007-multi-tenancy-shared-schema-rls.md) | Multi-tenancy: shared schema with PostgreSQL RLS | Accepted |
| [ADR-008](ADR-008-analytics-clickhouse.md) | Analytics store: ClickHouse with PostgreSQL fallback | Accepted |
| [ADR-009](ADR-009-licence-core-rust-nuitka.md) | Licence core in Rust and Nuitka-compiled backend | Accepted |
| [ADR-010](ADR-010-data-grid-heavy-lists.md) | Data grid for heavy lists | Open |
| [ADR-011](ADR-011-custom-function-sandbox.md) | Custom function sandbox technology | Open |
| [ADR-012](ADR-012-bundled-component-licences.md) | Bundled component licences (MinIO, Grafana) | Open |
| [ADR-013](ADR-013-local-llm-model.md) | Local LLM model family and sizing | Open |
| [ADR-014](ADR-014-database-postgresql-only.md) | Database engines supported: PostgreSQL only | Accepted |
| [ADR-015](ADR-015-discovery-agent-technology.md) | Discovery agent technology | Open |
| [ADR-016](ADR-016-remote-control.md) | Remote control | Open |
| [ADR-017](ADR-017-monitoring-boundary.md) | Monitoring boundary: MonetX owns correlation | Accepted |
