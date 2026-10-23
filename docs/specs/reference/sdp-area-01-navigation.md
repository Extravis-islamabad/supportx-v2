# Area 1: Navigation & global UI

I did not create, edit or save anything in this area. Two caveats: the browser viewport stayed at about 814×609 even after I resized the window, so some panels were read from the page structure instead of screenshots. Items I could not fully open are listed at the end of the Weak spots section.

## Navigation path
- Home is at `/app/itdesk/HomePage.do`.
- The product is ServiceDesk Plus Cloud, in the Enterprise plan trial, with 30 days left (expires Nov 22, 2026).
- Everything in this area is reached from the left rail, the top header icons, the profile drawer and the Home page.

## Screens and what they do

**Layout shell.** A dark left rail holds the modules. A top header carries the instance name (chosen by the trial admin when the trial was set up) and an icon strip. A blue trial banner shows days left, a Buy Now button and a sales phone number, plus a Quick Setup button. Bottom-right there is a floating chat bubble. A bottom-right strip of four small icons gives Feedback, Live Chat, Support and Latest Updates. A hamburger at top-left opens an instance switcher (lists instances, star marks the default) with an "ESM Portal" link at the bottom.

**Left rail modules** (17 links, in this order; the narrow window collapsed the last ones under "More"):
1. Home
2. Ask Zia
3. Activities
4. Requests
5. Assets
6. CMDB
7. Changes
8. Releases
9. Reports
10. Projects
11. Purchases
12. Contracts
13. Alerts
14. Problems
15. Solutions
16. Maintenance
17. More (a tab that holds the overflow items)

There is no separate Service Catalog or Setup link in the rail. Setup is the gear icon in the header, and the Service Catalog is reached from the "Raise a request" panel.

**Header icons** (left to right):
- **Search.** Opens an inline search bar with a module selector.
- **New Request (ticket-plus icon).** Opens a "Raise a request" side panel with New Incident, Service Catalog, a template search box and a list of template groups.
- **Quick Actions (lightning icon).** A creation and navigation launcher, described below.
- **Recent Items (clock icon).** A right drawer, empty in this trial.
- **Approvals (checklist icon).** A "My Pending Approvals" drawer, empty here.
- **Notifications (bell with a count badge).** A right drawer with a search box, grouped by date (Today), an on/off toggle at the top and a three-dot menu. It held two system messages ("Started populating sample data" and "Sample Data Populated!"), each with an unread dot.
- **Setup (gear icon).** Goes to the admin home.
- **Profile (avatar with a green presence dot).** Opens the profile drawer.

**Global search.**
- A scope dropdown picks the module: Requests, Archived Requests, Problems, Changes, Projects, Releases, Asset, Consumable, Software, Purchase, Contracts, Solutions, System Log, Users, CMDB, Maintenance.
- Typing in the box opens a "Narrow down your search" helper with field-prefixed search, for example "request id", "status", "requester" and "created date after/before/between", plus a "More…" expander and a help icon.
- For Requests the expanded field list covers about 80 searchable fields: Additional Fields, Approval Status, Attachment Name, Category, Completed Date (with After/Before/Between variants), Created By, Department, Due By, Emails To Notify, FCR (first call resolution), Group, Impact, Impact Details, Incident SLA, Incident Template, Item, Last Updated By, Level, Merged Request Id, Mode, On Behalf Of User, Priority, Request Contents, Request ID, Request Type, Requester, Resolved Time, Responded Date, Response Due Date, Scheduled Start/End Time, Service Category, Service Request SLA, Service Template, Site, Status, Sub Category, Subject, Tags, Technician and Urgency. Most date fields come in four forms (exact, after, before, between).
- I tested a plain search for "printer" in Requests. It went to the Requests list with a "Search in" bar showing "All Active Requests" and a filter chip "All Fields printer", with Add and Clear buttons. It returned "No Matches found", so searching reuses the list view with an editable search-criteria bar.

