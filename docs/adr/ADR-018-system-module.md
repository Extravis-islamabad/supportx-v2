# ADR-018: `system` platform module for process health

- **Status:** Accepted
- **Date:** 2026-10-23
- **Source:** architecture.md §6.1, §15; WP-004
- **Owner:** Haider (Product Owner)

## Context

CLAUDE.md §4 forbids new modules beyond the architecture.md §6.1 list without an ADR. WP-004 needs
liveness and readiness endpoints, and the product owner asked for a small example module that
exercises the new module registry (routers, startup hooks, event handlers through one interface).

## Decision

Add `app/modules/system`: a platform module with no tables and no events. It serves
`GET /api/v1/health` (liveness) and `GET /api/v1/ready` (readiness of PostgreSQL, Valkey and NATS),
and it is the reference implementation of the registry contract in `app/modules/README.md`.
It is not a business module and must not grow business features. An admin "dependency health"
status page (§15) may later read from it.

## Consequences

- **Positive:** Health lives in the same module shape as everything else; `main.py` stays generic.
- **Negative:** One module outside the §6.1 list; this ADR is its licence to exist.

## Notes

Accepted with WP-004 at the product owner's request.

WP-007 (2026-10-23): the module also declares the dev-only event logger consumer
(`system__dev_event_logger`, off in production) and reports the event workers' heartbeats in
`/ready`. It still owns no tables and publishes no events.
