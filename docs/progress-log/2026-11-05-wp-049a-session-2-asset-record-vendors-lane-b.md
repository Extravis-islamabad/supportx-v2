### 2026-11-05 — WP-049a session 2: the asset record and vendors (lane B)

- **Vendors (REQ-PUR-001):** the minimal `procurement` module, migration 0081. vendors.view
  (technicians by default), vendors.create (inline adds), vendors.manage. An inactive vendor
  can't be picked on new records but stays on old ones; a vendor that records name can't be
  deleted (409 with the count, through `register_vendor_usage`).
- **The asset record (REQ-AST-001, 002, 004, 007, 008):** migration 0082 and /api/v1/assets.
  - Tags come from the nearest type pattern up the tree, else the tenant's, each counting on its
    own and never reused; a typed tag is kept.
  - Tag and serial are unique ignoring case, trash included, and the refusal names the holder.
  - Search covers the name, every identifier and the custom text. The parser read "AST-12" as
    "ast" and "-12", so identifiers are indexed a second time with their separators as spaces.
  - Vendor and site are checked through their modules.
  - Only IT assets that aren't disposed take a slot of the plan (D-141): reserve_capacity on
    create, restore and a product change; a usage counter feeds the licence page.
  - History, outbox, audit, the trash, and live list and record channels.
- **Custom fields on assets:** migration 0083 adds `asset` to the entity check (live check, only
  `asset`). metadata's `index_sql` leads with `type` only on work_items; lanes A and C were told.
- **Console:** /assets, /assets/:id with fixed Details and History tabs, /assets/vendors; en/ar/ur.
- **Rule 5h:** 0080's downgrade dropped tables unconditionally; 0080-0083 now refuse per tenant
  while data exists, and a migration test covers 0080.
- **Also this session:**
  - #224: the second Valkey race. NOGOODSLAVE now ends pod 0's hand-over wait; the new test
    fails on main and passes with the fix.
  - #225: the coordinator's CI change. The Valkey and HA cluster jobs follow deployment paths,
    not the full-ci label.
  - #223: the REL-024 AC2 duty-preview port.
  - Reviews: #219's named-approver fix; #220 (bulk approvals; 0096/0097 downgrades fixed by
    lane A after review).
- **Tests:** 8 asset and 6 vendor API tests on real Postgres, domain tests, 4 console tests, the
  0080 migration test. All green locally.
