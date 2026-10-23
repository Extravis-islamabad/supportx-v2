# Area 13 (Admin part 3): Customization, closure, archive, surveys, mail, General Settings (part 1)

First, the housekeeping you asked for. The three ZZ business rules (BR 1, BR cascade, BR abort) and "ZZ-CLAUDE-TEST trigger 1" are switched OFF. I confirmed the trigger is off after a reload. The ZZ SLA, workflows, templates and life cycle are untouched.

For the whole of this area I changed nothing. Every form I opened was cancelled, no setting was saved, and I made no new ZZ items. One radio button on the Request Closure Rules page was clicked and never saved (see Closure).

## Navigation path

Setup is the gear icon at the top right. The menu has these groups:

- **Customization:** Helpdesk, Problem, Change, Project, Release, Solution, Asset, CMDB, Purchase and Contract Management, Additional Fields, Checklists & Items, Announcement, Maintenance Management, Subform Types.
- **Templates & Forms:** Service Category, one template page per module, Task Template & Layout, Reply Template, Resolution Template, Announcement Template, Form Rules, Custom Scripts.
- **Mail Settings:** Mail Server Settings, Mail Filter, Email Command.
- **User Survey:** Survey Settings, Define Survey, Survey Preview, Survey Results.
- **Data Administration:** Data Archive, Sandbox, Audit Log, System Log, PII/ePHI Log, Telephony Log, Import Data, Export Data.
- **General Settings:** Advanced Portal Settings, Requester Portal, Theme Settings, Navigation & Footer Settings, Cloud Attachments, Approval Settings.

## Screens and what they do

### Helpdesk customization

Setup > Customization > Helpdesk has tabs for Category, Status, Level, Mode, Impact, Urgency, Priority and Priority Matrix. A "..." overflow adds Request Type, Task Type, Worklog Type, Closure Code and Downtime Type. Each tab is a list with a "New ..." button. The list gear icon edits or deletes a row, and I did not open it.

| Tab | Current contents |
|---|---|
| Category | 14 categories, listed below |
| Status | 9 statuses in two types |
| Level | Tier 1 "Info", Tier 2 "Tips", Tier 3 "Trouble Shooting 1", Tier 4 "Trouble Shooting 2" |
| Mode | E-Mail, Live Chat, Mobile Application, Phone Call, Web Form |
| Impact | Affects Business, Affects Department, Affects Group, Affects User, High, Low, Medium (7) |
| Urgency | High, Low, Medium, Normal, Urgent (5) |
| Priority | Critical #d11818, High #ff0000, Low #666666, Medium #ff6600, Normal #006600 |
| Priority Matrix | Impact rows against Urgency columns. Every cell is empty ("Select Priority") |
| Request Type | Incident, Major Incident, Request For Information, Service Request |
| Task Type | At least 10 (see below) |
| Worklog Type | One: "General Services" |
| Closure Code | Cancelled, Failed, Moved, Postponed, Rejected, Success, Unable to Reproduce (7) |
| Downtime Type | Degraded Performance, Full ShutDown, Minor, Minor Impact, Partial availability (5) |

- **Categories:** Desktop Hardware, Firewall, General, Hardware, Internet, Network, Operating System, Printers, Routers, Services, Software, Switches, Telephone, User Administration. Each expands into sub-categories and items. The list has a Tree View button.
- **Task types** seen include Final Verification, Implementation, Install/Uninstall, Maintenance, Onboarding, Planning, Release, Replacement/Repair, Restoration and Testing. Several have a colour.
- **Status types:**
  - In Progress type: In Progress (timer stops), On Hold (timer stops), Open, Pending Verification and Staging (timer runs).
  - Completed type: Canceled, Closed, Rejected and Resolved (the Stop Timer column is empty).
  - Each status has a colour.
