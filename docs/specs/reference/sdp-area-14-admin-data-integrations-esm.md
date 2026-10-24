# Area 14: Admin part 4 (leftovers, Data Administration, Security, Integrations, Apps, ESM, Licence)

Nothing was changed in this area. Every form I opened was cancelled, and no toggles, Save, Enable, Create or Export buttons were used. The only earlier changes were the housekeeping switches (my ZZ business rules and trigger turned OFF).

## Navigation path

The inventory of remaining Setup items, with what I did on each:

| Setup group | Items | Done |
|---|---|---|
| Closure Rules leftovers | Problem, Change tabs | read |
| Instance Configurations | Instance Settings, Currency | read |
| Profile panel | Preferences, Personalize, Accessibility, plan details | read |
| Data Administration | Audit Log, System Log, PII/ePHI Log, Telephony Log, Sandbox, Import Data, Export Data | read |
| Apps & Add-ons | Chat Settings, Analytics Plus, Projects, SMS Settings, Integrations (3 tabs), Zoho Survey, Extensions (Marketplace and My Extensions) | read |
| Developer Space | Custom Menu, Custom Widgets, Custom Functions, Connections, Global Variables, Custom Modules | read |
| Zia | Artificial Intelligence (Area 10), Agents, Chatbot (3 tabs) | read |
| Probes & Discovery | Probe, Credential Library, Domain Scan, Network Scan, SCCM Integration, Settings (4 tabs) | read |
| Users & Permissions | Privacy Settings, Fine-Grained Access | read |
| Left rail menu | Instance switcher, Zoho Directory, ESM Portal, ESM Directory (8 sections) | read |
| Profile panel | My Account | blocked by OTP |

## Screens and what they do

**Closure Rules, Problem tab (all checkboxes unchecked).**
- Mandatory fields: 24 choices, including Resolution, Category, Root Cause, Workaround, Symptoms, Impact and Technician.
- Mandatory conditions: associated tasks closed, at least one change linked, linked changes closed, at least one request linked, all approval levels approved.
- Closure confirmation: prompt for a closure code and comments, or no prompt.
- Optional follow-ups after closing: email technicians and requesters on the linked incidents, copy the resolution and workaround to them, and optionally move them to a chosen status (default Closed).

**Closure Rules, Change tab.**
- A mandatory-field grid for each stage: Submission, Planning, CAB Evaluation, Implementation, UAT, Release, Review and Close.
- "Associated tasks completed" and "all stage approvals approved" are per stage.
- Close stage extras: closure code, close description, associated releases completed, linked child changes completed.
- Additional fields are listed too (Implementation Status, Budget).
- The Release, Purchase Order and Task Closure Rules tabs sit in an overflow menu, which I did not open.

**Instance Settings (edit form opened, then cancelled).**
- Name "the trial instance"; URL name itdesk; type IT HelpDesk, fixed.
- Time zone Pakistan Standard Time, chosen from 315 zones.
- Owner is the sole technician. Access is either "users with permission for this instance" or "everyone in the organization".
- Currency is US Dollar with an Exchange Rates link. Week starts on Sunday, and any day can be chosen.
- The Currency page holds one base currency (USD, rate 1), with New Currency and Configure Exchange Rate buttons.
- Language, date format and time format are not in Instance Settings. They are per user, under Preferences.

**Preferences (per user).**
- Language: 37 options.
- Country: 249 options.
- Date format: 11 options.
- Time format: 9 options.
- Time zone: a per-user override.
- Editor font and size, and an email signature.
- Layout Personalization: Light/Dark/System, sidebar/sidebar-lite/topbar navigation, background, accent colour, font and font scale.
- Accessibility Controls: tabs for Vision, Hearing, Mobility and Learning. The Vision toggles are contrast, reading mask, focus ring, underline links and font size.

**Data Administration.**
- **Audit Log:** it records reads as well as changes ("Accessed Instance Settings", "Modified Trigger (disable)").
  - Each entry has time, operation, object, an internal operation code, who did it with a client icon, a log ID and a "Related Application Logs" link.
  - Filters: a criteria builder (operation, module, user) and a date filter (All, Today, 7 days, 30 days, this/last month, custom).
  - Other controls: two view modes, sort, a download icon (not clicked) and Load More.
