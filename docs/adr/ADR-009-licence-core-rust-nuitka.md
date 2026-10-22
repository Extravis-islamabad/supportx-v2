# ADR-009: Licence core in Rust and Nuitka-compiled backend

- **Status:** Accepted
- **Date:** 2026-10-22
- **Source:** architecture.md §13, §13.7
- **Owner:** Haider (Product Owner)

## Context

On-prem licences must be bound to the activated hardware, impossible to edit, and hard to patch out. Shipping Python source would make enforcement trivial to remove.

## Decision

Signature verification (Ed25519), hardware fingerprinting and enforcement live in a small Rust library exposed to Python via PyO3 (`licence-core/`). Production Python services are compiled with Nuitka; binaries verify each other's hashes; images are signed.

## Consequences

- **Positive:** Much harder to tamper with than Python.
- **Negative:** Adds a Rust toolchain and a Nuitka build step to CI.
- **Negative:** Domain code only ever uses the entitlement interface (has_feature, check_limit, remaining).

## Notes

Accepted at bootstrap (architecture.md §19 listed it as *Proposed*). Owner set by D-007 until a tech lead is appointed.
