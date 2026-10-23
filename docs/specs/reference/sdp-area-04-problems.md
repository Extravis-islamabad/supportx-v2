# Area 4: Problems

## Navigation path
- **List:** left nav > Problems (`/app/itdesk/ui/problems`). Quick Actions > New > Problem also works.
- **New problem:** Problems list > "New Problem" split button, then choose a template.
- **Detail page:** click a problem row (`/ui/problems/<id>/details`).
- **Setup:**
  - Setup > Customization > Problem Management has two tabs, Closure Code and Configurations.
  - Setup > Templates & Forms > Problem Template.

## Screens and what they do
1. **Problem list**
   - Title shows the current view name with a view dropdown; a funnel icon opens the custom-view builder; a grid/list toggle sits at the top right.
   - Toolbar: column chooser, search, New Problem (split button), Delete, Pick Up, Assign (dropdown), export, row layout and column settings. Bulk actions work on ticked rows.
   - Each row shows the ID (PB-n), title, status, task progress ring (% and done/total), priority, template and "Reported By". Row icons are a gear menu and a quick-view icon.
   - The instance has 4 sample problems (PB-1 to PB-4), all Open.
2. **Public views (12):**
   - All Problems
   - All My Problems
   - Closed Problems
   - Completed Problems
   - Known Errors
   - My Closed Problems
   - My Completed Problems
   - My Open Problems
   - My Pending Problems
   - Open Problems
   - Pending Problems
   - Unassigned Problems
   - There is also a Favorites group (star a view to pin it) and a **Trashed Problems** entry.
3. **Custom view builder (opened, not saved)**
   - Fields: view name (with a favourite star), rows of Column / Operator / value (add or remove rows with +/−), a "private custom view" checkbox, and Apply / Save / Cancel.
   - Column choices:
     - Approval Status, Category, Closed Date
     - Closure Details (submenu)
     - Created Date, Due By Date, Group, Impact, Item
     - Known Error Details (submenu)
     - Priority, Region, Reported By, Reported Date, Site, Status, Sub Category
     - Technician, Template, Title, Updated Date, Urgency, Workflow
     - Additional Fields
4. **Trashed Problems**
   - Toolbar: Restore, Delete (permanent). I did not press either.
   - A banner says trashed problems are deleted automatically after 30 days.
5. **New Problem form.** Template selector at top (General Problem Template, Major Problem Template). It is a single page with a Save and Cancel bar at the bottom.
6. **Problem detail page**
   - Header buttons: back, Edit, Assign, Close (hidden once Closed), Print, Actions menu, previous/next arrows.
   - Title block: ID, title, a "Problem" badge, "Reported By", date.
   - Tabs: Details, Analysis, Solution, Tasks, Reminders, plus a "…" overflow. The overflow holds Approvals, Worklogs, Conversations, Associations, Announcements, History. Choosing one swaps it into the visible tab row.
   - Right panel: Problem ID, Status, Life cycle, Workflow, Template, Priority, Known Error (Yes/No with an icon), Technician, Tasks progress (n / total), Reminders count, Approval Status, Attachments, Due By Date. Below is an ASSOCIATIONS block with counts for Associated Incidents, Associated Changes, Releases Caused by Problem and Release that Initiated Problem.
   - For a problem on a life cycle (PB-2, which I only viewed), a status box with a "Transitions" button appears above the tabs (for example "Analyse Root Cause").
7. **Details tab:** Reported By, Site, Impact, Group, Urgency, Technician, Priority, Status; the CSI section; Due By Date, Closed Date; Services Affected, Assets Involved, CIs Involved; Reported Date, Created Date; Attachments; Description.
8. **Analysis tab:** three collapsible blocks, each with its own "Add" link:
   - Impact Details (with attachments drop zone)
   - Root Cause
   - Symptoms
   - An Edit pencil sits beside the heading.
9. **Solution tab:** two blocks, Workaround (with attachments) and Resolution, each with "Add". An Edit pencil sits beside the heading.
10. **Tasks tab**
    - List with "All Tasks" filter, Quick Add, Add Task, Organize, Assign Owner, a "…" menu, and list/detail layout toggle.
    - A task row shows status, priority, owner, scheduled end time and task order.
