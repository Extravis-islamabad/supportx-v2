# ADR-049: Shared life cycle versions, for action-based and staged types

- **Status:** Proposed (WP-046a S4, lane A; the shape approved by the coordinator, 2026-11-12;
  lane C reviews the stage engine side, lane B the per-transition rights and conditions)
- **Date:** 2026-11-12
- **Deciders:** Haider (Product Owner), the coordinator, lanes A, B and C

## Context

REQ-INC-049 asks for a life cycle designer: admins draw statuses and transitions, set who may run
each transition and when it is offered, the fields it needs and the actions that follow, and
publish versions. An incident keeps the version it started on until an admin migrates it.
REQ-CHG-030 asks the same of changes, which ADR-041 (§10) prepared for with a nullable
`lifecycle_version` but never built: only version 1 has shipped.

Today there are two stores of moves:

- **Action-based types** (incidents, service requests, problems): `work_item_transitions`, keyed by
  type, lifecycle, from status and action, with a reason mode and list. Their whole API and every
  caller (SLA, the portal, automation, workflows) speak *actions* (`/actions/{action}`). There are
  no versions, no per-transition right, no required fields and no conditions.
- **Staged types** (changes, releases, ADR-041): `work_item_status_transitions`, status to status,
  with a path, a nullable `lifecycle_version`, a `permission` and `required_fields`.

Both share `work_item_statuses`.

## Decision

