# ADR-001: Modular monolith with separate deployables

- **Status:** Accepted
- **Date:** 2026-10-22
- **Source:** architecture.md §3 P1, §4.1, §6.1
- **Owner:** TBC

## Context

A small team must build a very broad product. Microservices from day one would slow delivery for years, while some components (realtime, workers, AI, discovery, licensing) have different scaling or runtime needs.

## Decision

The Core API is a FastAPI modular monolith of domain modules (§6.1) with strict boundaries enforced by import-linter. Realtime gateway, async/Temporal workers, AI gateway, discovery service and licence service are separate deployables from the start.

## Consequences

- **Positive:** One deployable for business logic, simple transactions, fast refactoring.
- **Positive:** A module can later be extracted into a service without rewriting its callers.
- **Negative:** Boundaries must be policed in CI (import-linter).
- **Negative:** Modules never import each other's internals or query each other's tables.

## Notes

Accepted at bootstrap (architecture.md §19 listed it as *Proposed*); confirm owner at Stage 0 sign-off.
