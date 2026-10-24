# 06 — Releases and projects

Parity requirements for release management (architecture.md §2.5) and for projects
(architecture.md §2.15). Rules, ID scheme and field meanings: [README.md](README.md).

**Status:** Draft v0.1, 2026-10-24. Not yet reviewed by the product owner. **Owner:** Haider
(Product Owner).

## Scope of this file

- **REQ-REL-*** are release requirements. A release is a work item type on the shared engine
  (architecture.md §6.1, §6.2; REQ-WI-001), built in `work_items`. Everything the engine and
  incidents already define applies to releases unchanged: history, live updates, actions,
  fixed tabs, notes, conversations, worklogs, tasks, checklists, attachments, reminders,
  approvals on the record, links, closure, lists, views, bulk actions, print, notifications,
  AI on records and mobile (file 01). This file lists only how releases differ or add to them.
- **REQ-PRJ-*** are project requirements. Projects are **not** a work item type. They live in
  their own `projects` module (architecture.md §6.1: projects, milestones, tasks, resources,
  timesheets). Where a project feature behaves like an engine feature (comments, worklogs,
  task fields, history, live updates), the requirement says so and cites the file 01 ID; the
  module still owns its own tables and talks to other modules only through their public
  service interfaces or events.
- **Not in this file** (each has its own module file, see the README):
  - Changes, the change calendar, freeze and maintenance windows and CAB (file 05, Changes).
    This file says how releases use the calendar and the windows.
  - Visual workflows, triggers, custom actions, timers, notification rules and templates
    (file 03). This file says which of them apply to releases and projects.
  - Assets, configuration items and services (file 07), reports and dashboards (file 09),
    AI administration (file 10), roles, users, import and export tooling (file 11), DevOps
    connectors and their set-up (file 12).
- **Monitoring is out of scope** (ADR-017, D-001). A release may show the health of its linked
  items, read from MonetX read-only (REQ-REL-062). SupportX never polls or correlates.
- **Stage and priority.** Releases are a Stage 2 module (architecture §17), so their parity
  items are `V1` and the "beyond SDP" items are `LATER`. Projects are Stage 3, so every
  project item is `LATER`. Releases are in the Professional edition (product-plan §9). The
  plan does not place projects in an edition; this file proposes Professional (open question
  1).

## Words used in this file

| Word | Meaning |
|---|---|
| Release | A work item of type `release`: a planned set of changes that is built, tested and deployed together. |
| Stage | A phase of a release (planning, build, testing ...). Each stage has its own statuses, dates, tasks and approvals. |
| Stage status | A status that belongs to one stage. Each stage status also has a status category (REQ-INC-044). |
| Release role | A named responsibility on a release (release manager, QA lead ...), filled by one user per release. |
| Release schedule on a change | The go-live window of a single change (file 05). It is not a release record. |
| Environment | A place a release is deployed to, for example test, staging or production. |
| Project | A planned piece of work with members, milestones and tasks, owned by the `projects` module. |
| Milestone | A stage of a project that groups tasks and has its own dates and owner. |
| Project task | A task inside a project, optionally inside one milestone. |
| Dependency | A rule that one task cannot start or finish until another has. |
| Capacity | The hours a person can work on a day, from their operational hours. |
| Load | The hours of planned work a person has on a day. |
| Time sheet | A view of logged time per person; a weekly timesheet is a person's time for one week, which can be submitted and approved. |
| Roll-up | A value on a project or milestone computed from its children (effort, cost, dates, percent complete). |

## Requirement summary

<!-- summary:start -->
**Counts by decision and priority**

| Decision | MVP | V1 | LATER | Total |
|---|---|---|---|---|
| SAME | 0 | 33 | 32 | 65 |
| BETTER | 0 | 20 | 16 | 36 |
| NEW | 0 | 1 | 9 | 10 |
| SKIP | 0 | 0 | 1 | 1 |
| **Total** | **0** | **54** | **58** | **112** |

Edition (lowest edition that includes it): Essentials 0, Professional 112, Enterprise 0. By prefix: REQ-REL 63, REQ-PRJ 49.

