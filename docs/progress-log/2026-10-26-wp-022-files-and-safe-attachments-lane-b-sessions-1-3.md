### 2026-10-26 — WP-022 files and safe attachments (lane B, sessions 1–3)

- Built WP-022 in `../supportx-v2-wp022` (branch `feat/wp-022-files`) as planned and approved
  (D-082, ADR-028); see the WP entry for what each session delivered.
- Decision renumbered from D-081 to D-082 when merging main (lane A recorded D-081 meanwhile).
  Migration 0018 follows lane A's 0017: one head.
- Found: the console announcements test is flaky under full parallel load (passes alone,
  pre-existing, not touched here). Real clamd flags EICAR only at the start of a file; the fake
  scanner in tests now matches that.
- Follow-ups: an administrators' per-tenant data-key rotate action (optional); Urdu
  `limit.storage_gb` (limits have en/ar only, like the other limit labels).
