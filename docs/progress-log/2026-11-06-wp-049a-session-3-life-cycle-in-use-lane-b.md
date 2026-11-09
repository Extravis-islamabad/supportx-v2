### 2026-11-06 — WP-049a session 3: the life cycle in use (lane B)

- **Moves (REQ-AST-012, 013):** an asset moves only along its product type's life cycle (the
  nearest one up the tree, else the tenant's default). A move or a state can ask for a reason,
  a move can list fields to fill and a permission (back to stock from retired needs
  assets.reinstate). Each move is one audited save of `state_id` with If-Match; an IT asset
  leaving disposed reserves its plan slot again (D-141).
- **Copy (REQ-AST-010):** up to the tenant's copy limit (Appendix A: 50). Each copy gets its own
  tag, starts in stock, and drops the serial, barcode and discovered serial; its history names
  the asset it came from.
- **Bulk moves:** up to 100 assets to one state; each one goes through the single move in its own
  savepoint, and the answer lists the ones that couldn't move, and why.
- **Disposal (REQ-AST-017), migration 0108 (coordinator):**
  - `asset_disposals` (RLS) holds date, method, reason, cost, approver. One record per asset,
    made in the same step as the move to the disposed state.
  - The certificate is a file of owner type `asset_disposal`. The file_links check gains the
    type, and no open PR touched it. Whoever sees the asset sees the certificate; managers
    attach one.
  - AC1/AC2: `register_disposal_guard`, for loans (session 5) and licence allocations (WP-052).
  - AC3: a disposed asset changes only with `assets.edit_disposed` (admins only by default,
    coordinator) and always with a reason.
  - AC4 (cost table, TCO) comes with the cost table.
  - The downgrade refuses while any tenant has a record or a certificate (rule 5h).
- **Console:**
  - change state (disabled moves say why), copy, select-and-move in the list;
  - dispose and the disposal record with its certificate;
  - a searching product picker (server search, paging, the current product fetched on its
    own);
  - custom fields in the form and on the record (only changed values sent);
  - the asset's age (REQ-AST-011), computed with the backend's rule and test cases and
    recalculated live when the basis changes.
- **Labels:** en/ar/ur with every Arabic plural form; also `custom_field_entity.asset`, which s2
  missed.
- **Tests:**
  - DB: 5 move/copy/bulk tests and 6 disposal tests (one-step record, field checks, life cycle
    and If-Match, the guard, read-only with reason, RLS);
  - domain tests for the disposal rules;
  - 14 console asset tests, 2 age tests;
  - label, enum, audit-route and OpenAPI checks.
- **Also this session (lane B):**
  - #241: QA6 fixes;
  - #249: device sessions, the API and both UIs (ADR-044 item 5);
  - #257: PEO-14, a blocker;
  - #260: PEO-01 (draft people PR);
  - #262: the CI runner starvation fix (drafts run the fast set);
  - #264: AUD-01;
  - reviews: #233 (history approved; run-as identity approved after three bypasses were
    closed) and #258 (four API additions for settings pages, all taken).