11. **Reminders tab:** New Reminder, Delete, "Modify Reminder State To" dropdown, columns Reminder Summary and Reminder Date, plus search and column chooser.
12. **Approvals tab:** shows "Outgoing mail server is not configured – click here to configure". No approval UI is available without mail.
13. **Worklogs tab:** "Add Working" button, columns Worklog, Time Spent, Charges (Technicians, Others, TOTAL). The trial has no data.
14. **Conversations tab:** Send Notification, Add Note, and filter checkboxes Emails, System Notifications, Notes.
15. **Associations tab:** four sections:
    - **Associated Incidents** has Attach and Detach. Columns: ID, Subject, Requester Name, Technician, Due by date, Status, Created Date.
    - **Associated Changes** has New Change, Attach and Detach. Columns: ID, Title, Change Owner, Change Manager, Category, Priority, Change Type, Change Risk, Reason for Change, Stage, Status, Workflow, Template, Entity ID.
    - **Releases Caused by Problem** has New Release, Attach and Detach. Columns: Release ID, Title, Type, Stage, Status, Priority, Release Engineer.
    - **Release that Initiated Problem** has Attach only. Same columns.
16. **Announcements tab:** "All Announcements" view with New Announcement and Delete. This links problems to announcements.
17. **History tab:** Date / Time / Operation / Description, with a filter box, sort icon, date picker and an "All" dropdown. Every change is recorded as a "from X to Y" line.

## Fields (table: field | type | required | options/values | notes)

**New Problem form (General Problem Template)**

| Field | Type | Required | Options/values | Notes |
|---|---|---|---|---|
| Reported By | user search + "add requester" icon | no | requesters | shows "N/A" on the detail page if empty |
| Site | dropdown | no | Base Site (default) | |
| Impact | dropdown | no | Affects Business, Affects Department, Affects Group, Affects User, High, Low, Medium (list may be longer; Low/Medium visible) | |
| Group | dropdown (loaded on demand) | no | support groups, such as App Development, Data Management, Development, Hardware Problems, Hosting… | list is long |
| Urgency | dropdown | no | High, Low, Medium, Normal, Urgent | |
| Technician | dropdown with search | no | technician names and emails, such as Bella Mark and Heather Graham; includes the trial admin | not filtered by Group in the Assign dialog |
| Priority | dropdown | no | Critical, High, Low, Medium, Normal | not auto-calculated from Impact and Urgency |
| Status | dropdown | **yes** | Pending group: In Progress, On Hold, Open (default), Pending Verification, Staging. Completed group: Canceled, Closed (the last two appear in the Edit form) | coloured status dots |
| Category | dropdown | no | Desktop Hardware, Firewall, General, Hardware, Internet, Network, Operating System… | |
| Sub Category | dropdown | no | depends on Category | |
| Item | dropdown | no | depends on Sub Category | |
| Due By Date | date/time | no | | |
| Closed Date | date/time | no | | filled when closed |
| Services Affected | multi-select | no | | |
| Assets Involved | multi-select + "+" | no | | |
| CIs Involved | multi-select + "+" | no | | |
| Title | text | **yes** | | |
| Description | rich text | no | bold, italic, underline, strike, more, expand | |
| Attachments | file drop zone | no | | |

Required fields are Title and Status only.

**Major Problem Template**
- Same top fields as the General template.
- It adds collapsible sections in the create form: Root Cause, Symptoms, and a Solution section containing Workaround and Resolution (rich-text Description fields).

**Add Task dialog (from the Actions menu)**

