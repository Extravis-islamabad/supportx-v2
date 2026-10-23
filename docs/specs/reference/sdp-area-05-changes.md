# Area 5: Changes

## Navigation path

- **Change list:** left nav > More > Changes. After first use, "Changes" also appears in the main left rail. A guessed direct URL (`/ui/changes`) returns "URL not found".
- **Change detail:** click a change title in the list.
- **Settings (Setup):**
  - Setup > Customization > Change Management. Tabs: Change Type, CAB, Change Risk, Reason for Change, Closure Code, Change Role, and Stage and Status. The last two sit in the "…" overflow, and the overflow contents change depending on which tab is selected.
  - Setup > Templates & Forms > Change Template.
- Workflow design belongs to Area 12. Only the read-only execution diagram on a change was viewed here.

## Screens and what they do

1. **Change list.**
   - Three layout toggles: compact list, detailed list, calendar.
   - Each row shows ID, title, stage/status, task progress ring, priority, change type (with a coloured square), template and workflow.
   - A vertical "Approved Changes" tab sits on the right edge.
   - There are 12 public views plus Trashed Changes:
     - All Changes
     - Approved Open Changes
     - All My Changes
     - Closed Changes
     - Changes From Maintenance
     - My Approved Changes
     - My Closed Changes
     - Open Changes Assigned to Me
     - My Open Changes
     - My Unapproved Changes
     - Open Changes
     - Unassigned Changes
   - A funnel icon opens a custom-view builder, the same pattern as Problems.
2. **Change calendar.**
   - Month and week views with prev/next arrows and a month picker. It has its own New Change split button.
   - A "Showing" dropdown switches between Changes and "Freeze and Maintenance Windows".
   - A filter panel filters by Services and Sites, can show the Release Schedule, and has Reset and Apply.
   - A change is drawn as a bar spanning its scheduled start to end. The seeded CH-4 spans several weeks.
   - The "Approved Changes" side panel lists approved changes for the selected day. Today it showed CH-7, scheduled from 23 Oct 5:20 PM to 25 Oct 5:20 PM, type Standard.
3. **New Change menu.** A split button with a search box, grouped by template:
   - General: General Template, Normal Change Template, Standard Change Template.
   - Emergency: Emergency Template.
4. **New Change form.** Described in the Fields section below.
5. **Change detail page.**
   - Header buttons: Edit, Assign, Print, Scheduler, Workflow, Actions, and prev/next arrows.
   - A left stage rail shows the eight stages: Submission, Planning, CAB Evaluation, Implementation, UAT, Release, Review, Close.
   - Below the rail is a left menu: Roles, Associations, Conversations, Tasks, Reminders, Worklogs, Approvals, Announcements, History.
   - A right panel shows Change ID, Status, Workflow, Template, Change Type, Change Owner, Approval Status and Attachments. Under it is an ASSOCIATIONS block with counts for:
     - Linked Changes
     - Requests Caused by Change
     - Requests that Initiated Change
     - Associated Problems
     - Projects caused by Change
     - Project that initiated the Change
     - Associated Releases
   - Each stage has its own tab strip (see the Stage detail table below).
6. **Workflow execution view.**
   - Opened from the Workflow button, it is a read-only diagram.
   - Controls: a "Highlight Executed Path" toggle, zoom controls, and a "⋮" menu (Log Viewer, Copy Link, Export as PDF, Help).
   - The diagram runs Start > eight stage boxes > End. Each stage box holds its statuses. The statuses per stage in the General Change Workflow are:

| Stage | Statuses shown |
|---|---|
| Submission | Accepted, Rejected, Requested |
| Planning | Approved, Rejected, Planning In Progress |
| CAB Evaluation | Approved, Rejected, Approval Pending |
| Implementation | Completed, In Progress |
| UAT | In Progress, Accepted, Rejected |
| Release | In Progress, Completed, Cancelled |
| Review | Completed, Failed, In Progress |
| Close | Cancelled, Completed, In Progress |

   - A stage is left through its "completing" status, and a connector links that status to the next stage's entry status.
