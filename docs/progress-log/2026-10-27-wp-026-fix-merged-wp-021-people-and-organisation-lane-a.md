### 2026-10-27 — WP-026-FIX merged; WP-021 people and organisation (lane A)

- PR #67 (WP-026-FIX, D-091) merged under standing approval with every check green.
- Built WP-021 on `feat/wp-021-people-org` (plan approved: D-092, ADR-032). Coordinated numbers
  with lane B: D-089/D-090 and ADR-031 and migration 0022 are lane B's (WP-039, WP-017); this WP
  takes D-092, ADR-032 and migration 0023.
- Sign-in behaviour changed on purpose (D-092): two auth tests that expected Keycloak profile
  changes to reach SupportX now prove the opposite; new tests cover linking by email and
  refused contacts. The entitlement test for promotion now promotes in SupportX.
- Raw-SQL test fixtures and the dev seed set `first_name` and the IT desk.
- The first-run question is a banner, not a blocking dialog, so work (and the e2e suite) goes
  on until an admin answers.
