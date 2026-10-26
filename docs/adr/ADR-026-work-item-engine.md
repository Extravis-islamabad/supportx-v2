# ADR-026: Work item engine — one shared table, types as registry entries, history and counters

- **Status:** Accepted
- **Date:** 2026-10-24
- **Source:** WP-020; architecture.md §6.2, §7.1, §7.4, §10; docs/specs/parity/01-work-items-incidents.md; D-051..D-056 (plan decisions D2–D5)
- **Owner:** Haider (Product Owner)

## Context

Incidents are the first of five ticket-like types (incident, service request, problem, change,
release). architecture.md §6.2 asks for one engine so a feature built once (notes, tasks, links,
approvals) reaches every type. WP-020 had to decide how the types share storage, how they plug in,
how per-tenant life cycles fit the existing `StatusMachine`, how display IDs survive a prefix
rename, and how field history records parts of a record (notes, tasks) without colliding with
field edits.

## Decision

1. **One shared `work_items` table** for every type, plus a 1:1 extension table only for a type
   with fields of its own (`work_item_change_details` and the like, later). Every list index starts
   `(tenant_id, type, …)`. Rejected: a table per type (duplicated child tables or polymorphic
   foreign keys, unions for cross-type lists, links and search).
2. **Types are registry entries** (`work_items/domain/types.py`): code, API path, default prefix,
   licence feature, permission prefix, default life cycle, allowed fields. One router factory
   builds `/api/v1/<path>` per type (per-type paths, D3) with its own schemas and permissions
   (`incidents.view`, …), served by the same services. A module can now license each router
   separately (`ModuleSpec.router_features`).
3. **Life cycles are tenant data** (statuses with a fixed *category* — open, paused, resolved,
   closed, canceled — and transitions with a reason mode), seeded per tenant on first use from
   Appendix A. A pure `Lifecycle` (validated, fixed action order, `InvalidTransition` → 409)
   replaces the code-constant `StatusMachine` for work items; announcements keep theirs. Statuses
   are only edited in their values at MVP; structure waits for the designer (D-056).
4. **Display counters are keyed by type** (`WI_INCIDENT`), not by prefix: `next_display_number`
   returns the number, the record stores `display_id` with the prefix it was created under. A
   renamed prefix continues the numbering and old IDs keep resolving.
5. **Field history** (amends ADR-024, D4): new sources `portal`, `email`, `sla`, `integration`;
   child kinds `child_added` / `child_changed` / `child_removed` so parts of a record are recorded
   **without bumping its version**; an `automation_ref` (JSONB, SQL NULL for people) naming the
   matrix, rule, auto-move or agent behind a change; reading in true time order (occurred_at to the
   microsecond, then change ID) through `history_entries`, filterable to people or automation.
   Announcements keep their published history contract (only the old codes).
6. **Visibility for work items** (D-052, D-053): `group` scope also reaches the unassigned queue
   (no group, no technician) of the user's sites (`ResourceType.group_scope_extra`, live list
   channel `…unassigned.{site}`); `own` = requester, on behalf of, or assignee (not the creator). A
   write that would move a record out of the writer's reach returns 409 `would_lose_access` unless
   confirmed, and the confirmed hand-over is recorded in history.
7. **Rich text** is sanitised on the server with nh3 against the editor's allow-list
   (`app/shared/richtext.py`, D-051).

## Consequences

- Service requests, problems, changes and releases are a registry entry, seed data and (if needed)
  an extension table; the shared contract tests run per type.
- The work_items config tables have no DELETE grant: values are disabled, never removed.
- `field_changes` can grow faster (children); partitioning by month (§7.3) remains planned.
- `LiveList` publishes a record to both its old and new audiences; payloads stay IDs and codes.

## Amendment, WP-020b (2026-10-26): followers, the conversation and shared reach

- Followers (`work_item_followers`) and conversation entries (`work_item_conversations`) are child
  tables of the engine, used by every type. Replies and notes do not bump the record's version
  (no 409 for someone editing fields at the same time); the first-response stamp does.
- A follow that `grants_access` (only a hand-over that kept following, D-068) is a per-record
  grant in the **one policy layer**: `ResourceType.shared_scope` adds those records to the scope
  filter for `view` and `add_note` only, so lists, single records, realtime channels and (later)
  search and AI all see it the same way. Editing, assigning and status actions never use it.
- Removing such a follow revokes the person's realtime subscriptions (§8.2).