| ID | Title | Decision | Priority | Edition |
|---|---|---|---|---|
| [REQ-REL-001](#req-rel-001--releases-are-a-work-item-type) | Releases are a work item type | BETTER | V1 | Professional |
| [REQ-REL-002](#req-rel-002--release-record-and-core-fields) | Release record and core fields | SAME | V1 | Professional |
| [REQ-REL-003](#req-rel-003--release-types-of-their-own) | Release types of their own | BETTER | V1 | Professional |
| [REQ-REL-004](#req-rel-004--impact-urgency-priority-and-risk-on-clean-scales) | Impact, urgency, priority and risk on clean scales | BETTER | V1 | Professional |
| [REQ-REL-005](#req-rel-005--version-and-build-identifiers) | Version and build identifiers | NEW | V1 | Professional |
| [REQ-REL-006](#req-rel-006--custom-fields-on-releases-by-stage) | Custom fields on releases, by stage | SAME | V1 | Professional |
| [REQ-REL-007](#req-rel-007--create-a-release) | Create a release | BETTER | V1 | Professional |
| [REQ-REL-008](#req-rel-008--create-a-release-from-a-change-incident-or-problem) | Create a release from a change, incident or problem | SAME | V1 | Professional |
| [REQ-REL-009](#req-rel-009--copy-a-release) | Copy a release | SAME | V1 | Professional |
| [REQ-REL-010](#req-rel-010--import-releases) | Import releases | SAME | V1 | Professional |
| [REQ-REL-011](#req-rel-011--release-templates) | Release templates | SAME | V1 | Professional |
| [REQ-REL-012](#req-rel-012--emergency-releases) | Emergency releases | SAME | V1 | Professional |
| [REQ-REL-013](#req-rel-013--stage-sections-in-the-release-form-designer) | Stage sections in the release form designer | SAME | V1 | Professional |
| [REQ-REL-014](#req-rel-014--stages-each-with-its-own-statuses) | Stages, each with its own statuses | BETTER | V1 | Professional |
| [REQ-REL-015](#req-rel-015--admins-manage-stages-and-statuses) | Admins manage stages and statuses | SAME | V1 | Professional |
| [REQ-REL-016](#req-rel-016--stage-moves-only-through-allowed-transitions) | Stage moves only through allowed transitions | BETTER | V1 | Professional |
| [REQ-REL-017](#req-rel-017--going-back-a-stage-keeps-the-past) | Going back a stage keeps the past | BETTER | V1 | Professional |
| [REQ-REL-018](#req-rel-018--required-fields-per-stage) | Required fields per stage | SAME | V1 | Professional |
| [REQ-REL-019](#req-rel-019--stage-access-by-role) | Stage access by role | SAME | V1 | Professional |
| [REQ-REL-020](#req-rel-020--release-workflows-with-every-node-type) | Release workflows with every node type | BETTER | V1 | Professional |
| [REQ-REL-021](#req-rel-021--workflow-progress-shown-on-the-release) | Workflow progress shown on the release | SAME | V1 | Professional |
| [REQ-REL-022](#req-rel-022--triggers-timers-and-custom-actions-on-releases) | Triggers, timers and custom actions on releases | SAME | V1 | Professional |
| [REQ-REL-023](#req-rel-023--release-roles) | Release roles | SAME | V1 | Professional |
| [REQ-REL-024](#req-rel-024--who-may-hold-a-release-role) | Who may hold a release role | BETTER | V1 | Professional |
| [REQ-REL-025](#req-rel-025--release-plan-impact-rollout-backout-and-checklist) | Release plan: impact, rollout, backout and checklist | SAME | V1 | Professional |
| [REQ-REL-026](#req-rel-026--planned-and-actual-dates-for-each-stage) | Planned and actual dates for each stage | BETTER | V1 | Professional |
| [REQ-REL-027](#req-rel-027--planned-downtime) | Planned downtime | SAME | V1 | Professional |
| [REQ-REL-028](#req-rel-028--stage-outcomes-and-evidence) | Stage outcomes and evidence | SAME | V1 | Professional |
| [REQ-REL-029](#req-rel-029--deployment-environments) | Deployment environments | NEW | LATER | Professional |
| [REQ-REL-030](#req-rel-030--post-release-review) | Post-release review | BETTER | V1 | Professional |
| [REQ-REL-031](#req-rel-031--approvals-at-each-stage) | Approvals at each stage | BETTER | V1 | Professional |
| [REQ-REL-032](#req-rel-032--approval-reminders-and-backup-approvers) | Approval reminders and backup approvers | SAME | V1 | Professional |
| [REQ-REL-033](#req-rel-033--changes-in-a-release) | Changes in a release | BETTER | V1 | Professional |
| [REQ-REL-034](#req-rel-034--incidents-and-problems-linked-to-a-release) | Incidents and problems linked to a release | SAME | V1 | Professional |
| [REQ-REL-035](#req-rel-035--assets-configuration-items-and-services) | Assets, configuration items and services | SAME | V1 | Professional |
| [REQ-REL-036](#req-rel-036--projects-and-milestones-that-start-a-release) | Projects and milestones that start a release | SAME | LATER | Professional |
| [REQ-REL-037](#req-rel-037--parent-and-sub-releases) | Parent and sub-releases | SAME | V1 | Professional |
| [REQ-REL-038](#req-rel-038--release-calendar-combined-with-changes) | Release calendar combined with changes | BETTER | V1 | Professional |
| [REQ-REL-039](#req-rel-039--schedule-a-release-from-its-record) | Schedule a release from its record | SAME | V1 | Professional |
| [REQ-REL-040](#req-rel-040--freeze-and-maintenance-windows-guard-release-schedules) | Freeze and maintenance windows guard release schedules | SAME | V1 | Professional |
| [REQ-REL-041](#req-rel-041--conflict-detection-for-releases) | Conflict detection for releases | BETTER | V1 | Professional |
| [REQ-REL-042](#req-rel-042--link-devops-work-items) | Link DevOps work items | BETTER | V1 | Professional |
| [REQ-REL-043](#req-rel-043--pipeline-events-update-the-release) | Pipeline events update the release | NEW | LATER | Professional |
| [REQ-REL-044](#req-rel-044--deployment-gate-for-pipelines) | Deployment gate for pipelines | NEW | LATER | Professional |
| [REQ-REL-045](#req-rel-045--change-records-from-deployments) | Change records from deployments | NEW | LATER | Professional |
| [REQ-REL-046](#req-rel-046--release-notes-from-linked-work) | Release notes from linked work | NEW | LATER | Professional |
| [REQ-REL-047](#req-rel-047--engine-features-on-a-release) | Engine features on a release | SAME | V1 | Professional |
| [REQ-REL-048](#req-rel-048--tasks-by-stage) | Tasks by stage | BETTER | V1 | Professional |
| [REQ-REL-049](#req-rel-049--announce-a-release-and-send-notifications) | Announce a release and send notifications | SAME | V1 | Professional |
| [REQ-REL-050](#req-rel-050--release-closure-codes) | Release closure codes | SAME | V1 | Professional |
| [REQ-REL-051](#req-rel-051--release-closure-rules) | Release closure rules | SAME | V1 | Professional |
| [REQ-REL-052](#req-rel-052--closing-with-open-changes-tasks-or-sub-releases) | Closing with open changes, tasks or sub-releases | BETTER | V1 | Professional |
| [REQ-REL-053](#req-rel-053--failed-releases-and-rollback) | Failed releases and rollback | BETTER | V1 | Professional |
| [REQ-REL-054](#req-rel-054--cancel-and-reopen-a-release) | Cancel and reopen a release | SAME | V1 | Professional |
| [REQ-REL-055](#req-rel-055--release-list-and-built-in-views) | Release list and built-in views | SAME | V1 | Professional |
| [REQ-REL-056](#req-rel-056--release-board-by-stage) | Release board by stage | SAME | V1 | Professional |
| [REQ-REL-057](#req-rel-057--bulk-actions-on-releases) | Bulk actions on releases | SAME | V1 | Professional |
| [REQ-REL-058](#req-rel-058--release-record-page) | Release record page | BETTER | V1 | Professional |
| [REQ-REL-059](#req-rel-059--release-notifications-by-event-and-stage) | Release notifications by event and stage | SAME | V1 | Professional |
| [REQ-REL-060](#req-rel-060--release-reporting-hooks) | Release reporting hooks | SAME | V1 | Professional |
| [REQ-REL-061](#req-rel-061--release-engineer-and-risk-suggestions) | Release engineer and risk suggestions | SAME | LATER | Professional |
| [REQ-REL-062](#req-rel-062--health-of-release-items-before-and-after-deployment) | Health of release items before and after deployment | NEW | LATER | Professional |
| [REQ-REL-063](#req-rel-063--upcoming-releases-for-requesters) | Upcoming releases for requesters | SAME | LATER | Professional |
| [REQ-PRJ-001](#req-prj-001--projects-are-their-own-module) | Projects are their own module | SAME | LATER | Professional |
| [REQ-PRJ-002](#req-prj-002--project-record-and-core-fields) | Project record and core fields | SAME | LATER | Professional |
| [REQ-PRJ-003](#req-prj-003--project-types) | Project types | SAME | LATER | Professional |
| [REQ-PRJ-004](#req-prj-004--project-statuses-with-a-fixed-meaning) | Project statuses with a fixed meaning | BETTER | LATER | Professional |
| [REQ-PRJ-005](#req-prj-005--custom-fields-on-projects) | Custom fields on projects | SAME | LATER | Professional |
| [REQ-PRJ-006](#req-prj-006--create-a-project-reliably) | Create a project reliably | BETTER | LATER | Professional |
| [REQ-PRJ-007](#req-prj-007--copy-a-project) | Copy a project | SAME | LATER | Professional |
| [REQ-PRJ-008](#req-prj-008--import-projects-including-from-microsoft-project) | Import projects, including from Microsoft Project | SAME | LATER | Professional |
| [REQ-PRJ-009](#req-prj-009--project-templates) | Project templates | SAME | LATER | Professional |
| [REQ-PRJ-010](#req-prj-010--no-separate-add-on-page-for-projects) | No separate add-on page for projects | SKIP | LATER | Professional |
| [REQ-PRJ-011](#req-prj-011--project-members-and-project-roles) | Project members and project roles | SAME | LATER | Professional |
| [REQ-PRJ-012](#req-prj-012--project-roles-define-what-members-can-do) | Project roles define what members can do | BETTER | LATER | Professional |
| [REQ-PRJ-013](#req-prj-013--who-can-see-and-change-a-project) | Who can see and change a project | BETTER | LATER | Professional |
| [REQ-PRJ-014](#req-prj-014--admin-permissions-for-projects) | Admin permissions for projects | SAME | LATER | Professional |
| [REQ-PRJ-015](#req-prj-015--milestones) | Milestones | SAME | LATER | Professional |
| [REQ-PRJ-016](#req-prj-016--project-tasks) | Project tasks | SAME | LATER | Professional |
| [REQ-PRJ-017](#req-prj-017--one-milestone-per-task-shown-the-same-everywhere) | One milestone per task, shown the same everywhere | BETTER | LATER | Professional |
| [REQ-PRJ-018](#req-prj-018--quick-add-and-bulk-task-actions) | Quick add and bulk task actions | SAME | LATER | Professional |
| [REQ-PRJ-019](#req-prj-019--task-dependencies-with-types-and-lag) | Task dependencies with types and lag | BETTER | LATER | Professional |
| [REQ-PRJ-020](#req-prj-020--dependencies-are-enforced) | Dependencies are enforced | BETTER | LATER | Professional |
| [REQ-PRJ-021](#req-prj-021--dependency-diagram) | Dependency diagram | SAME | LATER | Professional |
| [REQ-PRJ-022](#req-prj-022--project-gantt-chart) | Project Gantt chart | SAME | LATER | Professional |
| [REQ-PRJ-023](#req-prj-023--plan-on-the-gantt-by-dragging) | Plan on the Gantt by dragging | BETTER | LATER | Professional |
| [REQ-PRJ-024](#req-prj-024--gantt-across-projects) | Gantt across projects | SAME | LATER | Professional |
| [REQ-PRJ-025](#req-prj-025--export-and-print-the-gantt) | Export and print the Gantt | SAME | LATER | Professional |
| [REQ-PRJ-026](#req-prj-026--task-board) | Task board | BETTER | LATER | Professional |
| [REQ-PRJ-027](#req-prj-027--resource-workload-view) | Resource workload view | BETTER | LATER | Professional |
| [REQ-PRJ-028](#req-prj-028--warning-on-over-allocation) | Warning on over-allocation | NEW | LATER | Professional |
| [REQ-PRJ-029](#req-prj-029--schedule-rules-strict-dates-auto-shift-and-roll-up) | Schedule rules: strict dates, auto-shift and roll-up | BETTER | LATER | Professional |
| [REQ-PRJ-030](#req-prj-030--baselines-and-critical-path) | Baselines and critical path | NEW | LATER | Professional |
| [REQ-PRJ-031](#req-prj-031--worklogs-on-project-tasks) | Worklogs on project tasks | SAME | LATER | Professional |
| [REQ-PRJ-032](#req-prj-032--project-time-sheet) | Project time sheet | SAME | LATER | Professional |
| [REQ-PRJ-033](#req-prj-033--weekly-timesheets-with-approval) | Weekly timesheets with approval | NEW | LATER | Professional |
| [REQ-PRJ-034](#req-prj-034--estimates-versus-actuals) | Estimates versus actuals | BETTER | LATER | Professional |
| [REQ-PRJ-035](#req-prj-035--project-budget-and-cost) | Project budget and cost | SAME | LATER | Professional |
| [REQ-PRJ-036](#req-prj-036--percent-complete-from-the-work) | Percent complete from the work | BETTER | LATER | Professional |
| [REQ-PRJ-037](#req-prj-037--link-projects-to-changes-releases-and-requests) | Link projects to changes, releases and requests | SAME | LATER | Professional |
| [REQ-PRJ-038](#req-prj-038--create-a-change-or-release-from-a-project) | Create a change or release from a project | SAME | LATER | Professional |
| [REQ-PRJ-039](#req-prj-039--closing-a-project-with-open-work) | Closing a project with open work | BETTER | LATER | Professional |
| [REQ-PRJ-040](#req-prj-040--completed-items-stay-as-they-are) | Completed items stay as they are | SAME | LATER | Professional |
| [REQ-PRJ-041](#req-prj-041--project-settings-with-tenant-defaults) | Project settings with tenant defaults | BETTER | LATER | Professional |
| [REQ-PRJ-042](#req-prj-042--project-list-and-views) | Project list and views | SAME | LATER | Professional |
| [REQ-PRJ-043](#req-prj-043--project-page-and-summary) | Project page and summary | BETTER | LATER | Professional |
| [REQ-PRJ-044](#req-prj-044--project-activity-feed-and-comments) | Project activity feed and comments | SAME | LATER | Professional |
| [REQ-PRJ-045](#req-prj-045--project-reporting-hooks) | Project reporting hooks | SAME | LATER | Professional |
| [REQ-PRJ-046](#req-prj-046--project-notifications) | Project notifications | SAME | LATER | Professional |
| [REQ-PRJ-047](#req-prj-047--triggers-and-automation-on-projects) | Triggers and automation on projects | SAME | LATER | Professional |
| [REQ-PRJ-048](#req-prj-048--projects-for-requesters) | Projects for requesters | SAME | LATER | Professional |
| [REQ-PRJ-049](#req-prj-049--projects-on-the-mobile-app) | Projects on the mobile app | SAME | LATER | Professional |
<!-- summary:end -->

---

## 1. The release record

#### REQ-REL-001 — Releases are a work item type

A release is a work item of type `release`. It inherits everything in file 01 that applies to
every type: the display ID, field history, live updates, actions decided by the server, fixed
tabs, permissions by action and scope, trash and restore, audit, keyboard shortcuts and
accessibility (REQ-WI-001 to REQ-WI-025). Releases have their own display-ID counter with an
editable prefix, `REL` by default (REQ-WI-002, D-045).

- **Decision:** BETTER. ServiceDesk Plus builds releases as a separate copy of changes, with a
  weaker workflow and lists borrowed from changes. One engine gives releases the same depth as
  every other type.
- **Source:** architecture §2.5, §6.1, §6.2; sdp-area-06 §Weak spots; sdp-area-13 §General Settings (release prefix); D-045
- **SDP weak spot fixed:** release workflows are much weaker than change workflows for no
  visible reason, and releases reuse change field lists.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. The shared engine contract test suite (REQ-WI-001 AC1) runs against the release type and
     passes.
  2. A new tenant's first release gets the ID `REL-1`; changing the prefix to `RL` makes the
     next one `RL-2`, and `REL-1` keeps its ID.
  3. A tenant without the release entitlement gets a 403 problem code from every release API
     and sees the module disabled with an upgrade hint (REQ-WI-025).

#### REQ-REL-002 — Release record and core fields

A release has:

- a title (required) and a rich-text description;
- a requester, site and group;
- the release manager and release engineer (REQ-REL-023);
- type, category, subcategory and item;
- impact, urgency, priority and risk (REQ-REL-004);
- an overall scheduled start and end, and actual start and end (REQ-REL-026);
- the services, assets and configuration items it touches (REQ-REL-035);
- attachments.

Only the title is required by default. Admins can make other fields required per stage
(REQ-REL-018).

- **Decision:** SAME.
- **Source:** sdp-area-06 §Fields (New Release); architecture §2.5 (release records)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A release created through the API with only a title is saved in the first stage and
     first status of its template.
  2. A release created with a scheduled end before its scheduled start is refused with a field
     error.
  3. Each core field change is recorded in history with old value, new value, actor and
     source (REQ-WI-003).

#### REQ-REL-003 — Release types of their own

Admins keep a list of release types, separate from change types. Each type has a name, colour,
description and translations, for example major, minor, emergency and maintenance (Appendix A).
A type can set the default template and a default risk. Types in use can be disabled but not
deleted.

- **Decision:** BETTER. ServiceDesk Plus reuses the change type list for releases, so release
  types cannot be tuned without changing changes too.
- **Source:** sdp-area-06 §Fields (Type: same list as change types), §Config (release type reuses change lists), §Weak spots; architecture §2.5 (release types)
- **SDP weak spot fixed:** releases reuse change lists.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Adding a release type does not add it to the change type list, and the other way round.
  2. A disabled release type is not offered on new releases; existing releases keep it and
     show its label.
  3. A type with a default template preselects that template on the create form.

#### REQ-REL-004 — Impact, urgency, priority and risk on clean scales

Releases use the same clean impact and urgency scales and the same priority matrix as
incidents (REQ-INC-008, REQ-INC-009), so priorities mean the same everywhere. Risk is a short
list (low, medium, high) set by hand or suggested by a risk assessment shared with changes
(file 05). No field on a release carries a change-only label.

- **Decision:** BETTER. In ServiceDesk Plus the release impact list mixes scope values with
  severity values, and a field on the release is labelled as a reason for a change.
- **Source:** sdp-area-06 §Fields (Impact, Risk, Reason for Change), §Weak spots; sdp-area-13 §Helpdesk customization (impact list); architecture §2.4 (risk)
- **SDP weak spot fixed:** mixed impact scales, and change-only labels on releases.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Setting impact "a department or site" and urgency "high" on a release gives P2 under the
     default matrix, as on an incident.
  2. Every release field label comes from the release label set; an automated label check finds
     no label containing the word "change" on the release form unless it refers to a linked
     change.
  3. A risk set by hand records who set it and why in history.

#### REQ-REL-005 — Version and build identifiers

A release can carry a version (free text such as `4.2.0`), a build or artefact reference, a
release reason (an admin-defined list, for example new features, fixes, security, compliance)
and release notes in rich text. Version and build are searchable and can be shown in lists.

- **Decision:** NEW. ServiceDesk Plus has no version field on a release, only a reused change
  reason list.
- **Source:** product-plan §5 (Release: pipeline-aware releases), §10 (release with DevOps hooks); sdp-area-06 §Fields (Reason for Change)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Searching for `4.2.0` finds the release with that version.
  2. Two open releases may not share the same version for the same service when the tenant
     setting "unique versions" is on; the second save is refused with a field error.
  3. Release notes are sanitised rich text (REQ-INC-064).

#### REQ-REL-006 — Custom fields on releases, by stage

Admins add custom fields to releases (all the types the metadata module offers) and place
them in a stage section of the form (REQ-REL-013). A custom field can be required when leaving
a chosen stage.

- **Decision:** SAME.
- **Source:** sdp-area-13 §Additional Fields (module list includes Release); sdp-area-06 §Fields (stage detail); architecture §6.6
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A custom field added to the testing stage section appears only in that stage's tab.
  2. A custom field required to leave testing blocks the move until it is filled, on every
     path (REQ-REL-018).
  3. Custom release fields can be used in list columns, filters and reports.

---

## 2. Creating releases and templates

#### REQ-REL-007 — Create a release

Technicians with permission create a release from the module, from the global "new" menu or by
keyboard shortcut. They pick a template first (the type's default is preselected), and the
form shows only the fields of the first stage. The workflow comes from the template; there is
no separate workflow picker on the form.

- **Decision:** BETTER. ServiceDesk Plus asks for a workflow and a template separately, which
  lets a user pair a template with the wrong workflow.
- **Source:** sdp-area-06 §Screens (New Release menu: Select Workflow, Select Template); sdp-area-01 §Actions (new release shortcut)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Opening the create form with the emergency template shows that template's fields and its
     workflow name, read-only.
  2. Saving twice quickly creates one release (REQ-WI-008).
  3. The new release appears in every open release list within one second (REQ-WI-005).

#### REQ-REL-008 — Create a release from a change, incident or problem

From a change, incident or problem, a user can create a release that is pre-filled from it
(title, description, category, services, assets and configuration items) and linked to it with
the right relation (REQ-REL-033, REQ-REL-034). From several selected changes in a list, a user
can create one release that contains them all.

- **Decision:** SAME.
- **Source:** architecture §2.5 (created from changes, incidents or problems); sdp-area-04 §Screens (new release from a problem); sdp-area-06 §Behaviour (release links on request and problem)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Creating a release from a change links them as "change in release", recorded in both
     histories.
  2. Creating a release from three selected changes links all three and copies the union of
     their configuration items.
  3. A user who may not create releases does not see the action, and the API refuses it with
     403.

#### REQ-REL-009 — Copy a release

A user copies a release into a new one. They choose what to copy: fields, plan sections, tasks,
checklists, roles and links. Stage progress, approvals, dates and worklogs are never copied.
The copy behaves as described for incidents (REQ-INC-033).

- **Decision:** SAME.
- **Source:** sdp-area-06 §Actions (Copy Release); REQ-INC-033
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A copy starts in the first stage and status, with no approvals and no actual dates.
  2. Choosing "copy tasks" copies each task with its owner and stage, status reset to open.

#### REQ-REL-010 — Import releases

Admins import releases from CSV or spreadsheet files with field mapping, including their
stage, status, roles, dates and links to existing changes by display ID. Import runs as a
background job with streamed progress and a row-by-row error report. The import tool itself is
in file 11.

- **Decision:** SAME.
- **Source:** architecture §2.5 (import releases), §6.8 (imports); sdp-area-14 §Screens (Import Data: releases)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Importing 500 releases shows live progress and ends with a count of created, updated and
     failed rows.
  2. A row that names an unknown change ID is reported with the row number and the reason,
     and the other rows still import.
  3. Imported releases record "import" as the source in their history.

#### REQ-REL-011 — Release templates

Admins keep release templates. A template sets:

- the form layout for each stage (REQ-REL-013);
- which stages the release goes through, and the workflow;
- default type, priority, group and roles;
- tasks per stage and checklists (REQ-INC-040);
- plan section headings and guidance text (REQ-INC-038).

A new tenant gets a standard release template and an emergency release template (Appendix A).
Templates can be copied, disabled and restricted to groups.

- **Decision:** SAME.
- **Source:** sdp-area-06 §Config (templates: General and Emergency); sdp-area-12 §Screens (template designers); architecture §2.5 (templates with layouts)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A release created from a template that skips the training stage never shows that stage.
  2. Tasks set on the template for the testing stage are created when the release enters
     testing, not before.
  3. A disabled template is not offered; releases already using it keep working.

#### REQ-REL-012 — Emergency releases

The emergency template runs a shorter path: it skips planning and training by default, uses a
small emergency approver group, and marks the release with an emergency flag that shows in
lists, on the calendar and in reports. Leaving out a stage is recorded on the release, and a
review is always required after an emergency release.

- **Decision:** SAME.
- **Source:** sdp-area-06 §Screens (Emergency Template, emergency icon on RL-2); sdp-area-05 (5b) §Behaviour (emergency change skips planning and CAB); architecture §2.5
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. An emergency release moves from submission straight to build with no planning stage.
  2. An emergency release cannot close until its review stage is completed.
  3. Lists and the release calendar show the emergency flag as a labelled badge.

#### REQ-REL-013 — Stage sections in the release form designer

The form designer (REQ-INC-036) has one section per stage for releases. Admins place standard
and custom fields in each stage section, set required, read-only and hidden per stage, and
preview the form stage by stage.

- **Decision:** SAME.
- **Source:** sdp-area-06 §Fields (stage detail); sdp-area-12 §Config (change template: stage list on the left); architecture §2.5 (templates with layouts)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A field marked read-only in the deployment stage cannot be changed through the UI or the
     API while the release is in deployment.
  2. The preview shows each stage's tab exactly as a technician will see it.

---

## 3. Stages, statuses and workflow

#### REQ-REL-014 — Stages, each with its own statuses

A release moves through ordered stages. Each stage has its own statuses, and each status has a
status category (REQ-INC-044), so reports and rules understand it. The default stages are
submission, planning, build, testing, acceptance testing, deployment, training, review and
closure (Appendix A). The record shows a stage rail with done, current, skipped and future
stages, and each stage's dates.

The stage model is the one changes use (file 05); it is built once in the engine (REQ-WI-026).

- **Decision:** BETTER. Same stage depth, plus status categories so a "failed" status means the
  same thing to every report and rule.
- **Source:** sdp-area-06 §Fields (stage detail), §Automation (stage statuses), §Config (Stage and Status); architecture §2.5 (stages and custom statuses with guided transitions)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Saving a stage status without a category is refused.
  2. The stage rail shows the current stage and status, and changes live when another user
     moves the release.
  3. A report grouped by stage and by status category counts each release once.

#### REQ-REL-015 — Admins manage stages and statuses

Admins add, rename, translate, reorder and disable release stages, and add statuses to a
stage. Each status can name roles to notify when it is reached (REQ-REL-059). A stage in use
cannot be deleted. Changes to stages are versioned like life cycles (REQ-INC-049), so open
releases keep the stage set they started with until an admin migrates them.

- **Decision:** SAME.
- **Source:** sdp-area-06 §Config (Stage and Status: new stage, reorder stages); sdp-area-05 §Config (stage statuses with notify lists)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Reordering two stages in a new version does not change open releases on the old version.
  2. Deleting a stage that releases use is refused, and the message gives the count.
  3. A status can be disabled; releases already in it stay and can leave it.

#### REQ-REL-016 — Stage moves only through allowed transitions

A release moves between stages and statuses only through the transitions its workflow allows,
on every path (record, board, bulk, API, rules, workflows, AI agents), as for incidents
(REQ-INC-046). Each move asks for a status comment when the transition requires one
(REQ-INC-047); by default it is required when a stage fails, is rejected or is skipped.

- **Decision:** BETTER. ServiceDesk Plus asks for a status comment on every change, and lets
  status be set by hand outside the workflow.
- **Source:** sdp-area-06 §Fields (Status Comment required); sdp-area-05 §Actions (status popup), §Weak spots; REQ-INC-046
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. The API refuses a move from submission to deployment when the workflow does not allow it,
     with a problem code.
  2. Moving testing to "failed" without a comment is refused under the default settings.
  3. The comment shows on the stage in the rail and in history.

#### REQ-REL-017 — Going back a stage keeps the past

When a later stage fails (for example testing fails), the workflow can send the release back to
an earlier stage (for example build). Going back keeps the earlier stage's dates, tasks,
approvals and comments as a past round; the stage starts a new round with fresh dates and
approvals. The rail shows how many rounds a stage has had.

- **Decision:** BETTER. ServiceDesk Plus offers a "back out" status but shows no history of
  repeated rounds.
- **Source:** sdp-area-06 §Automation (Development: Back Out; Testing: Failed); architecture §2.5 (guided transitions)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Sending a release from testing back to build creates build round 2; round 1's dates and
     tasks stay visible and read-only.
  2. Approvals given in round 1 do not count for round 2.
  3. Reports can count releases that needed more than one test round.

#### REQ-REL-018 — Required fields per stage

Admins set which fields must be filled before a release can leave each stage, and which
conditions must hold (stage tasks done, stage approvals given). The rules apply on every path.
A blocked user sees a short list of what is missing, as for transitions on incidents
(REQ-INC-048).

- **Decision:** SAME.
- **Source:** sdp-area-14 §Screens (Closure Rules: per-stage mandatory fields on changes; release tab exists); sdp-area-12 §Config (life cycle mandatory fields)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. With "rollout plan required to leave planning", the move is refused until the plan is
     filled, and the dialog asks for only that field.
  2. A bulk stage move reports each release it skipped and why.

#### REQ-REL-019 — Stage access by role

Admins can limit who may edit each stage and who may move a release out of it, by release
role, group or permission. For example, only the QA lead may complete testing. Users without
access see the stage read-only, with a reason on disabled actions (REQ-WI-010).

- **Decision:** SAME.
- **Source:** architecture §2.4 (restrict stage access by role), §2.5 (roles; stages with guided transitions); sdp-area-12 §Config (transition scope)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A technician who is not the QA lead sees "complete testing" disabled with a reason, and
     the API refuses it with 403.
  2. Changing the QA lead on the release gives the new holder the right at once, live.

#### REQ-REL-020 — Release workflows with every node type

Releases use the visual workflow designer and engine (file 03) with every node type that
changes have: status and stage, condition, switch, wait, approval, notification, field update,
task, checklist, timer, webhook, custom function and sub-workflow. A new tenant gets a default
release workflow for each seeded template (Appendix A).

- **Decision:** BETTER. In ServiceDesk Plus the release workflow is a linear chain of statuses
  with no decision, task, approval or notification nodes.
- **Source:** sdp-area-06 §Automation (release workflow is linear), §Weak spots; sdp-area-12 §Config (workflow node types); architecture §2.5 (release workflows), §6.7
- **SDP weak spot fixed:** the release workflow is far less capable than the change workflow.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A release workflow with an approval node waits at that node until the approval completes,
     then follows the approved or rejected branch.
  2. A condition node on release type sends an emergency release down a different path.
  3. The same workflow definition format and node set validate for changes and releases.

#### REQ-REL-021 — Workflow progress shown on the release

The release shows its workflow as a read-only diagram with the path taken, the current node,
any waiting node and why it waits, and any failed node with its error. A log lists each step
with time, actor and outcome. A failed step also shows on the record header (REQ-WI-009).

- **Decision:** SAME.
- **Source:** sdp-area-06 §Screens (workflow execution view); sdp-area-05 (5b) §Behaviour (failed node stalls silently); sdp-area-12 (12b) §Screens (execution view, log)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A failed notification node marks the release header with the failure and a retry action
     for permitted users.
  2. The diagram highlights the path taken and updates live as the release moves.

#### REQ-REL-022 — Triggers, timers and custom actions on releases

Business rules, triggers, timers, scheduled actions, custom actions and custom menu actions
(file 03) can apply to releases: on create, edit, stage change and status change, with
release fields in their conditions.

- **Decision:** SAME.
- **Source:** sdp-area-12 §Screens (Triggers module menu includes Release; Workflows include Release); architecture §2.5 (automation: timers, triggers, custom menu actions)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A trigger "release enters deployment" runs its webhook once per entry, and the run shows
     in the release history with the trigger's name (REQ-WI-004).
  2. A custom menu action limited to releases appears only on release records.

---

## 4. Roles

#### REQ-REL-023 — Release roles

A release has named roles, each filled by one user: requester, release manager, release
engineer, development lead, QA lead, acceptance (UAT) owner and reviewer by default
(Appendix A). Admins add, rename and translate roles. Roles are used as approvers, as
notification recipients, in stage access (REQ-REL-019) and as workflow task owners. A roles tab
on the record lists every role and its holder, and each can be changed there.

- **Decision:** SAME.
- **Source:** sdp-area-06 §Fields (role section), §Config (Release Role), §Screens (Roles in left menu); architecture §2.5 (roles)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Setting the QA lead on a release notifies that user and adds the release to their "my
     releases" view, live.
  2. An approval rule "QA lead approves testing" resolves to the current holder at the time
     the approval is raised.
  3. A role change is recorded in history with old and new holder.

#### REQ-REL-024 — Who may hold a release role

Admins decide, per role, which users may hold it: by permission, group or user. For example,
only users with the release manager permission can be set as release manager. Pickers show
only eligible users, and the API refuses others.

- **Decision:** BETTER. ServiceDesk Plus ties release manager eligibility to a fixed hidden
  role and does not say why a user is missing from the picker.
- **Source:** sdp-area-11 §Fields (SDReleaseManager prerequisite), §Weak spots (built-in roles not viewable)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A user without the release manager permission does not appear in the release manager
     picker, and the API refuses them with a field error naming the missing permission.
  2. Removing the permission from a user who holds the role on open releases lists those
     releases to the admin before saving.

---

## 5. Planning, build, test and deployment

#### REQ-REL-025 — Release plan: impact, rollout, backout and checklist

The planning stage has rich-text sections for impact details, the rollout (deployment) plan
and the backout plan, plus a plan checklist (REQ-INC-077). Each section keeps its own history,
and the template can provide headings and guidance for each.

- **Decision:** SAME.
- **Source:** sdp-area-06 §Fields (Planning stage sections); architecture §2.5 (release plans with checklists)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Editing the backout plan records a history entry for that section with the editor and the
     time.
  2. Two users editing different plan sections at once both keep their changes; editing the
     same section raises a conflict (REQ-WI-007).

#### REQ-REL-026 — Planned and actual dates for each stage

Each stage has a scheduled start and end and an actual start and end. Actual dates are set
automatically when a stage starts and ends, and can be corrected with a reason. The overall
release schedule is shown from the first and last stage dates, and the same dates are edited
in one place, whether from the stage, the scheduler or the calendar.

- **Decision:** BETTER. ServiceDesk Plus keeps per-stage dates, but its scheduler edits only one
  overall schedule, and per-stage dates must be edited elsewhere.
- **Source:** sdp-area-06 §Fields (stage schedule blocks), §Weak spots
- **SDP weak spot fixed:** the scheduler and the stage tabs edit different dates.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Entering the testing stage sets its actual start to that moment, in history with source
     "workflow".
  2. Changing the deployment stage's scheduled end in the scheduler shows the same value in the
     deployment stage tab, live.
  3. A list column "behind schedule" marks releases whose current stage's scheduled end has
     passed.

#### REQ-REL-027 — Planned downtime

A release records planned downtime windows: type, start, end, description and the services or
configuration items affected. When a change is linked to a release, the user can choose to copy
the change's downtime windows into the release. Actual downtime can be recorded after
deployment.

- **Decision:** SAME.
- **Source:** sdp-area-06 §Fields (Planning: Downtime tab), §Actions (associate and copy downtimes); sdp-area-13 §Helpdesk customization (downtime types)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Linking a change with two downtime windows and choosing "copy downtime" adds two windows to
     the release, each noting its source change.
  2. Downtime windows show on the release calendar and on the affected configuration items.

#### REQ-REL-028 — Stage outcomes and evidence

The build, testing, acceptance, deployment and training stages each record an outcome (for
example passed, failed, partly done), a description, issues found and evidence attachments.
Training records the audience and completion. The outcome of each stage is shown on the rail
and is reportable.

- **Decision:** SAME.
- **Source:** sdp-area-06 §Fields (stage Details blocks); architecture §2.5 (build, test and deployment stages, post-deployment training)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A testing outcome of "failed" requires an issues description under the default settings.
  2. A report can count releases by deployment outcome.

#### REQ-REL-029 — Deployment environments

Admins define environments (for example development, test, staging, production) in order. A
release lists its target environments and tracks a deployment per environment: planned time,
actual time, outcome and who deployed. A release cannot be marked deployed to production until
it is deployed to the environments before it, unless a permitted user overrides with a reason.

- **Decision:** NEW. ServiceDesk Plus has no environments on releases.
- **Source:** product-plan §5 (Release: environments, pipeline-aware releases)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Recording a production deployment before staging is refused, unless the override
     permission is used with a reason.
  2. Each environment's deployment status updates live on the release and on the calendar.
  3. Pipeline events can set a deployment's outcome (REQ-REL-043).

#### REQ-REL-030 — Post-release review

The review stage records the review date, findings, what went well and what did not, and an
overall result (successful, successful with issues, failed). Follow-up actions can become
tasks, problems or changes in one step, linked to the release. A reminder goes to the reviewer
on the review date.

- **Decision:** BETTER. ServiceDesk Plus has a review date and a description only.
- **Source:** sdp-area-06 §Fields (Review: next review on); architecture §2.5 (post-deployment review)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Turning a review action into a problem creates a linked problem pre-filled with the
     action text.
  2. The reviewer is notified on the review date if the review is not yet done.
  3. The review result is a reportable field.

---

## 6. Approvals

#### REQ-REL-031 — Approvals at each stage

Any stage can require approval before it completes. A stage approval uses the engine approvals
(REQ-INC-083): one or more levels, each with approvers (users, groups, release roles, a CAB
from file 05) and a rule (any one, all, majority). The stage shows who is pending and each
decision, live. Approvers act in the app, by email link, on mobile or in Teams (file 12); an
emailed approval link works once only and expires.

- **Decision:** BETTER. In ServiceDesk Plus release approvals cannot complete without a mail
  server, and the tab does not show who is pending.
- **Source:** sdp-area-06 §Fields (Approvals tab on each stage), §Weak spots; REQ-INC-083; REQ-SR-021 to REQ-SR-039 (shared approval engine); architecture §2.5
- **SDP weak spot fixed:** stage approvals are stuck when mail is not configured.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. With no mail configured, an approver approves the planning stage in the app and the
     release can move on.
  2. Using an emailed approval link a second time shows "already used" and changes nothing.
  3. A two-level approval raises level 2 only after level 1 is approved.
  4. The release requester cannot approve their own release when segregation of duties is on.

#### REQ-REL-032 — Approval reminders and backup approvers

Pending release approvals send reminders on a schedule (Appendix A). An approver can name a
backup for a period; the backup can act, and the decision records both names. An approver can
ask a clarification question, which pauses their decision without rejecting.

- **Decision:** SAME.
- **Source:** architecture §2.4 (reminders, backup approvers, clarification requests), §2.5 (approval reminders); sdp-area-13 §Advanced Portal Settings (approval reminder)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. An approval pending for 2 business days sends a reminder each business day, at most 3
     times, under the defaults.
  2. A backup's approval shows "approved by B on behalf of A" on the stage and in history.
  3. A clarification question notifies the release manager, and the answer appears on the
     approval.

---

## 7. Associations

#### REQ-REL-033 — Changes in a release

A release contains changes. A change can belong to at most one open release at a time. The
release lists its changes with ID, title, type, stage, status and schedule, live. Both records
record the link in history, under one label pair (REQ-INC-087). Adding a change can copy its
downtime (REQ-REL-027). The release shows when one of its changes is behind its own schedule.

- **Decision:** BETTER. Links are named the same on both sides and recorded on both.
- **Source:** sdp-area-06 §Behaviour (attach change to release), §Actions; sdp-area-05 §Screens (associated releases counter); architecture §2.5 (link releases to changes); REQ-INC-087
- **SDP weak spot fixed:** link names differ on each side, and one side keeps no history.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Linking a change to a release writes history on both and updates both counters live.
  2. Linking a change that is already in another open release is refused, naming that release.
  3. A user who cannot see a change sees that a linked change exists, but not its title.

#### REQ-REL-034 — Incidents and problems linked to a release

Incidents, service requests and problems link to a release in both directions: a record that
started the release, and records caused by the release. A user can create an incident or a
problem from a release, pre-filled and linked. The relation labels come from one label pair
per direction (REQ-INC-087).

- **Decision:** SAME.
- **Source:** sdp-area-06 §Behaviour (requests and problems caused by or initiating a release); sdp-area-04 §Screens (releases caused by problem); REQ-INC-087
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Linking an incident as "caused by release" shows "caused" on the release and "caused by"
     on the incident, with history on both.
  2. A report can count incidents caused by releases per release type.

#### REQ-REL-035 — Assets, configuration items and services

A release lists the services it affects and the assets and configuration items it touches. It
shows an impact view of the services that depend on those items, from the CMDB (file 07). The
items show the release on their own records.

- **Decision:** SAME.
- **Source:** sdp-area-06 §Fields (Services Affected, Assets Involved, CIs Involved); sdp-area-07 §Screens (CI association counters include releases); architecture §2.5 (link releases to assets and CIs)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Adding a configuration item to a release adds the release to that item's associations,
     live.
  2. The impact view lists every business service that depends on the linked items.

#### REQ-REL-036 — Projects and milestones that start a release

A release can be linked to the project or milestone that started it (REQ-PRJ-037). The project
shows the releases it started, and the milestone shows its releases.

- **Decision:** SAME.
- **Source:** sdp-area-06 §Behaviour (projects and milestones that initiated release)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Linking a release to a milestone shows it on the milestone and on its project, with
     history on both sides.
  2. Without the projects entitlement, the link section is shown disabled with an upgrade hint
     (REQ-WI-025).

#### REQ-REL-037 — Parent and sub-releases

A release can have sub-releases, for example one per component or region. The parent shows its
sub-releases with stage and status. The parent cannot enter deployment until every sub-release
has passed testing, unless a permitted user overrides with a reason. Loops are refused.

- **Decision:** SAME.
- **Source:** architecture §2.5 (parent and sub-releases)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Making a release the parent of its own parent is refused.
  2. Moving the parent to deployment while a sub-release is still in build is refused with a
     message naming it.
  3. Sub-release progress shows on the parent and updates live.

---

## 8. Calendar and scheduling

#### REQ-REL-038 — Release calendar combined with changes

A calendar shows releases by day, week, month and as a timeline, with each release as a bar
from start to end, coloured by type or stage. The same calendar can show changes, freeze
windows and maintenance windows (file 05), and can be filtered by service, site, type, group
and environment. It updates live.

- **Decision:** BETTER. ServiceDesk Plus has a release calendar per record and a change calendar
  that can show release schedules, but no single combined view with filters.
- **Source:** sdp-area-06 §Screens (release list calendar layout, scheduler); sdp-area-05 §Screens (change calendar shows release schedule, filters); architecture §2.5 (release calendar combined with the change calendar)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Turning on "show changes" draws changes and releases on one calendar with a legend.
  2. A release rescheduled by another user moves on every open calendar within one second.
  3. Clicking a bar opens a quick view of the release without leaving the calendar.

#### REQ-REL-039 — Schedule a release from its record

From the release, a scheduler opens a calendar centred on the release. It shows the release's
stages, its linked changes' schedules, freeze and maintenance windows and other releases on the
same services. The user sets the schedule there; the stage dates update (REQ-REL-026).

- **Decision:** SAME.
- **Source:** sdp-area-06 §Screens (Release Scheduler: show associated changes' schedules); sdp-area-05 §Screens (Change Scheduler)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Turning on "show linked changes" draws each linked change's window on the release
     scheduler.
  2. Saving a schedule from the scheduler updates the release's stage dates and history.

#### REQ-REL-040 — Freeze and maintenance windows guard release schedules

Freeze windows and maintenance windows (file 05) can apply to release schedules. Scheduling a
deployment inside a freeze window is warned or blocked, as the window says. Scheduling outside
every maintenance window that applies is warned. A permitted user can override with a reason.

- **Decision:** SAME.
- **Source:** sdp-area-05 (5b) §Config (freeze and maintenance windows apply to release schedule); sdp-area-06 §Automation (freeze and maintenance windows apply)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Scheduling a production deployment in a blocking freeze window is refused, naming the
     window, on every path.
  2. An override with a reason is allowed for users with the override permission and is
     recorded in history and the audit log.

#### REQ-REL-041 — Conflict detection for releases

The system flags conflicts on a release: another release or change on the same services or
configuration items at an overlapping time, a role holder booked on two deployments at once, or
a downtime that overlaps another. Conflicts show on the release and on the calendar, refresh
on their own when anything relevant changes, and can be acknowledged with a reason.

- **Decision:** BETTER. ServiceDesk Plus has conflict checks for changes only, with a manual
  refresh.
- **Source:** sdp-area-06 §Actions (no refresh-conflicts item on releases); sdp-area-05 §Actions (refresh schedule conflicts); architecture §2.4 (conflict detection)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Two releases scheduled at overlapping times on the same configuration item both show a
     conflict naming the other.
  2. Moving one of them out of the overlap clears the conflict on both, live, with no manual
     refresh.
  3. An acknowledged conflict stays visible as acknowledged, with who and why.

---

## 9. DevOps

#### REQ-REL-042 — Link DevOps work items

A release links to work items in Jira, Azure DevOps, GitLab and GitHub: issues, epics, merge or
pull requests and versions. A user can link an existing item by URL or search, or create a new
item from the release. Linked items show their title, state and assignee, read back from the
tool and refreshed. The connectors themselves are in file 12.

- **Decision:** BETTER. Same tools as ServiceDesk Plus, plus GitHub, and the state of linked
  items is shown on the release.
- **Source:** architecture §2.5 (DevOps: Jira, Azure DevOps, GitLab, GitHub added), §2.14 (DevOps); product-plan §5 (Release), Appendix (DevOps integrations)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Creating a Jira issue from a release links it, and the release shows the issue's key and
     state.
  2. When the issue's state changes in Jira, the release shows the new state without a page
     refresh.
  3. If the tool cannot be reached, the panel says so and the rest of the release works.

#### REQ-REL-043 — Pipeline events update the release

CI/CD pipelines (GitHub Actions, GitLab CI, Jenkins, Azure Pipelines, ArgoCD) send build and
deployment events to SupportX through a signed webhook. Events can record a build, set a
deployment's outcome per environment (REQ-REL-029), add the artefact version and move the
release to the matching stage when the workflow allows it. Each event is idempotent by its
event ID.

- **Decision:** NEW. ServiceDesk Plus has no pipeline-aware releases.
- **Source:** product-plan §5 (Release: pipeline-aware, GitHub/GitLab/Jenkins/ArgoCD hooks), Appendix (DevOps); architecture §2.14 (generic webhooks in)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A "deployed to staging, success" event marks the staging deployment successful and shows
     the pipeline run link.
  2. The same event delivered twice changes the release once.
  3. An event with a bad signature is refused and logged, and the release is unchanged.

#### REQ-REL-044 — Deployment gate for pipelines

A pipeline can ask SupportX whether a release may be deployed to an environment now. The answer
is "go" or "no-go" with reasons: approvals missing, inside a freeze window, open blocking
conflicts, earlier environments not done. The check is recorded on the release.

- **Decision:** NEW.
- **Source:** product-plan §5 (Release: pipeline-aware releases); architecture §2.4 (freeze windows, conflict detection)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A gate check for a release with a pending deployment approval returns "no-go" with the
     reason code "approval pending".
  2. A gate check during a blocking freeze window returns "no-go" naming the window.
  3. Each gate check appears in the release history with the pipeline and the answer.

#### REQ-REL-045 — Change records from deployments

When a pipeline deploys to an environment the tenant marks as controlled (for example
production) and no change covers it, SupportX can create a change automatically, linked to the
release, using a pre-approved standard change template (file 05). It records the pipeline run,
the version and the outcome. Admins choose per environment whether to create changes, require an
existing change, or do nothing.

- **Decision:** NEW.
- **Source:** product-plan §5 (Release: auto change records from deployments)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A production deployment event with "create changes" set creates one standard change
     linked to the release, with source "pipeline" in history.
  2. With "require an existing change", a gate check without a linked approved change returns
     "no-go".

#### REQ-REL-046 — Release notes from linked work

A user can generate release notes from the release's linked changes, incidents, problems and
DevOps items, grouped by kind (features, fixes, known issues). AI can draft the text (file 10);
a person edits and publishes it. Published notes can be shared as an announcement or a
knowledge article.

- **Decision:** NEW.
- **Source:** product-plan §5 (Release: pipeline-aware releases), §7 (AI assist); architecture §2.10
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Generated notes list every linked change and DevOps item once, grouped by kind.
  2. An AI draft is marked as a draft until a person publishes it, and shows which linked
     items it used.

---

## 10. Work on the release record

#### REQ-REL-047 — Engine features on a release

These engine features work on releases exactly as on incidents, and need no release-specific
build:

- conversations and replies (REQ-INC-057, REQ-INC-058), public and private notes
  (REQ-INC-061), mentions (REQ-INC-063);
- worklogs, costs and the timer (REQ-INC-067 to REQ-INC-070); a worklog can name a stage;
- checklists (REQ-INC-077), attachments (REQ-INC-079, REQ-INC-080), reminders
  (REQ-INC-082);
- followers (REQ-INC-056), print and PDF with stage sections (REQ-INC-126), recently viewed
  (REQ-INC-127);
- release approvals and records on the mobile app (REQ-INC-149).

Releases have no resolution field; closure uses closure codes (REQ-REL-050).

- **Decision:** SAME.
- **Source:** sdp-area-06 §Actions (Release Actions menu: note, reminder, task, worklog), §Screens (left menu); sdp-area-11 §Fields (worklog permissions include releases); sdp-area-13 §Advanced Portal Settings (worklog on closed releases); REQ-WI-001
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. The engine contract tests for notes, worklogs, checklists, attachments and reminders pass
     on the release type.
  2. A worklog on a release can be filtered by stage in the worklog tab and in reports.
  3. With "block worklogs on closed records" on, adding a worklog to a closed release is
     refused (REQ-INC-070).

#### REQ-REL-048 — Tasks by stage

Release tasks (REQ-INC-072 to REQ-INC-076) belong to a stage. Each stage tab lists its tasks,
and the release shows "done / total" overall and per stage. By default a stage cannot complete
while its tasks are open; admins can turn this into a warning. Task dependencies are enforced
(REQ-INC-075).

- **Decision:** BETTER. ServiceDesk Plus shows tasks per stage but does not stop a stage from
  completing with open tasks unless a closure rule is set up.
- **Source:** sdp-area-06 §Fields (stage tabs: Tasks), §Screens (task ring 0/15); sdp-area-14 §Screens (associated tasks completed per stage)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Completing the testing stage with one open testing task is refused under the default, and
     the message names the task.
  2. The per-stage task counter updates live when a task is closed.
  3. A task added from a template in the deployment stage is created in that stage.

#### REQ-REL-049 — Announce a release and send notifications

From a release, a user can publish an announcement (REQ-INC-129), for example planned downtime,
to chosen audiences in the portal and console. They can also send an ad-hoc notification to
chosen roles, groups or users. Both are recorded on the release.

- **Decision:** SAME.
- **Source:** sdp-area-06 §Actions (Notify: make an announcement, send notification); REQ-INC-129
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. An announcement made from a release links back to it and appears in the release history.
  2. An ad-hoc notification to "all release roles" reaches each role holder once.

---

## 11. Closure

#### REQ-REL-050 — Release closure codes

Admins define release closure codes (for example completed, completed with issues, rolled back,
deferred, rejected, canceled; Appendix A), with descriptions and translations. The closure stage
asks for a code and a closing comment.

- **Decision:** SAME.
- **Source:** sdp-area-06 §Config (Closure Code), §Fields (Closure stage); architecture §2.5 (closure codes)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Closing a release without a closure code is refused under the default settings.
  2. A disabled closure code is not offered and does not change old releases.

#### REQ-REL-051 — Release closure rules

Admins set the fields and conditions a release needs before it can close, as for incidents
(REQ-INC-094). Conditions can include: all stage approvals given, all tasks done, review
completed, all linked changes closed, all sub-releases closed. The rules apply on every path,
and a blocked user sees what is missing.

- **Decision:** SAME.
- **Source:** sdp-area-14 §Screens (Closure Rules: release tab, change close-stage extras such as associated releases completed); sdp-area-12 §Config (closure rules); REQ-INC-094
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. With "review completed" required, closing a release whose review is open is refused, and
     the message says so.
  2. A bulk close reports each release it skipped and why.

#### REQ-REL-052 — Closing with open changes, tasks or sub-releases

Before a release closes, open linked changes, open tasks, unfinished checklists, open
sub-releases and pending approvals are checked, as for incidents (REQ-INC-095). By default open
changes and sub-releases are listed with an offer to close the ones the user may close, open
tasks and checklists warn, and pending approvals block.

- **Decision:** BETTER.
- **Source:** REQ-INC-095; sdp-area-14 §Screens (close stage: associated releases completed, linked child changes completed); sdp-area-06 (6b) §Weak spots
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Closing a release with one open linked change shows a warning naming the change, and
     needs explicit confirmation.
  2. Closing with a pending stage approval is refused under the default settings.
  3. The confirmation is recorded in history with the open items listed.

#### REQ-REL-053 — Failed releases and rollback

When a deployment fails, the release records the failure, shows the backout plan, and lets the
release manager mark it rolled back. A failed or rolled-back release offers to create a linked
problem (file 04) and, if needed, a follow-up release. Failed and rolled-back releases are
reportable.

- **Decision:** BETTER. ServiceDesk Plus has failed statuses but no guided path after a failure.
- **Source:** sdp-area-06 §Automation (Deployment: Failed; Closure: Failed), §Screens (views: Failed)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Setting deployment to "failed" shows the backout plan and the "mark rolled back" action.
  2. "Create problem" from a failed release creates a problem linked as "caused by release".
  3. The built-in "failed" view lists the release within one second.

#### REQ-REL-054 — Cancel and reopen a release

A release can be canceled from any stage before closure, with a reason (REQ-INC-100). Its linked
changes are not canceled automatically; the user is offered to unlink them. A closed release can
be reopened by a permitted user with a reason, which returns it to its review stage and keeps
its past (REQ-INC-097).

- **Decision:** SAME.
- **Source:** sdp-area-06 §Screens (views: Canceled, Closed); REQ-INC-097, REQ-INC-100
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Canceling a release without a reason is refused.
  2. Reopening keeps the earlier closure code and dates in history and on the stage rail.

---

## 12. Lists, views and the record page

#### REQ-REL-055 — Release list and built-in views

The release list works like the incident list (REQ-INC-104 to REQ-INC-118): chosen columns,
custom views, filters, search, export and live updates. Release columns include stage, status,
type, priority, release manager, release engineer, version, scheduled end and task progress.
Built-in views (Appendix A) include all, open, mine (any role), unassigned, scheduled,
unscheduled, deployed, failed, canceled and closed.

- **Decision:** SAME.
- **Source:** sdp-area-06 §Screens (release list, views)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. "My releases" lists every release where the user holds any release role.
  2. "Unscheduled" lists open releases with no scheduled start.
  3. A release that changes stage moves between views live, with no refresh.

#### REQ-REL-056 — Release board by stage

A board view shows releases in columns by stage (or by status within one stage). Dragging a card
runs the transition, with any prompt, as for incidents (REQ-INC-052).

- **Decision:** SAME.
- **Source:** REQ-INC-111, REQ-INC-052; architecture §2.5 (stages with guided transitions)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Dropping a card on a stage the workflow does not allow does nothing and explains why.
  2. Other viewers see the card move live.

#### REQ-REL-057 — Bulk actions on releases

From the list, users select releases and assign them (group, manager, engineer), take them,
close them, move them to trash or edit fields, as for incidents (REQ-INC-119 to REQ-INC-121).
Each release is checked against its own rules, and the result lists the ones skipped and why.

- **Decision:** SAME.
- **Source:** sdp-area-06 §Actions (release list: Delete, Pickup, Close, Assign)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A bulk close of five releases, one with a pending approval, closes four and reports the
     fifth with the reason.
  2. "Take" sets the user as release engineer, or as release manager if the tenant says so
     (Appendix A).

#### REQ-REL-058 — Release record page

The release page shows the stage rail, one fixed tab strip per stage (details, plan or outcome,
tasks, approvals, comments), and fixed record tabs (roles, associations, conversations,
worklogs, history). Tabs never move into an overflow menu that changes by context
(REQ-WI-011). A side panel shows ID, stage, status, workflow, template, roles, schedule,
version and association counts. Inline edit can be switched off per tenant.

- **Decision:** BETTER.
- **Source:** sdp-area-06 §Screens (release detail), §Weak spots (overflow tabs move); sdp-area-13 §Advanced Portal Settings (release spot edit)
- **SDP weak spot fixed:** what sits in the "…" overflow changes with the selected tab.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. The tab order is the same in every stage; a tab with nothing to show is shown empty, not
     hidden.
  2. With inline edit off, fields change only through the edit form.
  3. Association counts in the side panel update live when a link is added elsewhere.

---

## 13. Notifications

#### REQ-REL-059 — Release notifications by event and stage

Release events notify the right people through the notification engine (file 03):

- created and assigned (release manager, release engineer);
- role set or changed (the new holder);
- a stage or status reached (the roles set on that status, REQ-REL-015);
- approval needed, approved, rejected, and reminders;
- schedule changed, conflict found, freeze window override;
- deployment succeeded or failed, rolled back;
- closed, canceled and reopened.

Each event can be switched on or off per tenant with chosen recipients and channels. Defaults
are in Appendix A. Templates ship in English and Arabic, and Urdu at V1 (D-048).

- **Decision:** SAME.
- **Source:** sdp-area-12 (12b) §Screens (Notification Rules: Release tab); sdp-area-05 §Config (notify per status); architecture §2.5 (notification rules)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. In a new tenant, a failed deployment notifies the release manager with no admin set-up.
  2. A status set to notify the QA lead notifies whoever holds that role at that moment.
  3. Nobody is notified of a change they made themselves, unless they opted in.

---

## 14. Reports, AI, monitoring and the requester side

#### REQ-REL-060 — Release reporting hooks

Release data is available to reports and dashboards (file 09): by stage, status category,
type, priority, risk, group, site, role holder, environment and closure code; on-time delivery
against the planned schedule; overdue stages; approval turnaround; failed and rolled-back
releases; test rounds. A release dashboard ships with the module.

- **Decision:** SAME.
- **Source:** sdp-area-09 §Screens (release reports, canned release dashboard); sdp-area-01 §Screens (dashboard list); architecture §2.5 (release dashboard)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. The release dashboard shows open releases by stage and updates live when a release moves.
  2. "On-time delivery" counts a release as on time when its deployment ended before the
     scheduled end of its deployment stage.

#### REQ-REL-061 — Release engineer and risk suggestions

AI suggests a release engineer and a risk level for a new release, from past releases (file 10).
Each suggestion shows why, the user accepts or changes it, and acceptance is measured. Model
access follows D-049.

- **Decision:** SAME.
- **Source:** sdp-area-10 §Screens (Release: engineer prediction and risk prediction); architecture §2.10; D-049
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A suggestion is shown as a suggestion and never saved without a user action.
  2. With AI switched off for the tenant, no suggestion is shown and no model call is made.

#### REQ-REL-062 — Health of release items before and after deployment

For linked configuration items that MonetX monitors, the release shows their current health,
read from MonetX read-only (D-001). Before and after a deployment window, it can record a health
snapshot of those items and flag items whose health got worse, as for changes (file 05).

- **Decision:** NEW.
- **Source:** D-001; ADR-017; product-plan §6 (pre/post change health check)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. After a deployment, an item that was healthy before and is now in problem is flagged on
     the release.
  2. If MonetX cannot be reached, the panel says so and the release works normally.
  3. SupportX makes no write call to MonetX and stores no performance data.

#### REQ-REL-063 — Upcoming releases for requesters

Admins can show requesters a portal page of upcoming and recent releases that affect the
services they use, with title, planned window, downtime and status as plain labels. Requesters
can also follow releases they requested. It is off by default.

- **Decision:** SAME.
- **Source:** sdp-area-13 §Navigation & Footer Settings (requester view includes Releases)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. With the page on, a requester sees only releases on services they are entitled to.
  2. A requester never sees internal fields, private notes or role holders' details.

---

## 15. The project record

#### REQ-PRJ-001 — Projects are their own module

Projects live in the `projects` module, not in the work item engine. A project still behaves
like the rest of the product: display IDs with an editable prefix (`PRJ` by default), field
history with source, live updates on every screen, fixed actions and tabs, labels and
right-to-left, trash and restore, and audit (the same rules as REQ-WI-002 to REQ-WI-023).
Project tasks show in every user's "my tasks" (REQ-INC-076).

- **Decision:** SAME.
- **Source:** architecture §6.1 (projects module), §2.15 (projects); sdp-area-13 §General Settings (project prefix); REQ-INC-076
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A new tenant's first project gets the ID `PRJ-1`.
  2. Changing a project's owner records old and new owner, actor and source in history.
  3. A project task assigned to a user appears in their "my tasks" list within one second.
  4. The import-linter contracts show no import from `projects` into the internals of
     `work_items` or the other way round.

#### REQ-PRJ-002 — Project record and core fields

A project has:

- a title (required), project code, description and attachments;
- type, status (required), priority, requester, owner, department and site;
- scheduled start and end, actual start and end, and projected end;
- estimated and actual hours, estimated and actual cost (REQ-PRJ-034, REQ-PRJ-035);
- percent complete (REQ-PRJ-036).

- **Decision:** SAME.
- **Source:** sdp-area-06 §Fields (New Project)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A project created with only a title gets the default status and the creator as project
     admin.
  2. A scheduled end before the scheduled start is refused with a field error.
  3. Two projects may not share a project code within a tenant.

#### REQ-PRJ-003 — Project types

Admins keep project types (for example business, infrastructure, maintenance, research,
upgrade; Appendix A), each with a colour, description and translations. Types can be
reordered and disabled.

- **Decision:** SAME.
- **Source:** sdp-area-06 §Config (Project Types)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A disabled type is not offered on new projects; existing projects keep it.
  2. Lists and the portfolio Gantt can colour projects by type.

#### REQ-PRJ-004 — Project statuses with a fixed meaning

Admins keep project statuses, each in a status category (not started, active, on hold,
completed, canceled), with allowed transitions between them (Appendix A). Putting a project on
hold or canceling it asks for a reason. Milestones and tasks have their own simple status lists
with the same categories.

- **Decision:** BETTER. ServiceDesk Plus project statuses have no fixed meaning, and status is a
  free choice on the edit form, so "closed" and "completed" overlap.
- **Source:** sdp-area-06 §Config (Project Status), §Screens (views: Completed, Closed), (6b) §Behaviour (reopen through Edit status)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Moving a project to on hold without a reason is refused.
  2. Only allowed transitions are offered, and the API refuses others with a problem code.
  3. Reports can group projects by status category.

#### REQ-PRJ-005 — Custom fields on projects

Admins add custom fields to projects, milestones and project tasks, with the same field types
as everywhere else (architecture §6.6), and place them on the forms.

- **Decision:** SAME.
- **Source:** sdp-area-13 §Additional Fields (module list includes Project); architecture §6.6
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A custom project field can be used as a list column, a filter and a report field.
  2. A required custom milestone field blocks saving a milestone without it.

#### REQ-PRJ-006 — Create a project reliably

Users with permission create a project from the module, from the global "new" menu or by
keyboard shortcut, choosing a template (REQ-PRJ-009). Switching template on the form reloads
the template's fields and keeps what was typed where the field exists in both (REQ-INC-039).

- **Decision:** BETTER. In ServiceDesk Plus choosing a template on the new project form left the
  form blank with a script error.
- **Source:** sdp-area-06 §Behaviour (new project form bug), §Weak spots; sdp-area-01 §Actions (new project shortcut)
- **SDP weak spot fixed:** picking a template renders a blank form.
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Switching between two templates on the create form always shows a complete form, and an
     end-to-end test covers it for every seeded template.
  2. A typed title survives a template switch.
  3. Saving twice quickly creates one project (REQ-WI-008).

#### REQ-PRJ-007 — Copy a project

A user copies a project into a new one, choosing what to copy: fields, members, milestones,
tasks, dependencies and settings. Dates can be shifted to a new start date, keeping the gaps
between items. Worklogs, comments and actual dates are never copied.

- **Decision:** SAME.
- **Source:** sdp-area-06 §Actions (Copy Project)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Copying a project with a new start date 30 days later moves every milestone and task by
     30 days.
  2. Copied dependencies link the copied tasks, never the originals.

#### REQ-PRJ-008 — Import projects, including from Microsoft Project

Admins import projects from CSV or spreadsheet files with their members, milestones, tasks and
comments, with field mapping. Users can also import a project plan exported from Microsoft
Project in its XML format, with tasks, hierarchy, dates, effort and dependencies. Imports run as
background jobs with a row-by-row error report (file 11).

- **Decision:** SAME.
- **Source:** sdp-area-06 §Actions (Import Project(s)); sdp-area-14 §Screens (Import Data: projects with members, comments, milestones); architecture §2.15 (MS Project import)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Importing a Microsoft Project XML file with 3 summary tasks and 20 tasks creates 3
     milestones and 20 tasks with their dependencies.
  2. An import row that names an unknown owner is reported and the task is created
     unassigned.
  3. The import shows live progress.

#### REQ-PRJ-009 — Project templates

Admins keep project templates with milestones, tasks (with dates relative to the project
start), dependencies, default members by role, settings (REQ-PRJ-041) and form layout. Users
can save any project as a template. A new tenant gets a default template and one sample
migration template (Appendix A).

- **Decision:** SAME.
- **Source:** sdp-area-06 §Actions (Copy as Project Template), §Config (templates); sdp-area-12 §Limits (project template editor not covered)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Creating a project from a template with a start date creates every milestone and task at
     its relative date.
  2. Saving a project as a template stores relative dates, not the original calendar dates.
  3. A disabled template is not offered.

#### REQ-PRJ-010 — No separate add-on page for projects

SupportX does not ship projects as a separate add-on with its own set-up page. Projects are a
module that the entitlement interface turns on, and its settings sit with the other module
settings.

- **Decision:** SKIP. ServiceDesk Plus lists projects under apps and add-ons with only a help
  page. Replaced by the module's entitlement (REQ-WI-017) and its admin settings
  (REQ-PRJ-014).
- **Source:** sdp-area-14 §Screens (Apps & Add-ons: Projects help page); product-plan §2 (projects a paid add-on below Enterprise)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A tenant whose edition includes projects sees the module with no extra activation step.
  2. Project settings are found by the admin settings search under "projects".

---

## 16. Members, roles and permissions

#### REQ-PRJ-011 — Project members and project roles

A project has members. Each member has a project role (project admin, project manager, team
leader, team member by default; Appendix A) and a member status (active or inactive). The
creator becomes project admin. Members can be added, removed and given a role from the members
tab, singly or in bulk. Each user can have a default project role used when they are added.

- **Decision:** SAME.
- **Source:** sdp-area-06 §Actions (Members tab), §Config (Project Roles); sdp-area-11 §Fields (Project Role on the technician form), §Actions (assign project role)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. The creator of a project is listed as project admin on save.
  2. A project must always have at least one active project admin; removing the last one is
     refused.
  3. An inactive member cannot be given new tasks, and keeps their past worklogs.

#### REQ-PRJ-012 — Project roles define what members can do

Each project role has a visible set of permissions inside a project: edit the project, manage
members, manage milestones, manage tasks, log time, see costs, close the project. A team leader
can be limited to the milestones they lead; a team member to their own tasks. Admins can add
roles and see exactly what each one grants.

- **Decision:** BETTER. ServiceDesk Plus describes project roles in one line each, and built-in
  roles cannot be opened to see what they grant.
- **Source:** sdp-area-06 §Config (Project Roles: full control, milestone control, assigned tasks); sdp-area-11 §Weak spots (built-in roles not viewable)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A team leader of milestone A can edit tasks in A and not in milestone B; the API refuses
     the edit in B with 403.
  2. A team member can update their own task's status and log time on it, but cannot edit
     another member's task.
  3. The role screen lists every permission of a built-in role, read-only.

#### REQ-PRJ-013 — Who can see and change a project

A project is visible to its members, to users with the "all projects" permission, and to others
only if the project is marked visible to a group, department or the whole tenant. The same
rules apply in lists, search, the Gantt, reports, realtime updates and AI answers (one policy
layer).

- **Decision:** BETTER.
- **Source:** architecture §11.2 (one policy layer); sdp-area-11 §Config (scope settings)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A non-member without "all projects" does not find a private project in search, lists or
     the portfolio Gantt.
  2. Removing a member stops their live updates for that project at once.
  3. A user who cannot see a project sees that a change is linked to "a project", but not its
     title.

#### REQ-PRJ-014 — Admin permissions for projects

Tenant roles include project permissions: create projects, see all projects, configure project
types, statuses, roles, templates, settings, notifications and automation, and see costs.

- **Decision:** SAME.
- **Source:** sdp-area-11 §Fields (ProjectConfig role)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A user without "configure projects" cannot open project settings, and the API refuses it
     with 403.
  2. A user without "see project costs" sees no cost or rate in any project screen, export or
     report.

---

## 17. Milestones and tasks

#### REQ-PRJ-015 — Milestones

A project has ordered milestones. A milestone has a title (required), description, owner,
priority, status, scheduled start and end, actual start and end, projected end, estimated and
actual hours and attachments. The project shows "done / total" milestones.

- **Decision:** SAME.
- **Source:** sdp-area-06 §Fields (Add Milestone), §Actions (Milestones tab), §Behaviour (milestone order)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Adding a milestone updates the project's milestone counter live.
  2. Reordering milestones is saved and seen by other users.
  3. Milestone dates use the shared date and time picker (REQ-WI-014), with time of day.

#### REQ-PRJ-016 — Project tasks

A project task has the fields of an engine task (REQ-INC-072, REQ-INC-073): title, description,
owner, status, priority, task type, scheduled and actual start and end, estimated effort,
percent complete, extra cost, a reminder before the scheduled start, and attachments. It also
has a milestone (optional) and its own comments, worklogs and history. Tasks can be added from
task templates (REQ-INC-074).

- **Decision:** SAME.
- **Source:** sdp-area-06 §Fields (Add Task), (6b) §Navigation path (task page tabs), §Behaviour (task form)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A task added from a template opens with the template's values and an empty title field
     to fill in, not the template's name.
  2. A reminder set to "1 hour before" notifies the owner one hour before the scheduled start.
  3. A task's scheduled end before its start is refused.

#### REQ-PRJ-017 — One milestone per task, shown the same everywhere

A task belongs to at most one milestone, held in one field. The task list, the task page, the
Gantt, the board and reports all show the same milestone. Moving tasks to another milestone (one
or many) keeps their dependencies unless the user chooses otherwise. A tenant setting can make
a milestone required on project tasks.

- **Decision:** BETTER. In ServiceDesk Plus the Gantt drew a task under a milestone that the task
  list said it did not belong to.
- **Source:** sdp-area-06 §Behaviour (task not assigned but drawn under milestone), §Weak spots, (6b) §Behaviour (assign milestone in bulk, preserve dependencies)
- **SDP weak spot fixed:** the Gantt and the task list disagree about a task's milestone.
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A task with no milestone is drawn directly under the project on the Gantt, and the task
     list shows no milestone.
  2. Moving three tasks to milestone B updates the list, Gantt and board for every viewer live.
  3. With "milestone required" on, saving a task without one is refused.

#### REQ-PRJ-018 — Quick add and bulk task actions

On the milestones and tasks tabs, users add items by typing a title in a row (quick add) and
fill the rest later. Selected tasks can be given an owner, a milestone, a status or a priority
in bulk, or moved to trash. Each change is checked per task and the result lists any skipped.

- **Decision:** SAME.
- **Source:** sdp-area-06 §Actions (Quick Add, Assign Owner, Assign Milestone)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Quick add creates a task with the typed title and the project's defaults.
  2. A bulk owner change to an inactive member is refused for each task with the reason.

#### REQ-PRJ-019 — Task dependencies with types and lag

A task can depend on other tasks in the same project: finish-to-start (default), start-to-start,
finish-to-finish or start-to-finish, with an optional lag or lead in working time. Dependencies
can be added from the task form, on the Gantt by drawing a link, and in the dependency diagram.
A loop is refused.

- **Decision:** BETTER. ServiceDesk Plus creates dependencies only in a diagram view, with
  finish-to-start only and no lag.
- **Source:** sdp-area-06 (6b) §Behaviour (dependency only in diagram, no link type or lag), §Weak spots
- **SDP weak spot fixed:** dependencies can only be created inside the diagram view.
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Adding a dependency from the task form shows it on the Gantt as an arrow, live.
  2. Creating A → B → C → A is refused with a message naming the loop.
  3. A finish-to-start link with 1 day lag requires the successor to start at least one working
     day after the predecessor ends.

#### REQ-PRJ-020 — Dependencies are enforced

Dependencies are never broken silently. By default:

- scheduling a successor before its predecessor allows is warned, and the arrow is drawn red
  until fixed;
- starting or completing a task whose predecessors are not done is blocked (REQ-INC-075);
- moving a predecessor later offers to shift its successors (REQ-PRJ-029).

Admins can turn the scheduling warning into a block per project.

- **Decision:** BETTER. In ServiceDesk Plus a successor could be dragged before its predecessor
  with no warning, no block and no visible sign.
- **Source:** sdp-area-06 (6b) §Behaviour (violation test), §Weak spots; REQ-INC-075
- **SDP weak spot fixed:** dependencies can be violated silently.
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Dragging a successor to start before its predecessor ends shows a warning naming the
     predecessor, and a red arrow if the user goes ahead.
  2. Starting a task whose predecessor is open is refused with a message naming it.
  3. With "block scheduling violations" on, the drag is refused and the bar returns to its
     place.

#### REQ-PRJ-021 — Dependency diagram

A project has a dependency diagram: tasks as nodes, dependencies as links, laid out across or
down. Users can add and remove links in it, and export it to PDF. It updates live.

- **Decision:** SAME.
- **Source:** sdp-area-06 (6b) §Behaviour (Task Dependency diagram: layouts, reload, PDF)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A link added in the diagram shows on the task form and the Gantt at once.
  2. The diagram is usable by keyboard and in right-to-left layout.

---

## 18. Gantt, board and resources

#### REQ-PRJ-022 — Project Gantt chart

Each project has a Gantt chart: a tree of project, milestones and tasks with start, duration,
owner and percent complete, and bars against a time scale from hours to years. Users choose
scheduled dates, actual dates or both, a date range, and whether non-working days are shaded or
skipped. Dependencies show as arrows; today shows as a line. Hovering a bar shows its details,
and items without dates are listed with a clear "no dates yet" marker and can be scheduled from
there.

- **Decision:** SAME.
- **Source:** sdp-area-06 §Screens (project Gantt), (6b) §Behaviour (Gantt toolbar, hover card, time settings)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Switching to "actual" draws bars from actual dates; items without actual dates show no
     bar and say so.
  2. A task changed by another user moves on the Gantt within one second.
  3. The Gantt works in right-to-left layout, with time running right to left.

#### REQ-PRJ-023 — Plan on the Gantt by dragging

Users with permission move and resize bars, draw dependencies, and give unscheduled items dates
by dragging them onto the time scale. A drag keeps the time of day unless snapping is on, shows
the new dates while dragging, and can be undone. Each change is saved with history and checked
against dependencies (REQ-PRJ-020) and schedule rules (REQ-PRJ-029).

- **Decision:** BETTER. In ServiceDesk Plus a new project's Gantt is empty until dates are typed
  in forms, and dragging a bar resets its times to whole days.
- **Source:** sdp-area-06 §Weak spots (no drag-to-schedule), (6b) §Behaviour (drag snaps to whole days, resets times)
- **SDP weak spot fixed:** dragging changes task length and time of day without asking.
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Dragging a task scheduled 09:00 to 13:00 one day later keeps 09:00 to 13:00 and its
     4-hour length.
  2. Dragging an unscheduled task onto a day gives it that day and its estimated effort as
     length.
  3. Undo restores the previous dates, and both changes are in history.

#### REQ-PRJ-024 — Gantt across projects

A portfolio Gantt shows many projects, filtered by project, type, status, owner, milestone and
date range. Each project row can be expanded to its milestones and tasks.

- **Decision:** SAME.
- **Source:** sdp-area-06 §Screens (global Gantt: select projects, milestones, tasks)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. The portfolio Gantt shows only projects the user may see (REQ-PRJ-013).
  2. Filtering by type "infrastructure" shows only those projects, with bars coloured by type.

#### REQ-PRJ-025 — Export and print the Gantt

Users export a Gantt (project or portfolio) to PDF or image, with the chosen date range, columns
and scale, and print it. Labels and dates follow the user's language and time zone.

- **Decision:** SAME.
- **Source:** sdp-area-06 §Screens (project Gantt: Export as PDF)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. An exported PDF of a 60-task project fits the chosen range and shows every task.
  2. An Arabic user's export is right-to-left with Arabic labels.

#### REQ-PRJ-026 — Task board

A project has a task board grouped by status, owner, priority or milestone, with a column for
unassigned tasks. Cards show title, owner, status, schedule state and markers for timer,
dependencies, comments and percent complete, in compact or comfortable density. Dragging a card
changes the grouped field, following the task's allowed status moves. The board is part of the
project page; closing it returns to the project page.

- **Decision:** BETTER. In ServiceDesk Plus the board's close button sits under another banner,
  and a missed click closes the whole project.
- **Source:** sdp-area-06 §Screens (Kanban view), §Weak spots (overlay close mis-click)
- **SDP weak spot fixed:** closing the board overlay can leave the project page by mistake.
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Dragging a card from "open" to "done" completes the task, unless its dependencies block
     it, in which case the card returns and the reason shows.
  2. Pressing Escape on the board returns to the project page, never elsewhere.
  3. Other viewers see the card move live.

#### REQ-PRJ-027 — Resource workload view

A workload view shows each member on a timeline (hours, days or weeks) with their load against
their capacity. Capacity comes from the member's operational hours, holidays and leave. Load
comes from each task's estimated effort spread over its scheduled working time; tasks without an
estimate use their scheduled time. Cells are shaded as a heatmap (under, full, over).
Filters cover members, projects, and unassigned or unscheduled tasks; bars can be coloured by
priority or project.

- **Decision:** BETTER. ServiceDesk Plus fixes capacity at 9 hours and counts a task's whole
  scheduled time as load, ignoring estimated effort and worklogs.
- **Source:** sdp-area-06 §Screens (Resource Management), (6b) §Behaviour (load from scheduled time, 9 h capacity), §Weak spots; architecture §2.15 (resource heatmap)
- **SDP weak spot fixed:** resource load ignores estimated effort.
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A task with a 4-hour estimate scheduled over one 8-hour working day shows a load of 4 of
     8 hours.
  2. A member on leave shows zero capacity that day, and any task load that day as over.
  3. Load updates live when a task is rescheduled or reassigned.

#### REQ-PRJ-028 — Warning on over-allocation

When a user assigns or schedules a task that takes a member over their capacity on any day, the
system warns and shows the days and hours over. The assignment can still go ahead.

- **Decision:** NEW.
- **Source:** architecture §2.15 (resource heatmap); sdp-area-06 (6b) §Behaviour (load shown only)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Assigning a 6-hour task to a member already at 4 of 8 hours that day warns "2 hours over"
     for that day.
  2. Confirming the warning is recorded in the task history.

#### REQ-PRJ-029 — Schedule rules: strict dates, auto-shift and roll-up

Each project can turn on:

- strict dates: milestones and tasks must fall inside the project's dates, and tasks inside
  their milestone's;
- auto-shift: moving a project, a milestone or a predecessor offers to move what depends on it,
  with a preview of every date that will change;
- date roll-up: the project's and milestones' scheduled dates follow their children.

- **Decision:** BETTER. Same rules, with a preview before shifting, and the project's own dates
  agree with its Gantt bar.
- **Source:** sdp-area-06 §Config (project settings: strict, auto-schedule), (6b) §Behaviour (project bar spans children while project dates stay unset), §Weak spots (limitations warnings)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. With strict dates on, saving a task that ends after its milestone's end is refused with a
     field error.
  2. Moving a milestone two days later with auto-shift shows a preview of every task that
     moves, and applies it only on confirm.
  3. With date roll-up on, the project's scheduled start and end equal its earliest and latest
     child dates.

#### REQ-PRJ-030 — Baselines and critical path

A project manager can save a baseline of the current plan and compare the live plan to it on
the Gantt (baseline bars, slip in days). The Gantt can highlight the critical path: the chain of
tasks that sets the project's end date.

- **Decision:** NEW. ServiceDesk Plus has neither.
- **Source:** architecture §2.15 (projects, Gantt); product-plan §5 (Projects: basic parity)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. After saving a baseline and moving a task 3 days later, the Gantt shows a 3-day slip on
     that task.
  2. The critical path highlights the tasks whose delay would move the project end date.

---

## 19. Time, effort and cost

#### REQ-PRJ-031 — Worklogs on project tasks

Members log time on project tasks with the same fields, validation, costs and timer as engine
worklogs (REQ-INC-067 to REQ-INC-070): owner, type, start and end or duration, description,
billable flag, technician and other charges in a currency. The task shows its total time and
cost.

- **Decision:** SAME.
- **Source:** sdp-area-06 (6b) §Behaviour (add worklog form, quirk), §Weak spots (worklog end picker rewrites time taken); REQ-INC-067
- **SDP weak spot fixed:** the end picker rewrites the time taken.
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A worklog with an end before its start is refused.
  2. A 1-hour worklog at 20 per hour plus 5 other charges shows 25 total on the task.
  3. Changing the end month in the picker changes only the end date, and the duration updates
     to match it visibly before saving.

#### REQ-PRJ-032 — Project time sheet

The project has a time sheet tab: per member, the time spent, technician charges, other charges
and total, expandable to each task and worklog, filterable by date range and milestone, and
exportable to PDF and spreadsheet.

- **Decision:** SAME.
- **Source:** sdp-area-06 §Actions (Time Sheet tab), (6b) §Behaviour (time sheet rows)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Adding a worklog updates the member's row and the totals live.
  2. A user without "see project costs" sees time but no charges.

#### REQ-PRJ-033 — Weekly timesheets with approval

Each user has a weekly timesheet: a grid of days against the projects, tasks and other work items
they logged time on. They can enter time in the grid (which creates worklogs), submit the week,
and their manager or project manager approves or returns it with a comment. Approved weeks are
locked against edits.

- **Decision:** NEW. ServiceDesk Plus shows time per project only, with no weekly view or
  approval.
- **Source:** architecture §2.15 (timesheets), §6.1 (projects: timesheets); product-plan §5 (Projects: timesheets)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Entering 2 hours on Tuesday for a task creates a 2-hour worklog on that task dated Tuesday.
  2. After approval, editing a worklog in that week is refused unless the week is returned.
  3. A returned week notifies the user with the approver's comment.

#### REQ-PRJ-034 — Estimates versus actuals

Projects and milestones show estimated hours, actual hours, estimated cost and actual cost, and
the variance between them. By default:

- estimated hours roll up from tasks;
- actual hours roll up from worklogs;
- actual cost rolls up from worklogs and task extra costs.

Roll-ups are kept up to date as work is logged, not only at closure. A manual figure can replace
a roll-up with a reason.

- **Decision:** BETTER. In ServiceDesk Plus roll-ups are off by default and the actual ones run
  only at closure, so a project shows no actuals while work is going on.
- **Source:** sdp-area-06 (6b) §Behaviour (roll-up stayed empty; settings needed), §Config (aggregate effort, calculate actual time, calculate actual cost on closure)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Logging 1 hour on a task makes the project's actual hours grow by 1 within one second.
  2. A project with 10 estimated and 12 actual hours shows a variance of +2 hours (+20%).
  3. A manual override is shown as such, with who set it and why.

#### REQ-PRJ-035 — Project budget and cost

A project has a budget in the tenant's currency, and cost from worklogs and extra costs in other
currencies is converted with the exchange rate of the day. The project shows budget, spent and
remaining, and warns the project manager when spending passes a chosen share of the budget.

- **Decision:** SAME.
- **Source:** sdp-area-06 §Fields (Estimated Cost / Actual Cost); sdp-area-14 §Screens (Currency, exchange rates); sdp-area-09 §Screens (projects: cost violated reports)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. With a budget of 1,000 and a warning at 80%, passing 800 spent notifies the project
     manager once.
  2. Costs logged in another currency show converted with the rate of the worklog's day.

#### REQ-PRJ-036 — Percent complete from the work

A project's and a milestone's percent complete are calculated from their tasks, by task count or
by estimated effort (project setting). Closing a project does not change its percent complete. A
manual value can replace the calculated one with a reason.

- **Decision:** BETTER. In ServiceDesk Plus closing a project with open tasks set it to 100%.
- **Source:** sdp-area-06 §Fields (% Completed editable and computed), (6b) §Behaviour (close jumps to 100%)
- **SDP weak spot fixed:** a closed project shows 100% complete with no task done.
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A project with 2 of 4 equal tasks done shows 50% by count.
  2. By effort, a done 6-hour task and an open 2-hour task give 75%.
  3. Closing a project with 0 of 2 tasks done keeps 0%.

---

## 20. Links

#### REQ-PRJ-037 — Link projects to changes, releases and requests

A project links to incidents and service requests, problems, changes (changes caused by the
project, the change that started the project) and releases (started by the project or by one of
its milestones). Links show on both sides with one label pair per direction and history on both
(REQ-INC-087). The project shows association counters.

- **Decision:** SAME.
- **Source:** sdp-area-06 §Behaviour (project association sections), §Weak spots (link names); sdp-area-05 §Screens (projects caused by change); product-plan §5 (Projects: links to changes); architecture §2.1, §2.4 (associations include projects)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Linking a change to a project as "caused by project" writes history on both records.
  2. The project's change counter updates live when the change side adds the link.
  3. Linking does not change the status of either record.

#### REQ-PRJ-038 — Create a change or release from a project

From a project or a milestone, a user creates a change or a release that is pre-filled (title,
description, requester, dates) and linked to it. Creating a change from a task links the change
to the task's project and shows it on the task.

- **Decision:** SAME.
- **Source:** sdp-area-06 §Behaviour (releases initiated by project or milestone); sdp-area-04 §Screens (new release from linked record)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Creating a release from milestone M links it as "started by milestone M" and shows it on
     the project.
  2. A user without permission to create changes does not see the action.

---

## 21. Closure and settings

#### REQ-PRJ-039 — Closing a project with open work

Before a project or milestone is completed or closed, open milestones and tasks are checked. By
default the user sees a list of the open items and can:

- close them together (they close through their normal rules and notifications); or
- cancel.

A project setting can block closure while children are open. Closing sets the actual end, and
reopening can clear it (setting).

- **Decision:** BETTER. In ServiceDesk Plus a project closes with open work by default, and
  closing children in one go skips their rules and notifications.
- **Source:** sdp-area-06 (6b) §Behaviour (closure tests: closes with open work, auto-close skips custom actions and notifications), §Weak spots; sdp-area-06 §Config (closure settings); REQ-INC-095
- **SDP weak spot fixed:** a project closes with open work and no warning.
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Closing a project with 2 open tasks shows both and needs a choice before it closes.
  2. "Close them together" closes each task through its normal transition, and each task
     owner is notified.
  3. With "block closure with open work" on, the close is refused and the API returns a
     problem code.

#### REQ-PRJ-040 — Completed items stay as they are

When a project, milestone or task is completed, it becomes read-only apart from status changes
and comments, if the project setting is on (default on). Reopening returns it to an active
status with a reason, and history keeps the earlier completion.

- **Decision:** SAME.
- **Source:** sdp-area-06 §Config (restrict operations on a completed entity, clear actual end on reopen), (6b) §Behaviour (reopen via edit status)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Editing the title of a completed task is refused with a reason, while adding a comment
     works.
  2. Reopening asks for a reason and records it.

#### REQ-PRJ-041 — Project settings with tenant defaults

The schedule, roll-up and closure switches (REQ-PRJ-020, REQ-PRJ-029, REQ-PRJ-034,
REQ-PRJ-036, REQ-PRJ-039, REQ-PRJ-040) have tenant
defaults set by an admin (Appendix A), which each project can change if its project admin is
allowed. Each switch has a short label and a one-line explanation of its effect. Changes are
saved explicitly, recorded in history and can be reverted.

- **Decision:** BETTER. In ServiceDesk Plus the switches exist only per project, carry long
  labels with "read the limitations" notes, and apply instantly with no undo.
- **Source:** sdp-area-06 §Config (project settings tab), §Weak spots, (6b) §Behaviour (settings save instantly), §Weak spots
- **SDP weak spot fixed:** settings only per project, no defaults, no undo.
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A new project takes the tenant defaults for every switch.
  2. Changing a switch on a project records old and new values in its history, and "revert"
     restores the previous value.
  3. A tenant admin can lock a switch so projects cannot change it.

---

## 22. Lists, pages and feeds

#### REQ-PRJ-042 — Project list and views

The project list has chosen columns (ID, title, status, priority, type, owner, created by,
milestone and task progress, project code, scheduled end, percent complete, budget used), list
and card layouts, search, custom views and filters, sharing of views, and export, as lists do
elsewhere (REQ-INC-104 to REQ-INC-110, REQ-INC-116). Built-in views (Appendix A) include all,
mine, open, active, on hold, completed, canceled and overdue. The list offers the portfolio
Gantt and the workload view as one click away.

- **Decision:** SAME.
- **Source:** sdp-area-06 §Screens (project list, views)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. "My projects" lists projects where the user is owner or a member.
  2. A project whose status changes moves between views live.
  3. Exporting the list respects the cost permission (REQ-PRJ-014).

#### REQ-PRJ-043 — Project page and summary

The project page has fixed tabs: summary, details, milestones, tasks, associations, time sheet,
members, comments, settings and history (REQ-WI-011); none of them move into an overflow that
changes with context. The summary shows charts of tasks and milestones by due state (on track,
due soon, overdue), by status and completed, plus budget and effort. A side panel shows ID,
status, priority, owner, due date, progress, counters and the viewer's own tasks (total, open,
done). Views (Gantt, board, workload, dependency diagram) are named buttons, not bare icons.

- **Decision:** BETTER.
- **Source:** sdp-area-06 §Screens (project detail), (6b) §Behaviour (Summary tab widgets, fourth icon), §Weak spots (overflow tabs)
- **SDP weak spot fixed:** tabs move into an overflow that depends on the selected tab; view
  icons are unlabelled.
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. The tab order is the same for every user and project; a tab without permission shows
     disabled with a reason.
  2. The summary charts update live when a task is completed.
  3. Each view button has a visible label and an accessible name.

#### REQ-PRJ-044 — Project activity feed and comments

A project has comments, with mentions (REQ-INC-063) and safe rich text (REQ-INC-064), on the
project, milestones and tasks. A feed shows recent activity across the project (new tasks,
status changes, comments, worklogs, members) and updates live. Users can filter the feed by
milestone or person.

- **Decision:** SAME.
- **Source:** sdp-area-06 §Screens (Project Feeds side tab, Comments), §Actions (Add Comment)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A comment mentioning a member notifies them and appears in the feed live.
  2. The feed shows only entries the viewer is allowed to see.

#### REQ-PRJ-045 — Project reporting hooks

Project data is available to reports and dashboards (file 09): by status, priority, type and
owner; estimated against actual hours and cost; budget overruns; overdue, due soon and delayed
projects, milestones and tasks; time spent per member; closed and canceled per period; projects
by linked requests. A project dashboard ships with the module.

- **Decision:** SAME.
- **Source:** sdp-area-09 §Screens (project reports, canned project dashboard); sdp-area-01 §Screens (dashboard list)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. The project dashboard shows overdue tasks and updates live when one is completed.
  2. Report results respect project visibility (REQ-PRJ-013) and the cost permission.

---

## 23. Notifications, automation and other channels

#### REQ-PRJ-046 — Project notifications

Project events notify the right people through the notification engine (file 03):

- added to or removed from a project, or given a new role;
- task or milestone assigned, due soon, overdue, and the reminder before scheduled start;
- a predecessor done (the successor's owner), a dependency broken;
- milestone completed, project status changed, budget warning;
- timesheet submitted, approved or returned.

Each event can be switched on or off per tenant with chosen recipients and channels; defaults
are in Appendix A.

- **Decision:** SAME.
- **Source:** sdp-area-12 (12b) §Screens (Notification Rules: Project tab, Task); sdp-area-06 §Automation (task notify before start)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Completing a predecessor notifies the successor's owner that their task can start.
  2. An overdue task notifies its owner once a day, at most, under the defaults.

#### REQ-PRJ-047 — Triggers and automation on projects

Triggers, timers, custom actions, custom functions and webhooks (file 03) can apply to
projects, milestones and project tasks: on create, edit, status change and date change, with
project fields in their conditions.

- **Decision:** SAME.
- **Source:** sdp-area-12 §Screens (Triggers module menu includes Project); sdp-area-11 §Fields (ProjectConfig: triggers, custom functions, webhooks)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A trigger "milestone completed" runs its webhook once, and the run shows in the project
     history.
  2. A failed automation step shows on the project (REQ-WI-009).

#### REQ-PRJ-048 — Projects for requesters

Requesters can follow projects they requested, or projects shared with them, in the portal: a
read-only view of status, milestones, dates and percent complete, with public comments. It is
off by default.

- **Decision:** SAME.
- **Source:** sdp-area-13 §Navigation & Footer Settings (requester view includes Projects)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A requester sees only projects they requested or that are shared with them.
  2. A requester never sees costs, worklogs, members' load or private comments.

#### REQ-PRJ-049 — Projects on the mobile app

Members see their project tasks in the mobile app's "my tasks", update status and percent
complete, log time with the timer, comment, and approve timesheets. The offline queue and push
notifications work as for incidents (REQ-INC-149).

- **Decision:** SAME.
- **Source:** architecture §2.15 (mobile apps), §9.1; REQ-INC-149
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Time logged offline is sent when the device reconnects, with no duplicate.
  2. A push for a new task assignment opens the task in the app.

---

## Appendix A — Proposed defaults

These are the defaults a new tenant would get. They are proposals for the product owner to
approve. As D-041 requires, they are seed data, not fixed behaviour: a tenant admin can change
every one of them. The requirements above refer to this appendix.

### Releases

**Display ID prefix** (REQ-REL-001): `REL`.

**Release types** (REQ-REL-003): major (new or changed service, high effect) · minor (small,
low effect) · maintenance (routine fixes and patches) · emergency (urgent fix, shortened path).

**Release reasons** (REQ-REL-005): new features · fixes · security · compliance ·
performance · technology refresh.

**Stages, statuses and categories** (REQ-REL-014). Categories as in REQ-INC-044.

| Stage | Statuses (category) |
|---|---|
| submission | requested (open) · accepted (open) · rejected (canceled) |
| planning | in planning (open) · waiting for approval (paused) · plan approved (open) · plan rejected (open) |
| build | in progress (open) · completed (open) · backed out (open) |
| testing | in progress (open) · passed (open) · failed (open) |
| acceptance testing | in progress (open) · accepted (open) · rejected (open) |
| deployment | scheduled (open) · in progress (open) · deployed (resolved) · failed (open) · rolled back (open) |
| training | in progress (open) · completed (resolved) |
| review | in progress (resolved) · completed (resolved) |
| closure | closed (closed) · canceled (canceled) |

**Allowed transitions** (REQ-REL-016, REQ-REL-017): each stage moves to the next when it reaches
its completing status (accepted, plan approved, completed, passed, accepted, deployed,
completed, completed). Backward moves: testing failed → build; acceptance rejected → build;
deployment failed → deployment rolled back → build or closure; plan rejected → planning (new
round). Any stage before closure → canceled (with reason). Closed → review (reopen, with
permission and reason).

**Reasons** required by default (REQ-REL-016): entering rejected, failed, rolled back, backed
out, canceled; skipping a stage; reopening.

**Templates** (REQ-REL-011, REQ-REL-012):

| Template | Stages | Approvals |
|---|---|---|
| standard release | all nine | planning: release manager; acceptance testing: acceptance owner; deployment: release manager |
| emergency release | submission, build, testing, deployment, review, closure | submission: emergency approver group (any one) |

**Release roles** (REQ-REL-023): requester · release manager · release engineer · development
lead · QA lead · acceptance owner · reviewer. Only users with the release manager permission can
be release manager (REQ-REL-024).

**Tasks by stage** (REQ-REL-048): a stage cannot complete with open tasks (block).

**Closing with open work** (REQ-REL-052): open linked changes and sub-releases are listed with
an offer to close them; open tasks and checklists warn; pending approvals block.

**Closure rules** (REQ-REL-051): closure code required; review completed required for emergency
releases.

**Closure codes** (REQ-REL-050): completed · completed with issues · rolled back · deferred ·
rejected · canceled.

**Approval reminders** (REQ-REL-032): first reminder after 2 business days without a decision,
then one per business day, at most 3.

**"Take" on a release** (REQ-REL-057): sets the user as release engineer.

**Built-in views** (REQ-REL-055): all · open · my releases (any role) · unassigned · scheduled ·
unscheduled · in deployment · deployed · failed · canceled · closed.

**Notifications on by default** (REQ-REL-059): release manager and engineer set; role set (to
the new holder); approval needed (to approvers); approved or rejected (to the release manager);
deployment succeeded or failed (to the release manager and requester); schedule changed (to all
role holders); freeze window override (to the release manager); closed and canceled (to the
requester and role holders).

**Requester release page** (REQ-REL-063): off.

**Unique versions per service** (REQ-REL-005): off.

### Projects

**Display ID prefix** (REQ-PRJ-001): `PRJ`.

**Project types** (REQ-PRJ-003): business · infrastructure · maintenance · research · upgrade.

**Project statuses** (REQ-PRJ-004):

| Status | Category | Reason needed to enter |
|---|---|---|
| planned | not started | no |
| active | active | no |
| on hold | on hold | yes |
| completed | completed | no |
| canceled | canceled | yes |

Allowed transitions: planned → active, canceled; active → on hold, completed, canceled; on hold →
active, canceled; completed → active (reopen, with reason); canceled → planned (undo, with
permission).

**Milestone and task statuses:** open (not started) · in progress (active) · on hold (on hold) ·
done (completed) · canceled (canceled).

**Project roles** (REQ-PRJ-011, REQ-PRJ-012):

| Role | Can do |
|---|---|
| project admin | everything in the project, including members, settings and closing |
| project manager | edit the project, milestones, tasks and members; see costs; approve timesheets |
| team leader | manage the tasks of the milestones they lead; log time |
| team member | update their own tasks; log time; comment |

**Templates** (REQ-PRJ-009): a default template (no milestones) and a sample "migration" template
with milestones for assessment, planning, pilot, migration and closure.

**Project settings** (REQ-PRJ-041):

| Setting | Default |
|---|---|
| strict dates | off |
| auto-shift dependents | offer with preview |
| date roll-up from children | on |
| scheduling a successor too early | warn |
| estimated effort roll-up | on |
| actual time and cost roll-up | on, kept up to date |
| percent complete | by task count |
| closing with open children | list and offer to close together |
| completed items read-only | on |
| clear actual end on reopen | on |
| milestone required on tasks | off |

**Capacity** (REQ-PRJ-027): the member's operational hours; 8 hours per working day where no
calendar is set.

**Budget warning** (REQ-PRJ-035): at 80% of budget.

**Built-in views** (REQ-PRJ-042): all · my projects · open · active · on hold · completed ·
canceled · overdue.

**Notifications on by default** (REQ-PRJ-046): added to a project; task assigned; task due in 1
day; task overdue (once a day); predecessor done (to the successor's owner); milestone completed
(to the project manager); budget warning (to the project manager); timesheet returned.

**Requester project view** (REQ-PRJ-048): off.

---

## Open questions for the product owner

1. **Projects edition.** product-plan §9 does not place projects in an edition, and ServiceDesk
   Plus sells them only in its top edition. Proposal: **Professional**, with the other practices,
   following the rule of no paid add-ons for core practices (product-plan §9.1). The
   alternative is Enterprise.
2. **Stages as an engine feature.** Changes and releases both need stages (a group of statuses
   with its own dates, tasks, approvals and form section). File 01 has no engine requirement
   for stages. Proposal: stages are built once in the engine, and a new REQ-WI requirement is
   added to file 01; this file and file 05 then reference it.
3. **Pipeline-aware releases.** product-plan §5 asks for environments, pipeline hooks
   (GitHub, GitLab, Jenkins, ArgoCD), deployment gates and change records from deployments.
   architecture §17 places release in Stage 2. Proposal: parity release items (including
   Jira, Azure DevOps, GitLab and GitHub links) are V1; environments, pipeline events, gates,
   automatic change records and release notes generation are LATER (REQ-REL-029, REQ-REL-043 to
   REQ-REL-046).
4. **Timesheets scope.** Should the weekly timesheet with approval (REQ-PRJ-033) cover time on
   all work items, as proposed, and does it belong to the `projects` module or to `work_items`?
   Proposal: owned by `projects`, reading worklogs from `work_items` through its public
   interface.
5. **Microsoft Project import format.** Proposal: import the Microsoft Project XML format and
   CSV only; the binary `.mpp` format is not supported, because no library with a licence that
   allows on-prem redistribution has been checked (REQ-PRJ-008).
6. **One open release per change.** Proposal: a change can belong to only one open release at a
   time (REQ-REL-033). Confirm, or allow a change in several releases.
7. **Defaults in Appendix A.** The release stages, templates, roles, closure codes, project
   statuses, roles and settings above need approval, as file 01's defaults were (D-041).
