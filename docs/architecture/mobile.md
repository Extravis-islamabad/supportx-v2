# Mobile app — implementation plan

Status: **approved** (D-138, 2026-11-03; SDK 58 instead of 57 by the product owner on 2026-11-04): dependencies, React 19.3 for mobile only, the sign-in hand-off design, and a 12 h session (same as web). **WP-M1 (scaffold) done 2026-11-04; WP-M2 (sign-in) built 2026-11-05**; WP-M3 is next. Screens follow the prototype (D-139).
Scope: the technician and admin app (architecture.md §9.1, D-004, D-065), used to see, create and move tickets.

## Context
`mobile/` holds only a placeholder README. architecture.md §9.1 calls for iOS and Android apps for technicians and approvers. They must share the TypeScript API client, labels and design tokens with `frontend/`, and keep an offline queue. D-065 puts the mobile app in V1, and D-004 approves React Native. This first app is for admins and technicians to **see, create and move tickets** (move means status, assignee, group and priority changes on incidents).

The stack must work with the backend **as it is today** (user requirement). A backend scan found:
- **Cookie-only auth.** The opaque session is `__Host-supportx_session` (`supportx_session` in dev), stored in Valkey and AES-GCM encrypted. Requests also need `X-CSRF-Token` from `GET /api/v1/auth/me`. No inbound bearer, PAT or API-key path exists (`backend/app/modules/identity_access/service/auth.py:425-450`).
- **Web-only login.** The BFF login (`bff/routes.py:141-216`) does PKCE with confidential Keycloak clients `supportx-console` and `supportx-portal`. The redirect is always `<web origin>/api/v1/auth/callback`, and the session is delivered only as `Set-Cookie`.
- **A missing `Origin` header passes CSRF** (`service/auth.py:481-483`). `X-SupportX-Client: mobile` is already accepted (`shared/history/history.py:23`).
- **Realtime tokens are reusable.** `POST /api/v1/realtime/connection-token` and `/subscription-token` return plain Centrifugo JWTs, which a WebSocket client can use.
- **Not built yet:** no native Keycloak client, no app redirect hand-off, no device or push registration. Sessions are 12 h absolute (7 days at most).

## Versions (latest stable, rechecked on npm 2026-11-04)
- **Expo SDK 58** (stable since 2026-09-29), which pins **React Native 0.88.1** and **React 19.3.0**. Hermes V1 and the New Architecture are on by default. Node 24 (`.nvmrc` 24.22.1).
- The 2026-11-03 check named SDK 57 (React Native 0.86.3, React 19.2) and missed that SDK 58 had shipped; the product owner chose SDK 58 on 2026-11-04.
- Packages are pinned to the SDK's own versions (`expo/bundledNativeModules.json`). Releases younger than a day are refused by pnpm's release-age policy, so the lockfile holds the 2026-10-31 SDK 58 patch set (`expo` 58.0.22); `npx expo install --check` moves them on.
- TypeScript stays on 5.9 (D-014), although the SDK 58 template ships 6.0.

## Tech stack (user chose Expo with local builds, no EAS cloud)

