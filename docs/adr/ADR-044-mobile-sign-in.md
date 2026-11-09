# ADR-044: Mobile sign-in through the system browser, a one-time hand-off, and a BFF session

- **Status:** Accepted — Haider, 2026-11-09 (approved in principle 2026-11-06 with the
  conditions below, which this record carries). Lane B wrote it and reviews the backend. The
  mobile team (#236) builds the app.
- **Date:** 2026-11-06
- **Deciders:** Haider (Product Owner), the coordinator, lane B (identity), the Extravis mobile team

## Context

The Extravis React Native app (`mobile/`, #236) signs people in to SupportX. The web apps already
follow D-009 and §11.1: Keycloak with OIDC Code + PKCE through the backend-for-frontend (BFF). The
BFF keeps the tokens; the browser holds only an HttpOnly session cookie, and JavaScript never sees
a token.

A phone app has no same-origin cookie jar we can rely on. It still must never hold Keycloak's
access or refresh tokens. A stolen phone or a malicious app on it must not be able to replay a
sign-in. And the way the sign-in returns to the app (a redirect address) can be claimed by other
apps on the same phone.

## Decision

1. **The same sign-in, in the system browser.** The app opens the BFF's
   `GET /api/v1/auth/login?app=…&mobile_challenge=…` in the **system browser**:
   ASWebAuthenticationSession on iOS and Custom Tabs on Android (`expo-web-browser`
   `openAuthSessionAsync`). Never an embedded web view: the person's passwords, MFA and SSO run
   on Keycloak's pages in the browser they trust. The Keycloak code exchange happens on the
   server, as for the web, and Keycloak's tokens stay in the BFF.
2. **A one-time hand-off code, bound to the app.**
   - The app makes a random verifier (RFC 7636 alphabet, 43–128 characters) and sends only its
     S256 challenge when the sign-in starts. The challenge is kept with the pending login on the
     server.
   - At the end, instead of a cookie, the BFF redirects to the app's return address with a
     hand-off code: 256 bits, stored encrypted, **valid 60 s, single use** (fetched and deleted
     at once, even when the exchange then fails).
   - The app calls `POST /api/v1/auth/mobile/exchange {handoff, verifier}`. The verifier is
     checked in constant time against the challenge. A wrong, used, expired or mismatched code
     gets the same 401 `handoff_invalid`. The exchange is rate-limited per client.
   - A code caught by another app is useless without the verifier, which never leaves the app.
3. **The return address is a verified link.** The redirect goes to an `https://` address on the
   SupportX host that the platform hands only to the SupportX app: a Universal Link on iOS (the
   host serves `apple-app-site-association`) and a verified App Link on Android (the host serves
   `assetlinks.json`). The `supportx://` custom scheme is not accepted as the return address,
   because any app can register it. The address is fixed per installation (settings), never
   taken from a request.
4. **A BFF session, by header.**
   - The exchange returns the BFF session ID. The app keeps it in the phone's secure storage
     (Keychain / Keystore through `expo-secure-store`) and sends it as `X-SupportX-Session` on
     every call.
   - The server treats it like the cookie: same expiry, refresh and CSRF on writes, same logout.
   - A refreshed or tenant-switched session returns its new ID in the same header, only to
     header sessions.
   - The header is redacted from logs. No CORS is configured, so a web page can't send it
     cross-origin. The web apps never set it.
5. **Device sessions are visible and revocable.** Each session records its client (console,
   portal, mobile), platform and app version, when it started, and when it was last used.
   - A person sees their sessions in My account and can end any one of them.
   - An admin with people rights can see and end a person's sessions.
   - Ending one ends that device's sign-in at once, and the next call answers 401.
6. **Wiped on sign-out.** Sign-out calls `POST /api/v1/auth/logout` (ending the BFF session and
   Keycloak's). The app then forgets the session ID and its cached data, also when offline or
   when the call fails. Any 401 makes the app forget the session too.
7. **No vendor cloud.** No Expo cloud services: no EAS cloud builds, no over-the-air updates
   through Expo servers, no Expo push, telemetry off (Haider, 2026-11-06). Push is decided
   separately (lane B's push plan).

## Consequences

- No new token type and no Keycloak client for the phone: the phone is one more BFF client, and
  every policy (sessions, MFA, step-up, preview read-only) applies to it unchanged.
- The host must serve the two link-verification files, so each installation configures the app
  IDs it trusts (iOS team and bundle ID, Android package and signing certificate fingerprint).
  On-prem and air-gapped installations do the same with their own app build.
- The session index (item 5) is new: it is kept with the sessions in Valkey, per user, and
  cleaned when sessions expire.
- Losing a phone: the person or an admin ends that session. Changing the password, or an admin
  ending all of a person's sessions (`end_sessions`), ends it too.

## Alternatives considered

- **Keycloak tokens on the phone** (public client with PKCE, tokens in secure storage): a stolen
  refresh token lives outside our session controls and revocation, and every API would accept a
  second kind of credential. Rejected.
- **An embedded web view for sign-in:** the app could read the person's password and MFA codes,
  and SSO providers block it. Rejected.
- **A custom URL scheme for the return:** any app can claim it. The hand-off would still be safe
  thanks to the verifier, but phishing and denial of sign-in become possible. Replaced by
  verified links.
