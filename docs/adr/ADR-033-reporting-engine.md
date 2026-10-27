# ADR-033: Reporting engine — a reporting port, PostgreSQL first through a read-only role, ClickHouse later

- **Status:** Accepted
- **Date:** 2026-10-27
- **Source:** WP-035 (plan: ~/Desktop/wp-035-plan.md); architecture.md §6.10, §7.3, §8, §14.2;
  docs/specs/parity/09-reports-dashboards.md REQ-RPT-001, 002, 006, 009; ADR-008, ADR-029; D-052,
  D-070, D-100
- **Owner:** Haider (Product Owner)

## Context

Reports, dashboard widgets and counters must show only what the viewer may see, with the same
scopes as lists (REQ-RPT-002, D-052), and must never slow down incident saves (REQ-RPT-006).
ADR-008 chose ClickHouse at scale with a PostgreSQL fallback. MVP runs on-prem on one node
(D-070), where architecture §14.2 makes ClickHouse optional, and modules may never query each
other's tables (CLAUDE.md rule e).

## Decision

1. **A reporting port** (`app/shared/reporting`). A module that owns a reportable entity registers
   a `SourceProvider` at startup. For a subject it returns a `ReportingSource`: **the module's own
   list query with its scope filter already applied**, the list's filter allowlist (custom fields
   included), and which fields can be grouped and how their values are labelled. The analytics
   module only replaces the columns with groupings and aggregates and adds the report's filter;
   it never removes the scope filter and never names another module's tables. A report can
   therefore never count a record the viewer could not list, and drill-down is the same list with
   the same filter (REQ-RPT-037). This is the ADR-029 pattern (search port, scope stays in the
   module).
2. **Measures live in analytics**, declared over field names of the source, so each standard
   measure has one definition (REQ-RPT-004).
3. **PostgreSQL is the MVP reporting store** (D-100 D1). Report transactions run as `supportx_app`
   switched with `SET LOCAL ROLE` to **`supportx_report`**: NOLOGIN, NOBYPASSRLS, SELECT only on
   the tables migrations grant it (`grant_report`), checked by the RLS guard. Each transaction is
   read-only and carries a `statement_timeout` (Appendix A: 30 s interactive, 15 min background),
   so the database cancels it at the limit whatever SQL the compiler produced.
4. **Own pool.** Reports use a separate small pool (`reporting_pool_size`, default 4 + 2), so a
   burst of reports cannot take the connections saves need. `reporting_database_url` points it at
   a read replica on HA profiles (CloudNativePG's `-ro` service); unset, it uses the main database
   (single node). No code branches on the deployment profile (rule f).
5. **Single node meets REQ-RPT-006 by role and limits** (D-100 D2): separate role, separate pool,
   statement timeout, a per-tenant cap on concurrent heavy reports, and a load test showing saves
   stay within target. A replica is required only on HA profiles.
6. **ClickHouse at V1** behind the same compiler as a second dialect, loaded from events
   (REQ-RPT-007, ADR-008). Definitions do not change.

## Consequences

- **Positive:** permissions are inherited, not copied; one number for "open incidents" across
  lists, reports, widgets and counters; reports cannot write or run forever; nothing extra to run
  on a single node or the dev machine.
- **Negative:** on a single node, reports share the primary's CPU and I/O (bounded by the pool,
  the timeout and the concurrency cap). The role must exist before migration 0027 runs; the
  bootstrap (`make db-migrate`, the deploy migrate Job) creates it, and a DBA-managed database
  must create it by hand (docs/deployment.md).
- **Negative:** each owning module writes a small provider (lane A writes the incident one).
