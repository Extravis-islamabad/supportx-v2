### 2026-11-09 — WP-049a session 5: loans, returns, due and warranty notices (lane B)

On branch feat/wp-049a-s4 with session 4, pushed as a backup; one PR from main after #216
merges (coordinator). Migration 0114 (coordinator).

- **Loanable and loans (REQ-AST-029, 030), 0114:**
  - `assets.loanable`, set in bulk from the list's selection ("Make loanable");
  - a loan takes only loanable assets in an in-stock state, moves each in use and gives it to the
    borrower (holding history), with a due time in the future and an optional comment;
  - one open loan per asset is enforced by the database (`uq_asset_loan_items_out`, a unique
    partial index), so two loans racing for one asset never both win (coordinator condition 1;
    `test_two_loans_racing_for_one_asset_never_both_win`);
  - `GET /assets/loanable` makes the same three checks for the new-loan picker.
- **Returns (031):** some or all of a loan's assets, to stock or to repair (repair needs a
  comment); the last return closes the loan; an asset on loan is refused for disposal.
- **Notices (059):**
  - due and overdue to the borrower and the loan's creator, warranty ending to the asset
    managers within `asset_settings.warranty_notice_days` (Appendix A: 30; on the asset
    settings screen);
  - each claimed by one `UPDATE ... RETURNING` (coordinator condition 2): two workers at once
    send one notice (`test_due_and_overdue_notices_go_out_exactly_once_with_two_workers`), and
    a warranty date is noticed once (a changed date again).
- **Screens, live (rule c):**
  - console `/assets/loans`: open loans, overdue first, borrower, assets, since, due back,
    status; New loan and Take back dialogs; refreshed by `assets.loans_changed`;
  - portal My assets: "Due back <date>", red once overdue (`loan_overdue`, worked out on the
    server), refreshed on the borrower's own channel;
  - built from shared page parts only, so they move onto lane C's UI pass 3 list template.
- **Tests:** `tests/db/test_asset_loans_api.py` (8, including RLS and the realtime route), the
  console and portal unit tests, and `e2e/tests/asset-loans.spec.ts`. The e2e needs a stack
  with 0111-0114, so it first runs in CI on the PR (the shared stack runs main).
- **Open:** REQ-AST-017 AC4 (disposal certificate file) waits for record attachments on assets;
  030's display ID, department borrower, site and filters, and 032 (booking ahead), to WP-049b.
