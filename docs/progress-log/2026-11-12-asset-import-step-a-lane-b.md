# 2026-11-12: asset import, step A (lane B)

- **Why:** #434 (S4c) made imports 35-40% faster but missed the 20,000-row targets: dry run
  425 s and run 589 s, against 120 s and 240 s. The coordinator asked for a profile by phase and
  fixes in a follow-up PR.
- **Profile:** about 16 SQL statements per created row, about 1 ms each, none slow.
- **Step A** (assets, licensing hold, identity_access `unrestricted`, shared display IDs):
  27,072 → 14,862 statements for 1,000 rows, dry run plus run. What's left is inserts only
  (Step B). Details in PROGRESS (WP-049b, S4c result).
- **Shared code:** `app/shared/db/display_ids.py` gains `reserve_display_numbers` and
  `return_display_numbers`. They're additive; existing callers are unchanged.
- **Tests:**
  - test_asset_import_batches.py: taken serials and tags per batch, including in-batch duplicates
    and the trash; a batch cut short hands its unused tag numbers back, with no gap;
  - test_entitlements.py: the limit lock is taken once per transaction and again after a
    savepoint rollback (pg_locks);
  - test_display_ids.py: blocks;
  - test_policy_unrestricted.py.
  Asset, scope, import and limit suites: 58 passed; display IDs 12; tests/test_*.py 529.
