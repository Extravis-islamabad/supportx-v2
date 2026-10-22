# ADR-007: Multi-tenancy: shared schema with PostgreSQL RLS

- **Status:** Accepted
- **Date:** 2026-10-22
- **Source:** architecture.md §3 P4, §7.2
- **Owner:** Haider (Product Owner)

## Context

Tenant isolation must not depend on every query remembering a WHERE clause. Large or regulated customers may need dedicated databases. On-prem runs a single tenant.

## Decision

Shared database, `tenant_id` on every business table, PostgreSQL row-level security driven by `SET LOCAL app.tenant_id` per transaction. Dedicated-database placement is supported without code changes. Departments (ESM) and MSP customers are partitions inside a tenant enforced by the permission layer.

## Consequences

- **Positive:** An application bug cannot leak data across tenants.
- **Negative:** App DB role must not own tables or bypass RLS; pooling (PgBouncer transaction mode) requires SET LOCAL inside each transaction.
- **Negative:** Every table needs an RLS policy and an isolation test.

## Notes

Accepted at bootstrap (architecture.md §19 listed it as *Proposed*). Owner set by D-007 until a tech lead is appointed.
