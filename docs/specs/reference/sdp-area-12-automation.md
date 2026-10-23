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

# Area 12b: Automation follow-up (Notification Rules, Workflows, Life Cycles, SLA pause, Triggers, Business Rule extras, Execution order, Skipped items)

This report is appended to Area 12. Everything was done on ZZ-CLAUDE-TEST items only. Nothing existing was edited, disabled or deleted. The one irreversible step was the English default notification templates, which you allowed.

## Navigation path

- Setup (gear icon) > Automation > Notification Rules, Workflows, Life Cycles, Triggers, Custom Actions, Business Rules, Service Level Agreements, Technician Auto Assign, Asset Auto Assign, Conflict Detection.
- Setup > Templates & Forms > Incident Template, Form Rules, Custom Scripts.
- Direct URLs use `/app/itdesk/AdminDetails.cc?forwardTo=` followed by `wfrule`, `sla`, `RequestLifeCycle`, `wftriggers`, `incidentWorkflow`, `TechAutoAssign`, `AssetAutoAssign`, `freeze_windows`, `incident_fafr` or `CustomScript`.

## Screens and what they do

### 1. Notification Rules

- **First visit.** The page showed "Notification Templates Generation" with a language picker. I chose English and clicked Save and Continue. This is a one-time step and cannot be undone. It filled every rule with ready-made email subject and body text.
- **Tabs.** Request, Problem, Change, Project, Release, Solution, Asset, CMDB, and an overflow with Purchase, Contract, Task and Other Notifications.
- **Rule layout.** Each rule is one row with three channels: email, SMS and mobile push. Each row has recipient pickers and a pencil icon, "Customize Notification Template".
- **Recipients.** Choices include the requester, the technician (owner), the technician group, approvers, followers, specific users, and role-based picks, depending on the rule.
- **Template editor.** It has a Subject and a Message. Typing `$` opens variable autocomplete, for example request ID, subject, requester, technician, status and due date. Variables are listed per module.
- **Header controls.** "Rich Text format (HTML)" and "With Default Templates".
- **Junk Notification Filter.** This sits in the same area and suppresses automated senders.
- **Defaults.** Some rules are ON by default, for example resolved-to-requester email and the approval notifications. Many others are OFF by default.
- **Limitation.** Mail is not configured, so no notification was sent. I checked rule options and templates only.

### 2. Workflows

- **List.** The page shows name, associated templates and "Workflow Settings: Global: Show all statuses". The row gear menu offers Edit, Delete, View History and Copy. There is no enable/disable switch. A workflow is active only while a template points to it.
- **Designer.**
  - A new workflow starts empty. You add the first Status node, and Start and End appear on their own.
  - You drag from a node's hover-only dot to open the Add Node menu.
  - Flow node: Status.
  - Condition nodes: If, Wait For, Switch.
  - Action nodes: Notification, Field Update, Task, Checklist, Custom Function, Webhook, Timer.
  - Branch nodes.
  - Fit-to-screen and Save are in the toolbar.
- **Validation on save.** There must be at least one Completed status, a path from Start to End, and every node must be linked.
- **Node dialogs.**
  - If: a name and criteria, or a custom function. The operators are is, is not, is changed, is empty, is not empty, contains, does not contain, begins with and ends with. It has Yes and No outputs.
  - Wait For: applies to Requests, Tasks, Approval Levels, Approvals, Notes, Email responses, Checklists and Worklogs. The operation is "Edited", plus conditions.
  - Field Update: pick an existing field-update action or create a new one, with an alternate path if it fails.
  - Timer: a duration (days, hours, minutes), an operational-hours option, a pause option, Level 1 and Level 2 actions (Notification, custom function, Field Update, Task, Webhook), and abort conditions.
- **Execution view.** A "Highlight Executed Path" toggle, a Log Viewer in the ⋮ menu, and a red link on discarded or failed steps. The log columns are Execution, Transition Type, Status, Comments, Start Time, End Time, Time Spent and Performed by.

### 3. Life Cycles

- **Editor.**
  - A Details tab with a description, associated templates, and drag-and-drop statuses (Pending Verification, Staging, Rejected, In Progress, On Hold, Canceled, Closed).
  - Map View and Linear View.
  - Publish, Save as Draft and Cancel.
