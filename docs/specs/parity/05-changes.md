# 05 — Changes

Parity requirements for change enablement (architecture.md §2.4): change types, templates,
stages, roles, the change advisory board, approvals, risk, scheduling, freeze and maintenance
windows, conflict detection, impact analysis, MonetX health checks, review and closure. Rules,
ID scheme and field meanings: [README.md](README.md).

**Status:** Draft v0.1, 2026-10-24. Phase 2, first draft for product owner review.
**Owner:** Haider (Product Owner).

## Scope of this file

- **REQ-CHG-*** are change requirements. A change is a work item type on the shared engine
  (REQ-WI-001). Everything the engine gives every type is inherited and **not repeated here**:
  history, live updates, presence, concurrency, actions and tabs, notes, conversations,
  worklogs, reminders, attachments, checklists, followers, trash, print, lists, custom views,
  bulk actions and the notification centre (file 01). This file lists only how changes differ
  from incidents or add to them.
- Changes are a Professional feature (product-plan §9) and a Stage 2 module (architecture §17),
  so nearly every requirement is `V1` or `LATER` and `Professional`.
- **Not in this file** (each has its own module file, see the README):
  - The visual workflow designer, business rules, triggers, timers, SLA engine and notification
    engine (file 03). This file says how a change *uses* them.
  - Releases and projects (file 06). This file covers only the change side of the link.
  - The CMDB, CI types, relationships, CI downtime records and the impact path engine (file 07).
    This file says how a change uses them.
  - Reports and dashboards (file 09), AI administration and agents framework (file 10), roles
    and approval settings screens (file 11), MonetX, DevOps and calendar connectors (file 12).
- **Monitoring is out of scope** (ADR-017, D-001). Health checks on a change **read** health and
  problems from the MonetX API, read-only. SupportX never polls devices, never collects metrics
  and never correlates alerts (REQ-INC-146, REQ-CHG-087).

## Words used in this file

| Word | Meaning |
|---|---|
| Change | A work item of type `change`: a planned addition, modification or removal of something that could affect IT services. |
| Change type | An admin-defined kind of change (for example minor, major), always bound to one change model. |
| Change model | The fixed behaviour behind a type: `standard` (pre-approved), `normal` or `emergency` (REQ-CHG-005). |
| Stage | A phase of a change with a fixed meaning (submission, planning, CAB review ...). Each stage holds admin-defined statuses. |
| Completing status | The status that finishes a stage and moves the change to the next stage on its path. |
| CAB | Change advisory board: a named group that reviews and approves changes. ECAB is the emergency board. |
| Change window | The scheduled start and end of the work. |
| Downtime | A period when a service or CI is expected to be (planned) or was (actual) unavailable because of the change. |
| Freeze window | A period in which changes are blocked or warned against. |
| Maintenance window | A preferred period for changes, agreed with the business. |
| Conflict | A scheduling clash found by conflict detection (REQ-CHG-073). |
| Health check | A read-only snapshot of MonetX health and open problems for the change's CIs, before and after the window. |
| PIR | Post-implementation review. |

## Requirement summary

<!-- summary:start -->
**Counts by decision and priority**

| Decision | MVP | V1 | LATER | Total |
|---|---|---|---|---|
| SAME | 0 | 43 | 5 | 48 |
| BETTER | 0 | 47 | 2 | 49 |
| NEW | 0 | 10 | 10 | 20 |
| SKIP | 0 | 0 | 1 | 1 |
| **Total** | **0** | **100** | **18** | **118** |

Edition (lowest edition that includes it): Essentials 0, Professional 118, Enterprise 0. By prefix: REQ-CHG 118.

