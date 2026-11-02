### 2026-10-23 — WP-011 realtime pipeline end to end
- Decisions: D-030 (`centrifuge` client approved), D-031 (navigation layout as a server-side user
  preference, SDP parity). ADR-023 (realtime pipeline). Docs: docs/architecture/realtime.md.
- Backend: `app/shared/realtime` (§8.1 channel names, HS256 connection/subscription tokens,
  Centrifugo server API client, `ChannelSpec`/`RealtimeRoute`/`LiveList` declarations);
  `/api/v1/realtime/connection-token`, `/subscription-token` (policy layer decides),
  `/lists/{list}`; identity_access channels (own, tenant broadcast, user records with presence,
  users and roles lists) and routes; licensing route for plan changes; logout/tenant switch cut
  the old connection. Production now requires the Centrifugo settings.
- `workers/realtime_fanout` (`make worker-fanout`): windowed WP-007 consumer, list coalescing
  (250 ms), per-tenant token bucket, idempotent batch publishes, cache invalidation before
  publishing, revocation by disconnect (code 4000), metrics + heartbeat, reported by /ready.
- Centrifugo dev config: history + forced recovery, presence, SSE/HTTP-streaming fallbacks,
  Prometheus; namespace separator moved so the `t:` names stay as in §8.1.
- Frontend: `packages/realtime` (centrifuge-js; WebSocket → HTTP streaming → SSE → polling;
  shared channels, recovery, presence; hooks), live users list, roles list, access drawer,
  menus, licence banners, profile change notice + presence; reconnecting/polling banner.
- Navigation layouts: top bar (default, More overflow), side bar, compact side bar; stored in
  `users.nav_layout` (migration 0007), follows the user live to other sessions.
- Found and fixed on the way: dark-mode contrast of horizontal menu / "More" selection; a race
  where a plan change could be refetched before the entitlement cache was dropped (now dropped
  by the route before publishing); e2e navigation helpers made layout-independent.
- Tests: backend 739 (tokens, channels, live lists, registry, fan-out merging / rate limit /
  failures, pipeline through NATS, token endpoint attacks); 114 Vitest (incl. 12 realtime);
  Playwright 17 journeys (two-browser live updates, streaming and polling fallbacks, raw
  WebSocket attacks, revocation < 1 s, layouts with axe). Measured: 200 saves p50 153 / p95 275 /
  p99 291 ms; 2,000 connections × 200 changes p50 205 / p95 353 / p99 407 ms, 0 lost; Centrifugo
  ≤ 10 % CPU / 131 MiB, fan-out ≤ 5 % CPU / 91 MB.
- Follow-ups: Prometheus scrape of the worker (WP-014 ingress also routes /connection and
  /emulation to Centrifugo); work-item, dashboard and portal channels as those modules arrive;
  sites/groups lists live in the access drawer; fan-out horizontal scaling (one consumer today).
