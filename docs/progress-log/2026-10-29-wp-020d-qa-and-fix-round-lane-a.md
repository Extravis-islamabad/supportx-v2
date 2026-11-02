### 2026-10-29 — WP-020d QA and fix round (lane A)

- QA on main f4caaa2 under the lock: ~/Desktop/qa-wp020d/QA-REPORT.md. The e2e passed, and the
  views, sharing with groups (D-111c), chips, page size, bulk and live list all work.
  Found 3 bugs; BUG-03 (Arabic 390 px clipping) was withdrawn after a re-check (a drawer-animation
  capture). The axe user-menu finding went to lane C (fixed on their header branch).
- Fix branch `fix/wp-020d-qa` from main:
  - BUG-01: every view count follows the changes that move it.
    - Record changes already reach the lists (tests per event type).
    - Personal changes now reach the person's own channel: follow and unfollow (and a
      hand-over that keeps access) and a reply by someone else send `work_items.lists_changed`;
      a manager change sends `users.reports_changed` to the old and new manager (`UserUpdated`
      gains an additive `managers`); a membership change's `access.changed` now recounts too.
    - Views refetch every minute, like the counters (clock-based counts).
    - Documented in docs/architecture/realtime.md.
  - BUG-02: the toolbar is two rows that each fit (view and search; then filters, sort, page
    size, columns), and chips stack under a fixed-width search. Measured at 1470 px (nothing
    moves sideways when a chip is added) and 390 px (no sideways scroll).
