### 2026-11-10 — Mobile app: #236 review changes and the three-way split (ADR-044, D-159, D-160)

The product owner's and lane B's review of #236 (2026-11-06 and 2026-11-09), applied after
merging the latest main (ADR-044 accepted, #246 CI plan, #247 CLAUDE.md lines, #249 device
sessions and verified-link files).

- **Numbers:** ADR-042 is lane A's change calendar, so the mobile sign-in record is ADR-044 (the
  draft ADR-042 file is removed; main's ADR-044 carries it). D-145 is claimed by lane A and
  D-146 by WP-048b, so the mobile decisions became **D-154** (setup) and **D-155** (one
  role-based app from the prototype). Main then took D-154 and D-155 (and a lane D-156), so they
  became D-157 and D-158 when PR #333 was brought up to date with main. Those were taken too
  (the asset-permissions decision and S4a), so the coordinator assigned **D-159** (setup) and
  **D-160** (one role-based app).
- **Verified return link (ADR-044 item 3):**
  - `SUPPORTX_MOBILE_REDIRECT_URI` replaces `supportx://auth`: the chart sets it to
    `publicUrl` + `mobile.returnPath` (`https://<host>/mobile/auth`); the default is the local
    console (`http://localhost:5173/mobile/auth`). A custom scheme, or a link without a host
    or path, refuses to start (`ADR-044` in the message);
  - the app returns to `<server>/mobile/auth`; `mobile/app.config.js` adds the associated
    domains (iOS) and a verified intent filter for `/mobile/auth*` only (Android) for the
    hosts in `SUPPORTX_APP_LINK_HOSTS` at build time.
- **Session list (ADR-044 item 5, #249):** the login takes `mobile_platform` (ios, android) and
  `mobile_version` (digits and dots, else dropped); mobile sessions record them, and the list
  shows client `mobile` with the platform and version. Web session records are unchanged, so
  the previous release's pods still read them during a rolling update.
- **Session lifetime:** the web's limits until Haider decides; the sign-in screen now says when
  the server ended a session (`mobile.signin.session_ended`, en/ar/ur).
- **No Expo cloud:** `EXPO_NO_TELEMETRY=1` in the Makefile's mobile targets and the CI job; no
  EAS, no OTA through Expo, no Expo push.
- **CI:** the branch's own `mobile` job is dropped for #246's. The mobile targets depend on
  `generated-frontend` (the `no-unsafe-*` lint errors were the missing API types), and the
  mobile job sets up the backend for it. The DB test fixture is now reused as #249 does (the
  `bff` fixture was not found under its import alias, the 9 mobile test errors).
- **Split:** (a) backend sign-in + api-client + error labels + chart, lane B; (b) shared
  packages ui tokens/theme, realtime, mobile labels, lane C (theme values unchanged, so the
  console looks the same); (c) the app, its Makefile targets and CI step, docs.
- **Checks (Windows, worktree):** ruff, ruff format, import-linter green; mypy green except
  `tooling/timing.py` (`fcntl`, Unix only, not touched). Backend: identity_access, settings, CI
  triggers, chart links and error-label tests 222 passed; DB tests (mobile sign-in, device
  sessions, BFF) 70 passed, 2 SSO-test failures from the same `fcntl` import on Windows.
  Frontend lint, Prettier, tsc green; api-client, labels, realtime tests green; ui 195/196
  with one rich-text timing flake that passes alone. Mobile ESLint, Prettier, tsc and Jest
  (25 tests) green. The chart golden file was updated by hand (helm not installed here); CI's
  chart-lint checks it.
- **Not done:** a sign-in on a real device (needs an https dev host with the `.well-known`
  files and the dev build's bundle ID and signing fingerprint, to send to lane B). iOS
  `openAuthSessionAsync` with an https return needs iOS 17.4 or later; to confirm on a device.
