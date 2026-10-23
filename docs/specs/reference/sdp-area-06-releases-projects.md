# Area 6: Releases and Projects

## Navigation path

- **Releases:** left nav > Releases (appears after first use; also under More). The list URL works: `/app/itdesk/ui/releases`. This is unlike Changes.
- **Projects:** left nav > Projects. List URL `/app/itdesk/ui/projects`. New project form `/app/itdesk/ui/projects/add`.
- **Settings:** Setup > Customization > Release Management (tabs Closure Code, Stage and Status, Release Role). Setup > Customization > Project Management (tabs Project Types, Project Status, Project Roles). Templates: Setup > Templates & Forms > Release Template and Project Template (not opened here).

## Screens and what they do

### Releases

1. **Release list.** Three layouts (compact list, detail list, calendar). Detail layout shows per row: ID, title, priority, type, scheduled end, category, status/stage, release engineer, task ring (e.g. 0/15), icons for details, workflow and warning. Toolbar: column chooser, search, New Release (split with template menu), Delete, Pickup, Close, Assign, export, and view-settings icons.
2. **Views (11 public + Trashed):** All Releases, All Open Releases, All My Releases, Canceled, Closed, Deployed, Failed, Scheduled, Unscheduled, Unassigned Releases. A funnel icon builds custom views.
3. **Sample data:** RL-1 "Migrating to SD-WAN", RL-2 "Migration of ERP VM…" (emergency icon), RL-3 "AIX Prod Server Patching", RL-4 "Asset Lease Tracking Tool (V1) Initial Release", RL-5 "…(V2)". All were Requested / Submission. RL-4/RL-5 are Major with scheduled ends and RL-5 has 15 tasks.
4. **New Release menu:** two templates, General Template and Emergency Template. The form (General): Select Workflow (General Release Workflow), Select Template.
5. **Release detail.** Same layout as Change: header buttons Edit, Assign, Print, **Scheduler**, **Workflow**, Actions, prev/next. Left stage rail with **nine** stages, left menu (Roles, Associations, Conversations, Tasks, Reminders, Worklogs, and more), right panel with Release ID, Status, Workflow, Template, Release Engineer, Release Manager, Scheduled End, plus association counts.
6. **Release Scheduler.** A month/week calendar dialog with "Configure Release Schedule" (Scheduled Start/End, Save/Cancel) and a toggle "Show Release Schedules of Associated Changes", which overlays the linked changes' schedules on the release calendar. This is the only conflict view for releases.
7. **Release workflow execution view.** Same read-only diagram viewer as Changes (Highlight Executed Path, zoom, "⋮" menu).

### Projects

1. **Project list.** Layouts: list and detail. Per row: ID (PJT-n), title, status, priority, owner, created by, milestone ring (e.g. 100% 5/5), task ring (7/7), project code, schedule end. Toolbar: New Project, Delete, Import Project(s), column chooser, search. Top buttons: **Gantt View**, **Resource Management**. A side tab "Project Feeds".
2. **Views:** All, Canceled, Closed, Completed, Onhold, Open, Pending, Trashed Projects.
3. **Sample data:** PJT-1 "Revert previous action" (Closed), PJT-2 "Migrating to SD-WAN" (Open, 1/6 milestones, 1/14 tasks), PJT-3 "Migration of ERP VM…" (Closed, 100%), PJT-4 "Migrating to Apache Flink" (Open, High), PJT-5 "Asset Leasing Tracking Tool" (In Progress).
4. **Global Gantt (Project Gantt Chart).** Full-screen. Filters: Select Projects, Select Milestones, All Tasks. Options: Scheduled Time, Default Date Range, zoom (Days etc.). Left columns Title, Start Date, Duration. Unscheduled items show "Not Scheduled" with only a progress pill.
5. **Resource Management.** A person-by-time timeline (hours view for a day, with arrows and a date picker) showing each member with a "Load – 0/9 h" figure (9 hours capacity per day). Filters: Project Member Filter, toggles "Unassigned" and "Unscheduled", zoom (Hours), "Bar Color – Priority", Legend. Task bars appear on the person's row (e.g. a red "Create Smart Account" bar).
6. **Project detail.** Header: Edit, Close, four view icons (Gantt View, Kanban View, a resource-style icon, a fourth icon I did not open), Actions, prev/next. Tabs: Summary, Details, Milestones, Tasks, Associations, and an overflow with Time Sheet, Members, Comments, Settings, History. Right panel: Project ID, Status, Priority, Owner, Attachments, Due Date, Progress, % Completed, Milestones and Tasks counters, "My Tasks" (Total/Pending/Completed) and an association counter block.
7. **Project Gantt (per project).** Tree of project > milestone > task with Start Date and Duration, Select Milestones, All Tasks, Export as PDF.
8. **Kanban view of tasks.** Columns by Group By (Owner, Status, Priority, default Priority), including an "Unassigned" column; cards show title, owner, status, schedule state, and icons for timer, dependencies, comments and % complete; compact/comfort density options; drag and drop between columns.

