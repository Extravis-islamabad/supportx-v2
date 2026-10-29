# ADR-037: SLA clocks — Temporal as the waker, PostgreSQL as the truth

- **Status:** Proposed (accepted with the WP-025 build; plan approved 2026-10-29, D-115)
- **Date:** 2026-10-29
- **Source:** WP-025 (plan: ~/Desktop/wp-025-plan.md); architecture.md §6.5, §6.7; ADR-004;
  D-017, D-038 (11), D-055; parity file 03 REQ-SLA-015..025, 037, 039
- **Owner:** Haider (Product Owner)

## Context

SLA clocks must flag a breach within 60 seconds of the due time (p99) with a million clocks
running. They must survive restarts, upgrades and failover without losing, delaying or repeating
an escalation level (REQ-SLA-037). They must work identically on single-node on-prem and on SaaS.
ADR-004 makes them Temporal workflows, one per work item, and D-055 brings Temporal in with
WP-025.

A timer engine alone does not settle the hard questions:
- **Where does the due time live?** The record, its history, the list and reports must agree
  to the second (REQ-SLA-014 AC2).
- **What happens to a timer when a record changes?** Pause, resume, priority change, reopen,
  a due date set by hand.
- **What if a timer fires twice, late, or not at all?** For example while Temporal is down or
  being upgraded.
- **Transactions.** A request may not talk to Temporal directly: every state change goes through
  the transactional outbox (CLAUDE.md rule b).

## Decision

1. **PostgreSQL holds the truth.**
   - Every due, warning and escalation-level time is a column in the `sla` module's tables
     (`sla_targets`, `sla_escalation_runs`). The save writes them in the same transaction as
     the record change (`sla.on_change`, called by the record's own module).
   - The record shows these times, history records them and reports read them. Temporal never
     holds a time anyone reads.
2. **Temporal is only the waker. One workflow per record**, ID `sla:<tenant>:<record>`, task
   queue `sla`, one namespace per installation.
   - **The loop:** the activity `next_wake(record)` returns the earliest pending moment and the
     plan revision; the workflow waits until then or until a `changed` signal; on time-out it
     runs the activity `fire(record, revision)`.
   - **The workflow does no I/O.** All business-time maths and every read are activities, so
     the workflow stays deterministic.
   - **It ends** when nothing is pending (resolved, closed, canceled), and continues as new
     after 200 events.
3. **Outbox-driven signals.**
   - The save writes `sla.applied`, `recalculated`, `paused`, `resumed` and `stopped` to the
     outbox with the record change.
   - A consumer (`sla_scheduler`, in the consumers worker) turns each event into
     `signal_with_start("changed")`.
   - A signal carries no data, only "plan again", so a repeated or reordered delivery is
     harmless. Nothing in a request calls Temporal.
4. **Exactly-once by a unique run key.**
   - `fire` runs in one tenant transaction (`SET LOCAL app.tenant_id`). It re-reads the target,
     does nothing if the plan revision moved on, and inserts the run under the unique key
     `(target, round, level)` before doing the level's actions through the record type's
     callback.
   - Warning and breach are stamped the same way: once, on the target row, with a conditional
     update.
   - A second `fire` for the same moment finds the key taken and stops. Two firings can
     therefore never run a level twice, whoever fires them.
5. **A 60-second safety net.** A housekeeping schedule (`app/shared/schedules.py`, one worker at a
   time by advisory lock) fires anything more than 2 minutes overdue through the same `fire`.
   It is idle when Temporal works and is never a second engine.
6. **Temporal down, restarted or upgraded.**
   - The due times are in PostgreSQL, so nothing is lost.
   - Signals wait in the outbox and NATS (the scheduler retries) until Temporal is back.
   - Overdue moments are caught by the safety net within about 3 minutes, or by the workflow
     when it resumes; exactly-once still holds (point 4).
   - Restarted workers replay workflow history. Determinism and versioning use
     `workflow.patched`, guarded in CI by a replay test against stored histories.
7. **Packaging (D-017, D-038):**
   - The Temporal server with its schema set up by admin-tools, never the auto-setup image, on
     the CloudNativePG cluster (`temporal` and `temporal_visibility` databases, own role),
     with SQL visibility (no Elasticsearch).
   - The official Helm chart in Kubernetes, the same on single node. Images are mirrored to the
     private registry for air-gapped installs. The UI is for development only.

## Consequences

- **Positive:**
  - One source of times: the panel, lists, history and reports agree by construction.
  - Duplicate, late or lost wake-ups cannot double-run or skip a level.
  - Temporal can be upgraded, restarted or lost briefly without changing any outcome.
  - The safety net keeps the 60-second promise through short outages.
- **Negative:**
  - Every wake-up costs a database round trip (`next_wake`, `fire`); measured by the 1M-clock
    load test (D-115 D10).
  - Two extra databases to back up on every profile (operations docs, backup runbook).
  - Workflow code needs versioning discipline (replay test in CI).
- **Rejected:**
  - **Due times kept in workflow state:** they can drift from what the record shows, and lists
    would need to query Temporal.
  - **One workflow per target or per level:** more workflows, and cancelling them on every
    change multiplies the signals.
  - **A cron sweep only:** no durable timers, and lag grows with volume. It remains as the
    safety net.
