# ADR-008: Analytics store: ClickHouse with PostgreSQL fallback

- **Status:** Accepted
- **Date:** 2026-10-22
- **Source:** architecture.md §4.1, §5, §6.10, §7.3
- **Owner:** TBC

## Context

Dashboards and reports must aggregate hundreds of millions of rows in under a second without loading the OLTP database. Small on-prem installs need a lighter footprint.

## Decision

Use ClickHouse, loaded from events with denormalised facts. Small on-prem installs use PostgreSQL reporting replicas/views instead. The query compiler targets both.

## Consequences

- **Positive:** Sub-second aggregations at scale; OLTP protected.
- **Negative:** Two SQL dialects in the query compiler.
- **Negative:** Analytics data is eventually consistent and rebuildable from PostgreSQL and the event log.

## Notes

Accepted at bootstrap (architecture.md §19 listed it as *Proposed*); confirm owner at Stage 0 sign-off.