- **Priority Matrix** has a toggle, ON, that lets requesters and technicians override the matrix and set priority themselves. A new request's priority is therefore set by hand, because the matrix is empty.
- **Impact list** mixes scope-style values (Affects User/Group/Department/Business) with severity values (Low/Medium/High). The two lists overlap, which is confusing.

### Additional Fields

- Setup > Customization > Additional Fields is a list with a module dropdown and a data-type filter. A "New Field" button opens the form.
- **Module dropdown:** Request, Problem, Change, Project, Release, Solution, Asset, CMDB, Purchase, Contract, plus License, Agreement and Vendor.
- **Request module:** 22 fields, 10 per page. Examples are Address, Analysis, Current Version, Destination, Division, Email id, Employee ID/Name/Type, Environment Impacted, Impact Start/End Time, Issue, Post Incident Action, Recently Upgraded, Resolvers Involved, Role, Root Cause, Solution, Type, Workaround and Zoho Meet (Web URL).
- **Columns:** Field Name, Description, Type, Default Value, Field Key. Keys follow the pattern `txt_<name>` or `date_<name>`.
- **Data-type filter:** All, Text, Numeric, Date/Time, Decision Box, Decimal, Lookup.

### Checklists & Items

- **Checklists tab:** it has "New Checklist". Currently 0 checklists exist.
- **Checklist Items tab:** it has "New Checklist Item" and "Import from CSV". Currently 0 items exist.

### Announcement and Maintenance

- **Announcement types:** six (New Knowledge Base Entry, New Policy, New Service Launched, Service Down, Service Up and Running, Service Update).
- **Maintenance Management > Configuration:** Date Format dd/MM/yyyy, plus ID prefix and start number per maintenance type:

| Type | Prefix | Starts from |
|---|---|---|
| Request maintenance | RQM | 3 |
| Change maintenance | CHM | 3 |
| Task maintenance | TKM | 1 |

- **Subform Types:** empty. It has "New Subform Type".

### Templates & Forms

- **Reply Template:** 4 system-created templates ("Please Call Us", "Need More Details", "Printer Configured", "Default Reply Template", the default one starred). Columns are Name, Subject, Description (starts "Dear $RequesterName"), Created by and Created Time.
- **Resolution Template:** empty ("No resolution template found"). It has "New Resolution Template".
- **Task Template:** 9 templates, all created by System and enabled. Examples are Restore Data Backup, Complete Verification, Add New Gadgets, Create Active Directory (AD), Create ID Card and Generate Employee ID. Columns are Name, Layout ("Default Task Layout"), Modules (6) and Created by. It has "New Task Template", "Copy Template", a star for the default, and a Task Layout tab.
- **Custom Scripts and Form Rules:** covered in Area 12. Custom Scripts is empty.

### Request closing, reopening and archiving

#### Closure Rules

Setup > Automation > Closure Rules > Request Closure Rules (Problem and Change tabs exist too).

- **Mandatory fields for closing:** a checkbox grid. All are unchecked right now.
  - Standard fields: Mode, Level, Group, Technician, Category, Priority, Sub Category, Description, Item, Resolution, Worklog, Urgency, Impact, Request Type, Attachments.
  - Closing conditions: "Associated tasks should be closed", "All child requests must be closed", "All associated checklists must be completed".
  - All 22 additional fields also appear in the grid.
- **Confirm User Acknowledgment.** It is set to "Yes, prompt a message before resolving the request", with two optional sub-checks, "Mandate closure code" and "Mandate closure comments". Both are off. The other choice is "No, don't prompt".
- **Request Closing Process.** It is set to Manual Closure. The alternative is Automated Closure. I clicked that radio only to read it and did not save, and I confirmed the page reverts on reload.
  - Automated Closure shows "Close resolved requests after N days" (default 1).
  - Technicians are prompted for resolution details when resolving.
  - The requester is emailed and can close or reopen the request. If they do nothing, the request is closed after the chosen number of days.
  - There is a Zia (AI) option that closes the request right after the requester acknowledges.
