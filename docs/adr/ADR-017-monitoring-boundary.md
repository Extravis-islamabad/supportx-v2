# ADR-017: Monitoring boundary: MonetX owns correlation

- **Status:** Accepted
- **Date:** 2026-10-22
- **Source:** architecture.md §2 intro, §2.14, §4.1, §6.8
- **Owner:** TBC

## Context

SDP depends on OpManager and other products for monitoring. Extravis already owns MonetX. The product plan suggested correlation inside SupportX.

## Decision

SupportX does no network, server or application monitoring and no alert correlation or de-duplication. The `monitoring_integrations` module receives already-correlated MonetX problems (plus a generic alert webhook for other tools), maps each problem to one incident, updates it on change and resolves it on recovery, and syncs MonetX topology into the CMDB.

## Consequences

- **Positive:** Clear product boundary; no duplicated monitoring logic.
- **Negative:** Product-plan items depending on correlation, syslog/SNMP-trap ingestion or live health inside SupportX need re-scoping against MonetX's API.
- **Negative:** A stable MonetX problem and topology API contract is a dependency.

## Notes

Accepted at bootstrap (architecture.md §19 listed it as *Proposed*); confirm owner at Stage 0 sign-off.
