# 03 — SLA, assignment, rules, workflows and notifications

Parity requirements for the automation engines that every work item type shares: SLA and OLA
policies with operating hours, auto-assignment, business rules, triggers and schedules, custom
actions and custom functions, life cycles and visual workflows, and the notification engine
(architecture.md §2.6, §6.5, §6.7, §6.8). Rules, ID scheme and field meanings:
[README.md](README.md).

**Status:** Draft v0.1, 2026-10-24, for product owner review. **Owner:** Haider (Product Owner).

## Scope of this file

- **This file owns the engines.** They are built once (in the `sla`, `automation`,
  `notifications` and `work_items` modules) and every work item type uses them: incidents,
  service requests, problems, changes and releases, and later other records.
  - **REQ-SLA-*:** SLA and OLA policies, matching, targets, operating hours, holidays, time
    zones, pause and resume, escalations, breach handling, recalculation and SLA data for
    reports.
  - **REQ-ASG-*:** routing to groups, technician auto-assignment, availability, shifts, leave,
    skills and the team availability calendar.
  - **REQ-RUL-*:** business rules, triggers, timers, schedules, custom actions, webhooks,
    connections, global variables, custom functions, custom menus, simulation, audit and loop
    protection.
  - **REQ-WF-*:** the life cycle engine (status machines per template) and the visual workflow
    designer and runtime.
  - **REQ-NTF-*:** the notification engine: channels, rules, recipients, templates, languages,
    preferences, digests, quiet hours, delivery, bounces and storm protection.
- **What file 01 already holds, and this file does not repeat:**
  - status categories and the default incident life cycle (REQ-INC-044 to REQ-INC-052),
    including the incident life cycle designer (REQ-INC-049);
  - how an incident uses the SLA: never without priority or SLA (REQ-INC-011), due dates,
    countdown and due-date overrides (REQ-INC-012);
  - assigning by hand, taking and reassigning (REQ-INC-053 to REQ-INC-055);
  - form rules (REQ-INC-037) and the refusal of browser scripts (REQ-INC-043);
  - approvals on a record (REQ-INC-083), closure rules (REQ-INC-094), reopen (REQ-INC-097) and
    merge (REQ-INC-088);
  - the incident notification events, the notification centre, incident templates, the
    recipient's language and the notification log (REQ-INC-130 to REQ-INC-134);
  - the automation trace on the record (REQ-WI-004) and "no silent failures" (REQ-WI-009).
- **Not in this file** (each has its own module file):
  - multi-stage catalog approvals, approval delegation and approval settings (file 02, service
    requests and catalog);
  - closure rules and follow-ups for problems (file 04, problems);
  - change stages, stage closure rules, CAB, freeze windows and conflict detection (file 05,
    changes);
  - asset auto-assignment and contract renewal alerts (file 07, assets and contracts);
  - SLA reports, dashboards and wallboards (file 09, reports and dashboards);
  - SLA breach prediction, the SLA guardian agent and AI workflow drafting models (file 10, AI);
  - sites, departments, groups, roles, surveys and data archive (file 11, admin); mail servers
    and mailbox connections (file 12, REQ-INT-050 to REQ-INT-055);
  - Teams, Slack and WhatsApp channels, inbound webhooks, the API and extensions (file 12,
    integrations).
- **Monitoring is out of scope** (ADR-017, D-001). Rules and workflows may react to incidents
  that MonetX created and may read MonetX health read-only through `monitoring_integrations`.
  They never poll devices and never correlate or de-duplicate alerts.

## Words used in this file

| Word | Meaning |
|---|---|
| SLA policy | A set of conditions and targets that decides when a work item must be answered and resolved. |
| Target | One time limit inside a policy: first response, resolution, or an update cadence. |
| OLA | An operational level agreement: a target for one internal group's part of the work. |
| Calendar | Operating hours, exception hours and holidays in a time zone. Business time is time inside the calendar. |
| Pause | A period in which an SLA clock does not run, because the record is in a paused status category (REQ-INC-044). |
| Escalation level | An action set that runs at a fixed offset before or after a target's due time. |
| Business rule | A synchronous rule that runs inside the save of a record and can change it or refuse the save. |
| Trigger | An asynchronous rule that runs after a change is committed and starts actions. |
| Custom action | A reusable, named action (notification, field update, task, webhook, custom function ...) kept in a shared library. |
| Custom function | Admin-written code (Python or JavaScript) that runs in an isolated sandbox, never in the API process. |
| Life cycle | The status machine of a template: statuses and the allowed transitions between them. |
| Workflow | A visual flow of nodes (conditions, waits, approvals, actions) that runs durably for one record. |
| Instance | One running copy of a workflow or SLA clock for one record. |
| Notification rule | For one event: whether it notifies, whom, and through which channels. |

## Requirement summary

<!-- summary:start -->
**Counts by decision and priority**

| Decision | MVP | V1 | LATER | Total |
|---|---|---|---|---|
| SAME | 17 | 30 | 5 | 52 |
| BETTER | 36 | 22 | 1 | 59 |
| NEW | 7 | 21 | 5 | 33 |
| SKIP | 0 | 0 | 2 | 2 |
| **Total** | **60** | **73** | **13** | **146** |

Edition (lowest edition that includes it): Essentials 109, Professional 35, Enterprise 2. By prefix: REQ-SLA 40, REQ-ASG 15, REQ-RUL 32, REQ-WF 31, REQ-NTF 28.

