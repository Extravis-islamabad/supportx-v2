### 2026-10-28 — WP-029 merged and QA'd (lane A)

- Merged #71 (WP-021-FIX), #75 (private Keycloak for tests), #74 and #78 (WP-029 parts 1 and 2);
  #81 (layout tests wait for fonts) landed through #78. Migration chain …0029 → 0031 → 0025 → 0028.
- The automation e2e journey found and fixed: unlabelled editor inputs, banner links, faint empty
  tables, field lists sorted by internal name; test data leaking between journeys.
- QA round on main with the lock: shared DB got lane C's skipped 0029/0031 (additive, db-guard
  PASS); backend/.env regenerated (old copy kept as backend/.env.before-wp029-qa); Keycloak
  recreated from the main folder. Report: ~/Desktop/qa-wp029/QA-REPORT.md.
