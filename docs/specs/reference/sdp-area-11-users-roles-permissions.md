# Area 11: Admin part 1 (users, roles, groups, structure, access)

Everything here is view-only. I opened forms and cancelled; nothing was saved or changed.

## Navigation path

- **Setup > Users & Permissions:** Roles, Users, User Groups, Technician Groups, Fine-Grained Access (an Asset view and a CMDB view), Privacy Settings. Direct URLs use `AdminDetails.cc?forwardTo=<key>`: `user`, `role`, `userGroupsDef`, `queues` (technician groups), `AssetFineGrainAccess`, `CMDBFineGrainAccess`.
- **Setup > Instance Configurations:** Instance Settings (`portaldetail`), Regions (`location`), Sites (`site`), Operational Hours, Holiday Groups, Unavailability Types, Departments, Currency, Organization Roles.
- **Setup > Data Administration > Import Data** (`dataImport`, the Import Wizard) and **Setup > Probes & Discovery > Domain Scan** (`domain`) are the only import-type screens near users.
- **Reports > All Reports** holds the sharing choice (Public or Private).
- Clicking some sidebar items (User Groups, Fine-Grained Access) can leave the previous page's user list under the new title. Reloading the direct URL shows the real page.

## Screens and what they do

1. **Users list.** One grid for technicians and requesters.
   - A view menu (All Users, Requesters, Technicians) and a "User category" filter (All, Login Users, Non-Login Users, Pending Users).
   - A page-size selector (10, 25, 50, 75, 100), a column chooser, and a search.
   - Columns: Name, User Type, Login Name, Email, Department, Employee ID, Phone, Job Title, Mobile, Site, First Name, Last Name.
   - Buttons: New Requester, New Technician, Actions.
   - This instance has 21 users: 7 technicians and 14 requesters. Only the account owner has a login name; the 20 sample users have none. A shield icon marks VIP users (Bruce Williams, Clark Kingston).
2. **New Technician / Edit Technician form.** Described under Fields.
3. **New Requester / Edit Requester form.** Described under Fields.
4. **Roles list.** 20 roles with a short description each, plus "New Role". Each row has icons for delete, edit and "Technicians with the role". Delete and edit are greyed out for every built-in role except SDSiteAdmin, so no role in this instance is deletable. Role names are not clickable.
5. **New Role form.** A permission matrix plus an advanced section (see Fields).
6. **User Groups.** Empty list in this instance. A group is a saved filter over users, not a hand-picked member list.
7. **Technician Groups.** Tabs for Active Groups and Inactive Groups, filtered by site. It shows 13 active groups on Base Site, and a note that the groups are also linked to 3 more sites. The groups are App Development, Data Management, Development, Hardware Problems, Hosting Team, Infra-SSO, Internet, Maintenance, Major Incident Team, Network, Onboarding, Printer Problems and Software.
8. **Fine-Grained Access (FGA).** Separate lists for Asset and CMDB. Both are empty. Each row would be a name, a set of technicians, and a scope.
9. **Regions.** One region, USA.
10. **Sites.** Four sites: Base Site, DataCenter FL, HeadQuarters NY, IDC SA. None is linked to a region.
11. **Departments.** Seven, filtered by site: ERP, Infrastructure, IT Services, Finance, Sales, Engineering, Administration. The department head is empty on all of them.
12. **Organization Roles.** A tree with five levels (see Fields). Each role has an "Associate User" slot, and some allow only one user.
13. **Instance Settings.** A read-only summary (see Fields).
14. **Import Wizard.** Described under Fields.
15. **Domain Scan.** A list (empty) with a New Domain form. It discovers computers, not user accounts.
16. **Privacy Settings.** A single "Enable privacy settings" button under a banner about handling personal data under privacy regulations such as GDPR. It is off, and I did not click it.

## Fields

**New Technician form** (type, required):

| Field | Type | Required | Notes |
|---|---|---|---|
| Name (Display Name) | text | no | Optional display override. |
| First Name | text | yes | Has an inline helper icon. |
| Last Name, Employee ID | text | no | |
| Email | text | yes | Used as the primary email and as the login name. Must be filled before login can be enabled. |
| Phone, Mobile | text | no | |
| SMS Mail ID | text | no | Email-to-SMS address, for example `1234567890@carrier`. |
| Cost Per Hour | number | no | Currency shown in USD. |
| Site Name | picker | no | Defaults to Base Site. |
| Department Name | picker | no | |
| Job title | text | no | |
| Reporting Manager | user picker | no | |
| Sites Association | multi-picker | no | Starts with Base Site. |
| Groups Association | multi-picker | no | Technician groups. |
| Enable login for this technician | checkbox | no | Cannot be ticked until an email is entered. |
| VIP User | checkbox | no | |
| Organization Roles | section | no | "No User level role has been configured". |

