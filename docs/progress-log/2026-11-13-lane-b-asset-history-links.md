### 2026-11-13 — Lane B: asset history for later links and unlinks (REQ-INC-015 AC3)

- `assets/service/linked.py` `on_asset_link_changed` now writes a line on the asset for every
  link change, not only links made as the record was raised: "INC-n linked to this asset"
  (`linked_work_item`, new) and "INC-n unlinked from this asset" (old), alongside REQ-AST-045's
  "raised from this asset". The work item already writes its own line (lane A's
  `work_items/service/asset_links.py`), so both records' histories now say it (AC3).
- No migration and no event change: lane A's `work_items.asset_link.changed` already carries
  `change` added/removed and `at_creation`.
- Console asset history renders the new lines; labels in en, ar, ur.
- Tests: test_asset_views_api.py (link and unlink lines named with the record's display ID),
  asset linked-records tests, console asset tests (101).
