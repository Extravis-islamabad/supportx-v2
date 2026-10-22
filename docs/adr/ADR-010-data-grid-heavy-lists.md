# ADR-010: Data grid for heavy lists

- **Status:** Open
- **Date:** 2026-10-22
- **Source:** architecture.md §19
- **Owner:** TBC

## Context

List views must page 50 rows with filters and sort in under 300 ms on 10 million rows, and power users expect spreadsheet-like grids.

## Decision

Recommendation: Ant Design Table with virtualisation; evaluate AG Grid Enterprise (commercial) for power-user views. Not yet decided.

## Consequences

- AG Grid Enterprise is commercial and outside the approved stack list; adopting it requires product-owner approval and a licence review for on-prem redistribution.

## Notes

Open in architecture.md §19; decision required before the dependent work starts.
