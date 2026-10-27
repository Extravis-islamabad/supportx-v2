# ADR-035: Automation — business rules inside the save, routing by group, auto-assignment only inside the group

- **Status:** Accepted
- **Date:** 2026-10-27
- **Source:** WP-029 (plan: ~/Desktop/wp-029-plan.md); architecture.md §6.1, §6.5, §6.7, §8;
  parity file 03 REQ-RUL-001..006, 029, REQ-ASG-001..006, 011, REQ-WI-004; D-052, D-074, D-097
- **Owner:** Haider (Product Owner)

## Context

Rules, routing and auto-assignment change records nobody touched by hand. The lessons of
Areas 12 and 15: people must see which rule changed what and why, auto-assignment must work by
group first and never pick someone outside the record's group, nothing may fail silently, and
automation must not loop forever. Modules may not read each other's tables (CLAUDE.md rule e).

## Decision

1. **A new `automation` module** owns rule definitions, routing rules and settings, per-group
   auto-assignment settings and turns, technician availability, triggers (definitions only in
   this WP) and the run log (`automation_runs`, kept 30 days). All tables are tenant-scoped with
   FORCE RLS.
2. **Record types register with it.** The owning module (work_items for incidents) registers a
   `RecordType`: rule fields, value checks and the category → group suggestion. Automation never
   reads work item tables. The owning module calls the public interface inside its own save.
3. **One documented order inside one transaction (REQ-RUL-006):** business rules → priority
   matrix (the owner's) → routing → auto-assignment. The same rules run on edits, assignments and
   life-cycle moves. Rules cannot set the status, so the life cycle stays in charge.
4. **Business rules** run top to bottom; each matching rule sets fields ("only if empty" or
   "replace") or refuses the save with an admin message in en/ar/ur (422 `rule_refused`). "Stop
   after this rule" ends the run. Drafts and disabled rules never run. A rule is checked when
   saved: unknown fields, fields that cannot be set and missing groups are refused at the field.
5. **Routing picks a group, never a person:** the first matching routing rule, then the category's
   group, then the fallback group. A group a person chose stays unless the rule says "replace".
6. **Auto-assignment picks a person only inside the record's group:** active, Available members
   who may work the type. Round robin keeps a per-group turn row taken with a row lock; load
   balancing weighs open records P1 = 4 … P4 = 1 and names the loads it compared. Nobody
   available, or everyone at the cap, leaves the record in the group queue with an
   `automation.assignment.waiting` event and a log entry, never a silent skip. It runs on create
   and on a move to the group (both switchable per group).
7. **Every automated change is a history line with source `rule`** and an `automation_ref`
   (business rule / routing / auto-assign, with the rule's name, the method and loads). The
   person's own entry never repeats what automation set.
8. **What a rule uses cannot be removed:** a group, site or department used by a routing or
   business rule is refused as in use (`automation_rules: n`). A custom field a rule names is
   refused as `custom_field_used_by_rule`, naming the rules.
9. **Triggers run after the commit** in the `automation__triggers` consumer, reading the owning
   module's events through a reader it registers (part 2, D-102). Field updates go through the
   record's own save path (`apply`), so business rules run again; each action has its own
   savepoint. A change a trigger makes carries the trigger's run log entry as its event's
   cause, so the next event knows its chain (depth and triggers).
10. **Loops:** business rules run once per save and cannot trigger each other. The guard stops a
   trigger chain at depth 5 or 20 automated changes per record per minute, and never runs a
   trigger on its own change unless allowed; a stop is a `loop_guard` run naming the triggers,
   shown on the record, with `automation.loop.stopped` told once per record per hour.
11. **Transition settings** (who may run, offered when, confirmation, "after" actions) are owned
   by automation and checked by the owning module when it builds a record's actions and when a
   move is asked for (403 `transition_not_allowed`); "after" actions run in the trigger consumer.

## Consequences

- Admins see why every automated change happened, on the record and in the run log.
- Other record types join by registering a `RecordType`; no automation code changes.
- Saves pay for the rule run; rules are loaded once per save and evaluated in memory.
- Notification, approval, task, timer, webhook, function and workflow actions register later as
  action types; the engine does not change.
