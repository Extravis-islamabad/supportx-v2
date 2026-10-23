# Area 2a: Requests module, list views, filters, columns and bulk actions

This is part 2a of Area 2, covering only the Requests list screen. Part 2b (the New Request form and templates) and part 2c (the request detail page) are not done yet. In 2a I created no records and saved nothing. Each dialog was opened and then cancelled or discarded.

## Navigation path
- Left rail: Requests (`/app/itdesk/ui/requests`). It opens the "Open Requests" view in list mode.
- First visit shows a three-step onboarding tour (Comprehensive Filters, Custom View, New Incident). I clicked through it to dismiss it.

## Screens and what they do

**Requests list screen layout.** Top to bottom:
1. **View selector** (title with a dropdown) plus a filter-with-plus icon for building a custom view.
2. **Right side of that row:** a time filter, then three view-mode buttons (list, detailed list, board).
3. **Toolbar row:** column chooser icon, in-list search icon, action buttons, record counter with paging, export, row-colour settings and table settings.
4. **Table.** Each row has a checkbox, a pencil, an envelope and a note icon, then the data columns.

**View selector** is a searchable dropdown with these groups:
- **Favorites** (star any view to pin it; empty here).
- **My Groups** (per technician-group views): Data Management, Software, Major Incident Team, Development, Infra-SSO, App Development, Hosting Team, Onboarding, Maintenance, plus "All My Groups".
- **Public Views** (31): All My Requests, All Requests, Awaiting My Update, Canceled Requests, Completed Requests, My Completed Requests, My Open Or Unassigned, My Open Requests, My Overdue Requests, My Pending Requests, My Pending Requests or Tasks, My Requests Due Today, My Requests On Hold, Open Requests, Overdue Requests, Pending Requests, Requests Approved by Me, Requests Created Today, Requests Due Today, Requests Followed by Me, Requests From Maintenance, Requests On Hold, Requests Pending Approval, Requests Raised by Direct Reportees, Requests Rejected by Me, Unassigned Requests, Updated By Me.
- **Shared Request:** Pending Requests Shared with me, Requests Shared with Me.
- **Request Type switch:** Incidents, Service, or Both (selected by default).
- Links to **Trashed Requests** and **Archived Requests**.

**Time filter** (button showing "Last 30 days"; a tooltip says it filters by last-updated date): Last 30 days, Last 24 hours, This week, Last week, Last 90 days, This month, This quarter, This year, Last quarter, Last year, All.

**List mode** is a dense table. Default columns: ID, Subject (with a request-type icon, orange for incident and teal for service), Requester Name (a shield icon marks VIP requesters), Technician (green dot for online, grey for offline), Group, Status, Due by date, Created Date. Unread/new requests are shown in bold. A sample count: 20 open requests, shown 10 per page.

**Detailed list mode** is a card-like row. It shows a flag-coloured status, "#ID Subject", "By requester On date", Approval Status, technician with group underneath, and a red-bordered due-date badge (month and day).

**Board (Kanban) mode.** Columns grouped by Status, with a card count and a bell icon per column. The empty-state text says "Drag and drop here", which means moving a card to another column changes its status; I did not drag any card. Controls above it:
- **Group By:** Status, Priority or Technician.
- **Display density:** Compact or Comfort.
- **Manage Status** panel with search, a "Pinned status" drop zone, and a drag-reorderable status list with counts and a bell. Statuses shown: Canceled, Closed, In Progress, On Hold, Open (19 in my view).
- **Sort by column** picker with an ascending/descending arrow.
- The time filter and the three view-mode buttons are repeated.

There is no calendar view on the list. Calendar-style views exist on Home (Scheduler) and elsewhere, as noted in Area 1.

**Column Chooser** (first toolbar icon) is a popover with search, a counter (8 of 70 selected), checkboxes and drag handles for ordering. Save and Cancel at the bottom. The 70 selectable columns:
- ID, Subject, Requester Name, Technician, Group, Status, Due by date, Created Date (default on).
- Address, Analysis, Approval Status, Category, Completed Time, Completed by Denial, Created By, Current Version, Department, Destination, Division, Editor, Editor Status, Email id, Employee ID, Employee Name, Employee Type, Environment Impacted, Impact, Impact End Time, Impact Start Time, Issue, Item, Last Updated By, Last Updated Time, Level, Linked Requests, Maintenance, Mode, On Behalf Of User, Post Incident Action, Priority, Project ID, Recently Upgraded, Request Type, Resolved Time, Resolvers Involved, Responded Time, Response Due Date, Role, Root Cause, SLA, Scheduled End Time, Scheduled Start Time, Service Category, Service Cost, Site, Solution, Sub Category, Tasks, Template, Total Cost, Type, Urgency, Workaround, Workflow, Worklog Timer, Zoho Meet.
- A few of these (Address, Destination, Employee ID, Issue, Zoho Meet and similar) look like fields from request templates rather than core fields.