7. **Change Scheduler** (button on the detail page).
   - A full-screen month/week calendar for scheduling this change against others.
   - Buttons: "Configure Change Schedule" and "Configure Release Schedule". Each is a small dialog with Scheduled Start, Scheduled End, Save and Cancel.
   - A toggle "Include overlapping changes" shows other changes in the same period.
   - Freeze windows are drawn on the calendar. Clicking one opens a panel with its name, applicability, what it applies to, recurrence, next occurrence and conditions.
8. **Change Management settings.** One list per tab; every list has a "New …" button.
9. **Change Template list and template editor.** Described in Configuration options.

### Stage detail (tabs per stage, from CH-8)

| Stage | Tabs | Notable content |
|---|---|---|
| Submission | Details, Tasks, Associations, Approvals, Status Comments | Associations lets you attach a "Project that initiated the change". Approvals shows "mail server not configured". |
| Planning | Details, Schedule, Tasks, Associations, Status Comments | Details has sections for Impact Details, Rollout Plan, Backout Plan, Checklist, each with an Edit link. Schedule has a Release Schedule and a Downtime Schedule. |
| CAB Evaluation | Details, Approvals, Tasks, Status Comments | CAB evaluation notes and attachments. |
| Implementation | Details, Tasks, Associations, Status Comments | Implementation notes and attachments. |
| UAT | Details, Tasks, Status Comments | UAT scheduled and actual start/end, UAT description. |
| Release | Details, Downtime, Associations, Tasks, Status Comments | Release actual start/end, release description, issues. |
| Review | Details, Tasks, Status Comments | Next Review On, review description, attachments. |
| Close | Details, Tasks, Status Comments | Closure Code, close description, attachments. |

## Fields (New Change form, Normal Change Template)

Selectors at the top: **Select Workflow** and **Select Template**. The workflows offered are:
- General: Firewall Workflow - General Change Workflow, General Change Workflow, Standard Change Workflow.
- Emergency: Emergency Change Workflow, plus a "Security Vulnerability Update …" workflow (name truncated).

| Field | Type | Required | Options / values | Notes |
|---|---|---|---|---|
| Change Requester | user search | no | any user, with an "add requester" icon | The test record showed "Requested By N/A". |
| Site | dropdown | no | Base Site | |
| Change Type | dropdown | no | Major, Minor, Normal, Significant, Standard | List is configurable in Setup. |
| Group | dropdown | no | technician groups | |
| Retrospective | dropdown | no | Yes / No (default No) | Meant for changes recorded after they were done. |
| Change Owner | user search | no | technicians | |
| Impact | dropdown | no | Affects Business, Affects Department, Affects Group, Affects User, High, Low, Medium | Mixes two different scales in one list. |
| Change Manager | user search | no | technicians | |
| Urgency | dropdown | no | High, Low, Medium, Normal, Urgent | |
| Stage | read-only | yes | auto "Submission" | Never editable by hand. |
| Priority | dropdown | no | Critical, High, Low, Medium, Normal | Not calculated from Impact/Urgency. |
| Status | dropdown (read-only on create) | yes | auto "Requested" | |
| Change Risk | dropdown | no | High, Low, Medium | Manual choice. |
| Status Comment | text (read-only on create) | yes | auto note that status is set by creation | |
| Category, Sub Category, Item | cascading dropdowns | no | the helpdesk category tree | |
| Scheduled Start / End | date-time pickers | no | | |
| Services Affected | multi-select | no | service catalog | |
| Assets Involved | multi-select with "+" | no | assets | This is the link between a change and assets. |
| Reason for Change | dropdown | no | 8 values, listed under Configuration options | |
| Title | text | **yes** | | The only truly required user input. |
| Description | rich text | no | | |
| Attachments | file | no | | |
| Implementation Status | dropdown | no | Implementation Due Violated, Implementation Completed | |
| Budget ($) | currency | no | | |
| Change Approver | team/user selector | no | | The Roles section sits on the create form. |
| Line Manager | team/user selector | no | | |
| Reviewer | team/user selector | no | | |
| Implementer | team/user selector | no | | |
| UAT Owner | user selector | no | | |

