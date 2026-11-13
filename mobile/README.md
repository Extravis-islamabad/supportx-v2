# mobile

The SupportX app for technicians and admins on iOS and Android (architecture.md §9.1, D-004,
D-065, D-157). It is built with Expo SDK 58 (React Native 0.88.1, React 19.3) and shares the API
client, labels and design tokens with `frontend/`. Builds are local only, with no EAS Build, EAS
Update or Expo push relay, so on-prem and air-gapped installs work the same way as SaaS.

Plan (stack, sign-in design, work packages, approvals): `docs/architecture/mobile.md`.

## Status

The prototype's screens are built (D-158): one app, by role.

- **Technicians** see Home (KPIs, a MonetX alert card, needs attention), the Queue (Mine, My
  group, Unassigned, Overdue), the incident screen (Take, Start work, Resolve; public reply vs
  private note), Approvals, Alerts and Me (Available / Away).
- **Requesters** see Home (announcements, report, request), Report a problem (with knowledge
  suggestions), the Catalog, and My requests (timeline, fixed / still broken).
- **Both:** sign-in through the organisation's sign-in page (ADR-044), live updates, and English,
  Arabic and Urdu with right to left.

Still to come: photo attachments, the full knowledge article page, push (WP-M6), offline
replies.

## Run it on the Android emulator (local dev)

Sign-in returns through a verified https link (ADR-044 item 3): `https://<host>/mobile/auth`,
which the host hands only to the app builds its `.well-known` files name. Build with
`SUPPORTX_APP_LINK_HOSTS=<host>` (`app.config.js` adds the associated domain and the verified
intent filter for `/mobile/auth*` only). `http://localhost` cannot be verified, so a device
sign-in needs an https dev host that serves those files; the screens without sign-in run
against the local stack as below. Expo Go cannot finish a sign-in. The
toolchain is set up on `D:Android` (JDK 17, SDK, NDK, the `SupportX_Phone` emulator); there
is no Android Studio.

1. **Backend:** start the dev stack with `make dev-up`, then the API: in `backend/`, run
   `uv run uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000`.
2. **Console dev server on port 5173**, which forwards `/api` and the live `/connection`:
   `cd frontend && pnpm --filter @supportx/console dev`. Port 5173 must be free; stop any other
   project's dev server using it. Keycloak's dev realm only accepts the callback there.
3. **Emulator:** run `emulator -avd SupportX_Phone`, then forward the PC's ports to it:
   `adb reverse tcp:5173 tcp:5173`, `adb reverse tcp:28080 tcp:28080` and
   `adb reverse tcp:8000 tcp:8000`.
4. **App:** in `mobile/`, run `pnpm android`. That builds, installs and starts Metro. On the
   server screen enter `http://localhost:5173`.
5. **Sign in with the dev quick sign-in** (D-163): with the quick sign-in on (`make
   dev-quick-sign-in` and `make showcase-seed`, docs/dev-setup.md), the debug build's Sign in
   screen shows one button per Showcase Company persona, as on the web's `/dev/sign-in`. The
   normal "Sign in" button opens Keycloak but cannot come back to the app on `http://localhost`
   (below).

## Prerequisites

- Node 24 (`.nvmrc`) and pnpm 12 through corepack (`corepack enable`). The version comes from
  `packageManager`.
- `frontend/` installed (`make setup`). The shared packages are linked from there, and their own
  type dependencies come from the frontend install.
- To run on a device: Android Studio with an emulator and JDK 17. An iOS build needs a Mac.

## Commands

Expo telemetry stays off (Haider, 2026-11-06): set `EXPO_NO_TELEMETRY=1` in your shell; the
Makefile's mobile targets and CI set it too. No EAS cloud builds, no over-the-air updates through
Expo's servers and no Expo push service.

```sh
pnpm install --frozen-lockfile
pnpm check          # ESLint, Prettier, tsc strict, Jest (also part of `make check`)
pnpm doctor         # expo-doctor; two of its checks need the Expo API (internet)
pnpm prebuild       # generate android/ and ios/ (never edited, not committed)
pnpm android        # build the dev client and start it on the emulator
pnpm start          # Metro for an installed dev client
```

On the Android emulator the dev API is at `http://10.0.2.2:8000`. Plain `http` is accepted only in
development builds. Release builds require `https`, because the session travels in a cookie
header (§11.1).

## How it fits the repo

- This is its own pnpm project (`pnpm-workspace.yaml` here holds settings only), because the web
  apps stay on React 18. `nodeLinker: hoisted` gives a flat `node_modules`, as Expo recommends.
- `@supportx/api-client`, `@supportx/labels` and `@supportx/ui` are `link:`ed from
  `../frontend/packages`. From `@supportx/ui`, import only `@supportx/ui/tokens`; the rest of it
  needs antd and the DOM.
- Package imports made inside the shared packages resolve from `mobile/node_modules`
  (`metro.config.js` and its twin `jest.resolver.js`). That gives one React, one TanStack Query
  and one i18next. A second React would fail with "Invalid hook call".
- `setApiOrigin()` points the shared API client at the chosen server, and every call sends
  `X-SupportX-Client: mobile`.
- Right to left: the root view's `direction` style follows the language, so no restart is needed.
  Screens draw their own titles, because native headers would not follow that style.
- Visible text goes through labels (`mobile.*` keys in `frontend/packages/labels`). The same
  `no-literal-text` and `no-raw-enum` lint rules as on the web apply here.
