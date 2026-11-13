# ADR-051: The sign-in service is degraded, not critical — Keycloak reported in readiness, a back-channel circuit breaker, sign-in says it is unavailable, sign-out never waits for Keycloak

- **Status:** Proposed (lane B, 2026-11-13; approved by the coordinator for the product owner)
- **Deciders:** Haider (Product Owner), through the coordinator
- **Related:** ADR-018 (liveness and readiness), D-009 (BFF), D-021 / ADR-048 (session records in
  Valkey), REQ-SEC-029 (password again after a timed-out session), audit row 14 (sign-in rate
  limits), docs/architecture/authentication.md

## Context

`/api/v1/ready` is every API pod's readiness probe, and Keycloak was one of its critical checks.
A Keycloak restart, a slow start after a database failover or a network blip therefore took every
API pod out of service: the whole application went away for people who were already signed in.

Nothing needs Keycloak per request. BFF sessions live in Valkey; ID-token keys are cached in
memory; API keys never touch Keycloak; a silent refresh with Keycloak down already keeps the
session (`token_refresh_deferred`). Only signing in, refreshing, signing out (the back-channel
end of Keycloak's session) and the identity admin screens use it.

Three smaller problems came with it:

- with Keycloak down, every back-channel call (a refresh on every request whose access token had
  expired) waited out the full HTTP timeout, holding request slots;
- `/auth/login` answered a browser with a raw 503 problem document (rule 5d);
- a sign-out with Keycloak down ended the SupportX session but left Keycloak's own SSO session
  standing, with nothing to end it later: the next person at a shared computer could be signed
  straight back in as the previous one once Keycloak returned.

## Decision

1. **Readiness.** The Keycloak probe is informational: when it fails `/ready` stays 200 and lists
   `keycloak` under `degraded`. PostgreSQL, Valkey and NATS stay critical. An *unconfigured*
   Keycloak (no issuer set) is still critical: that is a configuration error, not an outage.
2. **Circuit breaker on the back channel** (`identity_access/infra/breaker.py`, used by
   `OidcClient`). Every call to Keycloak's discovery, keys, token and logout endpoints goes
   through it. A connection error, a timeout or a 5xx (from Keycloak or the proxy in front of it)
   opens it for 15 seconds, during which calls fail at once with `IdentityProviderUnavailable`
   without touching the network. After the cool-down exactly one call goes through as the trial
   (concurrent callers keep failing fast); any answer closes it, another failure re-opens it. A
   refusal (400/401 such as `invalid_grant`) is an answer and never opens it. State is per
   process and in memory: each pod learns and recovers on its own, and nothing shared can stay
   open longer than one cool-down. The monotonic clock is injected so tests drive it.
3. **Sign-in says it is unavailable.** `/auth/login` while the breaker is open (or discovery
   fails), and `/auth/callback` when the code exchange finds Keycloak gone, send a browser back
   to its app with `?auth_error=sign_in_unavailable` (the existing BFF error path; the SessionGate
   shows the label); an API client gets the 503 problem with that code. The login state is
   stored only after Keycloak's address is known, so an outage leaves nothing behind in Valkey.
   The label now reads "Sign-in is temporarily unavailable. If you're already signed in, you can
   keep working." (en, ar, ur). The same code is also the fail-closed answer of the sign-in rate
   limits when Valkey is down (audit row 14); the new wording fits that case as well, as signed-in
   people in other tabs keep working once the blip passes.
4. **Sign-out never waits for Keycloak.** The SupportX session ends first, as before (store
   delete, sessions-changed signal, realtime cut, sign-in log, audit). When Keycloak cannot be
   reached, `identity_access.keycloak_session.end_pending` (user ID and Keycloak's session ID)
   goes into the outbox in the same transaction as `user.logged_out`, and the consumer
   `identity_access__keycloak_session_end` ends that one Keycloak session through the admin API
   (`DELETE /admin/realms/{realm}/sessions/{id}`) as the identity service account, which already
   holds `manage-users`. It is retried by the consumers worker (nak with backoff, up to 100
   attempts); a 404 counts as ended; a repeated event is skipped by the worker's claim. Every
   outcome is audited as `session.keycloak_ended` (system actor, object the person):
   done/ended, done/already_ended, done/still_in_use, or failed with `gave_up` (Keycloak still unreachable one hour
   after the sign-out), `refused` (a 4xx other than 404) or `not_configured`.
   Before ending it, the consumer checks the person's live SupportX sessions: when one still
   holds the same Keycloak session (the browser's console or portal shares it, or the person
   signed in again just as Keycloak returned and was handed the same session), it is left alone
   and audited `still_in_use`. A session begun before the person's sessions were ended
   (deactivation) never counts as live.
   Meanwhile the BFF leaves the browser's session cookie in place, now naming a session that no
   longer exists: the next sign-in from that browser is treated as after a timeout and Keycloak
   asks for the password (`prompt=login`, REQ-SEC-029), so Keycloak's surviving session cannot
   sign the next person in before the background end has run.

### Why the admin API and not a stored refresh token

Ending a session through OIDC's logout endpoint needs the refresh token. Keeping it for a retry
would mean a second store of live tokens (Valkey, encrypted, with a TTL as long as the token's
life), a worker able to decrypt it, and a token that still works if anything leaks before the
retry runs. The admin API needs only Keycloak's session ID, which authorises nothing on its own
(using it takes the identity service account), so it can travel in an outbox event: no secret is
written anywhere new, the retry and the audit follow the normal event path, and a redelivery is
harmless (the second delete finds nothing). events.py states this as the one exception to "no
session ID in an event"; the SupportX session ID and every token stay out of events.

Giving up after an hour is safe with the shipped realm when no other SupportX session shares the
Keycloak session: nothing then refreshes it, and its SSO idle timeout (30 minutes) ends it on its
own. When the browser's other app (console or portal) still holds it, that app's refreshes keep it
alive, as they would after a sign-out with Keycloak up only of the app signed out of; it ends with
that app's own sign-out or timeout (lane C's #481 review).

5. **Keycloak's own recovery after a database failover.** Its JDBC URL gets the PostgreSQL
   driver's `connectTimeout=10`, `socketTimeout=60` and `tcpKeepAlive=true`, in every profile, so
   a connection to a primary that vanished without a reset is dropped within a minute instead of
   hanging. Probes are unchanged; tuning them waits for the restart diagnostics.

## Consequences

- A Keycloak outage now means "no new sign-ins and no sign-in admin changes"; everything else
  keeps working, and `/ready` says `degraded: [keycloak]`. Monitoring that alerted on the API
  going unready must alert on `degraded` containing `keycloak` instead.
- During an outage refreshes are deferred per request without waiting for timeouts; access to a
  tenant removed in Keycloak during the outage is only noticed once Keycloak answers again (as
  before, now explicit).
- A sign-out during an outage leaves Keycloak's session alive until the consumer reaches it
  (within about a minute of Keycloak's return at the backoff cap), mitigated by the password
  prompt above. Sessions without a recorded Keycloak session ID are left to Keycloak's idle
  timeout (logged).
- The pending end is written in the same transaction as the sign-out record. If that write fails
  (database down at that moment), the SupportX session is still gone but nothing ends Keycloak's
  session; it lapses at Keycloak's idle timeout, and the password prompt still applies (logged
  `logout_event_not_recorded`).
- `withdraw_sign_in` (a break-glass sign-in refused after the fact) and admin screens keep their
  current behaviour; they run right after Keycloak answered or are admin-only.
- No migration, no new dependency.
