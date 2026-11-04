# ADR-041: Stages for work items, one engine for releases and changes

- **Status:** Proposed (WP-058a session 1, lane C; the coordinator approved building it, lane A
  reviews it, as changes reuse it unchanged)
- **Date:** 2026-11-05
- **Deciders:** Haider (Product Owner), the coordinator, lanes A and C

## Context

Releases (file 06, REQ-REL-014..019) and changes (file 05) move through ordered **stages**:
submission, planning, build and so on. Each stage has its own statuses, and each status still
has one of the five fixed categories (REQ-INC-044). The parity files require the stage model to
be built once in the work-item engine (REQ-WI-026). Releases come first (lane C, WP-058a); lane A
builds changes on it later (WP-045).

The engine already gives every type data-driven statuses (`work_item_statuses`, one category
each) and named-action transitions (`work_item_transitions`, ADR-026). Incidents and service
requests have no stages and must not change.

## Decision

1. **Stages are opt-in per type.** A `WorkItemType` declares `stages` (an ordered seed list).
   Types without stages (incident, service request) behave exactly as today. Nothing in their
   tables, routes or screens changes.
2. **A stage owns statuses.** New table `work_item_stages` (tenant, type, code, sort order,
   label overrides, `system`, `disabled_at`). `work_item_statuses` gains a nullable `stage`
   column; for a staged type every status belongs to exactly one stage. Status codes stay unique
   per type, so repeated names carry the stage in the code (`build_in_progress`,
   `testing_in_progress`), and the shipped labels give the plain name ("In progress").
3. **Two kinds of move, both data.**
   - *Within a stage*, a status is set directly to any active status of the current stage (no
     action enum). A status may require a reason to enter (`work_item_statuses.reason_mode`,
     with an optional reason list).
   - *Between stages*, only allowed moves exist: `work_item_stage_transitions` (tenant, type,
     from stage, to stage, `when_status`, reason mode). `when_status` is optional; when set, the
     move is offered only while the record is in that status (for example testing →
     build on `testing_failed`). Entering a stage sets its first active status (by sort order).
   - Skipping a stage is a move like any other, and requires a reason by default.
   - Cancel is a move to the closure stage's canceled status, allowed from every stage before
     closure. Reopen (closed → review) needs its own permission and a reason.
4. **The past is kept.** `work_items` gains a nullable `stage` column, the current stage.
   `work_item_stage_entries` records each time a record enters a stage: who, when, the reason,
   and when it left. Going back adds a new entry and never rewrites an old one, so a second
   build round shows as a second entry. Stage moves also write field history (`stage`, old and
   new) and emit `work_items.work_item.stage_changed` through the outbox. Planned and actual
   dates per stage (REQ-REL-026) are columns on the entry; they are added in session 4.
5. **The stage rail is computed, never stored.** For each stage in order: *done* (entered and
   left, or passed), *current*, *skipped* (a later stage was entered without entering it) or
   *future*, with its entries' dates. It is served on the record and changes live through the
   record channel (`work_items.stage_changed`).
6. **The same rules on every path.** API, bulk, workflow nodes (WP-048b) and automation call the
   same service functions (`move_stage`, `set_status`), which check the allowed move, the reason,
   required fields per stage (REQ-REL-018, session 3) and stage access by role (REQ-REL-019,
   session 3).
7. **Seeds and edits.** A tenant's stages, statuses and stage moves are seeded on first use from
   the type's declaration: Appendix A of file 06 for releases, file 05 for changes. Admins edit
   them later (REQ-REL-015, session 3). Seeds never overwrite a tenant's edits: defaults are
   applied at read time, as everywhere else.

## Consequences

- Changes (lane A) declare their stages, statuses and moves in `domain/types.py` and get the
  rail, the history and the checks with no engine work.
- A staged type does not use the named actions of `WorkItemAction` for status changes: its
  record page shows stage moves and the statuses of the current stage instead. Shared features
  keyed on status categories (SLA pause, final records, lists, reports) work unchanged, because
  every status still has a category.
- Reports can group by stage and by status category (REQ-REL-014 AC3). Each record counts once,
  by its current stage.
- Migration 0090 adds the tables and columns. Existing rows get NULL stages and are unaffected.

## Alternatives considered

- **Stages as a second status field with its own action enum.** It doubles the transition model
  and can't express backward moves tied to an outcome.
- **One status per (stage, name), with no stage column.** Nothing would group statuses by stage
  for the rail, the admin screens or reports.