- **System Log:** columns are message, module, sub-module, action, type, time and problem.
  - Buttons: Delete, Delete All (not clicked) and Export as XLS or CSV (not clicked).
  - It holds system-side events such as business rule updates, auto-assign on/off, the abort timer and life cycle updates.
- **PII/ePHI Log:** a "This week" filter and an Export button. It has one entry, a technician update performed by "System".
- **Telephony Log:** empty. Columns are caller and receiver numbers and names, module, record ID and time.
- **Sandbox:** a promo page with a "Create Sandbox" button (not clicked). It describes an isolated copy for testing life cycles, workflows, templates, form rules, business rules, SLAs, triggers and custom menus before deploying to production.
- **Import Data:** a wizard with a 3000-record limit.
  - 46 importable modules, including requests, problems, changes, releases, projects, CIs, assets, users, sites, departments, contracts, vendors, purchase orders, tasks, worklogs and custom modules.
  - Four duplicate modes: add and update, update only, delete existing and add, ignore duplicates.
  - Files can be csv, xls or xlsx. Encodings are UTF-8 plus ISO variants. A sample csv is offered.
  - The history tab is empty.
- **Export Data:** up to 3000 records per module as CSV or XLSX, with a history table (empty). The page says to contact support to export everything.
- **Retention periods:** no retention setting for any log is shown. Only the asset scan history cleanup (1, 3, 6, 9 or 12 months) and the data archive rule from Area 13 exist.