| ID | Title | Decision | Priority | Edition |
|---|---|---|---|---|
| [REQ-SLA-001](#req-sla-001--sla-policies-for-every-work-item-type) | SLA policies for every work item type | BETTER | MVP | Essentials |
| [REQ-SLA-002](#req-sla-002--policy-conditions-with-the-shared-filter-grammar) | Policy conditions with the shared filter grammar | SAME | MVP | Essentials |
| [REQ-SLA-003](#req-sla-003--first-match-wins-in-an-order-the-admin-sees) | First match wins, in an order the admin sees | BETTER | MVP | Essentials |
| [REQ-SLA-004](#req-sla-004--why-this-sla-applies) | Why this SLA applies | BETTER | MVP | Essentials |
| [REQ-SLA-005](#req-sla-005--targets-by-priority-inside-one-policy) | Targets by priority inside one policy | BETTER | MVP | Essentials |
| [REQ-SLA-006](#req-sla-006--update-cadence-target) | Update cadence target | NEW | V1 | Essentials |
| [REQ-SLA-007](#req-sla-007--site-specific-slas-and-inherited-site-settings) | Site-specific SLAs and inherited site settings | SAME | V1 | Essentials |
| [REQ-SLA-008](#req-sla-008--service-requests-take-the-sla-of-their-catalog-item) | Service requests take the SLA of their catalog item | SAME | V1 | Essentials |
| [REQ-SLA-009](#req-sla-009--sla-for-changes-problems-and-releases) | SLA for changes, problems and releases | BETTER | V1 | Professional |
| [REQ-SLA-010](#req-sla-010--operating-hours-calendars) | Operating-hours calendars | BETTER | MVP | Essentials |
| [REQ-SLA-011](#req-sla-011--exception-hours) | Exception hours | SAME | V1 | Essentials |
| [REQ-SLA-012](#req-sla-012--holiday-calendars) | Holiday calendars | BETTER | MVP | Essentials |
| [REQ-SLA-013](#req-sla-013--which-calendar-and-time-zone-a-record-uses) | Which calendar and time zone a record uses | BETTER | MVP | Essentials |
| [REQ-SLA-014](#req-sla-014--business-time-arithmetic-that-can-be-trusted) | Business-time arithmetic that can be trusted | NEW | MVP | Essentials |
| [REQ-SLA-015](#req-sla-015--pause-and-resume-by-status-category) | Pause and resume by status category | BETTER | MVP | Essentials |
| [REQ-SLA-016](#req-sla-016--no-separate-stop-the-clock-button) | No separate stop-the-clock button | BETTER | MVP | Essentials |
| [REQ-SLA-017](#req-sla-017--pause-while-waiting-for-approval) | Pause while waiting for approval | SAME | V1 | Essentials |
| [REQ-SLA-018](#req-sla-018--pause-history-and-paused-time) | Pause history and paused time | SAME | MVP | Essentials |
| [REQ-SLA-019](#req-sla-019--near-breach-warning) | Near-breach warning | SAME | MVP | Essentials |
| [REQ-SLA-020](#req-sla-020--breaches-are-flagged-and-stay-flagged) | Breaches are flagged and stay flagged | SAME | MVP | Essentials |
| [REQ-SLA-021](#req-sla-021--breach-reasons) | Breach reasons | NEW | V1 | Essentials |
| [REQ-SLA-022](#req-sla-022--escalation-levels-before-and-after-the-due-time) | Escalation levels before and after the due time | BETTER | MVP | Essentials |
| [REQ-SLA-023](#req-sla-023--escalation-recipients-including-people-relative-to-the-record) | Escalation recipients, including people relative to the record | BETTER | MVP | Essentials |
| [REQ-SLA-024](#req-sla-024--escalation-actions) | Escalation actions | SAME | MVP | Essentials |
| [REQ-SLA-025](#req-sla-025--escalations-stop-when-they-no-longer-apply) | Escalations stop when they no longer apply | BETTER | MVP | Essentials |
| [REQ-SLA-026](#req-sla-026--tenant-wide-switch-for-escalation-messages) | Tenant-wide switch for escalation messages | SAME | V1 | Essentials |
| [REQ-SLA-027](#req-sla-027--what-happens-when-priority-or-conditions-change) | What happens when priority or conditions change | BETTER | MVP | Essentials |
| [REQ-SLA-028](#req-sla-028--due-dates-set-by-hand) | Due dates set by hand | SAME | MVP | Essentials |
| [REQ-SLA-029](#req-sla-029--reopen) | Reopen | BETTER | MVP | Essentials |
| [REQ-SLA-030](#req-sla-030--merge-conversion-and-template-change) | Merge, conversion and template change | BETTER | V1 | Essentials |
| [REQ-SLA-031](#req-sla-031--policy-versions-changing-a-policy-does-not-rewrite-the-past) | Policy versions: changing a policy does not rewrite the past | BETTER | V1 | Essentials |
| [REQ-SLA-032](#req-sla-032--test-which-sla-would-apply) | Test which SLA would apply | NEW | V1 | Essentials |
| [REQ-SLA-033](#req-sla-033--operational-level-agreements-for-groups) | Operational level agreements for groups | SAME | V1 | Essentials |
| [REQ-SLA-034](#req-sla-034--vendor-contract-targets) | Vendor contract targets | NEW | LATER | Professional |
| [REQ-SLA-035](#req-sla-035--customer-contract-slas-for-managed-service-providers) | Customer contract SLAs for managed service providers | NEW | LATER | Enterprise |
| [REQ-SLA-036](#req-sla-036--experience-level-measures) | Experience level measures | NEW | LATER | Professional |
| [REQ-SLA-037](#req-sla-037--durable-accurate-sla-clocks) | Durable, accurate SLA clocks | NEW | MVP | Essentials |
| [REQ-SLA-038](#req-sla-038--the-sla-panel-on-the-record) | The SLA panel on the record | BETTER | MVP | Essentials |
| [REQ-SLA-039](#req-sla-039--sla-data-for-reports-and-events) | SLA data for reports and events | SAME | MVP | Essentials |
| [REQ-SLA-040](#req-sla-040--breach-prediction-and-the-sla-guardian) | Breach prediction and the SLA guardian | NEW | LATER | Professional |
| [REQ-ASG-001](#req-asg-001--routing-rules-choose-the-group) | Routing rules choose the group | BETTER | MVP | Essentials |
| [REQ-ASG-002](#req-asg-002--auto-assignment-set-up-per-group) | Auto-assignment set up per group | BETTER | MVP | Essentials |
| [REQ-ASG-003](#req-asg-003--round-robin) | Round robin | SAME | MVP | Essentials |
| [REQ-ASG-004](#req-asg-004--load-balancing) | Load balancing | BETTER | MVP | Essentials |
| [REQ-ASG-005](#req-asg-005--skills-based-assignment) | Skills-based assignment | SAME | V1 | Essentials |
| [REQ-ASG-006](#req-asg-006--who-counts-as-available) | Who counts as available | BETTER | MVP | Essentials |
| [REQ-ASG-007](#req-asg-007--shifts) | Shifts | NEW | V1 | Essentials |
| [REQ-ASG-008](#req-asg-008--leave-and-absences) | Leave and absences | SAME | V1 | Essentials |
| [REQ-ASG-009](#req-asg-009--team-availability-calendar) | Team availability calendar | BETTER | V1 | Essentials |
| [REQ-ASG-010](#req-asg-010--backup-technicians-and-delegation-during-absence) | Backup technicians and delegation during absence | SAME | V1 | Essentials |
| [REQ-ASG-011](#req-asg-011--load-caps-and-what-happens-when-nobody-is-available) | Load caps and what happens when nobody is available | NEW | MVP | Essentials |
| [REQ-ASG-012](#req-asg-012--exclusions) | Exclusions | SAME | V1 | Essentials |
| [REQ-ASG-013](#req-asg-013--assignment-per-site) | Assignment per site | SAME | V1 | Essentials |
| [REQ-ASG-014](#req-asg-014--task-auto-assignment) | Task auto-assignment | SAME | V1 | Essentials |
| [REQ-ASG-015](#req-asg-015--explain-and-test-an-assignment) | Explain and test an assignment | NEW | V1 | Essentials |
| [REQ-RUL-001](#req-rul-001--business-rules-run-inside-the-save) | Business rules run inside the save | SAME | MVP | Essentials |
| [REQ-RUL-002](#req-rul-002--rule-conditions) | Rule conditions | BETTER | MVP | Essentials |
| [REQ-RUL-003](#req-rul-003--rule-actions-that-change-the-record) | Rule actions that change the record | SAME | MVP | Essentials |
| [REQ-RUL-004](#req-rul-004--refuse-a-save-with-a-clear-message) | Refuse a save with a clear message | BETTER | MVP | Essentials |
| [REQ-RUL-005](#req-rul-005--order-and-stop-here) | Order and "stop here" | BETTER | MVP | Essentials |
| [REQ-RUL-006](#req-rul-006--one-documented-order-for-all-automation) | One documented order for all automation | BETTER | MVP | Essentials |
| [REQ-RUL-007](#req-rul-007--rules-apply-on-every-path) | Rules apply on every path | BETTER | MVP | Essentials |
| [REQ-RUL-008](#req-rul-008--rules-for-every-module) | Rules for every module | BETTER | V1 | Essentials |
| [REQ-RUL-009](#req-rul-009--triggers-on-any-committed-event) | Triggers on any committed event | BETTER | MVP | Essentials |
| [REQ-RUL-010](#req-rul-010--trigger-actions) | Trigger actions | SAME | MVP | Essentials |
| [REQ-RUL-011](#req-rul-011--timers) | Timers | SAME | V1 | Essentials |
| [REQ-RUL-012](#req-rul-012--scheduled-rules) | Scheduled rules | BETTER | V1 | Essentials |
| [REQ-RUL-013](#req-rul-013--a-shared-library-of-custom-actions) | A shared library of custom actions | SAME | V1 | Essentials |
| [REQ-RUL-014](#req-rul-014--webhook-action) | Webhook action | BETTER | V1 | Essentials |
| [REQ-RUL-015](#req-rul-015--safe-reliable-webhook-delivery) | Safe, reliable webhook delivery | BETTER | V1 | Essentials |
| [REQ-RUL-016](#req-rul-016--connections) | Connections | SAME | V1 | Essentials |
| [REQ-RUL-017](#req-rul-017--global-variables) | Global variables | SAME | V1 | Essentials |
| [REQ-RUL-018](#req-rul-018--custom-functions) | Custom functions | BETTER | V1 | Professional |
| [REQ-RUL-019](#req-rul-019--functions-run-in-an-isolated-sandbox) | Functions run in an isolated sandbox | BETTER | V1 | Professional |
| [REQ-RUL-020](#req-rul-020--what-a-function-may-read-and-change) | What a function may read and change | NEW | V1 | Professional |
| [REQ-RUL-021](#req-rul-021--function-editor-test-runs-logs-and-versions) | Function editor, test runs, logs and versions | BETTER | V1 | Professional |
| [REQ-RUL-022](#req-rul-022--functions-as-conditions-inside-the-save) | Functions as conditions inside the save | SAME | LATER | Professional |
| [REQ-RUL-023](#req-rul-023--no-vendor-scripting-language-or-block-builder) | No vendor scripting language or block builder | SKIP | LATER | Essentials |
| [REQ-RUL-024](#req-rul-024--custom-menu-actions-on-records) | Custom menu actions on records | SAME | V1 | Professional |
| [REQ-RUL-025](#req-rul-025--test-and-simulate-rules) | Test and simulate rules | NEW | V1 | Essentials |
| [REQ-RUL-026](#req-rul-026--configuration-history-and-restore) | Configuration history and restore | BETTER | V1 | Essentials |
| [REQ-RUL-027](#req-rul-027--execution-log-and-failure-alerts) | Execution log and failure alerts | BETTER | V1 | Essentials |
| [REQ-RUL-028](#req-rul-028--loop-protection) | Loop protection | NEW | MVP | Essentials |
| [REQ-RUL-029](#req-rul-029--checked-when-saved-switched-on-deliberately) | Checked when saved, switched on deliberately | BETTER | MVP | Essentials |
| [REQ-RUL-030](#req-rul-030--move-automation-between-environments) | Move automation between environments | BETTER | LATER | Enterprise |
| [REQ-RUL-031](#req-rul-031--who-may-change-automation) | Who may change automation | SAME | V1 | Essentials |
| [REQ-RUL-032](#req-rul-032--runbook-actions-on-endpoints) | Runbook actions on endpoints | NEW | LATER | Professional |
| [REQ-WF-001](#req-wf-001--life-cycles-for-every-work-item-type) | Life cycles for every work item type | BETTER | MVP | Essentials |
| [REQ-WF-002](#req-wf-002--every-template-has-a-life-cycle-a-workflow-works-through-it) | Every template has a life cycle; a workflow works through it | BETTER | MVP | Essentials |
| [REQ-WF-003](#req-wf-003--before-during-and-after-a-transition) | Before, during and after a transition | SAME | MVP | Essentials |
| [REQ-WF-004](#req-wf-004--who-may-run-a-transition) | Who may run a transition | SAME | MVP | Essentials |
| [REQ-WF-005](#req-wf-005--life-cycle-versions-and-moving-records) | Life cycle versions and moving records | NEW | V1 | Essentials |
| [REQ-WF-006](#req-wf-006--validation-that-says-what-to-fix) | Validation that says what to fix | BETTER | V1 | Essentials |
| [REQ-WF-007](#req-wf-007--map-view-and-list-view) | Map view and list view | SAME | V1 | Essentials |
| [REQ-WF-008](#req-wf-008--visual-workflow-designer) | Visual workflow designer | SAME | V1 | Professional |
| [REQ-WF-009](#req-wf-009--node-types) | Node types | BETTER | V1 | Professional |
| [REQ-WF-010](#req-wf-010--how-a-workflow-starts) | How a workflow starts | BETTER | V1 | Professional |
| [REQ-WF-011](#req-wf-011--conditions-and-switches) | Conditions and switches | SAME | V1 | Professional |
| [REQ-WF-012](#req-wf-012--waiting-for-events-and-people-working-alongside) | Waiting for events, and people working alongside | BETTER | V1 | Professional |
| [REQ-WF-013](#req-wf-013--timer-nodes) | Timer nodes | SAME | V1 | Professional |
| [REQ-WF-014](#req-wf-014--approval-nodes) | Approval nodes | BETTER | V1 | Professional |
| [REQ-WF-015](#req-wf-015--notification-field-update-note-task-and-checklist-nodes) | Notification, field update, note, task and checklist nodes | SAME | V1 | Professional |
| [REQ-WF-016](#req-wf-016--webhook-and-custom-function-nodes) | Webhook and custom function nodes | SAME | V1 | Professional |
| [REQ-WF-017](#req-wf-017--sub-flows) | Sub-flows | NEW | V1 | Professional |
| [REQ-WF-018](#req-wf-018--parallel-branches) | Parallel branches | SAME | V1 | Professional |
| [REQ-WF-019](#req-wf-019--validation-when-saved) | Validation when saved | BETTER | V1 | Professional |
| [REQ-WF-020](#req-wf-020--durable-workflow-runtime) | Durable workflow runtime | NEW | V1 | Professional |
| [REQ-WF-021](#req-wf-021--workflow-versions-and-safe-migration-of-running-instances) | Workflow versions and safe migration of running instances | NEW | V1 | Professional |
| [REQ-WF-022](#req-wf-022--simulate-and-test-a-workflow) | Simulate and test a workflow | NEW | V1 | Professional |
| [REQ-WF-023](#req-wf-023--execution-view-on-the-record) | Execution view on the record | SAME | V1 | Professional |
| [REQ-WF-024](#req-wf-024--errors-are-handled-and-visible) | Errors are handled and visible | BETTER | V1 | Professional |
| [REQ-WF-025](#req-wf-025--overview-of-running-and-failed-instances) | Overview of running and failed instances | NEW | V1 | Professional |
| [REQ-WF-026](#req-wf-026--stop-detach-or-restart-a-workflow-on-a-record) | Stop, detach or restart a workflow on a record | BETTER | V1 | Professional |
| [REQ-WF-027](#req-wf-027--copy-export-and-history-of-workflows) | Copy, export and history of workflows | SAME | V1 | Professional |
| [REQ-WF-028](#req-wf-028--a-designer-that-is-easy-to-use) | A designer that is easy to use | BETTER | V1 | Professional |
| [REQ-WF-029](#req-wf-029--limits-that-keep-workflows-safe) | Limits that keep workflows safe | NEW | V1 | Professional |
| [REQ-WF-030](#req-wf-030--draft-a-workflow-from-a-description) | Draft a workflow from a description | SAME | LATER | Professional |
| [REQ-WF-031](#req-wf-031--workflows-for-other-records) | Workflows for other records | SAME | LATER | Professional |
| [REQ-NTF-001](#req-ntf-001--one-notification-engine-for-every-module) | One notification engine for every module | BETTER | MVP | Essentials |
| [REQ-NTF-002](#req-ntf-002--email-channel) | Email channel | SAME | MVP | Essentials |
| [REQ-NTF-003](#req-ntf-003--in-app-channel-for-every-module) | In-app channel for every module | SAME | MVP | Essentials |
| [REQ-NTF-004](#req-ntf-004--browser-notifications) | Browser notifications | NEW | V1 | Essentials |
| [REQ-NTF-005](#req-ntf-005--mobile-push) | Mobile push | SAME | LATER | Essentials |
| [REQ-NTF-006](#req-ntf-006--text-messages-through-a-gateway) | Text messages through a gateway | SAME | LATER | Essentials |
| [REQ-NTF-007](#req-ntf-007--no-email-to-sms-carrier-addresses) | No email-to-SMS carrier addresses | SKIP | LATER | Essentials |
| [REQ-NTF-008](#req-ntf-008--notification-rules-per-module-and-event) | Notification rules per module and event | BETTER | MVP | Essentials |
| [REQ-NTF-009](#req-ntf-009--recipients-including-people-relative-to-the-record) | Recipients, including people relative to the record | SAME | MVP | Essentials |
| [REQ-NTF-010](#req-ntf-010--access-is-checked-when-sending) | Access is checked when sending | NEW | MVP | Essentials |
| [REQ-NTF-011](#req-ntf-011--template-editor) | Template editor | BETTER | MVP | Essentials |
| [REQ-NTF-012](#req-ntf-012--preview-and-test-send) | Preview and test send | BETTER | MVP | Essentials |
| [REQ-NTF-013](#req-ntf-013--default-templates-for-every-module-with-versions-and-reset) | Default templates for every module, with versions and reset | BETTER | MVP | Essentials |
| [REQ-NTF-014](#req-ntf-014--notifications-in-english-and-arabic-urdu-from-v1) | Notifications in English and Arabic, Urdu from V1 | NEW | MVP | Essentials |
| [REQ-NTF-015](#req-ntf-015--branding-and-sender-identity) | Branding and sender identity | SAME | V1 | Essentials |
| [REQ-NTF-016](#req-ntf-016--personal-notification-preferences) | Personal notification preferences | NEW | V1 | Essentials |
| [REQ-NTF-017](#req-ntf-017--digests) | Digests | NEW | V1 | Essentials |
| [REQ-NTF-018](#req-ntf-018--quiet-hours-and-urgency) | Quiet hours and urgency | NEW | V1 | Essentials |
| [REQ-NTF-019](#req-ntf-019--repeat-reminders-for-pending-actions) | Repeat reminders for pending actions | SAME | V1 | Essentials |
| [REQ-NTF-020](#req-ntf-020--delivery-status-retries-and-resend) | Delivery status, retries and resend | BETTER | MVP | Essentials |
| [REQ-NTF-021](#req-ntf-021--bounces) | Bounces | NEW | V1 | Essentials |
| [REQ-NTF-022](#req-ntf-022--throttling-and-storm-protection) | Throttling and storm protection | NEW | MVP | Essentials |
| [REQ-NTF-023](#req-ntf-023--no-mail-loops-and-no-notifications-to-robots) | No mail loops and no notifications to robots | SAME | MVP | Essentials |
| [REQ-NTF-024](#req-ntf-024--secure-action-links) | Secure action links | BETTER | MVP | Essentials |
| [REQ-NTF-025](#req-ntf-025--send-a-notification-by-hand) | Send a notification by hand | SAME | V1 | Essentials |
| [REQ-NTF-026](#req-ntf-026--group-notifications-without-hidden-switches) | Group notifications without hidden switches | BETTER | MVP | Essentials |
| [REQ-NTF-027](#req-ntf-027--alerts-to-admins-about-the-platform) | Alerts to admins about the platform | NEW | V1 | Essentials |
| [REQ-NTF-028](#req-ntf-028--delivery-log-and-metrics-for-admins) | Delivery log and metrics for admins | NEW | V1 | Essentials |
<!-- summary:end -->

---

## 1. SLA policies and matching

#### REQ-SLA-001 — SLA policies for every work item type

Admins create SLA policies per work item type: incident, service request, problem, change and
release. A policy has a name, a description, translations, an optional site, an enabled switch
and its targets. Each type has its own ordered list of policies. Turning on SLA for a new type
needs no code (REQ-WI-001).

- **Decision:** BETTER. ServiceDesk Plus has SLA lists for incidents and service requests only,
  and a separate change SLA; problems and releases have none. One engine covers every type.
- **Source:** sdp-area-12 §Screens (SLA list and form), (12b) §Behaviour (service request SLA list); architecture §2.6, §2.4 (change SLAs), §6.7
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. An admin can create, edit, disable and delete an incident policy and a service request
     policy, each in its own list.
  2. A disabled policy is never matched, and records it already applies to keep it.
  3. A policy in use cannot be deleted; the admin is offered to disable it instead.
  4. The same SLA contract tests pass for incidents and service requests.

#### REQ-SLA-002 — Policy conditions with the shared filter grammar

A policy matches records through conditions built with the shared filter grammar (architecture
§6.5): any standard or custom field, with AND/OR groups. Typical conditions are priority,
impact, urgency, category, service and its business criticality (file 07), site, department,
group, requester, VIP flag, template and channel. A policy with no condition matches everything
and is used as the fallback.

- **Decision:** SAME. ServiceDesk Plus offers about 48 fields and text operators.
- **Source:** sdp-area-12 §Fields (SLA conditions); architecture §2.6 (criteria-based selection), §6.5 (filtering DSL)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A policy with "requester is VIP AND priority is P2" matches a P2 incident from a VIP and
     not a P2 incident from anyone else.
  2. A condition on a custom pick-list field works like one on a built-in field.
  3. The condition editor is the same component used by list filters and rules, and a
     condition saved in one can be pasted into the other.
  4. Saving a condition on a field that does not exist for the type is refused.

#### REQ-SLA-003 — First match wins, in an order the admin sees

Policies are checked in the order the admin sets, and the first one that matches applies. The
list shows the order and lets the admin drag policies up and down. When a new policy is saved,
the admin is told if an earlier, broader policy will always win over it. A tenant always has a
fallback policy at the bottom (Appendix A).

- **Decision:** BETTER. The order is the same idea, but we warn about policies that can never
  win.
- **Source:** sdp-area-12 §Actions (organize SLA), §Automation; sdp-area-12 (12b) §Weak spots (SLA ordering)
- **SDP weak spot fixed:** a new SLA lands last in the list, so an older, broader SLA silently
  beats it.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. With policies A (category is network) above B (no condition), a network incident gets A
     and any other incident gets B.
  2. Saving a policy below a policy with no condition shows a warning that it can never match.
  3. Reordering takes effect for new matches at once and is recorded in the configuration
     audit (REQ-RUL-026).
  4. The fallback policy cannot be moved above other policies or deleted.

#### REQ-SLA-004 — Why this SLA applies

Every record shows which policy applies, which version, which conditions matched, and when it
was applied. History records each change of policy with its reason: created, field changed,
priority changed, type converted, re-applied by an admin or set by hand.

- **Decision:** BETTER. ServiceDesk Plus leaves no history line when an SLA is chosen, so the
  effect has to be guessed.
- **Source:** sdp-area-12 (12b) §Behaviour (execution order: SLA leaves no history line), §Weak spots; REQ-WI-004
- **SDP weak spot fixed:** a business rule changing priority silently changes the SLA.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. The SLA panel on a record names the policy and lists the conditions that matched.
  2. A rule that raises priority, and so changes the policy, writes one history entry naming
     the rule, the old policy and the new policy.
  3. A record that matches no policy except the fallback says so on the panel.

#### REQ-SLA-005 — Targets by priority inside one policy

A policy holds a target table by priority: for each priority, a first response time and a
resolution time, in days, hours and minutes of business time. A policy can also use one target
for every priority. Each row can use its own calendar, so P1 can run around the clock while P4
uses office hours. A row can also ignore daily hours but still skip weekends, holidays or both.

- **Decision:** BETTER. ServiceDesk Plus needs one SLA per priority (High SLA, Medium SLA ...),
  each with its own conditions, which multiplies the list.
- **Source:** sdp-area-12 §Fields (respond within, resolve within), (12b) §Behaviour (high, medium, normal, low SLAs); sdp-area-02c §Automation (SLA by priority); architecture §2.6 (targets)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. One policy with four priority rows gives a P1 incident the P1 targets and a P4 incident
     the P4 targets.
  2. A row with "around the clock" counts weekends and holidays; a row on office hours does not.
  3. A row may leave a target empty, and that target is then not tracked for that priority.
  4. Times entered as 1 day 2 hours are stored as business minutes and shown back the same way.

#### REQ-SLA-006 — Update cadence target

Besides first response and resolution, a policy can set an update cadence per priority, for
example "the requester gets a public update at least every 2 hours on P1". The clock restarts
at every public reply or public note, and a missed update counts as its own breach.

- **Decision:** NEW. ServiceDesk Plus tracks only response and resolution.
- **Source:** architecture §2.6 (first response, response and resolution targets)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. On a P1 incident with a 2-hour cadence, no public update for 2 business hours marks an
     update breach, and escalation levels for that target run.
  2. A public reply restarts the cadence clock; a private note does not.
  3. Update breaches are counted separately from resolution breaches in SLA data
     (REQ-SLA-039).

#### REQ-SLA-007 — Site-specific SLAs and inherited site settings

A policy can be limited to one or more sites. For each site, an admin chooses whether it uses
the tenant-wide SLA policies and business rules, its own, or a copy of the tenant-wide ones to
change. Site policies are checked before tenant-wide ones.

- **Decision:** SAME. ServiceDesk Plus offers copy, refer or custom per site for SLAs, rules,
  departments and groups.
- **Source:** sdp-area-11 §Fields (site form: related settings), §Automation (site rules and SLAs apply automatically); sdp-area-12 §Fields (SLA site); architecture §2.6 (site-specific SLAs)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. An incident at site Riyadh gets the Riyadh policy; an incident at a site without its own
     policies gets the tenant-wide one.
  2. "Copy" creates independent copies; changing the tenant-wide policy later does not change
     the copies.
  3. "Use tenant-wide" shows the tenant-wide policies read-only on the site page.

#### REQ-SLA-008 — Service requests take the SLA of their catalog item

For service requests, the SLA can come from the conditions, from the catalog item (file 02),
or both. When both give an answer, the tenant setting decides which wins (Appendix A). The
record shows which source was used.

- **Decision:** SAME.
- **Source:** sdp-area-13 §Advanced Portal Settings (SLA for service requests: condition based, selected, both); sdp-area-03 §Config (SLA choice for service requests); architecture §2.2 (service-specific SLAs)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A service request from an item with its own SLA gets that SLA under the "catalog item"
     setting.
  2. Under "both, conditions win", a matching condition policy beats the item's SLA, and the
     panel says so.
  3. A service request with neither shows the "no SLA" marker (REQ-INC-011).

#### REQ-SLA-009 — SLA for changes, problems and releases

Changes get SLA policies with response and resolution targets and escalations, like incidents.
Problems and releases can have policies too, switched on per type. A change's targets can be
measured to stage dates (for example "planned within 3 business days") as well as to closure.

- **Decision:** BETTER. ServiceDesk Plus has change SLAs; problem and release SLAs are new.
- **Source:** architecture §2.4 (change SLAs), §2.6; sdp-area-04 §Behaviour (nothing automatic, no SLA on problems); sdp-area-05 §Fields (implementation due violated)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A change matching a change policy shows due dates and a countdown, and escalates on breach.
  2. Problem SLA is off for a new tenant; switching it on makes problem policies available.
  3. A stage target on a change is met when the change leaves that stage.

---

## 2. Operating hours, holidays and time zones

#### REQ-SLA-010 — Operating-hours calendars

Admins define operating-hours calendars: working days, one or more working periods per day (for
example 08:00–12:00 and 13:00–17:00), and a time zone. Any day can be a working day, so
Sunday-to-Thursday and Monday-to-Friday weeks both work. A tenant can hold many calendars, and
a "around the clock" calendar always exists.

- **Decision:** BETTER. Split shifts and any working week; ServiceDesk Plus shows one default
  calendar with one period per day.
- **Source:** sdp-area-12 §Screens (operational hours); sdp-area-11 §Navigation path (operational hours); sdp-area-14 §Screens (week start); architecture §2.6
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A calendar Sunday–Thursday 08:00–17:00 Asia/Riyadh counts a Thursday 16:00 incident with a
     2-hour target as due Sunday 09:00.
  2. A day with two periods counts only the time inside them.
  3. A calendar change applies to open records from the next recalculation, and the admin is
     told how many open records it affects before saving.

#### REQ-SLA-011 — Exception hours

A calendar can hold exception periods with other hours, for example shorter hours in Ramadan or
a one-off weekend working day. Exceptions override the normal week for their dates.

- **Decision:** SAME. ServiceDesk Plus has special operational hours.
- **Source:** sdp-area-12 §Screens (special operational hours tab)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. An exception "10:00–15:00 from 1 to 29 March" changes due dates for records running in
     those days and no others.
  2. An exception that makes a Friday a working day counts business time on that Friday.

#### REQ-SLA-012 — Holiday calendars

Admins keep holiday lists (name, date or date range, optional half day) and attach them to
operating-hours calendars. Holidays can be added per year, copied to the next year, and
imported from an iCalendar file, so holidays that move each year (for example Eid) are easy to
enter.

- **Decision:** BETTER. Adds import and copy-forward to the holiday groups ServiceDesk Plus has.
- **Source:** sdp-area-12 §Screens (holiday groups); sdp-area-11 §Navigation path (holiday groups)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A holiday on a working day removes that day from business time for every calendar it is
     attached to.
  2. Importing an iCalendar file with 12 holidays creates 12 entries and reports any it skipped.
  3. "Copy to next year" creates the same named holidays for next year, flagged for review.

#### REQ-SLA-013 — Which calendar and time zone a record uses

Each policy row chooses where its calendar comes from:

- the record's site calendar (default);
- the assigned group's calendar (for follow-the-sun teams);
- a fixed calendar;
- around the clock.

Each site has a time zone and a calendar. When the source changes (a new site or group), the
due dates are recalculated and history shows the effect.

- **Decision:** BETTER. ServiceDesk Plus applies the site's hours; using the group's calendar is
  new.
- **Source:** sdp-area-11 §Fields (site form: time zone); sdp-area-12 §Fields (SLA operational hours); architecture §2.6 (per-site calendars, ignore business hours for critical tickets); REQ-INC-016
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Two incidents with the same policy at sites in Karachi and Riyadh get due dates in each
     site's hours and time zone.
  2. Moving an incident to another site recalculates its due dates and writes one history
     entry with old and new values.
  3. Each user sees due dates in their own time zone (REQ-WI-014), whatever the calendar's zone.

#### REQ-SLA-014 — Business-time arithmetic that can be trusted

One shared calendar service does all business-time maths: due dates, elapsed time, paused
time, worklog business time and reports. It handles daylight-saving changes, periods that
cross midnight and leap years. Its results are covered by a published test table.

- **Decision:** NEW. Engineering requirement; the research could not verify ServiceDesk Plus's
  arithmetic.
- **Source:** sdp-area-12 (12b) §Behaviour (SLA pause inconclusive, weekday retest needed); sdp-area-02c §Weak spots (due-by mismatch); REQ-WI-014
- **SDP weak spot fixed:** the header countdown and the due date in history disagreed.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A test table of at least 50 cases (weekends, holidays, exceptions, daylight saving, night
     shifts) passes in CI.
  2. The countdown on the record, the due date in the list and the due date in history come
     from the same calculation and agree to the second.
  3. A period crossing midnight (22:00–06:00) counts as one continuous working period.

---

## 3. Running the clock: pause, resume and breach

#### REQ-SLA-015 — Pause and resume by status category

SLA clocks pause when a record enters a status of the paused category, and resume when it
leaves it (REQ-INC-044). There is no other way to stop a clock. A policy may say which of its
targets pause: by default both response and resolution pause.

- **Decision:** BETTER. Pausing follows the fixed status category. ServiceDesk Plus pauses by a
  per-status timer flag, and by default pauses on "In Progress".
- **Source:** sdp-area-12 §Config (statuses: stop timer), §Weak spots; sdp-area-13 §Helpdesk customization (status types); sdp-area-12 (12b) §Behaviour (SLA pause inconclusive); architecture §2.6 (timer control)
- **SDP weak spot fixed:** the SLA form has no pause control, and the work-in-progress status
  stops the clock.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. An incident paused for 1 business hour and then resumed has its due dates pushed out by
     exactly 1 business hour.
  2. A pause that starts and ends outside business hours does not change the due date.
  3. A policy that pauses only resolution keeps the response clock running while paused.
  4. The countdown shows "paused" with the pause start time while paused, live.

#### REQ-SLA-016 — No separate stop-the-clock button

The clock is paused only by moving to a paused status. Who may do that is controlled by the
life cycle (who may run the transition) and the reason prompt (REQ-INC-047). There is no
separate "stop timer" switch on the record.

- **Decision:** BETTER. ServiceDesk Plus has a separate "allow stop timer" permission next to
  status-based pausing, so two mechanisms can disagree.
- **Source:** sdp-area-11 §Fields (advanced permissions: allow stop timer); sdp-area-12 §Config (statuses)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. No API or screen pauses an SLA clock except a status change into the paused category.
  2. A transition into "awaiting third party" limited to group heads cannot be used by other
     technicians to pause the clock (403).

#### REQ-SLA-017 — Pause while waiting for approval

A policy can pause the resolution clock while an approval on the record is pending, without
changing the status. This is off by default for incidents and on by default for service
requests (Appendix A).

- **Decision:** SAME. ServiceDesk Plus can stop the timer and set "on hold" while waiting for
  approval.
- **Source:** sdp-area-13 §Approval Settings (approval process: stop the timer while waiting)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. With the option on, a service request waiting 4 business hours for approval has its
     resolution due date moved by 4 business hours.
  2. The SLA panel shows "paused: approval pending" with the approval's link.
  3. With the option off, a pending approval does not affect the clock.

#### REQ-SLA-018 — Pause history and paused time

Every pause and resume is kept: start, end, the status or approval that caused it, and who
caused it. The record shows total paused business time and calendar time. These values are
available as list columns, filters and report fields.

- **Decision:** SAME. ServiceDesk Plus shows on-hold time in its time analysis.
- **Source:** sdp-area-02c §Screens (time elapsed analysis: on-hold time); REQ-INC-013
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Two pauses of 30 and 45 business minutes show a total paused time of 1 hour 15 minutes.
  2. Each pause is listed on the SLA panel with its cause.
  3. "Paused time" can be used as a filter in a list view.

#### REQ-SLA-019 — Near-breach warning

Each target has a warning point, as a percentage of the target or a fixed time before the due
time (Appendix A). At the warning point the record turns to a warning state in every list and
on the record, and the warning actions run (REQ-SLA-022).

- **Decision:** SAME. ServiceDesk Plus has "approaching violation" views and pre-breach
  escalations.
- **Source:** sdp-area-01 §Screens (requests approaching SLA violation); sdp-area-12 §Fields (escalation before); architecture §2.6 (pre-breach)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. With a 75 % warning point and a 4-hour target, the record turns to warning after 3
     business hours, live, with no reload.
  2. The built-in view "about to breach" lists exactly the records in warning, live.
  3. A paused record does not reach its warning point while paused.

#### REQ-SLA-020 — Breaches are flagged and stay flagged

When a due time passes without the target being met, the target is marked breached at that
moment. The flag stays even after the record is resolved, reopened or the SLA changes, and it
records the time and the amount of the breach. Meeting a target stamps it met, with the time
left.

- **Decision:** SAME. ServiceDesk Plus sets "first response overdue" and "overdue" flags.
- **Source:** sdp-area-12 §Behaviour (first response overdue, overdue status); architecture §2.6 (violation flags)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. An incident whose 5-minute resolution target passes is marked breached within 60 seconds
     of the due time, with a history entry from source "SLA".
  2. Resolving it later keeps the breached flag and records how long after the due time it
     was resolved.
  3. A first response sent before its due time stamps the response target met.
  4. Lists can filter on "response breached" and "resolution breached" separately.

#### REQ-SLA-021 — Breach reasons

When a target is breached, the assignee can be asked to choose a breach reason from an
admin-defined list (for example waiting on vendor, wrong priority, capacity). The reason feeds
SLA reports. Asking is a tenant setting, off by default.

- **Decision:** NEW. ServiceDesk Plus records breaches but not why.
- **Source:** product-plan §5 (SLA and escalation); architecture §2.6 (SLA compliance reports)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. With the setting on, resolving a breached incident asks for a breach reason, and the
     resolve is refused without one.
  2. Breach reasons have translations and can be disabled without affecting old records.
  3. The reason is a report field.

---

## 4. Escalations

#### REQ-SLA-022 — Escalation levels before and after the due time

Each target can have several escalation levels. Each level runs at a set business-time offset
before or after the due time, and has its own recipients and actions. Response and resolution
targets both support at least four levels; the warning point counts as one of them if the
admin wants.

- **Decision:** BETTER. ServiceDesk Plus allows one response level and four resolution levels.
- **Source:** sdp-area-12 §Fields (SLA escalations); architecture §2.6 (escalations)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A resolution target with levels "1 hour before", "at breach" and "2 hours after" runs each
     level once, at its time, and history records each run with source "SLA".
  2. A response target can have four levels.
  3. Levels run in order; a level is never run twice for the same target instance.

#### REQ-SLA-023 — Escalation recipients, including people relative to the record

Escalations can go to specific users, groups and roles, and to people relative to the
record: the assignee, the group's head, the assignee's manager, the requester's manager, the
department head, the site manager and the change manager. If a relative person is not set (for
example no assignee), the level falls back to the next person in a list the admin sets.

- **Decision:** BETTER. ServiceDesk Plus escalates to organisation roles or technicians; the
  research could not confirm what happens when the owner is empty.
- **Source:** sdp-area-12 §Fields (escalate to, $Ticket Owner), §Behaviour (escalation to owner not seen); sdp-area-11 §Fields (organization roles), §Automation (org roles feed escalations)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. An escalation to "the assignee" on an unassigned incident goes to the group head, as the
     fallback says, and history names the fallback.
  2. An escalation to "assignee's manager" goes to the manager on the assignee's profile.
  3. A recipient who cannot see the record is skipped and the skip is logged.

#### REQ-SLA-024 — Escalation actions

An escalation level can do any of these:

- notify (through the notification engine, any channel);
- reassign to a technician or group, or move to the next support level;
- raise the priority;
- set fields or add a note;
- run any custom action from the library, including webhooks and custom functions.

- **Decision:** SAME.
- **Source:** sdp-area-12 §Fields (escalation custom actions); architecture §2.6 (actions: notify, reassign, change group, raise priority, run custom function)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A level that reassigns to group B moves the incident to group B and notifies both groups.
  2. A level that raises priority does not change the targets of the running SLA unless the
     policy says so, and history shows both facts.
  3. A failed action (for example a webhook) shows on the record and in the automation log
     (REQ-WI-009).

#### REQ-SLA-025 — Escalations stop when they no longer apply

Escalation levels for a target are cancelled when the target is met, when the record is
resolved, closed or canceled, and are held while the clock is paused. When the record is
reopened or the due time moves, the remaining levels are rescheduled.

- **Decision:** BETTER. The research could not confirm escalation behaviour; we define it.
- **Source:** sdp-area-12 §Behaviour (escalation not confirmed), §Limits
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. An incident resolved 5 minutes before its "at breach" level never runs that level.
  2. A level due during a pause runs after the resume, at the right business-time offset.
  3. Pushing the due date by 1 day moves every remaining level by 1 day.

#### REQ-SLA-026 — Tenant-wide switch for escalation messages

An admin can pause all escalation notifications for the tenant, for example during a
migration, with a reason and an end time. Breach flags still record. The pause is audited and a
banner tells admins while it is on.

- **Decision:** SAME. ServiceDesk Plus has a global "disable all SLA based mail escalations"
  action; we add a reason, an end time and a banner.
- **Source:** sdp-area-12 §Actions (SLA list menu), (12b) §Actions
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. With the switch on, a breach sets the flag but sends no escalation notification.
  2. The switch turns itself off at its end time.
  3. Turning it on and off writes audit entries with the reason.

---

## 5. Recalculation and edge cases

#### REQ-SLA-027 — What happens when priority or conditions change

When a field used by policy conditions changes (priority, category, site, group ...), the
policy is checked again. If the policy or the target row changes:

- targets already met or breached keep their stamp;
- open targets are recalculated from the record's SLA start with the new times, minus pauses
  (default), or restarted from the moment of change (tenant setting, Appendix A);
- the record shows old and new due dates in one history entry.

- **Decision:** BETTER. ServiceDesk Plus re-evaluates silently and only when priority is set.
- **Source:** sdp-area-02c §Automation (SLA by priority), §Weak spots; sdp-area-12 (12b) §Weak spots (rule priority change); REQ-INC-012
- **SDP weak spot fixed:** priority silently drives the SLA, and nothing fires until priority
  is set.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Raising priority from P3 to P1 after 1 business hour gives a resolution due date of the
     P1 target counted from creation, and one history entry with old and new due dates.
  2. A response already met before the change stays met.
  3. Under the "restart" setting, the same change counts the P1 target from the moment of
     change.
  4. If the new due date is already past, the target is marked breached at once, with reason
     "target changed".

#### REQ-SLA-028 — Due dates set by hand

When a technician with permission changes a due date by hand (REQ-INC-012), automatic
recalculation of that target stops until the override is cleared. Escalation levels follow the
new due date. Clearing the override restores the calculated due date.

- **Decision:** SAME, with a clear rule for later recalculation.
- **Source:** sdp-area-11 §Fields (modifying due time); sdp-area-02c §Behaviour (edit form: editable due by date)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. After a manual due date, a priority change does not move that due date, and the panel
     says why.
  2. Clearing the override recalculates the due date from the current policy.
  3. The override shows a "set by hand" marker with who and why.

#### REQ-SLA-029 — Reopen

When a resolved or closed record is reopened (REQ-INC-097), the resolution target continues by
the tenant's rule (Appendix A):

- resume: the clock goes on from the business time already used, and the time spent resolved
  does not count (default);
- restart: a new resolution target starts at reopen.

The earlier met or breached stamp stays in history, and reports can count first-time and
after-reopen results.

- **Decision:** BETTER. ServiceDesk Plus resets elapsed time to zero on reopen and clears the
  old values.
- **Source:** sdp-area-02c §Automation (reopening clears values, resets time elapsed); REQ-INC-097
- **SDP weak spot fixed:** reopening wipes the SLA history of the first resolution.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Under "resume", an incident resolved after 3 of 8 business hours and reopened has 5
     business hours left.
  2. Under "restart", it gets a full 8 business hours from the reopen.
  3. The first resolution's met or breached stamp is still visible on the SLA panel.

#### REQ-SLA-030 — Merge, conversion and template change

- **Merge** (REQ-INC-088): the merged source's clocks stop with its status. The target keeps
  its own SLA by default; a tenant setting can give it the strictest open due date among the
  merged records.
- **Conversion** (REQ-INC-089): the record is matched against the new type's policies, and
  met and breached stamps are kept.
- **Template change:** the policy is checked again like any other condition change.

- **Decision:** BETTER. The research could not see what happened to a merged request.
- **Source:** sdp-area-02c §Behaviour (#39 state unverified); REQ-INC-088; REQ-INC-089
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Merging A into B stops A's clocks and leaves B's due dates unchanged under the default.
  2. Under "strictest", B takes A's earlier resolution due date, and history says why.
  3. Converting an incident into a service request matches service request policies and keeps
     the incident's breach flags.

#### REQ-SLA-031 — Policy versions: changing a policy does not rewrite the past

Each saved change to a policy creates a new version. New matches use the new version. Records
already running keep the version they started with, unless the admin chooses to re-apply the
new version to open records, which runs as a background job with progress and a summary.

- **Decision:** BETTER. Editing a live SLA has no defined effect on open records in ServiceDesk
  Plus.
- **Source:** architecture §6.7 (SLA timers), §10 (bulk as background jobs)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Changing P1 resolution from 4 to 2 hours leaves running P1 incidents on 4 hours.
  2. "Re-apply to open records" recalculates them in a background job, shows progress live and
     writes one history entry per record.
  3. The SLA panel names the version in use and links to its definition.

#### REQ-SLA-032 — Test which SLA would apply

An admin can test the SLA set-up: pick an existing record or fill in sample values and a
start time, and see which policy matches, why, the due dates and when each escalation level
would run. Nothing is saved.

- **Decision:** NEW. ServiceDesk Plus offers no way to check an SLA except creating test
  tickets.
- **Source:** sdp-area-12 §Behaviour (test requests needed); sdp-area-12 (12b) §Weak spots (SLA ordering)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Testing a sample P1 network incident at site Riyadh on a Thursday 16:00 shows the policy,
     the due dates and the escalation times in the site's zone.
  2. The test shows which earlier policies were checked and why they did not match.
  3. Running a test changes no record and sends no notification.

---

## 6. OLAs and contracts

#### REQ-SLA-033 — Operational level agreements for groups

An OLA sets a target for the part of the work a group owns, for example "network team picks
up within 30 minutes and hands back within 4 business hours". The OLA clock runs while the
record (or one of its tasks) is assigned to that group, using the group's calendar. OLAs show
beside the SLA on the record and have their own warnings, breaches and escalations.

- **Decision:** SAME. Architecture asks for OLAs inside SLAs for internal support groups.
- **Source:** architecture §2.6 (OLAs); product-plan §5 (SLA, OLA and XLA)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. An incident assigned to the network group for 3 business hours and then moved away shows
     an OLA met with 1 hour to spare.
  2. A task assigned to another group runs that group's OLA on the task.
  3. OLA breaches do not mark the SLA breached, and reports show them apart.

#### REQ-SLA-034 — Vendor contract targets

When work waits on an outside vendor, the record can be linked to the vendor's contract
(file 07), and the contract's response and fix times are tracked like an OLA. A breach can
notify the contract owner.

- **Decision:** NEW. Underpinning contracts are not tracked in ServiceDesk Plus.
- **Source:** product-plan §5 (purchase and contracts: SLA linkage)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Moving an incident to "awaiting third party" with vendor contract X starts the contract's
     fix-time clock.
  2. A vendor breach notifies the contract owner and appears in vendor reports.

#### REQ-SLA-035 — Customer contract SLAs for managed service providers

For MSP tenants, each customer organisation can have its own contract with SLA policies,
calendars and holidays. Policies from a customer's contract are matched before general ones.

- **Decision:** NEW. ServiceDesk Plus sells MSP as a separate product.
- **Source:** architecture §2.15 (MSP: per-customer SLAs); product-plan §5 (customer contract SLAs for MSP)
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. Incidents for customer A use customer A's policies and calendar; customer B's do not.
  2. Reports can show SLA results per customer contract.

#### REQ-SLA-036 — Experience level measures

Alongside time-based targets, a tenant can track an experience level measure per service: the
satisfaction score from closure surveys and the number of reopens and reassignments, against a
goal. It is reported per service, never per person, by default.

- **Decision:** NEW. ServiceDesk Plus has no XLA.
- **Source:** product-plan §5 (SLA, OLA and XLA; XLA P1)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A service with an XLA goal of 4.2 average satisfaction shows the current value and the
     trend.
  2. The measure uses only surveys and records the viewer may see.

---

## 7. SLA engine qualities and data

#### REQ-SLA-037 — Durable, accurate SLA clocks

SLA clocks are durable timers, one per record (architecture §6.7, ADR-004). They survive
restarts, upgrades and failover without drift or double runs, and they keep working with
millions of open records.

- **Decision:** NEW. Engineering requirement.
- **Source:** architecture §6.7 (SLA timers on Temporal), §1.3; ADR-004; D-038 (11)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A breach is flagged within 60 seconds of the due time (p99), with 1 million running clocks
     in the load test.
  2. Restarting every worker during a test does not lose, delay by more than 60 seconds, or
     repeat any escalation level.
  3. The same tests pass on the single-node on-prem profile and on SaaS.

#### REQ-SLA-038 — The SLA panel on the record

The record has an SLA panel that shows, for each target (response, resolution, update cadence,
OLAs): due time, time left or overdue, state (running, paused, warning, met, breached), the
pauses, the escalation levels with their state, the policy and its version. It updates live.

- **Decision:** BETTER. ServiceDesk Plus shows due-by and an overdue icon in the header and a
  time analysis tab.
- **Source:** sdp-area-02c §Screens (details tab, time elapsed analysis); sdp-area-12 §Behaviour (due in, delay by); architecture §2.6 (SLA countdown on every ticket)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. The panel shows every target with its state, and changes to warning, paused and breached
     live, with no reload.
  2. Each escalation level shows "waiting", "ran at <time>" or "cancelled".
  3. The panel is readable with a screen reader and in right-to-left layout.
  4. The requester's portal view shows only what the tenant allows (by default, the resolution
     due time and nothing about escalations).

#### REQ-SLA-039 — SLA data for reports and events

Every SLA change produces a domain event: applied, warning, paused, resumed, met, breached,
escalated, recalculated. Each record keeps its SLA results as fields: per target, the due time,
met or breached, breach amount, business time used and paused time. Reports, dashboards and
analytics (file 09) use these, and they are the same values the record shows.

- **Decision:** SAME, with events added. ServiceDesk Plus has SLA violation reports and widgets.
- **Source:** sdp-area-01 §Screens (SLA violation reports by category, group, level, priority, technician); architecture §2.6 (compliance reports and widgets), §6.5; REQ-WI-019
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A breach produces one "breached" event through the outbox, and the analytics store shows it
     within 1 minute.
  2. SLA result fields can be used in list columns, filters and exports.
  3. A report of compliance by group for last month matches the count of met and breached
     targets in the records.

#### REQ-SLA-040 — Breach prediction and the SLA guardian

The AI SLA guardian (file 10) uses the SLA engine's data to predict breaches and act before
them, through the same actions as escalations and with the same permissions and audit. This
file only provides the data and the actions it needs.

- **Decision:** NEW. ServiceDesk Plus has no breach prediction.
- **Source:** product-plan §7.3 (SLA guardian agent), §5 (breach prediction); architecture §12; REQ-AI-100 (SLA guardian agent)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. The SLA engine exposes, through the public API, each open target's due time, time left,
     pause state and escalation plan.
  2. An action taken by the guardian appears in history with source "AI agent" and the agent's
     name.

---

## 8. Routing and auto-assignment

#### REQ-ASG-001 — Routing rules choose the group

Admins keep an ordered list of routing rules per work item type. Each rule has conditions (the
shared filter grammar) and a target group, optionally per site. The first matching rule sets
the group when a record arrives without one. A category's suggested group (REQ-INC-006) is
used when no routing rule matches. A fallback group catches the rest.

- **Decision:** BETTER. In ServiceDesk Plus routing to a group is done with general business
  rules; a dedicated, ordered routing list is easier to read and to test.
- **Source:** sdp-area-12 (12b) §Behaviour (hardware dispatch rule sets the group); architecture §2.1 (assignment: technician groups)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. With rule "category is printers → printer group", a new printer incident gets the printer
     group, and history names the rule.
  2. An incident matching no rule and no category suggestion gets the fallback group.
  3. A record created with a group chosen by a person keeps it; routing does not override it
     unless the rule says so.

#### REQ-ASG-002 — Auto-assignment set up per group

Each group decides whether new work for it is assigned to a technician automatically, and how:
round robin, load balancing or skills-based. The group also sets which work item types it
applies to, whether it runs on create only or also when a record is moved to the group, and
whether it takes only unassigned records. Auto-assignment works for every work item type and
for tasks.

- **Decision:** BETTER. ServiceDesk Plus has one global page for all groups, for incidents (and
  optionally service requests) only.
- **Source:** sdp-area-12 §Screens (technician auto assign), §Fields (auto-assign fields), §Weak spots; sdp-area-11 §Config (no auto-assign on the group form); architecture §2.1 (assignment)
- **SDP weak spot fixed:** auto-assignment has no per-group set-up and covers incidents only
  unless a box is ticked.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Group A on round robin and group B on load balancing each assign their own new incidents
     by their own method.
  2. A group with auto-assignment off leaves records unassigned in the group queue.
  3. Moving an incident to group A with no technician assigns one when "also on move" is on.
  4. History names the method and the group's set-up used (REQ-WI-004).

#### REQ-ASG-003 — Round robin

Round robin gives each new record to the next available member of the group in turn. The turn
order is kept per group and is safe when many records arrive at the same moment.

- **Decision:** SAME.
- **Source:** sdp-area-12 §Fields (auto-assign model), (12b) §Behaviour (round robin picked a technician)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Nine incidents arriving for a group of three available technicians give each of them
     exactly three.
  2. Twenty incidents created in the same second never give two technicians the same turn or
     skip one.
  3. A technician who becomes unavailable is skipped, and gets the next turn when they return.

#### REQ-ASG-004 — Load balancing

Load balancing gives a new record to the available member with the lowest current load. Load
counts open records in the open status category (paused ones optionally), weighted by
priority (Appendix A). Ties go to whoever was assigned least recently.

- **Decision:** BETTER. Adds priority weights and a clear load definition; the research could
  not test ServiceDesk Plus's load balancing.
- **Source:** sdp-area-12 §Fields (load balancing), §Limits; sdp-area-12 (12b) §Limits (load balancing skipped)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. With A holding 2 open P3 incidents and B holding 1 open P1 incident (weight 4), a new
     incident goes to A.
  2. Paused records count only when the group says so.
  3. The assignment entry in history shows the loads that were compared.

#### REQ-ASG-005 — Skills-based assignment

Technicians have skills with a level (for example network level 3, Arabic speaker). Categories,
services and templates can require skills. Skills-based assignment picks an available member
who has the required skills, and among them uses round robin or load balancing.

- **Decision:** SAME. Architecture asks for assignment by skills.
- **Source:** architecture §2.1 (assignment by availability and skills)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. An incident in a category that needs "firewall level 2" goes only to members with that
     skill at level 2 or higher.
  2. If no available member has the skill, the record follows the fallback (REQ-ASG-011).
  3. A requester's preferred language can be a required skill.

#### REQ-ASG-006 — Who counts as available

Auto-assignment only picks technicians who are available. Availability combines:

- their shift and the group's operating hours (REQ-ASG-007);
- leave and other absences (REQ-ASG-008);
- their online state, set by the system from activity, by the technician, or by the system
  with the technician able to change it (tenant setting).

The tenant can also choose to check availability at the due time instead of now, for
long-running work.

- **Decision:** BETTER. Same choices as ServiceDesk Plus, combined with shifts and leave.
- **Source:** sdp-area-13 §Advanced Portal Settings (technician availability set by system, by technician, or both); sdp-area-12 §Fields (available on created date or due date); sdp-area-02c §Fields (online dot)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A technician on leave today is never auto-assigned today.
  2. Under "set by technician", a technician who sets themselves away is skipped until they
     return.
  3. Each technician's availability shows in the assign picker (REQ-INC-053) and updates live.

#### REQ-ASG-007 — Shifts

Groups and technicians can have shifts: repeating working patterns (for example a 24x7 NOC
rota with three shifts) with a time zone. A technician's shift decides when they can be
auto-assigned and which calendar their OLAs use.

- **Decision:** NEW. ServiceDesk Plus has instance operating hours but no technician shifts.
- **Source:** architecture §2.1 (assignment by availability); sdp-area-12 §Screens (operational hours)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A night-shift technician (22:00–06:00) is auto-assigned at 23:00 and not at 10:00.
  2. A rota with three rotating shifts over two weeks repeats correctly for the next two weeks.
  3. Shift changes take effect at once in auto-assignment and in the availability calendar.

#### REQ-ASG-008 — Leave and absences

Technicians or their managers record absences with an admin-defined type (for example annual
leave, sick leave, training) and a period. Whether technicians may add their own leave, and
whether a manager must approve it, are tenant settings.

- **Decision:** SAME. ServiceDesk Plus has unavailability types.
- **Source:** sdp-area-11 §Navigation path (unavailability types)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A technician records 3 days of annual leave; auto-assignment skips them for those 3 days.
  2. With approval required, leave counts only after the manager approves it.
  3. Absence types have translations and can be disabled without affecting old entries.

#### REQ-ASG-009 — Team availability calendar

Group heads and technicians see a team calendar per group: shifts, leave, holidays and
operating hours, by day and by week. It shows who is available now and who is covering for
whom. It updates live when leave or shifts change.

- **Decision:** BETTER. ServiceDesk Plus has no team availability view.
- **Source:** architecture §2.1 (availability), §8 (live updates)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Adding leave for a technician shows it on every open team calendar within 1 second.
  2. The calendar shows holidays from the site's holiday calendar.
  3. The calendar works in right-to-left layout with the week starting on the tenant's chosen
     day.

#### REQ-ASG-010 — Backup technicians and delegation during absence

A technician can name a backup, or a manager can name one for them. During an absence:

- new assignments meant for the absent technician go to the backup;
- optionally, their open records move to the backup, and move back when they return (tenant
  setting).

All moves are recorded and both people are notified.

- **Decision:** SAME. ServiceDesk Plus has request-ownership delegation.
- **Source:** sdp-area-12 §Screens (delegation: request ownership and approval delegation); architecture §2.1 (backup technicians)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. While A is on leave with backup B, a record routed to A is assigned to B, and history says
     it was delegated.
  2. With "move open records" on, A's open records move to B at the start of the leave and
     back at the end, unless B changed their assignee meanwhile.
  3. Approval delegation is handled with approvals (file 02); this requirement covers work
     items only.

#### REQ-ASG-011 — Load caps and what happens when nobody is available

A group can set a maximum open load per technician. If no member is available or all are at
their cap, the record stays in the group queue unassigned, the group head is notified, and the
record is offered again when someone becomes available.

- **Decision:** NEW. ServiceDesk Plus does not say what happens when nobody is available.
- **Source:** sdp-area-12 §Fields (availability), §Behaviour (only one login technician got everything)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. With a cap of 10 and every member at 10, a new incident stays unassigned and the group head
     is notified once.
  2. When a member drops to 9, the oldest waiting incident is assigned to them.
  3. The unassigned-for-N-minutes notification (REQ-INC-130) still applies.

#### REQ-ASG-012 — Exclusions

A group can exclude technicians from auto-assignment (for example the group head) and exclude
records by conditions (for example VIP incidents, which a person assigns by hand).

- **Decision:** SAME.
- **Source:** sdp-area-12 §Fields (exclude technicians, exclude requests)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. An excluded technician is never auto-assigned in that group but can be assigned by hand.
  2. An incident matching an exclusion condition stays unassigned in the group queue.

#### REQ-ASG-013 — Assignment per site

Groups belong to sites, and routing and auto-assignment respect them: a record at a site is
routed to that site's groups first. A group can serve several sites.

- **Decision:** SAME. ServiceDesk Plus groups are per site.
- **Source:** sdp-area-11 §Screens (technician groups by site), §Weak spots (groups per site easy to miss); sdp-area-02c §Fields (assign: site, group, technician)
- **SDP weak spot fixed:** a group's link to several sites is shown only in a small banner.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A routing rule scoped to site Lahore applies only to records at Lahore.
  2. The group list shows every site each group serves.

#### REQ-ASG-014 — Task auto-assignment

Tasks created from templates or workflows can be routed and auto-assigned to a group and a
technician with the same methods as records. A task can also be assigned to "the record's
assignee" or "the record's group".

- **Decision:** SAME. Architecture asks for task templates with auto-assignment.
- **Source:** architecture §2.2 (fulfilment: task templates with auto-assignment); REQ-INC-074
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A task template with group "desktop team" and round robin assigns each new task to the next
     desktop technician.
  2. A task set to "the record's assignee" follows the record if it is reassigned before the
     task starts, when the template says so.

#### REQ-ASG-015 — Explain and test an assignment

For any record, a user with permission can see why it was assigned as it was: which routing
rule, which method, the candidates considered and why others were skipped (unavailable, at
cap, missing skill, excluded). Admins can test routing and assignment on a sample record
without saving.

- **Decision:** NEW. ServiceDesk Plus records only "technician assigned through auto assign".
- **Source:** sdp-area-12 (12b) §Behaviour (execution order: history line for auto-assign); REQ-WI-004
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. The explanation for an auto-assigned incident lists every group member with the reason
     they were or were not picked.
  2. A test on sample values shows the group and technician that would be chosen, and changes
     nothing.

---

## 9. Business rules

#### REQ-RUL-001 — Business rules run inside the save

A business rule runs synchronously inside the save of a record, before it is committed
(architecture §6.7). Each rule has a name, a description, the work item type, the events it
runs on (create, update, delete), an optional time window (any time, inside or outside the
record's operating hours), an optional site and an enabled switch. Because it runs inside the
save, its changes are part of the same change and the same history entry group.

- **Decision:** SAME.
- **Source:** sdp-area-12 §Fields (business rule fields), §Automation; sdp-area-12 (12b) §Fields; architecture §6.7
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A rule on create that sets priority P2 for category "email" gives the new incident P2 in
     the same save, and its SLA uses P2.
  2. A rule limited to "outside operating hours" runs on an incident created on Friday at 20:00
     and not on one created on Monday at 10:00.
  3. A rule limited to site A never runs for records at site B.
  4. A disabled rule never runs, and disabling it is recorded in the configuration history
     (REQ-RUL-026).

#### REQ-RUL-002 — Rule conditions

Conditions use the shared filter grammar with AND/OR groups over standard and custom fields,
the requester's and assignee's attributes (VIP, department, site), and change operators: "is
changed", "changed from", "changed to". A rule with no condition matches every record of its
type.

- **Decision:** BETTER. Adds "changed from / changed to" and requester attributes to the
  operators ServiceDesk Plus offers.
- **Source:** sdp-area-12 §Fields (business rule conditions: is changed), (12b) §Screens (if node operators); architecture §6.5 (filtering DSL)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A rule "status changed from awaiting requester" fires only on that change.
  2. A rule "requester department is finance AND (priority is P1 OR P2)" matches only those
     records.
  3. A condition on a field that does not exist for the type is refused at save (REQ-WI-009).

#### REQ-RUL-003 — Rule actions that change the record

A business rule can set any standard or custom field the type has: group, technician,
category, subcategory, item, priority, impact, urgency, level, status (through an allowed
transition), template, site, tags, followers, assets and the "keep informed" list. For each
action the admin chooses whether it only fills empty fields or overwrites what a person
entered.

- **Decision:** SAME. ServiceDesk Plus offers the same field list and an override switch.
- **Source:** sdp-area-12 §Config (business-rule field list, override toggle), (12b) §Behaviour (hardware dispatch rule)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A "fill empty only" rule setting group B leaves group A in place when the user chose A.
  2. An "overwrite" rule replaces the user's value, and history shows both values and the rule.
  3. A rule that sets a status uses an allowed transition; a rule that would need a transition
     not allowed is refused at save.

#### REQ-RUL-004 — Refuse a save with a clear message

A rule can refuse the save with a message the admin writes in each language, for example
"Hardware requests must name an asset". The refusal applies on every path; the user sees the
message, keeps what they typed, and the API returns a problem code with the message.

- **Decision:** BETTER. Same "abort" capability, with translated messages and the user's
  input kept.
- **Source:** sdp-area-12 §Fields (abort process execution), (12b) §Behaviour (abort blocked creation), §Fields (abort with a custom message)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Creating a record that matches a refusing rule creates nothing and shows the message in the
     user's language.
  2. The same create through the API returns 422 with the rule's problem code and message.
  3. Every value the user entered is still in the form after the refusal.

#### REQ-RUL-005 — Order and "stop here"

Rules run in an order the admin sets by dragging. Each rule sees the changes made by the rules
before it. A rule can be marked "stop after this rule", so no later rule runs when it matches.
The list shows the order and marks rules that stop processing.

- **Decision:** BETTER. ServiceDesk Plus's "cascade" switch means the opposite of what most
  admins expect: a matching rule with cascade off silently stops every later rule.
- **Source:** sdp-area-12 §Actions (organize business rules, cascade), (12b) §Behaviour (cascade off stops later rules), §Fields (cascade)
- **SDP weak spot fixed:** a rule with cascade off stops all later rules, even a refusing rule,
  and nothing on the list shows it.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. With rule 1 setting P2 and rule 2 matching "priority is P2", both run in that order.
  2. With rule 1 marked "stop after this rule", rule 2 does not run when rule 1 matches, and the
     trace says why.
  3. The list shows a stop marker on rules that stop processing.

#### REQ-RUL-006 — One documented order for all automation

Automation on a save runs in a fixed, documented order, the same for every type and path:

1. template defaults and form rules (REQ-INC-037);
2. business rules, in their order;
3. the priority matrix (REQ-INC-009);
4. routing and auto-assignment (REQ-ASG-001, REQ-ASG-002);
5. SLA selection (REQ-SLA-003);
6. automatic status moves (REQ-INC-050);
7. commit, then triggers, workflows and notifications from the committed events.

If a later step changes a field that an earlier step uses, the earlier step is not run again
within the same save; the trace shows the final values.

- **Decision:** BETTER. The research had to infer ServiceDesk Plus's order from side effects.
- **Source:** sdp-area-12 §Behaviour (execution order), (12b) §Behaviour (execution order on #56); architecture §6.7
- **SDP weak spot fixed:** business rules and SLA selection leave no trace, and history is per
  minute, so the order had to be guessed.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. The automation trace of one save lists the steps in the documented order with second
     precision and their effects.
  2. A business rule that sets priority changes the SLA chosen in the same save.
  3. Triggers and workflows never run for a save that was refused or rolled back.

#### REQ-RUL-007 — Rules apply on every path

Business rules run the same way whatever made the change: the console, the portal, email,
the API, bulk edits, other rules' triggers, workflows and AI agents. Imports can choose to run
rules or not, and the import report says which.

- **Decision:** BETTER. Makes the behaviour predictable for integrations and bulk work.
- **Source:** architecture §3 (P2), §6.7; REQ-INC-046
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A rule that sets the group on create gives the same result for an incident from email,
     from the portal and from the API.
  2. A bulk edit of 200 records runs the rules on each record and reports any refusals per
     record.

#### REQ-RUL-008 — Rules for every module

Business rules, triggers and schedules are available for every work item type, and later for
other records: assets, configuration items, contracts, purchase orders, knowledge articles and
projects. Each module registers the fields, events and actions its records support.

- **Decision:** BETTER. ServiceDesk Plus business rules cover requests only, and triggers a
  fixed set of modules.
- **Source:** sdp-area-12 §Screens (business rules: requests; triggers: request, problem, change, project, release); architecture §2.15 (automation and customisation)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A business rule can be created for problems and for changes, with each type's own fields.
  2. A new module becomes available to rules by registering its fields and events, with no
     change to the rule engine.

---

## 10. Triggers, timers and schedules

#### REQ-RUL-009 — Triggers on any committed event

A trigger runs after a change is committed, from the domain event (REQ-WI-019). It can react to
any event a module publishes, for example created, updated, status changed, assigned, note
added, requester replied, approval decided, task completed, SLA warning and SLA breached.
Triggers have conditions like business rules, an optional time window, a site and an enabled
switch.

- **Decision:** BETTER. ServiceDesk Plus triggers react to created, edited and deleted only.
- **Source:** sdp-area-12 §Screens (triggers), §Fields (trigger), (12b) §Screens (trigger form), §Fields (trigger event, time); architecture §6.7, §6.5
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A trigger on "requester replied" with condition "status is resolved" runs once for each
     such reply.
  2. A trigger never runs for a change that was rolled back.
  3. A redelivered event does not run the trigger's actions twice.
  4. History of the record names the trigger for every change its actions make.

#### REQ-RUL-010 — Trigger actions

A trigger runs one or more custom actions in order:

- notification;
- field update;
- approval request;
- timer;
- task or task template, checklist;
- webhook;
- custom function;
- start a workflow (REQ-WF-010).

Each action shows its outcome on the record. A failed action does not undo the others, and is
shown as failed with its reason.

- **Decision:** SAME, plus "start a workflow".
- **Source:** sdp-area-12 §Fields (trigger actions), §Automation, (12b) §Screens (action types), §Behaviour (trigger fired task then timer)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A trigger with "add task" then "start timer" adds the task and starts the timer, and
     history shows both in order.
  2. A failing webhook action shows a failure banner on the record (REQ-WI-009) while the
     other actions still run.
  3. Approval and webhook actions work with no mail server configured.

#### REQ-RUL-011 — Timers

A timer action waits a set time (days, hours, minutes; business time or calendar time) and then
runs its actions. It can have up to two follow-up levels at their own offsets, each with
actions. It can be cancelled by conditions (for example "status is resolved"), and it can pause
while the record is paused.

- **Decision:** SAME.
- **Source:** sdp-area-12 (12b) §Screens (timer node), §Fields (timer duration, levels, abort), §Behaviour (timer level 1 action ran one minute later)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A 1-minute timer runs its level-1 action one minute after it starts (±10 seconds), and
     history says "level 1 of timer X".
  2. A timer with cancel condition "status is resolved" stops when the record is resolved, and
     its later levels never run.
  3. A timer in business time started on Thursday 16:30 with 1 hour on a Sunday–Thursday
     08:00–17:00 calendar runs on Sunday at 08:30.

#### REQ-RUL-012 — Scheduled rules

A schedule runs on a timetable (once, every N minutes or hours, daily, weekly, monthly,
yearly, in a chosen time zone). It either finds records with a saved filter and runs actions on
each match, or runs one custom function. Examples are: remind requesters about records waiting
on them for 3 days; close records resolved for 5 days.

- **Decision:** BETTER. ServiceDesk Plus schedules only run a custom function; ours can also act
  on matching records without code.
- **Source:** sdp-area-12 §Screens (schedules), §Fields (schedule), §Automation; architecture §2.15 (scheduler)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A daily 09:00 Asia/Karachi schedule runs at 09:00 Karachi time every day, including across
     a daylight-saving change elsewhere.
  2. A schedule over a filter matching 1,200 records processes all of them as a background job
     and records a run summary.
  3. A schedule that is still running when its next time comes does not start a second run.
  4. Recurring records (REQ-INC-034) use the same scheduler.

---

## 11. Custom actions, webhooks and connections

#### REQ-RUL-013 — A shared library of custom actions

Notifications, field updates, approvals, timers, tasks, checklists, webhooks and custom
functions are kept as named custom actions in one library per module. Triggers, workflows,
life cycle transitions, escalations and schedules reuse them. Each action shows where it is
used. An action in use cannot be deleted, and changing it warns how many automations use it.

- **Decision:** SAME. ServiceDesk Plus shows usage counts per action.
- **Source:** sdp-area-12 §Screens (custom actions, usage counts), (12b) §Screens (custom actions page); sdp-area-12 §Test records (field update created from workflow dialog stays)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. An action used by two triggers and one workflow lists all three, with links.
  2. Deleting an action in use is refused and names its users.
  3. An action created from a workflow dialog that is then cancelled is not left behind in the
     library.

#### REQ-RUL-014 — Webhook action

A webhook action calls an outside URL with a chosen method (GET, POST, PUT, PATCH, DELETE),
headers, query parameters and a body built from a template with record variables. It
authenticates through a saved connection (REQ-RUL-016). The response can be mapped into record
fields or a note, and its status can steer a workflow branch. Admins can send a test call with
a sample record.

- **Decision:** BETTER. Adds response mapping and branches to the webhook form ServiceDesk Plus
  has.
- **Source:** sdp-area-12 §Fields (webhook action), §Behaviour (save and test blocked); architecture §2.14 (generic webhooks in and out)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A POST webhook with a JSON body template sends the record's display ID and subject, and
     the test call shows the request and response.
  2. Mapping `$.ticket.id` from the response into a custom field stores it on the record.
  3. A 4xx or 5xx response follows the error branch in a workflow.
  4. A test call works with no mail server configured.

#### REQ-RUL-015 — Safe, reliable webhook delivery

Webhook calls run outside the request, with a timeout, retries with backoff for temporary
errors, and a log of each call (time, status, duration; bodies masked for secrets). Calls to
private network ranges and to the platform itself are refused unless an admin allows them.
The number of calls per day is an entitlement limit (`check_limit`).

- **Decision:** BETTER. Adds retries, a call log and protection against calls into internal
  networks.
- **Source:** sdp-area-12 §Fields (webhook daily limit 3000, cloud or intranet endpoint), §Edition notes; architecture §11, §13.1
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A call that times out is retried with backoff (Appendix A) and then marked failed on the
     record.
  2. A webhook to 169.254.169.254 or to a private address is refused at save unless the address
     is on the tenant's allowlist.
  3. Reaching the daily limit refuses further calls with a clear reason, and the admin is
     notified.
  4. Secrets in headers never appear in the call log.

#### REQ-RUL-016 — Connections

Admins save connections to outside systems: OAuth 2.0 (client credentials or authorisation
code), API key, basic and bearer token. Webhooks and custom functions use a connection by name,
never by copying the secret. Secrets are encrypted, never shown again after saving, and can be
rotated. OAuth tokens are refreshed automatically.

- **Decision:** SAME. ServiceDesk Plus has outbound connections for functions.
- **Source:** sdp-area-14 §Screens (developer space: connections); sdp-area-12 §Fields (webhook connection link); architecture §11 (secrets never in code or logs)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A saved API-key connection shows only its name and the last 4 characters afterwards.
  2. Rotating the secret makes the next call use the new one with no change to the webhook.
  3. An expired OAuth token is refreshed before the call; a refresh failure marks the
     connection broken and notifies the admin.

#### REQ-RUL-017 — Global variables

Admins define tenant-wide named values (for example an ERP base URL or a cost-centre code),
grouped, with an optional secret flag. Templates, webhooks and custom functions refer to them
by name, so a change in one place reaches every automation.

- **Decision:** SAME.
- **Source:** sdp-area-14 §Screens (developer space: global variables)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Changing a variable's value changes the URL used by every webhook that refers to it, from
     the next call.
  2. A secret variable is never shown after saving and is masked in logs.
  3. Deleting a variable in use is refused and names its users.

---

## 12. Custom functions and custom menus

#### REQ-RUL-018 — Custom functions

Admins write custom functions in Python or JavaScript. A function can be used as:

- a condition (returns true or false) in triggers, timers and workflows;
- an action in triggers, escalations, timers, life cycle transitions and workflows;
- the job of a schedule;
- the action behind a custom menu (REQ-RUL-024).

A function receives the record and the event as input and returns a result in a defined shape.

- **Decision:** BETTER. Common languages instead of the vendor's own scripting language.
- **Source:** sdp-area-12 §Fields (custom function), §Config (custom function use as); sdp-area-14 §Screens (developer space: custom functions), §Automation; architecture §6.7; product-plan §5 (Python/JS functions)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A Python function used as a trigger condition that returns false stops that trigger's
     actions, and the trace shows the result.
  2. A function used as an action that updates the record's category through the SDK changes
     it, with history naming the function.
  3. A function that returns a result in the wrong shape fails with a clear error, and the
     failure shows on the record.

#### REQ-RUL-019 — Functions run in an isolated sandbox

Custom functions never run in the API process or a worker that holds other tenants' data. They
run in an isolated sandbox runner (ADR-011) with limits on CPU, memory and run time, no file
system, and network access only to an allowlist the admin sets. Limits come from the
entitlement interface, so a licence may raise them; the same code runs on SaaS and on-prem.

- **Decision:** BETTER. Hard isolation, and no deployment-specific quotas in code.
- **Source:** architecture §6.7, §11.4; ADR-011; CLAUDE.md §5f; product-plan §5 (functions without quotas on-prem)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A function that loops forever is stopped at the time limit (Appendix A) and marked failed.
  2. A function that tries to open a file or reach a host not on the allowlist fails with a
     clear error.
  3. A function in tenant A cannot read any data of tenant B by any means, proven by a test.
  4. No API process imports or runs function code (checked by an architecture test).

#### REQ-RUL-020 — What a function may read and change

A function works on data only through a typed SDK that calls the public API (REQ-WI-018) as a
service identity of the automation that runs it. The admin grants that identity permissions
like a role. Every change it makes is recorded with source "custom function" and the
function's name.

- **Decision:** NEW. ServiceDesk Plus functions act with broad rights.
- **Source:** architecture §11.2 (one policy layer), §3 (P2)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A function whose identity lacks the "delete" permission gets 403 when it tries to delete a
     record.
  2. A change made by a function appears in history with the function's name.
  3. The SDK offers only public API operations.

#### REQ-RUL-021 — Function editor, test runs, logs and versions

Functions are edited in a code editor with syntax highlighting, completion for the SDK, and
snippets for common tasks. An admin can run a function against a chosen record in test mode,
where changes and outbound calls are shown but not made. Each run keeps a log (output, errors,
duration) for a set time. Functions have versions, and an earlier version can be restored.

- **Decision:** BETTER. Adds dry-run test mode and versions to save-and-run.
- **Source:** sdp-area-12 §Fields (custom function: save and execute script), §Config (syntax builder blocks)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A test run against a record shows the changes the function would make and changes nothing.
  2. The last 100 runs of each function are listed with outcome and duration.
  3. Restoring version 3 makes it the active version, recorded in the configuration history.

#### REQ-RUL-022 — Functions as conditions inside the save

A business rule can use a custom function as a condition, as a check that refuses the save, or
as an action that returns field values to set. Because this runs inside the save, it has a
short time budget (Appendix A), and the admin chooses what happens on timeout: skip the rule,
or refuse the save.

- **Decision:** SAME. ServiceDesk Plus allows custom functions in business rule conditions and
  pre-rule actions; ours adds a time budget and a declared failure behaviour.
- **Source:** sdp-area-12 §Fields (business rule conditions by custom function), §Config (use as: pre rule action); sdp-area-14 §Screens (custom functions scoped to business rule)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A function condition that returns within the budget decides whether the rule runs.
  2. A function that exceeds the budget follows the chosen behaviour, and the save never waits
     longer than the budget plus 200 ms.

#### REQ-RUL-023 — No vendor scripting language or block builder

SupportX does not offer the vendor's own scripting language or its block-based script builder.

- **Decision:** SKIP. A proprietary language locks customers in and cannot be reused elsewhere.
  Python and JavaScript functions (REQ-RUL-018) with snippets, plus no-code rules, actions and
  workflows, give the same outcomes. AI help to draft functions comes with file 10.
- **Source:** sdp-area-12 §Fields (custom function language), §Config (syntax builder), §Edition notes; architecture §6.7, §18.2
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. No screen or API accepts code in the vendor's scripting language.
  2. The migration tool lists every ServiceDesk Plus custom function as an item to rebuild by
     hand, with its source text (architecture §18.2).

#### REQ-RUL-024 — Custom menu actions on records

Admins can add custom menu actions to a record type: a named action in the record's action
menu that runs a custom action, a webhook, a function or a workflow, optionally after asking
the user for a few inputs. Each menu action has its own permission and conditions for when it
is offered. It follows the fixed-position rules for actions (REQ-WI-010).

- **Decision:** SAME. ServiceDesk Plus has custom menus.
- **Source:** sdp-area-14 §Screens (developer space: custom menu); architecture §2.5 (custom menu actions), §2.15
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A menu action "Reset VPN token" that asks for a reason and calls a webhook appears only for
     roles that have its permission.
  2. When its conditions are not met, the action is shown disabled with a reason.
  3. The action's outcome is shown to the user and recorded in history.

---

## 13. Testing, audit and safety of automation

#### REQ-RUL-025 — Test and simulate rules

An admin can simulate automation on an existing record or on sample values for a chosen event:
the result lists every business rule, trigger, routing rule, SLA policy and workflow that
would match, in the order of REQ-RUL-006, what each would change, and which would not match
and why. Nothing is saved and nothing is sent.

- **Decision:** NEW. ServiceDesk Plus offers no way to test rules except creating real records.
- **Source:** sdp-area-12 (12b) §Behaviour (execution order inferred from test records), §Weak spots; architecture §2.15
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Simulating "create" with a subject that matches two rules lists both with their changes in
     order.
  2. A simulation sends no notification, makes no webhook call and writes nothing.
  3. Rules that never match because an earlier rule stops processing are flagged.

#### REQ-RUL-026 — Configuration history and restore

Every change to a rule, trigger, schedule, custom action, function, SLA policy, routing rule,
life cycle, workflow or notification rule is versioned: who changed it, when, and a readable
difference. An admin can restore an earlier version. The changes are also written to the audit
log.

- **Decision:** BETTER. ServiceDesk Plus logs that a rule was modified, not what changed, and
  offers no restore.
- **Source:** sdp-area-14 §Screens (audit log: "Modified Trigger (disable)", system log); sdp-area-12 (12b) §Screens (workflow view history); architecture §7.4
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Changing a rule's condition shows a difference with the old and new condition.
  2. Restoring the previous version brings it back and records the restore.
  3. Each change has an audit log entry with actor, time and object.

#### REQ-RUL-027 — Execution log and failure alerts

Each automation keeps a log of its runs: time, record, matched or not, actions run, outcome and
duration. Admins can filter runs by automation, record and outcome. Repeated failures of the
same automation notify its owner and the admins, once per incident of failure, not per run.

- **Decision:** BETTER. ServiceDesk Plus has a system log with rule updates but no run history
  per rule.
- **Source:** sdp-area-14 §Screens (system log); sdp-area-12 (12b) §Screens (workflow log viewer); REQ-WI-009
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A trigger's page lists its last runs with outcome, and links to each record.
  2. Ten failures of the same webhook in an hour send the owner one alert, not ten.
  3. Run logs are kept for the period in Appendix A, then removed.

#### REQ-RUL-028 — Loop protection

Automations cannot loop without limit. A change made by automation can start other
automations, but the chain depth per original change is capped, and the number of automated
changes per record per minute is capped (Appendix A). A trigger never fires on the change its
own action made unless the admin allows it. When a cap is hit, the chain stops, the record
shows why, and the admins are told.

- **Decision:** NEW. Not covered in ServiceDesk Plus's settings.
- **Source:** architecture §6.7, §2.1 (email loop protection); REQ-WI-009
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Two triggers that set each other's field stop at the depth cap, and the record shows a
     loop warning naming both.
  2. A trigger whose action changes the field it watches does not fire again on that change.
  3. Hitting a cap notifies the admins once and writes an entry in the execution log.

#### REQ-RUL-029 — Checked when saved, switched on deliberately

Every automation is validated when it is saved, not when it runs: fields must exist for the
type, actions must be valid for the type, transitions must exist, recipients must resolve and
connections must exist. Automations can be saved as drafts and switched on later. Each has an
owner who is told about its failures.

- **Decision:** BETTER.
- **Source:** sdp-area-12 (12b) §Weak spots (field update fails only at run time), §Behaviour (cannot set approval status for incidents); REQ-WI-009
- **SDP weak spot fixed:** a field update that is invalid for incidents fails only at run time.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Saving a field update that sets a field not on the type is refused, naming the field.
  2. A draft automation never runs.
  3. Deleting a custom field used by an automation is refused, naming the automation.

#### REQ-RUL-030 — Move automation between environments

Rules, triggers, SLA policies, life cycles, workflows, functions and notification templates can
be exported and imported as files, and promoted from a test environment to production with a
preview of the differences (configuration as code). A sandbox copy of a tenant can be used to
try changes first.

- **Decision:** BETTER. ServiceDesk Plus has one cloud sandbox; we add export, import and
  promotion with a difference preview, on every deployment.
- **Source:** sdp-area-14 §Screens (sandbox); architecture §17 (Stage 3: sandbox and config-as-code); product-plan §5 (config-as-code with git and multi-environment promotion)
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. Exporting a workflow and importing it into another tenant gives the same workflow, with
     references to groups and fields matched by name and missing ones listed.
  2. A promotion shows a difference of every automation that will change, before applying.
  3. Connection secrets are never exported.

#### REQ-RUL-031 — Who may change automation

Changing automation is a set of admin permissions, separate per area: SLA policies and
calendars, routing and auto-assignment, business rules and triggers, schedules, custom actions
and webhooks, custom functions and connections, life cycles, workflows, and notification rules
and templates. Each can be granted for the whole tenant or for chosen sites, so a site admin
manages only their site's automation.

- **Decision:** SAME. ServiceDesk Plus has configuration roles (for example help desk and
  project configuration) and a site admin role.
- **Source:** sdp-area-11 §Fields (roles: help desk configuration, project configuration, site admin); architecture §11.2
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A user with "manage SLA policies" but not "manage custom functions" can edit policies and
     gets 403 on functions.
  2. A site admin for site A can edit site A's rules and policies and only view tenant-wide
     ones.
  3. Writing custom functions and connections needs its own permission, never granted by the
     built-in technician role.

#### REQ-RUL-032 — Runbook actions on endpoints

Triggers, workflows and custom menu actions can run approved runbook scripts on endpoints
through AgentX (for example clear a print queue or restart a service), with the output added
to the record as a private note. Only scripts from an approved library can run, each run is
audited, and runs can require an approval first. MonetX stays read-only (D-001): no actions are
sent to network devices through MonetX.

- **Decision:** NEW. ServiceDesk Plus relies on a separate orchestration product, mostly cloud
  only.
- **Source:** product-plan §6 (runbook automation); architecture §2.14 (endpoint and UEM: AgentX); D-001; ADR-017
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A workflow node that runs the approved script "clear print queue" on the incident's asset
     adds the script output to the incident as a private note.
  2. A script not in the approved library cannot be chosen.
  3. Every run is in the audit log with the script, its version, the target and the result.

---

## 14. Life cycles

The default incident life cycle, status categories, reasons, required fields per transition
and the incident life cycle designer are in file 01 (REQ-INC-044 to REQ-INC-052). The
requirements below are the engine they run on, shared by every type.

#### REQ-WF-001 — Life cycles for every work item type

The life cycle engine runs the status machine of every work item type: incidents, service
requests, problems, changes (inside each stage) and releases. Each type ships with a default
life cycle (file 01 for incidents; each module's file for the others). Admins can create more
life cycles per type and attach them to templates.

- **Decision:** BETTER. In ServiceDesk Plus life cycles exist for requests, problems and assets,
  while changes and releases use stage workflows of very different power.
- **Source:** sdp-area-12 §Screens (life cycles: request, problem, asset); sdp-area-04 §Behaviour (major problem life cycle); sdp-area-06 §Weak spots (release workflow weaker than change); architecture §2.1 (request life cycle), §2.3, §6.2
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. The same transition engine and contract tests serve incidents and service requests at MVP,
     and problems, changes and releases when their modules arrive.
  2. A new tenant has a working default life cycle for every enabled type.
  3. A record's allowed transitions come from its template's life cycle on every path
     (REQ-INC-046).

#### REQ-WF-002 — Every template has a life cycle; a workflow works through it

Every template has exactly one life cycle. A template may also have a visual workflow. The
workflow can move the status only through transitions the life cycle allows, so a record never
"violates" its workflow, and a person's transition is an event the workflow reacts to
(REQ-WF-012). The statuses a user is offered always come from the life cycle, so there is no
separate setting for which statuses a workflow shows. The record's actions keep their fixed
places whether or not a workflow is attached (REQ-WI-010).

- **Decision:** BETTER. In ServiceDesk Plus a template has either a life cycle or a workflow,
  hand changes outside the workflow are allowed and flagged "violated", and the close and
  cancel buttons vanish when a life cycle is attached.
- **Source:** sdp-area-12 §Config (template designers: workflow / life cycle picker), (12b) §Actions (close and cancel disappear), §Screens (workflow settings: show all statuses), §Config (template workflow field); sdp-area-05 §Weak spots (manual status changes flagged violated); sdp-area-04 §Weak spots
- **SDP weak spot fixed:** a change shows "violated" after a hand status change, and nothing
  stops it.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A template cannot be saved without a life cycle; the type's default is preselected.
  2. A workflow node that sets a status not reachable by an allowed transition is refused when
     the workflow is saved.
  3. No record ever shows a "violated" state; there is no such state.

#### REQ-WF-003 — Before, during and after a transition

Each transition has three parts:

- **before:** who may run it (REQ-WF-004) and conditions that decide when it is offered;
- **during:** required fields, a reason prompt and an optional confirmation text;
- **after:** custom actions to run once the transition is committed (notification, field
  update, task, webhook, function, start a workflow).

The first transition out of the start state has no "before" part.

- **Decision:** SAME.
- **Source:** sdp-area-12 §Config (life cycle transitions: before, during, after), (12b) §Screens (transition form), §Fields (life cycle scope, mandatory fields); architecture §2.1 (actions before, during and after transitions)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A transition with condition "category is hardware" is offered only on hardware records.
  2. A transition with a required resolution asks only for the resolution (REQ-INC-048).
  3. An "after" notification runs only after the transition is committed, and a failure in it
     does not undo the transition.

#### REQ-WF-004 — Who may run a transition

A transition can be limited to roles, groups and people relative to the record: the requester,
the assignee, the group head, the requester's manager, the department head, the change manager
and approvers. A transition not allowed for a user is shown disabled with the reason, and the
API refuses it with 403.

- **Decision:** SAME.
- **Source:** sdp-area-12 (12b) §Fields (life cycle scope), §Behaviour (scope "group head of request" restricted the transition); sdp-area-11 §Fields (organization roles)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A transition limited to the group head is refused for other group members with 403 and
     shown disabled with the reason.
  2. A transition open to "the requester" can be run from the portal by the requester only.

#### REQ-WF-005 — Life cycle versions and moving records

Life cycles have draft and published versions. A record keeps the version it started with.
When a new version is published, an admin can move open records to it: the tool maps each old
status to a new one, shows how many records each mapping affects, and runs as a background job
with a summary.

- **Decision:** NEW. ServiceDesk Plus has draft and publish but no versions per record or
  migration.
- **Source:** sdp-area-12 §Actions (life cycle: publish, save as draft); REQ-INC-049; architecture §6.6 (versioned metadata)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Publishing version 2 leaves records on version 1 working as before.
  2. Moving records with a status removed in version 2 requires a mapping for that status
     before the job can start.
  3. Each moved record gets one history entry naming both versions.

#### REQ-WF-006 — Validation that says what to fix

Saving or publishing a life cycle checks it and names every problem: a status with no way out,
a status that cannot be reached, a missing resolved or closed status, a transition to a
disabled status. Publishing does not require a template to be attached first; attaching is a
separate step.

- **Decision:** BETTER.
- **Source:** sdp-area-12 §Behaviour (life cycle: orphan stage error), (12b) §Behaviour (publish failed until a template was attached), §Weak spots (publish error does not say a template is needed; template picker disappears)
- **SDP weak spot fixed:** publishing fails without saying that a template is needed, and the
  template picker then disappears.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Saving with an unreachable status names that status.
  2. A life cycle can be published with no template attached, and the attach screen lists the
     templates of its type.
  3. All validation messages are translated and point to the item to fix.

#### REQ-WF-007 — Map view and list view

A life cycle can be viewed and edited as a diagram and as a table of transitions (from, to,
name, who, required fields). Both show the same data and edits in one show in the other.

- **Decision:** SAME. ServiceDesk Plus has map and linear views.
- **Source:** sdp-area-12 (12b) §Screens (life cycles: map view and linear view), §Behaviour (major incident life cycle in linear view)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Adding a transition in the table shows it on the diagram at once.
  2. The table view can be used fully with the keyboard and a screen reader.

---

## 15. Visual workflows

#### REQ-WF-008 — Visual workflow designer

Admins build workflows on a canvas (React Flow): nodes joined by links, with a start and an end.
The designer has a node palette with names and icons, a details panel for the selected node,
zoom, fit to screen, a minimap, undo and redo, and automatic layout. Workflows are stored as a
JSON definition (architecture §6.7).

- **Decision:** SAME. Same capability, original design.
- **Source:** sdp-area-12 §Screens (workflows), §Actions (workflow canvas), (12b) §Screens (designer); architecture §2.1 (visual workflows), §6.7; product-plan §5 (automation)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. An admin can build "start → if → notification → set status → end" by drag and drop and
     save it.
  2. Undo and redo work for every edit, at least 50 steps back.
  3. The saved definition is JSON that re-opens to the same diagram.

#### REQ-WF-009 — Node types

The designer offers these nodes:

- flow: start, end, set status (through a transition);
- logic: if, switch, wait for an event, timer;
- people: approval, task, checklist;
- actions: notification, field update, note, webhook, custom function, any library action;
- structure: sub-flow, parallel split, join.

- **Decision:** BETTER. Adds a real approval node, a sub-flow node and a note node. ServiceDesk
  Plus has no separate approval node in request workflows.
- **Source:** sdp-area-12 §Config (workflow node types: no separate approval node), (12b) §Screens (designer nodes); sdp-area-02b §Behaviour (onboarding workflow node types); sdp-area-05 §Behaviour (standard workflow: decision, notification, task, approval nodes); architecture §6.7 (node types)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Every listed node can be placed, configured and saved.
  2. Each node type has its own contract test against the runtime.
  3. A node that is not allowed for the workflow's record type is not offered.

#### REQ-WF-010 — How a workflow starts

A workflow starts when a record is created from a template that has it, when a trigger or
transition runs "start a workflow", or when a user with permission starts it from the record.
A record runs at most one instance of the same workflow at a time. A workflow has an enabled
switch; disabling it stops new instances and leaves running ones alone.

- **Decision:** BETTER. In ServiceDesk Plus a workflow starts only from its template and has no
  on/off switch.
- **Source:** sdp-area-12 (12b) §Screens (workflow list: no enable switch), §Config (template workflow field), §Behaviour (instance created at request creation)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Creating a record from a template with workflow W starts one instance, and history says
     so.
  2. A trigger can start workflow W on an existing record; starting it again while it runs is
     refused with a reason.
  3. Disabling W stops new starts and leaves running instances running.

#### REQ-WF-011 — Conditions and switches

An if node has a condition built with the shared filter grammar or a custom function, and yes
and no outputs. A switch node has several outputs by value or condition, and a default output.

- **Decision:** SAME.
- **Source:** sdp-area-12 §Config (workflow condition nodes: if, wait for, switch), (12b) §Screens (if node operators), §Fields (if node), §Behaviour (if node worked)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. An if node on "priority is P1" takes the yes output for P1 records and the no output for
     others.
  2. A switch on category with three cases and a default always takes exactly one output.

#### REQ-WF-012 — Waiting for events, and people working alongside

A wait node pauses the workflow until an event happens on the record or its parts (a field or
status change, a note, a requester reply, an approval decision, a task or checklist completed,
a worklog added), optionally with a condition and a time limit with its own output. If a
person makes the change the workflow is waiting for, the wait completes. If a person changes
the status so that the wait can no longer complete, the workflow takes the node's "overtaken"
output; it is never silently dropped.

- **Decision:** BETTER. In ServiceDesk Plus a hand status change discards the waiting step, so
  later steps never run.
- **Source:** sdp-area-12 (12b) §Screens (wait for: applies to), §Fields (wait for), §Behaviour (wait for discarded), §Weak spots (wait for discarded); REQ-INC-046
- **SDP weak spot fixed:** a manual status change throws away a waiting step and leaves the
  workflow stuck.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A wait for "status is in progress" completes when a technician moves the record to in
     progress by hand.
  2. A wait whose target status becomes unreachable takes the "overtaken" output, and the record
     shows which node was overtaken.
  3. A wait with a 2-day limit takes the timeout output after 2 days with no event.

#### REQ-WF-013 — Timer nodes

A timer node waits a duration or until a date field of the record, in business or calendar
time, and can pause while the record is paused. It can run actions at up to two levels before
moving on, and be cancelled by conditions.

- **Decision:** SAME.
- **Source:** sdp-area-12 (12b) §Screens (timer node), §Fields (timer), §Limits (timer node not proven in a workflow)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A timer "until scheduled start minus 1 day" moves on 1 day before the record's scheduled
     start.
  2. A business-time timer does not count holidays.
  3. A timer inside a workflow is covered by an automated test (the research could not prove
     one).

#### REQ-WF-014 — Approval nodes

An approval node asks for approval using the engine's approvals (REQ-INC-083): approvers by
name, role, group or relation to the record, a rule (any one, all, majority, first answer),
several levels, reminders, and approved, rejected and timed-out outputs. The pending approval
shows on the record with every approver and their state.

- **Decision:** BETTER. Request workflows in ServiceDesk Plus set an approval status field
  instead of using an approval node, and pending approvals cannot be seen without mail.
- **Source:** sdp-area-12 §Config (no separate approval node), §Fields (approval action rules); sdp-area-02b §Behaviour (workflow waiting at approval, not visible); sdp-area-05 §Behaviour (review approval node); architecture §6.7
- **SDP weak spot fixed:** the workflow waits at an approval nobody can see or act on.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A two-level approval node waits for level 1, then level 2, and takes the approved output
     after both approve.
  2. A rejection at level 1 takes the rejected output and level 2 is never asked.
  3. With no mail server, approvers can act in the app and the workflow continues.

#### REQ-WF-015 — Notification, field update, note, task and checklist nodes

- A notification node sends a template through the notification engine to chosen recipients.
- A field update node sets fields (validated for the record type when saved).
- A note node adds a public or private note from a template.
- A task node creates a task or a task template, and can wait for it with completed, overdue
  and canceled outputs; a checklist node adds a checklist and can wait for it.

- **Decision:** SAME. Task nodes with completed and overdue exits exist in ServiceDesk Plus
  change workflows.
- **Source:** sdp-area-12 §Config (action nodes), (12b) §Screens (field update node); sdp-area-05 §Behaviour (task nodes with completed and overdue exits, notification node with merge fields); sdp-area-02b §Behaviour (wait for task completion)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A task node waiting for completion moves on when the task is completed, and takes the
     overdue output when the task passes its due date.
  2. A field update node that sets a field the type does not have cannot be saved.
  3. A notification node uses the recipient's language (REQ-INC-133).

#### REQ-WF-016 — Webhook and custom function nodes

Webhook and function nodes run the same actions as triggers (REQ-RUL-014, REQ-RUL-018). Their
result can be stored in workflow variables and used by later nodes, and they have success and
error outputs.

- **Decision:** SAME, plus workflow variables.
- **Source:** sdp-area-12 §Config (action nodes: custom function, webhook), §Actions (alternate path on error)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A webhook node stores a returned ID in a variable, and a later note node includes it.
  2. A function node that fails takes its error output.

#### REQ-WF-017 — Sub-flows

A sub-flow node runs another workflow as a step and waits for it to finish, passing inputs and
receiving outputs. A shared sub-flow (for example "manager approval then notify") is defined
once and reused.

- **Decision:** NEW. ServiceDesk Plus workflows cannot call other workflows.
- **Source:** architecture §6.7 (sub-workflow node)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A workflow calling sub-flow S runs S and continues with S's outputs.
  2. Calling a sub-flow that calls the parent again is refused when saved (no recursion).
  3. The execution view lets the user open the sub-flow's run from the parent.

#### REQ-WF-018 — Parallel branches

A parallel split starts several branches at once; a join waits for all of them, or for the
first, or for a set number, as the admin chooses.

- **Decision:** SAME. ServiceDesk Plus has fork and join.
- **Source:** sdp-area-12 §Config (branch nodes: fork, join); sdp-area-02b §Behaviour (task split)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A split into "IT tasks" and "HR tasks" with a join "wait for all" continues only after both
     branches finish.
  2. A join "wait for first" continues after the first branch and cancels the others, with
     history showing which were cancelled.

#### REQ-WF-019 — Validation when saved

Saving a workflow checks it and names every problem: unconnected nodes, a missing path to the
end, nodes not valid for the type, conditions on missing fields, waits that can never finish,
a join without a split. Drafts with problems can be saved as drafts; only valid workflows can
be published.

- **Decision:** BETTER. ServiceDesk Plus's validation is strict on the end node, and the
  research could not save a workflow because of it.
- **Source:** sdp-area-12 §Config (validation rules), §Behaviour (saving failed), §Weak spots (end-node validation strict); sdp-area-12 (12b) §Screens (validation on save)
- **SDP weak spot fixed:** the end-node rule blocks saving, and the message does not lead to the
  fix.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A workflow with an unconnected node can be saved as a draft but not published, and the
     node is highlighted.
  2. Every validation message selects the node it is about when clicked.
  3. Any node can link to the end; there is no rule on which node types may reach it.

#### REQ-WF-020 — Durable workflow runtime

Each workflow instance runs durably on the workflow engine (Temporal, ADR-004): it survives
restarts, upgrades and failovers, and continues for days or months. Each node runs at least
once and its effects happen once.

- **Decision:** NEW. Engineering requirement.
- **Source:** architecture §6.7; ADR-004; D-038 (11)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Restarting all workers while 1,000 instances wait on timers loses none, and each timer
     fires once.
  2. A notification node interrupted by a crash sends its notification exactly once.
  3. The same workflow tests pass on single-node on-prem and on SaaS.

#### REQ-WF-021 — Workflow versions and safe migration of running instances

Saving a published workflow creates a new version. Running instances stay on their version.
An admin can move running instances to a new version with a node mapping (old node → new node),
a preview of how many instances sit at each node, and a dry run. Instances that cannot be
mapped stay on their old version and are listed.

- **Decision:** NEW. ServiceDesk Plus has no versions for workflows.
- **Source:** architecture §6.7; ADR-004 (workflow versioning needs discipline); sdp-area-12 (12b) §Screens (workflow list: view history)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Publishing version 2 leaves 50 running version-1 instances on version 1.
  2. A migration with a mapping for every occupied node moves all 50 and records it on each
     record.
  3. A dry run reports what would move and changes nothing.

#### REQ-WF-022 — Simulate and test a workflow

An admin can run a workflow in test mode against a chosen record or sample values. Test mode
steps through nodes, shows variables and decisions, and lets the admin answer waits and
approvals by hand. Notifications, webhooks and functions are shown, not sent or run, unless the
admin allows a live call for one node.

- **Decision:** NEW. ServiceDesk Plus has no workflow test mode.
- **Source:** sdp-area-12 §Limits (workflow not saved or run), (12b) §Limits (timer node not proven); architecture §6.7
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A test run of a workflow with an approval node lets the admin choose "approved" and shows
     the path taken.
  2. A test run sends no notification and writes nothing to the record.
  3. A test run can fast-forward timers.

#### REQ-WF-023 — Execution view on the record

From the record, a user with permission can open the running workflow: the diagram with the
path taken highlighted, the current node marked, and a log of each step (node, result, start
and end time, duration, who acted). It updates live.

- **Decision:** SAME. ServiceDesk Plus has an execution view with highlighted path and a log
  viewer.
- **Source:** sdp-area-12 (12b) §Screens (execution view, log columns); sdp-area-02b §Screens (workflow execution view); sdp-area-05 §Screens (workflow execution view)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Approving a pending approval moves the marker to the next node in the open execution view
     within 1 second.
  2. The log lists every node run with times to the second.
  3. Requesters never see the execution view; the portal shows only the record's status.

#### REQ-WF-024 — Errors are handled and visible

Each action node has a retry policy (attempts, backoff) and an error output. If a node fails
after its retries and has no error output, the instance stops at that node. The record shows a
banner naming the step and the error, the owner and the workflow's owner are notified, and a
user with permission can retry the step, skip it or cancel the workflow.

- **Decision:** BETTER. In ServiceDesk Plus a failed mail node stalls the workflow silently
  behind a small red marker.
- **Source:** sdp-area-05 §Behaviour (failed notification node stalled the flow), §Weak spots; sdp-area-02b §Weak spots (stuck workflow shows only a red dot); sdp-area-12 §Actions (alternate path on error), (12b) §Behaviour (failed action did not block the manual path); REQ-WI-009
- **SDP weak spot fixed:** a failed step stalls the flow with only a red dot to show it.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A webhook node that fails three times with no error output stops the instance, and the
     record shows a banner naming the node.
  2. "Retry" runs the node again; "skip" moves to its next node; both are recorded with the
     user's name.
  3. A failed notification does not stop the workflow when the node is set to "continue on
     failure".

#### REQ-WF-025 — Overview of running and failed instances

Admins have a screen listing workflow instances by workflow, state (running, waiting, failed,
finished, cancelled), current node and age, with filters and bulk retry or cancel for failed
ones. It updates live.

- **Decision:** NEW. ServiceDesk Plus shows instance state only per record.
- **Source:** sdp-area-12 (12b) §Screens (execution view per record); architecture §15 (operations)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. The screen lists all failed instances with their node and error, and a filter by workflow.
  2. Bulk retry of 20 failed instances runs as a background job and reports each result.
  3. Instances waiting more than a set time at one node can be listed.

#### REQ-WF-026 — Stop, detach or restart a workflow on a record

A user with permission can stop a running workflow on a record, with a reason, or restart it
from the start or from a chosen node. Stopping keeps the execution log; the record keeps
working through its life cycle.

- **Decision:** BETTER. ServiceDesk Plus's "revoke workflow" clears the execution log.
- **Source:** sdp-area-02c §Behaviour (revoke workflow clears its execution log), §Actions (revoke workflow), §Screens (workflow execution view)
- **SDP weak spot fixed:** revoking a workflow erases its log.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Stopping a workflow asks for a reason, and the log stays readable afterwards.
  2. Restarting from a chosen node runs from that node, and history records it.
  3. A canceled record's workflow is stopped automatically, and undoing the cancel offers to
     resume it.

#### REQ-WF-027 — Copy, export and history of workflows

Workflows can be copied, exported as a file and imported. Each workflow lists its versions with
who changed them and when (REQ-RUL-026). The list shows name, type, attached templates,
version, state and number of running instances.

- **Decision:** SAME. ServiceDesk Plus has copy, view history and export history.
- **Source:** sdp-area-12 §Screens (workflows: export history), (12b) §Actions (workflow list gear menu: edit, delete, view history, copy)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Copying a workflow creates an independent draft with " (copy)" in its name.
  2. Exporting and importing a workflow in the same tenant gives an identical definition.
  3. A workflow with running instances cannot be deleted; it can be disabled.

#### REQ-WF-028 — A designer that is easy to use

The designer works by keyboard and pointer: connection handles are always visible, a link can
be added from a node's menu as well as by dragging, and selected links have a clear delete
action. Node categories are labelled with text, not only icons. The canvas works in
right-to-left layout and with a screen reader through an outline view of nodes and links.

- **Decision:** BETTER.
- **Source:** sdp-area-12 §Weak spots (link-delete control hard to hit, add node menu icon-only), (12b) §Weak spots (hover-only link dots; a missed drag moves the node); architecture §9.4
- **SDP weak spot fixed:** link dots appear only on hover, and a missed drag moves the node
  instead.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. An admin can add a node, link it and delete a link using only the keyboard.
  2. The automated accessibility check reports no serious issues on the designer.
  3. In Arabic the canvas lays out right to left and labels are translated.

#### REQ-WF-029 — Limits that keep workflows safe

Workflows may contain loops (for example "ask again until approved"), but every loop has a
maximum number of rounds, and a workflow has a maximum number of nodes and steps per instance
(Appendix A). Hitting a limit stops the instance as failed, with the reason shown.

- **Decision:** NEW.
- **Source:** architecture §6.7; REQ-RUL-028
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A loop that would run a 101st round stops with a "loop limit" failure on the record.
  2. Saving a workflow above the node limit is refused with the limit named.

#### REQ-WF-030 — Draft a workflow from a description

An admin can describe a workflow in words (in English, Arabic or Urdu) and get a draft
workflow on the canvas to review and edit. Nothing is published without the admin. The AI
gateway and its model access are in file 10 (D-049).

- **Decision:** SAME. The vendor offers workflow drafting from text, voice or an image.
- **Source:** product-plan §6.1 (visual workflow builder with AI-assisted creation), §7.2 (phase 1: AI workflow drafting from text); sdp-area-10 §Screens (workflow editor); D-049
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. "When a P1 network incident is created, notify the network head and wait 30 minutes for
     an update" produces a draft with a trigger condition, a notification node and a timer.
  2. The draft is saved as a draft only, and the admin can edit every node.

#### REQ-WF-031 — Workflows for other records

Workflows can also run on records outside the work item engine: assets (for example a
hardware life cycle from purchase to disposal), configuration items, contracts and knowledge
articles, using the same designer and runtime.

- **Decision:** SAME. ServiceDesk Plus offers asset workflows.
- **Source:** sdp-area-12 §Screens (workflows: module switch includes asset); product-plan §5 (IT asset: lifecycle workflows)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. An asset workflow can wait for the asset's state to change and create a task.
  2. The same runtime tests pass for an asset workflow as for a work item workflow.

---

## 16. Notification engine: events, channels and rules

The incident events, their defaults, the notification centre, the incident template rules,
the recipient's language and the log on the incident are in file 01 (REQ-INC-130 to
REQ-INC-134). The requirements below are the engine that every module uses.

#### REQ-NTF-001 — One notification engine for every module

Every module sends notifications through one engine (architecture §6.8). Each module registers
its notification events with a label, the variables they offer and the recipients that make
sense. The engine resolves recipients, picks the template and language, applies preferences,
digests, quiet hours and throttling, sends through channel adapters, and records delivery.
Modules never send mail or messages themselves.

- **Decision:** BETTER. ServiceDesk Plus configures notifications separately in each module's
  tab, with different behaviour per module.
- **Source:** sdp-area-12 (12b) §Screens (notification rules tabs per module); architecture §6.8; REQ-WI-019
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A new module's events appear in the notification rules screen after it registers them,
     with no change to the engine.
  2. An architecture test finds no module other than notifications that sends mail directly.
  3. A notification is created only from a committed event; a rolled-back change sends nothing.

#### REQ-NTF-002 — Email channel

Email notifications go out through the tenant's outgoing mail set-up (SMTP or Microsoft Graph or
the Gmail API; mailbox connections are REQ-INT-050 to REQ-INT-055 in file 12), as HTML with a plain-text part. They carry the record's thread token
so replies thread into the record (REQ-INC-024), and standard headers that mark them as
automatic.

- **Decision:** SAME.
- **Source:** sdp-area-13 §Mail (outgoing settings); architecture §6.8 (channel adapters), §2.1 (loop protection)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A resolution email has an HTML part and a plain-text part with the same content.
  2. Replying to it adds the reply to the right record.
  3. Each email carries an "auto-generated" header so well-behaved mail systems do not answer
     it.

#### REQ-NTF-003 — In-app channel for every module

In-app notifications are available for every module's events, delivered live to the user's
notification centre (REQ-INC-131) through the user's realtime channel, and kept for a set time
(Appendix A). They work with no mail set up.

- **Decision:** SAME.
- **Source:** sdp-area-01 §Screens (notifications drawer); architecture §8.1 (user channel); REQ-INC-131
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A change approval request reaches the approver's notification centre within 1 second.
  2. A user who was offline sees missed in-app notifications when they return.
  3. In-app entries older than the retention period are removed automatically.

#### REQ-NTF-004 — Browser notifications

A user can allow desktop notifications in the browser for chosen events, so urgent items (for
example a P1 assignment) show even when the SupportX tab is in the background. The content is
short and contains no sensitive data.

- **Decision:** NEW. ServiceDesk Plus does not offer browser notifications.
- **Source:** architecture §8 (real-time everywhere), §9.1
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. With browser notifications allowed, a P1 assignment shows a desktop notification while
     the tab is in the background; clicking it opens the record.
  2. The notification shows the display ID and a short title only, never the description.

#### REQ-NTF-005 — Mobile push

Users of the mobile app (REQ-INC-149) get push notifications for the events they choose.
Pushes open the record in the app. Lock-screen text never contains sensitive data; the app
fetches details after unlock.

- **Decision:** SAME. ServiceDesk Plus offers mobile push per rule.
- **Source:** sdp-area-12 (12b) §Screens (rule layout: email, SMS, mobile push); architecture §6.8, §2.15 (mobile apps with push); REQ-INC-149
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. An approval request push opens the approval in the app.
  2. The push payload sent to the push service contains only IDs and a short title.
  3. A user who loses access to the record gets no further pushes about it.

#### REQ-NTF-006 — Text messages through a gateway

A tenant can connect an SMS gateway and use text messages for chosen urgent events, for example
P1 assignment and SLA breach. Texts are short and contain no sensitive data.

- **Decision:** SAME, through a gateway only.
- **Source:** sdp-area-12 §Fields (notification action mode: email or SMS); sdp-area-14 §Screens (SMS settings: mobile service or SMS gateway); architecture §6.8 (SMS adapter)
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. With a gateway connected, a P1 assignment sends the assignee a text within 1 minute.
  2. Text sending counts against a tenant limit set through the entitlement interface.

#### REQ-NTF-007 — No email-to-SMS carrier addresses

SupportX does not send texts through carrier email-to-SMS addresses stored on user profiles.

- **Decision:** SKIP. Most carriers have closed these gateways, and delivery cannot be checked.
  Texts go through an SMS gateway (REQ-NTF-006), and urgent alerts also go by push and
  browser notifications.
- **Source:** sdp-area-11 §Fields (SMS mail ID); sdp-area-14 §Screens (SMS settings: mobile service)
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. User profiles have no email-to-SMS field.
  2. The migration tool reports SMS mail IDs found in ServiceDesk Plus as not migrated, with
     the reason.

#### REQ-NTF-008 — Notification rules per module and event

For each module, admins see every notification event in one list. For each event they set:

- on or off;
- recipients (REQ-NTF-009);
- channels per recipient kind;
- the template per channel;
- conditions (for example only for P1 and P2, or only for VIP requesters).

Defaults ship on for a sensible set (file 01 Appendix A for incidents; each module's file for
its own).

- **Decision:** BETTER. Same shape as ServiceDesk Plus, with conditions and with defaults that
  need no generation step.
- **Source:** sdp-area-12 (12b) §Screens (notification rules: rule layout, recipients, defaults), §Weak spots; sdp-area-05 §Config (notifications per change status); REQ-INC-130
- **SDP weak spot fixed:** the rules screen cannot be opened until a one-time, irreversible
  template generation step is done.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A new tenant can open the rules screen with no set-up step and sees every event with its
     default state.
  2. An event limited to "priority is P1" notifies for P1 records only.
  3. Turning an event off is audited and takes effect for the next event.

#### REQ-NTF-009 — Recipients, including people relative to the record

Recipients can be:

- people relative to the record: requester, on-behalf-of person, assignee, previous assignee,
  group members, group head, followers, "keep informed" addresses, approvers, task owners,
  requester's manager, change manager and other module roles;
- specific users, groups, roles and user groups;
- fixed external email addresses.

One person reached by several paths gets one message per event.

- **Decision:** SAME, with de-duplication made explicit.
- **Source:** sdp-area-12 (12b) §Screens (recipients); sdp-area-12 §Fields (notification action: notify recipients); REQ-INC-066
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A user who is both the assignee and a follower gets one message for a status change.
  2. An event sent to "group members" reaches the members at the time of sending, not when the
     rule was saved.
  3. The person who made the change is not notified unless they opted in (REQ-INC-130).

#### REQ-NTF-010 — Access is checked when sending

Before each message is sent, the engine checks that the recipient may still see the record and
each part of the message. Private notes, internal fields and fields hidden from the recipient's
role (REQ-WI-016) never reach them, whatever the template says. Requesters only get public
content.

- **Decision:** NEW. The research found no such guarantee in ServiceDesk Plus.
- **Source:** architecture §11.2 (one policy layer), §8.2; REQ-INC-130
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A template that includes the latest note sends a requester the latest public note, never a
     private one.
  2. A user who lost access between the event and the send gets nothing, and the log says so.
  3. A field hidden from a role is rendered empty for recipients with that role.

---

## 17. Templates and languages

#### REQ-NTF-011 — Template editor

Each event has a template per channel: subject and rich body for email, short text for in-app,
push and text messages. Admins insert variables from a picker grouped by object (record,
requester, assignee, SLA, approval, links), never by typing raw names. Templates can use simple
conditions and lists (for example "if the record has an asset, show it"), and a shared header
and footer per tenant. Each email template can be HTML or plain text. Templates run in a
sandbox (architecture §6.8) and can reach only the event's variables.

- **Decision:** BETTER. Same variable insertion as ServiceDesk Plus, plus conditions, shared
  layout and sandboxing.
- **Source:** sdp-area-12 §Fields (notification action: subject, message, variables), (12b) §Screens (template editor, rich text toggle); architecture §6.8 (sandboxed Jinja2 templates)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Choosing "requester → name" from the picker inserts a variable that renders the
     requester's name.
  2. A template that tries to reach anything outside its variables fails to save with a clear
     message.
  3. A template with an unknown variable cannot be saved, and the message names it.
  4. Changing the shared footer changes every template that uses it.

#### REQ-NTF-012 — Preview and test send

An admin can preview a template against a real record they may see, in each language and on
each channel, and send a test to themselves. Previews show missing values clearly.

- **Decision:** BETTER.
- **Source:** sdp-area-12 (12b) §Screens (template editor); REQ-INC-132
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Previewing against INC-12 in Arabic shows the Arabic template with INC-12's values, right
     to left.
  2. A test send reaches only the admin, marked as a test.
  3. A variable with no value on the chosen record is highlighted in the preview.

#### REQ-NTF-013 — Default templates for every module, with versions and reset

Every module ships default templates for each of its events, ready to use with no generation
step. Each template edit creates a version; an admin can compare versions, restore one, or reset
to the shipped default. When a product upgrade improves a default, tenants that changed the
template keep theirs and are told an update exists.

- **Decision:** BETTER. ServiceDesk Plus generates templates once, irreversibly, in one language.
- **Source:** sdp-area-12 (12b) §Screens (notification templates generation), §Weak spots; REQ-INC-132
- **SDP weak spot fixed:** templates come from a one-time, irreversible step that does not say
  it is irreversible.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A new tenant has default templates for every event of every enabled module.
  2. Restoring version 2 of a template makes it active and records who did it.
  3. After an upgrade with a new default, a changed template is kept and marked "new default
     available".

#### REQ-NTF-014 — Notifications in English and Arabic, Urdu from V1

Each template exists per language. English and Arabic ship at MVP and Urdu at V1 (D-048). Each
message uses the recipient's language and time zone (REQ-INC-133), with right-to-left layout
for Arabic and Urdu. If a tenant's template has no version in the recipient's language, the
tenant's default language is used and the admin is told which templates lack a translation.

- **Decision:** NEW. ServiceDesk Plus generates templates in a single chosen language.
- **Source:** D-048; D-006; architecture §6.8 (per-locale variants), §9.5; REQ-INC-133
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Every shipped template has English and Arabic versions at MVP, checked in CI, and Urdu from
     V1.
  2. An Arabic email renders right to left in common mail clients, with dates in the
     recipient's zone and format.
  3. The template list shows, per language, which templates are missing.

#### REQ-NTF-015 — Branding and sender identity

Emails use the tenant's branding (logo, colours) from tenant branding (D-027). The sender name
and address can be set per tenant, per group and per mailbox, so replies go to the right
mailbox. A group's sender address must belong to a configured mailbox.

- **Decision:** SAME. ServiceDesk Plus has group mail settings with sender name and address.
- **Source:** sdp-area-11 §Fields (technician group form: group mail settings); sdp-area-13 §Mail (sender's name, reply-to); D-027
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A notification about a record in the network group is sent from the network group's
     address.
  2. Saving a group sender address that is not a configured mailbox is refused.
  3. Changing the tenant logo changes it in every email template.

---

## 18. Preferences, digests and quiet hours

#### REQ-NTF-016 — Personal notification preferences

Each user can choose, per event category and channel, whether they want a notification, within
what the tenant allows. The tenant marks some events as required (for example approvals and
assignments), which users cannot switch off. Preferences follow the user to every device.

- **Decision:** NEW. ServiceDesk Plus has only a notification on/off toggle in the drawer.
- **Source:** sdp-area-01 §Screens (notifications drawer toggle); architecture §6.8
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A technician who turns off email for "note added" still gets it in-app.
  2. A required event cannot be turned off; the setting shows locked with the reason.
  3. Preferences changed on one device apply on every device at once.

#### REQ-NTF-017 — Digests

Users can choose a digest for chosen events: instead of one message per event, one summary
per hour or per day at a chosen time, grouped by record. Urgent events are never held for a
digest.

- **Decision:** NEW. ServiceDesk Plus has no digests.
- **Source:** architecture §6.8 (digests and throttling)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A user on a daily 08:00 digest for "record updated" gets one email at 08:00 listing the
     previous day's updates, grouped by record.
  2. A P1 assignment still arrives at once for that user.
  3. A digest with nothing in it is not sent.

#### REQ-NTF-018 — Quiet hours and urgency

Users can set quiet hours (for example 20:00–07:00 in their time zone, and their days off).
Non-urgent email, push and text messages are held and delivered at the end of quiet hours;
in-app entries still arrive. Each event has an urgency (normal or urgent, set by the admin per
rule and condition, for example P1 or major incident), and urgent messages are never held.

- **Decision:** NEW.
- **Source:** architecture §6.8; REQ-INC-131 (do-not-disturb)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A normal notification at 22:00 for a user with quiet hours 20:00–07:00 is delivered at
     07:00.
  2. An urgent P1 assignment at 22:00 is delivered at once.
  3. Quiet hours follow the user's time zone, including daylight-saving changes.

#### REQ-NTF-019 — Repeat reminders for pending actions

The engine sends repeat reminders for things waiting on a person: approvals, requester
confirmation of a resolution, tasks due, unanswered requester questions. A reminder schedule
sets when to start, how often, at what time of day, for how many times, in business time
(Appendix A). Each module chooses which of its events use reminders; approval reminder
settings are in file 02.

- **Decision:** SAME. ServiceDesk Plus has approval reminders on business days.
- **Source:** sdp-area-13 §Advanced Portal Settings (approval reminder); architecture §2.2 (approvals: reminders), §2.5 (approval reminders)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A pending approval with the default schedule reminds the approver after 2 business days at
     10:00, daily, at most 3 times.
  2. Reminders stop as soon as the person acts.
  3. Reminders respect quiet hours and preferences.

---

## 19. Delivery, failures and protection

#### REQ-NTF-020 — Delivery status, retries and resend

Each message has a delivery state: queued, sent, delivered (where the channel reports it),
deferred, failed, bounced or suppressed, with the reason. Temporary failures are retried with
backoff (Appendix A), then marked failed. Failed messages show on the record's log
(REQ-INC-134), and a user with permission can resend one. When a channel is down (for example
mail not configured), messages wait in the queue and a banner tells admins.

- **Decision:** BETTER. In ServiceDesk Plus, with mail not set up, nothing is sent and nothing
  says so on the record.
- **Source:** sdp-area-12 §Behaviour (blocked by no mail server), (12b) §Edition notes; sdp-area-02c §Weak spots; REQ-INC-059; REQ-INC-060
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A message that fails with a temporary error is retried on the backoff schedule and then
     marked failed with the last error.
  2. "Resend" on a failed message sends it again and records who resent it.
  3. With no outgoing mail configured, email messages are queued, in-app messages go out, and
     admins see a banner with the number waiting.

#### REQ-NTF-021 — Bounces

The engine reads bounce reports from the mail channel. A hard bounce marks the address
undeliverable; repeated soft bounces do the same after a threshold (Appendix A). Undeliverable
addresses stop receiving email, the user's profile shows a warning, and admins see a list to
fix. Fixing or confirming the address clears the flag.

- **Decision:** NEW. Not seen in ServiceDesk Plus.
- **Source:** architecture §6.8; sdp-area-13 §Mail
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A hard bounce for a requester's address marks it undeliverable within 5 minutes of the
     bounce arriving.
  2. Messages to an undeliverable address are recorded as "suppressed", not sent.
  3. Editing the address clears the flag and sending resumes.

#### REQ-NTF-022 — Throttling and storm protection

The engine protects people and mail servers from floods:

- per recipient: past a set number of messages in a window, further ones are combined into one
  summary;
- per record: many changes in a short time (for example a field edited five times in a minute)
  become one message;
- bulk actions and imports: one summary per recipient instead of one message per record;
- per tenant: a sending rate limit, with excess queued, never dropped.

Urgent messages are never combined.

- **Decision:** NEW.
- **Source:** architecture §6.8 (digests and throttling), §8.4 (coalescing bursts)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A bulk assignment of 300 incidents to one technician sends them one summary message
     listing the 300, not 300 messages.
  2. Five edits to one record within a minute give each recipient one message with all the
     changes.
  3. A tenant over its sending rate has its messages delayed, and none is lost.

#### REQ-NTF-023 — No mail loops and no notifications to robots

The engine does not send notifications to automatic senders: messages that arrive with
auto-reply or bulk headers, out-of-office replies, and addresses on the tenant's junk list do
not get acknowledgements. Replies from such senders are added to the record without
notifying. A per-address rate cap stops two systems from answering each other forever.

- **Decision:** SAME. ServiceDesk Plus has a junk notification filter.
- **Source:** sdp-area-12 (12b) §Screens (junk notification filter); architecture §2.1 (loop protection), §6.8; REQ-INC-026
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. An out-of-office reply to a notification is added to the record and triggers no new
     notification.
  2. A new incident from an address marked automatic gets no acknowledgement.
  3. Two mail systems answering each other stop after the per-address cap, and admins are told.

#### REQ-NTF-024 — Secure action links

Notifications can carry action links (approve, reject, confirm resolution, not fixed, take
survey). Each link is signed, bound to its recipient and action, works once, and expires
(Appendix A). Using a link shows a confirmation page; actions that need more input ask for it
there. A used or expired link explains what happened and offers to sign in.

- **Decision:** BETTER. Defines the safety rules for links that the research could not test.
- **Source:** REQ-INC-096 (links work once and expire); REQ-INC-083; architecture §11; sdp-area-02c §Behaviour (approvals blocked without mail)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. An approval link used once approves; using it again shows "already used" and changes
     nothing.
  2. A link forwarded to another person cannot be used by them without signing in as the
     intended recipient, when the tenant requires it.
  3. An expired link shows the expiry and a sign-in link.

#### REQ-NTF-025 — Send a notification by hand

From a record, a user with permission can send a notification using a template or free text,
to chosen recipients (for example "notify the technicians of all linked incidents"). The
message is recorded on the record.

- **Decision:** SAME. ServiceDesk Plus has "send notification" and "notify incident
  technicians or requesters" on problems and changes.
- **Source:** sdp-area-04 §Actions (notify: send notification, notify incident technicians, notify incident requesters), §Behaviour; sdp-area-02c §Actions (notify: email or SMS the technician); sdp-area-06 §Actions (send notification)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Sending "notify requesters of linked incidents" from a problem reaches each linked
     incident's requester once, in their language.
  2. The sent message appears in the record's timeline under the system filter.

#### REQ-NTF-026 — Group notifications without hidden switches

A group can subscribe its members, or only its head, to group events: new record in the group,
record left unpicked for N minutes, record in the group updated. These settings work on their
own and do not depend on a separate global switch. If a tenant-level rule turns an event off,
the group page says so.

- **Decision:** BETTER. In ServiceDesk Plus group notifications silently depend on global
  notification rules.
- **Source:** sdp-area-11 §Fields (technician group form: group notifications), §Automation (group notifications depend on global rules)
- **SDP weak spot fixed:** group notification boxes do nothing unless the global rule is also
  on, with only a warning to explain it.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Turning on "new record in the group" for group A notifies group A's members when a record
     arrives, with no other setting.
  2. If the tenant turned the event off, the group page shows it as off with the reason.

#### REQ-NTF-027 — Alerts to admins about the platform

Admins are notified about problems they must fix: outgoing mail failing, a mailbox not
polling, a bounce surge, automation failures (REQ-RUL-027), workflow instances failing
(REQ-WF-024), webhooks and connections broken, loop caps hit, entitlement limits near. Each
alert is sent once per problem and again only if it continues, and it clears when fixed.

- **Decision:** NEW. ServiceDesk Plus shows such problems only in logs or on the affected
  screen.
- **Source:** sdp-area-14 §Screens (system log), §Weak spots; architecture §15; REQ-WI-009
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Outgoing mail failing for 10 minutes sends admins one alert; it is not repeated every
     minute.
  2. When mail works again, the alert is marked resolved and admins are told.

#### REQ-NTF-028 — Delivery log and metrics for admins

Admins can search all notifications sent by the tenant: by recipient, record, event, channel,
state and time, with the rendered content visible to those allowed to see it. Volumes, failure
and bounce rates per channel feed the operations dashboard and reports (file 09). The log is
kept for a set time (Appendix A).

- **Decision:** NEW. ServiceDesk Plus shows notifications only on the record.
- **Source:** sdp-area-02c §Screens (auto notifications filter); architecture §15; REQ-INC-134
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Searching by a requester's address lists every message sent to them in the retention
     period, with state.
  2. The failure rate per channel for the last 24 hours is shown and matches the log.
  3. Entries older than the retention period are removed automatically.

---

## Appendix A — Proposed defaults (for product owner approval)

These are the defaults a new tenant gets. They are seed data, not fixed behaviour: an admin can
change every one of them per tenant (D-041). The requirements above refer to this appendix.

**Default operating-hours calendar** (REQ-SLA-010): Monday to Friday, 09:00–18:00, in the
tenant's time zone. At onboarding the admin is offered a Sunday-to-Thursday 08:00–17:00
calendar instead. An "around the clock" calendar always exists. The holiday list starts empty,
with a prompt to import holidays (REQ-SLA-012).

**Default incident SLA policy** (REQ-SLA-005), the fallback policy (REQ-SLA-003):

| Priority | First response | Resolution | Calendar |
|---|---|---|---|
| P1 | 15 minutes | 4 hours | around the clock |
| P2 | 30 minutes | 8 business hours | operating hours |
| P3 | 4 business hours | 3 business days | operating hours |
| P4 | 8 business hours | 5 business days | operating hours |

A business day is one day of the calendar's operating hours.

**Default service request SLA policy:** first response 8 business hours, fulfilment 5 business
days, operating hours. Service request SLA source (REQ-SLA-008): the catalog item's SLA if it
has one, else conditions.

**Warning point** (REQ-SLA-019): 75 % of each target.

**Default escalation levels** (REQ-SLA-022, REQ-SLA-023):

| Target | Level | When | Notify |
|---|---|---|---|
| First response | 1 | at breach | assignee (fallback: group head) |
| Resolution | 1 | at the warning point | assignee |
| Resolution | 2 | at breach | assignee and group head |
| Resolution | 3 | 4 business hours after breach | group head's manager |

**Pause** (REQ-SLA-015, REQ-SLA-017): statuses in the paused category pause both response and
resolution. Pause while waiting for approval: off for incidents, on for service requests.

**Recalculation** (REQ-SLA-027, REQ-SLA-029, REQ-SLA-030): after a priority or condition
change, recalculate open targets from the SLA start; after a reopen, resume (time spent
resolved does not count); after a merge, the target keeps its own SLA. Breach reasons
(REQ-SLA-021): not asked.

**Routing and auto-assignment** (REQ-ASG-001 to REQ-ASG-011):

- fallback group: "Service desk", created with the tenant;
- auto-assignment: off for every group; when an admin switches it on, the method is round
  robin, on create and on move to the group, unassigned records only, available technicians
  only;
- load weights: P1 = 4, P2 = 3, P3 = 2, P4 = 1; paused records do not count;
- load cap: none;
- technician availability: set by the system, technician can change it;
- delegation during absence: new assignments go to the backup; open records stay.

**Business rules and automation** (REQ-RUL-005, REQ-RUL-015, REQ-RUL-019, REQ-RUL-022,
REQ-RUL-027, REQ-RUL-028):

- rule processing: continue to later rules unless a rule says "stop after this rule";
- automation chain depth per original change: 5; automated changes per record per minute: 20;
- webhook: timeout 10 seconds; 5 retries with exponential backoff (about 1, 5, 15, 60 minutes
  and 3 hours); daily calls: 10,000 per tenant (entitlement limit);
- custom function: 10 seconds run time, 256 MB memory, 1 CPU, no network until an allowlist is
  set; budget inside a save: 2 seconds, on timeout skip the rule;
- run logs kept 30 days.

**Workflows** (REQ-WF-024, REQ-WF-029): action nodes retry 3 times with backoff; maximum 200
nodes per workflow; maximum 100 rounds per loop; maximum 10,000 steps per instance.

**Notifications** (REQ-NTF-003, REQ-NTF-016 to REQ-NTF-024, REQ-NTF-028):

- channels on by default: email and in-app; browser notifications off until the user allows
  them;
- required events (cannot be switched off by users): approval requested, assigned to me,
  mention;
- digests: off; quiet hours: off (users opt in); urgent events: P1 records, major incidents,
  SLA breaches, approvals;
- per-recipient cap: 30 messages in 10 minutes, then combined into one summary; per-record
  coalescing window: 60 seconds; bulk actions over 10 records send one summary per recipient;
- delivery retries: 6 attempts over 24 hours;
- bounces: 1 hard bounce, or 3 soft bounces in 72 hours, makes an address undeliverable;
- action links: expire after 14 days, single use;
- reminders: first after 2 business days, then daily at 10:00, at most 3;
- in-app entries kept 90 days; delivery log kept 180 days.

---

## Open questions for the product owner

1. **Temporal and SLA at MVP.** Architecture §17 puts "rules and SLA on Temporal" in Stage 1,
   and ADR-004 makes SLA timers Temporal workflows. D-038 (11) says Temporal comes later, with
   the first workflow module. SLA clocks and escalations are MVP here (REQ-SLA-037). Does
   Temporal arrive with the SLA work package, or should MVP SLA timers use another durable
   scheduler that moves to Temporal later?
2. **Custom function sandbox.** ADR-011 is still open. Custom functions (REQ-RUL-018 to
   REQ-RUL-022) are V1 and Professional. Please confirm the edition, and that the sandbox
   decision is needed before the V1 automation work package.
3. **Edition of webhooks and custom menus.** Webhooks (REQ-RUL-014) are set to Essentials and
   custom menu actions (REQ-RUL-024) to Professional. product-plan §9 does not say. Agree?
4. **Default working week.** Appendix A proposes Monday–Friday 09:00–18:00 with a
   Sunday–Thursday option at onboarding. Should the default follow the tenant's country
   instead (for example Sunday–Thursday for Saudi Arabia, Monday–Friday or Monday–Saturday for
   Pakistan)?
5. **Priority change rule.** The proposed default recalculates open targets from the SLA start
   (REQ-SLA-027), so raising P3 to P1 late can breach at once. The alternative is to restart
   from the change. Which default do you want?
6. **Business rule processing default.** ServiceDesk Plus stops later rules by default when a
   rule matches; we propose to continue unless a rule says "stop" (REQ-RUL-005). The migration
   tool will need to map this. Agree?
7. **Mobile push timing.** REQ-NTF-005 follows REQ-INC-149 (mobile app LATER), but architecture
   §17 lists the mobile app in Stage 2 (V1). Should push, and the mobile app, move to V1?
8. **Text messages.** SMS (REQ-NTF-006) is LATER through a gateway. Is SMS needed for the
   design partner or for NOC customers at V1, and is there a preferred gateway that also works
   on-prem?
9. **Problem and release SLAs.** These are new compared with ServiceDesk Plus (REQ-SLA-009). Do
   you want them at V1, or only change SLAs?
10. **Experience level measures (XLA).** product-plan §5 lists XLA as P1; REQ-SLA-036 sets it to
    LATER and Professional. Agree?
11. **Intranet webhooks from SaaS.** ServiceDesk Plus can call intranet endpoints from its cloud.
    Reaching a customer's internal system from SaaS needs a relay agent on their network
    (file 12). Is that in scope, and when?
    *Proposed answer in file 12:* the intranet relay agent (REQ-INT-087), V1.
12. **Runbook actions on network devices.** Product-plan §6 describes runbooks on endpoints
    and network devices "via AgentX agents and MonetX". D-001 makes MonetX read-only, so
    REQ-RUL-032 covers AgentX endpoints only. Should device actions through MonetX stay out, or
    do you want an exception to D-001?