When login is enabled, these appear:

- **Login Name:** taken from the email.
- **A note on Zoho accounts:** the user must already exist in the Zoho organisation, or be invited by the organisation admin, and accept the invitation before they can sign in.
- **Enable Administrator Privileges (SDAdmin):** a checkbox.
- **Enable administrator privileges for the selected sites (SiteAdmin):** a checkbox.
- **Enable Custom Privileges:** a two-pane picker, "Available Roles" to "Assigned Roles".
- **Available roles:** the 20 roles listed under Roles.
- **Project Role:** a drop-down with Project Admin, Project Manager, Team Leader and Team Member.
- **Subscription Manager:** a checkbox.
- **Request Approver:** a checkbox.
- **Purchase Order Approver:** a checkbox.
- **Can view technician's cost per hour:** a checkbox.
- **A licence-upgrade option:** a checkbox I could see in the page code but not on screen.

**New / Edit Requester form:**

- **Basic fields:** Name (Display Name), First Name (required), Last Name, Employee ID, Description.
- **Contact:** Email, Phone, Mobile.
- **Placement:** Site, Department, Job Title, Reporting Manager.
- **Enable Self-Service Login:** a checkbox that cannot be turned on without an email.
- **View Permissions** (drop-down): Own Requests, Own Site Requests, All Requests.
- **View Requests of Direct Reportees:** a checkbox.
- **VIP User:** a checkbox.
- **Organization Roles:** same section as the technician form.
- **Change as Technician:** a row-menu action that promotes a requester.

**Role permission matrix** (rows by columns Full Control, View, Add, Edit, Delete):

- **Module rows:** Requests, Problems, Changes, Releases, Inventory, Purchase, Contract, Solutions, CMDB.
- **Other Configurations:** Reports.
- **Maintenance:** Request Maintenances, Change Maintenances, Task Maintenances.
- **Announcement:** View is ticked and locked by default.

**Advanced permissions** (collapsed section, all checkboxes, grouped by module):

| Group | Permissions |
|---|---|
| Requests, Add | Adding/Editing Request Task, Adding Requester, Adding Request Checklist |
| Requests, Edit | Resolving Request, Allow Stop Timer, Merging Requests, Modifying Due Time, Modify Resolution, Reopening Request, Closing Request, Assigning Technician, Editing Requester, Modify Approvers, Editing Closed Requests, Cancel Requests, Editing Request Checklist, Manage Followers, Share Request |
| Requests, Delete | Editing/Deleting Others Notes, Editing/Deleting Own Notes, Deleting Others Time Entry, Deleting Email Responses From Users, Deleting Request Task, Deleting Request Checklist |
| Requests, View | Allow task technician to access the request, Allow technicians in the task group to access the request, Allow technicians to access their direct reportees' requests |
| Problems, Edit | Adding/Editing Problem Approvals, Adding/Editing Problem Tasks, Modify Analysis Details, Modify Solution Details, Delete Problem Approvals, Delete Problem Tasks, Editing/Deleting Others Notes |
| Purchase | Add: Adding New Product, Adding New Vendor, Adding New Vendor Service. Edit: Cancel Purchase Order |
| Contracts | Edit: Cancel Contract |
| Worklog (requests, problems, changes, releases) | View, Add, Edit, Delete Worklog |
| CMDB | Add: Create Baselines. Delete: Delete Baselines |
| General | Allow technician to approve solutions; Allow technician to export data from list view |

**Scope setting on every role, "Allow technicians to view":** the choice is "All Module Data" or "Module Level Granular Permissions". The granular option shows a grid for Requests, Problems, Changes and Other Modules, with three columns:

- All in associated sites
- All in group and assigned to technician
- Assigned to technician

**Role names, in effect, as listed with their descriptions:**

| Role | What it grants |
|---|---|
| AnnouncementConfig | Full control over announcements |
| AssetConfig | Customise asset fields, configure probes and discovery, notifications |
| ContractConfig | Configure vendors, notifications, contract fields |
| HelpdeskConfig | Customise helpdesk fields, templates, SLAs, business rules, notifications, closure rules, maintenance tasks, technician auto-assign, data archive |
| ProjectConfig | Customise project fields, templates, triggers, notifications, tasks, custom functions, webhooks, types, status, roles |
| PurchaseConfig | Configure currency, products, vendors, notifications, purchase fields |
| SDAdmin | Mandatory admin role; cannot be edited or deleted |
| SDAssetAuditAdmin | Asset audit privileges |
| SDAssetAuditor | Asset audit scan privileges |
| SDAssetManager | Asset manager |
| SDChangeManager | Change manager |
| SDCMDBAdmin | CMDB admin |
| SDCMDBManager | CMDB and relationships access |
| SDCo-ordinator | Coordinator access |
| SDGuest | Self-service portal access for associated requesters |
| SDMaintenanceManager | Maintenance manager |
| SDReleaseManager | Prerequisite for a technician to be assigned as release manager |
| SDRemoteControl | Remote control of computers |
| SDReport | Permission to generate reports |
| SDSiteAdmin | Administrative rights for the technician's associated sites; editable |

