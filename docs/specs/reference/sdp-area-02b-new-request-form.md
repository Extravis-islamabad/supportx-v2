# Area 2b: New Incident form, templates and first test records

## Navigation path
- Requests → **New** (opens `/app/itdesk/ui/requests/add`, titled "New Incident"). The same form is reached from the list's New dropdown, which offers incident and service templates.
- Template switcher: the "Select Template" dropdown at the top right of the form.
- Detail page: `/app/itdesk/ui/requests/<id>/details`.
- Workflow execution view: the "Workflow" button on the request detail page.

## Screens and what they do
1. **New Incident form (Default Request template).** One long page with these sections, top to bottom: request classification, Requester Details, Site/Group/Technician plus the category tree, Subject, Description (rich text), Attachments, and Resolution. A "Suggested Solutions" panel sits on the right and searches the KB as the subject is typed. The panel can be hidden.
2. **Template switching.** Changing the template reloads the form and changes the title and the fields. Incident templates show the incident-style fields. Service templates (e.g. New Employee Onboarding) add their own fields, such as Employee Name and Employee Type.
3. **Request detail page after save** has:
   - An action bar: Edit, Close, Cancel, Pick up, Assign, Print.
   - A "Reply All" split button, a Workflow button (service requests with a workflow only) and an Actions menu.
   - Tabs: Conversations, Details, Approvals, Tasks, History and a "…" overflow.
   - A right-hand Properties panel, and an Associations section (Linked Requests, Changes Caused by Request, Change that Initiated Request, Associated Project).
4. **Workflow Execution view** (service requests only). A full-screen canvas of the workflow with a "Highlight Executed Path" toggle, zoom controls and a minimap. The current node is outlined.

## Fields (New Incident form, Default Request template)

| Field | Type | Required | Options / values | Notes |
|---|---|---|---|---|
| Select Template | dropdown | no | Default Request. Incident templates: Frequent Application Crashes, Mail Fetching, Maintenance, Major Incident Management, MIM - RCA, New Joinee, Printer problem, Unable to browse. The list is grouped under a "General Incident Templates" heading. | Switching reloads the form. |
| Request Type | dropdown | no (not starred) | Incident, Major Incident, Request For Information, Service Request | Empty by default on this form. |
| Status | dropdown | no | Open (default), On Hold, Closed, Resolved, Canceled, In Progress, Staging, Pending Verification, Rejected | 9 values. |
| Mode | dropdown with search | no | E-Mail, Live Chat, Mobile Application, Phone Call, Web Form | 5 values. |
| Level | dropdown | no | Tier 1, Tier 2, Tier 3, Tier 4 | |
| Impact | dropdown | no | Affects Business, Affects Department, Affects Group, Affects User, High, Low, Medium | The scale is a mix of scope-style and High/Medium/Low values. |
| Impact Details | free text | no | – | |
| Urgency | dropdown | no | Low, Normal, Medium, High, Urgent | Order read from the list. |
| Priority | dropdown | no | Low, Normal, Medium, High, Critical | Not computed from Impact and Urgency by default. |
| Requester Name | lookup with "add requester" icon | **yes** | users | Shows Phone, Department and Job Title under the field once chosen. |
| Assets | lookup with "+" | no | assets | Several assets can be linked. |
| Site | dropdown | no | Base Site (default) | |
| Group | dropdown | no | App Development, Data Management, Development, Hardware Problems, Hosting Team, Infra-SSO, Internet, Maintenance, Major Incident Team, Network, Onboarding, Printer Problems, Software | 13 groups. |
| Technician | dropdown | no | 7 technicians plus a "Show only online technicians" toggle | I did not record the names. |
| Category | dropdown | no | Desktop Hardware, Firewall, General, Hardware, Internet, Network, Operating System, Printers, Routers, Services, Software, Switches, Telephone, User Administration | 14 values. |
| Sub Category | dependent dropdown | no | depends on Category | Empty until a Category is chosen. |
| Item | dependent dropdown | no | depends on Sub Category | Only a few items were checked; the full tree is not listed. |
| Subject | text | **yes** | – | Typing triggers the Suggested Solutions panel. |
| Description | rich text editor | no | – | Font, size, colour, lists, indent, spacing, maximise, a "more" chevron and an AI-assist icon. |
| Attachments | drag and drop | no | – | "+" menu beside the label. |
| Resolution | rich text | no | – | Present on the create form, so a request can be created already resolved. |
| Scheduled Start Time | date-time | no | – | Shown on the service template form. |

**Service template (New Employee Onboarding) extras:**
- Employee Name: text.
- Employee Type: dropdown (Permanent was used; other values were not captured).
- It keeps the common fields: Site, Group, Technician, Category chain, Subject, Description.

**Buttons:** Add Request, Reset, Cancel.

## Actions and menus
- Form: Add Request saves and lands on the detail page. Reset clears the form. Cancel leaves it.
- Detail action bar: Edit, Close, Cancel, Pick up, Assign, Print. These are only listed here; trying them is for Area 2c.
- Request-level menus ("Actions", "Reply All" dropdown, "…" tab overflow) exist. Their contents are for 2c.
- Tasks tab: All Tasks view switcher, Quick Add, Add Task, Edit, Organize, Delete, Close, Trigger, Assign Owner, "…" and a list/card toggle.