| Field | Type | Required | Options/values | Notes |
|---|---|---|---|---|
| Select Template | dropdown | no | "Default Task" | |
| Title | text | yes | prefilled "Default Task" | |
| Description | rich text with a full toolbar | no | | |
| Scheduled Start Time / End Time | date/time | no | | |
| Actual Start Time / End Time | date/time | no | | |
| Group | dropdown | no | | |
| Owner | multi-select | no | defaults to me, with a toggle | |
| Priority | dropdown | no | | |
| Status | dropdown | yes | Open (default) | |
| Additional Cost | currency | no | | |
| Task Type | dropdown | no | | |
| Notify Before Schedule Start | dropdown | no | Never (default) | |
| % Completed | number | no | | |
| Estimated Effort | days / hrs / mins | no | | |
| Attachments | file | no | | |

**Add Worklog dialog**

| Field | Type | Required | Options/values | Notes |
|---|---|---|---|---|
| Owner | dropdown | yes | defaults to me | |
| Worklog Type | dropdown | no | General Services | only option seen |
| Include non operational hours | checkbox | no | on by default | |
| Executed Time | date/time | no | | |
| End time | date/time | no | defaults to now | |
| Time Taken To Resolve | hrs / mins | yes | | |
| Currency | dropdown | no | US Dollar | |
| Exchange Rate | number | no | 1 (read-only) | |
| Technician's Cost per Hour | currency | no | read-only | |
| Tech Charges | currency | no | | |
| Other Charges | currency | no | | |
| Total Charges | currency | no | read-only | |
| Description | rich text | no | | |

**Add Reminder dialog**

| Field | Type | Required | Options/values | Notes |
|---|---|---|---|---|
| Summary | multi-line text | yes | | |
| Date | date/time | yes | | |
| Email me before | dropdown | no | Never (default) | |

**Add Notes dialog:** a single rich-text editor, Save and Cancel. I saw no public/private option for problem notes.

**Assign Technician dialog**

| Field | Type | Required | Options/values | Notes |
|---|---|---|---|---|
| Site | dropdown | no | Base Site | |
| Group | dropdown | no | | |
| Technician | dropdown with search | no | | |

**Mark as Known Error dialog**

| Field | Type | Required | Options/values | Notes |
|---|---|---|---|---|
| Known error? | Yes / No radio | no | default No | |
| Comments | text | no | | |

**Closure Details dialog (Close)**

| Field | Type | Required | Options/values | Notes |
|---|---|---|---|---|
| Closure Code | dropdown | no | Canceled, Failed, Postponed, Success, Unable to Reproduce | |
| Closure Comments | text | no | | |

## Actions and menus
- **Header buttons:** Edit, Assign, Close, Print.
- **Close:** first a Yes/No "are you sure" confirm, then the Closure Details dialog.
- **Actions menu**
  - Add Note
  - Add Task
  - Add Task from Template
  - Add Reminder
  - Add Worklog
  - Mark as Known Error (hidden once the problem is already a known error)
  - Copy Problem
  - Delete Problem
  - **Notify:** Make an announcement, Send Notification, Notify incident Technicians, Notify incident Requesters
- **Copy Problem**
  - A two-step dialog.
  - Step one has section-wise tickboxes: General (Problem Fields, Attachments, Tasks), Analysis (Impact Details, Root Cause, Symptoms) and Solution (Workaround, Resolution). There is a banner about inactive values and system dates.
  - Step two shows the pre-filled form with Back, Copy and Cancel.
- **Delete Problem:** a confirm, then the problem moves to trash (it is not removed).
- **Pick Up and Assign:** from the list toolbar (bulk) and the detail header (Assign).
- **Row gear menu in the list:** not opened.
- **Tasks toolbar:** Quick Add, Add Task, Organize, Assign Owner.
- **Reminders toolbar:** New Reminder, Delete, "Modify Reminder State To".

## Configuration options
- **Setup > Customization > Problem Management > Closure Code.** A list of 5 codes with a gear menu each, plus "New Closure Code":
  - Canceled: "Problem gets canceled"
  - Failed: "Problem closing failed"
  - Postponed: "Problem is put off till later"
  - Success: "Problem closed successfully"
  - Unable to Reproduce: "Issue is not produced at technician end"
- **Setup > Customization > Problem Management > Configurations** (not saved):
  - Problem ID Prefix (text, required, currently "PB")
  - Problem ID Starts With (number, required; it showed 6 after I created PB-5 and PB-6, so it acts as a sequence generator)
  - Checkbox: disable spot edit on the problem details page when a Form Rule is configured
  - Save