**SDSiteAdmin as configured** (the only role whose checklist opens):

- **Requests:** View, Add, Edit and Delete ticked, Full Control not ticked.
- **Problems, Changes, Releases, Inventory, Purchase, Contract:** Full Control ticked on all.
- **Solutions:** View, Add, Edit, Delete.
- **CMDB:** nothing.
- **Reports, the three Maintenance rows, and Announcement:** Full Control.
- **Advanced section:** most items are unticked, including Resolving, Closing, Merging and Assigning. The role grants the module-level rows but does not tick those task-level boxes.

**Technician group form** (New or Edit Group):

- **Name:** required text.
- **Site:** fixed to the selected site.
- **Technicians:** required multi-picker.
- **Group notifications:** checkboxes for "a new request is added", "a request is left unpicked", and "a request is updated", with a warning that the global group notifications must be enabled under Notification Rules.
- **Description:** text.
- **Group Mail Settings:** Group Email (comma separated, must be unique and aliased to the incoming mail account), Sender's Name, Sender's Email.
- **Organization Roles:** assign role.

**User Group form:** Name, Description, Set Filters (required). The filter columns are Department, Email, Job Title, Organization Roles, Site, User, VIP User and User Additional Fields, each with an operator, plus a Preview.

**FGA form** (Asset or CMDB): Name, Description, Technicians, and a scope. Asset scope is "Select Product Types" or "All Product Types". CMDB scope is "Select CI Types" or "All CI Types". There is also an "Advanced Criteria" tick that adds column and operator rows.

**Region form:** Region Name, Description, Organization Roles.

**Site form:**

- **Site Details:** Name, Description, Region, Time Zone, Language.
- **Address:** Door Number, Street, Landmark, City, State/Province, ZIP, Country.
- **Contact:** Email, Phone, Fax, Web URL.
- **Related Settings** (Departments, Technician Groups, Business Rules, Service Level Agreements): for each, choose how to configure it: copy from the default site, refer to settings, or custom.
- **Technicians / Site Association:** a picker.
- **Organization Roles.**
- **Note:** site-based business rules and SLAs apply to requests automatically.

**Department form:** Name, Site, Department Head, Description, Organization Roles.

**Organization Roles tree:**

| Level | Roles |
|---|---|
| Organization | CEO, CFO, CIO, COO, General Manager |
| Region | Regional Incharge, Regional Manager |
| Site | Site Incharge, Site Manager |
| Department | Department Approver, Department Incharge, Department Head |
| Group | Group Head |
| User | Reporting Manager |

CEO accepts one associated user only. A "+" adds a role at a level and a gear opens a role's settings.

**Instance Settings:** the instance name (the trial instance), URL name (`itdesk`), instance type (IT HelpDesk), time zone (Pakistan Standard Time), owner (the account email), access permissions ("users with permission for this instance"), currency (US dollar, with an Exchange Rates link), and start day of the week (Sunday).

**Import Wizard:**

- **Limit:** at most 3,000 records per import.
- **Modules:** Attachments, Conversations, Worklog, Solutions, Purchase Order, Contracts, Vendor, Custom Modules, Users, Regions, Sites, Departments, Technician Groups, Category, GL Code, Cost Center, Tasks, Task Comments, Requests (with tasks, problems, conversations), request, change and task maintenances, Changes, Releases, Projects (members, comments, milestones), Configuration Items, CI Relationships, Asset, Consumable details, and Software Licenses.
- **Modes:** add records and update if they exist; update if they exist; delete existing and add; ignore duplicate records.
- **File format:** csv, xls or xlsx.
- **Character encoding:** UTF-8 and the ISO-8859 series.
- **Aids:** a sample-CSV download per module, an Import History tab, and a Next button that leads to field mapping.
- **Not opened:** I did not choose a file or press Next.

**Domain Scan form:** Probe Name, Exclude Devices, Domain Name, Domain Controller, Login Name, Password, Use SSL, Base DN, Description, and a software-scan option for Linux, Mac and AIX. The Base DN note says the probe collects all computers matching `objectClass=Computer`. I did not fill it in or add a domain.

## Actions and menus