## Configuration options
Read-only observations from the form:
- Templates control which fields appear and which type the form creates.
- The Request Type, Mode, Level, Impact, Urgency, Priority and Status lists are admin-defined lookups. I did not open their Setup pages in this part.
- Mail server: not configured. The Approvals tab shows "outgoing mail server is not configured yet", with a link to set it up.

## Automation / triggers / rules in this area
- **Incident #36 (default template, no priority set):** nothing fired. There was no technician or group assignment, no SLA, no due date, no notification and no workflow. I did not look in Setup to find out why. It is probably because no business rule, SLA or assignment rule matched.
- **Service request #37 and #38 (New Employee Onboarding):** a workflow instance was created automatically. The History tab shows "Workflow Instance Created — Workflow execution initiated for 'Employee Onboarding'" performed by System, followed by "Request Created" performed by the logged-in user.
- **Workflow structure, as seen on the canvas:**
  - A timer node: "wait for the scheduled start time" with Aborted/Ended branches.
  - A "Wait for Employee Type" node.
  - A Hiring Manager Approval node with Approved/Rejected branches.
  - An "In Progress" status-change node, then a "Split and Handle Tasks" node that creates three tasks: IT Task, Legal Task, and Facilities and Payroll. Each task has Completed and Overdue branches.
  - A "Wait for task completion" node with Completed/Failed branches, a "Hiring Team Notification" email node and a "Closed" status node.
  - Node types seen: timer/wait, wait-for-field, approval, status update, task split, wait for tasks, notification.

## Behaviour observed in tests
- **#36 "ZZ-CLAUDE-TEST incident 1"**
  - Type Incident, status Open, requester my test user.
  - Technician and group: not assigned. Auto-assignment did not run.
  - Priority: not assigned. SLA: none. Due By: "No due date set".
  - Conversations tab: only the description entry. No auto-notification appeared, and none could be sent anyway.
  - Approval Status: "Not Configured".
- **#37 "ZZ-CLAUDE-TEST service 1"** (New Employee Onboarding, Employee Type left empty)
  - Status Open, workflow Employee Onboarding.
  - The workflow stopped at the wait/timer node because Employee Type was empty.
  - Approval Status "Not Configured", no tasks, no technician, no SLA, no due date.
- **#38 "ZZ-CLAUDE-TEST service 2 (permanent, approval path)"** (Employee Type = Permanent)
  - Created on the second Add Request click. The first click did not save (the form stayed open and no #39 exists).
  - Status Open, priority Not Assigned, technician Not Assigned, group and site "-", Tasks 0/0, Due By "No due date set".
  - The workflow reached **Hiring Manager Approval** (highlighted in the execution view).
  - The Approvals tab, however, shows only the "outgoing mail server not configured" message, and the Approval Status field still says "Not Configured". So the approval node is waiting, but no approval request is visible or actionable because mail is not set up.
  - The Tasks tab is empty ("No tasks found in this view"). Tasks are only created after approval.
  - History shows two entries: Workflow Instance Created (System) and Request Created.
- **Notifications:** none appeared on any of the three. The bell has a "2" badge that belongs to earlier items and was not touched.
- **Assignment:** nothing is auto-assigned for the default incident or for either service request. Every record starts unassigned and Open.
- **Priority and due date:** neither is set by default, so no due date is computed.

## Edition notes
- Trial of the Enterprise plan, expiring in 30 days.
- The workflow canvas, task split and wait-for-task nodes were all available.
- I did not verify which parts are Enterprise-only.

## Weak spots / confusing UX
- The Impact list mixes scope values (Affects User/Group/Department/Business) with High/Medium/Low, so it is unclear how it feeds priority.
- Urgency has "Normal" and "Medium" together, and Priority has "Normal" and "Medium" together, which looks redundant.
- The form's title says "New Incident" even when a service template is chosen. The Request Type field is not required but decides how the request is treated.
- A new request with no priority gets no SLA and no due date, and nothing says so.
- The Approvals tab only shows a mail-server error. It does not show the pending approval or its approver, so you cannot see what the workflow is waiting for.
- A workflow stuck at a wait node (#37) gives no warning on the request page except a red dot on the Workflow button.
- The first click on "Add Request" did nothing visible, with no spinner or error. This is how a double-submit duplicate could happen.
- The Technician dropdown shows its count text and an "online only" toggle inside the list, which is easy to miss.

## Test records created
| # | Subject | Type / template | Notes |
|---|---|---|---|
| 36 | ZZ-CLAUDE-TEST incident 1 | Incident, Default Request | Open, unassigned, no SLA. |
| 37 | ZZ-CLAUDE-TEST service 1 | Service Request, New Employee Onboarding | Workflow stuck at the Employee Type wait. |
| 38 | ZZ-CLAUDE-TEST service 2 (permanent, approval path) | Service Request, New Employee Onboarding | Workflow waiting at Hiring Manager Approval. |

No existing records or settings were changed. I opened the New Incident form again at the end only to read dropdowns and did not save it.

**Not captured in 2b:**
- The names of the 7 technicians.
- The full Sub Category and Item tree.
- The other service templates' own fields.
- Why #36 got no assignment or SLA.

=== END OF AREA 2b ===
