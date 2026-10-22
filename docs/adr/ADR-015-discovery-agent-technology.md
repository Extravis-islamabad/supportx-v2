# ADR-015: Discovery agent technology

- **Status:** Open
- **Date:** 2026-10-22
- **Source:** architecture.md §2.13, §6.9, §19
- **Owner:** Haider (Product Owner)

## Context

SupportX needs its own inventory agent (Windows, macOS, Linux) replacing the Endpoint Central agent, with low footprint, offline caching and signed auto-update.

## Decision

Recommendation: evaluate reuse of the AgentX agent first; otherwise build a new Go agent (single static binary). Not yet decided.

## Consequences

- Go is not in the current approved stack; a new agent requires product-owner approval of the language.

## Notes

Open in architecture.md §19; decision required before the dependent work starts.