## Fields (table: field | type | required | options/values | notes)

### New Release (General Template)

| Field | Type | Required | Options / values | Notes |
|---|---|---|---|---|
| Release Requester | user search | no | users | |
| Site | dropdown | no | Base Site | |
| Type | dropdown | no | Major, Minor, Normal, Significant, Standard | Same list as change types. |
| Group | dropdown | no | technician groups | |
| Impact | dropdown | no | Affects Business, Affects Department, Affects Group, Affects User, High, Low (and Medium) | Same mixed scales as Change. |
| Release Engineer | user | no | technicians | |
| Urgency | dropdown | no | same as Change | |
| Release Manager | user | no | technicians | |
| Stage / Status | read-only | yes | Submission / Requested | |
| Priority | dropdown | no | Critical, High, Low, Medium, Normal | |
| Risk | dropdown | no | High, Low, Medium | Manual. |
| Status Comment | read-only note | yes | | Auto text. |
| Category, Sub Category, Item | cascading | no | | |
| Scheduled Start / End | date-time | no | | |
| Services Affected | multi-select | no | | |
| Assets Involved | multi-select + "+" | no | | |
| CIs Involved | multi-select + "+" | no | | Release adds CIs; Change does not show it by default. |
| Reason for Change | dropdown | no | same 8 values as Change | Label is "Reason for Change" even on releases. |
| Title | text | **yes** | | |
| Description | rich text | no | | |
| Attachments | file | no | | |
| Development Head, UAT Owner, QA Manager, Release Reviewer | user selectors | no | | Role section. |

### Stage detail (RL-6)

| Stage | Tabs | Content |
|---|---|---|
| Submission | Details, Tasks, Notes, Approvals, Status Comments | Request fields |
| Planning | Details, **Downtime**, Tasks, Notes, Approvals, Status Comments | Collapsible sections with "+" add: Impact Details, Rollout Plan, Backout Plan, Checklist; attachments |
| Development, Testing, UAT, Deployment, Training | Details, Tasks, Notes, Approvals, Status Comments | A **Schedule** block (Scheduled Start/End and Actual Start/End per stage) and a Details block (Description, attachments) |
| Review | same | "Next Review On" + the same schedule block + Details |
| Closure | same | Closure Code + Description + attachments |

Each stage has its own schedule, so releases track planned and actual dates **per stage**, unlike changes (which only have release and UAT schedules).

### New Project (Default Project Template)

| Field | Type | Required | Options | Notes |
|---|---|---|---|---|
| Title | text | **yes** | | |
| Priority | dropdown | no | | |
| Status | dropdown | **yes** | default Open | |
| Project Code | text | no | | |
| Project Type | dropdown | no | Business, Infrastructure, Maintenance, Research, Upgrade | Each has a colour. |
| Project Requester | user | no | | |
| Owner | user | no | | Has a "?" hint. |
| Department | dropdown | no | | |
| Site | dropdown | no | Base Site | |
| Estimated Hours / Actual Hours | number | no | | |
| Estimated Cost / Actual Cost | currency | no | | |
| % Completed | number | no | | Editable by hand but also computed. |
| Schedule Start / End, Actual Start / End, Projected End | date-time | no | | |
| Description | rich text | no | | |
| Attachments | file | no | | |

### Add Milestone

Title (required), Description (rich text), Schedule Start/End, Actual Start/End, Owner (with add icon), Priority, Status (default Open), Estimated Hours, Projected End, Actual Hours, Attachments. There is also a "Quick Add" shortcut.

### Add Task (project)

