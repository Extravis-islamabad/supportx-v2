# ADR-002: UI library: Ant Design 5

- **Status:** Accepted
- **Date:** 2026-10-22
- **Source:** architecture.md §5, §9.3
- **Owner:** TBC

## Context

The console is data-dense enterprise back-office UI that needs advanced tables, tree selects, cascaders, transfer lists, complex forms, theming, dark mode and RTL for Arabic and Urdu.

## Decision

Use Ant Design 5 with design-token theming, wrapped in `frontend/packages/ui`. Material UI was considered and rejected.

## Consequences

- **Positive:** Most needed components out of the box; tenant branding and dark mode via tokens; built-in RTL.
- **Negative:** Visual identity must be designed originally on top of AntD (never copying SDP screens).
- **Negative:** Heavy-list grid choice is separate (ADR-010).

## Notes

Accepted at bootstrap (architecture.md §19 listed it as *Proposed*); confirm owner at Stage 0 sign-off.
