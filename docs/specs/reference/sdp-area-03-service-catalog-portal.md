# Area 3: Service catalog & self-service portal

## Navigation path
- **Service categories:** Setup > Templates & Forms > Service Category.
- **Catalog view and ordering:** the "Customize Catalog" button on that page opens `ServiceCatalog.do?mode=ServiceCatalogUI`. Technicians see the same page as the normal Service Catalog.
- **Incident templates:** Setup > Templates & Forms > Incident Template.
- **Portal behaviour:** Setup > General Settings > Requester Portal, with two tabs: Requester Portal Settings and Requester Portal Customization.
- **Request-handling globals:** Setup > General Settings > Advanced Portal Settings.
- **Portal preview:** Requester Portal Customization > row gear > Preview. It opens in a new tab at `/app/itdesk/ui/ssp/pages/basic_preview/<pageId>`.
- **Requesters:** Setup > Users & Permissions > Users.

## Screens and what they do
1. **Service Category list.** It holds 8 categories, all enabled, each with a status toggle. The categories are:
   - Corporate Website
   - Email
   - Employee Onboarding
   - Feature Request
   - Internet Access
   - Intranet
   - Payroll
   - VOIP or Telephone
2. **Customize Catalog.** The left pane lists categories, plus a pseudo-category "General Incident Templates" that holds incident templates with no service category. The right pane lists the templates of the selected category. Rows can be reordered by drag handle or by a "move" icon.
3. **Technician-side Service Catalog.** It looks the same, but clicking a template opens a pre-filled New Request form for that template.
4. **Incident Template list.** It shows 9 templates. Columns are name/description, workflow or life cycle, created by, show to requester, and status toggle. A star marks the default template.
5. **Requester Portal Settings.** Behaviour switches for the portal (see Configuration options).
6. **Requester Portal Customization.** A list of portal pages. There is one page, "Code-Default", with access level All Users and builder type Code based, switched on and marked default.
7. **Portal (preview).** Left nav with Home, Requests and Solutions.
   - The Home page has three cards:
     - "I am facing an Issue"
     - "I need something New"
     - "I am looking for Solutions"
   - Home also has a global search box and these widgets:
     - **My Summary:** request counts by state, and task counts.
     - **Announcements:** each with a Follow button.
     - **My Assets:** each with a "Report an issue" button.
8. **"Create a service request" modal (portal).** It has a template search box, a category list (without the General Incident category) and a template list. A "Switch template" link is available on the form.
9. **Post-submit screen.** It says "Request added" with View Request, Create Another Request and Close. View Request opens a read-only details dialog.

## Fields (table: field | type | required | options/values | notes)

**New Service Category dialog (cancelled)**

| Field | Type | Required | Options/values | Notes |
|---|---|---|---|---|
| Icon | image picker | no | "Change" overlay | |
| Name | text | yes | | |
| Description | text | no | | |
| Parent | tree selector | no | default "Home" | allows nested categories |

**New Portal Page dialog (cancelled)**

| Field | Type | Required | Options/values | Notes |
|---|---|---|---|---|
| Page Name | text | yes | | |
| Description | text | no | | |
| Builder Type | select | yes | GUI based, Code based | next step is "Next" |

**Move-template popup**

| Field | Type | Required | Options/values | Notes |
|---|---|---|---|---|
| Position | radio | yes | Before / After | |
| Select Template | dropdown | yes | templates in the category | |

**Service template form, "Request internet access" (technician side)**

| Field | Type | Required | Options/values | Notes |
|---|---|---|---|---|
| Status | dropdown | no | default Open | |
| Priority | dropdown | no | | |
| Requester Name | search | yes | | |
| Assets | picker | no | | |
| Technician | dropdown | no | | |
| Group | dropdown | no | | |
| Subject | text | yes | prefilled by template | |
| Description | rich text | no | prefilled by template | |
| Site | dropdown | no | Base Site | |
| Attachments | file | no | | |
| Resolution | collapsed text | no | | |
| Select the type of operating system | dropdown | template-defined | Linux, Mac OSX, Unix, Windows, Other | custom "Resource Details" field |
| Select the device type | dropdown | template-defined | Desktop, Laptop, Moblie phone (sic), Tablet, Server, Other | custom "Resource Details" field |