**Quick Actions drawer** has these groups:
- **New** (with shortcuts): Add Quantity, Allocate, Announcement (Ctrl+Alt+A), Asset, Change (Ctrl+Alt+C), Consumable, Contract, Maintenance for Change, Maintenance for Request, Maintenance for Task, Problem (Alt+P), Product, Project (Ctrl+Alt+P), Purchase Order, Release (Ctrl+Alt+R), Requester (Alt+U), Software License, Solution (Alt+S), Technician (Alt+J), Vendor.
- **Schedule:** Scheduler, Tech Availability Chart, Online Technicians, Broadcast Message, Mark Unavailability.
- **Tasks:** My Tasks, All Tasks, New Task (Ctrl+Alt+T).
- **Reminders:** My Reminder(s), Add Reminder.
- **Assets:** Manage Groups, New Group, Asset Allocation Details.
- **Problem Prediction:** Run Prediction, View Predictions.
- **Others:** Go to Request (Alt+R), My Assets, Audit Assets.

**Profile drawer** has these parts:
- Name and email, with My Account and Personalize links.
- iOS and Android app icons.
- Sign out.
- A Display Mode picker: Light, Dark or System.
- Preferences.
- Accessibility Controls.
- Organize Navigation Tabs.
- Edition Details, which shows the Enterprise Plan, a Switch link, expiry date, "View plan details" and Buy Now.

**Organize Navigation Tabs** is a right drawer that lists the rail modules.
- Each module has a drag handle to reorder it.
- An eye icon shows or hides it.
- Home has a lock icon, so it is fixed and cannot be hidden or moved.
- A reset-to-default icon sits at the top.
- Save and Cancel buttons sit at the bottom.
- I opened it and pressed Cancel.

**Preferences dialog** has three tabs:
1. **Layout Personalization** (options below).
2. **Personalize.** Language (English shown), Country, Date Format, Time Format, Time Zone, Rich-text editor style (font and size) with a Reset Default link, and a personal Email Signature rich-text editor. Save and Cancel at the bottom.
3. **Accessibility Controls** (also reachable from the profile drawer), with four sub-tabs:
   - Vision: Increase Contrast, Reading Mask, Focus Ring, Underline Links, Display Font Size (percentage with Reset).
   - Hearing: Screen Reader (Cmd+F5) and Skip to Main Content.
   - Mobility: Keyboard Shortcuts (on/off with a View Shortcuts link), Page Navigator, Reduce Motion (Standard/Reduced), Hover Item, Emphasize Focus Area, Click-to-Drag Mode (for the template builder, favourites and column chooser), Custom Cursor, Custom Scrollbar.
   - Learning: Highlight Critical Information (IDs and contacts in a distinct colour), Toast Message Duration.

**Home page.** Six tabs run across the top, with a My Summary side tab on the right edge:
- Dashboard
- Scheduler
- Tech Availability Chart
- Tasks
- Reminders
- Announcements (under a "…" overflow menu)

**My Summary side panel** shows personal counters with links to the filtered lists:
- Requests: Overdue, Due Today, Pending, Awaiting Update.
- Problems: Pending, Unassigned.
- Changes: Approved, Unapproved.

**Dashboard tab.**
- A dashboard selector with a search box, a Favorites section (star toggle on each entry) and Canned Dashboards: Activities, Asset, Change, Contract, Problem, Project, Purchase, Release, Helpdesk (the default), Software and Zia.
- Filters for site and technician group.
- A full-screen toggle.
- A gear for settings.
- A Copy Dashboard button.
- A New button.
- The Helpdesk dashboard is a scrolling stack of widgets (list below).

**Scheduler tab.** A month calendar with prev/next arrows and three filters: Site, Group, Technician (technician defaulted to me). It shows scheduled work on a calendar.

**Tech Availability Chart tab.** A technician-by-day grid for the month. It has filters for Site, Group and Technician. Cell colour and numbers show workload per day. A legend explains Company Holiday, Weekends, Online Technicians, Offline Technicians, Leave and Non-Leave.

**Tasks tab** ("All Tasks" view).
- Toolbar: Add Task, Delete, Close, Trigger; a Quick Add button; list/detail view toggle; paging.
- Each row shows status, priority, owner and scheduled end time. A Module column shows what the task belongs to (General, Release, Milestone), plus a Module Id.

