# ADR-043: Visual workflows — a JSON definition, a pure interpreter, Temporal as the waker

- **Status:** Proposed (WP-048b; plan approved by the coordinator 2026-11-05)
- **Date:** 2026-11-05
- **Source:** WP-048b; parity file 03 §15 (REQ-WF-008..029) and Appendix A; architecture.md §6.5,
  §6.7, §8; ADR-004, ADR-011 (open), ADR-037, ADR-041; D-146
- **Owner:** Haider (Product Owner)

## Context

Admins build workflows on a canvas: start, conditions, waits, timers, approvals, tasks, actions,
sub-flows and parallel branches. Instances must run for days or months and survive restarts,
upgrades and failover, with each node's effects happening once (REQ-WF-020). They must behave the
same on single-node on-prem and on SaaS.

ADR-004 chose Temporal with "a JSON DSL executed by a generic interpreter workflow". ADR-037
showed how this repo uses Temporal safely for SLA clocks: PostgreSQL holds the truth, Temporal only
wakes. Four questions remain open:
- **Where the instance state lives.** The record, the execution view, the overview and reports
  must agree.
- **How a node's effect happens once** when an activity can run twice.
- **How a workflow hears about a record.** Requests may not talk to Temporal (rule b).
- **How workflows share actions with triggers.** WP-048a (lane A) adds notification, task and
  webhook actions to triggers. Two copies of each action would drift.

## Decision

### 1. The definition is data

- A workflow version holds a JSON definition: `{"format": 1, "nodes": [...], "links": [...],
  "variables": [...]}`.
  - A node is `{id, type, config, position}`.
  - A link is `{from, port, to}`, where `port` is the output named by the node type: `yes`/`no`,
    a switch case, `approved`/`rejected`/`timed_out`, `success`/`error`, `overtaken`, `timeout`,
    `completed`/`overdue`/`canceled`, or `next`.
- The definition re-opens to the same diagram (REQ-WF-008 AC3), because positions are part of it.
- **The node types** are a closed registry in `automation/domain/workflow_nodes.py`. Each type
  declares:
  - its config schema;
  - its outputs;
  - the record types it is offered for (REQ-WF-009 AC3).
- The UI renders node types through labels only (rule d).

### 2. Validation is pure, and names every problem

`validate(definition, record_type, catalogue) -> list[Problem]`. Each problem carries a code, the
node or link ID it is about, and parameters. The checks are:
- unconnected nodes, and a node with no path to an end;
- nodes not valid for the type, and conditions on fields the type does not have;
- waits that can never finish, a join without a split, and sub-flow recursion;
- the Appendix A limits: **200 nodes**, every loop with a **round limit of at most 100**.

How problems are used:
- **Drafts save with problems; only a problem-free version publishes** (REQ-WF-019).
- Any node may link to an end.
- The designer selects the node a message is about when the message is clicked.

### 3. PostgreSQL holds the truth

- **The tables, all in the automation module, with RLS:**
  - `workflows`: name, record type, enabled, owner, version.
  - `workflow_versions`: an immutable definition once published, with who and when.
  - `workflow_instances`: record, version, state, the tokens at their nodes, variables, the
    error, and the version for If-Match.
  - `workflow_steps`: the log of node runs, with node, token, result, output taken, start, end,
    actor, and a compact detail.
- The execution view, the overview and history read only these tables (REQ-WF-023, -025).
- Stopping an instance keeps its steps (REQ-WF-026).
- **At most one running instance per record and workflow.** A partial unique index enforces it
  (REQ-WF-010).

### 4. The interpreter is a pure step function

- `advance(definition, instance, event | None, now) -> Advance` returns:
  - the new token positions and variables;
  - the steps to log;
  - the **commands** to carry out (move the record, set fields, add a note, open an approval,
    create a task, send a notification, call a webhook);
  - the next wake time, or the events the instance now waits for.
- It does no I/O, so it is unit-tested node by node (REQ-WF-009 AC2) and drives the test mode
  (§9).
- **Parallel branches** are tokens. A join waits for all, the first or N tokens, as configured.
  "First" cancels the others and logs each cancellation (REQ-WF-018).
- **Limits** (Appendix A):
  - a loop back-edge counts rounds per token, at most 100;
  - an instance runs at most **10,000 steps**.
  Hitting either limit fails the instance with the reason shown (REQ-WF-029).

### 5. Temporal is only the waker. One workflow per instance

- The Temporal workflow ID is `wf:<tenant>:<instance>`, on task queue `workflows`.
- **The loop:**
  1. The activity `run_ready(instance)` loads the instance and runs `advance`.
  2. In **one transaction** it applies the commands through the owning modules' public services,
     writes the steps and the new instance state, and writes outbox events.
  3. It returns the next wake time.
  4. The workflow waits until then, or until an `event` signal.
- The workflow does no I/O, carries no data in signals, and continues as new after 200 wakes, as
  ADR-037 does.
- **Effects happen once.** Every step has a unique key `(instance, token, sequence)`.
  - A re-run activity finds the step already written and applies nothing.
  - External effects (notification, webhook) are outbox events handled by idempotent consumers,
    so a crash between the write and the call sends once (REQ-WF-020 AC2).
- **Hearing about the record.** The consumer `workflow_events` reads committed outbox events
  (status and field changes, notes, requester replies, approval decisions, task changes,
  worklogs). It signals the instances waiting on that record, as `sla_scheduler` does.
  - Requests never call Temporal.
  - A safety-net schedule re-wakes overdue instances when Temporal was down.
- **Waits complete on the committed change**, whoever made it. A wait takes its **`overtaken`**
  output when the record reaches a state where the wait can no longer complete: by default a
  closed or canceled category, or the node's own "overtaken when" condition. A wait is never
  dropped (REQ-WF-012).
