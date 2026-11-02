### 2026-10-27 — WP-017-FIX and ADR-031 (lane B)

- The product owner approved WP-017 and accepted ADR-031 (D-093): a separate domain worker
  provisions certificates; never from an air-gapped install.
- Fixed BUG-01..09 in `../supportx-v2-wp017fix` (branch `fix/wp-017-qa`), each with a failing
  test first. Checked in a real browser too: the fix branch's console on a second dev server
  (port 5183) against the shared API, axe clean in light, dark and high contrast; BUG-08 on a
  throwaway Keycloak 26.8.1 (name shown, markup escaped, axe clean in four variants).
- Housekeeping with lane A's OK: the 8 QA uploads purged (files service purge, audited
  `file.purged`), the shared Keycloak container recreated (`--no-deps keycloak`). Numbers agreed:
  D-093/D-094, ADR-036 and migration 0024 for lane B; D-095 for lane A.