Fields shown in the form are laid out in three sections: Submission Stage, CSI Section, Roles.

**Edit form behaviour.**
- The Edit form on the detail page shows the same fields.
- Status is a dropdown there, but Status Comment is disabled. Saving a status change from the Edit form therefore fails with "Provide value for field Status Comment".

## Actions and menus

- **List toolbar:** column chooser, search, New Change (split button), Delete, Pick Up, Close, Assign (dropdown), export, and a few icon tools.
- **Detail header:** Edit, Assign, Print, Scheduler, Workflow, Actions, prev/next.
- **Actions menu** (positions shift, so read the label first):
  - Add Note, Add Task, Add Task from Template, Add Reminder, Add Worklog, Copy Change, Delete Change.
  - Notify: Make an announcement, Send Notification.
  - Resolution: Enter Impact Details, Enter Rollout Plan, Enter Backout Plan, Enter Checklist, Enter Review Details.
  - Conflict: Refresh Schedule Conflicts.
- **Status popup (right panel).**
  - Click the Status value to open a small popup with Stage (locked), Status dropdown, Status Comment (becomes required once the status changes), Save and Cancel.
  - In the Submission stage the options are Requested, Requested for Information, Submitted for Authorization.
- **Linked Changes (Associations):** an Attach dropdown with Parent Change and Child Changes. Columns: Change ID, Title, Change Type, Stage, Status, Priority, Change Owner.
- **Roles page:** shows Change Requester, Change Owner, Change Manager, Change Approver, Line Manager, Reviewer, Implementer and UAT Owner, each editable through an Edit link.
- **Planning > Associations:** "Requests that Initiated Change" and "Associated Problems", each with Attach and Detach.
- **Planning > Schedule > Downtime Schedule:** Add Downtime, with columns Description, Downtime Type, Scheduled Start, Scheduled End.
- **Planning > Schedule > Release Schedule:** Scheduled Start/End, with links to the Freeze Windows and Maintenance Windows pages.

## Configuration options

**Setup > Customization > Change Management**

- **Change Type** (5 rows, each with a colour and a description). Standard carries a green "shield" marker and the rest a grey one; this is probably a "pre-approved" flag, but I did not open the edit form.

| Type | Colour | Meaning (from list) |
|---|---|---|
| Major | red | high impact and/or heavy resource needs |
| Minor | yellow | smaller impact |
| Normal | teal | no description |
| Significant | amber | routine, low impact |
| Standard | green | routine, low-impact changes |

- **CAB (Change Advisory Board).**
  - One seeded CAB: "Operational CAB".
  - The New CAB dialog has Name (required), Description, and CAB Members (required, multi-select).
  - A CAB is therefore just a named group of users.
  - There is also a CAB role (see Change Role) used on the CAB Evaluation stage.
- **Change Risk.** Just three values (High, Low, Medium), each with a short description. There is no matrix, score or weighting, so risk is not calculated.
- **Reason for Change** (8 seeded values):
  - Anti virus/firewall upgrades
  - New services
  - Patch updates
  - Patch updates for new features
  - Productivity improvements
  - Security compliance
  - Upgradations based on technology changes
  - Vulnerability fixes and minor improvements
- **Closure Code.** Present as a tab; its content was not opened in this area.
- **Change Role** (9 seeded roles, each with a description):
  - CAB (Change Advisory Board)
  - Change Approver
  - Change Manager
  - Change Owner
  - Change Requester
  - Implementer
  - Line Manager
  - Reviewer
  - UAT Owner
