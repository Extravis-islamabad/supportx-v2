### 2026-10-24 — WP-020 session 2: incident screens, editor, two fixes

- **Screens:** `apps/console/src/pages/incidents` (IncidentsPage, IncidentPage, NewIncidentPage,
  StatusActions, assign/take/hand-over dialogs, IncidentHistory, pickers, tags, labels helpers);
  routes `/incidents`, `/incidents/new`, `/incidents/:id`; nav item Incidents.
- **Shared UI:** `packages/ui` RichTextField (Tiptap 3.31.4, lazy chunk), RichTextView,
  `useDateTime`; high-contrast `colorError` darkened for danger buttons (axe). Tags use a coloured
  dot plus normal text (coloured fills failed contrast).
- **Backend:** people and assignees carry the email (`user_contacts`, Area 15 lesson);
  e2e fixtures also remove the suite's incidents and groups.
- **Fixes:** Appearance popover keeps its state across layout/language re-renders (store in
  AppHeader; Vitest + e2e without retry). `helm test` excludes the upstream Valkey auth pod; our
  smoke pod asserts NOAUTH without a password and PONG with it (verified on k3d, revision 7).
- **Labels:** about 105 new keys in en/ar/ur; `requests.*` and `nav.requests` now say "service
  requests".
- **Tests:** backend 876 passed (94.8 %); frontend unit tests all green (incl. 10 incident tests,
  3 popover tests); Playwright 27/27 on the Compose stack; chart lint OK; `make check` green.
- **Dev data:** dev database migrated 0010 → 0012 (expand-only; no existing row changed). The demo
  tenant's incident configuration was seeded on first use (Appendix A defaults). The e2e suite's
  incidents and groups were removed by its teardown (0 left). Dev workers `worker-fanout` and
  `worker-consumers` were restarted so they load the new module. k3d release upgraded to revision
  7 (test template only, same images).
- **Deviations:** following a handed-over incident (D-068) moves to WP-020b with followers
  (D-069); the language choice is a per-browser setting, so the Arabic e2e checks navigate inside
  the app.