**Apps & Add-ons.**
- **Chat Settings:** live chat is powered by Zoho SalesIQ. It has a representative picker (currently only the one technician), a per-group enable, a website embed script (not copied) and an Advanced Settings link out to SalesIQ.
- **Analytics Plus and Zoho Survey:** promo pages with Enable buttons (not clicked).
- **Projects:** a help page that links to project types, status and roles.
- **SMS Settings:** "Mobile Service" (selected, uses each technician's carrier email-to-SMS address) or "SMS Gateway".
- **Integrations:** a catalogue in three tabs, all Disabled, nothing enabled.
  - Third Party: Outlook Actionable Messages, Microsoft Entra ID, Entra ID User Sync, Office 365 Calendar, Microsoft Teams, Jira, Slack, Zapier, Azure OpenAI, ChatGPT, Claude, Google AI Studio, Cloud Telephony, Microsoft Intune, Azure DevOps, WhatsApp.
  - ManageEngine: Mobile Device Manager Plus Cloud, OpManager, Site24x7, Applications Manager, ADManager Plus, Endpoint Central (Cloud and On-Premise), AlarmsOne, SaaS Manager Plus.
  - Zoho: Circuit, Cliq, Flow.
  - Several (OpManager, Site24x7, Applications Manager, Endpoint Central on-premise, Zapier) are enabled from the other product's side, not from here.
- **Extensions:**
  - Marketplace is a filterable catalogue with category, edition, price, rating and deployment-type filters, plus tags such as ServiceDesk Plus Cloud (15) and IT and Administration (9). Entries seen include PAM360, Outlook, AnyCall and Ansible, mostly free and with ratings.
  - "My Extensions" is empty ("No installed Extension available").

**Developer Space (all empty).**
- Custom Menu: choose a module, then New Custom Menu.
- Custom Widgets: onboarding for building a widget with Zoho's extension toolkit (node.js, zet pack/run, developer mode).
- Custom Functions: a "New custom function" button, scoped to module and trigger (business rule, abort timer conditions or workflow actions).
- Connections: Create Connection (outbound OAuth connections for functions).
- Global Variables: groups, with New Group and Delete buttons.
- Custom Modules: a New button, with list columns Display Name, Created By/Time and Last Updated By/Time.

**Zia.**
- Agents: a promo page ("Create Agents", not clicked) for building agents in an Agent Studio that opens in a new tab. They then appear in Ask Zia.
- Chatbot has three tabs:
  - Ask Zia: a toggle, currently OFF, with a "Blended Conversations (Web only)" row.
  - Blended Conversations: only a description, no content.
  - Chatbot Customization: a preview of the portal chat window ("How may I help you today?" with quick actions Create a request, Search solutions and My Open Requests).

**Probes & Discovery (nothing configured, no scan started).**
- Probe: Add Probe, Download Probe, Actions menu. Columns are name, installed host, site, last contact, key and .NET version. Empty.
- Credential Library: New Credential, Delete. Empty.
- Domain Scan, Network Scan and SCCM Integration are empty lists with New buttons.
- Settings has four tabs:
  - General: an invalid service tag list (three defaults: "To Be Filled By O.E.M.", "SERIALNUMBER", "1234567890"), MAC-address identification (currently Disable), computer name format (AD domain name, DNS domain name, or none), an overdue asset scan action (delete the asset or move it to a state, with product-type and advanced criteria) and scan history cleanup.
  - Exclude Devices, by IP, range or name. Empty.
  - Unknown OID: SNMP devices the probe could not identify, so you can assign a type and product. Empty.
  - Scan Script: downloads for a self-scan executable and shell script, and instructions for running it as an AD logon script.

**Security-related pages.**
- Privacy Settings: a GDPR-style data handling feature, not enabled. There is an "Enable privacy settings" button (not clicked).
- Fine-Grained Access (FGA): rules for the Asset and CMDB modules only. The list is empty. The New FGA form has name, description, technicians, product types (selected or all) and an Advanced Criteria builder (column, operator, value). It was cancelled.

**Instances and ESM.**
- The left-rail menu lists instances (one: the trial instance, starred as default). At the bottom are Zoho Directory, ESM Portal and ESM Directory.
- ESM Directory opens a separate console. Its intro says ESM lets you create separate instances per business function, each with its own templates, workflows and users, plus a central portal.
  - Organization Details: org name "itdesk", an org ID, a business address (blank), country, time zone and primary contact email.
  - User Management: Active, Invited and Inactive users. Only the one admin exists. Actions are New, Edit, Change Password, Delete, Import Users, Add/Remove user to an instance. A banner says support for this feature in SDP will end soon and to use Zoho Directory.
  - Custom Domains: verify extra email domains so those users can join without an invitation. Empty.
  - SAML Authentication: configured via IdP login URL, IdP logout URL and an IdP certificate upload. Not configured. There is a "View current SAML configuration" button.
  - Active Directory Settings: a Provisioning App download to sync users from on-premise AD, and a pointer to SAML.
  - Custom Service URLs: branded domains with an SSL status column. Empty.
  - Service Instances: one instance listed, with Go to Instance and Actions (Edit, Delete).
  - ESM Portal: "Customize the Portal" plus Preview and Publish, and a preferred landing page (the ESM portal by default, or a chosen instance).
- The New Instance form (cancelled):
  - Fields: display name, description, service type (ServiceDesk Plus or AssetExplorer), URL name, instance type, owner, time zone, access permissions (everyone in the organization, or by permission) and optional custom service URL.
  - Instance types: IT HelpDesk, Facilities Desk, Finance Desk and HR HelpDesk.
  - So HR or Facilities desks are separate instances created here, not departments inside one instance.

**Licence and plan** (profile panel > "View plan details"; Switch and Buy Now were not clicked).
- Enterprise Plan, trial, expires Nov 22, 2026.
- 10 technicians (1 used), 500 IT assets (22 used), 10 probes (0 used).
- Add-ons: Remote Control (1 licence) and Live Chat (1 of 5 used).
- Edition contents: the in-app comparison sits behind Switch, so I did not open it. The vendor's public help page lists Standard as Help Desk only, Professional as Help Desk plus Asset Management, and Enterprise as Help Desk, Asset Management, ITSM and Project Management. It has no feature-by-feature split and does not say whether it applies to the cloud edition specifically. See [ServiceDesk Plus editions](https://help.servicedeskplus.com/general-features/edition-comparison.html).

## Fields

Only the New FGA form and the New Instance form were opened.

| Field | Type | Required | Options | Notes |
|---|---|---|---|---|
| FGA Name | text | yes | | |
| FGA Description | text | no | | |
| FGA Technicians | multi-select | yes | | |
| FGA Product Type | radio plus multi-select | yes | selected types / all | |
| FGA Advanced Criteria | checkbox plus builder | no | column, operator, value | |
| Instance Display Name | text | yes | | |
| Instance Service Type | tiles | yes | ServiceDesk Plus, AssetExplorer | |
| Instance URL Name | text | yes | | |
| Instance Type | dropdown | yes | IT HelpDesk, Facilities Desk, Finance Desk, HR HelpDesk | |
| Instance Owner | text | yes | | |
| Instance Time Zone | dropdown | yes | | defaults to PKT |
| Instance Access Permissions | dropdown | no | everyone / by permission | |
| Instance Custom Service URL | dropdown | no | | |

## Actions and menus

- Audit Log filters and download; System Log delete and export; PII Log export.
- Import wizard steps; Export Data job button.
- Instance Actions: Edit, Delete. Profile panel: My Account, Personalize, Preferences, Accessibility, Organize Navigation Tabs, Switch (edition), Buy Now.

## Configuration options

- Per-user language, date, time and time zone.
- Instance-level time zone, week start and currency.
- Discovery settings (service tags, MAC identification, computer name format, overdue assets, scan history cleanup).
- The full list of integration toggles is above.

## Automation / triggers / rules in this area

- The overdue asset scan action is the only automation: delete an asset, or move it to a state, when it hasn't been scanned for N days.
- Closure rules (above) act as mandatory-field and condition gates.
- Custom Functions are the intended extension hook for business rules, abort timers and workflow actions.

## Behaviour observed in tests

- Reading a page is logged in the Audit Log, so viewing configuration leaves a trail.
- The "Setup search" box matches page names only. Searching "API", "security", "mobile" or "key" returned "No matches found".
- Selecting a radio in Closure Rules (Area 13) reverted on reload because it was never saved.
- No scan, import, export or sandbox was started.

## Edition notes

- The trial is on Enterprise. Add-ons Remote Control and Live Chat are separate licences.
- The Marketplace and most integrations are visible on this plan.
- Whether Sandbox, ESM and Custom Modules are Enterprise-only is not shown in the UI; check the vendor's comparison.

## Weak spots / confusing UX

- Several vital admin controls live outside the product: security, 2FA, sessions and domain policy in Zoho Accounts and Zoho Directory, and chat advanced settings in SalesIQ. The ESM Directory screens carry an end-of-support notice and point users to Zoho Directory.
- "My Account" demands an emailed one-time code, and the code goes to the owner's mailbox. This is a hard stop for automated review.
- The sidebar scroll resets after every page load, so deep pages are hard to reach.
- Language and date format are hidden under per-user preferences, not instance settings.
- No retention setting for the audit, system or PII logs is visible.
- Export is capped at 3000 records, and the exports are only for supported modules.
- There is no setup page named for API keys, security policy, IP restriction, data masking or encryption, and no mobile app settings page.

## Test records created

None in this area.

## Limits of this area

- **My Account** (sessions, 2FA, IP allow-list, app passwords): not seen because it asks for an email code, so it is untested.
- **Security items:** not found inside SDP Setup: IP restrictions, data masking, encryption, session or login policy, API key or OAuth console, mobile app settings.
  - API keys: the only technician-API item visible is the integration catalogue.
  - Mobile: the profile panel shows only iOS and Android store icons.
  - Encryption: not observable.
- **Edition comparison:** the in-app feature matrix was not opened (behind Switch); the public help page was the substitute.
- **Not opened or not clicked:** Closure Rules overflow tabs (Release, Purchase Order, Task). Enable/Create buttons were deliberately skipped: Privacy settings, Sandbox, Analytics, Zoho Survey, Create Agents, Customize the Portal. I did not click the audit-log download, System Log Delete/Export, Chat Advanced Settings or any integration toggle.
- **List of Setup pages never opened across all areas:** I can only confirm what I opened in this area. The earlier detailed lists were compacted, so for Areas 1-13 treat this as best effort. What I know was not opened: the Release, PO and Task Closure Rules tabs. Please confirm against your own Area 1-13 notes whether Delegation, Technician/Asset Auto Assign, Layouts and Approval Settings were opened.

Sources: [ServiceDesk Plus editions](https://help.servicedeskplus.com/general-features/edition-comparison.html)

=== END OF AREA 14 ===
