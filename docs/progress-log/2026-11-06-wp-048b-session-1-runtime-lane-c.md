### 2026-11-06 — WP-048b session 1: the workflow runtime core (lane C, #233)

- **Design:** ADR-043 covers the JSON definition, the pure interpreter, PostgreSQL as the truth,
  Temporal as the waker, one action library shared with triggers, the guarded HTTP client and
  the custom-function runner port. Lanes A and B reviewed it.
- **Built:**
  - definitions and validation, and the interpreter (tokens, joins, waits, timers, commands,
    limits);
  - migration 0105 and RLS;
  - the runtime;
  - the work_items command adapter, with `history.automated` naming the workflow;
  - the run-as identity, with the never-list on every path;
  - the wakers: the record-event consumer, the minute sweep and the Temporal waker with its
    worker;
  - template starts;
  - the admin service and the API.
- **Paused once:** the full QA stop (2026-11-06). The QA fixes came first (#242, #243, #248,
  #251, #254, #255, #258, #263, #265, #266), then this resumed at the recorded point.
- **Open:** the trigger action "start a workflow" waits on lane A's choice; the chart's
  workflowTimers Deployment is lane B's.

## Addendum: the trigger action (same day)

- `start_workflow` trigger action, on lane A's four conditions: a save-time check at
  `actions.N.workflow_id` (`workflow_not_found` and `workflow_wrong_record_type` always;
  `workflow_not_published` and `workflow_disabled` for an enabled trigger), its own savepoint
  with the refusal logged by `instance_code`, and a loop guard.
- The loop guard needed a cause: the event's actor in a consumer is the system actor, so the
  runtime wraps each command in the new `app/shared/events.caused_by(instance)`, and the trigger
  skips with `kept/own_change` when the cause is an instance of the same workflow.
- Tests: `tests/db/test_workflow_trigger_action.py` (3), plus all 13 existing trigger API tests.
  Lane A reviewed and approved it on #233. Lane A will fix the automated note's `automatic`
  flag in WP-048a.