**Reminders tab.**
- Toolbar: New Reminder, Delete, "Modify Reminder State To".
- Columns: Reminder Summary, Reminder Date, Module, Link.
- Three sample reminders exist.

**Announcements tab.**
- Toolbar: New Announcement, Delete.
- Each row shows creator, banner flag, start date, end date, announcement type, views and followers.
- Three sample announcements exist.

**Other pages.**
- **Ask Zia** is a marketing/enablement page (details in Edition notes).
- **Activities** is a "My Pending Activities" list. A "Showing" dropdown (All Activities), a filter icon, New Incident and New Task buttons, a list/card/column-style view switcher and a column chooser. Each row shows an associated module (Milestone, General) with status and priority.
- **Getting Started / Quick Setup page** (`/ui/gettingstarted`). I landed here by accident from a click; I changed nothing. Content is summarised under Edition notes.

## Fields (table: field | type | required | options/values | notes)
Area 1 has no data-entry forms apart from Preferences and the (unsaved) dashboard and widget forms, so those are what I list here.

| field | type | required | options/values | notes |
|---|---|---|---|---|
| Display Mode | 3 cards | no | Light / Dark / System | Also in the profile drawer |
| Navigation Menu | segmented | no | Sidebar / Sidebar lite / Topbar | Controls how the module menu is laid out |
| Navigation Background | segmented | no | Charcoal black / Polar white | |
| Preferred Color | swatches | no | Blue / Teal / Purple / Maroon | |
| Font Type | dropdown | no | Zoho Puvi (others not opened) | |
| Font Size | slider | no | 5 sizes with Reset | |
| Language | dropdown | no | English (list not opened) | Personal setting |
| Country | dropdown | no | Pakistan (shown) | |
| Date Format | dropdown | no | e.g. "Oct 23, 2026" | |
| Time Format | dropdown | no | e.g. "Oct 23, 2026 05:..." | |
| Time Zone | dropdown | no | (GMT +05:00) Pakistan Standard Time | |
| Rich text editor style | font + size | no | Zoho Puvi shown | Preview box below it |
| Email Signature | rich text | no | free text | Personal signature |
| Dashboard Name | text | yes | free | New dashboard form |
| Dashboard Description | text | no | free | |
| Executive Dashboard | checkbox | no | on/off | Has a shield icon and an info tooltip, which suggests a special or premium type; I did not open the tooltip |
| Access Level | toggle | no | Private / Public | Dashboard default is Private; new graph widget defaults to Public |
| Widget column | 4 cards | no | Two / Four / Six / Eight columns | Layout of the dashboard grid |
| Widget Name | text | yes | free | New widget form |
| Module | dropdown | yes | Requests (default); full list below | New widget form |
| Data Filter | filter row | no | "-- Select Filter --", add/remove rows with +/− | Rows can be dragged to reorder |
| Graph Type | dropdown | no | Pie (default), Dial, Area, Bar, Doughnut, Line, others below the fold | |
| Group by | dropdown | yes | field list for the module | |
| Display Format | dropdown | yes | Number (default) | Other formats not opened |
| Refresh Frequency | dropdown | no | "Never" (default) | Dashboard settings gear |
| Enable SmartView | toggle | no | on (default) | Dashboard settings gear |

## Actions and menus (every button and menu item, what it does)
- **Hamburger:** opens the instance list and the ESM Portal link.
- **Search icon:** opens the inline search; the module dropdown narrows scope; Enter runs the search and opens the module list view with the criteria bar.
- **New Request icon:** the "Raise a request" panel offers New Incident, Service Catalog and a template search. The template groups listed are General Incident Templates, Corporate Website, Email, Employee Onboarding, Feature Request, Internet Access, Intranet, Payroll and VOIP or Telephone.
- **Quick Actions:** see the groups above; most entries are links to "add" forms.
- **Recent Items, Approvals, Notifications:** right-side drawers that open and close on click.
- **Setup gear:** goes to the admin home.
- **Profile drawer:** My Account, Personalize, Sign out, Preferences, Accessibility Controls, Organize Navigation Tabs, Switch plan, View plan details, Buy Now.
- **Quick Setup button:** opens the Getting Started page.
- **Bottom-right strip:** Feedback, Live Chat, Support, Latest Updates.
- **Dashboard toolbar:** dashboard selector, Copy Dashboard, site and group filters, full screen, settings gear (Refresh Frequency, SmartView), New (new dashboard).
- **Customize drawer (from the new-dashboard builder):** Layout Customization (column count, access level), Select Widgets (source type, module, search, checkboxes), a New button for creating widgets, Update Layout, Cancel.
- **Tasks tab toolbar:** Add Task, Delete, Close, Trigger, Quick Add.
- **Reminders toolbar:** New Reminder, Delete, Modify Reminder State To.
- **Announcements toolbar:** New Announcement, Delete.

