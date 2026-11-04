# ADR-041: Stages for work items, one engine for releases and changes

- **Status:** Proposed (WP-058a session 1, lane C; the coordinator approved building it; revised
  after lane A's review for changes, who reuse it unchanged, with their five additions to the
  table list: `work_items.lifecycle_version`, `required_fields`, RLS with tenant-carrying keys,
  cancel's role rule in the guard, and `stage_changed`'s from and to stage and entry id)
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

Revised after lane A's review for changes (file 05, REQ-CHG-023..031, -052, -053, -093/094).

1. **Stages are opt-in per type.** A `WorkItemType` declares its stages, paths, statuses and
   transitions as seed data. Types without stages (incident, service request) behave exactly as
   today. Nothing in their tables, routes or screens changes.
2. **A stage owns statuses.** New table `work_item_stages` (tenant, type, code, sort order,
   label overrides, `system`, `disabled_at`). `work_item_statuses` gains:
   - a nullable `stage`;
   - `completing` (boolean): exactly one completing status per stage, and saving a stage without
     one is refused;
   - `set_by` (`person` or `system`): `system` statuses, such as the approval outcomes
     *accepted*, *plan approved*, *CAB approved* and their rejected twins, are refused by the
     person-facing path, by rules and by workflows at design time. Only an internal entry point,
     which the approvals code calls, sets them.

   Status codes stay unique per type, so repeated names carry the stage in the code
   (`build_in_progress`), and the shipped labels give the plain name ("In progress").
3. **Paths below the type.** A type has one or more stage paths (`work_item_stage_paths`:
   tenant, type, code, a nullable `lifecycle_version`, labels). `work_item_path_stages` lists
   each path's stages in order, each optionally `optional`. A record carries its path
   (`work_items.stage_path`), set on create from its sub-type or template. Releases ship one
   default path. Changes ship standard, normal, emergency and major. Stages off a record's path
   never show for it.
4. **One transition table for every move.** `work_item_status_transitions` (tenant, type,
   nullable path, nullable lifecycle version, from status, to status, reason mode, reason list,
   nullable permission, and `required_fields`: the fields the move asks for in its one dialog,
   REQ-CHG-026). It is data, and only these moves are offered or accepted, on every
   path:
   - A transition whose target is in the **same stage** is a status move: `scheduled →
     in_progress`, never `scheduled → implemented`.
   - A transition whose target is in **another stage** is a hand stage move: backward or
     outcome moves (`testing_failed → build_in_progress`, `cab_rejected → planning`), or a skip.
     Skipping a non-optional stage requires a reason by default; skipping an optional one does
     not.
   - **Reaching a completing status advances automatically**, in the same transaction, to the
     first active status of the next stage on the record's path (REQ-CHG-025 AC2, -052 AC1).
   - End and outcome statuses can sit in any stage (rejected in submission, failed, backed out).
     Cancel and reopen are seeded transitions with their own permission and a required reason,
     not fixed engine rules. Who may cancel beyond that permission (for changes: the change
     manager, or the requester before approval) is the owning type's guard (§5), not data.
   - A type that wants free moves inside a stage seeds every pair.
5. **Hooks for the owning type, inside the transaction.** A type may register a `StageGuard`:
   - `check(record, move) -> list[Refusal]`: required fields per stage, open tasks and pending
     approvals, the emergency guard, freeze windows. Its refusals feed the record's action
     reasons (REQ-WI-010).
   - `on_entered(record, stage, entry)`: for example, superseding a stage's approvals on going
     back.

   The engine never contains approval or freeze logic.
6. **The past is kept.** `work_items` gains nullable `stage`, `stage_path` and
   `lifecycle_version` columns (the version a record started on, §10).
   `work_item_stage_entries` records each entry into a stage: path, who, when, the transition's
   reason, and when it left. Going back adds a new entry and never rewrites one; a stage passed
   through on an automatic advance gets an entry left at once. Every move writes field history
   (`status`, `stage`) and emits the existing status event (action `stage_move`) through the
   outbox; a move that enters another stage also emits `work_items.work_item.stage_changed` with
   the from and to stage, every stage entered and the id of the entry it is in now. Planned and actual dates per stage
   (REQ-REL-026) are columns added to the entry in session 4.
7. **The rail is computed, never stored.** For each stage on the record's path, in order: *done*,
   *current*, *skipped* (a later stage was entered without entering it) or *future*, with its
   entries' dates and whether it is optional. After going back, the stages after the current
   one are *future* again, keeping their earlier rounds' entries. It is served on the record and changes live
   through the record channel.
8. **The same rules on every path.** API, bulk, workflow nodes (WP-048b) and automation call the
   same service function, which checks, in this order: the transition exists for the record's
   path and version, the status is not system-only (unless the system entry point is used), the
   permission, the reason, and the type's guard. Required fields per stage (REQ-REL-018) and
   stage access by role (REQ-REL-019) are guards, arriving in session 3. With them (lane A's
   review): each offered move carries the guard's refusals as its reasons, so a screen shows
   why a move is not possible yet, and a refused move returns the guard's full refusal list,
   not only the first.
9. **Seeds and edits.** A tenant's stages, paths, statuses and transitions are seeded on first
   use from the type's declaration: Appendix A of file 06 for releases, file 05 for changes.
   Admins edit them later. Seeds never overwrite a tenant's edits.
10. **Life cycle versions.** The nullable `lifecycle_version` on paths and transitions lets a
   later publish (REQ-CHG-030) leave records running on the version they started on. Session 1
   ships version 1 only.

## Consequences

- Changes (lane A) declare their stages, statuses and moves in `domain/types.py` and get the
  rail, the history and the checks with no engine work.
- A staged type does not use the named actions of `WorkItemAction` for status changes: its
  record page offers the transitions from the current status (in-stage moves and stage moves). Shared features
  keyed on status categories (SLA pause, final records, lists, reports) work unchanged, because
  every status still has a category.
- Reports can group by stage and by status category (REQ-REL-014 AC3). Each record counts once,
  by its current stage.
- Migration 0090 adds the tables and columns. Existing rows get NULL stages and are unaffected.
  All five tables force RLS, and every composite foreign key carries `tenant_id`, so a row can
  only point at its own tenant's stages, paths and statuses; each table has an RLS test.

## Alternatives considered

- **Stages as a second status field with its own action enum.** It doubles the transition model
  and can't express backward moves tied to an outcome.
- **One status per (stage, name), with no stage column.** Nothing would group statuses by stage
  for the rail, the admin screens or reports.
- **Free status changes inside a stage** (the first draft). This doesn't fit changes, which allow
  only listed moves inside a stage (REQ-CHG-024/025).
- **A separate stage-transition table.** One table for every move keeps "what is allowed from
  here" in one place. A move into another stage is simply a stage move.