- **Setup > Templates & Forms > Problem Template:**
  - Two templates. Columns: Template Name (with a star for default), Problem Life Cycle, Workflow, Created By. Toolbar: New Problem Template, Copy Template.
  - **General Problem Template:** the default; "used to create problem"; no life cycle or workflow; created by System.
  - **Major Problem Template:** "used for major problem management"; life cycle "Major Problem Life Cycle"; no workflow; created by System.
  - Row gear: Edit, Copy, Disable, Delete (not used).
- **Template designer (opened both a new and the Major template, not saved).**
  - Header: back arrow and a Preview button (on existing templates).
  - Name (required, with a red "…" icon beside it), Comments, and a Workflow / Life cycle selector. The selector has two tabs, Workflow and Life cycle, and a search box. The Workflow tab said "No items found".
  - The main form is drag-and-drop with sections (the default is "Untitled section 1").
  - The right panel has an Available tab (unused fields such as Impact Start Time, Impact End Time, Problem Type and Reason for Outage on a new template) and a New tab for adding fields.
  - New-field types (19): Single-line, Multi-line, Pick List, Numeric, Date/Time, Date, Email, Multi-Select, Phone, Web URL, Lookup, Multi-Lookup, Check Box, Radio Button, Currency, Decimal, Percent, Auto Number, Decision Box. A "New section" tile can be dragged in.
  - Template tabs: Details, Analysis, Solution, Tasks, Form Rules, and "…" > Additional Settings.
  - On a brand-new unsaved template the Analysis, Solution, Tasks and Form Rules tabs are greyed out and clicking them does nothing; only Details works until the template exists.
  - **Tasks tab (Major template):** Add Task (split button), Organize, Delete, Task Dependency, Quick Add. No tasks yet.
  - **Form Rules tab:** "Filter by event: All Events", New Rule, an Actions menu. Columns: Rule Name, Associated Templates, Execution Details, Status. No rules exist.
  - **Additional Settings tab:** "Associate Groups to Template" with a Technician Groups multi-select, plus Save and Cancel.
  - Right side panel on an existing template: Template name (with star) and Comments.

## Automation / triggers / rules in this area
- **Life cycles.** Problem templates can attach a life cycle or a workflow. The Major Problem Life Cycle drives status transitions: PB-2 shows a Transitions button "Analyse Root Cause". I only looked at that screen; transitions were not clicked. The life-cycle editor itself belongs to Area 12.
- **Form rules.** Per template, on the Form Rules tab. None exist here.
- **Task templates.** "Add Task from Template" is in the Actions menu.
- **Problem-level notifications.** "Send Notification", "Make an announcement", and "Notify incident Technicians / Requesters" are manual actions. Email cannot be sent in this trial because no mail server is configured.
- **Automatic updates seen.** When a problem is closed, Closed Date and Closure Code are stamped automatically.
- **Nothing automatic happened on creation.** No auto-assignment, priority calculation, SLA, or due date (see tests).

## Behaviour observed in tests
All tests used my own records, PB-5 (and PB-6, its copy). No real problem was changed. "Me" below is the trial admin.
- **Create PB-5, "ZZ-CLAUDE-TEST problem 1"** from the General template with only Title filled:
  - Status Open; Life cycle, Workflow, Priority, Technician, Group, Impact and Urgency all "Not Assigned"; Known Error No; Tasks 0/0; Approval Status "Not Configured"; Due By Date "Not Configured".
  - The page showed "Reported By N/A".
  - The success toast was "Problem added".
  - History: "Problem Created", performed by me. No notification was shown.