| Concern | Choice | Notes |
|---|---|---|
| Framework | Expo SDK 58 + `expo-dev-client`, Continuous Native Generation (`expo prebuild`) | Builds run locally or on our CI. No EAS Build, EAS Update or Expo push relay, so on-prem and air-gapped work (rule 5f). |
| Language | TypeScript 5.9 strict + `noUncheckedIndexedAccess`, extends `tsconfig.base.json` | |
| Navigation | Expo Router (file-based, built on React Navigation) | Deep links for the auth callback and for push taps. |
| Server data | TanStack Query 5 (shared) + `@supportx/api-client` (openapi-fetch, generated types) | Same contract as the web apps (P2). |
| Offline | TanStack Query persist (`persistQueryClient`) + paused mutation queue, stored in `react-native-mmkv` | §9.1 offline queue. Replays keep `Idempotency-Key` and `If-Match`, and a 409 opens a conflict screen. |
| Realtime | `@supportx/realtime` + `centrifuge` (shared) | Pauses and resumes on `AppState` changes, and refetches on resume (§8.3). |
| Client state | Zustand | Holds the server URL, active tenant and UI prefs. |
| Forms | React Hook Form + Zod + `@hookform/resolvers` | Reuses the problem-details mapping logic. Antd field components are not used. |
| Labels / i18n | `@supportx/labels` (i18next) + `expo-localization`; RTL through `I18nManager` | English and Arabic from day one, Urdu later (rule 5d, D-006). |
| UI | Our own small component kit on RN primitives, driven by design tokens taken from `@supportx/ui/theme.ts` | Antd can't run in RN. Original design (parity rule). |
| Lists | `@shopify/flash-list` | For long ticket lists. |
| Animation / gestures | `react-native-reanimated` 4.7, `react-native-gesture-handler` 3.3 (SDK 58 pins) | Swipe actions to move tickets. |
| Auth | `expo-web-browser` (`openAuthSessionAsync`), `expo-linking`, `expo-secure-store` | See the auth design below. |
| Rich text | Show sanitised HTML with `react-native-render-html`; the first version edits plain text | Server-side `nh3` sanitising already exists. |
| Dates / icons | `dayjs` (shared), `@expo/vector-icons` | |
| Push (later work package) | `expo-notifications` with **native device tokens** sent straight to FCM/APNs | Not Expo's push service. |
| Scanning (later) | `expo-camera` barcode | For assets later. |
| Tests | `jest-expo` + `@testing-library/react-native`; Maestro for e2e | Vitest has no proper RN support. |
| Lint / format | ESLint flat config + `@supportx/eslint-plugin` (no-raw-enum), Prettier (repo config) | |

## Sign-in (built in WP-M2, ADR-039)
Keep the BFF model: Keycloak tokens never reach the device, and the phone holds only the opaque session ID.
1. The app makes a random verifier and opens the system browser at `/api/v1/auth/login?app=console&mobile_challenge=<S256 of the verifier>`. The BFF runs the existing PKCE flow with the existing Keycloak clients; no new client.
2. The callback sets no cookie. It redirects to `supportx://auth?handoff=<one-time code>` (60 s, single use, stored encrypted in Valkey), or to `?auth_error=<code>` on failure. A requester-only person is first sent on to the portal client with the same challenge, so they get a portal session (D-129, D-139).
3. The app calls `POST /api/v1/auth/mobile/exchange {handoff, verifier}` and gets the session ID, which it keeps in SecureStore. A wrong verifier spends the code.
4. Every request sends `X-SupportX-Session: <id>` and, on writes, `X-CSRF-Token` from `/auth/me`. A tenant switch returns the new ID in the same header. Expiry, refresh, logout and the realtime tokens are unchanged. A 401 makes the app forget the session.

Mobile sessions keep the web lifetime: 12 h absolute (D-138).

**Testing on a device in local dev:** Keycloak (`localhost:28080`) and the callback origin (`localhost:5173`, the console dev server, which forwards `/api` and the realtime `/connection` to the backend) must be reachable from the phone as `localhost`. On Android (emulator or USB), run `adb reverse` for ports 5173, 28080 and 8000, and use **`http://localhost:5173`** as the server address, so that live updates work too. Port 5173 must belong to SupportX's console dev server: the dev realm accepts only that callback. iOS needs a dev host the phone can reach, or a Mac with the simulator. Expo Go cannot finish a sign-in, because the `supportx://` return needs the app's own build. Step by step: `mobile/README.md`.

`@supportx/api-client` (done): `setApiOrigin()` for the chosen server, and `setSessionId()` / `onSessionId()` for the session header. Web behaviour is unchanged.

