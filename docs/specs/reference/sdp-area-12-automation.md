# Area 12: Admin part 2, Automation

I could not finish two things. I never saved a ZZ workflow, because the canvas kept failing validation. I never opened Notification Rules, because it starts with a one-time step that can't be undone. Details are under "Limits of this area".

## Navigation path
- Setup > Automation holds Business Rules, Service Level Agreements, Life Cycles, Triggers, Schedules, Custom Actions, Notification Rules, Closure Rules, Delegation, Technician Auto Assign, Asset Auto Assign, Workflows and Conflict Detection.
- Setup > Customization > Helpdesk > Priority Matrix.
- Setup > Instance Configurations > Operational Hours, Holiday Groups.
- Setup > Templates & Forms > Service Category (service request templates), Incident Template, Problem Template, Change Template.
- The Setup search box finds all of these; direct URLs only work for a few of them.

## Screens and what they do
- **SLA list and form.** Separate lists for Incident and Service Request, with a Site filter. Details are in the next section.
- **Technician Auto Assign.** One global page, not per group. Details are in the next section.
- **Business Rules.** Incident list with three existing rules: Hardware Dispatch, Network and Printer Requests.
  - Columns are Name, Applies to, Applied When, Cascade and Status.
  - Buttons are New Business Rule and Organize Business Rules (execution order).
- **Triggers.** Currently empty. The module menu offers Request, Problem, Change, Project and Release.
- **Schedules.** Currently empty. A schedule runs one custom function on a timetable.
- **Custom Actions.** The shared library of reusable actions, with tabs Notifications, Approvals, Field Updates, Timers, Tasks, Checklists, Custom Functions and Webhooks.
  - Existing entries: two notifications ("Hiring Team Notification", "Reminder Notification For Workflow Timer") and one field update ("Update Impact Details").
  - Each entry shows usage counts: Trigger, Workflow, Workflow/Lifecycle Transition, Timer and SLA.
- **Workflows.** Module switch for Incident, Service Request, Problem, Change, Release and Asset. The Incident list is empty.
  - The "..." menu has Global Workflow Settings and Export History.
  - A canvas designer opens after you name the workflow.
- **Life Cycles.** Modules are Request, Problem and Asset. One existing life cycle, "Major Incident Life Cycle", is published and tied to the Major Incident Management template.
- **Closure Rules.** Tabs for Request, Problem, Change and more.
- **Notification Rules.** Not opened (see Limits).
- **Delegation.** Disabled; it holds request-ownership and approval delegation options.
- **Priority Matrix.** 7 impacts by 5 urgencies, with every cell empty.
- **Operational Hours.** One default calendar, Monday to Friday 09:00 to 18:00, weekends non-working, plus a Special Operational Hours tab.
- **Holiday Groups.** Default Holiday Group (2 holidays) and Base Site Holidays (2).
- **Template designers.** Details are further down.

## Fields (table: field | type | required | options/values | notes)

