### 2026-11-06 — WP-049a session 4: ownership, acknowledgement, components, links, groups (lane B)

On branch feat/wp-049a-s4, pushed as a backup; its PR opens from main after #216 merges
(coordinator: WP-049a spans two PRs). Migrations 0111-0113 (coordinator).

- **Holders (REQ-AST-018, 019, 020 for assets), 0111:**
  - an asset is held by a person, a department or another asset;
  - each holding is kept (asset_assignments, one current per asset), never rewritten;
  - an asset is never fitted inside itself or its own children (the domain walks the chain and
    refuses a stored loop);
  - with "follow owner's site", assigning takes the person's own site, and a person's move moves
    their assets with history, through a consumer of identity_access's user.updated (claimed by
    event ID; the site comes through `person_placement`, never identity's tables);
  - `/assets/held-by` lists what a person or department holds or held, within scope.
- **Links and components (026, 027), 0111:**
  - typed links stored once, shown from both ends ("Connected to" / "Connected from"), with history
    on both assets; removable only under one of their own assets;
  - components are fitted assets;
  - disposing an asset that has any answers 409 with their count until the request says detach or
    dispose (the latter with the same record, all or nothing).
- **Acknowledgements and My assets (023, 024), 0112:**
  - a pending acknowledgement per holding of an asset whose type asks for one;
  - only the holder answers, once, and a dispute needs a comment;
  - a dispute never touches the holding or its history (coordinator's condition 3);
  - an `asset` notification source: ack_requested to the holder (public side, link to My
    assets), ack_disputed to the technician who gave it;
  - /assets/mine needs no asset permission;
  - the portal's My assets is live from the person's own channel (IDs only).
- **Groups (028), 0113:**
  - static (filled from the list's selection in one step) or dynamic (a saved filter DSL tree,
    checked when saved, evaluated when shown);
  - counts and lists come from one query within scope;
  - group events go to the tenant's staff screens.
- **For lane A (025):** `GET /assets/picker`, `can_see`, `asset_refs` (gone or hidden marked,
  never named), `assets_of`.
- **Tests:**
  - DB: holdings, nesting, unknown and other-tenant holders, the site follow (twice → once),
    links both ways, components on disposal, acknowledgement flow and history, My assets
    scope, the picker and refs, groups (dynamic after a change, one-step fill, names), RLS on
    every new table;
  - domain tests;
  - console 16 and portal 2 Vitest;
  - label, enum, event-schema and audit-route checks.
- **Also this session:**
  - #216 split, reviewed by lanes A and C and queued;
  - #260 queued;
  - #268 (Temporal in the chart);
  - reviews of #233, #240 and lane C's egress client;
  - the D16 notification shape with lane A.
- **Deferred:**
  - 021/022 with discovery (WP-050);
  - 020's consumables and licences with WP-052;
  - 024 AC2 and 025's forms on lane A's side;
  - REQ-AST-017 AC4 (cost table) with session 5.
