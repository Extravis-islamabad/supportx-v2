# Area 2c: Detail page actions on the test records

## Navigation path
- Requests → open a request. URL pattern: `/app/itdesk/ui/requests/<id>/details`.
- Action bar across the top: Edit, Close, Cancel, Pick up, Assign, Print. Service requests with a workflow also get a **Workflow** button. Every request has an **Actions** menu on the right.
- Tabs: Conversations, Details, Approvals, Tasks, History and a "…" overflow.
- Right panel: Properties, Associations, Requester Details.

## Screens and what they do
1. **Conversations tab.** Shows the description, notes and emails. Filters: Emails, Auto Notifications, Notes. A public note has a globe icon, a private note a red lock, and a merged request's content is tagged "MERGED". Each entry has reply, reply-all, forward and delete icons. The "Reply All" split button sits at the top right and has an arrow and a small notes icon next to it.
2. **Details tab.** Read-only field dump with a "Hide Empty Fields" toggle. It lists all create-form fields plus Created Date, Responded Time, Due by date, Response Due Date, Completed Time, Created By, Department, Template and SLA.
3. **Tabs that appear on demand.** Worklog and Reminders tabs show up only once the request has such items. The "…" overflow lists whichever tabs are not shown: Tasks, History, Checklists, Resolution, Reminders, Worklog, Time Elapsed Analysis and Announcements.
4. **Time Elapsed Analysis.**
   - A summary strip showing "Life of Request" (12 mins at that moment), On-Hold time, Assigned time in groups, Assigned time by technicians, and SLA Response/Resolution (N/A before an SLA is applied).
   - Below it, horizontal bars for Status, Group and Technician.
5. **Resolution tab.** Contains:
   - A "Search Solutions" button and a "Use Resolution Template" dropdown.
   - A rich-text editor, a "Request Status" dropdown at the bottom, and Attachments.
   - Two checkboxes: "Add resolution to all linked requests" and "Add Worklog".
   - Buttons: Save, Save and Add To Solutions, Cancel.
6. **Checklists tab.** Has a "New Checklist" split button, "Manage Checklists", a search box, and a collapsible list with a per-checklist progress circle (0/1).
7. **Reminders tab.** Has New Reminder, Delete, "Modify Reminder State To", and a grid of Summary and Date.
8. **Worklog tab.** Table with Time Spent, Charges (Technicians, Others, Total) and a TOTAL row.
9. **Tasks tab.** Same toolbar as the incident one in 2b (Quick Add, Add Task, Edit, Organize, Delete, Close, Trigger, Assign Owner, view toggles).
10. **Print Preview.** A modal with checkboxes for: Request Details (with "Hide Empty Fields"), Requester Details, Checklists, Resolution, Conversations, Worklogs, Notes, Time Elapsed Analysis, Announcements and History.
11. **Workflow Execution view** (service requests). Described in 2b. After "Revoke Workflow" the Workflow button disappears.

## Fields (dialogs on the detail page)

