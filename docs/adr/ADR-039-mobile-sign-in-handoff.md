# ADR-039: Mobile sign-in through the BFF with a one-time hand-off code

- **Status:** Proposed (WP-M2; the design approved by the product owner in D-138 (4), this
  record written with the build, 2026-11-05)
- **Date:** 2026-11-05
- **Deciders:** Haider (Product Owner)

## Context

The mobile app (D-138, docs/architecture/mobile.md) must sign in with the same Keycloak realm,
the same tenant rules and the same sessions as the web apps. The backend-for-frontend (D-009)
keeps Keycloak's tokens on the server. The browser holds only an opaque session ID in an
HttpOnly cookie, and the OIDC callback is always `<web origin>/api/v1/auth/callback`. A phone
app cannot read a cookie set in the system browser, and Keycloak's tokens must not reach the
device.

D-139 makes the app one app for everyone. Technicians and admins get console sessions;
requester-only people get portal sessions (D-129, REQ-PRT-001).

## Decision

1. **The phone runs the existing browser sign-in.** The app opens the system browser
   (`ASWebAuthenticationSession` / Custom Tabs, through `expo-web-browser`) at
   `/api/v1/auth/login?app=console&mobile_challenge=<S256 challenge>`. Same Keycloak clients
   (`supportx-console`, `supportx-portal`), same callback, same PKCE with Keycloak, and no new
   Keycloak client.
2. **A second PKCE leg protects the hand-off.** The app makes a random verifier, keeps it in
   memory, and sends only its SHA-256 (base64url, 43 characters) as `mobile_challenge`. The
   challenge travels inside the encrypted login state.
3. **The callback ends in the app, not in a cookie.**
   - It creates the session as usual, sets **no cookie**, stores a one-time **hand-off code**
     (256 bits) in Valkey, and redirects to the installation's `mobile_redirect_uri` (default
     `supportx://auth`) with `?handoff=<code>`.
   - The code lives 60 s, is encrypted under a hashed key like sessions, and stands for the
     session ID plus the challenge.
   - The redirect address is set by the operator, never taken from the request, so it cannot
     be turned into an open redirect.
   - Failures go back to the app as `?auth_error=<code>`, and the app shows the code's label
     (rule 5d).
4. **The exchange:** `POST /api/v1/auth/mobile/exchange {handoff, verifier}` returns the
   session ID.
   - The code is spent on the first try, right or wrong.
   - A wrong verifier, a used or expired code, and an unknown code all give the same `401
     handoff_invalid`.
   - Another app that catches the `supportx://` redirect has the code but not the verifier, so
     it gets nothing.
   - Rate limited per network address: 30 a minute, only to keep noise down.
5. **The app sends its session ID in `X-SupportX-Session`**, never as a cookie.
   - The same resolver serves it: expiry, the CSRF token on writes (from `/auth/me`), silent
     refresh, sign-out, tenant switch and the realtime tokens.
   - A cookie, when present, wins, so browsers behave exactly as before. The web apps never see
     the ID (HttpOnly), so the header adds no browser attack path.
   - A tenant switch from the app returns the new ID in the same header and sets no cookie: a
     cookie kept by the phone's HTTP stack would quietly win over the header.
6. **Requesters in the same app.** A requester-only person who signs in through the console
   client is sent to `/auth/login?app=portal` with the same challenge. Keycloak's own session
   stands, so there is no second prompt, and the hand-off then carries a portal session. The
   console is never opened to them (D-129).
7. **Lifetimes as on the web:** 12 h absolute, the tenant's idle limit (D-138 (5)). The app keeps
   the ID in the phone's secure storage (Keychain or Keystore, `expo-secure-store`) and forgets
   it on sign-out or on any 401.

## Consequences

- No new Keycloak client, token type or long-lived device credential. A stolen phone holds one
  session that ends like any other: idle timeout, absolute timeout, sign-out, deactivation, or
  "end all sessions".
- Air-gapped and on-prem installs work unchanged: no Expo or vendor service is involved.
- Testing on a device in local dev needs Keycloak and the callback origin reachable from the
  phone. On Android, `adb reverse` for ports 28080, 5173 and 8000 maps them to the PC. iOS needs
  a reachable dev host, or a Mac with the simulator.
- An installation that changes `mobile_redirect_uri` must ship an app built with the same
  scheme.
