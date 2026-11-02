### 2026-10-26 — WP-020c: incident settings screens and templates

- **Built:** see the WP-020c entry. Decision D-083 (defaults per D-074; renumbered from D-082 when merging main, lane B took
  it). Migration 0019 on top of lane B's 0018 (renumbered when merging main) (applied to the dev database). PR #56.
- **No new dependencies.** Shared changes: `users.form_density` (identity_access, BFF `/auth/me`),
  `display_ids.last_number` / `set_next_number`, the console frame listens to
  `work_items.settings_changed`, `@supportx/api-client` `incidentSettings.ts`, e2e cleanup of
  "E2E" templates and pick-list values.
- **Tests:** backend 1015 passed, 1 skipped (coverage 94.3 %); Vitest console 109 (13 new);
  Playwright `incident-settings.spec.ts` 3/3. Full e2e run: 38/40 locally; `qa-fixes` BUG-04
  passed on two reruns (flaky under load); `branding` login logo fails on the dev Keycloak (realm
  theme state, not this branch).
- **Slow tests (over 5 s, measured while the e2e suite ran in parallel):** event relay throughput
  10k (26 s), audit jobs seal/anchor/verify (24 s), 100k list p95 (19 s), commit→consumer latency
  (14 s), filtered list 100k (12 s), brand assets generation (9 s), audit retention archive
  (7.5 s), OpenAPI export (6.7 s), two parallel relays (6.4 s), and the incidents API tests whose
  *setup* (two orgs with roles, sites and groups) takes 6-22 s under load. Timeouts unchanged.
