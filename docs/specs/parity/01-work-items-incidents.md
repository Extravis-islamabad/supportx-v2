# 01 — Work item engine and incidents

Parity requirements for the shared work item engine (architecture.md §6.2) and for incident
management (architecture.md §2.1). Rules, ID scheme and field meanings: [README.md](README.md).

**Status:** Draft v0.2, 2026-10-24. The product owner's answers to the Phase 1 questions are
applied (D-039 to D-050). **Owner:** Haider (Product Owner).

## Scope of this file

- **REQ-WI-*** are engine requirements. They are built once in `work_items` and apply to every
  ticket-like type: incidents, service requests, problems, changes and releases. Later module
  files reference them instead of repeating them.
- **REQ-INC-*** are incident requirements, plus the parts of the engine (notes, tasks, worklogs,
  links, merge, closure ...) as an incident uses them. Most of them are built in the engine
  too, and later types inherit them; their module files only list the differences.
- **Not in this file** (each has its own module file, see the README):
  - SLA policies, escalations, auto-assignment, business rules and visual workflows (file 03).
    This file only says how an incident *uses* them: due dates, the countdown, SLA pause by
    status.
  - Catalog, service templates and the portal shell (file 02). The requester's view of an
    incident is here (REQ-INC-147).
  - The knowledge base itself (file 08), dashboards and reports (file 09), AI administration
    (file 10), users, roles, sites, mail servers and surveys (file 11), connector set-up
    (file 12).
- **Monitoring is out of scope** (ADR-017, D-001). SupportX turns MonetX problems into
  incidents and reads health from MonetX, read-only. It never polls devices and never
  correlates or de-duplicates alerts (REQ-INC-146).

## Words used in this file

| Word | Meaning |
|---|---|
| Work item | Any ticket-like record handled by the engine. |
| Incident | A work item of type `incident`: something is broken or degraded. |
| Requester | The person the incident is for. They may not be the person who logged it. |
| Technician | A staff user who works on incidents. |
| Group | A team of technicians that work items are assigned to. |
| Status category | The fixed meaning behind an admin-defined status: open, paused, resolved, closed, canceled (REQ-INC-044). |
| Action state | For each action on a record, whether the current user may run it now, and if not, a reason code (REQ-WI-010). |

## Requirement summary

<!-- summary:start -->
**Counts by decision and priority**

| Decision | MVP | V1 | LATER | Total |
|---|---|---|---|---|
| SAME | 36 | 45 | 8 | 89 |
| BETTER | 41 | 17 | 2 | 60 |
| NEW | 7 | 13 | 4 | 24 |
| SKIP | 0 | 0 | 2 | 2 |
| **Total** | **84** | **75** | **16** | **175** |

Edition (lowest edition that includes it): Essentials 164, Professional 11, Enterprise 0. By prefix: REQ-WI 25, REQ-INC 150.

