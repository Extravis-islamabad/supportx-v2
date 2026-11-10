### 2026-11-10 — REQ-AST-025: assets on incidents and requests (lane A)

- **Migration 0127:** `work_item_assets` (RLS, soft-deleted links, one live link per record
  and asset, no FK to asset tables: rule e).
- **work_items `asset_links`:**
  - link and unlink: the edit right, the `assets` feature, `assets.can_see` per asset, at most
    20 per record;
  - history lines name the asset by tag and name;
  - the outbox event `work_items.asset_link.changed` (IDs only), live on the record channel as a
    part change.
- **API:** `GET/POST/DELETE /{incidents|service-requests}/{id}/assets`; `asset_ids` on the
  console create and the portal report.
- **E-mail (AC2):** an e-mailed incident gets the requester's one asset when the tenant's
  `email_include_assets` is on, via `assets.email_includes_assets`, added with lane B's OK.
- **D-153 port:** `linked_asset_ids_select(user_id)` covers records assigned to the technician
  that are open, paused or resolved-not-closed (the coordinator's scope). Lane B wires the
  assets `own` scope and the technician grant on it in their PR.
- **UI:**
  - an asset picker on New incident, New request, the portal's Report an issue and the
    catalogue form; the portal offers only the person's own assets (AC1);
  - an Assets section on incident and request records (removed or hidden assets marked, never
    named).
- **Labels:** en/ar/ur.
- **Tests:** `tests/db/test_asset_links_api.py` (6), `test_asset_links_migration.py`, console
  `assets.test.tsx`, plus the console and portal suites.
