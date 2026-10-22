# ADR-011: Custom function sandbox technology

- **Status:** Open
- **Date:** 2026-10-22
- **Source:** architecture.md §6.7, §19
- **Owner:** TBC

## Context

Admins write custom functions (Python or JavaScript) that must run with CPU, memory and time limits, no file system and allowlisted network only, never inside the API process.

## Decision

Recommendation: an isolated runner with gVisor- or Firecracker-class isolation. Not yet decided.

## Consequences

- Choice affects single-node on-prem (k3s) feasibility and kernel/hardware requirements (Firecracker needs KVM).

## Notes

Open in architecture.md §19; decision required before the dependent work starts.