**Details dialog (read-only)** shows these fields:
- Request ID, subject, status
- Created date, due-by date, response due date, responded time and completed time
- Created by, department, template, service category, SLA
- Description, resource-detail answers, resolution

## Actions and menus
- **Service Category page:**
  - Toolbar: Customize Catalog, New Service Category, Copy Template, search box, column chooser.
  - Row gear: Edit, Move, Disable, Delete. I did not use any of them.
- **Incident Template page:** New Incident Template, Copy Template.
- **Portal page row gear:** Preview, Edit Details, Configure, Copy, Set as Default, Delete.
- **Portal Customization toolbar:** Access Level filter (All Access Levels), grid/list toggle, New Page, Organize.
- **Requester row menu in Users:** View Associations, Associated Org-Roles, Change as Technician, Edit Requester. There is no "log in as" or impersonate option.
- **Service form buttons:** Add Request, Reset, Cancel.
- **Post-submit buttons:** View Request, Create Another Request, Close.

## Configuration options

**Catalog contents (templates per category)**
- **General Incident Templates:**
  - Default Request
  - Frequent Application Crashes
  - Mail Fetching
  - Maintenance
  - Major Incident Management
  - MIM - RCA
  - New Joinee
  - Printer problem
  - Unable to browse
- **Corporate Website:** Request a CRM account.
- **Email:**
  - Request a new email account creation
  - Request an email client installation
  - Request an increased email storage
  - Request deletion of an email account
  - Request password reset for your email account
- **Employee Onboarding:**
  - Cab Allotment
  - Employee Background Verification
  - Employee Onboarding Preliminary
  - New Employee Onboarding
- **Feature Request:** Raise a new feature request.
- **Internet Access:**
  - Request a file download from an external website
  - Request a VPN account creation
  - Request an online meeting setup
  - Request internet access
  - Request WiFi access
- **Intranet:**
  - Request account deletion from Active Directory
  - Request an account creation in Active Directory
  - Request reset password for an AD Account
- **Payroll:**
  - Request change of place
  - Request to start the process associated to a new hire
  - Request to start the process associated to department change of a user
  - Request to start the process for an employee leaving
- **VOIP or Telephone:**
  - Request a BlackBerry
  - Request a mobile phone for on-call support
  - Request a telephone extension
  - Request an iPhone
  - Request Voice Message Password reset

**Requester Portal Settings (not saved)**
- **Reminders:** reminders for requesters (off).
- **Request checkboxes (all off):**
  - Let requesters close their resolved requests.
  - Hide the default request template from requesters.
  - Show incident approvals to requesters.
  - Show only associated assets during request creation.
  - Auto-include the requester's assets for email-created requests.
  - Let requesters add recipients when replying.
- **Scope dropdowns.** Each defaults to "Requesters in same department".
  - Options: Requesters in same department, Requesters in same site, All Requesters, Users in same department, Users in same site, All users.
  - "List recipients from."
  - "Requester can create requests on behalf of."
  - A third dropdown (the setting-editor "show all" scope) has a slightly different list: Requesters, Requesters in same site, Requesters in same department, Requesters who are service request approvers.
- **Cancellation:** Direct Cancelation, or Notify Technician (selected).
- **Editing:** "Allow requesters to edit their requests" is Yes/No (No selected). If Yes, a scope applies: Incidents Only, Service Requests Only, or Both.
- **Cost display:** show catalog cost to Requesters (off) and to Approvers (on).
- **Portal search scope:** Announcements, Solutions, Request Templates and Requests (all on, drag-orderable).
- **Profile:** "Allow requesters to edit their profile" (on).
- **Buttons:** Save, Reset.

