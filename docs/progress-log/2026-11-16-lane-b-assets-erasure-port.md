### 2026-11-16 — Lane B: assets erasure port and the person-column guard

The readiness check of 2026-11-14 found assets holding person data with no erasure port (#517
made it required). This adds it, as the coordinator approved on 2026-11-16:

- `assets.references` (160): the person comes off open audits' auditor lists; their future
  bookings are cancelled (the module's own cancel, with its event).
- `assets.owned` (545): open assignments and loans **stay open** (ending them would invent a
  return). `owner_user_id` is the asset's current holder, the same fact as the open assignment,
  so it stays too. The asset managers get one required notice (`asset.erased_holder_items`,
  event `assets.erased_holder.items`) listing the assets to recover; sent once per person,
  claimed in `processed_events` so a resumed or repeated run never sends it twice.
- identity_access: `register_holdings` / `person_holdings`; the erasure detail shows
  `holdings` (counts only) for requested and approved erasures. Assets reports open
  assignments and open loans.
- Pending acknowledgements stay (the module has no cancelled state); past bookings, finished
  loans and the `*_by` columns keep the ID.
- `REQUIRED_PORTS`: `assets.references` and `assets.owned` replace `assets`;
  `tests/erasure_pending.py` keeps only `service_catalog`.
- Guard test: every module whose tables name a person registers an erasure port or appears in
  `ERASURE_EXEMPT` with a reason (licensing: audit columns only; metadata: an admin ID;
  service_catalog: pending).
- Tests: the DB test covers holdings before approval, kept holdings, bookings, audit seats, the
  one notice, a second run counting zero and tenant B.
