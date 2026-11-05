# ADR-040: Problem investigators widen access to one record, never to its fields

- **Status:** Proposed (WP-044a session 5, lane A; in the plan the coordinator approved,
  2026-11-04)
- **Date:** 2026-11-05
- **Deciders:** Haider (Product Owner), the coordinator, lane A; lane B reviews the access part

## Context

REQ-PRB-029: besides its owner, a problem has *investigators*, technicians from other groups
or sites who work on it through tasks, notes and worklogs. They must reach that problem even
when their scope would not, they are notified like followers, and removing one removes the
access, with history both times.

The engine already has one way to share a single record: a follower row that `grants_access`
(D-068, hand-over). Through the resource type's `shared_scope` it adds `view` and `add_note`
on that record only, for people who hold the permission at some scope. The list query and the
record check use the same predicate, so the list and the record never disagree (D-052).

## Decision

1. **An investigator is a follower row with reason `investigator` and `grants_access`.** There
   is no new table. They follow the problem, so they hear what followers hear, and see it, and
   add private notes on it, through the existing shared scope.
2. **On top of that, investigators work the record's tasks and worklogs** (create, change, move,
   delete tasks; log time). Worklogs are their own: they log time only in their own name, and
   change or remove only the time they logged (lane B's review; `own_worklogs_only`). The parts service checks `edit` *or* "an
   investigator of this record who holds `<type>.view` at some scope". Nothing else is widened:
   not field edits, assignment, status moves, links, replies to the requester or deleting.
3. **Who may name one:** whoever may `edit` the problem (the owner and the problem's group). The
   person must hold `problems.view` (a technician, never a requester-only account). Removing an
   investigator ends the follow, and so the access. History names the change on the problem
   (`investigator` added or removed).
4. Only problems offer investigators now. The mechanism is type-neutral, so changes may reuse it.

## Consequences

- No identity change: the shared scope already exists. Lane B reviews that nothing beyond
  view, notes, tasks and worklogs opens up.
- Unfollowing as an investigator ends the access, the same as a hand-over follower who
  unfollows.
- A hand-over follower who is named an investigator gets the investigator row in place of the
  hand-over one, so removing them later also ends the access the hand-over gave.
- Problem notifications to followers arrive with WP-044c S2 (D15). Until then investigators see
  the record live.

## Alternatives considered

- **A separate investigators table with its own scope predicate.** That means a second sharing
  path in identity's policy layer, and two places for the list query to agree on.
- **Granting `edit` to investigators through the shared scope.** It would let them change fields
  and status, which REQ-PRB-029 does not ask for.