- **Closing requests associated with Task and Checklist.** It has "Move the request status to [Closed]", with checkboxes "Only when all associated tasks are completed" and "Only when all associated checklists are marked 100% complete". Both are off.

#### Reopen settings

These live in Advanced Portal Settings, under "Request Reopen Settings", and are all view-only here. Current values:

- **Zia:** "Allow Zia to close resolved requests based on requester's reply" is off.
- **On Hold reply:** "Set the status of a request to [Open] when a requester replies in any On Hold status" is off. The "Any of the 'On Hold' statuses" radio is the selected scope.
- **Reply on a completed request:** this is configured as follows.
  - **Status choices:** reopen to Open, Staging or Pending Verification (Open selected).
  - **Time limit:** a window of 1 to 10 days after completion (1 selected).
  - **After the window:** raise a new request, or add the reply to conversations and notify the technician.
  - **Other completed statuses:** add it to conversations (this is the one selected).
- **Technician reopen:** "Allow technicians to reopen the request when a reply is sent by email" is ON. A Zia validation checkbox next to it is off.

#### Data Archive

Setup > Data Administration > Data Archive has one rule: "Request status is [Closed] AND [Closed Date] is before [1 year]". There is an "Exclude Requests" criteria builder and Save and Reset buttons.

- **Status options:** Any Status, Resolved/Closed, Closed, Resolved/Closed/Canceled, Closed/Canceled, Any Completed Status/Canceled.
- **Date fields:** Created Date, Closed Date.
- **Time periods:** 1, 2, 3, 6 months and 1, 2, 3 years.
- Whether archiving is active could not be told from the screen. I did not press Save or Reset.

### Surveys

- **Survey Settings.** "Enable User Survey" is OFF (unchecked). It has a "Customize Template" link for the survey email, and four message boxes:
  - **Messages:** Welcome, Success, Failure and Thanks. All have default text.
  - **Survey Scheduling:** "Send Survey every time" has three options. The first is "When a request is closed". The other two are "After every N requests are closed" and "After every N requests from a requester are closed".
  - **Zoho Survey:** a promotional "Try Now" card for an outside product. I did not click it.
- **Define Survey, Questions tab.** It is empty. The "Add Question" form has one field: Survey Question (free text).
- **Define Survey, Satisfaction Levels tab.** Level 1 Poor, Level 2 Good, Level 3 Excellent. Each has edit and delete icons, plus up and down arrows, and there is an "Add Level" button. The scale runs from bad at the top to good at the bottom.
- **Define Survey, Survey Translation tab.** It is empty. It has New Translation, Disable, Enable and Delete buttons. Columns are Language, Created By, Created On, Updated By and Updated On.
- **Survey Preview.** It shows only a "Please share other comments or suggestions here" box, because there are no questions.
- **Survey Results.** Empty. Columns are Subject, Requester Name, Created Date, Technician, Overall Score, Overall Rating [%] and more.
- **Blocked without mail.** Surveys go out by email, and mail is not configured, so no survey could be sent or answered. I have not tested the survey end to end.

### Mail