| Field | Type | Required | Options/values | Notes |
|---|---|---|---|---|
| SLA Name | text | yes | | |
| SLA Site | dropdown | no | | |
| SLA Description | text | no | | |
| SLA Conditions | criteria builder | no | ~48 request fields; text operators: is, is not, is empty, is not empty, contains, does not contain, begins with, ends with | Or "no condition". |
| SLA Respond within | days, hours, minutes | no | | |
| SLA Resolve within | days, hours, minutes | no | | |
| SLA operational hours | checkbox | no | "irrespective of operational hours", with holidays and weekends sub-options | |
| SLA escalations | levels | no | Response: 1 level. Resolution: 4 levels. Each level has After/Before plus time, an Escalate To* target (org role or technician, including $Ticket Owner) and optional custom actions | |
| Auto-assign enable | checkbox | | | |
| Auto-assign applies to | radio | | Incidents / Incidents and Service Requests | |
| Auto-assign model | radio | | Round Robin / Load Balancing | |
| Auto-assign when | radio | | Created / Edited / Created and Edited | |
| Auto-assign on creation | radio | | Unassigned Only / All Requests | |
| Auto-assign availability | checkbox + radio | | Available on Created Date or Due Date | |
| Auto-assign exclusions | | | Exclude Technicians (picker); Exclude Requests (criteria) | |
| Business rule Name | text | yes | | |
| Business rule Description | text | no | | |
| Business rule applies to | dropdown | | Requests | |
| Business rule executes when | checkboxes | | Created, Edited, Deleted | |
| Business rule executes during | radio | | Any time / Within Operational Hours / Outside Operational Hours | |
| Business rule options | checkboxes | | Turn on cascade execution; Enable Rule | |
| Business rule conditions | | | By criteria (operators include "is changed"), by custom function, or none | |
| Business rule actions | | | "Execute custom actions" (Fields Update or Custom Function) or "Abort process execution" | |
| Trigger | same form as a business rule | | Without condition also possible | Actions here: Notification, Approval, Timer, Task, Checklist, Custom Function, Webhook. |
| Notification action | form | | Name, Description, Mode (Email/SMS), Applies to, Notify recipients*, Subject*, Message* | `$` autocompletes variables. |
| Webhook action | form | | Name, Description, URL*, Applies to, Method (GET/PUT/POST/DELETE), Endpoint (Cloud/Intranet), Connection link, Headers, Parameters | Daily limit 3000 calls (0 used). Buttons: Save, Save & Test. |
| Custom function | form | | Name, Description, Applies to, Use as (see below), Language (Deluge/Java/NodeJS), code editor with Syntax Builder | Buttons: Save, Save & Execute Script. |
| Approval action | form | | Name, Description, Approval Rule, Approvers*, email template (global or custom), settings (global or custom) | Approval rules include Anyone to Approve, Everyone to Approve, First Response Action, Majority to Approve. |
| Schedule | form | | Name, custom function*, start date and time (5-minute steps), Frequency Once/Daily/Weekly/Monthly/Yearly | |
| Life cycle | dialog | | Name*, Description, Associate Templates | |
| Life cycle transition | dialog | | Name*, Description | |
| Workflow | dialog | | Name*, Description | |

## Actions and menus
- **SLA list.**
  - Per-row gear and expand arrow, enabled toggles, and New SLA.
  - Organize SLA: rules run in list order, with up/down arrows.
  - The "..." menu has Delete and "Disable all SLA based mail escalations" (global; not clicked).
- **Business rules.**
  - Row gear and expand arrow, plus Organize Business Rules.
  - Setting Cascade makes later rules see changes from earlier ones.
- **Workflow canvas.**
  - Save, Save & Close, Cancel. The "⋮" menu has Reset, Undo, Redo, Select Tool, Manage Status and Help.
  - A right panel has "Drag & drop nodes" and "Details" tabs.
  - Node gear: Orientation, Delete. Hover a node to get connector dots; drag one out to add a node.
  - Clicking a link shows an x to delete it. The link label shows the transition type ("Auto").
  - A node can have an alternate path on error.
- **Life cycle editor.**
  - Drag statuses from the right panel. Buttons are Publish, Save as Draft and Cancel.
  - The legend shows status types: In progress, Stop Timer, Completed.
- **Template list rows.** Gear menu: Edit Template, Move, Delete Template, Disable.

## Configuration options

**Automation switches**
- **Auto-assign:** a single global switch. It was OFF originally.
- **Business rules, triggers, SLAs and custom actions:** per-item enabled toggles.
- **Delegation:** one global enable.
- **Closure rules (current values):**
  - A required-fields checklist of about 35 fields, none ticked.
  - The acknowledgment prompt is on, with closure code and comments not mandated.
  - Manual closure.
  - Status on closing: Closed (option Resolved).
  - No "only when tasks/checklists complete" conditions.

