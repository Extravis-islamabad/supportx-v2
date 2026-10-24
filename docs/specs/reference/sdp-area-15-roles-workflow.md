# Area 15 - Role-based workflow walkthrough

ServiceDesk Plus Cloud (Enterprise trial) - Oct 24, 2026

## Setup and licences

Six ZZ-CLAUDE-TEST users, two roles, two technician groups and one service template were created, and 5 of 10 trial licences are now used.

| Object | What it is | Note |
| --- | --- | --- |
| ZZ-CLAUDE-TEST L1 role | Custom technician role | Requests View/Add/Edit, no Delete, cannot resolve or close |
| ZZ-CLAUDE-TEST L2 role | Custom technician role | Requests View/Add/Edit incl. Resolving and Closing |
| ZZ-CLAUDE-TEST L1 / L2 groups | Technician groups | A group must contain at least one technician |
| Requester | Requester, login enabled | Raises requests via the portal |
| L1 technician | Technician, L1 role + L1 group |  |
| L2 technician | Technician, L2 role + L2 group |  |
| Line Manager | Requester-type with Request Approver ticked | Shows as the Line Manager test user in pickers |
| Change Manager | Technician, custom role SDChangeManager | Role cannot be opened in Setup |
| Site Admin | Technician with SiteAdmin privileges for Base Site | Role SDSiteAdmin |

Setup findings that matter for a competitor:

- The admin's own email must be verified before the first login-enabled user can be added.
- Plus-addresses are rejected ("+ character cannot be in email id").
- The Reporting Manager picker lists technicians only, so a requester cannot be set as a line manager there. A requester-type user only becomes an approver through the Request Approver tick.
- The three technicians show the identical display name ZZ-CLAUDE-TEST in every picker, so L1 and L2 can only be told apart by choosing the group first (the group narrows the technician picker to one member).
- No outgoing mail server is configured on the instance, so no email of any kind can be sent from it (see Emails and notifications).

## Roles and permissions matrix

The only difference between L1 and L2 is Resolving Request and Closing Request; a granular scope limits both to their group's and their own tickets.

| Permission | L1 role | L2 role | SDSiteAdmin (viewed only) |
| --- | --- | --- | --- |
| Requests | View, Add, Edit | View, Add, Edit | View, Add, Edit, Delete (no Full Control) |
| Requests Delete | Off | Off | On |
| Problems | View | not set | Full Control |
| Changes | View | not set | Full Control |
| Other modules | Off (Announcement View auto-ticked) | not set | Full Control on Releases, Inventory, Purchase, Contract, Reports, maintenances, Announcement |
| Solutions | Off | not set | View, Add, Edit, Delete |
| Advanced Add (Requests) | Adding/Editing Request Task, Adding Requester | not recorded | n/a |
| Resolving Request | Off | On | n/a |
| Closing Request | Off | On | n/a |
| Other advanced Edit | Due Time, Approvers, Checklist, Stop Timer, Resolution, Assigning Technician, Editing Closed Requests, Followers all On | All On | n/a |
| Advanced Delete | All off | All off | n/a |
| Scope type | Module Level Granular Permissions | Module Level Granular Permissions | n/a |
| Requests scope | All in group and assigned to technician | All in group and assigned to technician | n/a |
| Problems / Changes scope | Assigned to technician | All in associated sites | n/a |
| Other modules scope | All in associated sites | All in associated sites | n/a |
| Technician can approve solutions / export from list view | Off / Off | not recorded | n/a |

Notes:

- Module Level Granular Permissions works. L1 saw only its own request, and after it escalated the request to L2, L1 lost access to it.
- SDChangeManager cannot be opened in Setup, so its checkboxes are unknown. Behaviour is described under the Change Manager section.
- Each permission is a tick-box grid per module (View, Add, Edit, Delete, Full Control) plus a separate Advanced block of single actions per module.

## Request lifecycle per role

A request travelled Requester, L1, L2 and back to the Requester, and each hand-off changed what the next person could see or do.

