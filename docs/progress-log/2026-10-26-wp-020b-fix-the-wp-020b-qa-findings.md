### 2026-10-26 — WP-020b-FIX: the WP-020b QA findings

- **Fixed:** BUG-01..10 and C1..C7 (see the WP-020b-FIX entry), plus the D-081 changes. Shared
  changes: `@supportx/realtime` acquire/release, `limited` status, channel and connection retries,
  `@supportx/realtime/testing` (scripted client for app tests); `@supportx/ui` `ToneTag`, `tones.ts`,
  `richtext/direction.ts`, the `connectivity.limited` banner.
- **Not changed:** no new dependencies; no migration; the remembered tab is per browser (D-081).
- **Data:** Tariq (tech@demo.test) removed from QA-Desk A and QA-Site through the admin API (as
  before the QA run); INC-68..71 moved to the trash.