| ID | Title | Decision | Priority | Edition |
|---|---|---|---|---|
| [REQ-CHG-001](#req-chg-001--changes-run-on-the-work-item-engine) | Changes run on the work item engine | BETTER | V1 | Professional |
| [REQ-CHG-002](#req-chg-002--create-a-change-from-another-record) | Create a change from another record | SAME | V1 | Professional |
| [REQ-CHG-003](#req-chg-003--copy-a-change) | Copy a change | SAME | V1 | Professional |
| [REQ-CHG-004](#req-chg-004--record-a-change-after-the-fact) | Record a change after the fact | BETTER | V1 | Professional |
| [REQ-CHG-005](#req-chg-005--change-types-bound-to-a-change-model) | Change types bound to a change model | BETTER | V1 | Professional |
| [REQ-CHG-006](#req-chg-006--standard-changes-are-pre-approved) | Standard changes are pre-approved | BETTER | V1 | Professional |
| [REQ-CHG-007](#req-chg-007--standard-change-catalogue) | Standard change catalogue | NEW | V1 | Professional |
| [REQ-CHG-008](#req-chg-008--emergency-changes) | Emergency changes | BETTER | V1 | Professional |
| [REQ-CHG-009](#req-chg-009--change-record-core-fields) | Change record core fields | SAME | V1 | Professional |
| [REQ-CHG-010](#req-chg-010--impact-urgency-and-priority-on-clean-scales) | Impact, urgency and priority on clean scales | BETTER | V1 | Professional |
| [REQ-CHG-011](#req-chg-011--reason-for-change) | Reason for change | SAME | V1 | Professional |
| [REQ-CHG-012](#req-chg-012--services-cis-and-assets-involved) | Services, CIs and assets involved | BETTER | V1 | Professional |
| [REQ-CHG-013](#req-chg-013--plans-impact-rollout-backout-and-test) | Plans: impact, rollout, backout and test | BETTER | V1 | Professional |
| [REQ-CHG-014](#req-chg-014--budget-and-cost) | Budget and cost | BETTER | LATER | Professional |
| [REQ-CHG-015](#req-chg-015--custom-fields-per-stage) | Custom fields per stage | SAME | V1 | Professional |
| [REQ-CHG-016](#req-chg-016--planned-and-actual-times-per-stage) | Planned and actual times per stage | BETTER | V1 | Professional |
| [REQ-CHG-017](#req-chg-017--implementation-overdue-marker) | Implementation overdue marker | BETTER | V1 | Professional |
| [REQ-CHG-018](#req-chg-018--change-templates-bring-everything-together) | Change templates bring everything together | BETTER | V1 | Professional |
| [REQ-CHG-019](#req-chg-019--template-designer-with-stage-sections) | Template designer with stage sections | SAME | V1 | Professional |
| [REQ-CHG-020](#req-chg-020--who-can-use-a-template) | Who can use a template | SAME | V1 | Professional |
| [REQ-CHG-021](#req-chg-021--when-template-tasks-are-created) | When template tasks are created | BETTER | V1 | Professional |
| [REQ-CHG-022](#req-chg-022--default-templates) | Default templates | BETTER | V1 | Professional |
| [REQ-CHG-023](#req-chg-023--stages-with-fixed-meaning-statuses-inside-them) | Stages with fixed meaning, statuses inside them | SAME | V1 | Professional |
| [REQ-CHG-024](#req-chg-024--default-change-life-cycle) | Default change life cycle | BETTER | V1 | Professional |
| [REQ-CHG-025](#req-chg-025--stage-and-status-move-only-through-allowed-transitions) | Stage and status move only through allowed transitions | BETTER | V1 | Professional |
| [REQ-CHG-026](#req-chg-026--one-status-dialog-everywhere) | One status dialog everywhere | BETTER | V1 | Professional |
| [REQ-CHG-027](#req-chg-027--stage-paths-per-type) | Stage paths per type | SAME | V1 | Professional |
| [REQ-CHG-028](#req-chg-028--stage-pages-on-the-record) | Stage pages on the record | SAME | V1 | Professional |
| [REQ-CHG-029](#req-chg-029--restrict-stages-by-role) | Restrict stages by role | SAME | V1 | Professional |
| [REQ-CHG-030](#req-chg-030--change-life-cycle-designer) | Change life cycle designer | BETTER | V1 | Professional |
| [REQ-CHG-031](#req-chg-031--go-back-a-stage) | Go back a stage | BETTER | V1 | Professional |
| [REQ-CHG-032](#req-chg-032--implementation-outcome-completed-backed-out-or-failed) | Implementation outcome: completed, backed out or failed | BETTER | V1 | Professional |
| [REQ-CHG-033](#req-chg-033--withdraw-or-cancel-a-change) | Withdraw or cancel a change | SAME | V1 | Professional |
| [REQ-CHG-034](#req-chg-034--change-roles-on-the-record) | Change roles on the record | SAME | V1 | Professional |
| [REQ-CHG-035](#req-chg-035--admin-defined-change-roles) | Admin-defined change roles | SAME | V1 | Professional |
| [REQ-CHG-036](#req-chg-036--line-manager-filled-in-from-the-requester) | Line manager filled in from the requester | BETTER | V1 | Professional |
| [REQ-CHG-037](#req-chg-037--assign-take-and-reassign-changes) | Assign, take and reassign changes | SAME | V1 | Professional |
| [REQ-CHG-038](#req-chg-038--change-permissions-you-can-read) | Change permissions you can read | BETTER | V1 | Professional |
| [REQ-CHG-039](#req-chg-039--segregation-of-duties-on-changes) | Segregation of duties on changes | NEW | V1 | Professional |
| [REQ-CHG-040](#req-chg-040--change-advisory-boards) | Change advisory boards | BETTER | V1 | Professional |
| [REQ-CHG-041](#req-chg-041--the-right-cab-is-chosen-automatically) | The right CAB is chosen automatically | BETTER | V1 | Professional |
| [REQ-CHG-042](#req-chg-042--approvals-per-stage) | Approvals per stage | SAME | V1 | Professional |
| [REQ-CHG-043](#req-chg-043--multi-level-approvals-in-sequence) | Multi-level approvals in sequence | SAME | V1 | Professional |
| [REQ-CHG-044](#req-chg-044--approval-rules-and-quorum) | Approval rules and quorum | BETTER | V1 | Professional |
| [REQ-CHG-045](#req-chg-045--approvals-work-without-mail-and-cannot-be-replayed) | Approvals work without mail and cannot be replayed | BETTER | V1 | Professional |
| [REQ-CHG-046](#req-chg-046--approvers-see-the-whole-change) | Approvers see the whole change | BETTER | V1 | Professional |
| [REQ-CHG-047](#req-chg-047--ask-for-clarification) | Ask for clarification | SAME | V1 | Professional |
| [REQ-CHG-048](#req-chg-048--approval-reminders-and-escalation) | Approval reminders and escalation | SAME | V1 | Professional |
| [REQ-CHG-049](#req-chg-049--backup-approvers-and-delegation) | Backup approvers and delegation | SAME | V1 | Professional |
| [REQ-CHG-050](#req-chg-050--approval-settings-for-changes) | Approval settings for changes | BETTER | V1 | Professional |
| [REQ-CHG-051](#req-chg-051--approval-decision-from-teams-and-slack) | Approval decision from Teams and Slack | SAME | LATER | Professional |
| [REQ-CHG-052](#req-chg-052--the-approval-outcome-moves-the-change) | The approval outcome moves the change | BETTER | V1 | Professional |
| [REQ-CHG-053](#req-chg-053--re-approval-when-the-plan-changes) | Re-approval when the plan changes | NEW | V1 | Professional |
| [REQ-CHG-054](#req-chg-054--cab-meetings-agenda-and-minutes) | CAB meetings: agenda and minutes | NEW | LATER | Professional |
| [REQ-CHG-055](#req-chg-055--emergency-approval) | Emergency approval | NEW | V1 | Professional |
| [REQ-CHG-056](#req-chg-056--risk-levels) | Risk levels | SAME | V1 | Professional |
| [REQ-CHG-057](#req-chg-057--risk-questionnaire-with-scoring) | Risk questionnaire with scoring | BETTER | V1 | Professional |
| [REQ-CHG-058](#req-chg-058--risk-set-by-rules) | Risk set by rules | SAME | V1 | Professional |
| [REQ-CHG-059](#req-chg-059--risk-decides-the-approval-path) | Risk decides the approval path | NEW | V1 | Professional |
| [REQ-CHG-060](#req-chg-060--override-risk-with-a-reason) | Override risk with a reason | SAME | V1 | Professional |
| [REQ-CHG-061](#req-chg-061--ai-risk-prediction) | AI risk prediction | BETTER | LATER | Professional |
| [REQ-CHG-062](#req-chg-062--change-window) | Change window | SAME | V1 | Professional |
| [REQ-CHG-063](#req-chg-063--downtime-schedule) | Downtime schedule | SAME | V1 | Professional |
| [REQ-CHG-064](#req-chg-064--downtimes-appear-on-the-cis) | Downtimes appear on the CIs | SAME | V1 | Professional |
| [REQ-CHG-065](#req-chg-065--change-calendar-views) | Change calendar views | BETTER | V1 | Professional |
| [REQ-CHG-066](#req-chg-066--calendar-filters-and-layers) | Calendar filters and layers | BETTER | V1 | Professional |
| [REQ-CHG-067](#req-chg-067--the-calendar-updates-live) | The calendar updates live | BETTER | V1 | Professional |
| [REQ-CHG-068](#req-chg-068--reschedule-by-dragging) | Reschedule by dragging | NEW | V1 | Professional |
| [REQ-CHG-069](#req-chg-069--day-agenda) | Day agenda | SAME | V1 | Professional |
| [REQ-CHG-070](#req-chg-070--scheduler-on-the-record) | Scheduler on the record | SAME | V1 | Professional |
| [REQ-CHG-071](#req-chg-071--calendar-subscription-feed) | Calendar subscription feed | NEW | LATER | Professional |
| [REQ-CHG-072](#req-chg-072--announce-planned-downtime) | Announce planned downtime | BETTER | V1 | Professional |
| [REQ-CHG-073](#req-chg-073--what-counts-as-a-conflict) | What counts as a conflict | BETTER | V1 | Professional |
| [REQ-CHG-074](#req-chg-074--conflicts-are-checked-on-every-change-and-shown) | Conflicts are checked on every change and shown | BETTER | V1 | Professional |
| [REQ-CHG-075](#req-chg-075--freeze-windows) | Freeze windows | SAME | V1 | Professional |
| [REQ-CHG-076](#req-chg-076--freeze-windows-block-or-warn-with-a-controlled-override) | Freeze windows block or warn, with a controlled override | BETTER | V1 | Professional |
| [REQ-CHG-077](#req-chg-077--maintenance-windows) | Maintenance windows | SAME | V1 | Professional |
| [REQ-CHG-078](#req-chg-078--suggest-a-free-slot) | Suggest a free slot | NEW | LATER | Professional |
| [REQ-CHG-079](#req-chg-079--links-to-other-records) | Links to other records | BETTER | V1 | Professional |
| [REQ-CHG-080](#req-chg-080--ci-and-asset-links-show-on-both-sides) | CI and asset links show on both sides | BETTER | V1 | Professional |
| [REQ-CHG-081](#req-chg-081--parent-and-child-changes) | Parent and child changes | SAME | V1 | Professional |
| [REQ-CHG-082](#req-chg-082--impact-analysis-from-the-cmdb) | Impact analysis from the CMDB | BETTER | V1 | Professional |
| [REQ-CHG-083](#req-chg-083--incidents-after-a-change-are-flagged) | Incidents after a change are flagged | NEW | V1 | Professional |
| [REQ-CHG-084](#req-chg-084--recent-changes-on-a-ci-or-service) | Recent changes on a CI or service | NEW | V1 | Professional |
| [REQ-CHG-085](#req-chg-085--live-health-on-the-change) | Live health on the change | NEW | V1 | Professional |
| [REQ-CHG-086](#req-chg-086--pre-change-and-post-change-health-checks) | Pre-change and post-change health checks | NEW | LATER | Professional |
| [REQ-CHG-087](#req-chg-087--no-metric-collection-for-health-checks) | No metric collection for health checks | SKIP | LATER | Professional |
| [REQ-CHG-088](#req-chg-088--change-tasks-per-stage) | Change tasks per stage | SAME | V1 | Professional |
| [REQ-CHG-089](#req-chg-089--implementation-tasks-on-the-calendar) | Implementation tasks on the calendar | NEW | LATER | Professional |
| [REQ-CHG-090](#req-chg-090--post-implementation-review) | Post-implementation review | BETTER | V1 | Professional |
| [REQ-CHG-091](#req-chg-091--review-date-and-reminder) | Review date and reminder | SAME | V1 | Professional |
| [REQ-CHG-092](#req-chg-092--change-closure-codes) | Change closure codes | SAME | V1 | Professional |
| [REQ-CHG-093](#req-chg-093--closure-rules-per-stage-required-fields) | Closure rules per stage: required fields | SAME | V1 | Professional |
| [REQ-CHG-094](#req-chg-094--closure-rules-per-stage-tasks-and-approvals) | Closure rules per stage: tasks and approvals | SAME | V1 | Professional |
| [REQ-CHG-095](#req-chg-095--closing-a-change-code-description-and-outcome) | Closing a change: code, description and outcome | SAME | V1 | Professional |
| [REQ-CHG-096](#req-chg-096--closing-waits-for-child-changes-and-releases) | Closing waits for child changes and releases | BETTER | V1 | Professional |
| [REQ-CHG-097](#req-chg-097--closed-changes-are-locked) | Closed changes are locked | SAME | V1 | Professional |
| [REQ-CHG-098](#req-chg-098--change-list-and-built-in-views) | Change list and built-in views | BETTER | V1 | Professional |
| [REQ-CHG-099](#req-chg-099--change-board) | Change board | NEW | LATER | Professional |
| [REQ-CHG-100](#req-chg-100--change-record-page) | Change record page | BETTER | V1 | Professional |
| [REQ-CHG-101](#req-chg-101--bulk-actions-on-changes) | Bulk actions on changes | SAME | V1 | Professional |
| [REQ-CHG-102](#req-chg-102--print-a-change-pack) | Print a change pack | BETTER | V1 | Professional |
| [REQ-CHG-103](#req-chg-103--notifications-per-stage-and-status) | Notifications per stage and status | SAME | V1 | Professional |
| [REQ-CHG-104](#req-chg-104--default-change-notifications) | Default change notifications | BETTER | V1 | Professional |
| [REQ-CHG-105](#req-chg-105--schedule-reminders) | Schedule reminders | NEW | V1 | Professional |
| [REQ-CHG-106](#req-chg-106--change-workflows-with-a-visible-run) | Change workflows with a visible run | BETTER | V1 | Professional |
| [REQ-CHG-107](#req-chg-107--business-rules-triggers-and-slas-on-changes) | Business rules, triggers and SLAs on changes | SAME | V1 | Professional |
| [REQ-CHG-108](#req-chg-108--scheduled-recurring-changes) | Scheduled recurring changes | SAME | LATER | Professional |
| [REQ-CHG-109](#req-chg-109--requesters-raise-and-follow-changes-in-the-portal) | Requesters raise and follow changes in the portal | SAME | V1 | Professional |
| [REQ-CHG-110](#req-chg-110--changes-and-approvals-on-the-mobile-app) | Changes and approvals on the mobile app | SAME | LATER | Professional |
| [REQ-CHG-111](#req-chg-111--draft-plans-and-summaries) | Draft plans and summaries | NEW | LATER | Professional |
| [REQ-CHG-112](#req-chg-112--similar-past-changes) | Similar past changes | NEW | LATER | Professional |
| [REQ-CHG-113](#req-chg-113--change-risk-reviewer-agent) | Change risk reviewer agent | NEW | LATER | Professional |
| [REQ-CHG-114](#req-chg-114--changes-from-deployment-pipelines) | Changes from deployment pipelines | NEW | LATER | Professional |
| [REQ-CHG-115](#req-chg-115--links-to-devops-work-items) | Links to DevOps work items | SAME | LATER | Professional |
| [REQ-CHG-116](#req-chg-116--change-data-for-reports-and-dashboards) | Change data for reports and dashboards | BETTER | V1 | Professional |
| [REQ-CHG-117](#req-chg-117--change-counters-in-the-personal-summary) | Change counters in the personal summary | SAME | V1 | Professional |
| [REQ-CHG-118](#req-chg-118--import-changes) | Import changes | SAME | LATER | Professional |
<!-- summary:end -->

---

## 1. The change work item

#### REQ-CHG-001 — Changes run on the work item engine

A change is a work item type on the shared engine. It inherits every engine capability from
file 01: history with source, live updates, presence, concurrency, actions decided by the
server, fixed tabs, notes, conversations, worklogs, reminders, attachments, checklists,
followers, trash, print, lists, views and bulk actions. Changes get their own display ID
counter with the prefix `CHG` (for example CHG-12), which an admin can change. Merge is not
offered for changes; related changes are linked or made parent and child (REQ-CHG-081).

- **Decision:** BETTER. ServiceDesk Plus rebuilds notes, timers, templates and approvals per
  module; on one engine a change behaves like every other record.
- **Source:** architecture §6.2, §2.4; sdp-area-05 §Screens (detail page left menu); sdp-area-13 §Advanced Portal Settings (change prefix "CH"); D-045
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. The engine contract test suite (REQ-WI-001 AC1) passes for the change type.
  2. The first change in a new tenant is CHG-1; changing the prefix keeps old IDs working.
  3. A tenant without the `change` entitlement cannot create or open changes through the API
     (403 with a problem code); the UI follows REQ-WI-025.
  4. The merge action is not offered on a change, and the API refuses it.

#### REQ-CHG-002 — Create a change from another record

A technician can create a change from an incident, a service request, a problem, a CI, an
asset or a release. The new change is pre-filled (title, description, category, requester,
services, CIs and assets) and linked to the source with the right relation on both sides.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Actions (CI: create change); architecture §2.1 (relationships), §2.4 (associations); REQ-INC-087
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Creating a change from a problem links them as "change for problem" / "problem of
     change", recorded on both records.
  2. Creating a change from a CI puts that CI in the change's CIs involved.
  3. The user can edit every pre-filled value before saving.

#### REQ-CHG-003 — Copy a change

A technician can copy a change, choosing which parts come along: fields, plans, roles, CIs and
services, tasks and checklists. The copy starts at the first stage with no approvals, no
history and no schedule unless chosen.

- **Decision:** SAME. Reuses the engine copy behaviour (REQ-INC-033).
- **Source:** sdp-area-05 §Actions (copy change); REQ-INC-033
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A copy never carries over approval decisions or the approval status.
  2. The copy's history names the source change.
  3. Copying with "plans" selected copies rollout, backout and test plans as editable text.

#### REQ-CHG-004 — Record a change after the fact

A technician can log a retrospective change: work already done, for example during an outage.
It is marked retrospective, records actual start and end times, skips approval stages in the
past, and must still pass review and closure. Retrospective changes are reported separately.

- **Decision:** BETTER. ServiceDesk Plus has a yes/no field with no effect on the flow.
- **Source:** sdp-area-05 §Fields (retrospective)
- **SDP weak spot fixed:** the retrospective flag changes nothing on the record or the flow.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A retrospective change requires actual start and end, both in the past.
  2. It enters at the review stage with a visible "retrospective" marker in lists and on the
     record.
  3. Reports can filter and count retrospective changes.

---

## 2. Change types and change models

#### REQ-CHG-005 — Change types bound to a change model

Admins define change types with a name, colour, description and translations. Each type is
bound to exactly one change model, and the model fixes its behaviour:

| Model | Approval | Typical path |
|---|---|---|
| standard | pre-approved at creation | short: submission, implementation, closure |
| normal | assessed and approved per risk | full path with planning and CAB review |
| emergency | fast approval by the emergency board | shortened path, review is mandatory |

Types show with their colour in lists, the calendar and the record header.

- **Decision:** BETTER. ServiceDesk Plus types are only labels with a hidden "pre-approval"
  toggle; the template's own "emergency" category is separate from the type.
- **Source:** sdp-area-05 §Config (change type), §Weak spots; sdp-area-05 (5b) §5b-1, §5b-2; architecture §2.4 (change types)
- **SDP weak spot fixed:** the standard type looks special but nothing explains what it does;
  "emergency" is a template category, not a type.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Saving a type without a model is refused.
  2. The type picker shows each type's model and description.
  3. A type in use cannot be deleted; it can be disabled for new changes.
  4. A new tenant has the default types in Appendix A.

#### REQ-CHG-006 — Standard changes are pre-approved

A change of a standard-model type is approved at creation. The record says why ("pre-approved
standard change, model X") instead of showing an unexplained tick. If someone edits fields the
standard model locks (for example the CIs or the plan), the change stops being standard and
must go through normal approval, with a warning first.

- **Decision:** BETTER. Pre-approval is explained and protected against misuse.
- **Source:** sdp-area-05 (5b) §5b-1 (approved at creation), §5b-2 (pre-approval toggle); architecture §2.4
- **SDP weak spot fixed:** approval shows "Approved" at creation with no visible reason.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Creating a standard change sets the approval state to approved, with a history entry
     naming the standard model.
  2. Editing a locked field shows a warning; confirming converts the change to normal and
     resets its approval state to not submitted.
  3. Only users allowed to raise that standard model can create it.

#### REQ-CHG-007 — Standard change catalogue

Admins publish a catalogue of standard change models: a pre-approved, repeatable change with a
fixed template, plan, tasks, risk and allowed CIs. Technicians pick a model and fill only the
variable fields. Each model has an owner, a review date, and usage and success counts. A model
whose recent changes failed can be suspended.

- **Decision:** NEW. ServiceDesk Plus has only a pre-approval toggle per type.
- **Source:** architecture §2.4 (pre-approved standard change catalog)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A technician can raise a standard change from the catalogue in one form with only the
     model's variable fields.
  2. Each model shows how many changes used it and how many failed, live.
  3. A suspended model is not offered; changes already raised from it are unaffected.
  4. A model past its review date shows a warning to its owner.

#### REQ-CHG-008 — Emergency changes

An emergency-model change takes a shortened path: submission, emergency approval,
implementation, review and closure. Approval comes from the emergency board (REQ-CHG-055),
which can decide outside working hours. A post-implementation review is always required. An
emergency change can override a freeze window when the overrider has permission and gives a
reason (REQ-CHG-076).

- **Decision:** BETTER. In ServiceDesk Plus the emergency workflow simply skips planning and
  approval; nothing replaces the missing control.
- **Source:** sdp-area-05 (5b) §5b-1 (emergency workflow); architecture §2.4
- **SDP weak spot fixed:** the emergency path has no approval at all and no required review.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. An emergency change cannot enter implementation without an emergency board decision, or a
     recorded override by a user with the "emergency override" permission.
  2. Closing an emergency change without a completed review is refused.
  3. Reports can show the share of emergency changes per month.

---

## 3. Change record fields

#### REQ-CHG-009 — Change record core fields

A change has these fields in addition to the engine fields:

- title (required), description (rich text), requester, site, group, change owner, change
  manager;
- change type, template, category, subcategory and item;
- impact, urgency, priority (REQ-CHG-010), risk (section 8), reason for change;
- services affected, CIs involved, assets involved (REQ-CHG-012);
- change window and downtime (section 9), budget (REQ-CHG-014);
- stage, status and approval state, which are read-only and set only by the life cycle and
  approvals.

- **Decision:** SAME.
- **Source:** sdp-area-05 §Fields; sdp-area-05 (5b) §5b-1 (fields per template); architecture §2.4
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Creating a change through the API with only a title and type succeeds; the template's
     required fields are then enforced.
  2. Stage, status and approval state cannot be set through create or edit; the API refuses
     them with a problem code.
  3. All fields can be used in list columns, filters and reports.

#### REQ-CHG-010 — Impact, urgency and priority on clean scales

Changes use the same separate impact and urgency scales as incidents (REQ-INC-008), and a
change priority matrix fills in priority. The matrix ships filled in (Appendix A). Overrides
follow REQ-INC-010.

- **Decision:** BETTER. ServiceDesk Plus mixes two impact scales in one list and has no
  priority calculation for changes.
- **Source:** sdp-area-05 §Fields (impact, priority), §Behaviour (impact and urgency do not drive priority), §Weak spots; sdp-area-13 §Weak spots (mixed impact list)
- **SDP weak spot fixed:** impact mixes "affects user" values with high/medium/low; priority is
  never calculated.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Setting impact and urgency sets priority from the matrix in the same change, with history.
  2. The impact list has one scale only; the seed data has no severity words in it.
  3. An admin can use a change matrix that differs from the incident matrix.

#### REQ-CHG-011 — Reason for change

Admins keep a list of reasons for change (for example security fix, new service, capacity,
compliance). The list is translatable and reportable. A template can make it required.

- **Decision:** SAME.
- **Source:** sdp-area-05 §Config (reason for change)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A disabled reason is not offered but still shows on old changes.
  2. Reports group changes by reason.

#### REQ-CHG-012 — Services, CIs and assets involved

A change lists the services it affects, the CIs it touches and the assets involved. Pickers
search the CMDB, the asset register and the service catalogue with filters (type, site) and
show only items the user may see. Adding a CI offers to add the services that depend on it.

- **Decision:** BETTER. CIs are a first-class field on every change form, not an extra field
  that must be dragged onto the template.
- **Source:** sdp-area-05 §Fields (services affected, assets involved); sdp-area-05 §Config (template editor: CIs involved only in "available" fields); sdp-area-07 (7b) §7b.5 (asset picker on a change)
- **SDP weak spot fixed:** CIs involved are missing from the default change form.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Adding a CI that three services depend on offers to add those three services in one step.
  2. The picker never lists CIs or assets outside the user's fine-grained access.
  3. Changing CIs or services re-runs conflict detection (REQ-CHG-074) and impact analysis
     (REQ-CHG-082).

#### REQ-CHG-013 — Plans: impact, rollout, backout and test

A change carries planning sections, each rich text with attachments and its own history:

- impact details (what is affected and how);
- rollout plan (the steps);
- backout plan (how to undo the change);
- test plan (how success is checked);
- implementation checklist (engine checklist, REQ-INC-077).

Templates decide which sections show and in which stage each is required.

- **Decision:** BETTER. Adds a test plan and requires plans by stage, not only on closure.
- **Source:** sdp-area-05 §Screens (planning details sections), §Actions (enter impact, rollout, backout, checklist); architecture §2.4 (planning)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Each section saves on its own and records who changed it and when.
  2. With the default normal template, leaving planning without a backout plan is refused and
     the prompt asks only for the backout plan.
  3. Plans are sanitised rich text (REQ-INC-064).

#### REQ-CHG-014 — Budget and cost

A change has a budget and shows actual cost: worklog cost (REQ-INC-068) plus task extra costs
plus manual cost lines. Over-budget changes are marked. Currency follows the tenant settings.

- **Decision:** BETTER. ServiceDesk Plus has only a budget field with no comparison.
- **Source:** sdp-area-05 §Fields (budget); sdp-area-09 §Screens (change reports by cost)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Adding a worklog with cost updates the change's actual cost live.
  2. Actual cost above budget shows an over-budget marker and can trigger a notification.

#### REQ-CHG-015 — Custom fields per stage

Admins add custom fields to changes (all field types the engine supports, REQ-INC-014) and
place them in a stage's section. A field can be required in one stage and read-only in later
stages.

- **Decision:** SAME.
- **Source:** sdp-area-05 §Config (template editor, new field types); sdp-area-13 §Additional Fields (change module)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A field marked "required in planning" blocks leaving planning while empty.
  2. A field marked "read-only after CAB review" cannot be edited after that stage through the
     UI or the API.

#### REQ-CHG-016 — Planned and actual times per stage

Each stage records when it was entered and left. Stages that have their own schedule
(implementation, acceptance testing, deployment) have planned and actual start and end. Actual
times are stamped by the transitions, and can be corrected with a reason.

- **Decision:** BETTER. ServiceDesk Plus has separate schedule fields only for some stages and
  stamps nothing automatically.
- **Source:** sdp-area-05 §Screens (stage detail: UAT and release dates); sdp-area-06 §Behaviour (per-stage schedules on releases)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Moving to "implementation in progress" stamps actual start; the completing status stamps
     actual end.
  2. Correcting an actual time needs a reason and is recorded in history.
  3. Time spent per stage is available to reports.

#### REQ-CHG-017 — Implementation overdue marker

A change whose implementation has not finished by the scheduled end is marked overdue,
automatically, in lists, on the calendar and on the record. The marker clears when the
implementation stage completes.

- **Decision:** BETTER. ServiceDesk Plus has a hand-set "implementation status" dropdown.
- **Source:** sdp-area-05 §Fields (implementation status)
- **SDP weak spot fixed:** implementation overdue is a manual field, so it is often wrong.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. One minute after the scheduled end, an unfinished change shows as overdue on every open
     screen, live.
  2. The owner and change manager are notified once when it becomes overdue.
  3. There is no editable implementation status field.

---

## 4. Templates and forms

#### REQ-CHG-018 — Change templates bring everything together

A change template binds in one place: change type, life cycle or workflow, form layout per
stage, default roles, tasks, checklists, risk questionnaire and approval set-up. Picking a
template sets all of them. There is no separate workflow picker on the change form.

- **Decision:** BETTER. One choice instead of three screens and two pickers.
- **Source:** sdp-area-05 §Fields (select workflow and select template), §Weak spots; sdp-area-05 (5b) §5b-1 (standard template has no workflow); sdp-area-12 §Config (change template designer)
- **SDP weak spot fixed:** template and workflow are separate choices, standard and normal
  templates have no workflow, and setting up a type needs three screens.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A template cannot be published without a life cycle or workflow; the message names what
     is missing.
  2. The change form shows a template picker only; the life cycle comes from the template.
  3. The template page links to its life cycle and shows a summary of it.

#### REQ-CHG-019 — Template designer with stage sections

Admins design change templates with the shared form designer (REQ-INC-036): sections per
stage, field placement, required and read-only flags per stage, help text, and form rules
that run the same in the browser and on the server (REQ-INC-037). Inline edits on the record
run the same form rules, so inline editing never has to be switched off. A preview shows the
form as a technician and as a requester.

- **Decision:** SAME.
- **Source:** sdp-area-05 §Config (template editor); sdp-area-12 §Config (template designers); sdp-area-13 §Advanced Portal Settings (disable spot edit if a form rule exists); architecture §6.6
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A section placed in the planning stage shows only on the planning stage page.
  2. A form rule that requires the backout plan when risk is high is enforced by the API too.
  3. The designer works with keyboard and in right-to-left layout.

#### REQ-CHG-020 — Who can use a template

A template can be offered to technicians, to requesters (in the portal) or both, and limited
to user groups, sites or roles. The "new change" menu groups the templates a user may use by
type and can be searched. The default template can be changed but always exists.

- **Decision:** SAME.
- **Source:** sdp-area-05 §Config (template availability, user groups, default template cannot be disabled); sdp-area-05 §Screens (new change menu grouped by template)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A template limited to one user group is offered only to its members, in the console and
     the portal.
  2. Disabling the default template is refused until another default is chosen.

#### REQ-CHG-021 — When template tasks are created

For each template task, the admin chooses when it is created: manually, when the change is
created, or when the change enters a given stage. Tasks created by a stage say so in history.

- **Decision:** BETTER. ServiceDesk Plus has one "trigger tasks" setting per template.
- **Source:** sdp-area-05 §Config (task trigger settings), §Automation (task triggers); sdp-area-12 (12b) §Configuration options (template tasks)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A task set to "on entering implementation" appears when that stage starts, not before.
  2. The history entry names the template and the stage that created the task.

#### REQ-CHG-022 — Default templates

A new tenant has a working template for each default type (Appendix A), each with a life
cycle, roles and plan sections. They work with no admin set-up and can be copied and edited.

- **Decision:** BETTER. ServiceDesk Plus ships two of its four change templates without a
  workflow.
- **Source:** sdp-area-05 §Config (four system templates); sdp-area-05 (5b) §5b-1
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. In a new tenant, a change can be raised from each default template and taken to closure
     with no admin set-up.
  2. Each default template is bound to a life cycle.

---

## 5. Stages, statuses and transitions

#### REQ-CHG-023 — Stages with fixed meaning, statuses inside them

A change moves through stages. Each stage has a fixed meaning; admins rename stages, translate
them and define the statuses inside each stage. Each status also has a status category
(REQ-INC-044), so SLA clocks and reports work as for every other type. Exactly one status per
stage is its completing status, and stages may have end statuses (rejected, canceled, failed).

- **Decision:** SAME.
- **Source:** sdp-area-05 §Screens (stage rail, workflow statuses per stage), §Config (stage and status); architecture §2.4 (stages); REQ-WI-026 (engine stage model)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Saving a stage without exactly one completing status is refused.
  2. A status in use cannot be deleted; it can be disabled for new transitions.
  3. Reports can group by stage, by status and by status category.

#### REQ-CHG-024 — Default change life cycle

A new tenant has a ready-made change life cycle with the stages submission, planning, CAB
review, implementation, acceptance testing, deployment, review and closure, their statuses
and the allowed transitions (Appendix A). It works on day one.

- **Decision:** BETTER. Same stage set, with transitions shipped and documented.
- **Source:** sdp-area-05 §Screens (eight stages, statuses per stage); architecture §2.4
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A new tenant's first normal change follows the default life cycle with no admin set-up.
  2. Only the transitions in Appendix A are offered from each status.

#### REQ-CHG-025 — Stage and status move only through allowed transitions

The stage is never set by hand. It moves when the completing status of a stage is reached, or
when an allowed backward transition is run. Status changes follow the life cycle on every path
(record, list, bulk, API, rules, workflows, AI agents), as REQ-INC-046 requires. A change
cannot be "outside" its life cycle.

- **Decision:** BETTER. ServiceDesk Plus lets a person set any status by hand and only flags
  the change as "violated".
- **Source:** sdp-area-05 §Behaviour (manual status change flagged violated), §Weak spots; sdp-area-05 §Automation (stage never set by hand); REQ-INC-046
- **SDP weak spot fixed:** manual status changes break the workflow and are only flagged.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. The API refuses a status that is not an allowed transition from the current status, with
     a problem code, on every path.
  2. Reaching the completing status of planning moves the change to the next stage on its path
     in the same transaction.
  3. A status that needs an approval decision (for example "approved") cannot be chosen by
     hand; it is set only by the approval outcome (REQ-CHG-052).

#### REQ-CHG-026 — One status dialog everywhere

Changing a change's status always opens the same small dialog, from the record header, the
edit form, the list, the board and the stage page. It asks for the reason or comment the
transition needs (REQ-INC-047) and the fields it requires (REQ-INC-048), and nothing else.

- **Decision:** BETTER.
- **Source:** sdp-area-05 §Fields (edit form behaviour), §Actions (status popup), §Weak spots
- **SDP weak spot fixed:** the status comment box is disabled in the edit form, so a status
  change there always fails.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Changing status from the edit form and from the header gives the same prompt and result.
  2. A transition with a required comment cannot be saved without one, with a field error.

#### REQ-CHG-027 — Stage paths per type

The template's life cycle decides which stages a change passes through. By default a standard
change skips planning, CAB review, acceptance testing and deployment; an emergency change
skips planning, acceptance testing and deployment and has an emergency approval in CAB review;
a minor change skips CAB review (Appendix A). Skipped stages do not show in the stage rail.

- **Decision:** SAME.
- **Source:** sdp-area-05 (5b) §5b-1 (stages per template: 8, 6 and 4); architecture §2.4
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A standard change shows four stages in its rail and moves from submission straight to
     implementation.
  2. A skipped stage's required fields and approvals are not asked for.

#### REQ-CHG-028 — Stage pages on the record

The record shows a stage rail with the current stage, completed stages and stages to come.
Each stage has a page with its own fields, notes, attachments, tasks and approvals: CAB review
notes, implementation notes, acceptance test results, deployment notes and issues, review
findings and closure details. Past stages stay readable.

- **Decision:** SAME.
- **Source:** sdp-area-05 §Screens (stage rail, stage detail tabs)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. The stage rail updates live when another user completes a stage.
  2. Selecting a past stage shows its data read-only, with who completed it and when.
  3. Each stage page keeps the same tab order on every change (REQ-WI-011).

#### REQ-CHG-029 — Restrict stages by role

Admins decide per stage who may edit the stage's data and who may run its transitions: change
roles (REQ-CHG-034), groups or permission roles. Others see the stage read-only.

- **Decision:** SAME.
- **Source:** architecture §2.4 (restrict stage access by role); sdp-area-12 §Config (life cycle transition scope)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. With review limited to the reviewer role, another technician sees the review page
     read-only and the API refuses their edit with 403.
  2. The action state (REQ-WI-010) gives the reason "only the reviewer can complete review".

#### REQ-CHG-030 — Change life cycle designer

Admins design change life cycles on the shared designer (REQ-INC-049), with stages drawn as
lanes and statuses inside them. The designer shows how every status fits: which are
completing, which end the change, and which are unreachable. A status added in settings
appears in the designer, unconnected and flagged, so it cannot silently break running changes.

- **Decision:** BETTER.
- **Source:** sdp-area-05 §Config (stage and status), §Weak spots; sdp-area-12 (12b) §Screens (life cycles); REQ-INC-049
- **SDP weak spot fixed:** statuses are added on a settings page that does not show how they fit
  into the workflow, and doing so can make changes violate it.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Publishing a life cycle with an unreachable status is refused, and the message names it.
  2. Publishing version 2 does not change changes running on version 1 until migrated.
  3. The designer shows stages as lanes in left-to-right and right-to-left layouts.

#### REQ-CHG-031 — Go back a stage

Allowed backward transitions return a change to an earlier stage, for example from CAB review
to planning after a rejection with "re-plan", or from acceptance testing to implementation
after a failed test. Going back requires a reason, keeps all earlier data and resets the
approvals of the stages it re-enters.

- **Decision:** BETTER. Re-planning after a rejection is an explicit path, not a manual status
  edit.
- **Source:** sdp-area-05 §Screens (workflow statuses: rejected in planning, CAB and UAT)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Returning to planning keeps the plans and records the reason in history.
  2. CAB approvals given before going back are marked superseded and a new approval round is
     needed.

#### REQ-CHG-032 — Implementation outcome: completed, backed out or failed

The implementation stage ends with an outcome: successful, successful with issues, backed out
or failed. Backed out and failed need a reason and lead to a mandatory review. The outcome is
reportable and feeds the change success rate.

- **Decision:** BETTER. ServiceDesk Plus offers "back out" only inside one seeded workflow.
- **Source:** sdp-area-05 (5b) §5b-1 (standard workflow: implementation back out); sdp-area-05 §Screens (review failed)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Completing implementation without an outcome is refused.
  2. A backed-out change cannot be closed without a completed review.
  3. Reports show success rate by type, template and group.

#### REQ-CHG-033 — Withdraw or cancel a change

The requester can withdraw their change before it is approved. The owner or change manager can
cancel a change at any stage before implementation starts, with a reason. A canceled change
releases its schedule, so it no longer causes conflicts.

- **Decision:** SAME.
- **Source:** sdp-area-05 §Screens (close stage: cancelled); sdp-area-14 §Screens (change closure codes: canceled, rejected); REQ-INC-100
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Canceling a scheduled change removes it from conflict checks of other changes, live.
  2. A requester cannot withdraw a change after approval; the action shows disabled with a
     reason.

---

## 6. Change roles and assignment

#### REQ-CHG-034 — Change roles on the record

A change has named roles, each held by one or more users or a group:

- requester, change owner, change manager;
- approvers, line manager, CAB (REQ-CHG-040);
- implementer, testing owner, reviewer.

The roles panel shows every role and its holders. Roles can be set on the create form, from
the template, by rules, or edited later with permission. Role holders get the notifications
and stage rights that the template gives their role.

- **Decision:** SAME.
- **Source:** sdp-area-05 §Fields (roles section), §Actions (roles page), §Config (change role); architecture §2.4 (roles)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Changing the implementer notifies the new and old holder and records history.
  2. A role held by a group gives every group member that role's rights on the change.
  3. The roles panel updates live.

#### REQ-CHG-035 — Admin-defined change roles

Admins add their own change roles (for example security reviewer, vendor contact) with a
name, description and translations. Custom roles work like the built-in ones in templates,
stage rights, approvals and notifications.

- **Decision:** SAME.
- **Source:** sdp-area-05 §Config (change role, 9 seeded roles); architecture §2.4 (custom change roles)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A custom role can be made an approver of a stage in a template.
  2. A role in use by a template cannot be deleted.

#### REQ-CHG-036 — Line manager filled in from the requester

The line manager role is filled in from the requester's reporting manager by default, and
changes when the requester changes. Other organisation roles (department head, site manager)
can be used for approval the same way.

- **Decision:** BETTER. ServiceDesk Plus asks for the line manager by hand on the form.
- **Source:** sdp-area-05 §Fields (line manager); sdp-area-11 §Automation (organisation roles feed approvals)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Setting a requester with a reporting manager fills the line manager role.
  2. A requester with no reporting manager leaves the role empty and, if a stage needs line
     manager approval, the submit action explains what is missing.

#### REQ-CHG-037 — Assign, take and reassign changes

Changes are assigned to a group and a change owner as incidents are (REQ-INC-053, REQ-INC-054,
REQ-INC-055). A change manager can be set separately. Assignment rules from file 03 can set
group, owner and manager.

- **Decision:** SAME.
- **Source:** sdp-area-05 §Actions (assign, pick up), §Behaviour (no assignment rules fired)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. "Take" on an unassigned change sets the user as change owner, live in the list.
  2. A group with an assignment rule for changes assigns new changes to it on creation.

#### REQ-CHG-038 — Change permissions you can read

Change actions have their own permissions: create, edit, assign, approve, move stages, edit
plans, manage CABs, override freeze windows, close and delete. A built-in "change manager"
role exists, and admins can read and copy every built-in role to see what it grants.

- **Decision:** BETTER. ServiceDesk Plus built-in roles, including its change manager role, cannot
  be opened.
- **Source:** sdp-area-11 §Fields (role matrix, roles list), §Weak spots; architecture §11.2 (module and action); sdp-area-15 §Approvals flow (change manager could not move a change forward), §Dashboards, Site Admin and Change Manager, §Weak spots
- **SDP weak spot fixed:** an admin cannot see what the built-in change manager role grants.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. An admin can open the built-in change manager role and see every permission it holds.
  2. A technician without "override freeze window" cannot override one; the API returns 403.
  3. A user holding only the built-in change manager role can move a change through every stage
     to closure (approvals permitting) without a permission error.
  4. Every role's change permissions are readable by any admin at any time; no role, built-in or
     migrated, is hidden from the role list.

#### REQ-CHG-039 — Segregation of duties on changes

By default the requester and the implementer of a change cannot approve it. Admins can add more
rules, for example "the change owner cannot be the only approver". A conflict is shown when
approvers are chosen, not only when they try to approve.

- **Decision:** NEW.
- **Source:** architecture §11.2 (segregation of duties: the requester of a change cannot approve it)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Adding the requester as an approver shows a warning naming the rule, and their approve
     action is refused with a problem code.
  2. A CAB member who is the implementer is skipped for that change and the quorum is
     computed without them.

---

## 7. Change advisory board and approvals

Change approvals are built on the shared approval engine specified in file 02 (REQ-SR-021 to
REQ-SR-039: stages, parallel and conditional approvers, delegation, backups, reminders, safe
one-time links). The requirements below add what changes need on top of it: CABs, quorum,
per-stage approvals and re-approval. They are not a second approval implementation.

#### REQ-CHG-040 — Change advisory boards

Admins define CABs: name, description, members (users, groups, and requesters or external
stakeholders who are users), an optional chair, and a quorum rule (REQ-CHG-044). A member can
be marked optional. Members get the CAB role on the changes their board reviews.

- **Decision:** BETTER. A CAB is more than a named member list: it has a chair, quorum and
  optional members.
- **Source:** sdp-area-05 §Config (CAB: name, description, members); architecture §2.4 (CAB definitions including requesters)
- **SDP weak spot fixed:** a CAB is only a list of users with no rules.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Saving a CAB without members is refused.
  2. Removing a member updates pending approvals: their pending decision is withdrawn and the
     quorum recomputed, with history on the affected changes.
  3. A requester who is a CAB member can approve from the portal.

#### REQ-CHG-041 — The right CAB is chosen automatically

Admins map CABs to changes by type, service, site, risk level or template. When a change
reaches CAB review the matching board is assigned. If several match, all of them review, or
the first in order, as the admin chooses. The change shows which CAB and why.

- **Decision:** BETTER.
- **Source:** sdp-area-05 §Weak spots (nothing connects a CAB to a type, template or approval step)
- **SDP weak spot fixed:** nothing visibly connects a CAB to a change type, template or
  approval step.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A high-risk change on the payroll service gets the CAB mapped to that service, with a
     history entry naming the mapping.
  2. When no CAB matches, the default CAB is used and the change says so.

#### REQ-CHG-042 — Approvals per stage

A template sets approval levels on any stage: for example line manager at submission, change
manager after planning, CAB at CAB review, reviewer after review. Each level names its
approvers (users, groups, change roles, organisation roles, CABs) and its rule.

- **Decision:** SAME.
- **Source:** sdp-area-05 §Automation (approvals drive submission, planning and CAB statuses); sdp-area-14 §Screens (all stage approvals approved, per stage); architecture §2.4 (multi-stage approvals)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Entering a stage with an approval level sends the requests to that level's approvers.
  2. A stage with pending approvals cannot complete; the action shows disabled with the
     reason.
  3. The approvals tab lists every level, approver and decision, live (REQ-INC-083).

#### REQ-CHG-043 — Multi-level approvals in sequence

Within a stage, approval levels run in order: level 2 starts only when level 1 is approved.
Admins can let one approver who already approved an earlier level be approved automatically at
a later level.

- **Decision:** SAME.
- **Source:** architecture §2.4 (multi-level CAB approvals); sdp-area-13 §Approval Settings (auto-approve same approver at earlier level)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Level 2 approvers are not asked until level 1 is approved.
  2. With "skip repeat approver" on, a person approving both levels is asked once, and history
     records the automatic approval and why.

#### REQ-CHG-044 — Approval rules and quorum

Each approval level has a rule: anyone, everyone, majority, or a quorum (for example "at least
3 of 7, including the chair"). One rejection rejects under "everyone". The level shows how
many decisions are still needed.

- **Decision:** BETTER. Adds quorum with a required member, which a CAB needs.
- **Source:** sdp-area-12 §Fields (approval rules: anyone, everyone, first response, majority); architecture §2.4
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. With "3 of 7 including the chair", three approvals without the chair leave the level
     pending.
  2. The level shows "2 more decisions needed" and updates live as members decide.
  3. Once the outcome is decided, remaining approvers are told their decision is no longer
     needed.

#### REQ-CHG-045 — Approvals work without mail and cannot be replayed

Approvers decide in the console, the portal, the mobile app or from an email link. Approvals
never depend on a mail server. Email links are single-use, expire, and are tied to the
approver; a forwarded or reused link asks the reader to sign in.

- **Decision:** BETTER. In ServiceDesk Plus no change approval could be exercised without mail.
- **Source:** sdp-area-05 §Automation (approving needs mail), §Weak spots; sdp-area-05 §Screens (approvals: mail server not configured); REQ-INC-083
- **SDP weak spot fixed:** the approval path is dead without a mail server.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. With no mail configured, a CAB member approves in the console and the change moves on.
  2. Using an email approval link a second time does not record a second decision.
  3. An email link opened by someone other than the approver records nothing and asks them to
     sign in.

#### REQ-CHG-046 — Approvers see the whole change

The approval view shows everything an approver needs on one page: summary, type and model,
risk score and answers, plans, schedule and downtime, conflicts, impact analysis, health
check results if any, linked incidents and problems, and earlier decisions with comments.

- **Decision:** BETTER.
- **Source:** architecture §2.4 (approvals); product-plan §7.3 (CAB summary)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. An approver with no other access to changes can open the approval view for changes they
     must decide, and nothing else.
  2. Unresolved conflicts show at the top of the approval view.

#### REQ-CHG-047 — Ask for clarification

An approver can ask a question instead of deciding. The approval level pauses, the question
goes to the change owner and requester, and the answer reopens the decision for that
approver. Questions and answers are kept with the approval.

- **Decision:** SAME.
- **Source:** architecture §2.4 (clarification requests)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A clarification request notifies the change owner and shows "waiting for clarification"
     on the level.
  2. The owner's answer notifies the approver, and the approver can then decide.

#### REQ-CHG-048 — Approval reminders and escalation

Pending approvers are reminded on a schedule in business hours (Appendix A). If a level stays
pending past a limit, it escalates to the change manager or a named person.

- **Decision:** SAME.
- **Source:** sdp-area-13 §Advanced Portal Settings (approval reminder); architecture §2.4 (reminders)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Under default settings, an approver who has not acted for 2 business days is reminded.
  2. The escalation is recorded on the change and notifies the escalation target.

#### REQ-CHG-049 — Backup approvers and delegation

An approver can name a backup for a period (for example leave), and admins can set a backup
per CAB member. During the period, requests go to both, and the first decision counts. The
record shows who decided on whose behalf.

- **Decision:** SAME.
- **Source:** architecture §2.4 (backup approvers); sdp-area-12 §Screens (delegation)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. During a delegation, a decision by the backup is recorded as "on behalf of" the
     approver.
  2. A backup cannot approve a change they raised (REQ-CHG-039).

#### REQ-CHG-050 — Approval settings for changes

Tenant settings for change approvals: comment required on rejection (on by default) or on
every decision, notify the other approvers when one decides, and pause the change's SLA while
waiting for approval.

- **Decision:** BETTER. Comments on rejection are required by default.
- **Source:** sdp-area-13 §Approval Settings
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Rejecting without a comment is refused under default settings.
  2. With "pause SLA while waiting", the change SLA clock pauses on submit and resumes on the
     decision.

#### REQ-CHG-051 — Approval decision from Teams and Slack

Approvers can approve, reject or ask for clarification from a Teams or Slack message, with
the same single-use rules as email links.

- **Decision:** SAME.
- **Source:** architecture §2.14 (Teams approvals, actionable messages)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A Teams decision appears on the change within 1 second, with the channel recorded.
  2. A decision from a Teams account not linked to the approver is refused.

#### REQ-CHG-052 — The approval outcome moves the change

When a level's outcome is decided, the change moves to the matching status: approved goes to
the completing status of the stage, rejected goes to the stage's rejected status. Approval
status is never a field that people, rules or workflows can set directly.

- **Decision:** BETTER.
- **Source:** sdp-area-05 §Automation (submission accepted comes from approval); sdp-area-12 §Config (approval status set by field update)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. The last needed CAB approval moves the change to "CAB approved" and on to implementation
     in one transaction.
  2. A rule or workflow action that tries to set approval status is refused at design time.

#### REQ-CHG-053 — Re-approval when the plan changes

If key details change after approval (schedule, CIs, services, risk, plans), the change is
marked "changed since approval". By default schedule moves beyond a tolerance and risk
increases restart the approval of the affected stage; other edits notify the approvers. Admins
choose which fields do what.

- **Decision:** NEW.
- **Source:** architecture §2.4 (approvals); sdp-area-13 §Approval Settings (restart approval after a resource update, service requests)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Moving an approved change's window by more than the tolerance resets CAB approval and
     notifies the CAB.
  2. Raising the risk from medium to high restarts approval at the level the new risk needs.
  3. The record shows what changed since approval, field by field.

#### REQ-CHG-054 — CAB meetings: agenda and minutes

A CAB can hold meetings. The meeting agenda lists the changes waiting for that CAB, ordered by
scheduled start, with their summaries. During the meeting, decisions recorded for each change
count as the members' approvals when the chair confirms attendance. Minutes are kept and linked
from each change.

- **Decision:** NEW.
- **Source:** architecture §2.4 (CAB approvals); product-plan §7.3 (CAB summary)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A change entering CAB review appears on the CAB's next meeting agenda live.
  2. Recording "approved" in the meeting creates approval decisions for the members marked
     present, with source "CAB meeting".
  3. The minutes are linked from each change discussed.

#### REQ-CHG-055 — Emergency approval

Emergency changes are approved by the emergency CAB, which can be smaller and decides with its
own rule (by default any one member). Every emergency CAB decision is reviewed afterwards by
the full CAB in the post-implementation review.

- **Decision:** NEW. ServiceDesk Plus emergency changes have no approval step.
- **Source:** sdp-area-05 (5b) §5b-1 (emergency workflow has no approval node); architecture §2.4
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. An emergency change notifies every emergency CAB member on all their channels at once.
  2. One approval by any emergency CAB member moves it to implementation under the default
     rule.
  3. The review stage of an emergency change has a CAB review level by default.

---

## 8. Risk assessment

#### REQ-CHG-056 — Risk levels

Admins define risk levels (name, colour, description, translations) in order from lowest to
highest. The default set is low, medium, high and very high (Appendix A).

- **Decision:** SAME.
- **Source:** sdp-area-05 §Config (change risk: three values)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Reports can group and sort changes by risk level in its defined order.
  2. A level in use cannot be deleted.

#### REQ-CHG-057 — Risk questionnaire with scoring

A template can include a risk questionnaire. Each question has weighted answers; the total
score maps to a risk level through bands. The answers, score and level are saved on the
change and shown to approvers. The default questionnaire is in Appendix A.

- **Decision:** BETTER. ServiceDesk Plus risk is a bare dropdown with no calculation.
- **Source:** sdp-area-05 §Config (change risk), §Weak spots; architecture §2.4 (risk questionnaire with scoring); product-plan §5 (change enablement)
- **SDP weak spot fixed:** risk has no questionnaire, score or link to impact.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Answering the default questionnaire with a total of 9 sets risk to high.
  2. Changing one answer recomputes the score and level at once, in the form and on the server.
  3. A questionnaire edit does not change the score of changes already assessed; they keep the
     version they used.

#### REQ-CHG-058 — Risk set by rules

Business rules (file 03) can set or raise the risk level, for example "any change to a
service marked critical is at least high". A rule never lowers a questionnaire result unless
the admin allows it. History names the rule.

- **Decision:** SAME.
- **Source:** architecture §2.4 (risk by business rules)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A change touching a critical service gets risk high, with a history entry naming the rule.
  2. A rule that would lower a questionnaire result is ignored and the trace says why.

#### REQ-CHG-059 — Risk decides the approval path

Templates can map risk levels to approval set-ups: for example low and medium need the change
manager, high needs the CAB, very high needs the CAB with the chair. The mapping is applied
when the change enters the stage, and again if the risk changes (REQ-CHG-053).

- **Decision:** NEW.
- **Source:** architecture §2.4 (risk, approvals)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A low-risk normal change goes to the change manager only, under the defaults.
  2. A very high-risk change cannot complete CAB review without the chair's approval.

#### REQ-CHG-060 — Override risk with a reason

A change manager can override the calculated risk, giving a reason. The calculated and the
chosen level are both kept and shown.

- **Decision:** SAME. Manual risk stays available (architecture §2.4).
- **Source:** sdp-area-05 §Fields (change risk: manual); architecture §2.4 (manual risk)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. An override without a reason is refused.
  2. Lists can show calculated and chosen risk side by side, and reports count overrides.

#### REQ-CHG-061 — AI risk prediction

AI predicts a change's risk of failure from the tenant's history: past outcomes of similar
changes, incidents linked to past changes on the same CIs, recent incidents and MonetX
problems on those CIs, and calendar conflicts. It shows a level, a confidence and the main
reasons. It advises; it never sets the risk without a person, unless the tenant allows it.

- **Decision:** BETTER. ServiceDesk Plus offers risk prediction in the Cloud only; ours uses
  incident and monitoring history and runs on every deployment.
- **Source:** sdp-area-10 §Screens (change risk prediction); architecture §2.10 (change risk), §12; product-plan §5 (risk scoring from incident and monitoring history), §7.2; D-049
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. On a trained tenant, a new change shows a predicted risk with at least three stated
     reasons.
  2. Accepting the prediction records the change with source "AI", accepted by the user.
  3. The same feature passes its tests with the on-prem local model profile.

---

## 9. Scheduling, downtime and the change calendar

#### REQ-CHG-062 — Change window

A change has a scheduled start and end (the change window), entered and shown in the user's
time zone (REQ-WI-014). The window is required before CAB review by default. A window that
spans a weekend or crosses a time-zone change is shown as such.

- **Decision:** SAME.
- **Source:** sdp-area-05 §Fields (scheduled start, end), §Screens (scheduler); D-035
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. An end before the start is refused.
  2. Under the defaults, entering CAB review without a window is refused and the prompt asks
     for it.
  3. Two users in different time zones see the same window in their own zones.

#### REQ-CHG-063 — Downtime schedule

A change can list planned downtimes: description, downtime type, start, end, and the services
and CIs affected. After the work, actual downtimes are recorded the same way. Admins keep the
list of downtime types.

- **Decision:** SAME.
- **Source:** sdp-area-05 §Actions (downtime schedule: description, type, start, end); sdp-area-13 §Helpdesk customization (downtime type); architecture §2.4 (planned and actual downtime)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A planned downtime outside the change window shows a warning.
  2. Planned and actual downtime per service are available to reports.

#### REQ-CHG-064 — Downtimes appear on the CIs

Planned and actual downtimes of a change create downtime records on the CIs and services they
affect (file 07, REQ-CMDB-020). The CI shows scheduled, active and completed downtimes with a link to the
change.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Screens (CI downtime counts, downtimes tab); architecture §2.12 (CI downtime records)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Adding a planned downtime for a CI adds a scheduled downtime on that CI, live.
  2. When the downtime starts, the CI counts it as active without a refresh.

#### REQ-CHG-065 — Change calendar views

The change calendar shows changes as bars from start to end in month, week, day and timeline
views. The timeline view has one row per service, CI or group. Bars use the type colour and
show stage, risk and approval state. Clicking a bar opens a quick view (REQ-INC-113).

- **Decision:** BETTER. Adds day and timeline-by-service views.
- **Source:** sdp-area-05 §Screens (change calendar: month and week); architecture §2.4 (change calendar week and month)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A change spanning three weeks shows as one continuous bar in month view.
  2. The timeline view by service shows two changes on the same service in the same row,
     overlapping visibly.
  3. The calendar works in right-to-left layout with time running right to left.

#### REQ-CHG-066 — Calendar filters and layers

The calendar filters by service, site, CI, type, risk, stage, approval state and group, and
can save filters as views. Layers can be switched on: releases (file 06), freeze windows,
maintenance windows and planned downtimes.

- **Decision:** BETTER. More filters, and all layers at once instead of a switch between
  changes and windows.
- **Source:** sdp-area-05 §Screens (showing dropdown, filter panel: services, sites, release schedule); architecture §2.5 (release calendar combined with the change calendar)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Filtering by one service shows only changes affecting it, and freeze windows that apply
     to it.
  2. Freeze windows and changes show together, with the freeze window drawn behind the bars.
  3. A saved calendar view can be shared like a list view (REQ-INC-107).

#### REQ-CHG-067 — The calendar updates live

New, moved, approved and canceled changes appear, move or disappear on every open calendar
within one second, with no refresh. A change the user may not see never appears.

- **Decision:** BETTER.
- **Source:** architecture §8; REQ-WI-005
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Rescheduling a change in one browser moves its bar in another open calendar within
     1 second.
  2. Approving a change updates its bar's approval marker live.
  3. A change outside the viewer's scope is never sent to their calendar.

#### REQ-CHG-068 — Reschedule by dragging

Users with permission can drag a change's bar to move or resize its window. Conflicts are
checked before the drop is saved; the user sees them and confirms or cancels. Approved changes
follow REQ-CHG-053.

- **Decision:** NEW.
- **Source:** architecture §9.4 (UX standards); sdp-area-05 §Screens (scheduler: configure change schedule dialog)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Dropping a change into a freeze window shows the conflict before anything is saved.
  2. A user without edit permission cannot drag the bar.
  3. A successful drop is recorded in history with source "calendar".

#### REQ-CHG-069 — Day agenda

Selecting a day on the calendar shows a side list of the changes active that day, with
approval state, risk and times, and filters for "approved only".

- **Decision:** SAME.
- **Source:** sdp-area-05 §Screens (approved changes side panel)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. The agenda lists every change whose window overlaps the selected day.
  2. The agenda updates live with the calendar.

#### REQ-CHG-070 — Scheduler on the record

From a change, the user opens a scheduler: a calendar centred on this change, showing other
changes on the same services and CIs, freeze and maintenance windows and conflicts. The user
sets the change window and the downtime there.

- **Decision:** SAME.
- **Source:** sdp-area-05 §Screens (change scheduler: include overlapping changes, freeze windows drawn)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. The scheduler shows by default only changes that share a service or CI with this change.
  2. Clicking a freeze window shows its name, scope, recurrence, next occurrence and
     conditions.

#### REQ-CHG-071 — Calendar subscription feed

A user can subscribe to a personal calendar feed (iCalendar) of the changes they may see,
filtered by a saved calendar view. The feed URL is secret, can be revoked, and holds only the
title, ID, window and a link.

- **Decision:** NEW.
- **Source:** architecture §2.14 (Microsoft 365 calendar)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. The feed lists only changes the user may see, and stops working after it is revoked.
  2. Feed entries contain no description, plans or requester details.

#### REQ-CHG-072 — Announce planned downtime

From a change, a technician can publish an announcement of planned downtime to the users of
the affected services (REQ-INC-129). The announcement takes its dates from the downtime and
follows the change: rescheduling offers to update it, cancelling offers to withdraw it.

- **Decision:** BETTER. The announcement stays in step with the change.
- **Source:** sdp-area-05 §Actions (notify: make an announcement); sdp-area-13 §Announcement and Maintenance (announcement types); REQ-INC-129
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. An announcement made from a change shows the downtime dates and a link to the change.
  2. Moving the downtime offers to update the announcement; accepting updates it in the portal
     live.

---

## 10. Conflict detection, freeze and maintenance windows

#### REQ-CHG-073 — What counts as a conflict

Conflict detection finds:

- another change on the same CI or service with an overlapping window;
- a window inside a freeze window that applies to the change;
- a window outside every maintenance window that applies (if the tenant requires them);
- a CI already in a planned downtime from another change;
- an implementer booked on two overlapping changes;
- an overlap with a release window on the same service.

Each conflict names the other change or window and the shared CI or service.

- **Decision:** BETTER. ServiceDesk Plus checks only change creation against freeze windows.
- **Source:** sdp-area-05 §Behaviour (scheduling into a freeze window gave no warning), §Weak spots; architecture §2.4 (conflict detection)
- **SDP weak spot fixed:** scheduling into a freeze window gives no warning.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Two changes on the same CI with overlapping windows each show a conflict naming the other.
  2. Two changes on unrelated CIs with overlapping windows show no conflict.
  3. Each conflict type in the list above has a test.

#### REQ-CHG-074 — Conflicts are checked on every change and shown

Conflicts are checked whenever the window, CIs, services, implementer or downtime of a change
changes, and when a freeze or maintenance window is added or edited. The results show on the
record and in the approval view, live. A "check now" action shows its result even when there
is none.

- **Decision:** BETTER.
- **Source:** sdp-area-05 §Actions (refresh schedule conflicts), §Behaviour (no visible output), §Weak spots
- **SDP weak spot fixed:** "refresh schedule conflicts" shows nothing, even when there is no
  conflict.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Adding a freeze window over an existing change's window adds a conflict to that change
     within 1 second.
  2. "Check now" with no conflicts says "no conflicts found" and the time of the check.
  3. A conflict that is resolved (one change moved) disappears from both changes live.

#### REQ-CHG-075 — Freeze windows

Admins define freeze windows with:

- name, description, active flag;
- scope: all changes, chosen services, or chosen sites, plus optional conditions on change
  fields (for example type is normal);
- what is frozen: creating changes, the change window, downtime, or several of them;
- schedule: from, to, all day, and recurrence (once, daily, weekly, monthly, yearly, with an
  end).

The list shows each window's next occurrence.

- **Decision:** SAME.
- **Source:** sdp-area-05 (5b) §5b-4 (freeze window form, seeded window); sdp-area-05 §Automation (freeze windows); architecture §2.4 (freeze windows recurring, scoped)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A weekly freeze on Saturdays shows the correct next occurrence in the tenant time zone.
  2. A freeze scoped to one service does not apply to a change on another service.
  3. A condition "type is normal" lets a standard change through.

#### REQ-CHG-076 — Freeze windows block or warn, with a controlled override

Each freeze window either blocks or warns. A block refuses the save on every path, with a
message naming the window. A user with the "override freeze window" permission can override a
block for one change with a reason; the override is shown on the change, recorded in history
and audited, and the CAB is told.

- **Decision:** BETTER.
- **Source:** sdp-area-05 (5b) §5b-4 (apply to); architecture §2.4; REQ-WI-021
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Scheduling into a blocking freeze window is refused through the UI, the calendar drag and
     the API.
  2. An override needs the permission and a reason, and shows an "overrides freeze" marker on
     the change.
  3. The override is in the audit log with the user, the window and the reason.

#### REQ-CHG-077 — Maintenance windows

Admins define maintenance windows the same way as freeze windows, with the same scope,
conditions and recurrence. A template or type can require changes to fall inside a
maintenance window; outside, a warning or block applies as configured.

- **Decision:** SAME.
- **Source:** sdp-area-05 (5b) §5b-4 (maintenance window form, seeded window); architecture §2.4
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. With "must fall in a maintenance window" on a type, a change of that type scheduled
     outside one gets a conflict.
  2. Maintenance windows show on the calendar as a layer (REQ-CHG-066).

#### REQ-CHG-078 — Suggest a free slot

The scheduler can suggest the next windows of a given length that are free of conflicts: inside
a maintenance window if required, outside freeze windows, with no other change on the same CIs
or services.

- **Decision:** NEW.
- **Source:** architecture §2.4 (scheduling, conflict detection)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Asking for a 2-hour slot returns up to three slots with no conflicts.
  2. Choosing a slot sets the window and re-runs conflict detection, which finds none.

---

## 11. Associations and impact analysis

#### REQ-CHG-079 — Links to other records

Changes link to incidents and service requests (initiated by, caused by), problems, releases,
projects, purchase orders and other changes, using the engine associations with one label pair
per relation (REQ-INC-087). The record shows a counter for each kind, live, and the other
record shows the same link with its own label and history. Pickers search everything the
user may see (REQ-INC-085).

- **Decision:** BETTER.
- **Source:** sdp-area-05 §Screens (associations counters), §Actions (planning associations); sdp-area-05 (5b) §5b-3 (request side has no history); sdp-area-06 §Weak spots (inconsistent link names); architecture §2.4 (associations)
- **SDP weak spot fixed:** the same link has a different name on each side, and only the change
  side records history.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Linking a request as "initiated the change" writes history on both records.
  2. Each relation shows the same label pair in every language on both sides.
  3. Linking a purchase order shows the change on the purchase order.

#### REQ-CHG-080 — CI and asset links show on both sides

A CI or asset involved in a change shows the change in its associations, with a counter for
open and total changes, like requests and problems.

- **Decision:** BETTER.
- **Source:** sdp-area-07 (7b) §7b.5 (no changes counter on the asset); sdp-area-07 §Screens (CI association counters)
- **SDP weak spot fixed:** an asset linked to a change shows no change counter.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Adding an asset to a change raises the asset's open changes counter by one, live.
  2. Closing the change moves it from open to total on the asset.

#### REQ-CHG-081 — Parent and child changes

A change can have child changes, for example one programme split into several changes. The
parent shows its children with their stage and status; children show their parent. The parent
cannot close while children are open (REQ-CHG-096).

- **Decision:** SAME.
- **Source:** sdp-area-05 §Actions (linked changes: parent and child); sdp-area-05 (5b) §5b-3 (parent and child badges)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Attaching a child shows a "parent" marker on one and "child" on the other, live.
  2. A change cannot be the child of its own child (no loops).

#### REQ-CHG-082 — Impact analysis from the CMDB

From a change, the user opens an impact view: starting from the change's CIs, it walks CMDB
relationships by depth and direction (file 07, REQ-CMDB-010) and shows the affected services, CIs, sites and
an estimate of affected users. The user can add affected services to the change in one step.
The impact summary is saved on the change when it enters CAB review.

- **Decision:** BETTER. ServiceDesk Plus has no impact analysis view; the relationship map
  must be read by hand.
- **Source:** sdp-area-07 §Behaviour (impact analysis: no dedicated view), §Weak spots; architecture §2.4 (CMDB impact view), §2.12 (impact analysis)
- **SDP weak spot fixed:** there is no dedicated impact-analysis view.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. For a change on a database CI that two applications depend on, the impact view lists both
     applications and the services above them.
  2. The depth and direction can be changed and the view updates.
  3. The saved summary on the change does not change when the CMDB changes later; a refresh
     action recomputes it.

#### REQ-CHG-083 — Incidents after a change are flagged

After a change's implementation, new incidents on its CIs or services within a set period
(Appendix A) are suggested to the change owner as possibly caused by the change. Accepting
links them; the change is then counted as having caused incidents.

- **Decision:** NEW.
- **Source:** product-plan §5 (change enablement), §7.3 (change risk reviewer, PIR writer); architecture §2.4 (associations)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. An incident on a changed CI 2 hours after implementation shows as a suggestion on the
     change.
  2. Accepting creates a "caused by" link on both records; rejecting hides the suggestion.
  3. Reports count changes that caused incidents.

#### REQ-CHG-084 — Recent changes on a CI or service

A CI, service, incident or problem shows the recent and upcoming changes on the same CIs and
services, so investigators can see what changed.

- **Decision:** NEW.
- **Source:** product-plan §5 (problem: RCA using change history); REQ-INC-143 (changes from the last 72 hours)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. An incident on a CI shows changes implemented on that CI in the last 72 hours.
  2. The list only shows changes the user may see.

---

## 12. MonetX health checks

All health data is **read** from the MonetX API through `monitoring_integrations`, read-only
(D-001, ADR-017). SupportX never polls devices and never stores metrics.

#### REQ-CHG-085 — Live health on the change

A change whose CIs are monitored by MonetX shows each CI's current health and open MonetX
problems on the record and in the impact view, with a link to open the CI in MonetX. It uses
the same read-only panel as incidents (REQ-INC-145).

- **Decision:** NEW.
- **Source:** D-001; ADR-017; product-plan §6 (topology-aware impact with live health); REQ-INC-145
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A change linked to a monitored CI shows its MonetX health, refreshed while the page is
     open.
  2. If MonetX cannot be reached, the panel says so and the rest of the change works.

#### REQ-CHG-086 — Pre-change and post-change health checks

Before the change window starts (at a set lead time) and after implementation completes (after
a set settle time), SupportX reads from MonetX the health state and open problems of the
change's CIs and the services above them, and stores the result on the change. The post-change
result is compared with the pre-change result, and any regression (a CI healthier before than
after, or a new problem) is flagged on the change and notified to the owner and implementer.

- **Decision:** NEW. ServiceDesk Plus offers nothing like this.
- **Source:** product-plan §5 (automatic pre/post change health checks via MonetX), §6 (pre/post change health check); D-001; ADR-017
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A pre-change check runs at the lead time and its result shows on the change with the time
     it was read.
  2. A CI that was healthy before and has a new MonetX problem after is flagged as a
     regression, and the owner is notified.
  3. A pre-change check that finds a CI already unhealthy warns the implementer before
     implementation starts.
  4. Health checks make only read calls to MonetX; a contract test proves no write call
     exists.

#### REQ-CHG-087 — No metric collection for health checks

SupportX does not collect, store or compare raw performance metrics for health checks. It
compares the health states and problems that MonetX reports. If MonetX later exposes a
read-only health summary per CI, the check may show it, but SupportX still does not poll or
store time series.

- **Decision:** SKIP. Metric collection is monitoring, which is MonetX's job (ADR-017, D-001).
  product-plan §6's "compare key metrics" is met by comparing MonetX's own health results.
- **Source:** ADR-017; D-001; product-plan §6 (pre/post change health check); REQ-INC-146
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. No SupportX table stores metric time series; an architecture test checks the
     monitoring_integrations module has only read-only clients.
  2. The health check record holds only health states, problem IDs and read times.

---

## 13. Tasks and implementation

#### REQ-CHG-088 — Change tasks per stage

Change tasks use the engine tasks (REQ-INC-072 to REQ-INC-076), with a stage added: each task
belongs to a stage, and the stage page shows its tasks. Implementation tasks have a schedule
inside the change window and an implementer. Dependencies are enforced (REQ-INC-075).

- **Decision:** SAME.
- **Source:** sdp-area-05 §Screens (tasks tab per stage), §Actions (add task, add task from template); sdp-area-05 (5b) §5b-1 (task nodes with completed and overdue exits); architecture §2.1 (tasks with dependencies)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A task added on the implementation page belongs to that stage and shows in its count.
  2. A task scheduled outside the change window shows a warning.
  3. An overdue implementation task is marked overdue on the change and in "my tasks".

#### REQ-CHG-089 — Implementation tasks on the calendar

Scheduled implementation tasks can be shown on the change calendar as sub-bars of their change,
and in the implementer's "my tasks" list.

- **Decision:** NEW.
- **Source:** architecture §2.4 (change calendar); REQ-INC-076
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Turning on the "tasks" layer shows each scheduled task under its change's bar.
  2. Completing a task updates its sub-bar live.

---

## 14. Review and closure

#### REQ-CHG-090 — Post-implementation review

The review stage holds a post-implementation review: whether the change met its goal,
the implementation outcome, incidents it caused, downtime planned versus actual, health check
results, lessons learned and follow-up actions. A review is required for failed, backed-out
and emergency changes, and optional for others by default. Follow-up actions can become
tasks, problems or new changes in one step.

- **Decision:** BETTER. ServiceDesk Plus review is a free text with a date.
- **Source:** sdp-area-05 §Screens (review stage: next review on, description); architecture §2.4 (post-implementation review)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Opening the review pre-fills outcome, linked incidents and downtime figures from the
     change.
  2. Closing a failed change without a completed review is refused.
  3. A follow-up action turned into a problem is linked to the change on both sides.

#### REQ-CHG-091 — Review date and reminder

A reviewer can set a "review on" date. The reviewer is reminded on that date, and changes due
for review appear in a built-in view.

- **Decision:** SAME.
- **Source:** sdp-area-05 §Screens (review stage: next review on)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. On the review date the reviewer gets a notification with a link to the change.
  2. The "due for review" view lists changes whose review date has passed, live.

#### REQ-CHG-092 — Change closure codes

Changes have their own closure code list (for example completed, completed with issues, backed
out, failed, rejected, canceled, deferred), separate from incident closure codes (REQ-INC-093).
The closure code is required to close by default.

- **Decision:** SAME.
- **Source:** sdp-area-05 (5b) §5b-4 (closure codes); sdp-area-05 §Screens (close stage: closure code); architecture §2.4 (closure codes)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Closing without a closure code is refused under default settings.
  2. A closure code can be disabled without affecting closed changes.

#### REQ-CHG-093 — Closure rules per stage: required fields

Admins set, for each stage, which fields must be filled before the stage can complete:
standard fields, plan sections and custom fields. The rules apply on every path. A blocked
user sees only what is missing.

- **Decision:** SAME.
- **Source:** sdp-area-14 §Screens (closure rules, change tab: mandatory-field grid per stage); REQ-INC-094
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. With "rollout plan required in planning", completing planning without one is refused and
     the prompt asks only for it.
  2. The API returns field errors with the same codes the UI shows.

#### REQ-CHG-094 — Closure rules per stage: tasks and approvals

For each stage, admins can require that the stage's tasks are complete and that all its
approvals are approved before it completes. Open work follows REQ-INC-095: by default open
tasks give a warning, pending approvals block.

- **Decision:** SAME.
- **Source:** sdp-area-14 §Screens (associated tasks completed, all stage approvals approved, per stage); REQ-INC-095
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. With "tasks complete" on for implementation, completing it with an open task is refused
     and the message names the task.
  2. A stage with a pending approval cannot complete under default settings.

#### REQ-CHG-095 — Closing a change: code, description and outcome

The closure stage asks for the closure code and a closing description, and shows a summary of
the change (outcome, review, downtime, linked records). Closing stamps the closed time and
makes the change read-only (REQ-CHG-097).

- **Decision:** SAME.
- **Source:** sdp-area-14 §Screens (close stage extras: closure code, close description); sdp-area-05 §Screens (close stage)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. The closing dialog shows only the missing required fields.
  2. The close summary shows the review result and the actual downtime.

#### REQ-CHG-096 — Closing waits for child changes and releases

By default a change cannot close while its child changes are open or its linked releases are
not complete. The message lists them. Admins can turn each condition into a warning.

- **Decision:** BETTER. Same conditions, on by default (ServiceDesk Plus has them off).
- **Source:** sdp-area-14 §Screens (associated releases completed, linked child changes completed)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Closing a parent with one open child is refused and the message names the child.
  2. With the condition set to warning, the close needs confirmation and history lists the open
     child.

#### REQ-CHG-097 — Closed changes are locked

A closed change is read-only except for notes and links, unless the user has "edit closed
changes" (REQ-INC-101). Worklogs on closed changes can be blocked by a tenant setting.

- **Decision:** SAME.
- **Source:** sdp-area-13 §Advanced Portal Settings (disable operations on a closed change; prevent worklog on closed records); REQ-INC-101
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Editing a field on a closed change without the permission is refused with 403.
  2. With the setting on, adding a worklog to a closed change is refused.

---

## 15. Lists, views and the record page

#### REQ-CHG-098 — Change list and built-in views

The change list uses the engine list (REQ-INC-104 to REQ-INC-121) with change columns: stage
and status, task progress, type with colour, template, risk, approval state, change window,
change owner and manager, conflict marker and overdue marker. Built-in views include:

- open changes, my open changes, open changes assigned to me, unassigned changes;
- waiting for my approval, approved and not yet implemented, my approved changes;
- scheduled this week, in implementation now, overdue, due for review;
- closed changes, changes from scheduled maintenance, emergency changes, trash.

Changes have their own entry in the main navigation and a working direct address.

- **Decision:** BETTER. Adds "waiting for my approval", "in implementation now" and conflict
  markers; changes are not hidden under a "more" menu.
- **Source:** sdp-area-05 §Screens (change list, 12 public views), §Weak spots (list URL not guessable, changes under "more"); sdp-area-01 §Screens (personal summary: changes approved, unapproved)
- **SDP weak spot fixed:** the change list lives under "more" and its address cannot be
  guessed.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. "Waiting for my approval" lists exactly the changes with a pending decision for the
     user, and a change leaves it live when they decide.
  2. Every built-in view exists in a new tenant.
  3. The list address can be bookmarked and opens the same view.

#### REQ-CHG-099 — Change board

The change list can show as a board with one column per stage. Moving a card runs the
transition to the next stage's first status, with the same checks and prompts as on the record
(REQ-INC-052).

- **Decision:** NEW. ServiceDesk Plus offers list and calendar for changes, but no board.
- **Source:** sdp-area-05 §Screens (three layout toggles); REQ-INC-111, REQ-INC-052
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Dropping a card onto a stage it cannot move to is refused with the reason.
  2. Cards move live when another user completes a stage.

#### REQ-CHG-100 — Change record page

The record page shows the stage rail, the current stage page, and a side panel with ID,
stage and status, type, template, owner, manager, approval state, risk, change window,
conflicts, health check result and association counters. Header actions keep their place
(REQ-WI-010): edit, assign, status, scheduler, life cycle view, notify, and the action menu
(notes, tasks, reminders, worklogs, copy, print, delete).

- **Decision:** BETTER. Fixed positions for actions and tabs.
- **Source:** sdp-area-05 §Screens (change detail page), §Actions (actions menu), §Weak spots (shifting menus and overflows)
- **SDP weak spot fixed:** the action menu, tab overflow and side panel shift, and are easy to
  mis-click.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. The header actions are in the same order on every change; unavailable ones are disabled
     with a reason.
  2. The side panel counters update live when a link is added elsewhere.
  3. The page works at phone width and in right-to-left layout.

#### REQ-CHG-101 — Bulk actions on changes

Bulk actions (REQ-INC-119 to REQ-INC-121) on changes are: assign, take, edit fields, add to a
CAB agenda, cancel, close and delete. Each change is checked against its own life cycle,
closure rules and freeze windows; the result lists the ones skipped and why.

- **Decision:** SAME.
- **Source:** sdp-area-05 §Actions (list toolbar: delete, pick up, close, assign)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Bulk close on ten changes, two with open children, closes eight and reports the two with
     reasons.
  2. Bulk actions never change stage or approval state outside the life cycle.

#### REQ-CHG-102 — Print a change pack

A change can be printed or saved as a PDF in two forms: the full record (REQ-INC-126), and a
CAB pack with the summary, risk, plans, schedule, conflicts, impact and approvals.

- **Decision:** BETTER. Adds the CAB pack.
- **Source:** sdp-area-05 §Actions (print); REQ-INC-126
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. The CAB pack PDF contains the risk score, the backout plan and the conflict list.
  2. The PDF uses labels and the user's language, including right-to-left for Arabic.

---

## 16. Notifications

#### REQ-CHG-103 — Notifications per stage and status

Admins choose, for each change status, which change roles and other recipients are notified
when a change enters it, through the notification engine (file 03). Recipients can be roles
(requester, owner, manager, implementer, reviewer, testing owner, CAB, line manager), groups or
named users.

- **Decision:** SAME.
- **Source:** sdp-area-05 §Config (stage and status: notify column), §Automation (status notifications); sdp-area-12 (12b) §Screens (notification rules, change tab)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Setting "notify CAB on awaiting CAB" notifies every current CAB member when a change
     enters it.
  2. A notification sent to a role reaches the current holders, not the holders at the time
     the rule was made.

#### REQ-CHG-104 — Default change notifications

A new tenant has change notifications on for the events in Appendix A, with templates in
English and Arabic (Urdu at V1, D-048). Delivery state shows on the change (REQ-INC-134).

- **Decision:** BETTER. Sensible defaults on day one.
- **Source:** sdp-area-12 (12b) §Screens (notification rules: some on, many off by default); REQ-INC-130; D-048
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. In a new tenant, submitting a change for CAB review notifies the CAB with no set-up.
  2. A notification that fails shows the reason on the change.

#### REQ-CHG-105 — Schedule reminders

The implementer and change owner are reminded before the change window starts (default 1 hour)
and when the window ends with implementation not complete. CAB members are reminded of
changes starting in the next 24 hours that are still waiting for them.

- **Decision:** NEW.
- **Source:** sdp-area-05 (5b) §5b-1 (seed workflow notifies a schedule by mail node); architecture §2.4
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. One hour before the window, the implementer gets a reminder with a link.
  2. A canceled change sends no reminders.

---

## 17. Automation and SLAs

#### REQ-CHG-106 — Change workflows with a visible run

Templates can bind a visual workflow (file 03) instead of a plain life cycle. Each change
shows its workflow run: the path taken, the current step, and any failed step with its error
and a retry action. A failed step never stalls the change silently: the owner is notified and
the change shows the failure.

- **Decision:** BETTER.
- **Source:** sdp-area-05 §Screens (workflow execution view); sdp-area-05 (5b) §5b-1 (failed mail node stalled the change silently); sdp-area-12 (12b) §Screens (execution view, log viewer); architecture §2.4 (automation), §6.7
- **SDP weak spot fixed:** a failed notification node stops the flow and only colours a button.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A failed workflow step shows on the change header and notifies the owner.
  2. The run view highlights the path taken and lists each step with time and result.
  3. Retrying a failed step continues the run from that step.

#### REQ-CHG-107 — Business rules, triggers and SLAs on changes

Business rules, triggers, timers, custom actions and webhooks (file 03) apply to changes,
including rules that abort a save with a message. Change SLAs set response and completion
targets with escalations (file 03); the change shows its due times as incidents do
(REQ-INC-012).

- **Decision:** SAME.
- **Source:** architecture §2.4 (automation, SLAs), §2.6; sdp-area-12 §Screens (triggers: change module; workflows: change module)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A business rule on changes that sets the group runs on creation and is recorded with its
     name.
  2. A change SLA escalation fires at its time and is recorded on the change.

#### REQ-CHG-108 — Scheduled recurring changes

Admins schedule recurring changes (for example monthly patching): a template, a recurrence and
a lead time. Each occurrence creates a change with its window set. Recurring standard changes
are pre-approved; others go through approval.

- **Decision:** SAME.
- **Source:** sdp-area-01 §Screens (new: maintenance for change); sdp-area-13 §Announcement and Maintenance (change maintenance prefix); sdp-area-11 §Fields (change maintenances permission); architecture §2.15 (preventive maintenance tasks); REQ-INC-034
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A monthly schedule with a 7-day lead time creates each change 7 days before its window.
  2. Each created change links back to its schedule, and the "from scheduled maintenance" view
     lists it.
  3. Pausing a schedule stops new occurrences without touching changes already created.

---

## 18. Requester side and mobile

#### REQ-CHG-109 — Requesters raise and follow changes in the portal

Requesters can raise changes from templates offered to them and follow their changes in the
portal: stage, status, schedule and public notes, never internal plans or private notes.
Requesters who are approvers or CAB members decide in the portal.

- **Decision:** SAME.
- **Source:** sdp-area-05 §Config (available for requesters); sdp-area-13 §Navigation & Footer Settings (requester view: changes); architecture §2.15 (my requests and approvals)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A requester sees their change's stage change in the portal live.
  2. The portal never shows the backout plan or private notes to a requester.
  3. A requester CAB member can approve from the portal.

#### REQ-CHG-110 — Changes and approvals on the mobile app

Technicians and approvers handle changes in the mobile app: lists, the record, stage
transitions, tasks, notes, and approval decisions with the approval view (REQ-CHG-046).

- **Decision:** SAME.
- **Source:** architecture §2.15 (approver apps), §9.1; REQ-INC-149
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A push notification for a pending approval opens the approval view in the app.
  2. Transitions in the app follow the same rules and prompts as the console.

---

## 19. AI on changes

AI on changes runs through the AI gateway with the user's permissions, as in file 01 section
20. Model access, pending a pricing decision (D-049): SaaS includes a fair-use allowance of
cloud model usage; Enterprise tenants may bring their own key; on-prem and air-gapped
installations use a local model.

#### REQ-CHG-111 — Draft plans and summaries

AI drafts a rollout, backout and test plan from the change description, CIs and similar past
changes, and writes a short CAB summary of the change. A person reviews and edits every draft
before it is saved.

- **Decision:** NEW.
- **Source:** product-plan §7.3 (change risk reviewer: drafts rollout/backout plans and CAB summary); architecture §2.10
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A draft is inserted only when the user accepts it, and is recorded with source "AI".
  2. The draft cites the past changes it drew on.

#### REQ-CHG-112 — Similar past changes

While a change is being planned, the record shows similar past changes with their outcomes,
so planners reuse what worked and avoid what failed.

- **Decision:** NEW.
- **Source:** product-plan §7.3 (change history); architecture §2.10
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A change on a CI with past failed changes lists them with their outcome.
  2. Only changes the user may see are listed.

#### REQ-CHG-113 — Change risk reviewer agent

An agent reviews submitted changes: it scores risk from history, affected CIs and calendar
conflicts, checks the plans are complete, and posts an advisory note for the CAB. It never
approves or rejects.

- **Decision:** NEW.
- **Source:** product-plan §7.3 (change risk reviewer: advisory to CAB); architecture §2.10 (agents)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. The agent's note shows as an internal note with source "AI agent".
  2. The agent has no approve or reject permission; an architecture test proves it.

---

## 20. DevOps and integrations

#### REQ-CHG-114 — Changes from deployment pipelines

A deployment pipeline can create or update a change through the API or a webhook: for example a
standard change from a catalogue model for each production deployment, with the build, commit
and environment recorded, and the outcome set when the pipeline finishes. A pipeline can ask
whether a change is approved and not frozen before deploying.

- **Decision:** NEW.
- **Source:** product-plan §5 (release: auto change records from deployments, pipeline hooks); architecture §2.5 (DevOps), §2.14 (DevOps)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A pipeline call with an idempotency key creates one standard change, even if retried.
  2. The "may I deploy" check returns "no" during a blocking freeze window, with the window's
     name.
  3. Pipeline calls use a scoped API token that can only touch changes.

#### REQ-CHG-115 — Links to DevOps work items

A change can link to issues and work items in Jira, Azure DevOps, GitLab and GitHub, and create
one from the change, through the connectors in file 12.

- **Decision:** SAME. GitHub is added.
- **Source:** architecture §2.5 (DevOps links and issue creation), §2.14
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A linked work item shows its key, title and state on the change.
  2. Creating a work item from a change links it on both sides.

---

## 21. Reports, data and import

#### REQ-CHG-116 — Change data for reports and dashboards

Change records give reports and dashboards (file 09) these measures, live: counts by stage,
type, risk, category, reason, group and owner; success rate; emergency and retrospective
share; changes that caused incidents; approval time per level; time per stage; planned versus
actual downtime; budget versus cost; freeze overrides. A change dashboard ships ready-made.

- **Decision:** BETTER. Adds outcome, approval and downtime measures that ServiceDesk Plus
  reports lack.
- **Source:** sdp-area-09 §Screens (change reports, canned change dashboard), §Weak spots (no drill-down for changes); architecture §2.8
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. The ready-made change dashboard shows success rate and emergency share in a new tenant.
  2. Every chart drills down to the list of changes behind it.
  3. A change closing updates the dashboard within 2 seconds.

#### REQ-CHG-117 — Change counters in the personal summary

Each user's personal counters (REQ-INC-128) include changes waiting for their approval,
their changes starting today, and their overdue changes.

- **Decision:** SAME.
- **Source:** sdp-area-09 §Screens (my summary: changes approved, unapproved); sdp-area-01 §Screens; REQ-INC-128
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Deciding an approval lowers the user's "waiting for my approval" counter live.

#### REQ-CHG-118 — Import changes

Admins can import changes from a file (with field mapping and a dry run), and the migration
tool imports changes with their stages, approvals and associations from ServiceDesk Plus.

- **Decision:** SAME.
- **Source:** sdp-area-11 §Fields (import wizard: changes, change maintenances); sdp-area-14 §Screens (import modules); architecture §18 (migration tool)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A dry run reports rows that would fail and why, without saving anything.
  2. Imported closed changes keep their original dates and closure codes.

---

## Appendix A — Proposed defaults

These are the defaults a new tenant gets, proposed for product owner approval. They are seed
data, not fixed behaviour: **a tenant admin can change every one of them** (D-041). The
requirements above refer to this appendix.

**Display ID prefix** (REQ-CHG-001): `CHG`.

**Change types** (REQ-CHG-005):

| Type | Model | Colour | Default template |
|---|---|---|---|
| Standard | standard | green | Standard change |
| Minor | normal | blue | Minor change |
| Normal | normal | teal | Normal change |
| Major | normal | orange | Major change |
| Emergency | emergency | red | Emergency change |

**Stages and statuses** (REQ-CHG-023, REQ-CHG-024). The completing status of each stage is in
bold.

| Stage | Statuses | Category of each status |
|---|---|---|
| Submission | submitted, more information needed, awaiting acceptance, **accepted**, rejected | open, paused, open, open, closed |
| Planning | planning, awaiting plan approval, **plan approved**, plan rejected | open, open, open, open |
| CAB review | awaiting CAB, clarification requested, **CAB approved**, CAB rejected | open, paused, open, closed |
| Implementation | scheduled, in progress, **implemented**, backed out, failed | open, open, open, open, open |
| Acceptance testing | testing, **tests passed**, tests failed | open, open, open |
| Deployment | deploying, **deployed**, deployment failed | open, open, open |
| Review | in review, **review complete** | open, open |
| Closure | **closed**, canceled | closed, canceled |

**Allowed transitions** (REQ-CHG-025, REQ-CHG-031):

| From | To |
|---|---|
| submitted | more information needed, awaiting acceptance, canceled |
| more information needed | submitted, canceled |
| awaiting acceptance | accepted (approval only), rejected (approval only) |
| rejected (submission) | closed |
| planning | awaiting plan approval, canceled |
| awaiting plan approval | plan approved (approval only), plan rejected (approval only) |
| plan rejected | planning (re-plan), canceled |
| awaiting CAB | clarification requested, CAB approved (approval only), CAB rejected (approval only) |
| clarification requested | awaiting CAB |
| CAB rejected | planning (re-plan), closed |
| scheduled | in progress, canceled |
| in progress | implemented, backed out, failed |
| backed out, failed, deployment failed | review stage (in review) |
| testing | tests passed, tests failed |
| tests failed | implementation (in progress) |
| deploying | deployed, deployment failed |
| in review | review complete |
| any status before implementation in progress | canceled (owner or change manager, reason required) |

**Stage paths per type** (REQ-CHG-027):

| Type | Stages |
|---|---|
| Standard | submission, implementation, review (optional), closure |
| Minor | submission, planning, implementation, review, closure |
| Normal | submission, planning, CAB review, implementation, review, closure |
| Major | all eight stages |
| Emergency | submission, CAB review (emergency CAB), implementation, review (mandatory), closure |

Acceptance testing and deployment are switched off in the normal template and can be switched
on per template.

**Approvals by default** (REQ-CHG-042, REQ-CHG-059):

| Where | Approvers | Rule |
|---|---|---|
| Submission (normal, major) | line manager | anyone |
| Planning, risk low or medium | change manager | anyone |
| CAB review, risk high | default CAB | majority |
| CAB review, risk very high | default CAB including the chair | majority including the chair |
| CAB review, emergency | emergency CAB | anyone |
| Review, emergency | default CAB | majority |

Comment required on rejection: on. Repeat approver auto-approved at a later level: off.
Approval reminder: after 2 business days without a decision, then daily for 3 business days.
Escalation to the change manager: after 5 business days.

**Default CABs** (REQ-CHG-040): "Change advisory board" and "Emergency change board", both with
no members; until members are added, a change needing them shows "CAB has no members" and the
change manager is notified.

**Risk levels** (REQ-CHG-056): low, medium, high, very high.

**Risk questionnaire** (REQ-CHG-057):

| Question | Answers (score) |
|---|---|
| Who is affected if it goes wrong? | one team (0), a department or site (2), the whole organisation or customers (4) |
| Has this change been done here before? | yes, often without problems (0), once or twice (1), never (3) |
| Is there a tested backout plan? | yes, tested (0), written but not tested (2), no (4) |
| Is a service outage expected? | no (0), yes, inside a maintenance window (1), yes, outside one (3) |
| Does it touch a critical service or a security control? | no (0), yes (3) |
| How many CIs are changed? | one (0), two to five (1), more than five (2) |

Score bands: 0 to 3 low, 4 to 7 medium, 8 to 11 high, 12 and above very high.

**Impact, urgency and priority** (REQ-CHG-010): the incident scales and matrix from file 01
Appendix A.

**Reasons for change** (REQ-CHG-011): security fix, vulnerability patch, new service or
feature, capacity or performance, compliance requirement, end of life or end of support,
fault fix, cost reduction.

**Downtime types** (REQ-CHG-063): full outage, partial outage, degraded performance,
no user impact.

**Closure codes** (REQ-CHG-092): completed, completed with issues, backed out, failed,
rejected, canceled, deferred.

**Freeze and maintenance windows** (REQ-CHG-075, REQ-CHG-077): none active. An inactive example
freeze window ("year-end freeze", all changes, warn) is seeded for admins to copy. Maintenance
windows are not required by any default type.

**Conflict detection** (REQ-CHG-073): all conflict types on, as warnings, except a blocking
freeze window, which blocks.

**Re-approval** (REQ-CHG-053): moving an approved window by more than 24 hours, or raising
risk, restarts approval of the affected stage; other edits after approval notify the
approvers.

**Closure rules** (REQ-CHG-093 to REQ-CHG-096): backout plan and change window required to
leave planning; tasks of a stage give a warning when open; pending approvals block; closure
code required to close; open child changes and incomplete linked releases block closing.

**Review** (REQ-CHG-090): required for failed, backed-out and emergency changes; optional for
others.

**Incidents after a change** (REQ-CHG-083): suggestion window 72 hours after implementation.

**Health checks** (REQ-CHG-086): pre-change read 30 minutes before the window; post-change
read 30 minutes after implementation completes.

**Notifications on by default** (REQ-CHG-104, REQ-CHG-105):

- submitted: to the change manager;
- approval needed: to the approvers of the level (including CAB members);
- approved or rejected: to the requester and change owner;
- clarification requested: to the change owner and requester;
- assigned: to the new change owner;
- 1 hour before the window: to the implementer and change owner;
- implementation overdue: to the change owner and change manager;
- implemented, failed or backed out: to the requester, change manager and reviewer;
- health check regression: to the change owner and implementer;
- closed: to the requester.

---

## Open questions for the product owner

1. **MVP scope.** Changes are Stage 2 (architecture §17), so this file has no MVP items, while
   product-plan §5 calls change core "P0, Phase 1". architecture.md wins (D-002). Does the
   design-partner customer (D-042) need a basic change record at MVP?
2. **Default types.** architecture §2.4 names standard, normal, emergency, major and minor.
   Appendix A seeds all five on three models. Keep all five, or seed only standard, normal and
   emergency?
3. **Emergency approval.** We require an emergency CAB decision before implementation, with a
   permission-based override (REQ-CHG-008, REQ-CHG-055). ServiceDesk Plus allows emergency
   changes with no approval. Confirm.
4. **Health check content.** product-plan §6 says "compare key metrics". Under D-001 we compare
   MonetX health states and problems only and store no metrics (REQ-CHG-086, REQ-CHG-087). Is
   that enough, or should the MonetX API offer a read-only health summary per CI to compare?
   This needs the MonetX API contract (ADR-017).
5. **Freeze window default.** No freeze window is active in a new tenant (ServiceDesk Plus seeds
   a weekend freeze). Confirm.
6. **CAB meetings** (REQ-CHG-054) are `LATER`. Are they needed for V1 tenders?
7. **Calendar feed** (REQ-CHG-071) exposes change titles and windows outside the product
   through a secret URL. Allow it, and if so, off by default per tenant?
8. **Editions.** Everything here is Professional. Should the standard change catalogue
   (REQ-CHG-007) or pipeline-created changes (REQ-CHG-114) be Enterprise?
