### 2026-10-27 — WP-021-FIX merged path, WP-029 part 1 (lane A)

- WP-021-FIX (PR #71): BUG-01..08 and C1..C5 each with a failing test first; main (#72) merged in.
- WP-029 part 1: automation module, business rules, routing, auto-assignment, screens, history
  "why" lines, in-use refusals, availability switch, live updates; the work item reporting
  provider for lane C. Plan defaults recorded as D-097 (no fallback group by default); ADR-035.
- Split: triggers, loop guard and transition hooks moved to WP-029 part 2 (business rules run
  once per save and cannot trigger each other, so part 1 cannot loop).
