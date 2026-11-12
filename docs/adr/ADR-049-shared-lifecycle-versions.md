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
5. **One conditions function.** Whether a person may run a transition is decided by one pure
   function over the transition's conditions and the person's facts on the record. The same
   function decides what is offered (the record's buttons and the API's operations) and what the
   API accepts: a transition it refuses is a 403 with its reason, never just hidden (AC2).
6. **Publishing validates.** A version publishes only when every status that is not final has a
   way out (the message names the status, AC1), every transition's target exists in it, every
   required field is a real field of the type, every condition names something that exists, and
   every after-action is known to the action library. Each problem names exactly what to fix.
7. **Migrating records is an admin action.** It moves chosen records (or all on a version) to
   another published version, after a dry run that lists each record whose status has no place
   in the target and where it would go. It needs the type's settings right, writes history on
   each record and one audit entry per run.
8. **The designer reuses lane C's flow package** (packages/flow): statuses as nodes, transitions as
   links, keyboard moves and right-to-left layout as the workflow designer has them (AC4).
9. **Data step.** The migration that adds this makes every tenant's existing transitions version 1,
   published, and sets `lifecycle_version = 1` on every action-based record, once per tenant with
   `app.tenant_id` set and in batches. It is reversible while no tenant has a version 2.

## Consequences

- Every move lookup carries the version: the key and indexes include it, and a timing test covers
  100,000 records.
- REQ-CHG-030's publish uses the same table and validation, so changes and releases gain versions
  without a second model.
- The conditions function is security-relevant and is reviewed by lane B; the stage side, by
  lane C.
- Incidents keep their actions contract, so no caller changes.

## Alternatives considered

- **Incidents onto stages** (one implicit stage): one transition table, but it rewrites the
  actions contract every caller uses, for no gain in INC-049.
- **Versions inside each transition table only** (no shared version table): no single place for a
  version's state, publish time and validation, and two ways to publish.