**Advanced Portal Settings (not saved; mostly request-handling globals)**
- Quick Incident for technicians (off).
- Include technicians in the requester list (on).
- **SLA choice for service requests:**
  - Condition-based SLAs only (selected).
  - SLA picked by the user.
  - Both, with an optional "condition-based SLA wins on conflict" box.
- Show the Conversations tab (on).
- First-response time can be set when a technician adds a note or replies from the mail client (both off).
- Note defaults: show note to requester (off), email technician on note (off).
- Prompt for a reason on On Hold or any status change (on), with a separate "mandate reason" box (off).
- Disable spot edit (off).
- Let Zia close resolved requests from a requester's reply (off).
- Set a chosen status when a requester replies.
- **Reopen on email reply:** a choice of reopen and set status, reopen only within 1-10 days (else raise a new request), add to conversations and notify, or always raise a new request.
- The bottom of this page was not fully captured.

## Automation / triggers / rules in this area
- Templates link to workflows, shown as the "Workflow / Life cycle" column on the incident template list. Examples are the onboarding workflow and the Major Incident Management templates. The workflow engine itself is covered in Area 12.
- Nothing fired on the portal-created request (see Behaviour observed in tests).
- Portal visibility has two controls: the per-template "Show to Requester" toggle, and the portal page's access level.

## Behaviour observed in tests
- **Test request #41, "ZZ-CLAUDE-TEST portal service 1".** I created it from the portal using the "Request internet access" template. Requester was Diana Patrick (a demo requester), OS was Linux and device was Laptop.
  - Result: Status Open. Priority, technician, group and SLA were all "Not Assigned". Due dates showed "Not Configured". Created By was the trial admin.
  - So there was no auto-assignment, no SLA, no priority default and no on-screen notification. The mail server is not configured.
- **Portal preview renders as the logged-in technician.** It is not a true requester view. The service form still shows the Requester, Technician and Group fields. The preview tab has an orange "PREVIEW" badge.
- **The portal's "Requests" page is the full technician request list.** It is not filtered to the requester.
- **Requester login is not possible in this trial.** I did not try to log in as a requester.
  - Sample requesters (Benjamin Allen, Bruce Patrick, Bruce Williams, Clark Kingston, Diana Patrick, Henry James, Jean George and others) have Login Name "-" and Email "-".
  - The row menu has no "log in as" option.
  - A real requester login would need new credentials or a user change, which the exploration rules forbid. The Preview is the closest I could get.
- Service-template form behaviour: fields are prefilled from the template (subject, description), and custom "Resource Details" fields appear as a section on the form.
- Portal details dialog: "Resolution" shows "No resolution available" until the request is resolved.
- Setup search for "service template" returned "No matches found".

## Edition notes
- The instance is on the Enterprise plan trial (expires Nov 22, 2026).
- The "Requester Portal Customization" builder with "GUI based" vs "Code based" pages and access levels is available in this plan.
- The instance switcher also lists "ESM Portal" and "ESM Directory". I did not open them.

## Weak spots / confusing UX
- I could not find a single admin screen for editing a service template's layout, approvals and tasks. Setup has no search hit for it, and the Customize Catalog page only reorders templates. Incident templates have their own list; service templates are managed elsewhere (probably from the Service Category or the template itself), and I did not confirm where.
- Portal preview is not a requester view. A product team can't check what requesters actually see without creating a real login.
- Typo in the sample template: "Moblie phone".
- Two almost identical email-reopen settings appear on the Advanced Portal Settings page.
- Portal behaviour settings are split across three places: Requester Portal Settings, Advanced Portal Settings and the Customization tab. Nothing on the screens explains which controls what.
- A service request created from a service template with approvals-style fields got no SLA, priority or technician, so the user must set those by hand. There is no obvious warning.

## Test records created
- **#41** "ZZ-CLAUDE-TEST portal service 1", from the "Request internet access" template.
- Earlier test records (from Areas 2b/2c) are #36 to #40. Nothing was changed in Setup and no real records were touched.

=== END OF AREA 3 ===
