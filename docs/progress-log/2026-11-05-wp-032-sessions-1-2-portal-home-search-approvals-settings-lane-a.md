### 2026-11-05 — WP-032 sessions 1-2: portal home, search, approvals, settings, announcements (lane A)

**Scope:** REQ-PRT-002, -003, -004, -005, -006, -008, -009, -031. PR #220 (draft). Numbers 0096,
0097, D-143.

**Built**
- Backend:
  - `GET /portal/summary`;
  - `GET /catalog/items/popular`, through service_catalog's new `register_request_counts` port,
    which work_items answers;
  - the portal service request's `resolution_due_at` (only when due times are shown);
  - `POST /service-requests/approvals/decisions` (≤ 20, each through `decide()` in a savepoint,
    one audit entry each);
  - `GET /service-requests/my-approvals/decided`;
  - `origin` on inbox entries;
  - `work_item_portal_settings` with GET and PATCH `/portal/settings` (audited old and new,
    field history, `work_items.portal_settings_changed`).
- Announcements (lane C's module, their request and review):
  - `announcement_dismissals` and `announcement_follows` (RLS);
  - PUT `/dismissal`, PUT and DELETE `/follow`;
  - `dismissed` and `following` on the feed;
  - `announcements.personal.changed` to the person's channel;
  - a notification RecordSource (`announcement.updated`, `announcement.ended`) for followers,
    with the audience checked at send time.
- Portal:
  - the home;
  - `/search` in the admin's order;
  - shared item cards with "needs approval";
  - what happens next after submitting;
  - the inbox's bulk approve, decided list and delegated tag;
  - attachments on the item form;
  - Follow on announcements;
  - banners dismiss through the server;
  - settings reload live.
- Console: Admin › Portal, every setting in groups with explanations, in the setup map with
  keywords.

**Checks:**
- ruff, mypy (1001 files), import-linter;
- backend unit tests (1486);
- DB tests for the portal home, settings, bulk approvals, announcements (personal and existing),
  migrations, portal requests and catalog (all pass);
- tsc, eslint, prettier, labels (65), console (514 + 1), portal (35), ui (147).

**Reviews:**
- Lane C approved the announcements part after one fix (audience at send time).
- I reviewed lane C's #219 (0095 fits file 05; 0098 breaks nothing here).
