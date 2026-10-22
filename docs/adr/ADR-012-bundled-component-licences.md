# ADR-012: Bundled component licences (MinIO, Grafana)

- **Status:** Open
- **Date:** 2026-10-22
- **Source:** architecture.md §5 licence box, §19
- **Owner:** TBC

## Context

On-prem installs redistribute third-party components. MinIO and Grafana are AGPL; source-available licences need legal approval.

## Decision

Recommendation: legal review before the first on-prem release; alternatives exist if needed. Not yet decided.

## Consequences

- Scope should also cover Redis (7.4+ licence change; Valkey is the BSD alternative already allowed by §5) and any other non-permissive component.

## Notes

Open in architecture.md §19; decision required before the dependent work starts.