- **Stage and Status.**
  - Eight stages are listed with descriptions: Submission, Planning, CAB Evaluation, Implementation, UAT, Release, Review, Close.
  - Each stage's row menu has only "Edit", and there is a "New Change Stage Status" button at the top.
  - Expanding a stage shows its statuses. Each status row has an edit pencil and a delete icon, plus the columns Name, Description and Notify.
  - CAB Evaluation has three statuses: Approval Pending, Approved, Rejected. Their notify lists include Change Manager and CAB.
  - So notifications are configured per status.

**Setup > Templates & Forms > Change Template**

- Four system templates (Created By = System):

| Template | Type | Workflow | Notes |
|---|---|---|---|
| General Template | General | General Change Workflow | The default (star). Its toggle is greyed out, so it cannot be disabled. |
| Emergency Template | Emergency | Emergency Change Workflow | |
| Normal Change Template | Normal | none set | |
| Standard Change Template | Standard | none set | |

- Columns: Template Name, Workflow, Created By, "Available for requesters", Status (on/off toggle).
- Buttons: New Change Template, Copy Template.
- **Template editor** (opened view-only on the Emergency Template, then cancelled):
  - Top bar: Preview button.
  - Left nav: Stages (Submission through Close, eight entries), then Roles, Tasks, Form Rules, Additional Settings.
  - Header fields: Name (required), Comments, Type (Emergency in this case), Workflow.
  - The form area is a sectioned drag-and-drop canvas, with a gear icon on each section and a "Move Section" link.
  - The Details and Tasks tabs exist per stage.
  - The right panel has two tabs:
    - Available: fields not yet used (Budget, CIs Involved, Implementation Status) plus a "New section" block.
    - New: 19 field types for adding custom fields: Single-line, Multi-line, Pick List, Numeric, Date/Time, Email, Multi-Select, Phone, Web URL, Lookup, Check Box, Radio Button, Currency, Decimal, Percent, Auto Number, Decision Box. (Two further entries beyond the visible ones were not scrolled to.)
  - Additional Settings contains:
    - Template Availability: "Available for requesters" checkbox, then User Groups (defaults to all requesters).
    - Task Trigger Settings: "Trigger Tasks" dropdown, defaulting to "Manually".
  - A Template/Workflow summary is shown on the right.
  - This is the same editor design as the Problem Template. Area 12 should treat it as one shared editor family.

## Automation / triggers / rules in this area

- **Workflow.**
  - Each change is bound to a workflow, which defines which statuses are allowed inside each stage and which status finishes a stage.
  - A change moves between stages when a "completing" status is reached. For Submission that is Accepted, which comes from approval.
  - Stage itself is never set by hand.
- **Approvals.** Submission, Planning (approved/rejected) and CAB Evaluation statuses are driven by approvals. Approving needs mail, so none of this could be exercised.
- **Freeze windows.**
  - A seeded freeze window, "Restrict Change Creation on Weekends", applies to all changes.
  - It applies to *Change Creation* only, repeats weekly on Saturday with no end, and has the condition "Change Type is Normal".
  - Its next occurrence is Oct 24 to Oct 25, 2026.
- **Task triggers:** each template has a "Trigger Tasks" setting, default Manual. Other options were not opened.
- **Status notifications:** configured per stage status through the Notify column.
- **Form Rules, Tasks** (per template): present in the template editor, not opened in this area. Business rules and automation apply in Area 12.

## Behaviour observed in tests

1. **Created CH-8** "ZZ-CLAUDE-TEST change 1" with the Normal Change Template and General Change Workflow, Change Type Normal, Priority Medium, Risk Medium. Impact and Urgency were left empty and nothing was auto-filled.
   - After saving, the stage/status was Submission / Requested.
   - Change Owner was "Not Assigned" and Approval Status "-". No assignment rules fired.
   - A "General Change" badge appeared.
2. **Impact and Urgency do not drive Priority or Risk.** Choosing Impact and Urgency did not change Priority or Change Risk on the form. This product has no priority matrix for changes.
3. **Scheduling.**
   - I set CH-8 to Oct 24 7:07 pm to Oct 25 7:07 pm in the Scheduler, which falls inside the weekend freeze window, and saved.
   - No warning, conflict message or block appeared. The change simply showed beside the freeze window on the calendar.
   - Actions > Refresh Schedule Conflicts produced no visible output.
   - The freeze window is creation-only, which probably explains why a schedule change was never checked.