- **Mail Server Settings.** The mail server is not configured, and I did not type in or connect anything. The page has an upgrade banner ("Switch and Configure" for the vendor's own mail server). I did not click it.
  - **Incoming:** Server name/IP, User Name, Password, Email Address.
  - **Email Type:** POP (port 110), IMAP (143), POPS (995), IMAPS (993).
  - **Fetch Mails Every:** 2, 5, 15, 30 or 60 minutes.
  - **Accept emails from unknown users:** a checkbox (off).
  - **Outgoing:** Server, Sender's Name, Reply-to Address, Email Type (SMTP 25, SMTPS 465, SMTP with TLS 587), User Name, Password.
  - **Email Request Settings:** "Disable new request creation through email" (off).
  - The page warns that all messages on the polled mailbox are deleted after fetching, so you must use a dedicated mailbox.
- **Mail Filter.** One checkbox, "Match the below rules", with a criteria builder. Matching emails are blocked and no request is created from them. It is off, and I did not turn it on.
- **Email Command.** Off ("Active" unchecked).
  - **Email Subject Contains:** "@@@".
  - **Command Delimiter:** "@@".
  - **Parsing rules:** when active, commands in the email body set request fields.
  - **Example keys:** OPERATION (ADD_REQUEST), CATEGORY, SUBCATEGORY, ITEM, LEVEL, MODE, PRIORITY, URGENCY, IMPACT, GROUP, REQUESTER, REQUESTTYPE, ASSET, TECHNICIAN, REQUESTTEMPLATE, SUBJECT.
  - **Example line:** `@@CATEGORY=Printer@@`. The example text shows how to pick your own subject marker.

### General Settings

#### Advanced Portal Settings

This is the largest settings page. All values below are current and unchanged.

- **Request settings:**
  - "Enable Quick Incident option for technicians": off.
  - "Include technicians in the list of requesters": on.
  - **SLA for service requests:** "Use condition based SLAs" is selected. The other two options are "Use SLA selected by the user" and "Use both" (with an override on conflict).
  - "Show Conversations tab on request details": on.
  - **First response time** can be set when a technician adds a note or replies by email: both off.
  - **Note defaults:** "Show note to requester" and "Email technician for note addition" are both off.
  - **Status-change reason:** "Prompt for a reason when status changes" is on, set To On Hold, and "Mandate reason" is off.
  - "Disable spot edit in the request details page": off.
- **Request ID settings.** Incident and Service Request ID prefixes are blank, so IDs are plain numbers. "Request ID starts with" is 57. It is one counter shared by incidents and service requests.
- **Worklog settings:**
  - "Prevent adding worklog to closed requests, problems, changes or releases": off.
  - "Include non-operational hours in Time Spent": on.
  - "Auto-start worklog timer when owner views the request": off.
- **Technician availability.** Set by system (selected). The other choices are "Set by technician" and "Set by system, but technician can modify".
- **Zoho Directory sync.** If a user is removed in the directory, the system deletes the user (selected). The other option is to disable the login.
- **Approval reminder.** Notify approvers consecutively for 3 operational days when no action is taken for 2 operational days, at 10:00.
- **Change settings:** prefix "CH", next ID 11. Two checkboxes (disable spot edit if a form rule exists; disable operations on a closed change) are both off.
- **Project settings:** prefix "PJT", next ID 7.
- **Release settings:** prefix "RL", next ID 7, plus a spot-edit checkbox (off).

#### Requester Portal

- **Requester Portal Settings tab:**
  - "Enable reminders for requesters": off.
  - "Allow requesters to close their resolved requests": off.
  - "Do not show default request template to requesters": off.
  - "Show incident approvals to requesters": off.
  - "Show only associated assets during request creation": off.
  - "Automatically include requester's assets for email requests": off.
  - "Allow requesters to add recipients when replying": off. A "List recipients from" dropdown is attached, currently "Requesters in same department".
  - "Requester can create requests on behalf of" has six choices: requesters or users in the same department, same site, or all.
  - **Cancel options:** Direct Cancelation, or Notify Technician (selected).
  - **Editor lists:** "When a requester is setting editor, show all" offers all requesters, same site, same department, or service request approvers.
  - **Request editing:** a Yes/No question, then Incidents only, Service Requests only, or both.
  - "Show service and resource cost to": Requesters, Approvers.
  - **Portal search:** modules searched are Announcements, Solutions, Request Templates and Requests, all on.
  - "Allow requesters to edit their profile": on.
- **Requester Portal Customization tab:** one page, "Code-Default", for All Users, builder type "Code based", status on. "New Page" asks for a name, description and builder type, either GUI based or Code based. Pages can be filtered by access level and reordered with Organize.

#### Theme Settings

- "Allow other users to personalize their theme and font" is on.
- **Navigation menu:** Topbar, Sidebar (selected), Sidebar lite.
- **Navigation background:** Charcoal black (selected), Polar white.
- **Preferred colour:** four swatches (blue, teal, purple, red). Blue is selected.
- **Font:** Zoho Puvi (selected), Open Sans, PT Sans, Droid Sans, Fira Sans, Lato, Roboto.
- The same options appear in the personal "Layout Personalization" panel, with a font-size scale and a Light/Dark/System mode.
- **Languages and date formats.** I did not review these, and they were not on this page. The only date format I saw is dd/MM/yyyy in Maintenance Configuration. They belong to Instance Settings (Area 3).

#### Navigation & Footer Settings

- **Technician view:** the tab order is Home (locked), Activities, Requests, Assets, CMDB, Changes, Releases, Reports, Projects, Purchases, Contracts, Alerts and more. Tabs can be dragged, hidden, and grouped under a "More" slider. A Reset link restores the default.
- **Requester view:** Home (locked), Dashboard, Requests, Changes, Projects, Releases, Solutions, Assets.
- **Footer menus:** Latest Updates (locked), Support, Live Chat (locked), Discover Product (the footer lists run right to left).

#### Cloud Attachments

"Allow users to attach files from cloud services" is on. Five services are enabled and can be reordered by drag: Google Drive, One Drive, Dropbox, Evernote and Box. I connected nothing.

#### Approval Settings

This page has a module dropdown (Request is selected).

- **Approval checkboxes (all off):**
  - Mandate comments for all approvals.
  - Notify pending approvers when one has acted.
  - Automatically approve if the approver is [pick users].
  - Automatically approve if the same approver approved at an earlier level.
- **Approval process (all off):**
  - While waiting for approval, stop the timer and set the status to On Hold.
  - When approved, start the timer and set the status to Open.
  - When rejected, set the status to Closed.
  - Restart the approval process of a Service Request after a resource update.

## Behaviour observed in tests

I only read pages in this part. I did not run any create or delete tests.

## Edition notes

- The trial is Enterprise. Survey, Zia options and the Zoho Survey promo card all appear.
- The mail server and the survey email cannot run because mail is not configured.
- The Data Archive screen stayed open without confirming whether it is active.

## Weak spots / confusing UX

- The Impact list mixes scope values (Affects User, Group, Department, Business) with severity values (Low, Medium, High). Nothing stops you picking either style.
- The Priority Matrix is empty but overrides are allowed, so priority is entirely manual.
- The same Settings area exists in two places: reopen rules sit in Advanced Portal Settings, closing rules in Closure Rules, and archive rules in Data Archive.
- The Request Closure Rules radio changes the page on click without saving, which is easy to leave half-set.
- "Advanced Portal Settings" holds unrelated items (reopen, IDs, worklogs, change, project, release, approval reminders), so it is hard to find a setting.
- Maintenance IDs start at 3 and 1, and a template of prefix "RQM" shows up beside blank request prefixes.
- The Reply Template list and the rule-based reply defaults are system-created, so I could not tell which template is used where.

## Test records created

None in this part. The only change today is the housekeeping at the start: the three ZZ business rules and the ZZ trigger switched OFF.

## Limits of this part

- Problem, Change, Project, Release, Solution, Asset, CMDB, Purchase and Contract Management customization (their own statuses, categories and fields) were not opened. They follow the same list-and-form pattern.
- Service Category, the per-module templates (Incident, Problem, Change and so on), Layouts and the Task Layout tab were not reviewed in this part.
- Problem and Change Closure Rules tabs were not opened.
- The Sandbox, Audit Log, System Log, PII/ePHI Log, Telephony Log, Import Data and Export Data pages were not opened (Area 14).
- Languages, date format and time zone (Instance Settings) were not re-read here.
- Mail Filter's criteria builder and the Email Command parser were not exercised, because mail is not configured.

I can continue with part 2 (the module-by-module customization pages and the template groups) or move straight on to Area 14, whichever you prefer.

=== END OF AREA 13 (PART 1) ===