**Workflow design**
- **Node types**
  - Flow: Status.
  - Condition: If, Wait For, Switch.
  - Action: Notification, Field Update, Task, Checklist, Custom Function, Webhook, Timer.
  - Branch: Fork, Join.
  - There is no separate Approval node. Approval Status is a field you can set through a Field Update, and approvals are otherwise a trigger or template feature.
- **Validation rules**
  - At least one "Completed" status must be present.
  - End can only be reached from a Completed status through an If, Notification, Custom Function or Webhook node.
- **Existing field update "Update Impact Details":** it sets Impact to High and shows its related workflows.
- **Field Update picker:** supports New, Save and Save and Select.

**Statuses**
- **Status types:** In progress, Stop Timer, Completed. The Stop Timer group is the "pause on status" mechanism for SLAs.
  - Open, Pending Verification and Staging are In progress.
  - In Progress and On Hold are Stop Timer.
  - Rejected, Canceled, Closed and Resolved are Completed.
  - The SLA form itself has no pause control.

**Life cycle transitions**
- BEFORE: Scope (org roles, groups, roles who may run it) and Criteria (when the button shows).
- DURING: Mandatory Fields (system or additional fields; the technician sees them when running the transition).
- AFTER: Rule Sets (conditions plus custom actions).
- The first transition out of Start has BEFORE disabled.
- Validation: every stage needs an outgoing transition.

**Custom function**
- "Use as" options: Business Rule/Timer Condition/Workflow Action (returns a Boolean); Business Rule/Workflow Transition Pre Rule Action; Trigger/Request Life cycle/Timer/Workflow Transition Post Rule Actions.
- The Syntax Builder blocks are: set variable, comment, info, if/else, webhook, Zoho integration, invoke API, FTP/SFTP, and collection operations.

**Business-rule field list**
- **Fields a business rule can set:**
  - Assets, Category, CIs, Description, Group, Impact, Impact Details, Item, Level, Mode.
  - On Behalf Of User, Priority, Request Type, Scheduled Start/End Time, Service Category.
  - Status, Sub Category, Subject, Technician, Template, Urgency, Resolution, plus Additional Fields.
- **Override toggle:** "Override values with business rule values".

**Template designers**
- **Incident and Service Request**
  - Same drag-and-drop designer. Tabs: Technician View, plus Form Customization (help card and reference documents, shown in the request form or details page).
  - Sections have 1 or 2 columns, label orientation (Left/Top/Right) and collapsed state (Expanded/Collapsed/None).
  - Field properties are Mandatory, Requester can Set, Requester can View.
  - The right panel has Available fields and New fields. New field types: Single-line, Multi-line, Pick List, Numeric, Date/Time, Date, Email, Multi-Select, Phone, Web URL, Lookup, Check Box, Radio Button, Currency. There is also New section and a Preview button.
  - A Workflow / Life cycle picker with two tabs attaches one of them.
- **Service template extras**
  - Bound to a Service Category (service categories nest: sub-categories, service templates and incident templates).
  - Cost Details, Associate Technician Groups, Show to Requester.
  - An Approver(s) field.
  - On an existing service template: Resource Info, Approvals, Tasks, Checklists and Form Rules tabs.
  - Approvals tab: auto-send notifications, show approval status to requesters, assign technician only after approval, approval rule, Manage approval. Resource Info needs Service Cost enabled.
  - Actions menu: Copy Template, Add Task, Add Task from Template.
- **Problem**
  - Tabs Details, Analysis, Solution, Tasks, Form Rules.
  - Attaches a Workflow or Life cycle.
  - Extra fields: Impact Start/End Time, Problem Type, Reason for Outage.
  - Two templates exist.
- **Change**
  - A stage list on the left (Submission and more), a Type field (General, Emergency, Normal, Standard) and a Workflow.
  - Move Section; extra fields Budget, CIs Involved, Implementation Status.
  - Four templates exist; General and Emergency have change workflows.

## Automation / triggers / rules in this area
- Business rules are the first automation to run on a new request, and can set Priority, assign, or abort further processing.
- SLA rules run in the order you set, first match wins.
- Triggers run notifications, approvals, timers, tasks, checklists, custom functions and webhooks.
- Workflows and life cycles are attached to templates.
- Schedules run custom functions on a timetable.

