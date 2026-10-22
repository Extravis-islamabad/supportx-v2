# ADR-004: Workflow and timer engine: Temporal

- **Status:** Accepted
- **Date:** 2026-10-22
- **Source:** architecture.md §5, §6.7
- **Owner:** Haider (Product Owner)

## Context

SLA timers, approvals, escalations and visual workflows are long-running and must survive restarts and failovers without drift. Cron and Celery chains are not durable enough.

## Decision

Use Temporal (Python SDK). Visual workflows are stored as a JSON DSL and executed by a generic interpreter workflow; each node type is an activity. SLA timers are one Temporal workflow per work item.

## Consequences

- **Positive:** Durable timers and long-running workflows out of the box.
- **Negative:** Temporal server and its persistence must be bundled for on-prem, including single-node.
- **Negative:** Workflow code must respect Temporal determinism rules; workflow versioning needs discipline.

## Notes

Accepted at bootstrap (architecture.md §19 listed it as *Proposed*). Owner set by D-007 until a tech lead is appointed.