## Repo integration
- `mobile/` is its **own pnpm project** (React 19.3 there, while the `frontend/` catalog pins React 18.3.1).
- It uses shared packages through `link:../frontend/packages/{api-client,labels,realtime}`.
- Metro config: `watchFolders` takes in `../frontend/packages`. `resolver.disableHierarchicalLookup` plus `extraNodeModules` make sure there is **one React and one TanStack Query** (from `mobile/node_modules`).
- Widen those packages' `react` peer to `^18.3.1 || ^19.3.0` (done for api-client and labels in WP-M1; realtime when it is linked in WP-M3).
- Move tokens out of `@supportx/ui/theme.ts` into a plain TS export (no antd import) that the mobile app can import.
- Makefile: add a `mobile` lint, typecheck and test step to `make check`.
- Windows dev: Android emulator plus dev client. iOS builds need a Mac or a macOS CI runner.
- First-run screen asks for the **server address** (SaaS default or on-prem URL). Plan for private-CA certificates on on-prem servers.

## Work packages (one per session)
1. **WP-M1 Scaffold (first session):**
   - `create-expo-app` (SDK 58, TS template) into `mobile/`, then Expo Router, Metro monorepo config and the shared package links.
   - Tokens, labels with en/ar and RTL toggle, lint, typecheck and Jest.
   - A "server address + about" screen calling `GET /api/v1/system/...` health.
   - `make check` wiring, README and PROGRESS.md.
   - No backend change.
2. **WP-M2 Mobile sign-in (built 2026-11-05):** ADR-039, BFF hand-off and exchange with tests, the app's sign-in, Home by side, Me (organisation switch, language, server status, sign-out).
   The screens below follow the prototype (D-139), one role-based app:
3. **WP-M3 Technician: see the work.**
   - Home: KPIs (my open, overdue, due today, unassigned in my group), the MonetX alert card, and "needs your attention".
   - Queue with the Mine, My group, Unassigned and Overdue filters, an SLA chip on every row.
   - Incident detail and conversation.
   - Live updates over realtime.
4. **WP-M4 Technician: act.**
   - Take, Start work and Resolve (a resolution is required): actions in a fixed order, disabled with a reason.
   - Public reply vs private note, plus a photo from the camera (`expo-camera`).
   - Approvals: approve, or reject with a required reason.
   - Alerts (notifications), and the Available / Away switch.
   - If-Match conflicts, and an offline queue for replies.
5. **WP-M5 Requester.**
   - Home with announcements.
   - Report a problem, with knowledge suggestions while typing and a photo.
   - The catalog (manager approval when needed).
   - My requests, with a status timeline, and "Yes, it's fixed" / "Still broken" (reopens).
6. **WP-M6 Push:** device registration API, the notifications channel adapter, deep links into the right record.
7. **WP-M7 Release:** signing, CI Android build (and iOS on macOS), Maestro e2e for en and ar.

## Approvals (granted 2026-11-03, D-138)
- **New dependencies:** expo + expo-router + expo-dev-client, expo-web-browser, expo-linking, expo-secure-store, expo-localization, react-native-mmkv, @shopify/flash-list, reanimated and gesture-handler, react-native-render-html, @expo/vector-icons, jest-expo, @testing-library/react-native, Maestro. Later: expo-notifications, expo-camera.
- **React 19.3 on mobile** (SDK 58) while web stays on 18.3.1.
- **Mobile auth design** (hand-off above) approved; the formal ADR is written in WP-M2.
- **Mobile session lifetime:** stays 12 h absolute, the same as web (tenant overrides as today).

## Verification (WP-M1)
- `pnpm -C mobile lint typecheck test` is green, and `make check` is green.
- `npx expo-doctor` is clean.
- `npx expo prebuild && npx expo run:android` starts on the emulator. The server-address screen reaches the local dev API. Switching the language to Arabic flips the layout to RTL.
- Shared package imports resolve with a single React (no "invalid hook call").

Sources: npm registry (`expo` dist-tags and `bundledNativeModules.json` of the `sdk-58` branch, 2026-11-04), [Expo SDK 57 changelog](https://expo.dev/changelog/sdk-57), [RN 0.86 / SDK 57 release note](https://releases.sh/release/rel_aH7NaXbDXMlY2_I-Ak0D0), [Expo SDK 56](https://expo.dev/sdk/56), [react-native releases](https://releasealert.dev/github/react/react-native)
