### 2026-11-25 — Raise from a CI: `?ci=` on the create forms (lane A)

For lane B's WP-053 S5c Raise menu (rule 8: lane A's create pages). A new incident, request or
change opened with `?ci=<id>` links that CI:

- `useRaisedFromCi` (console) asks for the CI only once the plan is known to include the CMDB:
  while entitlements load `has()` answers yes, and `ci_ids` without the feature makes the server
  refuse the whole create (403 entitlement_required).
- Unknown or unseen (404), unlicensed: nothing shows, nothing is said, nothing is sent.
- Known: a read-only "Configuration item: <name>" line (never the ID, rule d) and
  `ci_ids: [id]` in the create body. The server's `can_link` and feature checks are unchanged.
- Labels: `work_item.field.raised_from_ci` in en, ar, ur.

Tests: console Vitest for the three forms: a known CI by name, a 404 drops it, no CMDB never asks,
change create sends `ci_ids` (and not after a 404), RTL in ar and ur.
