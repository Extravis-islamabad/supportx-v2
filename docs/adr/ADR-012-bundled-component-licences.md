# ADR-012: Bundled component licences (MinIO, Grafana, Redis)

- **Status:** Open
- **Date:** 2026-10-22
- **Source:** architecture.md §5 licence box, §19
- **Owner:** Haider (Product Owner)

## Context

On-prem installs redistribute third-party components. MinIO and Grafana are AGPL; Redis 7.4+ moved to non-OSI licences. Source-available and AGPL licences need legal approval.

## Decision

- **Redis — resolved (D-011, via D-004):** Valkey (BSD-3-Clause, Redis-compatible) replaces Redis everywhere.
- **MinIO and Grafana — open:** legal review before the first on-prem release; alternatives exist if needed.

## Consequences

- Any other non-permissive component found later is added to this ADR.
- Code and config reference Valkey, never Redis-only features.

## Notes

Open in architecture.md §19 for MinIO and Grafana; decision required before the first on-prem release. Redis part resolved 2026-10-22 (D-011).