| Step | Role | What happened |
| --- | --- | --- |
| 1 | Requester | Raised a service request (#62) from the ZZ template in the Corporate Website category, and incidents, through the portal. The template only appeared after Show to Requester was ticked and saved. |
| 2 | Admin | Incidents #58 and #59 were routed to the L1 and L2 groups; the service request needed manual assignment because Auto Assign covers incidents only. |
| 3 | L1 technician | Saw only requests in its group or assigned to it. Could add and edit fields, reassign, add notes and change status. Resolve and Close were blocked, and Delete was blocked. |
| 4 | L1 technician | Escalated the request to L2. Immediately afterwards L1 could no longer open it (permitted scope error). |
| 5 | L2 technician | Picked up the request, resolved it and closed it. |
| 6 | Requester | Saw the result and the technician's name, replied, and could reopen the closed incident. No survey arrived because User Survey is not enabled. |

View behaviour worth copying or avoiding:

- The requester's default list is My Open Requests, filtered to Service requests only, until the Request Type toggle (Incidents, Service, Both) is switched to Both. An incident therefore looks missing on first login.
- L2's default Open Requests view hides In Progress requests.
- Requester views: All My Requests, Awaiting My Update, My Closed Requests, My Completed Requests, My Open Requests, Archived Requests.
- L2 additionally gets My Groups views and Trashed Requests.
- The Description typed into service request #62 did not register, so #62 was saved with a blank body. This is recorded as a test-input glitch, not a product finding.

## Approvals flow

Approvals could not be completed end to end, because the approval request is never delivered to the approver without a mail server.

| Check | Result |
| --- | --- |
| Service request #62 after submission | Shows Pending Approval |
| Approver on the ZZ template | Line Manager (Stage I), picked from requester-type users with Request Approver ticked |
| Template switch Show approval status to requesters | On |
| Template approval toggles | Blocked in Setup by the missing mail server |
| Line Manager portal | My Pending Approvals and My Open Requests were both empty |
| Requester's Approvals tab | Shows: Oops, outgoing mail server is not configured yet. Please contact your administrator for assistance. |
| Technician Actions menu on a request | Has Submit for Approval |
| Approve by email link, portal, or both | Not testable; no email goes out and the portal list stayed empty |

Change approvals:

- Change CH-11 (General Change Workflow) was created by the Change Manager. Its Approvals tab was empty at the Submission stage.
- The Change Approver picker lists technicians only. It was set to a ZZ technician before saving.
- Moving CH-11 to Submitted for Authorization first demanded a Status Comment (Provide value for field Status Comment). Saving then failed with User does not have this permission, so the Change Manager role cannot move a change forward on its own.
- CAB approval could not be tested because the change never left the Submission stage. The workflow does show the stages Submission, Planning, CAB Evaluation, Implementation, UAT, Release, Review and Close.
- Submission stage statuses: Accepted, Rejected, Requested, Requested for Information, Submitted for Authorization.

## Assignment and SLA behaviour

Technician Auto Assign is a plain round robin over every technician and ignores groups, and it only covers incidents.

| Setting (Setup > Automation > Technician Auto Assign) | Original | During test | Now |
| --- | --- | --- | --- |
| Enable Auto-assign | Off | On | Off (restored) |
| Auto-assign to | Incidents | Incidents | Incidents |
| Assignment model | Round Robin | Round Robin | Round Robin |
| When | Created | Created | Created |
| Apply to | All Requests | All Requests | All Requests |
| Based on technician availability | Off | Off | Off |
| Exclude technicians / requests | Off | Off | Off |

- Four incidents (#58 to #61) went to four different technicians in order: the admin, Shawn Adams, Heather Graham and John Roberts. None went to the L1 or L2 test technicians, because the rotation covers all technicians and has no group routing.
- Load Balancing is the only alternative model; it was not switched on.
- The option Incidents and Service Requests exists on the page, but was left unselected so service request #62 and the earlier #57 stayed unassigned and needed manual assignment.
- \#58 and #59 were then assigned by hand to the L1 and L2 groups. Choosing the group first narrows the technician picker to that group's member.
- SLA pause retest (On Hold 3 min, In Progress 3 min, Open) was not run: it is weekday-only, 09:00 to 18:00 instance time, and the session ran on a Saturday. It stays pending for the next weekday on a new ZZ request with SLA ZZ-CLAUDE-TEST SLA 1.

## Emails and notifications

No email was sent or received in any step, because Mail Server Settings is unconfigured and was deliberately left that way.

- Approval requests, assignment notices, status updates and replies produced no email to any role.
- The only in-product notifications seen were the bell icon on the technician and admin home screens and the in-page error shown on the Requester's Approvals tab.
- Notification Rules (Setup > Automation) exist for Request, Problem, Change, Project, Release, Solution, Asset, CMDB, Purchase, Contract, Task and Other Notifications, so a competing product needs per-module notification rules, not one global switch.
- Site Admin can see Business Rules and Custom Actions (including Notifications) but not Notification Rules.

## Blocked actions and error messages

Every block came from a permission or scope check, and each shows its own plain message.

| Who | Action | Exact message |
| --- | --- | --- |
| Any technician | Saving a request without a subject | You must provide a value for field Subject / Provide value for field Subject |
| L1 | Resolve, Close, Delete a request | User does not have this permission |
| L1 | Open a request after it was escalated to L2 | Request does not fall under your permitted scope. So you are not authorized to view the same. |
| Requester | View approvals with no mail server | Oops, outgoing mail server is not configured yet. Please contact your administrator for assistance. |
| Change Manager | Move a change to Submitted for Authorization | Provide value for field Status Comment, then User does not have this permission |
| Admin | Turn on template approvals | Toggle blocked: mail server not configured |

## Portal and chatbot as a requester

The requester portal is a thin self-service front end: raise a request from a visible template, follow it, reply and reopen.

- Service templates only show to requesters after Show to Requester is ticked and saved; saving adds a Requester View tab to the template. The first save did not take, so always confirm the Show to Requester column in the template list reads Yes.
- The requester can see the assigned technician's name.
- The requester can reopen a closed incident.
- Announcements and solutions are visible on the portal; no survey was shown because User Survey is not enabled.
- The chat widget is a Zoho SalesIQ widget with leave a message, voice message and articles. The requester gets no Ask Zia assistant; Zia chatbot settings (Ask Zia, Blended Conversations, Chatbot Customization) sit under Setup for admins.

## Dashboards, Site Admin and Change Manager

Dashboards and widgets were measured as Site Admin and main admin only; other roles were not compared and remain open.

**Site Admin: what it sees**

- Home tabs: Dashboard, Scheduler, Tech Availability Chart, Tasks, Reminders, Announcements. Main menu: Home, Activities, Requests, Assets, Changes, Releases, Reports, Purchases, Contracts, More.
- Setup shows only three sections: Instance Configurations (Sites, Departments), Users & Permissions (Users: All Users, Requesters, Technicians) and Automation (Business Rules, Custom Actions with Notifications).
- The Users page offers New Technician and an Actions menu, and no New Requester button.
- There is no Roles, Technician Groups, SLA, Templates, Auto Assign or Mail settings. The main admin sees all 14 Setup sections.

**Change Manager: what it sees**

- Menus: Home, Activities, Requests, Assets, Changes, Releases and More (Problems), with access to all data.
- Changes toolbar: Edit, Assign, Close, Print, Scheduler, Workflow, Actions and previous/next. Actions menu: Add Note, Add Task, Add Task from Template, Add Reminder, Add Worklog, Copy Change, Delete Change, Close Change; Notify > Send Notification; Resolution > Impact Details, Rollout Plan, Backout Plan, Checklist, Review Details; Conflict > Refresh Schedule Conflicts. There is no Submit for Approval entry.
- The change detail page has a stage rail (Stages, Roles, Associations, Conversations, Tasks, Reminders, Worklogs, Approvals) and tabs Details, Tasks, Approvals, Status Comments.
- The Roles block of a change holds Change Approver, Line Manager, Reviewer, Implementer and UAT Owner.

**Dashboards**

- Nine or more canned dashboards, including Helpdesk (default), Activities, Asset, Change, Contract, Problem, Purchase, Release and Software; a search box and a Favorites list sit at the top of the selector.
- Helpdesk dashboard widgets include Requests by Technician, Open Requests by Mode, Requests Last Week and SLA Violation by Technician.
- Header controls: All Sites and All Groups filters, full screen, a settings gear (refresh frequency Never to 30 minutes, Enable SmartView) and + New.
- A new dashboard takes a name, description, Executive Dashboard tick, Private or Public access, and 2, 4, 6 or 8 columns. Widgets can be grouped, up to 10 per group.
- Widget sources: Canned, Graph, Info, Report, Table and URL widgets.

| Module | Canned widgets |
| --- | --- |
| Requests | 31 |
| Asset | 21 |
| Releases | 21 |
| Changes | 20 |
| Purchases | 11 |
| Problems | 8 |
| Contracts | 6 |
| Software | 5 |
| Solutions | 0 |
| Tasks | 0 |
| Total | 123 |

The module selector may list more modules above Asset that were not opened, so 123 is a floor, not a verified ceiling. No maximum number of widgets per dashboard was found.

## Weak spots

The product's weakest points are everything that quietly depends on a mail server, and several confusing defaults.

- Approvals fail silently: the request says Pending Approval but nothing reaches the approver, and the only error is on the requester's Approvals tab.
- Auto Assign ignores groups and skips service requests unless changed, so it cannot route by team.
- Identical display names for different technicians make pickers unusable without the group trick.
- Approvers for requests must be requester-type users with a hidden Request Approver flag, while change approvers are technicians.
- A template stays invisible to requesters until Show to Requester is ticked and saved, and the first save can silently fail.
- Default list filters hide in-progress and incident records for L2 and requesters.
- The Change Manager role cannot be inspected or used to move a change forward, so the permissions gap is only visible by failing.
- The Site Admin cannot create requesters, only technicians.
- A technician loses sight of an escalated request, so L1 cannot follow up on what it escalated.
- The requester can reopen closed incidents with no policy shown.

## Everything created and settings restored

Only ZZ-CLAUDE-TEST objects were created, and the one global setting changed, Technician Auto Assign, is back to its original OFF state.

| Created | Detail |
| --- | --- |
| Roles | ZZ-CLAUDE-TEST L1, ZZ-CLAUDE-TEST L2 (edited by me, both mine) |
| Technician groups | ZZ-CLAUDE-TEST L1, ZZ-CLAUDE-TEST L2 |
| Users | Requester, L1 technician, L2 technician, Line Manager, Change Manager, Site Admin (5 of 10 licences used) |
| Service template | ZZ template in Corporate Website, Show to Requester ticked, approver Line Manager |
| Incidents | #58, #59, #60, #61 |
| Service request | #62 (no description) |
| Change | CH-11 ZZ-CLAUDE-TEST change by Change Manager, Submission stage; the status and approver edit was rejected, so it was not saved |
| Dashboard | A new dashboard form was opened and cancelled; nothing saved |

| Setting | Before | Changed to | Restored |
| --- | --- | --- | --- |
| Technician Auto Assign enabled | Off | On | Off, confirmed by the Technician auto assign settings saved message |
| ZZ role grids | Created by me | Edited several times | Final grids in the matrix above |
| ZZ template Show to Requester | Off | On | Left on (my own object) |

Nothing belonging to the existing instance was edited or deleted. No real email address, password or OTP appears in this report.

Still open: the SLA pause retest (weekday only), a Line Manager approval that can actually be delivered, CAB approval, per-role dashboard comparison, and a survey test (not enabled).

## Sign-in, invitation and MFA (observed by the trial admin; screenshots kept offline)

Invitation email:

- Sent by "Zoho Team" from a Zoho no-reply address, not the service desk's own address.
- Heading "Welcome to itdesk service desk!" ("itdesk" is the instance URL name, not a company name); no customer branding anywhere; ManageEngine/Zoho footer.
- Says "<inviter full name> has invited you to join the itdesk team"; Accept invitation button and Reject invitation link.
- One generic text for all user types (describes requester features even for technicians). Arrived within about a minute.

Join page (on the vendor's account site):

- Shows the org name and "Invited by <inviter name> (<inviter email>)": the inviter's personal email is shown to every invitee.
- A NEW third-party (Zoho) account is created for the invitee. First and last name are prefilled from the user record. Password, Country (auto-detected), and a mandatory tick to accept the vendor's Terms of Service and Privacy Policy. Proceed / Back.
- Then "Account Confirmed" and "Continue to Sign In".

Sign-in page:

- Vendor-branded, never the customer's.
- Email or mobile number first, then Next; social sign-in (Apple, Google, LinkedIn, X, Microsoft, Slack and more); QR "smart sign-in"; passwordless via the vendor's authenticator app; a separate "tenant account" sign-in link; a "Sign up now" link; a marketing panel.

MFA:

- After the first sign-in, a full-page "Secure your account using MFA" screen, shown even to requesters before they reach the service desk.
- Pushes the vendor's own authenticator app first (QR code, app store badges, manual "Start setup"); other methods are hidden behind "Show other MFA modes".

Findings for SupportX:

- Every user must create a third-party account and accept a third-party's terms before raising a ticket: friction for requesters and a data-protection question for banks and government.
- Invites, sign-in and MFA are vendor-branded. SupportX: tenant-branded invites (tenant logo, name and sender address), tenant-branded login page, role-appropriate invite text, and the organisation shown instead of the inviter's personal email.
- MFA via Keycloak with any standard authenticator app (and WebAuthn), admin-controlled per role (e.g. required for technicians, optional for requesters), no vendor app required.
- Good to copy: short three-step activation, prefilled names, clear accept/reject.

=== END OF AREA 15 ===