| Field | Notes |
|---|---|
| Select Template | "Default Task" |
| Title | required |
| Description | rich text |
| Scheduled Start/End Time, Actual Start/End Time | |
| Owner | with an on/off toggle next to it and a "?" |
| Priority | |
| Additional Cost | $ |
| Notify Before Schedule Start | Never, 15 mins, 30 mins, 45 mins, 1 hr, 2 hr, 6 hr, 12 hr, 1 day, 2 days, 1 week |
| Estimated Effort | days / hrs / mins |
| Status | default Open |
| Task Type | dropdown |
| % Completed | |
| Attachments | |

## Actions and menus

- **Release Actions menu:** Add Note, Add Reminder, Add Task, Add Task from Template, Add Worklog, Copy Release, Delete Release; Notify: Make an announcement, Send Notification. There is no "Refresh conflicts" item as in Changes. Release has Notes rather than Changes' Resolution items.
- **Release list:** Delete, Pickup, Close, Assign (dropdown).
- **Project Actions menu:** Add Milestone, Add Task, Add Task from Template, Add Comment, Copy Project, **Copy as Project Template**, Delete Project.
- **Project list:** New Project, Delete, Import Project(s), Gantt View, Resource Management.
- **Milestones tab:** Add Milestone, Assign Owner (dropdown), Quick Add, list/detail toggle.
- **Tasks tab:** Add Task (split with templates), Assign Owner, **Assign Milestone**, Quick Add, view toggles.
- **Members tab:** Add Member, Delete, Assign Project Role, Assign User Status. Columns: Name, Role, Email, User Status. The project creator is added automatically as **Project Admin**.
- **Time Sheet tab:** Members, Time Spent, Charges (Technicians, Others, Total), Export as PDF.
- **Release Associations page:** Attach/Detach per link type. The Change Attach dialog offers **"Associate"** or **"Associate & Attach Downtimes"** (copies the change's downtime windows into the release).

## Configuration options

**Setup > Release Management**
- **Closure Code** (4): Closed - Canceled, Closed - Completed, Closed - Deferred, Closed - Rejected (each with a description).
- **Stage and Status** (9 stages, each with description): Submission, Planning, Development, Testing, UAT, Deployment, Training, Review, Closure. Buttons: "New Release Stage", **"Organize Release Stages"** (reordering). Not opened further.
- **Release Role** (7): Development Head, QA Manager, Release Engineer, Release Manager, Release Requester, Release Reviewer, UAT Owner.
- Release type, impact and priority reuse the change lists; there are no separate release type or risk tabs.

**Setup > Project Management**
- **Project Types** (5): Business (red), Infrastructure (yellow), Maintenance (green), Research (blue), Upgrade (no colour). Buttons: New Project Type, Organize.
- **Project Status** (5): Canceled (grey), Closed (green), In Progress (no colour), Onhold (yellow), Open (blue). Organize button.
- **Project Roles** (4): Project Admin (full control), Project Manager, Team Leader (control over one or more milestones), Team Member (works on assigned tasks). New Project Role button.
- **Project settings tab (per project)** (switches, all off on the new test project):
  - Schedule: "Enable strict project management" (milestones/tasks cannot fall outside the project's schedule), "Auto-schedule child entities" (shifting a project or milestone start shifts its children; has a limitations warning), "Aggregate estimated effort" (estimated hours roll up from children).
  - Closure: "Restrict operations on a completed entity" (only status changes allowed), "Auto-close child entities" (closing a project or milestone closes its children), "Prevent closure with open child entities", "Calculate actual time from child entities" (and more below that I did not read).
- **Templates:** New Project offers two project templates, "Default Project Template" and "General Migration Management". New Release offers General and Emergency templates.

## Automation / triggers / rules in this area

- **Release workflow** (General Release Workflow, read-only diagram). Stage statuses, in order:
  - Submission: Requested, Accepted, Rejected
  - Planning: Approved, Rejected, In Progress
  - Development: Completed, Back Out, In progress
  - Testing: Completed, Failed, In progress
  - UAT: Accepted, Rejected, In progress
  - Deployment: Deployed, Failed, In progress
  - Training: Completed, In progress
  - Review: Completed, Rejected, In progress
  - Closure: Completed, Failed, In Progress, then End
- The diagram is linear and laid out in rows. It has no task, approval or notification nodes. All approvals are driven from each stage's Approvals tab.
- **Freeze and maintenance windows** can apply to a release schedule (Area 5b).
- **Project automation:** the project settings switches above (strict schedule, auto-schedule, aggregate effort, auto-close, restrict completed items, prevent closure) are the only built-in project rules. Task templates add tasks to projects.
- **Task notification:** a task can notify its owner before its scheduled start, with the options listed above.

## Behaviour observed in tests

**Release RL-6 "ZZ-CLAUDE-TEST release 1"** (General Template, General Release Workflow)
- Created with only a title. Result: Requested / Submission, Release Engineer and Manager "Not Assigned", Scheduled End "Not Configured". No auto-assignment.
- Workflow button showed a yellow dot (waiting), not red.
- Release Scheduler: opened and cancelled the Configure dialog (did not save dates).
- Associations: attached CH-8 under "Associated Changes" with plain **Associate**. The change row shows ID, title, type, stage, and a gear. The release page also lists, as separate sections: Requests caused by Release, Requests that Initiated Release, Problems Caused by Release, Problems that Initiated Release, Associated Changes, Projects that Initiated Release, **Milestones that Initiated Release**, and more below. No status changed.
- The request page for a request shows "Releases Caused by Request" (New | Search) and "Release that Initiated Request". The problem page shows "Releases Caused by Problem" and "Release that Initiated Problem". So releases connect to requests, problems, changes, projects and milestones.

**Project PJT-6 "ZZ-CLAUDE-TEST project 1"** (Default Project Template)
- **Bug found:** opening New Project from the list, then picking a template from the dropdown, left the form blank with a script error ("Cannot read properties of null") for both templates. Opening the form by URL (`/projects/add`) rendered correctly with the default template. After that the form worked.
- Created with title only. Result: Open, Owner and Priority "Not Assigned", % Completed 0%, 0 milestones, 0 tasks. The creator became Project Admin.
- Added **milestone** "ZZ-CLAUDE-TEST milestone 1" (Open, "Milestone Order: 1") and **task** "ZZ-CLAUDE-TEST project task 1" (Open, Owner "Not Assigned", no schedule). The counters updated to Milestones 0/1 and Tasks 0/1.
- The task was not assigned to the milestone (the list shows milestone "-"), but the Gantt tree drew it under the milestone with 0 duration. Both show "Not Scheduled" because they have no dates.
- Kanban shows the task in the "Unassigned" column under Priority grouping.
- Associations: attached CH-8 under "Changes caused by Project". The project counter "Changes caused by Project" became 1, and no status changed. Other project association sections: Associated Requests, Change that initiated the Project, Releases initiated by Project, Releases initiated by Milestone. On a Release, the reverse sections are "Projects that Initiated Release" and "Milestones that Initiated Release".
- **Time Sheet** showed 0 hrs and 0.00 charges. **Resource Management** showed each member's daily load against 9 hours. Time tracking and costs come from task worklogs, which I did not add.
- I did not test Copy as Project Template, strict mode, auto-schedule or closing the project.

## Edition notes

- The Quick Setup welcome page states "You are on Enterprise Edition" with a "Switch" button for changing edition (not clicked).
- Gantt, Kanban, Resource Management, project templates and release workflows were all available on this trial. I cannot say which are limited in lower editions.

## Weak spots / confusing UX

1. **New Project form bug:** choosing a template from the dropdown on New Project renders a blank form (JS error), but the direct URL works.
2. Releases reuse change lists. The field "Reason for Change" appears on releases, and release Impact has the same mixed scales (High/Low next to "Affects User").
3. Release workflow is a plain linear chain, much less capable than the Standard change workflow, which has decision, notification, task and approval nodes. The two modules differ in power for no visible reason.
4. A release's "Approvals" tab appears in almost every stage, but with no mail server none of them can complete.
5. Release stages each have their own schedule, but the Scheduler dialog only edits one overall release schedule. Per-stage dates are edited in the Details tab.
6. Link names are inconsistent: the same link is "Requests that Initiated Change" on the change and "Changes Caused by Request" on the request, and the request side leaves no history entry.
7. Project task creation does not require a milestone, and the Gantt tree can show a task under a milestone that the task list says it is not assigned to.
8. Gantt shows "Not Scheduled" for everything created without dates, so a new project's Gantt is empty. Dates are only entered on the item forms; there is no drag-to-schedule discovered.
9. The project settings switches are only per project, with long single-sentence labels, and several carry "read the limitations" warnings.
10. The tab strips use "…" overflow on both project and release pages, and what is in the overflow depends on the selected tab (Members, Time Sheet, Settings, History move around).
11. Pressing Escape and clicking near the top right while in the Kanban overlay closed the whole project page and opened the Quick Setup welcome page, because the overlay's close button sits under the Quick Setup banner. Easy to mis-click.

## Test records created

- **Release:** RL-6 "ZZ-CLAUDE-TEST release 1", with CH-8 attached.
- **Project:** PJT-6 "ZZ-CLAUDE-TEST project 1", with milestone "ZZ-CLAUDE-TEST milestone 1", task "ZZ-CLAUDE-TEST project task 1", and CH-8 attached under Changes caused by Project.
- **Changes (5b):** CH-9 (emergency, child of CH-8), CH-10 (standard).
- No existing sample records or Setup items were modified. Dialogs opened for Configure Release Schedule, the freeze/maintenance forms, and the Edit Change Type were cancelled.

## Not covered (so you can decide)

- Release Emergency Template flow, and the release/project template editors in Setup > Templates & Forms.
- Project closure, strict/auto-schedule behaviours, task dependencies, task worklogs and the project Summary tab.
- Release approvals (blocked by mail).
- Project import (not run).

# Area 6b (add to end of Area 6 report): PJT-6 follow-up tests

## Navigation path
Projects > PJT-6 > tabs Summary / Details / Milestones / Tasks / Associations, overflow "…" = Time Sheet, Members, Comments, Settings, History. View icons top-right of the project header: 1 Gantt, 2 Kanban, 3 Resource Management, 4 Task Dependency diagram. Task page: Details / Task Dependency / Worklogs / Comments / History; task Actions menu = Add Worklog, Add Comment.

## Behaviour observed in tests
**1. Dates, milestone assignment, Gantt, Kanban**
- Milestone edit form dates use a calendar-only picker (day precision). I set Schedule Start Oct 26 and Schedule End Oct 30; Milestones list then shows Schedule End. The inputs are read-only text boxes, so dates can only be chosen from the picker.
- Task dates use a date-and-time picker (hour, minute drop-downs + Apply). Task 1: Oct 27 to Oct 29 (default time was "now"). Task form also has Estimated Effort (days/hrs/mins), Additional Cost ($), Task Type, Notify Before Schedule Start, % Completed, Owner (only one owner offered: me).
- Assign Milestone is done by ticking the task in the Tasks list and using the "Assign Milestone" bulk drop-down (options: No Milestone + each milestone). It first asks "preserve the task dependencies of the selected tasks?" with Cancel / No / Yes. After choosing Yes the toast says "Milestone(s) assigned".
- Gantt updated at once: green project bar auto-spans the earliest to latest child date (even though the project's own Schedule Start/End fields stay "Not Configured"), orange milestone bar, blue task bars, an orange arrow between dependent tasks. Items with no dates show "Not Scheduled". Task 2 was shown directly under the project instead of under the milestone because it had no milestone.
- Gantt toolbar: Select Milestones filter, All Tasks filter, Export as PDF, Time Settings (Gantt based on Scheduled / Actual / Both; date range; zoom slider years to hours; "Exclude holidays and weekends" checkbox). Row gear menu on a task: Edit Task, Delete Task. Hover card on a bar shows task ID, status, priority, scheduled and actual dates, owner, More Info, edit, delete.
- Dragging a bar works: it saves immediately ("Task Scheduled Time updated successfully"), snaps to whole days, and resets the time to 12:00 AM to 11:59 PM. Dragging task 2 left shrank its length from about 25 h to one day.

**2. Second task and dependency**
- Task 2 created from Add Task (the title is pre-filled with the template name "Default Task", must be overwritten).
- Dependencies are NOT created from the task Actions menu or the Task Dependency tab on the task (that tab is read-only: "No dependency available"). They are created in the fourth view icon (Task Dependency diagram): hover a task node, a blue link icon appears on its right edge, drag it onto the other task. Toast "New Dependency added"; a "Last Activities" drop-down logs it. Diagram has Horizontal/Vertical layout, Reload, Save as PDF. Direction: the task you drag from is the predecessor. Only finish-to-start style links were seen; no lag or link-type choice.
- Violation test: I dragged the successor (task 2) to Oct 28, before predecessor task 1 ends (Oct 29), then moved task 1 later to Oct 30. Both saves succeeded with no warning, no blocking, no red arrow and no auto-shift of the successor; the Gantt arrow simply loops backwards. So dependencies are visual only here (auto-scheduling is a separate project setting that is off by default).

**3. Worklog, Time Sheet, Resource load, roll-up**
- Add Worklog form: Owner, Worklog Type (only "General Services"), Include non-operational hours, Executed Time start and end, Time Taken to Resolve (hrs/mins), Currency and Exchange Rate, Technician cost per hour (read-only, 0.00), Tech Charges, Other Charges, Total Charges (auto-sum), Description. Quirk: changing the end picker's month moved the end by days and the time-taken box jumped to 231 h; time taken and end time stay in sync, so set the end time first, then check the hours.
- Saved: 1 h, $20 tech + $5 other = $25 total on task 1. Toast "Worklog added"; the task Worklogs tab shows a row and TOTAL row.
- Time Sheet (project overflow tab): one row per member with Time Spent 1 h 00 min, Technicians 20.00, Others 5.00, Total 25.00, expandable per member, Export as PDF.
- Resource Management: per-member daily capacity 9 h. On Oct 23 load 0/9 h. On Oct 29, when task 1 (assigned to me) is scheduled, load shows 9/9 h and a full-day bar. The load is based on scheduled time spread over the day, not on Estimated Effort (4 h) or on the worklog. Task 2 has no owner, so it only appears under the "Unassigned" toggle. Other toggle: "Unscheduled". Options: Project Member Filter, date navigation, Hours/Days zoom, Bar Color (Priority), Legend.
- Roll-up: with default settings, project Estimated Hours, Actual Hours, Estimated Cost, Actual Cost all stayed "-" even after the worklog and the 4 h estimate and $10 additional cost. Roll-up needs the Settings switches "Aggregate estimated effort", "Calculate actual time from child entities" and "Calculate actual cost on closure" (both closure ones only calculate at closure). I did not turn those three on.

**4. Closure tests (PJT-6 only)**
- Default settings: Close > "Do you want to close the Project?" > Yes closes the project with both tasks and the milestone still Open. Project shows Closed, % Completed jumps to 100% although tasks show 0/2 done; Actual End is auto-set to today. The Close button disappears; to reopen, use Edit and change Status (list: Open, Onhold, Closed, Canceled, In Progress). I reset Status to Open and % Completed to 0.
- Settings tab toggles save instantly (toast "Settings saved", no Save button). Turning on "Prevent closure with open child entities" then Close > Yes gave a red error toast: "Cannot close this project as one or more of its child entities are still open." Project stays Open.
- Turned Prevent off and "Auto-close child entities" on (its limitations note says: child updates trigger no custom actions or notifications, closure rules are not applied, and "Calculate actual time" is not run). Close now shows a different confirmation saying all milestones and tasks will also be closed. After Yes: project Closed, both tasks Closed, milestone 1/1, tasks 2/2, 100%. Actual Hours and Cost still "-".
- Full Settings list on a project, grouped: Schedule Settings (Enable strict project management, Auto-schedule child entities, Aggregate estimated effort); Closure Settings (Restrict operations on a completed entity, Auto-close child entities, Prevent closure with open child entities, Calculate actual time from child entities, Calculate actual cost on closure, Clear actual end time on re-open).

**5. Summary tab and fourth icon**
- Summary tab = six donut widgets: Tasks by Due Date, Milestones by Due Date (both "On Track"), Tasks Completed, Milestones Completed, Milestones by Status, Tasks by Status (empty widgets say "No Data").
- Fourth icon = Task Dependency diagram described above.

## Weak spots / confusing UX
- Dependencies can be violated silently; no warning even when dragging a successor before its predecessor.
- Dependency can only be created inside the diagram view, not from the task form.
- Project close succeeds with open work by default and shows 100% complete.
- Resource load ignores estimated effort and worklogs.
- The calendar-only picker and date-time picker open on click but close on scroll, and the worklog end picker rewrites time taken.
- Settings toggles apply instantly with no confirmation or undo.

## Test records created
PJT-6 now has: milestone "ZZ-CLAUDE-TEST milestone 1" (Oct 26 to 30, now Closed), "ZZ-CLAUDE-TEST project task 1" (Oct 27 to 30, owner me, 4 h estimate, $10 cost, 1 h worklog, Closed), "ZZ-CLAUDE-TEST project task 2" (Oct 28, Closed), one dependency task 1 to task 2. PJT-6 is Closed. Settings left as: Auto-close child entities ON, all others off.

=== END OF AREA 6 (including 6b) ===
