### 2026-10-27 — WP-029 part 2: triggers, loop guard, transition settings (lane A)

- Product owner approved part 1 (D-097, ADR-035). Built part 2 on `feat/wp-029b-triggers`:
  trigger consumer, loop guard, transition settings, record Automation tab, admins' loop
  banner, confirmation before a move; defaults D-102; migration 0028.
- Found while testing: within one event a later trigger re-read the record after an earlier
  trigger changed it and fired on a change it never saw; conditions now use the record as the
  event left it.
- Keycloak sign-in tests moved to a private Keycloak per test process (PR #75, with lane B):
  two lanes' runs no longer race on the shared dev Keycloak.
