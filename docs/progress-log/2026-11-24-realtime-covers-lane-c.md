### 2026-11-24 — Realtime `covers`: no refresh is dropped (§8.3; lane C polish bundle)

The follow-up to #602 (the first-subscribe catch-up). Design approved by the coordinator; lane A
reviewed it as owner of the portal screens, and lane B reviews the lint rule (D-175, CI).

## Found

A channel handler that filtered on message types (`if (m.type === 'x.changed') …`) silently
dropped the `refresh` message: both the first-subscribe catch-up and the older lost-channel
refresh. Roughly 116 files had at least one such hook.

## Done

- **`packages/realtime`:** every channel hook takes `{ covers: QueryKey[] }`. On a refresh, the hook
  calls `refreshQueries` on those keys (as prefixes) before the screen's handler, then hands on the
  message marked `covered: true`. Covers are read through a ref, so a new array each render never
  re-subscribes. `isRefresh` and `ChannelOptions` are exported.
- **`connection.open()`** adds the first listener before subscribing. A client that confirms a
  subscription synchronously had delivered the catch-up to an empty channel. Real Centrifugo
  confirms asynchronously, so production wasn't affected.
- **Lint:** `supportx/channel-covers` (in our eslint plugin) is an error for all new code. Because
  lint runs with `--max-warnings=0`, the files still to convert are listed in
  `channel-covers-pending.json` rather than warned about.
- **Lane C's files converted:** workflows (runs, designer, list, record), knowledge, releases,
  reports, dashboards, AI settings, admin security, announcements, the schedule calendar, the
  console layout, the support banner, and packages/ui. The pending list went from 116 to 93.
- **CLAUDE.md §3:** the D-183 dnspython line, approved by Haider in lane C's session.

## Tests

- `realtime/covers.test.tsx`:
  - a type-filtered handler with covers refetches on a refresh;
  - a new id gives one subscription, with the new key refreshed;
  - the first-subscribe catch-up refetches a covered query with data;
  - without covers, behaviour is unchanged;
  - a record hook with no id refreshes nothing.
  The catch-up case fails without the `open()` fix.
- `eslint-plugin` RuleTester cases for the rule.
- A RunsPage Vitest: a published `refresh` refetches the runs. It failed on main.
- Full console, portal and mobile suites in the heavy slot after part 2. Console was 1,146 of
  1,147: lane A's problems test failed under load, passes alone, and uses the inert client. Area
  suites after part 3 pass.

## Next

Lanes A and B convert their files (split sent by the coordinator). After #606, the reports-home
CMDB tab and two built-ins join this bundle.
