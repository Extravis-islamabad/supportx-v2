### 2026-10-27 — WP-026: custom fields (lane A)

- Built WP-026 (D-087 defaults; the product owner's answers are D-088): metadata module,
  values on incidents, filters, search text, history, templates, admin screen, form, record,
  list filter, index worker. Merged main with lane B's WP-027; migration 0021 follows 0020 and
  rebuilds the search vector with the custom field text.
- The 2 skipped backend tests are the opt-in volume and load checks (audit scale, file
  uploads); nothing to fix.
- Tests: 14 backend database tests for custom fields, 1 in search, 46 metadata domain tests, 9
  index-failure unit tests, 9 Vitest tests, one two-user Playwright journey (green in CI).
- Local Vitest timed out on first renders while containers outside SupportX loaded the Docker
  VM (load average 47); the same tests pass alone and in CI.
