### 2026-11-25 — WP-057 S6b, the mobile app policy (lane C)

- **Plan:** approved by the coordinator 2026-11-25 (S6b first, migration 0206); storage settled
  with lane B as columns on `identity_settings` with three conditions.
- **Built:** the policy (domain rules, 0206, the Mobile card's own save), enforcement at sign-in
  (AC1 with the tenant's message; MFA on mobile; mobile session limits), switching off ends the
  tenant's mobile sessions, `GET /auth/mobile/policy` for the app's client-enforced parts, the
  console Mobile app card, docs (identity.md, mobile.md).
- **Found and fixed in the first DB run:** mobile sessions need their own `mobile` flag (the
  platform is optional at sign-in); 0206's limits check let a NULL through (BETWEEN on NULL);
  the message column wrote JSON null instead of SQL NULL.
- **Tests:** domain 11; DB policy 7 and the 0206 migration test; test_auth_mobile still green;
  test_*.py 805; Vitest security + conflicts 25.
- **Next:** the draft PR after 0205 lands; S6a after the real-Keycloak spike.