- **Assign:** I picked myself in the Assign dialog. The detail page and the list updated, and History said "Technician updated from None to <the trial admin>". Status stayed Open (no auto status change).
- **Add Task:** created "ZZ-CLAUDE-TEST problem task 1" with the default values (status Open, owner me). The right panel changed to Tasks 0 / 1 and History logged "Task Added, Title: …".
- **Mark as Known Error (Yes):** Known Error became "Yes" with an icon. History logged "Known Error updated from false to true".
- **Close (with closure code "Success"):**
  - A Yes/No confirm appeared, then the Closure Details dialog.
  - Status turned Closed (green) and the Close button disappeared.
  - The open task was left open (no cascade).
  - History logged: Closed Date from None to the time, Status Open to Closed, Closure Code None to Success.
- **Reopen via Edit:** the Edit form shows the same fields as create (editable at any time, including Status and Closed Date). Choosing Open and saving reopened the problem. There is no separate Reopen button. History recorded "Status Closed to Open", "Closed Date to None" and "Closure Code Success to None".
- **Edit form:** a "Select Template" selector and all fields are editable (including Status "Closed" in the list). There is a Cancel via the back arrow.
- **Copy Problem (PB-6):**
  - The copy kept the title (identical, no "Copy of" prefix), the technician, Known Error "Yes", and tasks (0 / 1). It got the next ID, PB-6.
  - It took me straight to the new problem with the toast "Problem copied".
- **Delete (PB-6):** after confirming I got "Problem moved to trash". PB-6 left the list (5 problems remain) and appeared in Trashed Problems with a Restore button. I did not restore or permanently delete it.
- **Delete mistake, no effect:** I opened the Delete confirm on PB-5 by accident and cancelled; nothing was deleted.
- **View-only look at an existing problem (PB-2):** I opened it to see the life-cycle UI and made no change.
- **Not tested (outside what a test record can show):** Add Worklog (opened and cancelled), Add Note (opened and cancelled), Add Reminder (opened and cancelled), Make an announcement, Send Notification, Notify incident Technicians / Requesters, Add Task from Template, linking problems to incidents/changes/releases, the Approvals flow, and Print.
- **Delete without waiting on mail.** Approvals show "Outgoing mail server is not configured" rather than any approval UI.

## Edition notes
- Enterprise trial (30 days left on the trial banner).
- The Major Problem Life Cycle is a ready-made life cycle linked to the Major template. Custom workflows and life cycles belong to Area 12.
- Problem-to-Release and problem-to-Change associations appear in the Associations tab, so those modules are enabled.

## Weak spots / confusing UX
- Only Title and Status are required, so problems can be saved with no technician, priority or reporter. There is no priority matrix (Impact x Urgency), so Priority stays "Not Assigned".
- A problem can be closed while its tasks are still open.
- "Close" is a plain button that needs two dialogs (confirm, then Closure Details) and there is no Reopen button; users must know to edit the Status.
- The overflow "…" tab menu reshuffles every time you pick an item (the picked tab moves into the bar and another item drops in). Clicking the same position twice opens a different tab each time.
- Actions-menu items move when the menu changes (for example "Mark as Known Error" disappears once set), so click positions shift. I opened "Delete Problem" by mistake that way.
- Copy Problem reuses the title unchanged, which can make duplicate-looking rows.
- Dropdowns such as Group and Technician load on demand and may show "Searching…" first. The Technician list was not filtered by group.
- The unsaved new-template form greys out tabs without saying why. The "Additional Settings" tab can look selected while the Details form is still showing.
- The Workflow tab in the template designer's Workflow/Life cycle selector was empty ("No items found"), so problems on life cycles only work through the Life cycle tab.
- The page needs a deep click path to reach Problem settings: Setup > Customization > Problem Management for closure codes and ID, but Setup > Templates & Forms for templates.
- The note editor has no public/private distinction, unlike request notes.

## Test records created
- **PB-5** "ZZ-CLAUDE-TEST problem 1" (General template, Open, technician the trial admin, Known Error Yes, 1 task "ZZ-CLAUDE-TEST problem task 1"). It was closed and reopened during tests and is still open.
- **PB-6** "ZZ-CLAUDE-TEST problem 1" (copy of PB-5) is in Trashed Problems, not permanently deleted.
- Earlier test records from Areas 2 and 3 (#36 to #41) are untouched. Nothing was saved in Setup.

=== END OF AREA 4 ===
