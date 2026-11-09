### 2026-11-05 — WP-049a session 1: the asset catalogue (lane B)

- New `assets` module (§6.1, no ADR): catalogue domain rules, service, API under
  `/api/v1/assets`, events, realtime broadcast, ModuleSpec and an import-linter contract.
- Migration 0080: life cycles, states, life-cycle moves, product types, products and asset
  settings, all with RLS FORCE. Life cycles got a stable `code` (coordinator: every seeded row
  has a code that logic, events and the API use, never shown in the UI).
- Appendix A defaults are seeded for each tenant the first time its catalogue is read: 35
  product types under four top-level types, seven states (on loan and disposed are system
  states), 21 moves (back to stock from retired needs `assets.reinstate`), the standard life
  cycle and the settings.
- D-141 applied: category (IT or non-IT) and kind are set on top-level types and flow down,
  including when a type moves. Price and tax are stored apart, the total is computed, and
  `cost_includes_tax` defaults to on.
- Refusals carry codes and params (`{{used}}` for a state or type still in use); history
  through `record_changes`; audit actions `asset.*`; labels in en/ar/ur.
- Console `/admin/assets`: product types as a tree (codes never shown), products paged by the
  server with price, tax and total, states, life cycles with their moves, and settings. Every
  write sends If-Match or an Idempotency-Key, and another admin's change arrives live.
- D-141 and D-142 recorded.
- Tests: domain unit tests; 11 API tests on real Postgres (seed, permissions, tree, products,
  states, life cycles, moves, validation, history/outbox/audit, realtime, RLS on six tables);
  5 console tests. Service coverage 93 %.
- Moved: the minimal `procurement` vendors piece goes to session 2, with the asset record that
  first needs it.
- Also this session: #221 fixed the Valkey first-start stall from 4110820b (only pod 0 waits, and
  only while no peer answers), which had turned the HA job red on every PR.
