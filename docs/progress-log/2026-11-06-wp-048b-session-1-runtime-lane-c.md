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
