### 2026-10-28 — WP-020f: resolution, closure, reopen and cancel (lane A)

- Built to the approved plan (~/Desktop/wp-020f-plan.md) with the product owner's change:
  auto-close counts only from when the requester was told, is off by default and cannot be
  switched on while no channel reaches requesters. Defaults in D-107 (pending review).
- Ports for later packages: `register_open_work` (WP-020e, WP-030), `register_requester_channel`
  and `resolution_notified` (WP-023/024/028; lane B has the follow-up on its WP-023 list).
- Also: ToneTag falls back to the neutral tone for an unknown tone instead of taking the page
  down (the load-dependent "reading 'color'" Vitest failures); `docs/specs/parity/mvp-build-plan.md`
  WP-043 gets the database-level `updated_at` stamp (product owner).
