### 2026-11-09 — Dev-only quick sign-in for QA (D-151, lane B)

- `/dev/sign-in` on the local console and portal: one button per showcase persona (administrator,
  technician, team lead, approver, requester, new starter). The routes answer 404 unless the dev
  setting is on and the request is local (loopback, localhost Host, same-origin Origin), and only
  for the showcase tenant.
- Keycloak's password grant, then the normal session path; the second step from each persona's
  dev-only TOTP authenticator, enrolled by the showcase seed (partial import, same user ID).
  A code is never sent twice (a claimed time step), as a wrong one counts toward the lock.
  Refusals are named reasons (labelled), never a 500. Audited as `session.quick_sign_in`.
- Guards: the API refuses the setting and the persona secrets under any profile but dev; the
  chart refuses to render them; no realm the chart renders allows the password grant (the base
  realm stays byte-identical; the dev realm as the chart renders it has the grant off).
- Seed: four new sign-ins, departments with heads, each sign-in's site, department and manager,
  the Service desk lead, the lead's service desk manager role, the showcase session limits.
- Tests: the domain (RFC 6238 vector, local checks, refusals), the API over the fake Keycloak
  (guards, the second step, no reused code, refusals, showcase only, new starter, logout, audit),
  the startup refusal per profile, the chart refusal and every shipped realm, the realm files, the
  seed (idempotent), the real Keycloak in a private container (pre-enrolment, the grant with the
  code, roles and membership restored, re-enrol on a new key), the dev page.
