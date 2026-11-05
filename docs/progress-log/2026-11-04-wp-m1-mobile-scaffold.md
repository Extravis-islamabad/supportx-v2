### 2026-11-04 — WP-M1 mobile scaffold (D-145)

- **Version change:** npm showed Expo SDK 58 (React Native 0.88.1, React 19.3.0) as the stable
  release since 2026-09-29, while the 2026-11-03 plan named SDK 57. The product owner chose SDK 58.
  The decision approved as "D-112" was renumbered to D-138, then to D-145, because main had taken D-112 and D-138 first.
- **mobile/:** its own pnpm project (`nodeLinker: hoisted`, `link:` to api-client, labels and ui).
  Expo Router with three routes: index (redirect), server, about.
  - Server address screen: an https-only address check (http in development builds only), then
    `GET /api/v1/health`, then the address is saved in SecureStore.
  - About: server, live status (refreshed every 30 s), server and app versions.
  - Language picker (en/ar/ur): right to left through the root view's `direction`, no restart.
  - Own small components on the shared tokens. iOS and Android only (no web build).
  - Checks: ESLint (strict type-checked plus the SupportX label rules), Prettier, tsc strict,
    Jest (jest-expo and Testing Library).
- **Shared packages:**
  - api-client: `setApiOrigin()` and `currentApiOrigin()` (a live `api` binding; the web is
    unchanged), and a `ClientApp` type that includes `mobile`. Nothing reads `window.location`
    at import any more.
  - ui: `@supportx/ui/tokens`, with no antd import; theme.ts takes its radius, light surfaces and
    shade helpers from it.
  - The `react` peer is widened to `^18.3.1 || ^19.3.0` in api-client and labels.
  - The `mobile.*` labels live in the `shared` label module, in en, ar and ur.
- **Repo:** Makefile `mobile-install-check`, `mobile-lint`, `mobile-typecheck` and `mobile-test`,
  run by `setup`, `lint`, `typecheck`, `test`, `check` and `format`. A `mobile` CI job.
- **Checks:** see the WP-M1 session report. Not run on this Windows machine: `make` and `uv` (not
  installed), so the backend tests, a full `make check` and an emulator or device build.
- **First run on a device (iPhone, Expo Go, 2026-11-05):** connected to the local API at
  `http://192.168.18.35:8000`. Two fixes were found on the way:
  - Expo SDK 58 installs its own native `fetch`, and its `FetchResponse` does not extend the
    global `Response`. The api-client middleware returned the response from `onResponse`, so
    openapi-fetch's `instanceof Response` check threw after every 200. The middleware now
    returns nothing, and a regression test covers it.
  - On a Windows checkout the PostgreSQL init script had CRLF line endings, so the dev database
    and roles were never created. `.gitattributes` now forces LF for `*.sh`.