## Configuration options (every setting and its possible values)

**Layout and appearance.**
- Display Mode: Light, Dark, System.
- Navigation Menu: Sidebar, Sidebar lite, Topbar.
- Navigation Background: Charcoal black, Polar white.
- Preferred Color: Blue, Teal, Purple, Maroon.
- Font Type and Font Size, plus Reset.

**Personal settings.** Language, Country, Date Format, Time Format, Time Zone, editor style and email signature.

**Accessibility toggles:**
- Increase Contrast
- Reading Mask
- Focus Ring
- Underline Links
- Display Font Size (percentage)
- Screen Reader
- Skip to Main Content
- Keyboard Shortcuts (on/off)
- Page Navigator
- Reduce Motion
- Hover Item
- Emphasize Focus Area
- Click-to-Drag Mode
- Custom Cursor
- Custom Scrollbar
- Highlight Critical Information
- Toast Message Duration

**Dashboards.**
- Selectable canned dashboards: 11, listed above.
- Per-dashboard options: private or public, favourite star, copy, refresh frequency, SmartView.
- The empty-state tiles of the builder describe: widgets from all modules in one place, grouping up to 10 widgets per group, private/public access, and configurable widget columns.

**Widget sources** (the first dropdown in the Customize drawer): Canned Widgets, Graph Widgets, Info Widgets, Report Widgets, Table Widgets, URL Widgets.

**New widget types** (the New menu): Info, Graph, Table, URL.

**Widget modules** (the second dropdown): Asset, Changes, CMDB, Contracts, Problems, Projects, Purchases, Releases, Requests, Software, Solutions. I saw the top and middle of this list; the very end may hold more entries I did not scroll to.

**Graph widget form:** Name, access level, module, data filter rows, graph type, group by, display format, with a Preview link and Add Widget and Back buttons.

**Canned Requests widgets** (about 36 shown for the Requests module):
- FCR Compliance Requests By Category / Group / Priority / Technician
- FCR Violated Requests By Category / Group / Priority / Technician
- Unassigned and Open Requests
- Open Requests by Category / Level / Mode / Priority
- Requests Last Month / Last Week / This Month / This Week
- Requests Approaching SLA Violation
- Requests completed in last 20 days
- Requests received in last 20 days
- Requests by Technician / Category / Level / Mode / Priority
- SLA Violated Requests
- SLA Violation by Category / Group / Level / Priority / Technician

**Helpdesk Dashboard default widgets** (as loaded):
- Requests by Technician (table of Open, OnHold and OverDue counts)
- Open Requests by Mode
- Requests Last Week
- SLA Violation by Technician
- Requests Approaching SLA Violation
- SLA Violated Requests
- Unassigned and Open Requests
- Open Requests by Priority
- Requests received in last 20 days
- Requests completed in last 20 days

**Keyboard shortcuts** (the list is available from Accessibility, Mobility, View Shortcuts, or by pressing Shift+/):
- Go to Home: g then h. Go to Requests: g then r.
- Search: `/`. Go to Request: Alt+R.
- New Announcement: Ctrl+Alt+A. New Change: Ctrl+Alt+C. New Problem: Alt+P. New Project: Ctrl+Alt+P. New Release: Ctrl+Alt+R. New Requester: Alt+U. New Solution: Alt+S. New Technician: Alt+J. New Task: Ctrl+Alt+T. New Incident: Alt+W.
- List view: open the Views menu with v, search in the list with s.
- Details page: Edit with e, Print Preview with Shift+P, previous/next with the arrow keys.
- On a request details page: Assign a, Pick up i, Reply r, Forward f, Link Requests l, Close c, New Task nt, Add Note nn, Add Worklog nw. Tab jumps: Request Details or, Tasks ot, Resolution os, Approvals oa.

