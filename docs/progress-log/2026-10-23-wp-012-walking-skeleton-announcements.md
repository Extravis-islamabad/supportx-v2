### 2026-10-23 — WP-012 walking skeleton (announcements)
- Decisions: D-032 (announcements in a new module, licensed by `incident`, banners in console and
  portal, four-eyes off by default, reasons on unpublish/archive, live publish window, checklist
  not scaffold), D-033 (plain-text body; Urdu for new strings; rich-text editor question before
  Knowledge), D-034 (field history now, hash-chained audit log = WP-018). ADR-024.
- Shared platform pieces: field history (`app/shared/history`, table `field_changes`, migration
  0008; source `ui`/`api` from `X-SupportX-Client`; reasons; history paging; 409s explained with
  `changed_fields` / `changed_by` / `changed_at`); status machines with a fixed action order
  (`app/shared/domain`); `PermissionSpec.defaults` (modules own their built-in role defaults);
  users' calendar filters in their time zone (`X-Time-Zone`, profile zone in `/auth/me`).
- Module `announcements` (migration 0009): RLS tables incl. audience links (same-tenant FKs) and
  tenant settings; service with scope checks before and after every write, history and outbox in
  the same transaction; API (list with DSL, trash, feed, settings, CRUD, publish / unpublish /
  archive / reopen with reasons, restore, history); action states with reasons and `can_manage`;
  requester read path (live-for-me public view, everything else 404); four-eyes as a SoD rule.
- Live: staff list and record channels (presence); ID-free tenant broadcast for banners and the
  portal; scheduled windows go live by a client timer from `next_change_in_seconds` (no
  scheduler). Console: list (filters, sort, trash, four-eyes switch), record (fixed actions,
  disabled with tooltip reasons, reason dialog, edit form with live notice and 409 "who changed
  what", History tab), create; banners in console and portal; portal home lists the feed.
- Follow-ups done: (a)+(b) relay purges expired idempotency keys and consumer records > 30 days
  (min 7, enforced by relay-only RLS policies, migration 0010); (c) time zone; (d) `make check`
  runs `CI=true pnpm install --frozen-lockfile` first; profile PATCH writes history and its 409
  says who changed what.
- Found on the way: a transition read the status after the repository had updated the same
  object (history said "draft → draft") → status kept before the update; generic OpenAPI enum
  names (`Status`, `Action`) would collide across modules → `Announcement…`; field codes passed
  through a helper were invisible to the label check (`errors.field.required` had no label) →
  written out literally; `permission_reason.*` and the new reasons merged into
  `action_reason.*` (checked by `tests/test_action_reason_labels.py`); axe: Ant Design's gold
  tag and default danger text fail contrast → severity as a dot + text, theme `colorError`
  darkened (light) / lightened (dark) for every danger control.
- Tests: backend 798 (announcements API 25 incl. 10k performance, domain 21, status machine 6,
  housekeeping 2, fixture tool, labels); Vitest 138; Playwright 24 journeys (6 new: two-browser
  live + 409 + reasons, scheduled publish 1 min ahead on a second browser, requester visibility in
  Arabic RTL, site-scoped technician, tenant isolation, axe light/dark/RTL). 10,000 rows: p95
  9.2–11.8 ms for every list and the feed.
- Dev data: migrations 0008–0010 applied to the dev database (new tables and policies only); the
  fan-out and consumer workers restarted to load the module; the suite's E2E records are
  hard-deleted by `tooling/e2e_fixtures.py delete` (also run once by hand: 10 history rows of the
  suite user `e2e.tech`).
- Follow-ups: ~~owner picker in the form~~ and ~~E2E role teardown~~ (done in WP-012b); portal
  announcement page; delete API for sites/groups; layer contracts for the older modules; history for
  role and unit changes; `field_changes` partitioning with WP-018.
