### 2026-11-12 — Mobile app: dev quick sign-in (D-163)

On the local stack the mobile sign-in stopped in the browser after Keycloak: Android hands
`/mobile/auth` to the app only through a verified App Link, which `http://localhost` cannot be
(ADR-044 item 3). The product owner chose the web's answer (D-151) for the app too: D-163.

- **API:** `POST /api/v1/auth/dev/mobile/sign-in` (`identity_access/bff/quick.py`). Same guards,
  Keycloak grant, session path and `session.quick_sign_in` audit entry as the web's
  `/auth/dev/sign-in` (shared helper `_quick_session`), audited with client `mobile`. It returns
  the session ID in the body, never a cookie, and answers 404 without `X-SupportX-Client: mobile`
  or with any `Origin` (no web page can post there or read the ID). Hidden from OpenAPI.
- **App:** `mobile/src/screens/DevQuickSignIn.tsx`, shown on the Sign in screen of debug builds
  only (`__DEV__`) when the API lists the personas; nothing shows when it answers 404. Labels are
  the web's `dev_sign_in.*` and `dev_persona.*` (English, Arabic, Urdu already there).
- **Tests:** backend `tests/db/test_quick_sign_in.py` gains 4 tests (11 cases): session ID and no
  cookie, the new starter's set-up link, the guards (no client header, any Origin, non-local host,
  forwarded headers), switched off. Mobile `screens.test.tsx` gains 4: sign-in with the app header
  and no Origin, the new starter, nothing on 404, never in a release build.
- **Docs:** D-163, mobile/README.md (step 5), docs/dev-setup.md (quick sign-in).
- **Not done here:** `make check` was not run end to end on this Windows machine (the backend
  conftest needs `fcntl`); the backend DB tests ran in a Linux container against the dev stack.