## Automation / triggers / rules in this area
- None are configurable in this area.
- The only automation-like items are dashboard auto-refresh frequency (default Never) and SmartView (default on).
- "Problem Prediction" (Run Prediction, View Predictions) appears in Quick Actions, which points to an ML feature (see Area 10).

## Behaviour observed in tests (what happened when you created ZZ-CLAUDE-TEST records)
- I created no records, as nothing in this area required it.
- Search runs on Enter and moves you to the module list with a visible, editable criteria bar. An empty result shows "No Matches found" with the list toolbar still visible.
- Side drawers close when you click elsewhere or press Escape. Clicking an icon while a drawer is closing can be ignored, so a second click is needed.
- Opening the new-dashboard form puts the page into an inline "create" mode with confirm (✓) and cancel (✗) icons and no save until you confirm. I left it without saving by reloading the page.
- The new graph widget defaults to Public while the new dashboard defaults to Private.

## Edition notes
- The trial is on the Enterprise Plan (selected from the onboarding answers, switchable during the evaluation), expiring Nov 22, 2026.
- Ask Zia is not enabled by default. Its page describes four sample uses (raise a ticket, find similar tickets, a help centre, analytics) and has an "Enable Ask Zia" button, which I did not press. Once enabled it is added to the navigation bar.
- The Getting Started page also lists: a sample-data-loaded notice, a support email address (not yet activated), a "Visit Portal" link for the self-service portal, instance settings (logo, name), team invites with an email-verification prompt, a Personalize link, and AI sections ("Explore AI Features", "Try Zia Chatbot").
- The "Executive Dashboard" checkbox carries a shield badge and an info icon, so it is likely a plan-restricted option. I did not open it, so this is unconfirmed.
- The Problem Prediction items in Quick Actions look like an ML add-on, but I did not confirm their edition status.

## Weak spots / confusing UX (where a competitor could do better)
- **Discoverability of modules.** Seventeen modules are fixed in a vertical rail, and on a laptop-sized window half of them hide behind "More", which did not open reliably for me. Service Catalog and Setup are not in the rail at all.
- **Two sets of preferences.** The profile drawer repeats Preferences, Accessibility and Navigation Tabs, and Accessibility appears again inside Preferences. The "Personalize" link and the "Preferences" entry overlap.
- **Search needs knowledge of field names.** The helper lists many field-prefixed filters but doesn't show them as visual chips. A beginner has to learn the syntax, and the scope selector is easy to miss.
- **Search lands on a different screen.** A global search replaces the current page with the list view, which loses your place on Home.
- **Dashboard creation is heavy.** A new dashboard requires opening a side drawer, choosing a widget source, a module and then ticking widgets one by one. There are two creation paths for widgets (the drawer selection and the "New" menu), which is confusing.
- **Drawers that toggle.** Recent Items, Approvals and Notifications close if you click their icon again while they are animating, which looks like a lost click.
- **Mixed visibility defaults** (private for dashboards, public for widgets) are easy to overlook.
- **Empty states.** Recent Items and Approvals show large illustrated empty states, but nothing explains what populates them.
- **Not verified:** the contents of the three-dot menu and the toggle in the Notifications drawer, the full Language, Font Type and Display Format option lists, what the Executive Dashboard checkbox does, the "Alerts", "Maintenance" and other modules' landing pages (those belong to later areas), and the hover/tooltip text on the footer icons.

## Test records created (names and IDs, so they can be cleaned up later)
None. No ZZ-CLAUDE-TEST records were created in this area. I opened the new-dashboard form and the new Graph Widget form but never saved either, and I made no changes to preferences, navigation tabs or notifications.

=== END OF AREA 1 ===
