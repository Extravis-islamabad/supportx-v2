### 2026-10-26 — WP-018 session 3 (retention, restore, volume, demo)

- **Built:** see the WP-018 entry. No new dependencies.
- **Merged main:** lane A's migration 0013 came first, so the audit migration is now 0014, and
  lane A's D-075 kept its number, so the WP-018 decisions are now **D-076** (every reference in
  the WP-018 files was renamed). Conflicts in `DECISIONS.md` and `test_auth_bff.py` were
  resolved by keeping both sides.
- **Shared changes:** `useDateTime().formatMonth` (a UTC month); CI sets
  `SUPPORTX_AUDIT_SCALE_ROWS=100000`; new pytest marker `scale`.
- **Tests:** backend 949 passed, 1 skipped (the opt-in volume test), 94.53 % coverage; 7 new
  retention tests on PostgreSQL and SeaweedFS; console 75, ui 38, labels 25. Volume test at 100k
  (in CI on every run): seal, full verification, retention (24 archives, partitions dropped),
  search 13-47 ms, tamper detected at the changed position. The e2e journey `audit.spec.ts` passes
  in CI after three accessibility fixes it found (tag and link contrast, an inline link without
  underline, the empty-table text). Verification is 18x faster after bounding entry lookups by
  time (about 1,000 to about 18,000 entries/s at 100k).
- **Update 2026-10-26:** the 10M workflow ran to the end. Sealing finished but at 875/s (below
  the 1,000/s floor); see the WP-018 follow-ups. The leftover throwaway database was dropped.
- **Not finished here:** the local 10M run stopped after 66 minutes because the whole dev stack
  was shut down by a normal stop request (not by this session, not out of memory). The first 10M
  result comes from the `audit-scale` workflow on GitHub, which can only be started by hand once
  it is on main. The stopped dev PostgreSQL still holds that run's throwaway
  `supportx_test_*` database; drop it when the stack is up again.
- **Seen, not changed (lane A screens):** the incidents and announcements tables show their
  empty-table text in Ant Design's faint placeholder colour, the same contrast problem axe found
  on the Archives tab.
