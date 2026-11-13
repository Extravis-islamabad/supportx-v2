### 2026-11-13 — Lane B: Keycloak-degraded alert noted in the audit register

- `docs/architecture/engineering-practices-audit.md` gap 2 (no alert rules) now names the alerts
  ADR-051 (#481) needs: `/ready` degraded with `keycloak` for more than 5 minutes, and the BFF
  breaker open for more than 5 minutes (a per-pod gauge to add with the rules), so they are built
  with the rest of the alerting (the coordinator's request).