1. **One versioning model, two transition shapes.** A new table, `work_item_lifecycle_versions`
   (tenant, type, lifecycle, version, state `draft` / `published` / `retired`, published at and
   by, and the last validation's problems), is the one place a life cycle's versions live, for
   both engines. Each transition table references it through its own `lifecycle_version`. The
   action-based types keep actions; nothing moves onto stages, and ADR-041's decision stands.
2. **Published versions are immutable.** Editing a published life cycle makes a new draft (a copy
   of its transitions under the next version). A draft saves with problems; only a valid one
   publishes. Publishing retires nothing by itself: records keep the version they run on.
3. **A record runs on its version.** `work_items.lifecycle_version` (already there for staged
   types) is set on every record when it is made, to the life cycle's latest published version.
   Every lookup of a move reads the record's own version, so publishing version 2 never changes a
   record on version 1 (REQ-INC-049 AC3).
4. **What an action-based transition gains** (mirroring ADR-041's names): `lifecycle_version` (in
   the key), `permission` (an extra right, as ADR-041's), `required_fields`, `conditions` (JSONB:
   who may run it, from roles, groups, the requester, the group head and the reporting manager)
   and `after_actions` (references to the automation action library, run through it, ADR-043).
5. **One conditions function; conditions only narrow, never grant** (lane B's review). A
   transition runs only when all of these hold, checked in this order:
   1. the record is in the person's scope (`authorize_stored`); a record out of scope stays a
      404, before any condition is looked at;
   2. the person holds the type's base right for the move, as today;
   3. the person holds the transition's `permission`, when one is set;
   4. the transition's conditions pass.

   A condition can never stand in for a missing right.
   - **Semantics.** No conditions means no extra limit. The conditions are **one any-of list**:
     the transition runs for anyone who matches any entry ("the requester, or the group head, or
     role Finance"). Within an entry, its roles, groups or people are any-of too.
   - **Fail closed.** An entry naming a role or group since deleted, or "the reporting manager" of
     a requester who has none, matches nobody. Publishing reports it up front, and at run time it
     is a refusal, never an allow.
   - **Facts are read when the move is accepted**, inside its transaction and after the If-Match
     check (the group, the requester or a manager may have changed since the buttons were shown).
     What is offered is advisory only.
   - **Ids stay in the tenant.** A role, group or person id in a condition is checked within the
     tenant when the draft is saved. One from another tenant is refused (RLS already hides it,
     and a test proves the refusal).
   - **The refusal says why, without naming anyone.** It is a 403
     `transition_condition_not_met` whose params carry only the condition kind
     (`{kind: "group_head"}`): no names, other people's identities or role ids. On the portal a
     requester sees only that the move is not available to them.
   - **No silent bypass.** Conditions apply to automation, workflows and rules too, acting
     through their run-as identities (lane C's run-as pattern). Anything that must bypass them
     does so only through an explicit transition flag that only an administrator sets, and the
     setting is audited.
   - **After-actions** run through the ADR-043 action library as the configured run-as identity,
     never as the acting person, after the commit through the outbox, never in the request's
     transaction, so an action cannot make the move succeed or fail.
   - **`permission`** must be a right in the catalogue, checked at publish, and never an
     administrator-only right (identity, roles, API keys): the same rule as
     `role_allowed_for_service`.
6. **Publishing validates.** A version publishes only when every status that is not final has a
   way out (the message names the status, AC1), every transition's target exists in it, every
   required field is a real field of the type, every condition names something that exists in
   the tenant, every `permission` is allowed (above), and every after-action is known to the
   action library. Each problem names exactly what to fix. Saving a draft, publishing and
   retiring a version need the type's settings right; publishing and retiring are audited.
7. **Migrating records is an admin action** (the type's settings right).
   - A dry run writes nothing: it lists each record whose status has no place in the target
     version and where it would go.
   - A real run moves records in background jobs of up to 1,000 each, with each record's version
     check: a record changed since the dry run is skipped and listed, never forced.
   - Migrating runs no after-actions and none of the new version's required-field checks.
   - History on each record uses the source `migration`. One audit entry per run records the
     actor, the type, the from and to version, and the moved, skipped and failed counts.
8. **Staged types** (lane C's review):
   - **What a version covers.** On a staged type a version covers its statuses' transitions
     only. Stages, paths, stage access, stage approvals and required-to-leave rules stay per type,
     not per version. Publishing a staged version also checks that every status's stage exists,
     every path still reaches closure, and each stage keeps a completing status.
   - **No NULL versions left.** The data step (§10) makes every staged transition version 1 and
     points it at the new table, so no staged row stays NULL against a referenced version. NULL
     is gone after it; until then `load_model` keeps reading NULL as version 1.
   - **The stage model cache** (`stage_service.load_model`) is keyed by (tenant, type, version)
     and dropped on publish. A test proves that a record on version 1 still gets version 1's
     moves after version 2 publishes, on a change and on a release.
   - **Migrating a staged record** can change its stage. The dry run shows each record's stage
     change. A record whose current stage is not on its path in the target version is listed as
     not movable, never moved. A moved record keeps `stage`, `stage_path` and its tasks
     consistent: tasks keep their stage, and the per-stage task counts follow.
   - **Seeds.** A catalogue top-up (`_seed_vN`) adds only to the version it shipped with, never
     into an administrator's published or draft version.
9. **The designer reuses lane C's flow package** (packages/flow): statuses as nodes, transitions as
   links, keyboard moves and right-to-left layout as the workflow designer has them (AC4). The
   package stays domain-free (no work-item imports): status nodes are a new node kind with their
   own names, on the in-house layout.
10. **Data step.** The migration that adds this makes every tenant's existing transitions, in both
    tables, version 1 and published, and sets `lifecycle_version = 1` on every record that has
    none, once per tenant with `app.tenant_id` set and in batches. It is reversible while no
    tenant has a version 2.

## Consequences

- Every move lookup carries the version: the key and indexes include it, and a timing test covers
  100,000 records.
- REQ-CHG-030's publish uses the same table and validation, so changes and releases gain versions
  without a second model.
- The conditions function is security-relevant: lane B blocks it and its 403 path; lane C
  blocks the stage engine side.
- Incidents keep their actions contract, so no caller changes.

## Tests this decision requires

- RLS for `work_item_lifecycle_versions` (rule 5a): tenant A never reads or writes tenant B's.
- A condition matrix: each kind × matches / doesn't / names something deleted.
- The API refuses a transition it did not offer, with `transition_condition_not_met` and its kind.
- A record out of scope is a 404 before any condition is checked.
- A role or group id from another tenant is refused when a draft is saved.
- A run-as identity (automation, workflow) is limited by a condition like a person.
- A migration skips a record changed since its dry run and lists it.
- A record on version 1 keeps working after version 2 is published (REQ-INC-049 AC3), on an
  incident, a change and a release (the stage model cache).
- A staged record whose stage is not on the target version's path is listed, never moved.

## Alternatives considered

- **Incidents onto stages** (one implicit stage): one transition table, but it rewrites the
  actions contract every caller uses, for no gain in INC-049.
- **Versions inside each transition table only** (no shared version table): no single place for a
  version's state, publish time and validation, and two ways to publish.
