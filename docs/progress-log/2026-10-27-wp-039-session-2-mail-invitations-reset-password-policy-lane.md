### 2026-10-27 — WP-039 session 2: mail, invitations, reset, password policy (lane B)

- Built on `feat/wp-039-session2` (stacked on PR #70): see the WP-039 checklist. Decisions
  D-099 (Keycloak's e-mails, done properly) and D-103 (session 2 defaults; reviewed 2026-10-28).
- Proved on a throwaway Keycloak 26.8.1 (`wp039-kc`): the breached list loads (46,941) and
  refuses a listed password that meets every other rule; a short one gets the length message;
  `supportx-realm` sets the policy and `supportx-identity` gets 403; Urdu users see the rules'
  messages in Urdu, right to left; invitation and reset e-mails branded, single use, expiring.
- Tests: backend unit and DB (identity API 29, mail 17, Keycloak set-up 8, theme 12, labels);
  console Vitest (admin 87), portal (reset page). E2E on the shared stack under the QA lock
  (Keycloak recreated, a throwaway database agreed with lane A): `invitations.spec.ts` passes,
  the full suite 51/51. PR #80.
- CI: PR #70's backend job was cancelled at the 30-minute limit (the suite reached 31% of
  tests in 28 minutes; lane A's #71 too); the limit is now 45 (agreed with lane A).
- Found outside scope: the realm's brute-force settings do not match Appendix A (15 minutes,
  doubling) and Keycloak says "invalid username or password" while locked: session 3.