- **Transition form.** Each transition has three tabs:
  - Before: Scope (organization roles, groups, roles such as "Group Head of Request" and "User > Reporting To") and Criteria.
  - During: Mandatory Fields and a Rule Set.
  - After.
- **List.** Name, associated templates, last modified, status and an on/off toggle. Publishing needs at least one associated template.

### 4. Triggers and Custom Actions

- **Trigger form.** Name, Description, applies to Requests, event (Created, Edited or Deleted), timing (any time, within or outside operational hours), an Enable flag, conditions, and custom actions.
- **Action types.** Notification, Approval, Timer, Task, Checklist, Custom Function, Webhook.
- **Custom Actions page.** It is the shared library of Timer and Task actions that triggers and workflows reuse.

## Fields

| Field | Type | Required | Options / values | Notes |
|---|---|---|---|---|
| Workflow name | Text | Yes | – | Attached via the template's Workflow field |
| If node: condition | Criteria builder | Yes | 9 operators, or custom function | Yes and No outputs |
| Wait For: applies to | Dropdown | Yes | Requests, Tasks, Approvals, Notes, Emails, Checklists, Worklogs | Operation "Edited" |
| Timer: duration | Number plus unit | Yes | Days, hours, minutes | Operational hours optional |
| Timer: Level 1 and Level 2 | Action pickers | No | Notification, Custom Function, Field Update, Task, Webhook | Run at their own offset |
| Timer: abort | Choice | No | "Don't Abort Until Timer Ends" or abort conditions | – |
| Life cycle: scope | Multi-select | No | Roles, groups, "Group Head of Request", "User > Reporting To" | Decides who sees the transition button |
| Life cycle: mandatory fields | Multi-select | No | Any request field | Enforced when the transition is run |
| Trigger: event | Dropdown | Yes | Created, Edited, Deleted | – |
| Trigger: time | Radio | Yes | Any time, Within, Outside operational hours | – |
| Business rule: cascade | Toggle | No | On or Off | Also has a "Level" setting |
| Business rule: abort | Action | No | Abort with a custom message | Blocks request creation |

## Actions and menus

- **Workflow list gear menu:** Edit, Delete, View History, Copy.
- **Workflow ⋮ menu:** Log Viewer.
- **Life cycle editor:** Publish, Save as Draft, Cancel, and the Map and Linear view switch.
- **SLA page "..." menu:** includes "Disable all SLA based mail escalations". I did NOT click it.
- **Request page after a life cycle is attached:** a Status and Transitions bar appears, and the Close and Cancel buttons disappear from the toolbar.

## Configuration options

- **Template Workflow field.** It attaches one workflow to an incident template. Workflows apply only to requests raised from that template.
- **Template Tasks tab.** Tasks can be added to a template with "Trigger Tasks" set to On creation of Incident Request. Tasks appear on the request as 0/N.
- **Template Life Cycle.** A life cycle is attached to the template.
- **Form Rules.** The incident Form Rules list and a New Form Rule form were opened, but no rule was saved.
- **Custom Scripts.** The page is empty. It has New Custom Script, Actions and Import Sample Scripts. I did not import anything.
- **Technician Auto Assign.** Global "Enable Auto-assign" was OFF originally.
- **Asset Auto Assign.** It was read only, and the form was not saved.
- **Freeze Windows (Conflict Detection).** It was read only. A New Freeze Window form was opened and cancelled.

## Automation / triggers / rules in this area

### Workflows built

- **Workflow 1** (Start > Open > ZZ field update 1 > Resolved > End).
  - The Field Update sets Approval Status and failed with "Cannot set approval status for incidents".
  - A failed action did not block the parallel manual path.
- **Workflow 2.** It uses If, Wait For and Timer. There was a wiring problem and Wait For was discarded, so I rebuilt it.
- **Workflow 3** (Start > Open > Wait For "wait in progress 3" > Timer "timer 1" > Resolved > End). It saves and runs.

### Trigger "ZZ-CLAUDE-TEST trigger 1"

- It fires on Request Created, any time, when Subject contains "ZZ-CLAUDE-TEST TRG".
- Its actions are Task action 1, then Timer 1.
- Timer 1 waits 1 minute, then Level 1 runs Task action 1 again.

### Business rules

