### 2026-10-23 — WP-010 frontend foundation and design system
- Decisions: D-026 (react-router 7.x — 8.x needs React 19 —, openapi-fetch, @axe-core/playwright;
  CLAUDE.md §3), D-027 (Stage 1 WP-017 tenant branding and domains, planning only). Companions
  named for veto: `@ant-design/icons` 5.x (MIT), `@hookform/resolvers` (MIT). i18next 26.5.4 /
  react-i18next 17.1.0 chosen to respect pnpm's minimum release age (no policy exclusion added).
- api-client: openapi-fetch on `schema.ts`; middleware adds X-Request-ID, CSRF, Idempotency-Key
  (POST) and If-Match (from remembered ETags); `call()` → typed `ApiError` (problem details,
  field errors, request ID, outage detection); connectivity events; `queryKeys`; hooks for
  session, tenant switch, entitlements, users (infinite, filter DSL), user, update user.
- labels on i18next + react-i18next (flat keys, CLDR plurals incl. six Arabic forms,
  interpolation, humanize fallback); ~150 new en/ar keys, ur for the shell. ESLint plugin
  `@supportx/eslint-plugin` (`no-raw-enum`, `no-literal-text`; 23 rule tests). Backend
  `test_enum_labels.py`: every enum in the OpenAPI contract needs en+ar labels.
- ui: Extravis theme (#9619B5), light/dark/high contrast, AA-safe secondary text, tenant
  `Branding` override, antd locales; AppShell, header (tenant switcher, user menu, appearance),
  Ctrl+K palette, Coming soon / Not in plan; licence context, grace + read-only banners,
  `WriteButton`; error reporter (toasts + Copy reference), conflict dialog, reconnecting banner,
  error boundary, `createQueryClient`. forms: FormField + applyServerErrors. charts: themed,
  RTL-mirrored ECharts wrapper.
- Console: react-router with lazy routes (Home, 8 sections, Admin › Users, My profile, 404,
  dev-only /dev/components), entitlement-aware sidebar (hidden; locked + upgrade hint for
  admins). Portal: simple top-nav shell. Vendor chunk groups (`vite.chunks.ts`): largest chunk
  726 kB → 416 kB, no chunk over 500 kB.
- Found and fixed via e2e: every login bumped the user's `version` (JIT upsert), so signing in on
  a second device made an open profile form stale → version now moves only when a synced field
  changes (+ test); "keep my changes" re-sent untouched fields and wiped the other user's change
  → PATCH now sends only changed fields; antd secondary text / tags / dark sider failed axe
  contrast → tokens and badges fixed.
- Tests: frontend 102 Vitest (api-client 9, labels 25, ui 13, forms 3, eslint-plugin 23,
  console 25, portal 4); Playwright 8 journeys on the dev stack incl. axe (0 serious/critical on
  home, coming soon, users, profile, Arabic RTL, high contrast, dark); backend 602.
- e2e test data: suite-owned Keycloak users e2e.tech/e2e.admin (random password per run), 40
  `e2e-scroll-NN` requester rows (`tooling/e2e_fixtures.py`, deleted after the run), Other
  Company plan changed and restored with `make dev-subscription`. CI stack-smoke now starts the
  event workers and runs all journeys.
- Follow-ups: initial console download is larger than before (shell uses more of Ant Design;
  ~415 kB gzip) — trim with per-component imports or lazy header widgets; live entitlement
  refresh via WP-011; field-level permission rendering from WP-016; Urdu labels complete in
  Stage 2.