- **Users list, Actions menu:** Assign Approval Permissions, Mark as VIP user, Assign Project Role, Assign Department. These work on ticked rows, and I ticked rows without choosing any of them.
- **Row menu, technician:** View Associations, View FGA Associations, Associated Org-Roles, Manage Sites and Groups, Edit.
- **Row menu, requester:** View Associations, Associated Org-Roles, Change as Technician, Edit Requester.
- **Technician groups:** a Delete button, a pencil per row, and an Active/Inactive split.
- **Departments:** New Department and Delete, with row selection.
- **Deactivate vs delete users:** I could not find either action. There is no Delete or Deactivate on the list, the bulk Actions menu, the row menus, or the edit forms. Group deactivation exists only as the Active/Inactive group tabs. Whether a user can be removed from some other screen is unconfirmed.

## Configuration options

- **Scope of what a technician can see:** the role scope grid (sites, group, assigned) plus site and group association on the user.
- **Requester visibility:** Own, Own Site, or All requests, plus direct reportees.
- **Fine-grained access** narrows asset or CMDB visibility by product type or CI type, with optional criteria.
- **Logins:** per-user checkboxes only. I found no password policy, session timeout, SSO or SAML, or two-factor screen in Setup. Searching Setup for SSO and login returns nothing, and the Setup index has none. Sign-in appears to be handled by Zoho Accounts outside this product, which I did not open.
- **Mail Server Settings** exist but mail is not configured, so invitations cannot be sent from here.
- **Privacy Settings** is a single on/off for personal-data handling, currently off.
- **Technician auto-assign (round-robin or load balancing):** no such option on the group form. It sits under Setup > Automation > Technician Auto Assign, which is Area 12.

## Automation / triggers / rules in this area

- Group notifications depend on global notification rules.
- Site-based business rules and SLAs apply automatically to requests at that site.
- Organization roles feed approvals and escalations: Reporting Manager, Department Head and similar can be used as approvers.
- Importing users in bulk is manual through the wizard. I found no directory (LDAP or AD) user sync.

## Behaviour observed in tests

- Login cannot be ticked on a new technician until an email is typed. With the email filled, the login section expands. Same rule for requester self-service login.
- The advanced "Module Level Granular Permissions" radio reveals the scope grid immediately.
- Built-in roles cannot be opened: their pencil and trash are disabled and the names do nothing. Only SDSiteAdmin opens in an edit form.
- The Setup index dropdown and sidebar can show stale content (see Weak spots).
- Report sharing (left from Area 9): the Save Report dialog offers Public or Private only, plus the folder. A report's list row shows "Public" under Accessibility. There is no sharing by role, group or user. Folder rows show owner, count, and an "Access to Dashboard" column. Who can create or edit reports comes from the Reports row of a role's matrix and the SDReport role. The Report Settings tab only holds display defaults (column widths, date format, link and group options, and the placeholder for empty values).
- Dashboards (from Area 9): private or shared per dashboard, not by role.

## Edition notes

- Zoho-hosted sign-in is why there is no password, SSO or session settings page.
- Self-service login and technician login both rely on Zoho accounts and invitations, which need a mail setup.
- Privacy Settings, FGA and organisation roles are all available on this Enterprise trial.
- The Domain Scan form needs a probe, and discovery is off limits here.

## Weak spots / confusing UX

- Sidebar links for User Groups and Fine-Grained Access first show the Users grid under the wrong heading until you reload the page.
- Built-in roles are not viewable at all, so an admin cannot see what SDAdmin or SDChangeManager actually grant without trial and error.
- The "login" checkbox silently does nothing when the email is empty; there is no error message.
- Role names like HelpdeskConfig and SDAdmin mix two naming styles.
- There is no visible way to deactivate or delete a user, and no user-group member list (only a dynamic filter).
- Technician groups are per site, which is easy to miss because the "also associated with 3 more sites" banner is small.
- Pagination on the users grid starts at 10 with a hidden "..." total control.
- The Setup search found nothing for SSO or login, so admins looking for them get a dead end.

## Limits of this area

- I could not read the permission checklist of the 19 locked built-in roles. Only their descriptions and the full permission universe (from the New Role form) are documented, and SDSiteAdmin's ticks.
- I did not open every group to compare members, and I did not read individual users' role assignments through the "Technicians with the role" icons.
- I did not open Zoho Accounts, so Zoho-side password, session and SSO settings are unverified.
- The licence-upgrade checkbox was only seen in the page code.
- Dashboard sharing is as recorded in Area 9; I did not reopen the dashboard editor here.

## Test records created

None. The New Technician, New Requester, role, group, FGA, region, site, department, domain and import screens were opened and abandoned unsaved. In the New Technician form I typed the name "ZZ-CLAUDE-TEST" and the address zz-claude-test@example.invalid, then left the page without saving; no email was sent. I ran my own ZZ-CLAUDE-TEST report once to reach its Save dialog and cancelled it, so the report is unchanged.

=== END OF AREA 11 ===