4. **Manual status change.**
   - I set CH-8 to "Submitted for Authorization" with a comment through the status popup. It saved and showed "Change details updated".
   - The Workflow button then turned red, with a popup saying the execution status was "Violated" and that the change was not following the workflow. The workflow expects Accepted/Rejected from the approval, and approval needs a mail server.
   - The change was not blocked or reverted, only flagged.
5. **Edit form versus popup.** In the Edit form the Status Comment box is disabled, so changing status there fails. The inline popup works.
6. **History (CH-8)**: three entries so far, each with date, time, operation and description, plus a filter box ("filter by operations and fields"):
   - Change Created
   - Change Updated (schedule changed, with old and new dates)
   - Change Updated (status changed)
7. **Associations were not populated.** All counts stayed 0. I only observed the Attach and Detach controls and the panels; I did not link real incidents, problems, assets or releases.
8. **Emergency vs Standard flow.**
   - The Emergency Template is bound to the Emergency Change Workflow, and the Standard and Normal templates have no workflow set (the user picks a workflow on the New Change form).
   - I did not create changes from the Emergency or Standard templates, so I cannot say whether their stage lists or required fields differ.

## Edition notes

- This is a trial on the Enterprise tier. Change workflows, freeze/maintenance windows, CAB roles, release schedules and the custom template editor were all available.
- I do not know which of these are limited in lower editions.

## Weak spots / confusing UX

1. Change Risk is a bare 3-value dropdown with no calculation, no risk questionnaire, and no link to Impact or Urgency. This is a clear gap a competitor can fill.
2. The Impact list mixes two scales (High/Medium/Low and Affects User/Group/Department/Business).
3. Manual status changes are allowed and only flagged as "Violated", with nothing stopping them. Meanwhile the real way forward (approval) is dead without mail.
4. The Status Comment field is disabled in the Edit form, which blocks status edits there.
5. Freeze windows apply only to *creating* a change. Scheduling or moving a change into a freeze window gives no warning, and "Refresh Schedule Conflicts" gives no feedback.
6. Standard and Normal templates have no workflow bound, so the user must remember to choose the right workflow. This also means template and workflow are separate choices on the form.
7. The Standard change type looks special (a green marker) but nothing visible explains what it does. There is no visible pre-approval behaviour on a Standard change.
8. A CAB is only a named member list. Nothing connects a particular CAB to a change type or template, or to the approval step, visibly.
9. The Stage and Status settings page lets you add statuses, but the page does not show how they fit into the workflow. Changes there can make a change violate its workflow.
10. The Actions menu, the "…" tab overflows (on both Setup and the detail page), and the right panel all shift positions. They are easy to mis-click.
11. The list URL is not guessable and Changes lives under "More".
12. The template editor and the workflow are in different places (Templates & Forms versus Automation), so setting up a change type means working in three screens.

## Test records created

- **CH-8 "ZZ-CLAUDE-TEST change 1"** (Normal Change Template, General Change Workflow). Current state: Submitted for Authorization / Submission, scheduled Oct 24 7:07 PM to Oct 25 7:07 PM, workflow flagged Violated. It is a test record and nothing was deleted.
- Existing sample changes CH-1 to CH-7 were not modified.
- No Setup item was saved. The New CAB dialog and the Emergency Template editor were opened and cancelled.
- Earlier-area test records are unchanged (requests #36 to #41, PB-5, and PB-6 which stays in trash).

## Not covered (so you can decide)

- Creating a change from the Emergency and Standard templates and comparing forms.
- The Closure Code tab, freeze/maintenance window admin pages, Add Task / Roles editing / Copy Change on CH-8.
- Real links to incidents, problems, assets and releases.
- Approvals and CAB voting (blocked by the missing mail server).

=== END OF AREA 5 ===