- **"BR 1"** sets priority High, cascade OFF.
- **"BR cascade"** has cascade ON, Level = Tier 2.
- **"BR abort"** aborts with a custom message.
- Cascade and abort rules both match subject containing "ZZ-CLAUDE-TEST CAS".

### Life cycle "ZZ-CLAUDE-TEST life cycle 1"

- It is Published and enabled.
- Transition "ZZ Start" runs Start > Open.
- Transition "ZZ Resolve" has the mandatory field Resolution and scope "Group Head of Request".

## Behaviour observed in tests

### 2. Workflow on a ZZ template

- Requests #46, #47 and #48 were raised from templates WF, WF2 and WF3.
- A workflow instance is created at request creation. The History shows "Workflow Instance Created".
- The If node worked. The Field Update failed on incidents, as noted above.
- Wait For on Status showed "Discarded" when I changed the status by hand, so the Timer after it was never reached.
- **Timer node.** I could not prove it inside a workflow. I proved the Timer action through the trigger instead (item 5).

### 3. Life cycle

- I published the life cycle after associating "template LC". Publishing failed first until a template was attached.
- Requests #52 and #53 were raised from that template.
- The Resolve transition demanded the Resolution field. The scope "Group Head of Request" restricted who could run it.
- #52 was moved to Resolved.

### 4. SLA pause (inconclusive)

- Requests #50 and #51 used the ZZ SLA. Moving to On Hold and to In Progress both showed "Timer Stopped" on Due By.
- The exact due-time change could not be measured. The test ran on a Saturday, and operational hours pushed the due date to Monday, so the minute-level change was hidden.
- **A retest on a weekday is needed.**

### 5. Trigger

- Request #49 fired both actions.
- History showed Task Added by the trigger, then Timer Initiated, then a second Task Added "Level 1 action of timer 1" one minute later.

### 6. Business rule extras

- **Abort.** An attempt to create "ZZ-CLAUDE-TEST CAS request 1" was blocked by the abort rule with its custom message. No record was created.
- **Cascade.** A matching rule with cascade OFF stops all later rules, including the abort rule. With cascade ON on the earlier rule, the abort rule is reached.
- Request #54 was a BR 1 test.

### 7. Execution order on request #56

Subject: "ZZ-CLAUDE-TEST BR ZZ-CLAUDE-TEST SLA ZZ-CLAUDE-TEST TRG order 2".

- The History records time to the minute only. The order below is the History list read from the bottom (oldest) to the top (newest). Business rule and SLA leave no History line, so I inferred their place from their effects.
- **01:56 AM, in this order:**
  1. The business rule ran first, and the priority became High.
  2. The SLA was chosen on the new priority. The existing "High SLA" (60 minutes, operational hours) matched, and Due By shows "Due in 60Mins". The ZZ SLA lost because it is last in the order.
  3. Technician auto-assign ran. The History line is "Request Created: Technician assigned through Tech Auto Assign". It picked Shawn Adams (round robin).
  4. Workflow Instance Created for "ZZ-CLAUDE-TEST workflow 3".
  5. The trigger ran, and Task "ZZ-CLAUDE-TEST auto task" was added.
  6. Timer "timer 1" was initiated by the trigger.
- **01:57 AM:** The timer's Level 1 action added the task again, "Performed through Trigger … Level 1 action of timer 1".
- **Other points.**
  - The template-level task ("template task 1") did not show in this History. The request shows Tasks 0/2.
  - Request #55 matched only the business rule, because its subject used the wrong strings.

### 8. Skipped items now covered

- **Service Request SLA list.** The module dropdown on the SLA page offers Incident and Service Request. The Service Request list is empty (0 SLAs).
- **Incident SLA list.** High, Medium, Normal and Low SLAs, plus the ZZ SLA.
  - Resolution: 1 h, 2 h, 4 h and 8 h for High, Medium, Normal and Low.
- **Existing business rule "Hardware Dispatch".** Condition: Category is Desktop Hardware AND Subject contains "System Crashed". Action: Field Update, Group = Hardware Problems (Base Site), "Override values with business rule values" disabled. Applies to Requests when Created, cascading off.
- **Other existing rules.** "Network" and "Printer Requests" also run on Created with cascading off.
- **Major Incident Life Cycle (view only).**
  - Associated template: "Major Incident Management". Status Published, last modified by System on Oct 23, 2026.
  - Transitions in Linear View: Start to Staging, In Progress to Staging, In Progress or On Hold to Resolved, In Progress or Resolved to On Hold, and Staging, On Hold or Resolved to In Progress.
  - Statuses available: Open, Pending Verification, Rejected, Canceled, Closed.
  - I closed the editor without saving.