## Behaviour observed in tests
- **SLA (request #43).**
  - Subject "ZZ-CLAUDE-TEST SLA request 1", Priority left unset, matched the ZZ SLA on creation. The Details tab showed the SLA name and Due By "Due in 4 mins".
  - At 3 minutes the system logged "First Response Overdue Status updated No to Yes" and the status icon changed.
  - At 5 minutes the system logged "Overdue Status No to Yes" and Due By showed "Delay by 4Mins".
  - The escalation to $Ticket Owner did not appear in History. No mail server is configured and the ticket had no owner, so I could not confirm whether anything was attempted.
  - Pause-on-status was not tested.
- **Auto-assign.** With the switch on, request #44 (no group) went to the trial admin, the only login technician. The other six technicians have no login, so I could not see round-robin or load-balancing spread across several people. A request with no subject match had no SLA ("No due date set").
- **Business rule (request #45).** The ZZ rule set Priority to High on creation. The request then showed Due By of 60 minutes, so the High default SLA used the rule's priority. That means business rules run before SLA assignment.
- **Workflow canvas.** Saving failed with the two validation errors listed above. I tried to remove the link from the Field Update node to End but could not confirm it was removed, so I cancelled without saving.
- **Life cycle.** Saving a draft with an orphan stage failed ("Open should have at least one outgoing transition"). After connecting Open to Resolved it saved as a draft.
- **Execution order (observed plus UI hints).**
  - Business rule runs first. SLA assignment follows, using the rule's output.
  - Auto-assign: I did not isolate its order against business rules.
  - Triggers, workflows and life cycles: not tested.
- **Blocked by no mail server:** SLA escalation mail, approval notifications, notification actions, and "Save & Test" of webhooks.

## Edition notes
- Enterprise trial. Webhook daily limit is 3000. Custom functions support Deluge, Java and NodeJS.

## Weak spots / confusing UX
- Auto-assign has no per-group setup and is incidents-only unless you tick the option.
- No pause control on the SLA form; pausing depends on status type.
- "In Progress" is a Stop Timer status by default.
- The workflow End-node validation is strict and the link-delete control is hard to hit.
- Add Node menu categories are icon-only until hovered.
- New request form: the Add Request button moves after you type a subject, so a first click can miss.
- Notification Rules forces a one-time irreversible template step before showing anything.

## Test records created
- Incident SLA "ZZ-CLAUDE-TEST SLA 1".
- Business rule "ZZ-CLAUDE-TEST BR 1" (enabled).
- Field update custom action "ZZ-CLAUDE-TEST field update 1" (Approval Status; created from the workflow dialog, and it stays even though the workflow was not saved).
- Life cycle draft "ZZ-CLAUDE-TEST life cycle 1" (Open → Resolved, transitions "ZZ Start" and "ZZ Resolve"), unpublished.
- Requests #43 (SLA test), #44 (auto-assign test) and #45 (business-rule test).
- A workflow named "ZZ-CLAUDE-TEST workflow 1" was started but **not saved**, so it does not exist.

**Settings changed and restored:** Technician Auto Assign "Enable Auto-assign" was OFF originally. I turned it ON to test and turned it back OFF; I verified OFF after a reload. Incidents, Round Robin, Created and All Requests were never changed.

## Limits of this area
- Notification Rules: not opened (one-time, irreversible template generation).
- Not saved or run: ZZ workflow, any trigger, schedule, webhook, approval, custom function or notification action.
- Not tested: pause-on-status (Stop Timer) behaviour, load-balancing, availability-based assignment, execution order beyond rule-then-SLA, cascade, and "Abort process execution".
- Not covered: Asset Auto Assign, Conflict Detection, Form Rules, Custom Scripts, the Service Request SLA list, the existing business-rule and life-cycle detail views, Project and Release template editors, and the Tasks tab on templates.

=== END OF AREA 12 ===