| ID | Title | Decision | Priority | Edition |
|---|---|---|---|---|
| [REQ-WI-001](#req-wi-001--one-engine-for-every-ticket-like-record) | One engine for every ticket-like record | BETTER | MVP | Essentials |
| [REQ-WI-002](#req-wi-002--human-readable-ids-per-type) | Human-readable IDs per type | BETTER | MVP | Essentials |
| [REQ-WI-003](#req-wi-003--field-history-for-every-change) | Field history for every change | BETTER | MVP | Essentials |
| [REQ-WI-004](#req-wi-004--automation-leaves-a-visible-trace) | Automation leaves a visible trace | BETTER | MVP | Essentials |
| [REQ-WI-005](#req-wi-005--live-updates-on-every-screen) | Live updates on every screen | BETTER | MVP | Essentials |
| [REQ-WI-006](#req-wi-006--presence-and-edit-collision) | Presence and edit collision | NEW | V1 | Essentials |
| [REQ-WI-007](#req-wi-007--safe-concurrent-editing) | Safe concurrent editing | NEW | MVP | Essentials |
| [REQ-WI-008](#req-wi-008--no-duplicate-records-from-retries) | No duplicate records from retries | BETTER | MVP | Essentials |
| [REQ-WI-009](#req-wi-009--no-silent-failures) | No silent failures | BETTER | MVP | Essentials |
| [REQ-WI-010](#req-wi-010--actions-decided-by-the-server-shown-in-a-fixed-order) | Actions decided by the server, shown in a fixed order | BETTER | MVP | Essentials |
| [REQ-WI-011](#req-wi-011--fixed-tabs-on-the-record-page) | Fixed tabs on the record page | BETTER | MVP | Essentials |
| [REQ-WI-012](#req-wi-012--stable-layout-while-working) | Stable layout while working | BETTER | MVP | Essentials |
| [REQ-WI-013](#req-wi-013--labels-languages-and-right-to-left) | Labels, languages and right-to-left | BETTER | MVP | Essentials |
| [REQ-WI-014](#req-wi-014--one-date-and-time-formatter) | One date and time formatter | BETTER | MVP | Essentials |
| [REQ-WI-015](#req-wi-015--permissions-by-action-and-by-scope) | Permissions by action and by scope | SAME | MVP | Essentials |
| [REQ-WI-016](#req-wi-016--field-level-visibility) | Field-level visibility | NEW | V1 | Professional |
| [REQ-WI-017](#req-wi-017--licensing-through-entitlements-only) | Licensing through entitlements only | NEW | MVP | Essentials |
| [REQ-WI-018](#req-wi-018--everything-the-ui-does-the-api-does) | Everything the UI does, the API does | NEW | MVP | Essentials |
| [REQ-WI-019](#req-wi-019--domain-events-for-every-change) | Domain events for every change | NEW | MVP | Essentials |
| [REQ-WI-020](#req-wi-020--trash-and-restore) | Trash and restore | SAME | MVP | Essentials |
| [REQ-WI-021](#req-wi-021--audit-of-privileged-actions) | Audit of privileged actions | SAME | V1 | Essentials |
| [REQ-WI-022](#req-wi-022--keyboard-shortcuts-and-command-palette) | Keyboard shortcuts and command palette | BETTER | V1 | Essentials |
| [REQ-WI-023](#req-wi-023--accessible-to-wcag-22-aa) | Accessible to WCAG 2.2 AA | BETTER | MVP | Essentials |
| [REQ-WI-024](#req-wi-024--list-speed-at-scale) | List speed at scale | NEW | V1 | Essentials |
| [REQ-WI-025](#req-wi-025--features-outside-the-edition-disabled-with-a-hint-or-hidden) | Features outside the edition: disabled with a hint, or hidden | NEW | V1 | Essentials |
| [REQ-INC-001](#req-inc-001--incident-record-and-core-fields) | Incident record and core fields | SAME | MVP | Essentials |
| [REQ-INC-002](#req-inc-002--the-type-decides-the-form-and-the-behaviour) | The type decides the form and the behaviour | BETTER | MVP | Essentials |
| [REQ-INC-003](#req-inc-003--requester-on-behalf-of-and-requester-context) | Requester, on behalf of, and requester context | SAME | MVP | Essentials |
| [REQ-INC-004](#req-inc-004--vip-requesters) | VIP requesters | SAME | V1 | Essentials |
| [REQ-INC-005](#req-inc-005--channel-recorded-automatically) | Channel recorded automatically | BETTER | MVP | Essentials |
| [REQ-INC-006](#req-inc-006--category-subcategory-and-item) | Category, subcategory and item | SAME | MVP | Essentials |
| [REQ-INC-007](#req-inc-007--support-level) | Support level | SAME | V1 | Essentials |
| [REQ-INC-008](#req-inc-008--impact-and-urgency-on-clean-scales) | Impact and urgency on clean scales | BETTER | MVP | Essentials |
| [REQ-INC-009](#req-inc-009--priority-matrix-with-sensible-defaults) | Priority matrix with sensible defaults | BETTER | MVP | Essentials |
| [REQ-INC-010](#req-inc-010--priority-override-with-permission-and-reason) | Priority override with permission and reason | SAME | MVP | Essentials |
| [REQ-INC-011](#req-inc-011--never-silently-without-priority-or-sla) | Never silently without priority or SLA | BETTER | MVP | Essentials |
| [REQ-INC-012](#req-inc-012--due-dates-from-the-sla-overrides-recorded) | Due dates from the SLA, overrides recorded | SAME | MVP | Essentials |
| [REQ-INC-013](#req-inc-013--system-times-and-counters) | System times and counters | SAME | MVP | Essentials |
| [REQ-INC-014](#req-inc-014--custom-fields-on-incidents) | Custom fields on incidents | SAME | MVP | Essentials |
| [REQ-INC-015](#req-inc-015--assets-and-configuration-items-on-an-incident) | Assets and configuration items on an incident | SAME | V1 | Professional |
| [REQ-INC-016](#req-inc-016--site-and-department) | Site and department | SAME | MVP | Essentials |
| [REQ-INC-017](#req-inc-017--create-form-for-technicians) | Create form for technicians | SAME | MVP | Essentials |
| [REQ-INC-018](#req-inc-018--quick-create) | Quick create | SAME | V1 | Essentials |
| [REQ-INC-019](#req-inc-019--unsent-form-drafts-are-kept) | Unsent form drafts are kept | NEW | V1 | Essentials |
| [REQ-INC-020](#req-inc-020--log-an-incident-already-resolved) | Log an incident already resolved | SAME | MVP | Essentials |
| [REQ-INC-021](#req-inc-021--knowledge-suggestions-while-typing) | Knowledge suggestions while typing | BETTER | V1 | Essentials |
| [REQ-INC-022](#req-inc-022--possible-duplicate-warning) | Possible duplicate warning | NEW | V1 | Essentials |
| [REQ-INC-023](#req-inc-023--email-creates-incidents) | Email creates incidents | SAME | MVP | Essentials |
| [REQ-INC-024](#req-inc-024--email-replies-thread-into-the-incident) | Email replies thread into the incident | SAME | MVP | Essentials |
| [REQ-INC-025](#req-inc-025--set-fields-from-an-email) | Set fields from an email | SAME | V1 | Essentials |
| [REQ-INC-026](#req-inc-026--block-unwanted-mail) | Block unwanted mail | SAME | V1 | Essentials |
| [REQ-INC-027](#req-inc-027--unknown-senders) | Unknown senders | SAME | MVP | Essentials |
| [REQ-INC-028](#req-inc-028--requesters-report-incidents-in-the-portal) | Requesters report incidents in the portal | SAME | MVP | Essentials |
| [REQ-INC-029](#req-inc-029--create-from-an-asset-or-configuration-item) | Create from an asset or configuration item | SAME | V1 | Professional |
| [REQ-INC-030](#req-inc-030--monetx-problems-become-incidents) | MonetX problems become incidents | NEW | V1 | Professional |
| [REQ-INC-031](#req-inc-031--generic-alert-webhook) | Generic alert webhook | NEW | V1 | Professional |
| [REQ-INC-032](#req-inc-032--other-channels) | Other channels | SAME | LATER | Essentials |
| [REQ-INC-033](#req-inc-033--copy-an-incident) | Copy an incident | BETTER | V1 | Essentials |
| [REQ-INC-034](#req-inc-034--scheduled-recurring-incidents) | Scheduled recurring incidents | SAME | LATER | Essentials |
| [REQ-INC-035](#req-inc-035--incident-templates) | Incident templates | SAME | MVP | Essentials |
| [REQ-INC-036](#req-inc-036--form-designer-with-technician-and-requester-layouts) | Form designer with technician and requester layouts | SAME | V1 | Essentials |
| [REQ-INC-037](#req-inc-037--form-rules-the-same-in-the-browser-and-on-the-server) | Form rules, the same in the browser and on the server | BETTER | V1 | Essentials |
| [REQ-INC-038](#req-inc-038--guidance-on-a-template) | Guidance on a template | SAME | LATER | Essentials |
| [REQ-INC-039](#req-inc-039--switching-template-keeps-what-was-typed) | Switching template keeps what was typed | BETTER | V1 | Essentials |
| [REQ-INC-040](#req-inc-040--tasks-and-checklists-from-the-template) | Tasks and checklists from the template | SAME | V1 | Essentials |
| [REQ-INC-041](#req-inc-041--reply-templates) | Reply templates | SAME | V1 | Essentials |
| [REQ-INC-042](#req-inc-042--resolution-templates) | Resolution templates | SAME | V1 | Essentials |
| [REQ-INC-043](#req-inc-043--no-admin-scripts-run-inside-the-browser-form) | No admin scripts run inside the browser form | SKIP | LATER | Essentials |
| [REQ-INC-044](#req-inc-044--statuses-with-a-fixed-meaning) | Statuses with a fixed meaning | BETTER | MVP | Essentials |
| [REQ-INC-045](#req-inc-045--default-statuses-and-life-cycle) | Default statuses and life cycle | NEW | MVP | Essentials |
| [REQ-INC-046](#req-inc-046--status-changes-only-through-allowed-transitions) | Status changes only through allowed transitions | BETTER | MVP | Essentials |
| [REQ-INC-047](#req-inc-047--reasons-for-status-changes) | Reasons for status changes | BETTER | MVP | Essentials |
| [REQ-INC-048](#req-inc-048--required-fields-per-transition) | Required fields per transition | SAME | V1 | Essentials |
| [REQ-INC-049](#req-inc-049--life-cycle-designer) | Life cycle designer | BETTER | V1 | Essentials |
| [REQ-INC-050](#req-inc-050--assignment-moves-the-status-sensibly) | Assignment moves the status sensibly | BETTER | MVP | Essentials |
| [REQ-INC-051](#req-inc-051--requester-reply-resumes-a-paused-incident) | Requester reply resumes a paused incident | SAME | MVP | Essentials |
| [REQ-INC-052](#req-inc-052--board-moves-respect-the-life-cycle) | Board moves respect the life cycle | BETTER | V1 | Essentials |
| [REQ-INC-053](#req-inc-053--assign-to-a-group-and-a-technician) | Assign to a group and a technician | BETTER | MVP | Essentials |
| [REQ-INC-054](#req-inc-054--take-ownership) | Take ownership | BETTER | MVP | Essentials |
| [REQ-INC-055](#req-inc-055--reassign-with-a-record-of-why) | Reassign with a record of why | SAME | MVP | Essentials |
| [REQ-INC-056](#req-inc-056--followers-and-sharing) | Followers and sharing | SAME | V1 | Essentials |
| [REQ-INC-057](#req-inc-057--one-conversation-timeline) | One conversation timeline | SAME | MVP | Essentials |
| [REQ-INC-058](#req-inc-058--reply-reply-to-all-forward) | Reply, reply to all, forward | BETTER | MVP | Essentials |
| [REQ-INC-059](#req-inc-059--delivery-status-of-outgoing-messages) | Delivery status of outgoing messages | NEW | MVP | Essentials |
| [REQ-INC-060](#req-inc-060--work-goes-on-when-mail-is-not-configured) | Work goes on when mail is not configured | BETTER | MVP | Essentials |
| [REQ-INC-061](#req-inc-061--public-and-private-notes) | Public and private notes | SAME | MVP | Essentials |
| [REQ-INC-062](#req-inc-062--edit-and-delete-notes-with-history) | Edit and delete notes with history | SAME | V1 | Essentials |
| [REQ-INC-063](#req-inc-063--mentions) | Mentions | NEW | V1 | Essentials |
| [REQ-INC-064](#req-inc-064--safe-rich-text) | Safe rich text | BETTER | MVP | Essentials |
| [REQ-INC-065](#req-inc-065--first-response-is-stamped-automatically) | First response is stamped automatically | BETTER | MVP | Essentials |
| [REQ-INC-066](#req-inc-066--extra-people-to-keep-informed) | Extra people to keep informed | SAME | V1 | Essentials |
| [REQ-INC-067](#req-inc-067--worklogs) | Worklogs | BETTER | MVP | Essentials |
| [REQ-INC-068](#req-inc-068--worklog-costs-and-billable-time) | Worklog costs and billable time | SAME | V1 | Essentials |
| [REQ-INC-069](#req-inc-069--personal-work-timer) | Personal work timer | BETTER | V1 | Essentials |
| [REQ-INC-070](#req-inc-070--worklog-rules) | Worklog rules | SAME | V1 | Essentials |
| [REQ-INC-071](#req-inc-071--time-analysis) | Time analysis | SAME | V1 | Essentials |
| [REQ-INC-072](#req-inc-072--tasks-on-an-incident) | Tasks on an incident | SAME | MVP | Essentials |
| [REQ-INC-073](#req-inc-073--task-details) | Task details | SAME | V1 | Essentials |
| [REQ-INC-074](#req-inc-074--task-templates) | Task templates | SAME | V1 | Essentials |
| [REQ-INC-075](#req-inc-075--task-dependencies-that-are-enforced) | Task dependencies that are enforced | BETTER | V1 | Essentials |
| [REQ-INC-076](#req-inc-076--task-notifications-and-my-tasks) | Task notifications and "my tasks" | SAME | V1 | Essentials |
| [REQ-INC-077](#req-inc-077--checklists-on-an-incident) | Checklists on an incident | SAME | V1 | Essentials |
| [REQ-INC-078](#req-inc-078--checklist-library-and-import) | Checklist library and import | SAME | V1 | Essentials |
| [REQ-INC-079](#req-inc-079--safe-attachments) | Safe attachments | BETTER | MVP | Essentials |
| [REQ-INC-080](#req-inc-080--all-attachments-in-one-place) | All attachments in one place | NEW | V1 | Essentials |
| [REQ-INC-081](#req-inc-081--links-to-cloud-files) | Links to cloud files | SAME | LATER | Essentials |
| [REQ-INC-082](#req-inc-082--personal-reminders-on-an-incident) | Personal reminders on an incident | SAME | V1 | Essentials |
| [REQ-INC-083](#req-inc-083--ask-for-approval-on-an-incident) | Ask for approval on an incident | BETTER | V1 | Essentials |
| [REQ-INC-084](#req-inc-084--link-related-incidents) | Link related incidents | BETTER | MVP | Essentials |
| [REQ-INC-085](#req-inc-085--link-and-merge-pickers-search-everything-you-can-see) | Link and merge pickers search everything you can see | BETTER | MVP | Essentials |
| [REQ-INC-086](#req-inc-086--parent-and-child-incidents) | Parent and child incidents | SAME | V1 | Essentials |
| [REQ-INC-087](#req-inc-087--associations-with-other-records) | Associations with other records | BETTER | V1 | Professional |
| [REQ-INC-088](#req-inc-088--merge-incidents-with-a-preview) | Merge incidents with a preview | BETTER | V1 | Essentials |
| [REQ-INC-150](#req-inc-150--undo-a-merge) | Undo a merge | NEW | V1 | Essentials |
| [REQ-INC-089](#req-inc-089--convert-between-incident-and-service-request) | Convert between incident and service request | SAME | V1 | Essentials |
| [REQ-INC-090](#req-inc-090--resolve-with-a-resolution) | Resolve with a resolution | SAME | MVP | Essentials |
| [REQ-INC-091](#req-inc-091--turn-a-resolution-into-knowledge) | Turn a resolution into knowledge | SAME | V1 | Essentials |
| [REQ-INC-092](#req-inc-092--apply-a-resolution-to-linked-incidents) | Apply a resolution to linked incidents | SAME | V1 | Essentials |
| [REQ-INC-093](#req-inc-093--closure-codes) | Closure codes | SAME | MVP | Essentials |
| [REQ-INC-094](#req-inc-094--closure-rules) | Closure rules | SAME | MVP | Essentials |
| [REQ-INC-095](#req-inc-095--closing-with-open-work-is-warned-or-blocked) | Closing with open work is warned or blocked | BETTER | MVP | Essentials |
| [REQ-INC-096](#req-inc-096--requester-confirms-the-resolution-then-auto-close) | Requester confirms the resolution, then auto-close | SAME | MVP | Essentials |
| [REQ-INC-097](#req-inc-097--reopen-keeps-the-past) | Reopen keeps the past | BETTER | MVP | Essentials |
| [REQ-INC-098](#req-inc-098--requester-replies-after-resolution) | Requester replies after resolution | SAME | MVP | Essentials |
| [REQ-INC-099](#req-inc-099--tell-thanks-from-still-broken) | Tell "thanks" from "still broken" | SAME | V1 | Essentials |
| [REQ-INC-100](#req-inc-100--cancel-with-a-reason-and-undo-it) | Cancel with a reason, and undo it | SAME | MVP | Essentials |
| [REQ-INC-101](#req-inc-101--editing-closed-incidents-is-controlled) | Editing closed incidents is controlled | SAME | V1 | Essentials |
| [REQ-INC-102](#req-inc-102--first-contact-resolution) | First-contact resolution | BETTER | V1 | Essentials |
| [REQ-INC-103](#req-inc-103--satisfaction-survey-after-closing) | Satisfaction survey after closing | SAME | V1 | Essentials |
| [REQ-INC-104](#req-inc-104--incident-list-with-chosen-columns) | Incident list with chosen columns | SAME | MVP | Essentials |
| [REQ-INC-105](#req-inc-105--built-in-views) | Built-in views | SAME | MVP | Essentials |
| [REQ-INC-106](#req-inc-106--custom-views-and-the-filter-builder) | Custom views and the filter builder | BETTER | MVP | Essentials |
| [REQ-INC-107](#req-inc-107--share-views-and-mark-favourites) | Share views and mark favourites | SAME | V1 | Essentials |
| [REQ-INC-108](#req-inc-108--quick-time-range) | Quick time range | SAME | MVP | Essentials |
| [REQ-INC-109](#req-inc-109--search-with-chips-without-losing-your-place) | Search with chips, without losing your place | BETTER | MVP | Essentials |
| [REQ-INC-110](#req-inc-110--counts-and-paging) | Counts and paging | BETTER | MVP | Essentials |
| [REQ-INC-111](#req-inc-111--card-list-and-board) | Card list and board | SAME | V1 | Essentials |
| [REQ-INC-112](#req-inc-112--calendar-view) | Calendar view | SAME | V1 | Essentials |
| [REQ-INC-113](#req-inc-113--split-view-and-quick-peek) | Split view and quick peek | NEW | V1 | Essentials |
| [REQ-INC-114](#req-inc-114--edit-in-the-list) | Edit in the list | NEW | V1 | Essentials |
| [REQ-INC-115](#req-inc-115--row-colours-and-unread-markers) | Row colours and unread markers | SAME | V1 | Essentials |
| [REQ-INC-116](#req-inc-116--export-lists) | Export lists | BETTER | V1 | Essentials |
| [REQ-INC-117](#req-inc-117--chart-a-list-in-place) | Chart a list in place | SAME | LATER | Essentials |
| [REQ-INC-118](#req-inc-118--archive-old-incidents) | Archive old incidents | SAME | LATER | Essentials |
| [REQ-INC-119](#req-inc-119--select-across-pages) | Select across pages | BETTER | MVP | Essentials |
| [REQ-INC-120](#req-inc-120--bulk-edit-assign-take-resolve-and-close) | Bulk edit, assign, take, resolve and close | BETTER | MVP | Essentials |
| [REQ-INC-121](#req-inc-121--bulk-merge-link-delete-and-note-with-safeguards) | Bulk merge, link, delete and note with safeguards | BETTER | V1 | Essentials |
| [REQ-INC-122](#req-inc-122--record-page-layout) | Record page layout | BETTER | MVP | Essentials |
| [REQ-INC-123](#req-inc-123--edit-fields-on-the-record) | Edit fields on the record | SAME | MVP | Essentials |
| [REQ-INC-124](#req-inc-124--a-reason-for-an-edit) | A reason for an edit | SAME | V1 | Essentials |
| [REQ-INC-125](#req-inc-125--next-and-previous) | Next and previous | SAME | V1 | Essentials |
| [REQ-INC-126](#req-inc-126--print-and-pdf) | Print and PDF | SAME | V1 | Essentials |
| [REQ-INC-127](#req-inc-127--recently-viewed) | Recently viewed | SAME | V1 | Essentials |
| [REQ-INC-128](#req-inc-128--personal-counters) | Personal counters | SAME | MVP | Essentials |
| [REQ-INC-129](#req-inc-129--announce-from-an-incident) | Announce from an incident | SAME | V1 | Essentials |
| [REQ-INC-130](#req-inc-130--incident-notifications-with-sensible-defaults) | Incident notifications with sensible defaults | BETTER | MVP | Essentials |
| [REQ-INC-131](#req-inc-131--in-app-notification-centre) | In-app notification centre | SAME | MVP | Essentials |
| [REQ-INC-132](#req-inc-132--notification-templates-per-language-editable-safely) | Notification templates per language, editable safely | BETTER | V1 | Essentials |
| [REQ-INC-133](#req-inc-133--notifications-in-the-recipients-language) | Notifications in the recipient's language | NEW | MVP | Essentials |
| [REQ-INC-134](#req-inc-134--notification-log-on-the-incident) | Notification log on the incident | SAME | MVP | Essentials |
| [REQ-INC-135](#req-inc-135--classification-suggestions) | Classification suggestions | SAME | V1 | Essentials |
| [REQ-INC-136](#req-inc-136--writing-help-in-replies-and-notes) | Writing help in replies and notes | SAME | V1 | Essentials |
| [REQ-INC-137](#req-inc-137--conversation-summary) | Conversation summary | BETTER | V1 | Essentials |
| [REQ-INC-138](#req-inc-138--sentiment-and-frustration-cues) | Sentiment and frustration cues | SAME | LATER | Essentials |
| [REQ-INC-139](#req-inc-139--translate-messages) | Translate messages | NEW | LATER | Essentials |
| [REQ-INC-140](#req-inc-140--triage-agent) | Triage agent | NEW | LATER | Professional |
| [REQ-INC-141](#req-inc-141--declare-a-major-incident) | Declare a major incident | SAME | V1 | Essentials |
| [REQ-INC-142](#req-inc-142--stakeholder-updates-and-a-status-page) | Stakeholder updates and a status page | BETTER | LATER | Professional |
| [REQ-INC-143](#req-inc-143--war-room) | War room | NEW | LATER | Professional |
| [REQ-INC-144](#req-inc-144--post-incident-review) | Post-incident review | BETTER | LATER | Professional |
| [REQ-INC-145](#req-inc-145--live-health-of-linked-items-from-monetx) | Live health of linked items from MonetX | NEW | LATER | Professional |
| [REQ-INC-146](#req-inc-146--no-alert-correlation-in-supportx) | No alert correlation in SupportX | SKIP | LATER | Essentials |
| [REQ-INC-147](#req-inc-147--requesters-follow-their-incidents) | Requesters follow their incidents | SAME | MVP | Essentials |
| [REQ-INC-148](#req-inc-148--requester-cancel-and-edit-rules) | Requester cancel and edit rules | SAME | V1 | Essentials |
| [REQ-INC-149](#req-inc-149--incidents-on-the-mobile-app) | Incidents on the mobile app | SAME | LATER | Essentials |
<!-- summary:end -->

---

## 1. Engine foundation (applies to every work item type)

#### REQ-WI-001 — One engine for every ticket-like record

Incidents, service requests, problems, changes and releases share one core. That core covers
identifiers, the status machine, fields, conversations, notes, attachments, tasks, checklists,
approvals, worklogs, links, followers, history and live updates. Each type adds only its own
fields and rules.

- **Decision:** BETTER. ServiceDesk Plus rebuilds templates, statuses, approvals, notes and
  timers separately for each module, so they behave differently. One engine gives the same
  behaviour everywhere, and a feature built once reaches every type.
- **Source:** architecture §6.2; sdp-area-04 §Weak spots; sdp-area-06 §Weak spots
- **SDP weak spot fixed:** problem notes have no public/private split while request notes do.
  Release workflows are much weaker than change workflows for no visible reason.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. One shared contract test suite (notes, tasks, checklists, attachments, links, history) runs
     against every work item type and passes for each.
  2. A new engine capability needs no per-type code beyond enabling it for that type.
  3. Type-specific fields are stored and validated per type and never show on another type.

#### REQ-WI-002 — Human-readable IDs per type

Every work item gets a human ID with a type prefix and a per-tenant counter, for example
INC-1042 or SR-77. Each type has its own counter. An admin may change the prefix.

- **Decision:** BETTER. One shared, unprefixed counter for incidents and service requests makes
  IDs ambiguous in conversation and in email subjects.
- **Source:** architecture §7.1; sdp-area-13 §Advanced Portal Settings; D-045
- **SDP weak spot fixed:** incident and service request IDs are plain numbers from one shared
  counter, and other modules each use their own prefix style.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. The first incident in a new tenant is INC-1, and the first service request is SR-1.
  2. Two tenants each get INC-1; IDs never collide inside a tenant, even when created concurrently.
  3. A display ID is never reused, even after the record is deleted or merged.
  4. After a prefix change, new records use the new prefix and old IDs still open their records.
  5. Searching for a display ID (with or without the prefix) opens that record.

#### REQ-WI-003 — Field history for every change

Every change to a work item is recorded: who made it, when (to the second), the field, the old
value, the new value, the source and the reason if one was given. Sources are UI, API, email,
portal, rule, workflow, SLA, AI agent, integration and system. The history covers links,
attachments, tasks and approvals as well as fields. Both sides of a link record it.

- **Decision:** BETTER. Full history with source and reason, recorded on both ends of every
  relationship.
- **Source:** architecture §7.4; D-034; sdp-area-05 §Behaviour (5b links); sdp-area-12 (12b) §Weak spots
- **SDP weak spot fixed:** history timestamps are per minute, so order inside a minute is
  guessed. Linking a change to a request leaves no entry on the request side.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Changing a field writes one history entry with actor, second-precision time, old value,
     new value and source.
  2. Entries made within the same second keep their true order.
  3. Linking record A to record B adds an entry to both A and B.
  4. Values in history display through labels, never as raw codes.
  5. History entries cannot be edited or deleted through any API.

#### REQ-WI-004 — Automation leaves a visible trace

Rules, SLA selection, auto-assignment, workflows, timers and AI agents record what they changed
and which rule or agent did it, the same way a person's change is recorded.

- **Decision:** BETTER. An admin can always answer "why did this field change?"
- **Source:** sdp-area-12 (12b) §Behaviour (execution order)
- **SDP weak spot fixed:** business rules and SLA selection leave no history line. Their effect
  had to be inferred, and a rule that changes priority silently changes the SLA.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A rule that sets priority writes a history entry naming the rule.
  2. Applying an SLA writes an entry naming the SLA policy and the matching reason.
  3. An auto-assignment entry names the assignment method used.
  4. The history view can be filtered to automation only or people only.

#### REQ-WI-005 — Live updates on every screen

Any committed change reaches every screen showing that data within one second, with no page
refresh. The change can come from a person, the portal, email, a rule, a workflow, an AI agent
or MonetX. This covers record pages, lists, boards, counters, the conversation timeline, tasks,
approvals and the portal. Events carry only IDs, changed fields and version; screens fetch
anything sensitive through the API.

- **Decision:** BETTER. ServiceDesk Plus lists refresh on a timer that is off by default.
- **Source:** architecture §8, §1.3; ADR-023; sdp-area-02a §Config (refresh frequency Never)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. With two browsers open, a field change in one appears on the record page in the other
     within 1 second (p95 at design load).
  2. A change that moves an incident out of a list's filter removes the row live; a change
     that moves it in adds the row.
  3. Personal counters (for example "overdue") change live when an incident becomes overdue.
  4. After a network drop and reconnect, missed changes are replayed or the screen refetches;
     no stale data stays on screen.
  5. A user without access to an incident receives no event about it.

#### REQ-WI-006 — Presence and edit collision

A record page shows who else is viewing it and who is writing a reply or note, so two
technicians do not answer the same requester at once.

- **Decision:** NEW. ServiceDesk Plus has no presence on records.
- **Source:** architecture §8.3
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. When a second technician opens the record, the first sees them listed within 2 seconds.
  2. When someone starts typing a reply, others see a typing indicator; it disappears when they
     stop or send.
  3. Presence never shows to the requester.

#### REQ-WI-007 — Safe concurrent editing

Every edit carries the version it was based on. If someone else changed the record in between,
the save is refused and the user sees who changed what. They can then reapply their change.

- **Decision:** NEW. No overwrite protection was observed in ServiceDesk Plus.
- **Source:** architecture §6.5, §10; CLAUDE.md §5g
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Two users edit the same field from the same version; the second save returns 409 and the
     UI names the other user and the changed fields.
  2. After a conflict the user's unsaved input is kept, so they can review and save again.
  3. Edits to different parts that cannot clash (adding a note, adding a task) never conflict
     with field edits.

#### REQ-WI-008 — No duplicate records from retries

Creating a record is idempotent. A double click, a retried request on a flaky network or a
resubmitted form never creates two records. The submit button shows progress and cannot be
pressed twice.

- **Decision:** BETTER. Removes duplicate tickets and the "did it save?" doubt.
- **Source:** architecture §6.5; sdp-area-02b §Weak spots; sdp-area-02c §Behaviour
- **SDP weak spot fixed:** the first click on the create button sometimes did nothing visible,
  with no spinner, so users click again.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Two create calls with the same idempotency key return the same record; only one exists.
  2. While a create is in flight the submit control shows progress and ignores further clicks.
  3. A create that fails shows an error and keeps every entered value.

#### REQ-WI-009 — No silent failures

Every action ends in a visible outcome: confirmation, a clear error in the user's language, or
a clearly shown pending state. Background work (email sending, workflow steps, rule actions,
exports, bulk jobs) that fails is shown on the record and to the right people. It is never only
in a log.

- **Decision:** BETTER. This is a cross-cutting lesson from the research.
- **Source:** sdp-area-02b §Weak spots; sdp-area-02c §Weak spots; sdp-area-05 §Behaviour (5b); sdp-area-12 (12b) §Weak spots
- **SDP weak spot fixed:** a failed mail step stalls a workflow silently. A field update that
  is invalid for incidents fails only at run time. A stuck workflow shows only a small red dot.
  Pressing reply with no mail server replaces the conversation with an error.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Every write action in the UI shows success or a human-readable error; tests assert that no
     action completes with no feedback.
  2. A failed background step on an incident shows a banner on the record naming the step and
     the next action, and notifies the owner.
  3. Errors never show stack traces, exception names or raw codes.
  4. Admin configuration that can never work (for example a field update that is invalid for
     the type) is rejected when it is saved, not when it runs.

#### REQ-WI-010 — Actions decided by the server, shown in a fixed order

The server tells the UI, for every action on a record, whether this user may run it now, and
if not, why. Actions keep a fixed order and position. An action that is not available is shown
disabled with its reason, instead of disappearing and moving the others.

- **Decision:** BETTER. Menus that change shape lead to wrong clicks.
- **Source:** module-template.md §4 (action states); sdp-area-04 §Weak spots; sdp-area-05 §Weak spots
- **SDP weak spot fixed:** Actions menu items appear, vanish and move as state changes; a
  wrong click opened "delete" by mistake. Action buttons do nothing without a selection and
  then raise a blocking alert.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. The record API returns a state for every action: allowed, or not allowed with a reason code.
  2. The order of actions in the action bar and menu is the same in every status.
  3. A disabled action shows its reason as a tooltip, translated.
  4. Destructive actions (delete, merge, cancel) sit apart from everyday actions and always ask
     for confirmation.

#### REQ-WI-011 — Fixed tabs on the record page

The record page has the same tabs in the same order on every incident. Each tab shows a count,
and an empty tab shows an empty state with the action to add the first item. Tabs never appear,
disappear or move into an overflow menu depending on content.

- **Decision:** BETTER.
- **Source:** sdp-area-02c §Screens, §Weak spots; sdp-area-04 §Weak spots
- **SDP weak spot fixed:** worklog and reminder tabs appear only once items exist, and the
  overflow menu reshuffles the tab bar each time it is used.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A new incident and an incident with every kind of item show the same tab list in the same
     order.
  2. Each tab label shows a live count.
  3. At the narrowest supported width the tab bar scrolls; it never reorders.

#### REQ-WI-012 — Stable layout while working

Panels that appear while a user types (suggestions, warnings, banners) never move the control
under the pointer or lose typed text. Suggestions open beside the form or in reserved space.

- **Decision:** BETTER.
- **Source:** sdp-area-02c §Weak spots; sdp-area-12 §Weak spots; sdp-area-12 (12b) §Weak spots
- **SDP weak spot fixed:** the knowledge suggestion banner shifts the form, so the first click
  on the save button misses, and text typed before the shift was lost.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. An e2e test types a subject that triggers suggestions and then clicks save at the original
     position; the save happens.
  2. No typed character is lost when a suggestion panel opens.
  3. A layout-shift check on the create form stays below the agreed threshold (CLS < 0.1).

#### REQ-WI-013 — Labels, languages and right-to-left

Every value on screen goes through the labels package: statuses, priorities, field names, codes,
event types, errors. The product works fully in English and Arabic from day one, and in Urdu
from Stage 2, including right-to-left layout. Admin-defined values carry their own translations.

- **Decision:** BETTER. ServiceDesk Plus shows internal-style names (role names such as
  "SDAdmin", field keys) and charges extra for multiple languages on-prem.
- **Source:** architecture §9.5; CLAUDE.md §5d; D-006; product-plan §9.1; sdp-area-11 §Weak spots
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. CI fails if any backend code used by incidents lacks an English label or an Arabic
     translation (and Urdu from Stage 2).
  2. Every incident screen passes the e2e suite in Arabic with right-to-left layout.
  3. An admin-created status shows its translated label in each language and falls back to
     English when a translation is missing.
  4. A lint rule blocks rendering a raw code in the console and portal.

#### REQ-WI-014 — One date and time formatter

All dates and times show in the user's profile time zone and locale through one shared
formatter. Relative times ("in 40 minutes") and absolute times agree. All date entry uses the
shared date-time field (D-035).

- **Decision:** BETTER.
- **Source:** D-035; sdp-area-02c §Automation, §Weak spots
- **SDP weak spot fixed:** the header said an incident was due in 47 minutes, while history
  showed a due date two days later.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. The due time in the header, the properties panel, the list and history is the same instant,
     in the same zone, for one user.
  2. Two users in different time zones see the same instant, each in their own zone.
  3. Relative and absolute forms come from the same value, and a test checks they agree
     across a daylight-saving change.
  4. No screen uses a native browser date input.

#### REQ-WI-015 — Permissions by action and by scope

Each action has its own permission: view, create, edit, assign, take, resolve, close, reopen,
cancel, merge, link, delete, edit closed, change due date, change priority, manage followers,
share, edit or delete own notes, edit or delete others' notes, add or delete worklogs, add or
delete tasks and checklists, export. Each permission is granted at a scope: all, site, group or
own (assigned to me, or created by me). The rules are the same in the API, search, live updates
and AI.

- **Decision:** SAME. Matches the per-action permissions and the site/group/assigned scopes in
  ServiceDesk Plus, on our policy layer.
- **Source:** sdp-area-11 §Fields (advanced permissions, scope grid); architecture §11.2; ADR-022
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A technician scoped to group A gets 404 for an incident in group B, through the API,
     search, live updates and AI.
  2. A role without the "merge" permission sees merge disabled with a reason, and the API
     refuses it with 403.
  3. Removing a permission takes effect on open screens without a new login.
  4. Built-in roles can be opened and read by an admin, so it is clear what they grant.

#### REQ-WI-016 — Field-level visibility

An admin can hide a field, mask it or make it read-only per role, for example cost fields or
personal data. Hidden values are removed by the server, not only by the UI.

- **Decision:** NEW. ServiceDesk Plus has no field-level permission on requests.
- **Source:** architecture §11.2 (field level)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A role without visibility of a field never receives its value from the API, exports,
     search, live events or AI answers.
  2. A masked field shows a masked value and cannot be searched or filtered by that role.
  3. A read-only field cannot be changed through the API by that role (403).

#### REQ-WI-017 — Licensing through entitlements only

Incident features are switched on through the entitlement interface only (`has_feature`,
`check_limit`, `remaining`), with the same behaviour on SaaS and on-prem. No code checks the
deployment type.

- **Decision:** NEW. ServiceDesk Plus Cloud and On-Prem differ in hundreds of features; ours do not.
- **Source:** architecture §13.1, §1.2; CLAUDE.md §5f; ADR-021; product-plan §4.3 (pillar 1)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. With the incident feature off, every incident API returns the licence problem code and the
     UI explains it in plain words.
  2. The same incident test suite passes in the SaaS and the on-prem profile.
  3. Import-linter and a code search find no deployment-mode branches in incident code.

#### REQ-WI-018 — Everything the UI does, the API does

Every incident action in the console and the portal uses the same public, versioned and
documented REST API, with the same permissions. Integrations, the mobile app, AI agents and the
MCP server use it too.

- **Decision:** NEW (architecture principle P2).
- **Source:** architecture §3 (P2), §10
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Every incident action is described in the OpenAPI document with request and response
     schemas and problem codes.
  2. An e2e test can perform the full incident life (create, assign, note, resolve, close) with
     API calls only.
  3. A breaking API change fails CI.

#### REQ-WI-019 — Domain events for every change

Every state change writes a domain event to the outbox in the same transaction as the change.
Events include created, updated, status changed, assigned, note added, reply sent, attachment
added, linked, merged, resolved, closed, reopened and deleted. Notifications, live updates,
search, analytics, webhooks and workflows consume these events.

- **Decision:** NEW (architecture principle P3).
- **Source:** architecture §6.5, §3 (P3); CLAUDE.md §5b; ADR-019
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A rolled-back change produces no event; a committed change always produces one.
  2. Each event has a unique ID, and consumers process a redelivered event only once.
  3. Event contracts are versioned in `events.py`, and a breaking change fails CI.

#### REQ-WI-020 — Trash and restore

Deleting an incident moves it to a trash that users with permission can browse, search and
restore from. Restoring brings back the record with its conversations, links and history. Trash
is emptied after a tenant-set retention period. Permanent erasure happens only through the
privacy erasure job.

- **Decision:** SAME.
- **Source:** sdp-area-02a §Screens (trashed requests); architecture §7.1
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A deleted incident disappears from lists and search and appears in trash.
  2. A restored incident has the same ID, history and links, plus a history entry for the
     delete and the restore.
  3. Incidents older than the retention period are purged from trash automatically, and each
     purge is audited.
  4. A user without the delete permission cannot see or use trash.

#### REQ-WI-021 — Audit of privileged actions

Privileged actions are written to the tamper-evident audit log: delete, restore, purge, merge,
bulk changes, permission-overriding edits, editing closed records, export and changing due
dates.

- **Decision:** SAME.
- **Source:** architecture §7.4, §11; D-034 (WP-018)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Each listed action creates an audit entry with actor, time, target and outcome.
  2. Changing or removing an audit entry is detected by the audit verification.
  3. An auditor can export the audit entries for one incident.

#### REQ-WI-022 — Keyboard shortcuts and command palette

Frequent technician actions have keyboard shortcuts: open by ID, new incident, assign, take,
reply, note, worklog, task, resolve, close, link, and next and previous record. A command
palette (Ctrl+K) finds records and runs actions. Shortcuts can be listed and switched off.

- **Decision:** BETTER. Same shortcut coverage, plus a command palette.
- **Source:** sdp-area-01 §Config (keyboard shortcuts); architecture §9.4
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Each listed action can be run from the keyboard on the record page.
  2. The palette finds an incident by display ID or subject words and opens it.
  3. A user who switches shortcuts off triggers none of them while typing.
  4. Shortcuts work the same way in right-to-left layout.

#### REQ-WI-023 — Accessible to WCAG 2.2 AA

All work item screens meet WCAG 2.2 AA: keyboard reach, focus management, ARIA, contrast, and
reduced motion.

- **Decision:** BETTER. ServiceDesk Plus offers many personal accessibility switches. We build
  the standard in, so every user gets it without setting anything.
- **Source:** architecture §9.4; sdp-area-01 §Config (accessibility toggles)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. The automated accessibility check (axe) reports no serious or critical issues on the
     incident list, record and create form, in English and Arabic.
  2. Every incident action can be done with the keyboard only.
  3. Users who ask for reduced motion get no animation.

#### REQ-WI-024 — List speed at scale

The incident list stays fast at scale. A 50-row page with filters and sort loads in under
300 ms on 10 million incidents in one tenant. Reads take under 200 ms and writes under 400 ms
(p95) at design load.

- **Decision:** NEW (architecture design targets).
- **Source:** architecture §1.3
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A load test with 10 million incidents meets the list target for the five most used views.
  2. Read and write API latency targets are met at 10,000 concurrent technicians in the load
     test.
  3. Every sortable list column has a supporting index, and CI checks for missing ones.

#### REQ-WI-025 — Features outside the edition: disabled with a hint, or hidden

When a capability is not in the tenant's edition, for example linking an incident to a problem
in Essentials, its actions, tabs and fields show disabled with a short upgrade hint. A tenant
admin can switch this to hide such capabilities completely. The server decides through the
entitlement interface and returns the action state with a licence reason code; the browser only
renders it.

- **Decision:** NEW. ServiceDesk Plus hides or shows edition-locked features inconsistently.
- **Source:** D-044; architecture §13.1; CLAUDE.md §5f; REQ-WI-010
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. In an Essentials tenant, the link-to-problem action is shown disabled with an upgrade
     hint, and the API refuses it with the licence problem code.
  2. With the admin switch set to hide, the same action, tab and fields are absent from the
     console and the portal.
  3. Changing the switch takes effect on open screens live, with no reload.
  4. No browser code decides availability from the edition name; it uses the action state from
     the server.

---

## 2. The incident record and its classification

#### REQ-INC-001 — Incident record and core fields

An incident has these fields:

- subject (required) and description (rich text);
- requester (required), created by and on behalf of;
- channel, site and department;
- group and technician;
- category, subcategory and item;
- impact, impact details, urgency and priority;
- status;
- first response due and resolution due;
- assets and configuration items;
- template, tags and custom fields.

- **Decision:** SAME. The same field set as the ServiceDesk Plus request form, in our own
  layout.
- **Source:** sdp-area-02b §Fields; sdp-area-02c §Screens (details tab); architecture §2.1
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. An incident can be created with only a subject and a requester; every other field is
     optional unless a template or rule makes it required.
  2. Each field is readable and writable through the API, and allowed in list columns, filters
     and reports.
  3. The details view can hide empty fields, and the choice is remembered per user.
  4. Tags can be added and removed and used as a list filter.

#### REQ-INC-002 — The type decides the form and the behaviour

Each work item has a required type: incident or service request. Problems, changes and
releases are separate types. The type decides the form, the default life cycle, the SLA family
and the counter. "Request for information" and other kinds of ask are service request
templates, not extra types. Major incident is a flag on an incident (REQ-INC-141), not a type.
The page title always matches the type.

- **Decision:** BETTER. In ServiceDesk Plus the request type is optional, yet it decides how
  the request is treated, and the form title stays "New Incident" on a service template.
- **Source:** sdp-area-02b §Fields (request type), §Weak spots; architecture §6.2
- **SDP weak spot fixed:** the type field is not required but controls behaviour, and the page
  title does not match the chosen template.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A work item cannot be saved without a type.
  2. Choosing a service request template changes the form title and the ID prefix to the
     service request ones.
  3. The type can change only through conversion (REQ-INC-089), never by editing a field.

#### REQ-INC-003 — Requester, on behalf of, and requester context

The requester is picked by name, email or employee ID. When the requester is chosen, the form
shows their contact details, department, job title and VIP flag. It also shows their open and
recent incidents and the assets they use. A technician can log an incident on behalf of a
requester. The creator, the requester and the on-behalf-of person are kept separate. A new
requester can be added from the form if the technician has permission.

- **Decision:** SAME.
- **Source:** sdp-area-02b §Fields (requester); sdp-area-02c §Actions (requester details cards); sdp-area-13 §Requester Portal (on behalf of)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Choosing a requester shows their details and their last five incidents without leaving the
     form.
  2. Adding a requester inline creates the user and selects them; the inline form refuses a
     duplicate email.
  3. History and reports keep creator, requester and on-behalf-of person apart.

#### REQ-INC-004 — VIP requesters

Requesters can be marked VIP. A VIP marker shows wherever the requester appears (list, record,
notifications to technicians). The flag can be used in views, SLA selection and rules.

- **Decision:** SAME.
- **Source:** sdp-area-02a §Screens (VIP marker); sdp-area-11 §Fields; architecture §2.6
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. An incident from a VIP shows the VIP marker in the list and on the record.
  2. A view filtered on "requester is VIP" returns only VIP incidents.
  3. An SLA policy with a VIP condition applies to VIP incidents only (rule engine in file 03).

#### REQ-INC-005 — Channel recorded automatically

The channel an incident came from (console, portal, email, phone, chat, mobile app, API,
MonetX, alert webhook, virtual agent, Teams, Slack, WhatsApp) is set automatically by the entry
point. Only the phone and walk-up channels are picked by hand. Admins can add channels.

- **Decision:** BETTER. In ServiceDesk Plus the mode is a manual list, so it is often wrong or
  empty and reports by channel cannot be trusted.
- **Source:** sdp-area-02b §Fields (mode); architecture §2.1 (omnichannel)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. An incident created from email has channel "email" without anyone choosing it.
  2. A technician creating an incident in the console can choose phone or walk-up; the default
     is phone.
  3. An API caller cannot set a channel that is reserved for another entry point (email,
     MonetX); the API refuses it.

#### REQ-INC-006 — Category, subcategory and item

Incidents are classified in an admin-defined three-level tree: category, subcategory and item.
The pickers depend on each other, can be searched, and an admin can manage the tree in a tree
view. Categories can be disabled without breaking old incidents. A category can suggest a group.

- **Decision:** SAME.
- **Source:** sdp-area-02b §Fields (category chain); sdp-area-13 §Helpdesk customization
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Subcategory options show only after a category is chosen and only belong to that category.
  2. Changing the category clears a subcategory and item that no longer fit, and says so.
  3. A disabled category is not offered on new incidents but still shows on old ones.
  4. Search in the picker finds an item by name at any level.

#### REQ-INC-007 — Support level

Incidents carry a support level (tier 1 to 4 by default, admin-defined). The level can be used
in views, rules, assignment and reports.

- **Decision:** SAME.
- **Source:** sdp-area-02b §Fields (level); sdp-area-13 §Helpdesk customization
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Admins can rename, reorder, add and disable levels, each with translations.
  2. A rule can set the level, and the change is recorded in history.

#### REQ-INC-008 — Impact and urgency on clean scales

Impact measures how widely the incident is felt. Urgency measures how fast it must be fixed.
Each is a single, ordered scale, and the defaults are ready to use:

- impact: one person, a team, a department or site, the whole organisation;
- urgency: low, medium, high, critical.

Admins can rename values and add translations. A value list must not mix kinds of value.

- **Decision:** BETTER. ServiceDesk Plus mixes scope values with severity values in one impact
  list, and has overlapping values in urgency.
- **Source:** sdp-area-02b §Weak spots; sdp-area-13 §Helpdesk customization, §Weak spots; sdp-area-05 §Weak spots
- **SDP weak spot fixed:** "affects user / group / department / business" next to
  "high / medium / low" in one impact list; "normal" and "medium" both in urgency and priority.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A new tenant has exactly the default impact and urgency scales above, in a fixed order.
  2. Each value has a rank, so the matrix and reports can order them.
  3. Value lists are the same for console, portal, API and rules.

#### REQ-INC-009 — Priority matrix with sensible defaults

Priority is worked out from impact and urgency through a matrix that comes filled in for a new
tenant (proposed default in Appendix A). Admins can edit the matrix. The priority updates live
on the form as impact or urgency changes. Requesters set urgency (and impact, if allowed) but
never priority directly.

- **Decision:** BETTER. In ServiceDesk Plus the matrix ships empty, so priority is entirely
  manual and the SLA depends on someone remembering to set it.
- **Source:** sdp-area-13 §Helpdesk customization (priority matrix); sdp-area-12 §Screens; sdp-area-04 §Weak spots
- **SDP weak spot fixed:** every matrix cell is empty and overrides are on, so priority is
  always manual.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A new tenant's matrix has every cell filled with the Appendix A defaults.
  2. Setting impact "whole organisation" and urgency "critical" gives priority P1 on the form
     before saving, and the same on the server.
  3. Changing impact or urgency later recomputes priority and records why (matrix) in history.
  4. Saving the matrix with an empty cell is refused.

#### REQ-INC-010 — Priority override with permission and reason

A technician with the "change priority" permission can override the computed priority. They
must give a reason, and the record then shows that priority was set by hand. Clearing the
override brings back the matrix value.

- **Decision:** SAME (matrix override exists in ServiceDesk Plus), with reason and marker added.
- **Source:** sdp-area-13 §Helpdesk customization (override toggle)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Without the permission, the priority field is read-only, showing the reason.
  2. An override without a reason is refused.
  3. An overridden priority shows a "set by hand" marker until the override is cleared.

#### REQ-INC-011 — Never silently without priority or SLA

Every incident always has a priority. If impact and urgency are both unknown, the tenant's
default priority applies, and the record shows that it was defaulted. If no SLA policy matches,
the record shows a clear "no SLA applies" marker, and a built-in view lists such incidents.

- **Decision:** BETTER.
- **Source:** sdp-area-02b §Behaviour, §Weak spots; sdp-area-02c §Weak spots; sdp-area-03 §Behaviour, §Weak spots
- **SDP weak spot fixed:** a request without priority gets no SLA and no due date, and nothing
  says so; it can sit like that forever.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. An incident created with no impact, urgency or priority gets the default priority and a
     "defaulted" marker.
  2. An incident that matches no SLA policy shows the "no SLA" marker on the record and in the
     list.
  3. The built-in view "incidents without SLA" lists exactly those incidents, live.

#### REQ-INC-012 — Due dates from the SLA, overrides recorded

The applied SLA (file 03) sets the first response due and resolution due. The record and the
list show a countdown, a warning state before the due time and an overdue state after it. A
technician with permission can change a due date, with a reason. Changes to priority, category
or other SLA conditions re-evaluate the SLA, and the effect on due dates is shown.

- **Decision:** SAME.
- **Source:** sdp-area-02c §Automation (SLA by priority); sdp-area-11 §Fields (modifying due time); sdp-area-12 §Behaviour
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Raising priority from P3 to P1 recalculates both due dates and writes one history entry
     with old and new values.
  2. Without the permission, the due date fields are read-only.
  3. The countdown passes the warning threshold and then the overdue state live, with no reload.
  4. A paused incident shows "paused" instead of a running countdown (REQ-INC-044).

#### REQ-INC-013 — System times and counters

The system stamps these times and counts, and nobody can edit them:

- created time and first assigned time;
- first response time and resolved time;
- closed time and last reopened time;
- reopen count, reassignment count, and time spent paused.

- **Decision:** SAME.
- **Source:** sdp-area-02c §Screens (details tab), §Automation
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Each stamp is set exactly once by the event that defines it (first response by the first
     public reply or public note).
  2. Reopening increases the reopen count and keeps earlier resolved and closed times in
     history.
  3. The stamps are available as list columns, filters and report fields.

#### REQ-INC-014 — Custom fields on incidents

Admins can add custom fields to incidents in these types:

- single-line text, multi-line text, number and decimal;
- currency, date and date-time;
- pick list, multi-select, check box and radio;
- email, phone, web link, and a lookup to a user, asset or configuration item.

Custom fields work like built-in ones in forms, lists, filters, rules, reports, exports and the
API. Each field has a label and help text in each language.

- **Decision:** SAME.
- **Source:** sdp-area-13 §Additional Fields; sdp-area-12 §Config (template designers, field types); architecture §6.6
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A new pick-list custom field can be added to a template, filled in, filtered on in a view
     and exported, without a deployment.
  2. A frequently filtered custom field can be promoted to an indexed column without a code
     change.
  3. A custom field key is never shown to users; its label is.
  4. Deleting a custom field in use asks for confirmation and keeps its old values in history.

#### REQ-INC-015 — Assets and configuration items on an incident

An incident can list several affected assets and configuration items, picked by name, tag or
serial number. It can offer the requester's own assets first. The linked records show the
incident in their own associations.

- **Decision:** SAME.
- **Source:** sdp-area-02b §Fields (assets); sdp-area-07 §Behaviour (links to requests); D-044 (REQ-WI-025 in Essentials)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Adding an asset to an incident shows the incident in the asset's associations, live.
  2. The asset picker lists the requester's assets first.
  3. Adding or removing an asset is recorded in the history of both records.

#### REQ-INC-016 — Site and department

An incident carries a site and a department. By default they come from the requester. The site
decides the operating hours and holidays the SLA uses, and which site-scoped technicians can
see the incident.

- **Decision:** SAME.
- **Source:** sdp-area-02b §Fields (site); sdp-area-11 §Fields (site form: site rules and SLAs apply automatically)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Choosing a requester fills site and department from their profile, and the user can change
     them.
  2. A technician scoped to site A cannot see an incident at site B.
  3. Changing the site re-evaluates the SLA calendar.

---

## 3. Creating incidents and incoming channels

#### REQ-INC-017 — Create form for technicians

Technicians create incidents from a form opened from the global "new" action, the list or a
keyboard shortcut. They pick a template from a searchable, grouped picker, with the tenant's
default template preselected. After saving they land on the new record. A "save and create
another" option keeps them on the form.

- **Decision:** SAME.
- **Source:** sdp-area-02b §Screens; sdp-area-01 §Actions (new request panel)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. The create form opens with the default template, and the template picker can search all
     incident templates by name.
  2. Saving shows the new display ID and opens the record.
  3. "Save and create another" clears the form but keeps the template and requester if the user
     ticks "keep requester".

#### REQ-INC-018 — Quick create

A compact quick-create dialog lets a technician log an incident with subject, requester and
optional priority without leaving the current screen. All template defaults and rules still
apply.

- **Decision:** SAME.
- **Source:** sdp-area-13 §Advanced Portal Settings (quick incident option)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Quick create from the list adds the new row to the list live.
  2. A rule that makes a field required on creation still blocks quick create, and the dialog
     shows the missing field.

#### REQ-INC-019 — Unsent form drafts are kept

If the create form is closed, the browser crashes or the session expires, the entered values
are kept as a personal draft and offered back the next time the form opens.

- **Decision:** NEW.
- **Source:** sdp-area-12 (12b) §Weak spots (typed text lost)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Typing a subject and description and then reloading the page brings back both values with
     an option to discard them.
  2. A draft is visible only to its author and is deleted when the incident is saved or the
     draft is discarded.

#### REQ-INC-020 — Log an incident already resolved

A technician can resolve an incident at creation, for example a fix on a phone call. They
enter the resolution and choose a resolved status on the form. The incident is stamped as a
first-contact resolution (REQ-INC-102).

- **Decision:** SAME.
- **Source:** sdp-area-02b §Fields (resolution on create)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Creating with a resolution and a resolved status gives a resolved incident with created,
     responded and resolved times set.
  2. Closure rules (REQ-INC-094) apply to this path as well.

#### REQ-INC-021 — Knowledge suggestions while typing

While the subject and description are typed, matching knowledge articles appear in a side
panel without moving the form (REQ-WI-012). A technician can open an article, copy it into the
resolution, or link it to the incident. By default only approved articles are suggested.

- **Decision:** BETTER. Same capability. Suggestions use approved content only by default, and
  never shift the form.
- **Source:** sdp-area-02b §Screens (suggested solutions); sdp-area-08 §Behaviour (suggestions match unapproved content)
- **SDP weak spot fixed:** unapproved articles are suggested by default, and the suggestion
  banner moves the save button.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Typing words that match an approved article lists it within one second.
  2. An unapproved article is not suggested unless the tenant setting allows it.
  3. Copying an article into the resolution records the link between the article and the
     incident.

#### REQ-INC-022 — Possible duplicate warning

While an incident is created, open incidents that look similar are shown in the side panel.
Similarity means the same requester with a similar subject, or the same asset or configuration
item, or similar text. The technician can open one, link the new incident to it, or attach it
as a child of an open major incident.

- **Decision:** NEW. ServiceDesk Plus has nothing like this at creation (product-plan triage
  agent: duplicate detection).
- **Source:** product-plan §7.3 (triage agent); architecture §2.10 (similar tickets)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Creating a second incident from the same requester with nearly the same subject within an
     hour shows the first one as a possible duplicate.
  2. Choosing "this is a duplicate" links the two incidents and records it on both.
  3. The suggestion only lists incidents the user may see.

#### REQ-INC-023 — Email creates incidents

Mail to a configured support mailbox creates an incident. The sender becomes the requester, the
subject becomes the subject, and the body becomes the description, with signatures and quoted
history trimmed. Attachments and inline images are kept. Mailboxes are read over IMAP,
Microsoft Graph or the Gmail API. Messages are marked as read or moved, never deleted, by
default. One mailbox can be set to create incidents and another service requests.

- **Decision:** SAME. ServiceDesk Plus deletes fetched mail from the mailbox; we keep the mail
  by default.
- **Source:** architecture §2.1 (email to ticket), §6.8; sdp-area-13 §Mail
- **SDP weak spot fixed:** the mail server set-up warns that every message is deleted from the
  polled mailbox.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. An email with two attachments to the support mailbox creates one incident within the poll
     interval, with both attachments scanned and attached.
  2. The incident's channel is email and the original email can be viewed from the timeline.
  3. The source message is left in the mailbox, marked as read or moved to a processed folder.
  4. A mailbox connection failure is shown to admins in the product (REQ-WI-009), not only in
     logs.

#### REQ-INC-024 — Email replies thread into the incident

Replies to incident emails are added to the conversation of that incident, matched by message
headers and by a ticket token in the subject. Loops are prevented: auto-replies, bounces,
mailing-list mail and mail from our own addresses never create incidents or replies. The same
email received twice is processed once.

- **Decision:** SAME.
- **Source:** architecture §2.1, §6.8
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A requester's reply to a notification is added to the right incident even if they edit the
     subject but keep the token.
  2. An out-of-office auto-reply is logged as a system entry and does not reopen the incident or
     notify the technician.
  3. A mail loop with another system stops after the first message.
  4. The same message ID received twice is added once.

#### REQ-INC-025 — Set fields from an email

Senders who are allowed to can set incident fields from an email using a simple
`field = value` block in the body. Examples are category, priority, group, technician and
template. The fields that can be set this way, and who may use it, are configurable. Values
that cannot be applied are listed in a reply to the sender.

- **Decision:** SAME.
- **Source:** sdp-area-13 §Mail (email command)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. An email from an allowed sender with a valid priority line creates the incident with that
     priority and records the source as email.
  2. An invalid value is ignored, the incident is still created, and the sender is told which
     line failed.
  3. A sender who is not allowed cannot set fields; the block is kept as plain text.

#### REQ-INC-026 — Block unwanted mail

Admins can define block rules (sender, domain, subject or body pattern) for inbound mail.
Matching messages create nothing. They are kept in a reviewable quarantine list for a set
period.

- **Decision:** SAME, plus a quarantine so blocked mail can be checked.
- **Source:** sdp-area-13 §Mail (mail filter)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Mail matching a block rule creates no incident and appears in quarantine.
  2. An admin can release a quarantined mail, which then creates the incident.

#### REQ-INC-027 — Unknown senders

Each mailbox has a policy for mail from addresses that are not known users. It can create the
requester automatically (optionally only for allowed domains), or hold the mail for review, or
reject it with a polite reply.

- **Decision:** SAME.
- **Source:** sdp-area-13 §Mail (accept emails from unknown users)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. With "create requester for allowed domains", mail from a new address in an allowed domain
     creates the user and the incident.
  2. Mail from an unknown address outside allowed domains follows the hold or reject setting.

#### REQ-INC-028 — Requesters report incidents in the portal

Requesters report an issue in the self-service portal with the requester layout of an incident
template. The portal shell, home and catalog are specified in file 02. They see knowledge
suggestions as they type, can attach files, and get the new ID straight away.

- **Decision:** SAME.
- **Source:** sdp-area-03 §Screens (portal); architecture §2.15
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A requester can submit an incident with subject, description and attachment and sees its
     ID.
  2. The requester never sees technician-only fields (group, technician, internal priority
     override).
  3. The new incident appears in the technician list live.

#### REQ-INC-029 — Create from an asset or configuration item

From an asset or configuration item, a user can raise an incident. It opens the create form
with that item and its user already filled in.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Actions (raise request from asset, create incident from CI), §Behaviour; D-044 (REQ-WI-025 in Essentials)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Raising from an asset fills the asset and its assigned user as requester.
  2. The asset shows the new incident in its associations, and both records record the link.

#### REQ-INC-030 — MonetX problems become incidents

The MonetX connector turns each MonetX problem into one incident. It keeps the incident in step
while the problem changes, adds a note on each MonetX update, and resolves the incident when
MonetX reports recovery. Admins set which MonetX problems create incidents, with which template,
priority mapping and group. The connector only receives problems and reads from the MonetX API;
correlation and de-duplication stay in MonetX.

- **Decision:** NEW. ServiceDesk Plus needs OpManager for alarm-to-ticket.
- **Source:** architecture §2.14, §6.8; ADR-017; D-001; D-050; product-plan §4.3 (pillar 3)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A MonetX problem matching a policy creates exactly one incident with channel MonetX and
     the mapped priority.
  2. A repeat or updated delivery of the same problem updates that incident and never creates
     a second one.
  3. By default, a MonetX recovery resolves the incident with a system note. If a technician
     has taken it over, it stays open, gets a "source recovered" note and the assignee is
     notified. Both behaviours are configurable per tenant (D-050).
  4. The connector makes no write call to MonetX and does no correlation itself.

#### REQ-INC-031 — Generic alert webhook

Other tools can create and update incidents through a signed inbound alert webhook with a
documented payload. The webhook uses the same one-alert-one-incident key and recovery
behaviour as REQ-INC-030.

- **Decision:** NEW.
- **Source:** architecture §2.14 (generic alert webhook); ADR-017
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A correctly signed alert creates an incident; a badly signed one is refused and logged.
  2. Two alerts with the same alert key update one incident.
  3. A "resolved" alert resolves that incident following the tenant policy.

#### REQ-INC-032 — Other channels

Incidents can also be created from live chat, the virtual agent, Microsoft Teams, Slack,
WhatsApp, phone systems (screen pop and call logging), the mobile app and the REST API. Each
channel keeps its conversation threaded on the incident. Connector set-up is in file 12.

- **Decision:** SAME.
- **Source:** architecture §2.1 (omnichannel logging), §2.14; product-plan §5 (unified inbox)
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. Each channel creates incidents with the right channel value and requester match.
  2. A requester reply in the channel is added to the same incident's conversation.
  3. A technician's public reply is delivered back to the channel the requester used.

#### REQ-INC-033 — Copy an incident

A technician can copy an incident one or more times. Each copy gets a new ID and a history
entry naming the original, and its subject is marked as a copy so the two are easy to tell
apart. The technician chooses what to carry over: fields, attachments, tasks.

- **Decision:** BETTER. ServiceDesk Plus gives copies the identical subject.
- **Source:** sdp-area-02c §Fields (duplicate request), §Behaviour, §Weak spots; sdp-area-04 §Weak spots
- **SDP weak spot fixed:** copies have exactly the same subject and look like duplicates in
  the list.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Copying INC-10 twice makes two incidents whose history names INC-10 and whose subjects are
     marked as copies.
  2. Conversations, worklogs and history are never copied.
  3. The number of copies is limited (default maximum 20) and the limit is explained.

#### REQ-INC-034 — Scheduled recurring incidents

Admins can schedule incidents to be created on a recurring timetable (daily, weekly, monthly,
yearly or custom) from a template, for preventive maintenance and routine checks. Each run is
logged. A failed run is shown and notified.

- **Decision:** SAME.
- **Source:** sdp-area-01 §Screens (maintenance module); sdp-area-13 §Announcement and Maintenance; architecture §2.15 (preventive maintenance)
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. A weekly schedule creates one incident each week from its template, in the tenant time
     zone.
  2. Each run appears in the schedule's log with the created ID or the error.
  3. Pausing a schedule stops new runs without deleting the history.

---

## 4. Templates and forms

#### REQ-INC-035 — Incident templates

Admins create incident templates. A template chooses the fields shown, their default values,
which fields are required, and whether requesters can use it in the portal. Templates can be
grouped and searched, copied, disabled and set as the default. Each template can attach a life
cycle (REQ-INC-049) and a workflow (file 03).

- **Decision:** SAME.
- **Source:** sdp-area-02b §Screens (template switching); sdp-area-03 §Screens (incident template list); sdp-area-12 §Config (template designers)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A template with default category and group fills those fields on the create form.
  2. A disabled template is not offered but still opens on incidents created from it.
  3. Copying a template creates an independent copy that is marked as a copy.
  4. Only templates marked for requesters appear in the portal.

#### REQ-INC-036 — Form designer with technician and requester layouts

A drag-and-drop designer arranges a template's form into sections (one or two columns,
collapsible), with field label position and a separate requester layout. For each field it
sets required, requester may set, and requester may see. New custom fields can be added from
inside the designer, and the form can be previewed in both layouts and both text directions.

- **Decision:** SAME.
- **Source:** sdp-area-12 §Config (template designers); architecture §2.1 (incident templates)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Moving a field into a new section and saving shows it there on the next create form.
  2. A field marked "requester may not see" is never sent to the portal API.
  3. The preview shows the technician and requester layouts in left-to-right and right-to-left.

#### REQ-INC-037 — Form rules, the same in the browser and on the server

Form rules show, hide, require, lock or set fields based on conditions over other fields, for
example "if category is network, require location". The browser applies them for instant
feedback, and the server enforces the same rules on save, so the API cannot get around them.

- **Decision:** BETTER. Rules are also enforced on the server, so API and email paths obey them.
- **Source:** architecture §6.6; sdp-area-12 (12b) §Config (form rules)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A rule that requires a field when the category is network blocks saving in the UI and
     makes the API return a field error with the same code.
  2. Hidden fields keep their value only when the rule says so; otherwise they are cleared on
     save and the clear is recorded.
  3. One shared rule test suite gives identical results in the browser evaluator and the
     server evaluator.

#### REQ-INC-038 — Guidance on a template

A template can show a help card and reference documents to technicians and to requesters, for
example "before you log a VPN issue, check these steps".

- **Decision:** SAME.
- **Source:** sdp-area-12 §Config (help card and reference documents)
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. A template's help card shows on the create form for that template only.
  2. Help cards have per-language text and render right-to-left in Arabic and Urdu.

#### REQ-INC-039 — Switching template keeps what was typed

Changing the template on the create form keeps every value the new template also has, warns
about values that will be dropped, and never reloads the page.

- **Decision:** BETTER. In ServiceDesk Plus, switching template reloads the form.
- **Source:** sdp-area-02b §Screens (template switching)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Subject, description and requester survive a template switch.
  2. A value in a field missing from the new template is listed in a warning before the switch
     completes, with an option to cancel.

#### REQ-INC-040 — Tasks and checklists from the template

A template can include tasks and checklists. They are created on the incident automatically
when it is created. Each one can be set to be created only when a condition matches.

- **Decision:** SAME.
- **Source:** sdp-area-12 (12b) §Config (template tasks); sdp-area-12 (12b) §Behaviour
- **SDP weak spot fixed:** the template task's creation did not show in the request history,
  so when it fired was unknown.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. An incident created from a template with two tasks has those two tasks, and history
     records their creation by the template.
  2. A conditional template task is created only when its condition matches at creation.

#### REQ-INC-041 — Reply templates

Technicians can insert reply templates into replies and notes. A template has a subject, a
body with variables (requester name, ID, status, due date ...) and a language variant per
supported language. Templates can be personal or shared with groups.

- **Decision:** SAME.
- **Source:** sdp-area-13 §Templates & Forms (reply template); architecture §2.1 (reply templates, canned responses)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Inserting a template fills its variables with the incident's values.
  2. For a requester whose language is Arabic, the Arabic variant is offered first.
  3. A variable with no value shows a clear placeholder in the editor, never the raw variable
     name.

#### REQ-INC-042 — Resolution templates

Technicians can fill the resolution from resolution templates, which can be filtered by
category.

- **Decision:** SAME.
- **Source:** sdp-area-02c §Screens (resolution tab); sdp-area-13 §Templates & Forms
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Choosing a resolution template fills the resolution editor, which stays editable.
  2. Templates can be limited to categories and appear first for incidents in those categories.

#### REQ-INC-043 — No admin scripts run inside the browser form

SupportX does not run admin-written JavaScript inside incident forms. The same results come
from declarative form rules (REQ-INC-037) and from sandboxed server-side custom functions
(file 03).

- **Decision:** SKIP. Admin scripts running in every technician's browser are a security and
  upgrade risk (architecture §6.7: custom code runs only in an isolated sandbox). Form rules
  plus sandboxed functions give the same outcomes.
- **Source:** sdp-area-12 (12b) §Config (custom scripts); architecture §6.7, §11.4
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. No API or admin screen accepts browser script for forms.
  2. The migration tool reports any ServiceDesk Plus custom scripts as items to rebuild by hand
     (architecture §18.2).

---

## 5. Statuses, life cycles and transitions

#### REQ-INC-044 — Statuses with a fixed meaning

Admins define incident statuses (name, colour, translations, description). Each status belongs
to exactly one status category, and the category fixes its behaviour:

| Category | SLA clock | Meaning |
|---|---|---|
| open | runs | someone needs to act |
| paused | paused | waiting on the requester or a third party |
| resolved | stopped | fix given, waiting for confirmation |
| closed | stopped, final | finished |
| canceled | stopped, final | not needed |

- **Decision:** BETTER. ServiceDesk Plus uses timer types per status, and by default it pauses
  the SLA on "In Progress", which is when the work is being done.
- **Source:** sdp-area-13 §Helpdesk customization (status types); sdp-area-12 §Config (statuses), §Weak spots
- **SDP weak spot fixed:** the default "In Progress" status stops the SLA timer, and the SLA
  form itself has no pause control.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Saving a status without a category is refused.
  2. Moving an incident into a paused status pauses both SLA clocks, and moving it back resumes
     them; history records the pause time.
  3. Reports can group by status category as well as by status.
  4. A status in use cannot be deleted; it can be disabled for new transitions.

#### REQ-INC-045 — Default statuses and life cycle

A new tenant gets a ready-made incident life cycle (Appendix A): new, assigned, in progress,
awaiting requester, awaiting third party, resolved, closed, canceled. It comes with the allowed
transitions between them. It works on day one with no set-up.

- **Decision:** NEW. ServiceDesk Plus ships a flat list of nine statuses with no transitions,
  and several of them overlap.
- **Source:** sdp-area-02b §Fields (status list); sdp-area-12 (12b) §Behaviour (major incident life cycle)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A new tenant's first incident follows the default life cycle with no admin set-up.
  2. Only the transitions in Appendix A are offered from each status.
  3. Admins can copy and change the default life cycle, but cannot delete it while templates
     use it.

#### REQ-INC-046 — Status changes only through allowed transitions

The status changes only through the transitions the life cycle allows. That holds for every
path: the record page, the list, the board, bulk actions, email, rules, workflows, the API and
AI agents. There is no free-choice status field. A transition that is not allowed is refused
with a clear reason.

- **Decision:** BETTER. In ServiceDesk Plus a status can be changed by hand outside the
  workflow, which is then only flagged as violated.
- **Source:** sdp-area-05 §Weak spots; sdp-area-02c §Behaviour (reopen via edit); sdp-area-12 (12b) §Behaviour (wait node discarded on manual change)
- **SDP weak spot fixed:** manual status changes are allowed and only flagged "violated". A
  hand change of status throws away a waiting workflow step.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. The API refuses a status change that is not an allowed transition with a problem code, on
     every path.
  2. The UI offers only allowed transitions for the current status and user.
  3. A workflow waiting on a status reacts to a transition made by a person; it is not silently
     dropped (behaviour defined in file 03).

#### REQ-INC-047 — Reasons for status changes

Each transition can ask for a reason: free text, a pick list, or both. By default a reason is
required when pausing, canceling, reopening and moving back from resolved. The reason shows in
history and on the record while the incident stays in that status.

- **Decision:** BETTER. ServiceDesk Plus can ask for a reason on hold, but does not require it
  by default and does not show it on the record.
- **Source:** sdp-area-13 §Advanced Portal Settings (status-change reason); sdp-area-02c §Fields (cancel reason)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Moving to "awaiting requester" without a reason is refused under the default settings.
  2. The reason is visible on the record header while the status lasts, and in history
     afterwards.
  3. Admins can turn the reason prompt on or off and make it required or optional per
     transition.

#### REQ-INC-048 — Required fields per transition

A transition can require fields, for example resolution and closure code before "resolved".
The user is prompted for only those fields in a small dialog when they run the transition.

- **Decision:** SAME.
- **Source:** sdp-area-12 §Config (life cycle transitions, during); sdp-area-12 (12b) §Behaviour (resolve transition demanded resolution)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Running a transition that needs a field opens a dialog with only the missing fields.
  2. The API refuses the transition without those fields, with field errors.

#### REQ-INC-049 — Life cycle designer

Admins draw incident life cycles on a canvas: statuses as nodes, transitions as links. For each
transition they set:

- who may run it (roles, groups, the requester, the group head, the reporting manager) and when
  it is offered (conditions);
- the fields it requires;
- the actions that run after it.

Life cycles have draft and published versions, and an incident keeps the version it started
with until it is migrated. Each validation message says exactly what to fix.

- **Decision:** BETTER. Same power, plus versions and clear validation.
- **Source:** sdp-area-12 §Config (life cycle transitions); sdp-area-12 (12b) §Screens, §Weak spots; architecture §2.1 (request life cycle)
- **SDP weak spot fixed:** publishing fails without saying that a template must be attached,
  and the template picker then disappears.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Publishing a life cycle with a status that has no way out is refused, and the message
     names the status.
  2. A transition limited to group heads is not offered to other technicians, and the API
     refuses it with 403.
  3. Publishing version 2 does not change incidents running on version 1 until an admin
     migrates them.
  4. The designer works with keyboard and in right-to-left layout.

#### REQ-INC-050 — Assignment moves the status sensibly

By default, assigning a new incident to a technician moves it from new to assigned. The first
public reply or a technician's "start work" moves it to in progress. Unassigning an assigned
incident moves it back to new. Admins can switch these moves off or change them per life cycle.

- **Decision:** BETTER. In ServiceDesk Plus assigning does not change the status, so status
  has to be set by hand and is often stale.
- **Source:** sdp-area-02c §Automation (assignment does not change status), §Weak spots
- **SDP weak spot fixed:** after assigning or taking a request, status stays "open" and the
  life cycle says "not assigned".
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Assigning a "new" incident sets "assigned" in the same change, and history shows both.
  2. The first public reply by the assignee moves "assigned" to "in progress".
  3. With the automatic moves switched off, assignment leaves the status unchanged.
  4. Assigning an incident that is already in progress keeps it in progress.

#### REQ-INC-051 — Requester reply resumes a paused incident

When the requester replies (email, portal or chat) to an incident that is waiting on them, it
moves back to in progress, the SLA clock resumes, and the assignee is notified. This is on by
default and configurable per status.

- **Decision:** SAME, but on by default. ServiceDesk Plus has the option, off by default.
- **Source:** sdp-area-13 §Reopen settings (on hold reply)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A requester email reply to an "awaiting requester" incident moves it to "in progress" and
     resumes the clock.
  2. A reply while waiting on a third party does not change the status by default; the
     assignee is notified.

#### REQ-INC-052 — Board moves respect the life cycle

On the board, dragging a card to another status column runs that transition. While dragging,
columns the card cannot move to are greyed out. If the transition needs a reason or fields,
the prompt opens before the move completes.

- **Decision:** BETTER.
- **Source:** sdp-area-02a §Screens (board drag to change status)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Dropping a card on an allowed column changes the status after any required prompt.
  2. Dropping on a greyed-out column does nothing and explains why.
  3. Other viewers of the board see the card move live.

---

## 6. Assignment and ownership

#### REQ-INC-053 — Assign to a group and a technician

A user assigns an incident to a group and, optionally, a technician. The technician list shows
only members of the chosen group, with each person's availability and current open load. It
can be searched and limited to people available now. Assignment and auto-assignment rules live
in file 03.

- **Decision:** BETTER. In ServiceDesk Plus the technician list is not filtered by the chosen
  group, and the "online only" switch is hidden inside the list.
- **Source:** sdp-area-02c §Fields (assign), §Weak spots; sdp-area-04 §Weak spots; sdp-area-02b §Weak spots
- **SDP weak spot fixed:** the technician picker ignores the chosen group.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. After choosing group A, the technician list shows only group A's members.
  2. Each technician shows availability and their number of open incidents.
  3. Choosing a technician who is not in the group is refused unless the user has the
     "assign outside group" permission.
  4. Assignment changes are recorded and the new assignee is notified.

#### REQ-INC-054 — Take ownership

A technician can take an unassigned incident with one action. If the incident has no group and
the technician is in exactly one group that may handle it, that group is set too. Otherwise
they are asked to pick one.

- **Decision:** BETTER. In ServiceDesk Plus taking a request sets the technician but leaves the
  group empty.
- **Source:** sdp-area-02c §Behaviour (pick up left group blank); sdp-area-02a §Actions
- **SDP weak spot fixed:** after taking a request, its group stays blank.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Taking an unassigned incident with no group, as a member of one group, sets both
     technician and group.
  2. As a member of several eligible groups, the user is asked to pick one.
  3. Taking an incident someone else has just taken fails with a conflict that names them.

#### REQ-INC-055 — Reassign with a record of why

Reassigning to another group or technician can take a reason (required by default when moving
between groups). The previous and new assignee are notified. The reassignment count goes up.

- **Decision:** SAME.
- **Source:** sdp-area-02c §Behaviour (assign history); sdp-area-11 §Fields (assigning technician permission)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Moving an incident from group A to group B without a reason is refused under default
     settings.
  2. Both the old and the new assignee are notified, and history shows the reason.

#### REQ-INC-056 — Followers and sharing

Users can follow an incident to get its updates. Technicians with permission can add or remove
followers, and can share an incident with other users. A shared user gets read access and can
add notes, even outside their normal scope. Requesters can add colleagues as followers when the
tenant allows it.

- **Decision:** SAME.
- **Source:** sdp-area-02c §Fields (share request, manage followers); sdp-area-02a §Screens (shared views)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A follower receives notifications for public replies and status changes.
  2. A user the incident is shared with can open it, even though their scope would not show it.
  3. Removing a share removes access at once, including on open screens.

---

## 7. Conversations, replies and notes

#### REQ-INC-057 — One conversation timeline

The conversation tab shows, in time order:

- the description and every inbound and outbound message, with its channel;
- public and private notes;
- system notifications that were sent.

Each entry shows the author, time and visibility. Filters narrow it to messages, notes or
system entries. New entries appear live.

- **Decision:** SAME.
- **Source:** sdp-area-02c §Screens (conversations tab)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A requester email, a technician reply and a private note show in time order with clear
     visibility markers.
  2. Each filter shows only its kind of entry.
  3. A new inbound email appears in an open timeline within one second of being processed.

#### REQ-INC-058 — Reply, reply to all, forward

Technicians reply to the requester, reply to all participants or forward to someone from the
incident. The composer has To and CC, reply templates, attachments (including files already on
the incident), the technician's signature in their language, and a preview. Sent messages are
threaded so replies come back to the incident.

- **Decision:** BETTER. In ServiceDesk Plus the reply-all arrow opens nothing, and a reply
  attempt without mail replaces the conversation card with an error.
- **Source:** sdp-area-02c §Actions, §Behaviour, §Weak spots
- **SDP weak spot fixed:** the reply split button does nothing, and replying without mail set
  up breaks the conversation view.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A reply with one attachment reaches the requester, and their answer threads back into the
     same incident.
  2. Forward lets the user pick which existing attachments to include.
  3. Every option in the reply menu opens a working composer.

#### REQ-INC-059 — Delivery status of outgoing messages

Each outgoing message on the incident shows its delivery state: queued, sent, failed with a
readable reason, or retrying. Failed messages can be retried or edited and resent. Repeated
failures are raised to the assignee and to admins.

- **Decision:** NEW. ServiceDesk Plus shows no delivery state on a message.
- **Source:** sdp-area-02c §Behaviour (replies blocked by mail server); REQ-WI-009
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A reply to an address that bounces shows "failed" with the bounce reason on the message.
  2. A temporary mail outage queues messages and sends them when mail recovers, with no
     duplicates.
  3. A failed message can be resent from the timeline.

#### REQ-INC-060 — Work goes on when mail is not configured

If outgoing mail is not set up or is down, the incident still works. Notes, in-app
notifications, the portal and approvals in the app all go on working. The composer explains
that mail is not set up and who can fix it, and the reply is kept as a draft or queued.

- **Decision:** BETTER. In ServiceDesk Plus a missing mail server blocks replies, approvals,
  knowledge approval and surveys.
- **Source:** sdp-area-02b §Behaviour; sdp-area-02c §Edition notes; sdp-area-08 §Weak spots; sdp-area-13 §Surveys
- **SDP weak spot fixed:** without a mail server, approvals cannot be seen or acted on, and
  submitting for approval fails hard.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. With no mail configured, a technician can still add notes and change status, and the
     requester sees public notes in the portal.
  2. The composer shows a clear "mail is not set up" message with a link for admins; the typed
     reply is kept.
  3. Approvals on the incident can be acted on in the app with no mail.

#### REQ-INC-061 — Public and private notes

Technicians add notes that are private (staff only, the default) or public (the requester sees
them and is notified). Public and private notes look clearly different in every view. The
visibility can be switched after saving, with history, by users with permission.

- **Decision:** SAME.
- **Source:** sdp-area-02c §Fields (add notes), §Behaviour; sdp-area-13 §Advanced Portal Settings (note defaults)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A private note never reaches the requester through the portal, email, the API or AI
     answers.
  2. A public note appears in the portal live and notifies the requester (following
     notification rules).
  3. Making a private note public asks for confirmation and is recorded in history.

#### REQ-INC-062 — Edit and delete notes with history

Authors can edit or delete their own notes, and others' notes if they have permission. Each
edit keeps the earlier text in history. A deleted note leaves a "note deleted" entry with who
and when.

- **Decision:** SAME.
- **Source:** sdp-area-11 §Fields (editing/deleting own and others' notes)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Editing a note shows an "edited" marker, and the earlier text can be seen in history.
  2. Deleting someone else's note without permission is refused (403).

#### REQ-INC-063 — Mentions

Typing @ in a note lets the author mention a technician or a group. Mentioned people are
notified and can open the note directly. A mention gives no access the person did not already
have; the author is warned if the person cannot see the incident.

- **Decision:** NEW. ServiceDesk Plus has no mentions in notes.
- **Source:** architecture §2.1 (work on the ticket)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Mentioning a technician sends them an in-app notification that links to the note.
  2. Mentioning someone outside the incident's scope shows a warning and does not notify them.

#### REQ-INC-064 — Safe rich text

Descriptions, replies, notes and resolutions use one rich-text editor. It has formatting,
lists, tables, links, code blocks, pasted screenshots and inline images, and works right to
left. The server sanitises every stored value with an allow-list, and incoming email HTML is
sanitised the same way. The editor and the sanitiser are built in the first incidents work
package (D-040).

- **Decision:** BETTER. One safe editor everywhere, with server-side sanitising.
- **Source:** D-036; D-040; architecture §11, §11.4; sdp-area-02b §Fields (description editor)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A script tag or event handler in a description or inbound email is removed before storage.
  2. A pasted screenshot is uploaded as an attachment and shown inline.
  3. Arabic text in the editor is laid out right to left, and mixed Arabic and English text
     keeps its order.

#### REQ-INC-065 — First response is stamped automatically

The first public reply or public note by a technician stamps the first response time and meets
the first response SLA. Admins choose which actions count. An internal note never counts by
default.

- **Decision:** BETTER. In ServiceDesk Plus the first response is stamped by resolving, or by
  ticking a box on a worklog, and the note and reply options are off by default.
- **Source:** sdp-area-13 §Advanced Portal Settings (first response time); sdp-area-02c §Automation (resolving stamped responded time); sdp-area-02c §Fields (worklog: consider as first response)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A first public reply stamps the first response time and stops the first response clock.
  2. A private note does not stamp it under default settings.
  3. Later replies do not change the stamp.

#### REQ-INC-066 — Extra people to keep informed

An incident can carry a list of extra email addresses (CC) that receive public updates. Inbound
CC addresses on the first email are added automatically (configurable).

- **Decision:** SAME.
- **Source:** sdp-area-02c §Behaviour (edit form has emails to notify); sdp-area-13 §Requester Portal (requesters adding recipients)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. An address in the incident's CC list receives public replies but not private notes.
  2. With the setting on, CC addresses on the first email are added to the list.

---

## 8. Worklogs and time

#### REQ-INC-067 — Worklogs

Technicians log time on an incident. Each worklog has an owner (default: the user), a worklog
type, a start and end time or a duration and a description. Validation stays
consistent: the end cannot be before the start, and the duration and the times agree. The
incident shows total time, per technician and per type.

- **Decision:** BETTER. ServiceDesk Plus accepts a worklog with an end time and no start time.
- **Source:** sdp-area-02c §Fields (add worklog), §Behaviour, §Weak spots; D-047
- **SDP weak spot fixed:** a worklog saves with a blank start, and the end picker rewrites the
  time taken (sdp-area-06 6b §Weak spots).
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A worklog with an end time before its start time is refused with a field error.
  2. Entering a start and a duration fills the end time, and the other way round.
  3. The worklog tab shows totals per technician and per type, and updates live.

#### REQ-INC-068 — Worklog costs and billable time

Each worklog can be marked billable and can carry technician cost (time × the technician's
cost per hour) and other costs, in a currency with the exchange rate of the day. The incident
shows its total cost and its billable time. Only roles with permission see cost rates. Time
itself is MVP (REQ-INC-067); costs and billable time are V1 (D-047).

- **Decision:** SAME.
- **Source:** sdp-area-02c §Fields (worklog currency and charges); sdp-area-11 §Fields (cost per hour, can view cost); D-047
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A 1.5-hour worklog by a technician costing 40 per hour shows a technician cost of 60.
  2. A user without the cost permission sees no rate or cost in the UI, API or export.
  3. The incident shows billable and non-billable time totals separately.

#### REQ-INC-069 — Personal work timer

A technician can start and stop a timer on an incident. Stopping it opens a worklog already
filled with the elapsed time and the timer comment. If the incident is resolved or closed
while a timer runs, the time is saved as a draft worklog for the technician, never lost.

- **Decision:** BETTER. In ServiceDesk Plus, stopping the timer warns that the data will be
  lost, yet then opens an empty worklog. Closing stops the timer without asking.
- **Source:** sdp-area-02c §Behaviour (timer), §Automation (closing stopped the timer), §Weak spots
- **SDP weak spot fixed:** the "add worklog" from the timer opens with 0 hours.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Stopping a timer after 25 minutes opens a worklog with 25 minutes filled in.
  2. Closing the incident with a running timer creates a draft worklog with the elapsed time,
     and tells the technician.
  3. The timer shows on every screen of the record and survives a page reload.

#### REQ-INC-070 — Worklog rules

Admins can block worklogs on closed incidents, decide whether non-working hours count, and
start the timer automatically when the owner opens the incident. These are tenant settings.

- **Decision:** SAME.
- **Source:** sdp-area-13 §Advanced Portal Settings (worklog settings)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. With the block on, adding a worklog to a closed incident is refused, and the reason is
     shown.
  2. With auto-start on, opening an incident you own starts your timer once.

#### REQ-INC-071 — Time analysis

The record shows how long the incident has been open, and how long it spent:

- in each status;
- with each group and each technician;
- paused.

It also shows response and resolution against the SLA.

- **Decision:** SAME.
- **Source:** sdp-area-02c §Screens (time elapsed analysis)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. An incident that was two hours in progress and one hour paused shows both durations
     correctly.
  2. The figures use business hours or calendar hours, and the screen says which.
  3. Reopening keeps earlier time and adds new time; nothing is reset.

---

## 9. Tasks

#### REQ-INC-072 — Tasks on an incident

Technicians add tasks to an incident. A task has a title, owner, group, status (its own simple
life cycle), priority and due date. The incident shows "done / total" and lists tasks in an
order the user can change. Task owners can work on a task without access to the whole
incident, if the tenant allows it.

- **Decision:** SAME.
- **Source:** sdp-area-02c §Fields (add task); sdp-area-11 §Fields (task technician access)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Adding a task updates the "done / total" counter live for everyone viewing the incident.
  2. Reordering tasks is saved and seen by others.
  3. A task owner with task-only access can update the task but cannot see private notes on
     the incident.

#### REQ-INC-073 — Task details

Tasks also carry a description, task type, scheduled and actual start and end, estimated
effort, percent complete, extra cost, and a reminder before the scheduled start.

- **Decision:** SAME.
- **Source:** sdp-area-02c §Fields (add task)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A scheduled end before the scheduled start is refused.
  2. The reminder before scheduled start notifies the owner at the chosen offset.

#### REQ-INC-074 — Task templates

Admins keep task templates. Technicians add tasks from a template, singly or as a set.

- **Decision:** SAME.
- **Source:** sdp-area-02c §Fields (task template list); sdp-area-13 §Templates & Forms (task template)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Adding from a template creates the task with the template's fields, ready to edit.
  2. A disabled task template is not offered.

#### REQ-INC-075 — Task dependencies that are enforced

A task can depend on other tasks finishing first. A task whose predecessors are not done shows
as blocked and cannot be started or completed until they are. Admins can turn the block into a
warning.

- **Decision:** BETTER. In ServiceDesk Plus dependencies can be broken silently.
- **Source:** architecture §2.1 (tasks with dependencies); sdp-area-06 (6b) §Weak spots
- **SDP weak spot fixed:** dependencies can be violated with no warning, and are only created
  in a diagram view.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Starting a task whose predecessor is open is refused with a message naming the
     predecessor.
  2. Completing the predecessor unblocks the task live.
  3. A dependency can be added from the task form; a dependency loop is refused.

#### REQ-INC-076 — Task notifications and "my tasks"

Task owners are notified when a task is assigned, nearly due or overdue. Every user has a
"my tasks" list that covers tasks from every work item type and projects.

- **Decision:** SAME.
- **Source:** sdp-area-01 §Screens (tasks tab, activities); sdp-area-02c §Fields (task notify before start)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Assigning a task to someone notifies them, and it appears in their "my tasks" list live.
  2. An overdue task is marked overdue in "my tasks" and on the incident.

---

## 10. Checklists

#### REQ-INC-077 — Checklists on an incident

Technicians add checklists to an incident, from scratch or from the library. Each item records
who ticked it and when. The incident shows progress per checklist. There is no small fixed
limit on items: the default maximum is 100 and admins can change it.

- **Decision:** SAME, with a higher, configurable item limit (ServiceDesk Plus allows 25).
- **Source:** sdp-area-02c §Fields (new checklist), §Behaviour
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Ticking an item records the user and time and updates progress live.
  2. Empty items are ignored on save and the user is told.
  3. A checklist added from the library can be changed on the incident without changing the
     library copy.

#### REQ-INC-078 — Checklist library and import

Admins keep a library of checklists and reusable items. Items can be imported from CSV, and
the import reports rows it rejected.

- **Decision:** SAME.
- **Source:** sdp-area-13 §Checklists & Items; sdp-area-02c §Fields (add from CSV)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Importing a CSV with one bad row imports the good rows and lists the bad one with a reason.
  2. Library checklists can be translated.

---

## 11. Attachments

#### REQ-INC-079 — Safe attachments

Files can be attached to the incident, to replies, to notes and to tasks: by drag and drop,
file picker or paste, several at once. Files go straight to object storage. They are scanned
for malware before anyone can open them, encrypted per tenant, and limited by type and size
(tenant settings). Images and PDFs preview in the browser. The scan state is visible while a
file is checked.

- **Decision:** BETTER. Adds a malware scan, a visible scan state, per-tenant encryption and
  previews.
- **Source:** architecture §6.8 (files), §11.3; sdp-area-02b §Fields (attachments)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. An infected test file is marked as blocked and can never be downloaded.
  2. A file over the size limit is refused before upload with the limit shown.
  3. Downloading needs a fresh short-lived link checked against the user's access.
  4. Image and PDF attachments preview without downloading.

#### REQ-INC-080 — All attachments in one place

The incident has one attachments view that lists every file on the incident, its replies,
notes and tasks. It shows the file's source, uploader and date, and can download several files
together.

- **Decision:** NEW. ServiceDesk Plus spreads files across the conversation.
- **Source:** sdp-area-02c §Screens
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A file attached to a requester's email reply appears in the attachments view with its
     source.
  2. Selecting three files downloads them as one archive.

#### REQ-INC-081 — Links to cloud files

Users can attach a link to a file in Google Drive, OneDrive, Dropbox or Box instead of
uploading it. Admins choose which services are allowed.

- **Decision:** SAME.
- **Source:** sdp-area-13 §Cloud Attachments
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. A cloud file link shows the file name and service and opens in the service.
  2. Disabled services are not offered.

---

## 12. Reminders

#### REQ-INC-082 — Personal reminders on an incident

A user can set a reminder on an incident: a short note, a date and time, and how long before
to alert them. Reminders show on the incident and in the user's reminder list. They can be
completed, reopened and deleted.

- **Decision:** SAME.
- **Source:** sdp-area-02c §Fields (add reminder); sdp-area-01 §Screens (reminders tab)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A reminder for 15:00 with a 15-minute alert notifies the user at 14:45 in their time zone.
  2. Reminders are personal; other users do not see them.
  3. Completing a reminder removes it from the open list and keeps it on the incident as done.

---

## 13. Approvals on incidents

#### REQ-INC-083 — Ask for approval on an incident

A technician can ask one or more people to approve an incident, for example to spend money on
a fix or to restore a backup. They choose approvers and a rule (any one, all, majority). The
approval shows on the incident with each pending approver and their decision. Approvers act in
the app, by email or on mobile. Approvals are built once in the engine, so the multi-stage
catalog approvals in file 02 reuse them.

- **Decision:** BETTER. In ServiceDesk Plus the approvals tab shows only a mail error, not who
  is pending, and "submit for approval" fails without mail.
- **Source:** sdp-area-02c §Actions (submit for approval), §Automation; sdp-area-02b §Weak spots; sdp-area-12 §Fields (approval rules)
- **SDP weak spot fixed:** you cannot see what or whom an approval is waiting for.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. After submitting, the incident lists every approver with "pending", live.
  2. An approver can approve in the app with no mail configured.
  3. With the "all must approve" rule, one rejection rejects the request, and the technician
     is notified.
  4. The requester of the incident cannot approve it when segregation of duties is on.

---

## 14. Linking, merging and conversion

#### REQ-INC-084 — Link related incidents

A technician links an incident to other incidents as "related", with an optional comment. The
link shows on both incidents, is recorded in both histories, and can be removed from either
side.

- **Decision:** BETTER. Links are symmetrical and recorded on both sides.
- **Source:** sdp-area-02a §Fields (link request dialog); sdp-area-02c §Behaviour (link); sdp-area-05 §Behaviour (5b: request side has no history)
- **SDP weak spot fixed:** only one side of a link records it.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Linking A to B shows the link on both records, live, and writes history on both.
  2. Unlinking from B removes it from A as well, with history on both.
  3. A user who cannot see B sees that a link exists, but not B's subject.

#### REQ-INC-085 — Link and merge pickers search everything you can see

Pickers for links, merges and parents search every incident the user may see, by ID, subject
words, requester or status. They also offer recently viewed incidents and incidents from the
same requester. They never open on a narrow default view that hides the right record.

- **Decision:** BETTER.
- **Source:** sdp-area-02c §Behaviour (link dialog opened on "my pending"), §Weak spots
- **SDP weak spot fixed:** the link dialog opens on the user's own pending requests, so
  unassigned requests are hidden until the view is changed, and there is no search box.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Typing a display ID finds that incident in the picker whatever its status or assignee.
  2. Typing subject words returns matching incidents ranked by relevance.
  3. The picker never lists incidents outside the user's scope.

#### REQ-INC-086 — Parent and child incidents

An incident can be the parent of child incidents, for example one outage reported by many
people. Resolving the parent can resolve all open children with the same resolution and notify
their requesters. Children show their parent on the record and in lists.

- **Decision:** SAME.
- **Source:** architecture §2.1 (parent and child, major incident child incidents); sdp-area-02c §Screens (add resolution to all linked requests)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Resolving a parent with "resolve children" resolves every open child, and each child's
     history names the parent.
  2. A child cannot be the parent of its own parent (no loops).
  3. A list column and filter show the parent of each child.

#### REQ-INC-087 — Associations with other records

Incidents can be associated with problems, changes, releases and projects. The relation types
are: caused by, initiated, related to and resolved by. Each relation has one name per
direction, used the same everywhere, and both sides record it. From an incident a user can
create a problem or a change that is pre-filled and linked.

- **Decision:** BETTER. ServiceDesk Plus names the same link differently on each side, and only
  one side keeps history.
- **Source:** sdp-area-02b §Screens (associations); sdp-area-05 §Behaviour (5b); sdp-area-06 §Behaviour, §Weak spots; sdp-area-07 §Behaviour (7b); architecture §2.1 (relationships); D-044 (REQ-WI-025 in Essentials)
- **SDP weak spot fixed:** the same link is called something different on each record, and
  the request side records no history.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Creating a problem from an incident links them as "problem of" / "incident of", recorded
     on both records.
  2. The relation label on each side comes from one label pair, in every language.
  3. Associations show live counts on the incident and on the other record.
  4. An asset linked to an incident that is linked to a change shows both on the asset
     (no missing counters).

#### REQ-INC-088 — Merge incidents with a preview

A technician merges incidents into one target that they pick explicitly. Before confirming,
they see a preview of what moves to the target: conversations, notes, attachments, worklogs,
tasks, checklists, reminders, followers and links. Each merged source:

- is closed with the system status "merged" and points to the target;
- still opens by its old ID, with a clear redirect;
- notifies its requester, if chosen.

A merge can be undone (REQ-INC-150).

- **Decision:** BETTER. ServiceDesk Plus explains the merge direction only in a confirmation,
  and the merged request vanishes from view.
- **Source:** sdp-area-02a §Fields (merge dialog); sdp-area-02c §Automation (merge), §Behaviour (#39 state unverified), §Weak spots; D-046
- **SDP weak spot fixed:** it is unclear what happened to the merged request, and the merge
  direction is easy to get wrong.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. The confirm screen names the target and lists item counts per kind that will move.
  2. After the merge, opening the source ID shows that it was merged into the target, with a
     link.
  3. The target's timeline marks the moved entries with their original incident ID.
  4. Requester notification goes out only if chosen, and in the requester's language.


#### REQ-INC-150 — Undo a merge

A technician with permission can undo a merge. The source incident is restored to the status it
had before the merge, and everything that moved with it (conversations, notes, attachments,
worklogs, tasks, checklists, reminders, followers and links) moves back. Anything added to the
target after the merge stays on the target. The undo, its actor and reason are recorded on both
incidents.

- **Decision:** NEW. ServiceDesk Plus cannot undo a merge.
- **Source:** D-046; sdp-area-02c §Automation (merge), §Weak spots
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. After merging A into B and undoing it, A is back in its previous status with its own
     conversation, notes, attachments and worklogs, and B no longer shows them.
  2. A note added to B after the merge stays on B after the undo.
  3. Both incidents record the undo with actor, time and reason, and lists update live.
  4. A user without the undo permission sees the action disabled with a reason.
#### REQ-INC-089 — Convert between incident and service request

A technician can convert an incident into a service request or the other way round when it
was logged as the wrong type. It keeps its conversation, attachments, history and links. It
gets an ID of the new type, and the old ID redirects to it. It is re-evaluated against the new
type's template, life cycle and SLA, and fields that do not fit are listed before confirming.

- **Decision:** SAME.
- **Source:** sdp-area-02c §Actions (convert to service request / incident); architecture §2.2 (conversions)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Converting INC-5 creates SR-n with the same conversation, and INC-5 redirects to it.
  2. Fields not on the new template are listed before the user confirms.
  3. SLA due dates are recalculated for the new type and recorded in history.

---

## 15. Resolution, closure, reopening and cancellation

#### REQ-INC-090 — Resolve with a resolution

A technician resolves an incident by entering a resolution (rich text) and running the resolve
transition. Without leaving the resolution editor they can search the knowledge base, copy an
article in, or use a resolution template. They can also log a worklog in the same step.

- **Decision:** SAME.
- **Source:** sdp-area-02c §Screens (resolution tab); sdp-area-08 §Behaviour (request to solution)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Resolving with a resolution sets the status to resolved, stamps the resolved time and
     notifies the requester.
  2. A knowledge search from the resolution editor starts with the incident subject as its query.
  3. Saving the resolution and a worklog in one step creates both, or neither on error.

#### REQ-INC-091 — Turn a resolution into knowledge

From the resolution, a technician can save a knowledge article draft, pre-filled with the
incident's subject, resolution and category. It goes into the knowledge approval flow (file 08)
and is linked to the incident.

- **Decision:** SAME.
- **Source:** sdp-area-02c §Screens (save and add to solutions); sdp-area-08 §Behaviour
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. "Save as knowledge" creates a draft article linked to the incident, not published.
  2. The draft keeps the resolution's formatting and images.

#### REQ-INC-092 — Apply a resolution to linked incidents

When resolving, the technician can apply the same resolution to linked or child incidents
that are still open, and pick which ones.

- **Decision:** SAME.
- **Source:** sdp-area-02c §Screens (add resolution to all linked requests)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Choosing two of three linked incidents resolves exactly those two with the resolution.
  2. Each resolved incident's history says the resolution came from the source incident.

#### REQ-INC-093 — Closure codes

Admins define closure codes (for example fixed, workaround, no fault found, duplicate, user
error). The closing technician picks one, and reports group by it.

- **Decision:** SAME.
- **Source:** sdp-area-02c §Fields (close request); sdp-area-13 §Helpdesk customization (closure code)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Closure codes have translations and can be disabled without affecting old incidents.
  2. A closure code can be required by the closure rules (REQ-INC-094).

#### REQ-INC-094 — Closure rules

Admins set which fields must be filled before an incident can be resolved and before it can
be closed. Standard and custom fields can both be required, for example category, closure
code, resolution, a worklog or an attachment. The rules apply on every path: record, bulk,
email, API and automation. A blocked user sees a short list of what is missing.

- **Decision:** SAME.
- **Source:** sdp-area-13 §Closure Rules; sdp-area-12 §Config (closure rules)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. With "closure code required", closing without one is refused, and the prompt asks only
     for the closure code.
  2. A bulk close applies the rules to each incident and reports the ones it skipped and why.
  3. The API returns field errors with the same codes the UI shows.

#### REQ-INC-095 — Closing with open work is warned or blocked

Before an incident is resolved or closed, open tasks, unfinished checklists, open child
incidents and pending approvals are checked. By default:

- open tasks and checklists: a warning that lists them, and an explicit confirmation;
- open child incidents: an offer to resolve them together;
- pending approvals: the close is blocked.

Admins can turn each warning into a block. Closing can also complete the open items
automatically, if the admin enables it.

- **Decision:** BETTER. ServiceDesk Plus allows closing with open tasks and checklists by
  default, with no warning.
- **Source:** sdp-area-02c §Behaviour (closed with open task and checklist), §Weak spots; sdp-area-13 §Closure Rules; sdp-area-04 §Weak spots; sdp-area-06 (6b) §Weak spots
- **SDP weak spot fixed:** requests, problems and projects close with open work and no warning.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Resolving an incident with one open task shows a warning that names the task and needs
     explicit confirmation.
  2. With the tenant setting "block on open tasks", the same action is refused and the API
     returns a problem code.
  3. Closing with a pending approval is refused under default settings.
  4. Confirming the warning is recorded in history with the open items listed.

#### REQ-INC-096 — Requester confirms the resolution, then auto-close

When an incident is resolved, the requester is asked by email and in the portal to confirm the
fix or say it is not fixed. Confirming closes the incident. Saying it is not fixed reopens it
with their comment. With no answer, the incident closes automatically after a set number of
business days (Appendix A). Admins can also let technicians close straight away.

- **Decision:** SAME. ServiceDesk Plus offers manual or automated closing; we ship a sensible
  automatic default.
- **Source:** sdp-area-13 §Closure Rules (request closing process, user acknowledgment); sdp-area-02c §Fields (requester acknowledged)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Clicking "confirm" in the resolution email closes the incident with the requester as
     actor and source "email".
  2. Clicking "not fixed" reopens it to in progress, with the requester's comment as a public
     entry.
  3. With no answer, the incident closes after the configured business days, recorded as
     "auto-closed".
  4. The confirm and reject links work once only, expire, and need no login beyond the link.

#### REQ-INC-097 — Reopen keeps the past

A technician with permission can reopen a resolved or closed incident, giving a reason. A
requester can reopen through REQ-INC-096 or REQ-INC-098. The earlier resolution, closure code
and resolved and closed times stay in history. The reopen count goes up, and the SLA continues
by the tenant's rule (resume, or restart).

- **Decision:** BETTER. In ServiceDesk Plus reopening clears the closure code, completed time
  and resolved time, and resets the elapsed time to zero.
- **Source:** sdp-area-02c §Automation (reopening clears values), §Behaviour; sdp-area-04 §Weak spots (no reopen button)
- **SDP weak spot fixed:** reopening wipes the earlier resolution data and timings, and there
  is no reopen action, only editing the status.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Reopen is an explicit action that needs a reason; it is not done by editing the status.
  2. After reopening, history still shows the earlier resolution, closure code and times.
  3. The reopen count goes up by one each time, and reports can filter on it.
  4. Time analysis keeps the time before the reopen.

#### REQ-INC-098 — Requester replies after resolution

A requester's reply to a resolved or closed incident reopens it if it arrives within the
reopen window (Appendix A; configurable from 1 to 30 days). The incident returns to a chosen
status and the assignee is notified. After the window, the reply creates a new incident linked
to the old one. Replies that only say thanks are handled by REQ-INC-099.

- **Decision:** SAME.
- **Source:** sdp-area-13 §Reopen settings; sdp-area-03 §Config (reopen on email reply)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A reply two days after closing, with a 7-day window, reopens the incident and notifies the
     assignee.
  2. A reply after the window creates a new incident linked "follows" to the old one, and the
     requester is told the new ID.
  3. Both behaviours are recorded in history with source "email".

#### REQ-INC-099 — Tell "thanks" from "still broken"

AI reads requester replies to resolved incidents and decides whether they confirm the fix or
report it still broken. A simple thanks does not reopen the incident. The decision and its
confidence are shown on the reply, a technician can override it, and below a confidence
threshold a person decides. It works with the local model on-prem.

- **Decision:** SAME.
- **Source:** sdp-area-13 §Reopen settings (AI close or reopen from reply); architecture §2.1 (natural-language reopen), §2.10, §12
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A reply "thanks, all good" to a resolved incident does not reopen it and is marked
     "confirmed fix".
  2. A reply "it happened again this morning" reopens it.
  3. Below the confidence threshold the reply is flagged for the assignee to decide.
  4. The feature works with the on-prem local model profile.

#### REQ-INC-100 — Cancel with a reason, and undo it

An incident can be canceled with a reason from an admin list plus a comment, for example
logged by mistake, solved by the requester, or a duplicate. A canceled incident is read-only.
A user with permission can undo the cancellation with a reason, and it goes back to the status
it had before.

- **Decision:** SAME.
- **Source:** sdp-area-02c §Fields (cancel request), §Actions (revert cancellation), §Behaviour
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Canceling without a reason is refused.
  2. A canceled incident accepts no edits except undo-cancel and private notes (configurable).
  3. Undoing returns the incident to its previous status and records both steps.

#### REQ-INC-101 — Editing closed incidents is controlled

Editing fields of a closed incident needs its own permission and a reason. Notes can still be
added. Closed incidents can be locked fully by a tenant setting.

- **Decision:** SAME.
- **Source:** sdp-area-11 §Fields (editing closed requests); sdp-area-13 §Advanced Portal Settings (closed change operations)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Without the permission, the fields of a closed incident are read-only with a reason shown.
  2. With the permission, an edit needs a reason and is written to the audit log.

#### REQ-INC-102 — First-contact resolution

An incident is marked as resolved at first contact when it was resolved by the first
technician to handle it, without being reassigned and within a tenant-set time from creation.
The system suggests the flag and the technician can confirm or change it.

- **Decision:** BETTER. In ServiceDesk Plus the flag is a manual tick box only.
- **Source:** sdp-area-02a §Fields (close dialog FCR); sdp-area-02c §Actions (mark FCR); sdp-area-01 §Config (FCR widgets)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. An incident resolved at creation by its creator is suggested as first-contact.
  2. A reassigned incident is never suggested.
  3. Changing the flag is recorded, and reports use the final value.

#### REQ-INC-103 — Satisfaction survey after closing

When an incident closes, the requester can get a short satisfaction survey (one-click rating
in the email and the portal, plus optional questions). Survey design and sending rules (every
time, every Nth incident, per requester) are set in file 11. A low rating can notify the
technician's lead.

- **Decision:** SAME.
- **Source:** sdp-area-13 §Surveys; architecture §2.1 (satisfaction survey on closure)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Closing an incident sends the survey when the sending rule matches, in the requester's
     language.
  2. A one-click rating from the email is recorded against the incident without a login.
  3. A rating below the threshold notifies the group lead.

---

## 16. Lists, views and search

#### REQ-INC-104 — Incident list with chosen columns

The incident list is a dense table. Users choose columns from every field, including custom
fields and system times, by search. They can reorder and resize columns and sort by any
sortable column. Choices are saved per user per view. Rows link to the record, and unread
changes are marked.

- **Decision:** SAME.
- **Source:** sdp-area-02a §Screens (list mode, column chooser, table settings)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Adding a custom field column and reloading keeps the column in place for that user only.
  2. Sorting by due date sorts across all pages, not just the visible one.
  3. Column choices in one view do not change another view.

#### REQ-INC-105 — Built-in views

Ready-made views include:

- all open, my open, unassigned in my groups, my groups' open;
- overdue, due today, waiting on requester, resolved awaiting confirmation;
- created today, updated by me, followed by me, shared with me;
- pending approval, from my direct reports, without SLA, canceled and closed.

Views can be filtered by type (incidents, service requests, or both).

- **Decision:** SAME.
- **Source:** sdp-area-02a §Screens (view selector)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Each built-in view returns exactly the incidents its definition says, and a test covers
     each one.
  2. Counts next to each view update live.
  3. The type filter applies to every view.

#### REQ-INC-106 — Custom views and the filter builder

Users build views with the shared filter builder: conditions on any field, AND and OR groups,
and operators that fit the field type (text, number, date, list, user). Relative dates are
supported ("last 7 days", "this quarter"). The field list is grouped by kind and searchable. A
filter can be tried without saving, then saved as private or shared with everyone. The same
filter format is used by rules, SLA conditions, reports and the API.

- **Decision:** BETTER. Grouped, searchable fields and visible relative dates. One filter
  format across the product.
- **Source:** sdp-area-02a §Fields (custom view builder), §Weak spots; architecture §2.9, §6.5 (filter DSL)
- **SDP weak spot fixed:** the column list mixes fields with sub-menus and is slow to scan; the
  date operators are long and cut off, and relative dates are hard to find.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A view "priority is P1 or P2, and created in the last 7 days" returns the right incidents
     and stays right as days pass.
  2. Applying a filter without saving changes only the current screen.
  3. A filter saved in the UI can be sent unchanged to the list API and returns the same rows.
  4. Operators offered match the field type, and invalid combinations cannot be built.

#### REQ-INC-107 — Share views and mark favourites

Views can be shared with chosen roles, groups or users. Users can star views as favourites,
and favourites show first in the view picker.

- **Decision:** SAME.
- **Source:** sdp-area-02a §Screens (favourites, shared views); sdp-area-11 §Behaviour (sharing only public or private)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A view shared with group A appears for group A members and no one else.
  2. A view only ever shows incidents within the viewer's own scope.

#### REQ-INC-108 — Quick time range

A time range control above the list narrows it by a chosen date field (created, updated, due,
resolved). It offers presets and a custom range, and the active range is always visible.

- **Decision:** SAME.
- **Source:** sdp-area-02a §Screens (time filter)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Choosing "this week" on created date shows only incidents created this week in the user's
     time zone.
  2. The control names the date field it filters on.

#### REQ-INC-109 — Search with chips, without losing your place

Global search finds incidents by ID, words in subject, description and conversations, and
attachment names. It respects the user's scope. Filters are added as visual chips (field,
operator, value) chosen from suggestions, so nobody has to learn a syntax. Results open in a
panel over the current screen, and the user can move them into the full list.

- **Decision:** BETTER. ServiceDesk Plus needs field-prefixed text, and a global search replaces
  the current page.
- **Source:** sdp-area-01 §Screens (global search), §Weak spots; sdp-area-02a §Screens (in-list search)
- **SDP weak spot fixed:** search needs knowledge of field names and syntax, and jumps to a
  different screen.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Searching a word that appears only in an email reply finds that incident.
  2. Adding "status is open" as a chip narrows the results without typing syntax.
  3. Closing the search panel leaves the user where they were.
  4. Results never include incidents outside the user's scope or private notes they cannot see.

#### REQ-INC-110 — Counts and paging

Lists show the total number of matches fast. For very large results they show an exact count
up to a cap and then "more than N". Paging uses stable cursors, so new incidents arriving do
not shift or repeat rows. Page size can be 25, 50 or 100.

- **Decision:** BETTER.
- **Source:** sdp-area-02a §Weak spots (counter shows "…" while loading); architecture §10 (cursor pagination)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Paging through a list while new incidents arrive never shows a row twice.
  2. The count shows within the list load time target, or "more than N" if counting would be
     slower.

#### REQ-INC-111 — Card list and board

Besides the table, users can switch to a card list or a board grouped by status, priority,
technician or group, with compact and comfortable density. The choice is remembered per user
and view. Board columns show counts, and a column can be pinned.

- **Decision:** SAME.
- **Source:** sdp-area-02a §Screens (detailed list, board)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Switching to the board grouped by technician shows one column per technician with counts.
  2. The chosen mode is restored on the next visit.
  3. The board updates live as incidents change (REQ-WI-005), and drags follow REQ-INC-052.

#### REQ-INC-112 — Calendar view

Incidents with due dates or scheduled times can be shown on a calendar by day, week or month,
filtered like any view.

- **Decision:** SAME.
- **Source:** architecture §2.1 (calendar view); sdp-area-02a §Screens (no calendar on list)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. An incident due tomorrow 10:00 shows on tomorrow at 10:00 in the user's time zone.
  2. The calendar applies the same filters as the current view.

#### REQ-INC-113 — Split view and quick peek

A technician can open an incident beside the list without leaving it, and move to the next
incident with one key. Hovering an ID shows a short preview anywhere in the product.

- **Decision:** NEW. ServiceDesk Plus Cloud is only now adding a peek view.
- **Source:** architecture §9.4; product-plan §3 (direction: peek view)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Opening an incident in split view keeps the list scroll position and selection.
  2. The next-key moves the split view to the next incident in the list.
  3. The preview shows status, priority, assignee and due time, and respects access.

#### REQ-INC-114 — Edit in the list

Status (through transitions), priority, group, technician and other simple fields can be
changed inline in list cells, with the same validation and prompts as on the record.

- **Decision:** NEW.
- **Source:** architecture §9.4 (inline editing)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Changing priority in a list cell saves with a version check and shows a conflict if the
     row changed meanwhile.
  2. A status change in a cell that needs a reason opens the reason prompt first.

#### REQ-INC-115 — Row colours and unread markers

Rows can be coloured by status or priority (tenant default, personal override). Incidents with
changes the user has not seen are marked until opened.

- **Decision:** SAME.
- **Source:** sdp-area-02a §Screens (row colour settings, bold unread)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. With colouring by priority on, P1 rows use the P1 colour, with contrast meeting WCAG AA.
  2. A new public reply marks the incident unread for its assignee until they open it.

#### REQ-INC-116 — Export lists

Users with the export permission can export all matching incidents, the current view or the
selected rows to CSV, Excel or PDF. The chosen columns are used. Exports run in the
background, show live progress, and notify the user when ready. The tenant sets limits, and
each export is audited.

- **Decision:** BETTER. Adds Excel and PDF, live progress, and per-tenant limits; ServiceDesk
  Plus offers CSV only, capped at 10,000 rows.
- **Source:** sdp-area-02a §Screens (export); architecture §2.8 (export), §6.8 (imports/exports)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Exporting 50,000 incidents runs in the background with progress, and the file is ready
     to download when done.
  2. Exported values use labels in the user's language, never codes.
  3. Fields the user may not see are not exported.

#### REQ-INC-117 — Chart a list in place

From any list view, a user can show a quick chart of the current results grouped by a chosen
field, and turn it into a dashboard widget.

- **Decision:** SAME.
- **Source:** architecture §2.7 (instant graph view inside any list view)
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. Charting the "my open" view by priority shows counts that match the list.
  2. The chart updates live as the list changes.

#### REQ-INC-118 — Archive old incidents

Admins set an archive policy, for example closed or canceled more than one year ago, with
exceptions. Archived incidents leave the active lists. They remain searchable and readable in
an archive view, and can be restored.

- **Decision:** SAME.
- **Source:** sdp-area-13 §Data Archive; architecture §2.1 (scheduled archiving), §7.3
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. Incidents matching the policy move to the archive on the next run, and the run is logged.
  2. An archived incident opens read-only, and a restore brings it back to active lists.
  3. Archived incidents still count in reports over their period.

---

## 17. Bulk actions

#### REQ-INC-119 — Select across pages

Users can select rows on one page, all rows on the page, or every incident matching the view
("all N"). The selection count is always visible. Actions that need a selection are disabled
with a hint until something is selected.

- **Decision:** BETTER. In ServiceDesk Plus "select all" covers one page only, and actions with
  no selection raise blocking alerts.
- **Source:** sdp-area-02a §Actions, §Weak spots
- **SDP weak spot fixed:** select-all affects only the current page, and actions without a
  selection show a blocking alert instead of being disabled.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. "Select all 3,200" selects every matching incident, not just the page.
  2. With nothing selected, bulk actions are disabled and say why; no blocking alert appears.

#### REQ-INC-120 — Bulk edit, assign, take, resolve and close

Selected incidents can be edited in bulk (only the fields the user changes are applied),
assigned, taken, resolved or closed. Transitions, closure rules and permissions apply to each
incident. Up to 1,000 incidents run as a background job with live progress and a result per
incident. Partial failures are listed with reasons. Updates are grouped, so screens do not
flood.

- **Decision:** BETTER. Adds a per-incident result report, streamed progress and grouped
  updates.
- **Source:** sdp-area-02a §Fields (bulk edit, close dialog); architecture §10 (bulk), §8.4
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A bulk close of 300 incidents, where 20 lack a closure code, closes 280 and lists the 20
     with the reason.
  2. Fields left untouched in the bulk form are not changed on any incident.
  3. Progress shows live, and the user can leave the page and find the result later.
  4. Each changed incident gets its own history entry naming the bulk job.

#### REQ-INC-121 — Bulk merge, link, delete and note with safeguards

Selected incidents can be merged (REQ-INC-088), linked, given a note, or deleted. Delete sits
apart from everyday actions. It needs its own permission and a confirmation that states the
count.

- **Decision:** BETTER. In ServiceDesk Plus delete sits among everyday actions, and link and
  merge pick the parent automatically.
- **Source:** sdp-area-02a §Actions (link, merge, delete), §Weak spots
- **SDP weak spot fixed:** delete sits next to "take" and "close", and linking picks the oldest
  record as parent without asking.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Bulk delete asks the user to confirm the exact number of incidents before running.
  2. Bulk link asks which incident is the parent, or links them as peers.
  3. A bulk note can be public or private and is added to each incident's timeline.

---

## 18. The record page and productivity

#### REQ-INC-122 — Record page layout

The record page has:

- a header with display ID, subject, status, priority, SLA countdown, requester and assignee;
- an action bar in fixed order (REQ-WI-010) and fixed tabs (REQ-WI-011);
- a properties panel and an associations panel.

While a record loads, a skeleton shows. The previous record's data never shows under the new
record's ID.

- **Decision:** BETTER.
- **Source:** sdp-area-02b §Screens (detail page); sdp-area-02c §Weak spots (properties briefly showed the previous request's ID)
- **SDP weak spot fixed:** while a request was loading, its properties briefly showed the
  previous request's ID.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Opening incident B after incident A never shows A's data under B's header.
  2. The header shows the SLA countdown and updates live.
  3. The page is usable down to tablet width with no horizontal page scroll.

#### REQ-INC-123 — Edit fields on the record

Fields in the properties panel can be edited in place, with validation, form rules and
permissions, and saved one at a time. A full edit form is also available for many changes at
once.

- **Decision:** SAME.
- **Source:** sdp-area-13 §Advanced Portal Settings (spot edit); sdp-area-02c §Behaviour (edit form)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Changing the category in place saves it, writes history, and updates other viewers live.
  2. A field locked by a form rule cannot be edited in place.

#### REQ-INC-124 — A reason for an edit

Editing can take a "why I changed this" note, which appears in history. Admins can make it
required for chosen fields, for example due dates and priority.

- **Decision:** SAME.
- **Source:** sdp-area-02c §Behaviour (reason for updating request)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. With a reason required for due date changes, saving a new due date without a reason is
     refused.
  2. The reason shows on the history entry for that change.

#### REQ-INC-125 — Next and previous

On a record opened from a list, next and previous move through that list in its current order
and filter.

- **Decision:** SAME.
- **Source:** sdp-area-02c §Actions (previous/next arrows); sdp-area-01 §Config (arrow shortcuts)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. "Next" on the 3rd row of a view opens the 4th row of that view.
  2. At the end of a page, "next" moves on to the next page.

#### REQ-INC-126 — Print and PDF

A user can print or save an incident as PDF. They choose sections: details, requester,
conversation, notes (public only or all), tasks, checklists, worklogs, resolution, approvals,
time analysis and history. The output follows the user's language and text direction and
leaves out what they may not see.

- **Decision:** SAME.
- **Source:** sdp-area-02c §Screens (print preview)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A PDF with "public notes only" contains no private notes.
  2. An Arabic user's PDF is laid out right to left with Arabic labels.

#### REQ-INC-127 — Recently viewed

Each user has a list of incidents (and other records) they recently viewed, available from the
header and the command palette.

- **Decision:** SAME.
- **Source:** sdp-area-01 §Screens (recent items)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Opening three incidents lists them, newest first.
  2. A record the user can no longer see disappears from the list.

#### REQ-INC-128 — Personal counters

Each technician sees live counters for their work: overdue, due today, waiting on me, recently
updated by others, unassigned in my groups, and pending my approval. Each counter opens the
matching view.

- **Decision:** SAME.
- **Source:** sdp-area-01 §Screens (personal summary panel)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. An incident becoming overdue increases "overdue" live, with no reload.
  2. Each counter opens a view whose row count equals the counter.

#### REQ-INC-129 — Announce from an incident

From an incident (typically an outage), a technician can publish an announcement to chosen
audiences, for example "email is down for the Riyadh site", using the announcements module.
The announcement is linked to the incident and can be ended when the incident is resolved. It
is shown to requesters in the portal, to cut duplicate reports.

- **Decision:** SAME.
- **Source:** sdp-area-02c §Actions (make an announcement); architecture §2.1 (announcements); ADR-024
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Announcing from an incident creates a linked announcement for the chosen audience.
  2. Resolving the incident offers to end the linked announcement.
  3. Requesters see the announcement in the portal live.

---

## 19. Notifications

#### REQ-INC-130 — Incident notifications with sensible defaults

These incident events notify the right people:

- created: an acknowledgement to the requester, a note to the group;
- assigned and reassigned: to the new and old assignee;
- left unassigned for N minutes: to the group;
- a public reply or note: to the requester and followers;
- a requester reply: to the assignee;
- status changes the requester cares about, and resolved (with confirm and reject links);
- closed, reopened, canceled and merged;
- mentions, and task assignment;
- approval needed.

Each event can be switched on or off per tenant, with chosen recipients and channels (email,
in-app, mobile push; Teams and Slack later). Defaults are on for the events in Appendix A.
Templates ship in English and Arabic at MVP, and in Urdu at V1 (D-048).

- **Decision:** BETTER. Same event coverage, with sensible defaults.
- **Source:** sdp-area-12 (12b) §Screens (notification rules); sdp-area-11 §Fields (group notifications); architecture §6.8; D-048
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. In a new tenant, creating an incident sends the requester an acknowledgement with no admin
     set-up.
  2. Switching an event off stops it for the whole tenant, and the change is audited.
  3. Nobody gets a notification about a change they made themselves, unless they opted in.
  4. Notifications respect access: a follower who lost access gets nothing.

#### REQ-INC-131 — In-app notification centre

Every user has a notification centre that updates live. It shows unread counts, groups entries
by day, and has links to the record. Entries can be marked read singly or all at once, and
there is a do-not-disturb switch.

- **Decision:** SAME.
- **Source:** sdp-area-01 §Screens (notifications drawer)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Being assigned an incident shows a new entry and raises the unread badge within one
     second.
  2. Opening the entry opens the incident and marks the entry read.
  3. The centre works with no mail configured.

#### REQ-INC-132 — Notification templates per language, editable safely

Each notification has a template for each language: subject, body and variables. Variables are
inserted from a picker, never typed as raw names. Admins can preview a template against a real
incident, send a test to themselves, and reset it to the default. Defaults ship ready in
English and Arabic (and Urdu from Stage 2). No one-time step that cannot be undone is needed.

- **Decision:** BETTER. In ServiceDesk Plus templates come from a one-time, irreversible
  generation step in a single chosen language.
- **Source:** sdp-area-12 (12b) §Screens (notification templates generation), §Weak spots; architecture §6.8 (sandboxed templates, per-locale variants)
- **SDP weak spot fixed:** templates are generated once, irreversibly, in one language, and
  the prompt does not say so.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A new tenant has every notification template in English and Arabic with no set-up step.
  2. Previewing a template against an incident shows the real values.
  3. "Reset to default" restores the shipped template and is recorded.
  4. Templates run in a sandbox and cannot read data outside their variables.

#### REQ-INC-133 — Notifications in the recipient's language

Each notification goes out in the recipient's language and time zone (from their profile, or
the site default). It is right to left for Arabic and Urdu. English and Arabic are available
at MVP; Urdu follows at V1 (D-048).

- **Decision:** NEW. ServiceDesk Plus generates templates in one language.
- **Source:** architecture §6.8; D-006; D-048; product-plan §8 (internationalisation)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. An Arabic-speaking requester gets the acknowledgement in Arabic, laid out right to left,
     with times in their zone.
  2. A requester with no language set gets their site's default language.
  3. From V1, a requester whose language is Urdu gets Urdu notifications, right to left.

#### REQ-INC-134 — Notification log on the incident

The incident shows which notifications were sent: to whom, through which channel, when, and
whether delivery succeeded. The entries sit in the timeline under the system filter.

- **Decision:** SAME, plus delivery state.
- **Source:** sdp-area-02c §Screens (auto notifications filter)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. After resolving, the timeline lists the resolution notification with recipient and
     delivery state.
  2. A failed notification shows the reason (REQ-INC-059).

---

## 20. AI on incidents

All AI on incidents runs through the AI gateway (architecture §12). It works with the local
model on-prem and air-gapped, and with a chosen cloud model on SaaS, with the same permissions
as the user. Every suggestion records whether a person accepted, edited or rejected it.
Administration is in file 10.

Model access, pending a pricing decision (D-049): SaaS includes a fair-use allowance of cloud
model usage; Enterprise tenants may bring their own key; on-prem and air-gapped installations
use a local model.

#### REQ-INC-135 — Classification suggestions

When an incident is created or updated, AI suggests template, category, subcategory, item,
priority, group and technician, each with a confidence. Technicians accept or reject each
suggestion. Admins can let high-confidence suggestions apply automatically, and those are
recorded with source "AI".

- **Decision:** SAME. ServiceDesk Plus offers this in the Cloud only after training; we offer
  it on every deployment.
- **Source:** sdp-area-10 §Screens (predictive features); architecture §2.10; product-plan §7.2 (phase 1)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. On a trained tenant, a new incident shows category and group suggestions with confidence
     values.
  2. Accepting a suggestion records the change with source "AI", accepted by the user.
  3. With auto-apply above 90 percent, only suggestions above that confidence are applied.
  4. The same feature passes its tests with the on-prem local model profile.

#### REQ-INC-136 — Writing help in replies and notes

In the reply and note editors, AI can draft a reply from a short instruction, and can improve
the user's text: grammar, length, tone, or a translation between the supported languages. The
user always reviews the result before it is inserted, and nothing is sent automatically. One
consistently named entry point is used in every editor.

- **Decision:** SAME. ServiceDesk Plus uses one icon with two different names in two editors.
- **Source:** sdp-area-10 §Fields (reply assist, text assist), §Behaviour, §Weak spots
- **SDP weak spot fixed:** the same icon opens differently named tools in the reply and note
  editors, and generated notes can invent facts.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A draft is shown for review and inserted only when the user accepts it.
  2. Drafts use only facts from the incident and the user's instruction; an evaluation set
     checks for invented commitments.
  3. Personal data is masked before any external model is called.

#### REQ-INC-137 — Conversation summary

A summary of the incident (problem, what has been tried, current state, next step) shows at a
fixed place on the record. It can be refreshed on demand and updates as the conversation grows.
Admins choose which parts feed the summary.

- **Decision:** BETTER. In ServiceDesk Plus the summary can be switched on with no sign of
  where it appears.
- **Source:** sdp-area-10 §Fields (conversation summary), §Behaviour, §Weak spots
- **SDP weak spot fixed:** the summary's location could not be found after switching it on.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. An incident with ten messages shows a summary in the fixed summary area of the record.
  2. The summary excludes private notes when shown to someone who cannot see them.
  3. Each summary records the model used and the time, and can be refreshed.

#### REQ-INC-138 — Sentiment and frustration cues

AI flags incoming messages that show strong frustration or urgency, so leads can step in. The
cue shows on the message and can be used in views and rules.

- **Decision:** SAME.
- **Source:** sdp-area-10 §Screens (sentiment analysis); architecture §2.10
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. A clearly angry test message is flagged; a neutral one is not.
  2. A view "frustrated requester in the last 24 hours" lists flagged incidents.

#### REQ-INC-139 — Translate messages

Technicians can see any incoming message translated into their own language, and can send a
reply translated into the requester's language. The original text is always kept and visible.

- **Decision:** NEW. ServiceDesk Plus translates in the writing tools, not in the conversation.
- **Source:** architecture §2.10 (translation); product-plan §4.2 (MENA and South Asia)
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. An Arabic email shows an English translation on request for an English-speaking
     technician, with the original one click away.
  2. A reply written in English can be sent in Arabic after the technician reviews the
     translation.

#### REQ-INC-140 — Triage agent

A triage agent sets category, priority, service and group on new incidents, finds duplicates,
and links incidents to an open major incident. Each tenant chooses whether it only suggests or
acts on its own above a confidence level. Every action it takes is in history and can be
undone.

- **Decision:** NEW. ServiceDesk Plus agents are Enterprise-only and run in the Cloud.
- **Source:** product-plan §7.3 (triage agent), §4.3 (pillar 4); architecture §2.10 (agents)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. In suggest mode the agent changes nothing, only proposes.
  2. In act mode, actions below the confidence level are left as suggestions.
  3. Every agent action shows source "AI agent" and can be undone by a technician.

---

## 21. Major incidents

#### REQ-INC-141 — Declare a major incident

A technician with permission can declare an incident major, giving a reason. The incident then
switches to the major incident template and life cycle, alerts the major incident team, and
gets a visible marker everywhere. Similar open incidents can be attached as children in bulk.
Ending the major status is recorded.

- **Decision:** SAME.
- **Source:** architecture §2.1 (major incident); sdp-area-02b §Fields (major incident template); sdp-area-12 (12b) §Behaviour (major incident life cycle); D-043
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Declaring major notifies the configured team and shows the major marker in lists live.
  2. Ten similar incidents can be attached as children in one action.
  3. Resolving the major incident offers to resolve its children (REQ-INC-086).

#### REQ-INC-142 — Stakeholder updates and a status page

During a major incident, the incident lead posts updates to stakeholders on a set rhythm, for
example every 30 minutes, and is reminded when an update is due. Updates go to chosen groups
and channels and to a status page that requesters see in the portal.

- **Decision:** BETTER. ServiceDesk Plus has multi-stage notifications but no update rhythm or
  status page.
- **Source:** product-plan §5 (major incident: stakeholder updates, status page); architecture §2.1 (multistage notifications)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. With a 30-minute rhythm, the lead is reminded if no update was posted in 30 minutes.
  2. A posted update appears on the portal status page live.
  3. Each update is kept on the incident timeline.

#### REQ-INC-143 — War room

A major incident has a war room view: a live timeline of every event, roles (incident lead,
communications lead, resolvers), a link to the bridge call, linked changes from the last 72
hours on the affected services, and affected services from the CMDB.

- **Decision:** NEW.
- **Source:** product-plan §5 (native war room); D-043
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. The war room timeline shows notes, status changes, updates and linked changes in order,
     live.
  2. Roles can be assigned, and each role's holder is shown and notified.
  3. Changes on the affected services in the last 72 hours are listed automatically.

#### REQ-INC-144 — Post-incident review

After a major incident, a post-incident review record is created from a template (timeline,
impact, cause, actions). AI drafts it from the incident timeline, monitoring data and recent
changes, and a person edits and publishes it. Follow-up actions become tasks or problems.

- **Decision:** BETTER. ServiceDesk Plus ships review drafting as an add-on extension.
- **Source:** architecture §2.1 (post-incident review), §2.10 (PIR drafts); product-plan §5, §7.3 (PIR writer); D-043
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Closing a major incident creates a review linked to it, pre-filled with its timeline.
  2. The AI draft cites the timeline entries it used.
  3. A follow-up action in the review can be turned into a linked problem in one step.

---

## 22. The monitoring boundary

#### REQ-INC-145 — Live health of linked items from MonetX

An incident linked to configuration items that MonetX monitors shows their current health,
read from the MonetX API (read-only, D-001). It also shows a link to open them in MonetX.

- **Decision:** NEW.
- **Source:** D-001; ADR-017; product-plan §6 (topology-aware impact)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. An incident linked to a monitored item shows its MonetX health, refreshed while the page
     is open.
  2. If MonetX cannot be reached, the panel says so; the rest of the page works.
  3. SupportX makes no write call to MonetX and stores no performance data.

#### REQ-INC-146 — No alert correlation in SupportX

SupportX does not correlate, de-duplicate or suppress monitoring alerts, poll devices or
collect metrics. MonetX does that work, and SupportX receives one problem per root event
(REQ-INC-030).

- **Decision:** SKIP. This is MonetX's job (ADR-017, D-001). product-plan §6's alert
  correlation engine is out of scope for this build.
- **Source:** ADR-017; D-001; architecture §2 (intro), §2.15 (out of scope); CLAUDE.md §1
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. No SupportX component polls devices or stores metrics; an architecture test checks the
     monitoring_integrations module has only receive and read-only clients.
  2. Duplicate MonetX deliveries are handled by the one-problem-one-incident key, not by
     correlation logic.

---

## 23. The requester's side

#### REQ-INC-147 — Requesters follow their incidents

In the portal, requesters see their own incidents. Depending on their permission they may
also see incidents from their site, their department or all incidents, and their direct
reports' incidents. Each incident shows:

- its status as a plain-language label;
- the public conversation and public notes;
- the attachments, and the expected resolution time if the tenant shows it.

Requesters can reply, add files, confirm or reject a resolution, and follow live. The portal
shell is in file 02.

- **Decision:** SAME.
- **Source:** sdp-area-11 §Fields (requester view permissions); sdp-area-03 §Behaviour (portal list was the full technician list in preview); sdp-area-13 §Requester Portal
- **SDP weak spot fixed:** the portal preview showed the full technician request list, not the
  requester's own.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A requester with "own" scope sees only incidents where they are requester or on behalf of.
  2. A requester never sees private notes, internal fields or technician-only statuses.
  3. A technician's public reply appears in the requester's portal within one second.
  4. An admin can preview the portal as a chosen requester, with that requester's real scope.

#### REQ-INC-148 — Requester cancel and edit rules

Tenants decide whether requesters can cancel their own incidents directly or only ask for
cancellation (the technician decides). They also decide whether requesters can edit their
incidents after submitting, and which fields.

- **Decision:** SAME.
- **Source:** sdp-area-13 §Requester Portal (cancel options, request editing); sdp-area-11 §Fields (cancel requests)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. With "ask for cancellation", a requester's cancel creates a request that the assignee can
     approve or decline; the incident stays open until then.
  2. With requester editing off, the portal shows the incident read-only, apart from replying.

#### REQ-INC-149 — Incidents on the mobile app

Technicians handle incidents in the mobile app: lists and views, the record, replies and notes
(including voice dictation), status transitions, assignment, worklogs and approvals. Push
notifications and an offline queue for changes made without signal are included.

- **Decision:** SAME.
- **Source:** architecture §2.15 (mobile apps), §9.1; product-plan §5 (mobile)
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. A note added offline is sent when the device reconnects, with no duplicate.
  2. A push notification for a new assignment opens the incident in the app.
  3. Status changes in the app follow the same transitions and prompts as the console.

---

## Appendix A — Approved defaults

These are the defaults a new tenant gets, approved by the product owner (D-041). They are seed
data, not fixed behaviour: a tenant admin can change every one of them. The requirements above
refer to this appendix.

**Impact** (REQ-INC-008), lowest to highest: one person · a team · a department or site · the
whole organisation.

**Urgency:** low (can wait) · medium (work slowed) · high (work stopped) · critical (business
stopped or safety risk).

**Priority matrix** (REQ-INC-009). P1 is the highest.

| Impact \ Urgency | Low | Medium | High | Critical |
|---|---|---|---|---|
| One person | P4 | P4 | P3 | P3 |
| A team | P4 | P3 | P3 | P2 |
| A department or site | P3 | P3 | P2 | P1 |
| The whole organisation | P3 | P2 | P1 | P1 |

The default priority, when impact and urgency are both unknown, is P3, marked as defaulted
(REQ-INC-011).

**Statuses and categories** (REQ-INC-044, REQ-INC-045):

| Status | Category | Reason needed to enter |
|---|---|---|
| new | open | no |
| assigned | open | no |
| in progress | open | no |
| awaiting requester | paused | yes |
| awaiting third party | paused | yes |
| resolved | resolved | resolution required (REQ-INC-090) |
| closed | closed | closure code required |
| canceled | canceled | yes (cancel reason) |
| merged (system only) | closed | set by merge |

**Allowed transitions:**

| From | To |
|---|---|
| new | assigned, in progress, resolved, canceled |
| assigned | new (unassign), in progress, awaiting requester, awaiting third party, resolved, canceled |
| in progress | awaiting requester, awaiting third party, resolved, canceled |
| awaiting requester | in progress, resolved, canceled |
| awaiting third party | in progress, resolved, canceled |
| resolved | closed, in progress (reopen) |
| closed | in progress (reopen, permission and reopen window rules) |
| canceled | the previous status (undo cancel, permission) |

**Automatic moves** (REQ-INC-050, REQ-INC-051): new → assigned when a technician is set;
assigned → in progress on the assignee's first public reply; awaiting requester → in progress
on a requester reply.

**Closing with open work** (REQ-INC-095): open tasks and checklists give a warning and need
confirmation; open child incidents get an offer to resolve them together; pending approvals
block.

**Closing** (REQ-INC-096): auto-close 3 business days after resolution if the requester does
not answer.

**Reopen window** (REQ-INC-098): 7 days after resolution or closure. After that, a requester
reply creates a new linked incident.

**Notifications on by default** (REQ-INC-130): acknowledgement to the requester on creation;
assigned to the assignee; public reply or note to the requester; requester reply to the
assignee; resolved to the requester (with confirm and reject links); reopened to the assignee;
unassigned for 30 minutes to the group; mention to the person mentioned.

**Other defaults:**

- trash retention: 30 days (REQ-WI-020);
- checklist item limit: 100 (REQ-INC-077);
- copy limit: 20 (REQ-INC-033);
- attachment size: 25 MB per file (REQ-INC-079);
- list page size: 50 (REQ-INC-110).

---

## Open questions for the product owner

None open. The Phase 1 questions were answered on 2026-10-24 and are recorded as decisions:

1. Reference Area 14 is added as its own file (D-039).
2. Tiptap and server-side sanitising move to the first incidents work package (D-040,
   REQ-INC-064).
3. The Appendix A defaults are approved; every default is editable per tenant (D-041).
4. MVP is the Stage 1 internal go-live plus one design-partner customer (D-042).
5. Declaring a major incident is Essentials; the war room and the post-incident review are
   Professional (D-043, REQ-INC-141, 143, 144).
6. Features outside the edition show disabled with an upgrade hint; an admin can hide them
   (D-044, REQ-WI-025).
7. Separate counters per type with an admin-editable prefix (D-045, REQ-WI-002).
8. Undo merge is V1 (D-046, REQ-INC-150).
9. Worklog time is MVP; costs and billable time are V1 (D-047, REQ-INC-067, 068).
10. Notifications in English and Arabic at MVP, Urdu at V1 (D-048, REQ-INC-130, 133).
11. AI model access: fair-use allowance on SaaS, bring your own key for Enterprise, local model
    on-prem and air-gapped; pending a pricing decision (D-049, section 20).
12. MonetX recovery auto-resolves by default; a technician's incident gets a "source
    recovered" note and the assignee is notified instead; configurable (D-050, REQ-INC-030).