- **Custom Scripts and Form Rules.** The Custom Scripts list is empty. I opened a New Form Rule form and did not save it. I did not build a working form rule or custom script on a ZZ template.

## Edition notes

- The account is the Enterprise trial, which expires Nov 22, 2026.
- Workflows, life cycles, triggers with Timer actions, custom functions and webhooks all worked on this edition.
- Mail is not configured, so no notification, escalation or SLA mail was sent.

## Weak spots / confusing UX

- **Hover-only link dots.** Node output dots are visible only on hover, and a drag that misses lands on the node and moves it.
- **Wait For discarded.** It is discarded when the status is changed by hand instead of by the workflow, so a Timer after it can never run that way.
- **Field Update failure.** Choosing a field that is invalid for incidents only fails at run time, not at design time.
- **Life cycle publish error.** It does not say a template is needed. After the error, the template picker disappears until you reopen the editor.
- **SLA ordering.** The new ZZ SLA was last in the list, so an older broad SLA beats it. This is easy to miss.
- **Business rule priority change.** It silently changes which SLA applies.
- **History timestamps.** They are per minute, so true order inside a minute is guessed from list order.
- **Layout shifts.** The request form moved during typing. A subject typed before the shift was lost.
- **Auto-generated notification templates.** The one-time generation step is irreversible and the prompt does not say so.

## Test records created

See the full list below.

## Limits of this area

- **Load balancing.** Skipped, because it needs several real login users (Area 15).
- **Timer node.** It was not proven inside a workflow. Only the Timer action was proven, through the trigger.
- **SLA pause.** The exact due-time arithmetic was not obtained. It needs a weekday retest.
- **Notification sending.** Not tested, because mail is not configured.
- **Form rules and custom scripts.** I saw the screens but did not run a rule or script.
- **Template task.** The template task "template task 1" did not show in #56's History, so its firing order is unknown.

## Everything created in Area 12 and 12b

- **Workflows:** "ZZ-CLAUDE-TEST workflow 1", "workflow 2", "workflow 3".
- **Custom actions:** Timer "ZZ-CLAUDE-TEST timer 1" and Task action "ZZ-CLAUDE-TEST task action 1" (task "ZZ-CLAUDE-TEST auto task").
- **Field update:** "ZZ-CLAUDE-TEST field update 1" (Approval Status).
- **Trigger:** "ZZ-CLAUDE-TEST trigger 1".
- **Incident templates:** "ZZ-CLAUDE-TEST template WF", "template WF2", "template WF3" and "template LC" (with task "ZZ-CLAUDE-TEST template task 1").
- **Life cycle:** "ZZ-CLAUDE-TEST life cycle 1", Published and enabled.
- **Business rules:** "ZZ-CLAUDE-TEST BR 1", "BR cascade" and "BR abort".
- **Incident SLA:** "ZZ-CLAUDE-TEST SLA 1" (respond 3 min, resolve 5 min, Level 1 escalation to $Ticket Owner).
- **Requests:** #43 to #45 (Area 12 part 1), then #46 to #56 (12b). No record exists for the aborted CAS attempt.
- **Earlier ZZ records from Areas 1 to 11 are unchanged.**
- **One irreversible change:** English default notification templates were generated, with your permission.

### Settings restored

- **Technician Auto Assign "Enable Auto-assign".** It was OFF at the start. I switched it ON for the tests and back to OFF, and confirmed OFF after a reload.
- **All AI switches (Area 10).** OFF.
- **Notification rule switches.** I changed none.
- **Never clicked:** "Disable all SLA based mail escalations", "Scan Now", "Switch" edition, "Create Agents".
- **Opened and cancelled without saving:** Asset Auto Assign, the New Freeze Window form, the New Form Rule form, the Major Incident Life Cycle editor.
- **Left on:** the ZZ life cycle, ZZ trigger and ZZ business rules are enabled. They only match ZZ-CLAUDE-TEST subjects, and I did not disable them. Tell me if you want them switched off.

=== END OF AREA 12 (including 12b) ===
