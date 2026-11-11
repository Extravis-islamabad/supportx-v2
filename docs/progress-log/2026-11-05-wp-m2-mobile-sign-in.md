### 2026-11-05 — WP-M2 mobile sign-in (ADR-044, D-158)

- **Prototype adopted (D-158):** the "SupportX Mobile Prototype" canvas (technician and requester
  screens) becomes one role-based app. Sign-in comes first, so that every later screen uses real
  data. Work packages renumbered to WP-M3..M7 (mobile.md, PROGRESS.md).
- **Backend (identity_access):**
  - `GET /auth/login` takes `mobile_challenge` (S256, checked; otherwise
    `invalid_mobile_challenge`).
  - The callback of a mobile login sets no cookie. It redirects to `mobile_redirect_uri`
    (setting; default `supportx://auth`) with `handoff=<code>`, or with `auth_error=<code>` on
    failure. The code lasts 60 s, works once and is stored encrypted under a hashed key.
  - `POST /auth/mobile/exchange {handoff, verifier}` returns the session ID. A wrong verifier
    spends the code (`handoff_invalid`). It is rate limited to 30 a minute per network address.
  - The resolver also accepts `X-SupportX-Session`; a cookie still wins.
  - A tenant switch made from the app returns the new ID in that header and sets no cookie.
  - A requester-only person is sent on to the portal client with the same challenge, so they get
    a portal session (D-129).
  - New error labels (en/ar/ur).
- **API client:** `setSessionId()` / `onSessionId()`; the session header goes on every call; a
  new ID from the server is kept.
- **App:**
  - Sign-in through the system browser (`expo-web-browser`, approved in D-157) with an
    `expo-crypto` verifier. The session is kept in SecureStore and forgotten on a 401, on
    sign-out and on a server change.
  - Home by side (technician or requester), and Me: organisation switch, language, server status
    and versions, sign-out. The old About screen is folded into Me.
- **Tests:**
  - Backend: 7 new HTTP tests (`tests/db/test_auth_mobile.py`) and 5 domain tests. The existing
    56 BFF tests still pass (63 passed in all).
  - Identity module, label and docs checks: 184 passed. Import contracts: 16 kept.
  - Mobile: 17 tests (`pnpm check` green). api-client: 9. Labels: 65. Frontend typecheck green.
- **Not done:** a sign-in on a real device. Expo Go cannot receive the `supportx://` return, so
  it needs the development build: Android Studio with `adb reverse` (mobile.md), or a Mac.