- **Timers** use the sla module's `Calendar` for business time. They can pause while the record
  is paused (REQ-WF-013).

### 6. Workflows act through the owning modules' public services

- These services enforce every check, history and SLA stamp, with source `workflow` and the
  instance in `automation_ref`:
  - **Moves:** work_items' public move service (`transition`/`move_status` or `_stage_move`, the
    same functions as API, bulk and triggers, ADR-041 §8). A move is by action code and honours
    reason mode, required fields and closure rules.
  - **Field updates:** work_items' public update service.
- A refusal is never forced. It takes the node's `error` output if there is one; otherwise the
  instance stops at the node (REQ-WF-024).
- System-only statuses are refused at design time.
- **Approvals** open on the WP-030 engine with the instance as their origin. Levels use the shared
  level outcome, with D-146:
  - an exact split rejects;
  - an optional per-tenant deciding approver (the chair) breaks a tie when set.
  Lane A's CAB and problem approvals use the same outcome.
- **Tasks and checklists** are the record's parts. A node waits on their committed events
  (REQ-WF-015).
- **Sub-flows** start a child instance and wait for it to finish. Recursion is refused when the
  workflow is saved (REQ-WF-017).

### 7. One action library for workflows and triggers

`automation/actions/` holds the shared action library. Workflow nodes use it from WP-048b. Lane
A's WP-048a triggers adopt it unchanged, and today's `_set` and `_note` move onto it in 048a.

- **Each action** declares:
  - its config schema;
  - `validate(config, record_type) -> problems`, run when a workflow or trigger is saved;
  - `run(ctx, config) -> ActionResult`, where the result is success with outputs, or an error
    with a code.
- **The actions:**
  - **Field update:** any field of the record's edit form, custom fields included, through the
    public update service. Never direct column writes.
  - **Status move:** by action code through the public move service.
  - **Note:** public or private, from a template rendered with label-safe variables.
  - **Task:** title, owner (a person or a group), due offset in business days on the record's
    calendar.
  - **Notification:** only through the one notification engine. The audience is checked at send
    time, and each recipient gets their own language (REQ-WF-015 AC3).
  - **Webhook:** always driven from the outbox, never inside a request. It goes through the shared
    guarded HTTP client (§8). Its result can be stored in workflow variables (REQ-WF-016).
- **Retries.** Action nodes retry 3 times with backoff and can have an `error` output. "Continue on
  failure" is a per-node setting (Appendix A, REQ-WF-024).
- **The loop guard** carries over: the per-record depth and cooldown from triggers.

### 8. Outbound HTTP and custom functions

- **One guarded HTTP client in `app/shared`**, which lane B's WP-055 outbound webhooks reuse.
  Lane B reviews its security.
  - It blocks loopback, link-local and private ranges unless they are allow-listed.
  - It follows no redirects.
  - It has size and time limits (Appendix A: 10 s).
  - It resolves a name once and connects to that IP, so DNS rebinding does not work.
  - Every call is checked against an egress policy entry.
- **Custom functions:** only a `FunctionRunner` port in this WP. ADR-011 (the sandbox) is Haider's
  decision and is still open.
  - The function node is offered only when the `SANDBOX` and `CUSTOM_FUNCTIONS` entitlements are
    on and a runner is configured. Otherwise validation names why.
  - Functions never run in the API process (architecture §6.7).

### 9. Versions, migration and test mode

- **Versions.** Publishing creates a new immutable version. Running instances stay on their own
  version (REQ-WF-021).
- **Migration** moves instances to a new version through a node mapping, with a dry run and a
  per-node preview. It is a bulk job with progress. Instances that cannot be mapped stay on their
  version and are listed.
- **Test mode** runs the same `advance` against a chosen record's facts or against sample values.
  - The admin answers waits and approvals by hand.
  - Timers can be fast-forwarded.
  - Commands are shown, never applied, unless the admin allows one live call for one node
    (REQ-WF-022).
  - Test runs are stored apart, and never touch the record or its history.

### 10. Who sees what, and live updates

- **Permissions:**
  - `workflows.manage` covers designing, publishing, migrating, and bulk retry and cancel.
  - Running, stopping or restarting a workflow on a record needs `workflows.run` and the right to
    edit the record.
  - The execution view needs the right to view the record. Requesters never see it; the portal
    shows only the record's status (REQ-WF-023 AC3).
- **The `WORKFLOWS` entitlement gates the feature**, through the entitlement interface only
  (rule f).
- **Live updates.** Step and state changes publish to the record's channel and to the workflow
  overview's channel, with IDs, changed fields and version only (rule c). An open execution view
  moves its marker within a second (REQ-WF-023 AC1).

## Consequences

- **Positive:**
  - One state, in PostgreSQL, for the record, the execution view, reports and support.
  - The interpreter is plain Python, testable without Temporal.
  - Workflows and triggers share one action library, so behaviour cannot drift.
  - The same runtime works on on-prem and SaaS: Temporal on k3s through lane B's chart, and the
    safety net when Temporal is down.
- **Negative:**
  - Node types are a closed registry. A new kind of node is a code change with its own contract
    test, not a configuration.
  - Every pending run wakes through two hops: outbox to consumer, then consumer to signal. Waits
    complete in about a second, not instantly.
  - Custom functions stay unavailable until ADR-011 is decided.
- **Follow-ups:**
  - Lane A's WP-048a moves triggers onto §7.
  - Lane B's chart adds the on-prem Temporal and its schema Job.
  - REQ-WF-030 (drafting from text) and REQ-WF-031 (other records) stay LATER.
