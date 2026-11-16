### 2026-11-13 — The sign-in service degraded, not critical (ADR-051, lane B)

- **Scope:** ADR-051, approved by the coordinator for the product owner: a Keycloak outage must
  stop new sign-ins only, never take the application away from people already signed in. No
  migration, no new dependency.
- **Built:**
  - **Readiness:** the Keycloak probe is informational; `/api/v1/ready` stays 200 and lists
    `keycloak` under `degraded`. PostgreSQL, Valkey and NATS stay critical; an unconfigured
    Keycloak stays critical (configuration error).
  - **Circuit breaker** (`identity_access/infra/breaker.py`) on every BFF back-channel call to
    Keycloak (discovery, keys, token, logout): a connection error, timeout or 5xx opens it for
    15 s, calls then fail at once; one trial call after the cool-down; refusals (400/401) never
    open it. Per process, in memory, injected monotonic clock.
  - **Sign-in:** `/auth/login` with Keycloak unreachable and `/auth/callback` when the code
    exchange is unavailable send the browser back with `?auth_error=sign_in_unavailable`; the
    label now says sign-in is temporarily unavailable and signed-in people can keep working
    (en, ar, ur). The login state is stored only after Keycloak's address is known.
  - **Sign-out:** ends the SupportX session at once as before; with Keycloak unreachable,
    `identity_access.keycloak_session.end_pending` (user ID, Keycloak session ID, no token) goes
    into the outbox with `user.logged_out`, and the consumer
    `identity_access__keycloak_session_end` ends that Keycloak session through the admin API
    (`DELETE /sessions/{id}`, identity service account) when it answers, audited as
    `session.keycloak_ended` (ended / already ended / gave up after an hour / refused / not
    configured). The dead cookie stays meanwhile, so the next sign-in in that browser asks for
    the password.
  - **Keycloak failover recovery:** `connectTimeout=10&socketTimeout=60&tcpKeepAlive=true` on
    its JDBC URL in every profile; golden file updated. Probes unchanged: tuning them waits for
    the restart diagnostics.
  - Docs: ADR-051, deployment.md (readiness), authentication.md (failure table), event schemas.
- **Tests:** readiness (Keycloak failing → ready, degraded), breaker (fail fast within 15 s, one
  trial after, refusals never open it, 5xx opens it), BFF login/callback redirects, logout with
  Keycloak down (session gone, /me 401, pending event without a token, password asked next
  time), the consumer (retried while down, ends and audits once up, a repeated event skipped,
  gives up after an hour with an audit entry), console SessionGate message.
- **Open:** monitoring rules that alerted on API unreadiness should alert on
  `degraded: [keycloak]`; Keycloak probe tuning after the restart diagnostics.