| Dialog | Field | Type | Required | Options / values | Notes |
|---|---|---|---|---|---|
| Add Notes | Note body | rich text | yes | – | Plus attachments. |
| Add Notes | Show this note to requester | checkbox | no | – | Unchecked = private (lock); checked = public (globe). |
| Add Worklog | Owner | dropdown | yes | technicians (defaults to me) | |
| Add Worklog | Worklog Type | dropdown | no | General Services (the only value) | |
| Add Worklog | Include non operational hours | checkbox | no | on by default | |
| Add Worklog | Executed Time | date-time range | no | – | End defaults to now; start was blank and saving still worked. |
| Add Worklog | Time Taken To Resolve | hrs and mins | yes | – | |
| Add Worklog | Currency / Exchange Rate | dropdown / number | no | US Dollar (starred default) | Exchange rate read-only; changes apply to this worklog only. |
| Add Worklog | Technician's Cost per Hour | read-only number | – | 0.00 | |
| Add Worklog | Tech Charges / Other Charges | numbers | no | 0.00 | Tech Charges = time × cost per hour; Total = Tech + Other. |
| Add Worklog | Total Charges | read-only | – | – | |
| Add Worklog | Description | rich text | no | – | |
| Add Worklog | Consider as first response | checkbox | no | – | |
| Worklog timer | Comments | text | no | – | Buttons: Start My Timer, Stop My Timer, Add My Worklog. |
| Add Task | Select Template | dropdown | no | Default Task, Add New Gadgets, Complete Verification, Create Active Directory (AD), Create ID Card, Generate Employee ID, Level 1 Employee Verification, Level 2 Employee Verification by Vendor, Restore Data Backup | 9 results. |
| Add Task | Title | text | yes | – | Defaults to "Default Task". |
| Add Task | Description | rich text | no | – | |
| Add Task | Scheduled Start/End, Actual Start/End | date-times | no | – | |
| Add Task | Group | dropdown | no | same groups as the request | |
| Add Task | Owner | dropdown with clear (x) and a toggle with "?" help | no | technicians (defaults to me) | |
| Add Task | Priority | dropdown | no | Critical, High, Medium, Low, Normal | |
| Add Task | Status | dropdown | yes | Open (default), In Progress, On Hold, Pending Verification, Rejected, Resolved, Staging, Closed, Canceled | |
| Add Task | Additional Cost | currency | no | – | |
| Add Task | Task Type | dropdown | no | 14 values incl. Final Verification, Implementation, Install/UnInstall, Maintenance, Onboarding, Planning, Replacement/Repair, Restoration, Testing, Troubleshooting, Vendor Verification, Verification | 2 of 14 not captured. |
| Add Task | Notify Before Schedule Start | dropdown | no | Never (default) | Options not captured. |
| Add Task | % Completed | number | no | – | |
| Add Task | Estimated Effort | days / hrs / mins | no | – | |
| Add Reminder | Summary | text | yes | – | |
| Add Reminder | Date | date-time picker (with Today and Apply buttons) | yes | – | |
| Add Reminder | Email me before | select | no | Never, 15 mins, 30 mins, 45 mins, 1 hr, 2 hrs, 6 hrs, 12 hrs, 1 day, 2 days, 1 week | |
| New Checklist | Name / Description | text | Name yes | – | |
| New Checklist | Items | inline list | – | – | Max 25. Buttons: New Item, Add Existing Items, Add from CSV, and a Preview link. |
| Assign | Site / Group / Technician | dropdowns | no | Base Site; 13 groups; 7 technicians | The technician list was not filtered by the chosen group. Each name has an online dot. A "Show only online technicians" toggle sits in the list. |
| Link Requests | View selector | dropdown | – | All Requests, My Completed Requests, Pending Requests, Unassigned Requests, Completed Requests, Service Requests, Incident Requests, My Pending Requests or Tasks (opens on My Pending Requests) | Plus a comments box. |
| Merge Request | View selector | dropdown | – | Open Requests (default) | Single-select radio list. |
| Duplicate Request | Number of Copies | number | yes | – | |
| Close Request | Is FCR | checkbox | no | – | |
| Close Request | Requester Acknowledged Resolution | radio | no | Yes / No (default No) | |
| Close Request | Closing Comments | text | no | – | |
| Close Request | Closure Code | dropdown | no | Cancelled, Failed, Moved, Postponed, Rejected, Success, Unable to Reproduce | 8 results listed; one value may be missing. |
| Close Request | Closure Comments / Status Change Comments | text | no | – | |
| Cancel request | Reason | dropdown | yes | Created a request by mistake, Found a solution by self, Invalid Request, Duplicate Request, Others | Plus a comment box. |
| Share Request / Manage Followers | Select Users | multi-lookup | – | – | Plus comments. |
| Edit form (#36) | – | – | – | – | See "Behaviour observed" for what changes versus New. |

## Actions and menus

**Actions menu, open incident (#36):** Add Note, Add Task, Add Task from Template, Add Reminder, Add Worklog, Share, Follow, Manage Followers, Merge Request, Duplicate Request, Delete, Convert as service request, Create Service Request. Under "Approve": Submit for Approval. Under "Notify": Make an announcement.

**Actions menu, open service request (#37):** same, except it has Convert as incident request and Revoke Workflow instead of the two Convert/Create service-request items. Notify adds "Email the Technician".

**Actions menu, closed incident:** Add Note, Add Task, Add Task from Template, Add Reminder, Add Worklog, **Add Closure Code**, Share, Follow, Manage Followers, Merge Request, Duplicate Request, Delete. Notify has Make an announcement, Email the Technician and SMS the Technician. Convert, Create Service Request and Submit for Approval are gone.

**Action bar by state:**
- Open: Edit, Close, Cancel, Pick up, Assign, Print.
- Resolved: Edit, Close, Pick up, Assign, Print (Cancel removed).
- Closed: Edit, Pick up, Assign, Print, **Mark FCR** (Close and Cancel removed). A "CLOSED" stamp appears over Properties.
- Canceled: only **Revert Cancelation** and Print. The Cancel dialog warns that the request becomes read-only.

**Also seen:**
- Reply All and its arrow: the arrow opened no menu.
- Reply icons on conversation entries: reply, reply-all, forward.
- Worklog Timer icon in Properties. It turns blue while running and opens a popup (started time, comment, "include non operational hours" toggle, Stop My Timer, Add My Worklog).
- Previous/next request arrows at the top right, and a gear icon beside Actions.
- Requester Details cards: Assets Owned, Previous Requests, Remote Connection.
- Not opened: Follow, Delete, Task from Template, Make an announcement, Mark FCR, Add Closure Code, and the Email/SMS options.

## Configuration options
Nothing was saved in Setup. Observations only:
- Worklog types, closure codes, cancel reasons, task templates, task types and resolution templates are admin-defined lists.
- The mail server is still unconfigured. Approvals and reply dialogs depend on it.

## Automation / triggers / rules in this area
- **SLA by priority.** Saving Priority = High on #36 (no priority before) set "SLA: High SLA" and a Due by date of Oct 26, 2026 09:47 AM. These were added in the same History entry as the priority change. The header's Due By showed "Due in 47Mins" afterwards, which does not match that due date; I could not explain the difference. So SLA and due date are only evaluated when a priority is set. Nothing fired at creation because no priority was chosen.
- **Assignment** does not change status. After Assign (#36) and Pick up (#37), status stayed Open and Life cycle stayed "Not Assigned".
- **Closing** stopped the running worklog timer automatically (History: "Worklog timer stopped… Performed by System").
- **Reopening** clears Closure Code, Completed Time and Resolved Time, and resets "Time Elapsed" to 0.
- **Resolving** stamped a Responded Time on #36 and changed Due By to "Timer Stopped".
- **Workflow:**
  - Cancel put #37 into Canceled and the Workflow button showed a red cross. "Revert Cancelation" restored it.
  - "Revoke Workflow" on #38 showed a warning that it stops the workflow automation and clears its execution log. After confirming, the Workflow field went to "Not Assigned" and the Workflow button disappeared.
  - "Submit for Approval" on #37 jumped to the Approvals tab and showed only the "outgoing mail server not configured" message, so manual approvals cannot be sent here.
- **Merge:** the confirm text says that worklogs, notes, conversations, reminders, tasks, checklists and announcements of the CURRENT request move to the selected request.

## Behaviour observed in tests

**#36 "ZZ-CLAUDE-TEST incident 1" (History in order):**
1. Private note: saved with a lock icon, toast "Note added".
2. Public note: saved with a globe icon. Both appear as "Note Created" in History, with a link to view the note.
3. Reply All: the description entry turned into the "mail server not configured" panel and nothing could be composed or sent.
4. Worklog 1 hr 30 mins (type General Services): toast "Worklog added", and a Worklog tab appeared. Total charge $0.00.
5. Timer: stop prompts "Stopping the timer will lose the worklog data. Add the worklog?". "Add My Worklog" opened the worklog form prefilled with the comment as the description and 0 hrs; I closed it without saving.
6. Task "ZZ-CLAUDE-TEST task 1": Tasks counter 0/1, status Open, owner me.
7. Reminder (Oct 26): a Reminders tab appeared, counter 1.
8. Checklist with one item: counter 0/1. The empty second row was ignored.
9. Edit form: identical to New Incident plus Request ID chip, "Emails to Notify", editable Created Date, Due by date and Response Due Date, read-only Responded Time and Completed Time, a collapsed Resolution section, and a "Reason for updating request" box (reasons appear in History). The button reads "Update Request". The create form also shows "Emails to Notify" in the narrow layout. Priority options carry coloured dots.
10. Edit with Priority High: SLA applied (see above).
11. Assign (Group Software, technician me): History "Group updated None→Software, Technician updated, Assigned Time updated".
12. Linked #37 to #36: History "Request Linked… Link comments…"; the panel then shows "1 request(s) linked" with Attach | Detach. Linking only offered My Pending Requests at first, so #37 was reached through the "Unassigned Requests" view. The list there also contains real sample requests.
13. Close with code Success and comment: allowed even with an open task (0/1) and open checklist. History "Closed… Closure Code None→Success… FCR is set as false".
14. Reopen via Edit: the status list for a closed request is Closed, In Progress, On Hold, Open, Pending Verification, Rejected, Resolved, Staging (no Canceled). History "Reopened".
15. Resolve via the Resolution tab with Request Status = Resolved: toast "Resolution added", status Resolved, entry "(Resolution Submitted)".

**#37 "ZZ-CLAUDE-TEST service 1":**
- Pick up: assigned to me immediately with no dialog. Technician set, Group stayed blank.
- Submit for Approval: Approvals tab error as above.
- Cancel with reason "Created a request by mistake": toast "Request updated", status Canceled, only Revert Cancelation and Print left.
- Revert Cancelation: confirmation dialog, then Open again. Completed Time cleared and Time Elapsed reset.

**#39 and #40 (merge test):**
- #39 created as a normal incident. Its first Add Request click did nothing visible because the Suggested Solutions banner shifts the layout; the second click saved it.
- "Duplicate Request" with 1 copy made #40 with the same subject. History on #40: "Request Copied… copied as a New request from Request ID 39".
- Merge from #39 selecting #40: confirmation, then the page switched to #40. A "MERGED" conversation entry carries #39's content. History on #40: "The following requests have been merged — Request IDs: 39".
- #39 no longer appears in the Open Requests list (only #38, #37 and #40 do). I could not open #39 to see whether it was closed or deleted, so that stays unverified.

**#38 "ZZ-CLAUDE-TEST service 2":**
- Print preview opened with all checkboxes ticked; I cancelled it.
- Revoke Workflow confirmed and executed (see above).
- Share and Manage Followers dialogs opened and cancelled (a user picker and a comments box only).

## Edition notes
- Trial of the Enterprise plan. Everything above worked on the trial.
- Email-related actions (reply, approvals, email/SMS technician) need a mail server. I did not try to configure one.

## Weak spots / confusing UX
- The Reply All arrow does nothing, and a reply attempt replaces the conversation card with an error instead of opening a composer.
- Closing is allowed with open tasks and checklists. The timer stops without asking.
- "Assigned" does not move a request to In Progress, so status has to be changed by hand.
- Priority drives SLA silently. The request can sit with no SLA and no due date forever if priority is left blank.
- Due By in the header ("Due in 47Mins") disagrees with the due date in History (Oct 26).
- The Link Requests dialog opens on "My Pending Requests", so unassigned requests are hidden until the view is changed. It also mixes real and test data with no search shown by default.
- The Merge dialog is a single-select radio list, and the direction of the merge is only explained in a confirmation.
- "Duplicate Request" gives the copy the identical subject, which makes copies hard to tell apart.
- The first click on a bottom button often misses because the form grows (Suggested Solutions banner).
- Tabs appear and disappear (Worklog, Reminders), so the tab bar moves around.
- Timer stop dialog says data will be lost, yet "Add My Worklog" opens an empty (0 hrs) form.
- While a request page was loading, Properties briefly showed the previous request's ID (#36 while opening #38).
- Worklog "Executed Time" start can be blank and still save.

## Test records created
| # | Subject | State at end |
|---|---|---|
| 36 | ZZ-CLAUDE-TEST incident 1 | Resolved. Priority High, High SLA, group Software, technician me. Has 2 notes, a 1h30 worklog, 1 task, 1 checklist, 1 reminder, linked to #37. |
| 37 | ZZ-CLAUDE-TEST service 1 | Open (cancel reverted), technician me, workflow still attached, linked to #36. |
| 38 | ZZ-CLAUDE-TEST service 2 (permanent, approval path) | Open, workflow revoked. |
| 39 | ZZ-CLAUDE-TEST merge A | Merged into #40 (current state not verified). |
| 40 | ZZ-CLAUDE-TEST merge A (duplicate of #39) | Open, holds #39's merged content. |

"Me" in these notes is the trial admin. No existing request was changed. The only other records I viewed were real sample requests listed in the Link and Merge pickers. I did not select or alter any of them. Notification bell badge went from 2 to 3 during this area. I did not open it. Nothing was saved in Setup.

=== END OF AREA 2c ===