**In-list search** (second toolbar icon) shows an inline row of text boxes under the column headers, one per visible column, for filtering as you type.

**Table Settings** (last toolbar icon): Records Per Page (10, 25, 50, 75, 100), Sort By Column with a direction arrow, Refresh Frequency (default Never), and Display Density (Compact or Comfort).

**Row colour settings** (green list icon): toggles "Enable row color settings" and "Enable color settings for template view", colours rows based on Status (default), with a default colour and "Applies to: All Columns", plus an "Edit row color settings" link.

**Export** (download icon) opens "Data Export (CSV)", with a note that it may take time and the user is notified by email and push when it finishes. Choices: All data (up to 10,000 records), All data from the current view (default), Selected data from the current view. Export and Cancel buttons. I cancelled it.

**Row icons** (from the page's accessibility labels): Edit (pencil), Conversations (envelope, labelled "No new conversations" when none), View Notes (note icon).

## Fields (table: field | type | required | options/values | notes)
These are the controls in the list-screen dialogs I opened.

**Custom View builder** (filter-with-plus icon):

| field | type | required | options/values | notes |
|---|---|---|---|---|
| Custom view name | text | needed to save | free text | Star icon marks it a favourite |
| Column | dropdown with search | yes per row | about 57 columns (list below) | Some entries have sub-menus (Approval Status, Assets, Category) |
| Operator | dropdown | yes per row | depends on column type (below) | |
| Value | depends on column | yes per row | | |
| Row controls | drag handle, "−", "+" | | | Rows can be added, removed and reordered |
| Make this view a private custom view | checkbox | no | on/off | Otherwise it is shared |
| Buttons | Apply, Save, Cancel | | | Apply runs it without saving; the tour describes this as trying a view "without saving" |

Filterable columns: Approval Status, Assets, Assigned Time, Cancellation Requested, Category, Closing Comments, Comments, Completed by Denial, Completed Time, Created By, Created Date, Department, Due by date, First Response Overdue Status, Group, ID, Impact, Impact Details, Item, Last Updated By, Last Updated Time, Level, Linked Request ID, Linked Request Title, Maintenance, Mode, Notification Status, On Behalf Of User, Overdue Status, Pending Status, Priority, Project ID, Region, Request Type, Requester, Resolved By, Resolved Time, Responded Time, Response Due Date, Scheduled End Time, Scheduled Start Time, Service Category, Service Cost, Site, SLA, Status, Sub Category, Subject, Tags, Technician, Template, Time Elapsed, Total Cost, UnReplied Count, Urgency, Workflow, Additional Fields.

Operators by column type (those I saw):
- **List/choice fields** (e.g. Priority): is, is not, is empty, is not empty.
- **Text fields** (e.g. Subject): is, is not, is empty, is not empty, contains, does not contain, begins with, ends with.
- **Date fields** (e.g. Created Date): is, is not, is empty, is not empty, greater than, lesser than, greater or equal, lesser or equal, between (the list continued below the fold; there may be relative-date options I did not see).

**Bulk Edit dialog** (select rows, then Edit). The header shows "Editing Requests" with the selected IDs. Every field defaults to "Leave it as it is".

| field | type | required | options/values | notes |
|---|---|---|---|---|
| Request Type | dropdown | no | not expanded | |
| Status | dropdown | no | not expanded | |
| Impact | dropdown | no | not expanded | |
| Impact Details | text | no | free | |
| Urgency | dropdown | no | not expanded | |
| Mode | dropdown | no | not expanded | |
| Priority | dropdown | no | not expanded | |
| Level | dropdown | no | not expanded | |
| Category | dropdown | no | not expanded | Under "Category Details" |
| Sub Category | dropdown | no | not expanded | |
| Item | dropdown | no | not expanded | |
| Site | dropdown | no | not expanded | Under "Owner details" |
| Group | dropdown | no | not expanded | |
| Technician | dropdown | no | not expanded | |
| Additional Fields | table (Field Name / Value) | no | "Configure the additional fields to be updated" | Below the fold; I did not scroll it |

**Close Request dialog** (select rows, then Close):

| field | type | required | options/values | notes |
|---|---|---|---|---|
| Is FCR | checkbox | no | on/off | First-call resolution flag |
| Requester Acknowledged Resolution | radio | no | Yes / No (default No) | |
| Closing Comments | text area | no | free | |
| Closure Code | dropdown | not marked | "-- Select Closure Code --" | |
| Closure Comments / Status Change Comments | text area | no | free | |

**Link Request dialog:** text "The oldest request will be retained as the parent request. Other selected request(s) will be in new relationship." One comments box, Confirm and Discard.

**Merge Request dialog:** a warning that child requests are merged under the parent and that their worklogs, notes, conversations, reminders, tasks and checklists move to the parent. A "Select Parent Request" dropdown (listing the selected requests by ID and subject), Merge and Cancel.

## Actions and menus (every button and menu item, what it does)
- **New Incident:** creates an incident from the default template (opens the New Incident form; I opened it once by accident and left without saving; it belongs to 2b).
- **New Incident dropdown arrow:** a template browser. A "Home" breadcrumb, a search box, then nested template groups (General Incident Templates, Corporate Website, Email, Employee Onboarding, Feature Request, Internet Access, Intranet, and more below), each with a chevron to drill down.
- **Edit:** opens Bulk Edit for the selected rows. With nothing selected it shows an alert "Please select request(s) to edit".
- **Pick Up:** assigns the selected requests to the logged-in technician (not pressed).
- **Close:** opens the Close Request dialog above.
- **Merge:** opens the Merge dialog; needs two or more rows.
- **Link Requests:** needs more than one row (alert: "Please select more than one request to link"), then opens the Link Request dialog.
- **Assign (dropdown):** a search box, a "Show only online technicians" toggle, then a list of technicians with an online/offline dot. The technicians shown: Bella Mark, Heather Graham, Howard Stern, Jeniffer Doe, John Roberts, Shawn Adams, and the trial admin. Apart from the trial admin these are the trial's demo users. I did not pick one.
- **Delete:** not pressed. There is a "Trashed Requests" view, which suggests delete is a soft delete.
- **Select-all checkbox:** selects all rows on the page (10 here); it cycles between none, partial and all.
- **Paging arrows:** previous and next page.
- **Row icons:** edit, conversations, notes.

## Configuration options (every setting and its possible values)
- Records per page: 10, 25, 50, 75, 100.
- List sort: any column, ascending or descending.
- Refresh frequency: Never (other values not opened).
- Display density: Compact or Comfort (also for the board).
- View modes: list, detailed list, board.
- Board grouping: Status, Priority, Technician.
- Time filter: 11 presets.
- Request type filter: Incidents, Service, Both.
- Row colour settings: on/off, colour by Status (other fields not tested).
- Export scope: all data (max 10,000), current view, or selected rows; output is CSV.

## Automation / triggers / rules in this area
- No rules are configurable on the list screen.
- Row colouring by status, auto-refresh frequency and the board's drag-to-change-status behaviour are the only automation-like pieces.
- Bell icons on board columns suggest per-status notification subscriptions; I did not click them.

## Behaviour observed in tests (what happened when you created ZZ-CLAUDE-TEST records)
No test records were created. Observed behaviour:
- Action buttons are always visible, but most act only on selected rows. Edit, Link and Merge show an alert if too few rows are selected.
- Link and Merge both pick the parent automatically or by dropdown; Link picks the oldest by default.
- Opening the filter builder with Escape cancels it without saving.
- The view mode (list, detailed, board) is remembered per user between page loads.
- The Open Requests list header showed "Subject" as the active sort column after my interactions, although the first load showed ID. I did not knowingly change the sort. It may be that the table settings panel opens with a different default, so I'd treat this as unconfirmed.
- I accidentally pressed New Incident while the filter popover was closed, which opened the form; nothing was saved.

## Edition notes
- Nothing on the list screen was marked Enterprise-only or locked.
- Sharing views ("Shared Request" group) and "Requests Raised by Direct Reportees" suggest user-hierarchy features, but I did not confirm their edition requirements.

## Weak spots / confusing UX (where a competitor could do better)
- **Operator lists depend on column type**, and the column dropdown mixes real fields with sub-menus (Category, Assets), which is slow to scan; there is no grouping by field kind.
- **Delete sits next to everyday actions** (Pick Up, Close) in the same row of buttons; a mistaken click on a selected set is easy.
- **Action buttons do nothing without a selection** and show a blocking alert instead of being disabled or greyed out.
- **Selection model** is only per page (select-all affects 10 rows), and the indeterminate state is easy to mis-click.
- **Mixed placement of controls.** View selector, time filter and view modes are on one row, while sort, density and refresh are hidden in a settings popover, and the board has its own separate sort and density controls.
- **The "…" counter** (total unknown until it loads) briefly shows ellipses.
- **Product tour overlays** appear on first visit and block interaction.
- **Operators for dates** were long, and the visible list was cut off; discoverability of relative-date options is unclear.
- **Not verified:** Pick Up, Delete and Assign results; what the bell icons do; the full option lists for Bulk Edit fields; the "Additional Fields" section of Bulk Edit; saved-view creation (private versus shared); how the board looks with data (I saw it with 19 open cards in the Manage Status counts but the visible columns were empty); whether column drag-reorder persists; and the Trashed and Archived views.

## Test records created (names and IDs, so they can be cleaned up later)
None. No ZZ-CLAUDE-TEST records were created, and nothing was edited, assigned, closed, merged, linked, exported or deleted.

=== END OF AREA 2a ===
