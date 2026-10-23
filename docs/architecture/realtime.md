# Realtime: how a change reaches every screen

Any change saved by anyone (a technician, the portal, a rule, an agent) shows on every screen that
displays it within about a second, with no refresh (architecture.md §8; CLAUDE.md rule c; WP-011;
ADR-023). This page explains how, what is safe to send, and how a new module makes its screens live.

## The path of one change

1. **Save.** The API saves the record and, in the same transaction, writes a domain event to the
   outbox (e.g. `identity_access.user.updated` with the changed field names and the new version).
2. **Event bus.** The outbox relay publishes the event to NATS a few milliseconds after the commit.
3. **Fan-out.** The realtime fan-out worker (`make worker-fanout`) reads the event and asks the
   owning module's *route* where it goes: the record's channel, the list channels of the
   audiences that may see the record, the owner's own channel. Messages for the same list that
   arrive within 250 ms are merged into one ("users 12, 15 and 40 changed").
4. **Gateway.** The worker hands the messages to Centrifugo, which pushes them to every browser
   that joined those channels.
5. **Screen.** The browser looks at the message (what changed, never the data itself) and
   refetches exactly the affected list or record through the normal API, where permissions are
   applied again. If the browser already has that version (its own save) it does nothing.

Measured on the dev stack: commit → other browser p50 153 ms, p95 275 ms (200 changes); with
2,000 browsers following the same list, p95 353 ms and no message lost.

## Channels

| Channel | Who may join | Carries |
|---|---|---|
| `t:{tenant}:user:{user}` | that user only | "your access changed", changes to their own records |
| `t:{tenant}:broadcast` | every signed-in user of the tenant | plan / licence changes (banners, menus) |
| `t:{tenant}:users:{id}` | the user, or anyone who may see that user (`users.view`) | one user record; presence ("also viewing") |
| `t:{tenant}:queue:{list}` | holders of the list's permission at scope *all* | list changes, with record IDs |
| `t:{tenant}:queue:{list}.site.{site}` / `.group.{group}` | holders at *site* / *group* scope who belong to that site / group | list changes for records of that site / group |
| `t:{tenant}:queue:{list}.signal` | holders whose grant has an attribute rule | "the list changed", **without** IDs |
| `t:{tenant}:wi:{id}`, `dash:`, `wall:`, `portal:` | §8.1, as those modules arrive | |

Lists today: `users` (`users.view`), `roles` (`roles.view`). `GET /api/v1/realtime/lists/{list}`
tells a browser which of these channels it should join.

## Security

- **No anonymous joins.** A browser connects with a short-lived connection token
  (`POST /api/v1/realtime/connection-token`, 15 minutes, signed-in users only) and joins each
  channel with its own subscription token (`POST /api/v1/realtime/subscription-token`, 5 minutes).
- **The policy layer decides.** A subscription token is signed only after the module that owns the
  channel says yes, using the same rules as the API (WP-016): another tenant's channel, someone
  else's personal channel, a record or list the user may not see → 403 `realtime_channel_denied`.
  Centrifugo verifies the signature, audience, issuer, expiry and that the token names the channel.
- **Nothing sensitive in messages.** A message holds a type, record IDs, changed field *names*, the
  new version and the ID of who made the change. The data itself is always fetched through the API.
  Audiences restricted by an attribute rule get no IDs at all.
- **Revocation.** When a user's access changes (role given or taken, role edited, site/group
  membership, user disabled, plan changed) their connections are closed with code 4000; the
  browser reconnects at once with fresh tokens and is refused anything it lost. Measured: under
  300 ms after the change. Signing out or switching tenant closes the old connection too.
- **Expiry as a backstop.** Tokens are renewed through the API before they expire, so even a lost
  revocation is limited to the token lifetime.

## In the browser

`@supportx/realtime` keeps one connection per session (WebSocket; if a proxy blocks it, HTTP
streaming, then SSE; if all fail for 10 seconds, the page refreshes what it shows every 15 seconds
and says so in a banner). After a reconnect it replays missed messages from Centrifugo's history;
if too much was missed it refreshes the affected screens instead. Record pages show who else has
them open. `<html data-realtime-status data-realtime-transport>` shows the state for diagnostics.

## Making a new module's screens live, in 3 steps

1. **Say who may join** — in the module's `ModuleSpec(channels=[...])`:
   a `LiveList("tickets", "requests.view").spec()` for each list, and a
   `ChannelSpec(kind="wi", authorize=...)` for records whose `authorize` asks the policy layer
   (`authorize_stored`) and returns `ChannelAccess(presence=True)`.
2. **Say where its events go** — `ModuleSpec(realtime=[RealtimeRoute(event_types, route)])`.
   The route returns `RealtimeEffects`: publications for the record channel and
   `LIST.publications(tenant, "tickets.changed", id, sites=..., groups=..., owners=...)`, plus
   `revoke_users` if the change alters anyone's access.
3. **Follow it on the screen** — `useListChannel('tickets', m => refreshList(qc, keys.list))` on
   list pages and `useRecordChannel('wi', id, m => refreshRecord(qc, keys.detail(id), m))` on
   record pages (it also returns the other viewers for `<PresenceAvatars>`).

Then add a two-browser Playwright test: change in one, assert the other updates without a reload.

**Content that changes by the clock** (a publish window, later SLA timers): store the times,
compute the state per request, and return `next_change_in_seconds` (relative to the server's
clock). Screens call `useRefetchAfter(seconds, query.dataUpdatedAt, refetch)` and refresh at that
moment; nothing has to run on the server at the boundary (ADR-024).

**Audiences you cannot name on a channel** (everyone a record is *addressed to*, e.g. banners for
the requesters of some sites): publish an ID-free message on the tenant `broadcast`
(`announcements.feed_changed`), only when something they could see changed, and let screens
refetch; the API filters by audience. See `app/modules/announcements/service/realtime.py`.

## Operating it

- Run: `make worker-fanout` (dev), the `realtime_fanout` deployment later (WP-014).
- `/api/v1/ready` lists `realtime_fanout` (informational, like the other workers); `make
  events-stats` prints its counters: publications, coalesced, deferred (rate limit), dropped
  (backlog limit), revocations, failures, fan-out lag p50/p95/p99.
- Settings: `SUPPORTX_CENTRIFUGO_API_URL`, `…_API_KEY`, `…_TOKEN_SECRET` (required in production),
  `SUPPORTX_REALTIME_COALESCE_MS` (250), `SUPPORTX_REALTIME_TENANT_PUBLICATIONS_PER_SECOND` (200),
  token lifetimes.
- Measurements: `pnpm --filter @supportx/e2e perf:latency` and `perf:load [connections] [changes]`.
