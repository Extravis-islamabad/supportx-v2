# 02 — Service requests, service catalog and self-service portal

Parity requirements for service request management and the service catalog (architecture.md
§2.2) and for the requester self-service portal (architecture.md §2.15, §9.1). Rules, ID scheme
and field meanings: [README.md](README.md).

**Status:** Draft v0.1, 2026-10-24, for product owner review. **Owner:** Haider (Product Owner).

## Scope of this file

- **REQ-SR-*** are service request requirements: how a service request differs from an
  incident. That covers approvals before fulfilment, fulfilment tasks and plans, cost and
  delivery estimates, requests on behalf of others, several items in one order, and closing
  with the requester's confirmation. The approval engine is built once in `work_items`
  (REQ-INC-083 says so); its full behaviour (stages, rules, email links, delegation, reminders)
  is specified here and every work item type reuses it.
- **REQ-CAT-*** are service catalog requirements: categories, catalog items, item forms, who
  can see an item, approval, SLA, fulfilment and cost settings per item, publishing, versions
  and search (module `service_catalog`).
- **REQ-PRT-*** are requirements for the requester self-service portal shell (the `portal`
  app, architecture §9.1): home, search, my requests, approvals inbox, announcements,
  branding, languages, accessibility, guest options, the chat entry point and the portal
  settings an admin controls.
- **Inherited, not repeated.** A service request is a work item. Everything in file 01 applies
  to it unchanged unless a requirement here says otherwise: the engine (REQ-WI-001 to 025),
  notes, conversations, worklogs, tasks, checklists, attachments, reminders, linking, merge,
  closure codes, reopen, lists, views, bulk actions, the record page, notifications and AI on
  records (REQ-INC-*). REQ-SR-002 lists this inheritance so it can be tested.
- **The requester's side of an incident** is in file 01 (REQ-INC-028, REQ-INC-147,
  REQ-INC-148). This file adds the portal shell around it and the service request side.
- **Not in this file:**
  - The SLA engine, operating hours, auto-assignment, business rules, visual workflows and
    the notification engine (file 03). This file says how a service request *uses* them.
  - The knowledge base itself (file 08); the portal only shows it (REQ-PRT-010).
  - Report and dashboard building (file 09); catalog figures feed it (REQ-CAT-030).
  - AI administration, the assistant's models, actions and scripted conversations (file 10);
    the portal entry point is here (REQ-PRT-028, REQ-PRT-029).
  - Users, requesters, organisation roles, user groups, surveys, sign-in and security
    settings, and announcement authoring (file 11).
  - Connectors (Teams, Slack, identity, email) and department desks themselves (file 12).
  - Assets and purchase (file 07); a request only links to them.
- **Monitoring is out of scope** (ADR-017, D-001). Nothing in this file polls, monitors or
  correlates alerts.

## Words used in this file

| Word | Meaning |
|---|---|
| Service request | A work item of type `service_request`: a person asks for something (access, a device, a change to an account), as opposed to reporting that something is broken. |
| Catalog item | One thing a requester can ask for, with its own form, approvals, SLA, fulfilment plan and price. ServiceDesk Plus calls it a service template. |
| Service category | A node in the catalog tree that groups catalog items. |
| Requested by / requested for | The person who submits the request, and the person it is for. They are the same person unless someone asks on behalf of another (REQ-SR-011). |
| Approval | A set of one or more stages that must succeed before fulfilment starts. |
| Stage | One step of an approval with its own approvers and decision rule. |
| Decision rule | How a stage's approvers decide: any one, all, majority, or first answer. |
| Fulfilment | The work that delivers what was asked for: tasks, a workflow or automated actions. |
| Fulfilment plan | The tasks (with order, owners and conditions) a catalog item creates on its requests. |
| Order | One submission that holds several catalog items, from a cart or a bundle (REQ-SR-013). |
| Bundle | A catalog item that stands for several other items, requested with one form (REQ-CAT-023). |
| Audience | The people allowed to see and request a catalog item (REQ-CAT-015). |
| Portal | The requester self-service web app, separate from the technician console. |

## Requirement summary

<!-- summary:start -->
**Counts by decision and priority**

| Decision | MVP | V1 | LATER | Total |
|---|---|---|---|---|
| SAME | 33 | 26 | 10 | 69 |
| BETTER | 26 | 11 | 0 | 37 |
| NEW | 1 | 14 | 4 | 19 |
| SKIP | 0 | 0 | 2 | 2 |
| **Total** | **60** | **51** | **16** | **127** |

Edition (lowest edition that includes it): Essentials 91, Professional 32, Enterprise 4. By prefix: REQ-SR 62, REQ-CAT 32, REQ-PRT 33.

| ID | Title | Decision | Priority | Edition |
|---|---|---|---|---|
| [REQ-SR-001](#req-sr-001--service-request-is-its-own-work-item-type) | Service request is its own work item type | BETTER | MVP | Essentials |
| [REQ-SR-002](#req-sr-002--service-requests-inherit-the-engine) | Service requests inherit the engine | SAME | MVP | Essentials |
| [REQ-SR-003](#req-sr-003--service-request-fields) | Service request fields | SAME | MVP | Essentials |
| [REQ-SR-004](#req-sr-004--default-life-cycle-for-service-requests) | Default life cycle for service requests | BETTER | MVP | Essentials |
| [REQ-SR-005](#req-sr-005--priority-is-never-left-blank-on-a-new-request) | Priority is never left blank on a new request | BETTER | MVP | Essentials |
| [REQ-SR-006](#req-sr-006--sla-chosen-by-the-item-or-by-rules) | SLA chosen by the item or by rules | SAME | MVP | Essentials |
| [REQ-SR-007](#req-sr-007--sla-clock-waits-for-approval) | SLA clock waits for approval | SAME | MVP | Essentials |
| [REQ-SR-008](#req-sr-008--assignment-from-the-catalog-item) | Assignment from the catalog item | SAME | MVP | Essentials |
| [REQ-SR-009](#req-sr-009--service-request-lists-views-and-columns) | Service request lists, views and columns | SAME | MVP | Essentials |
| [REQ-SR-010](#req-sr-010--technicians-raise-requests-from-the-catalog) | Technicians raise requests from the catalog | SAME | MVP | Essentials |
| [REQ-SR-011](#req-sr-011--request-on-behalf-of-someone-else) | Request on behalf of someone else | SAME | MVP | Essentials |
| [REQ-SR-012](#req-sr-012--request-for-several-people-at-once) | Request for several people at once | NEW | LATER | Professional |
| [REQ-SR-013](#req-sr-013--order-several-items-at-once) | Order several items at once | NEW | V1 | Professional |
| [REQ-SR-014](#req-sr-014--quantity-on-a-request) | Quantity on a request | NEW | V1 | Professional |
| [REQ-SR-015](#req-sr-015--needed-by-date-and-expected-delivery) | Needed-by date and expected delivery | BETTER | V1 | Essentials |
| [REQ-SR-016](#req-sr-016--request-again) | Request again | NEW | V1 | Essentials |
| [REQ-SR-017](#req-sr-017--service-requests-from-email) | Service requests from email | BETTER | V1 | Essentials |
| [REQ-SR-018](#req-sr-018--scheduled-recurring-service-requests) | Scheduled recurring service requests | SAME | LATER | Essentials |
| [REQ-SR-019](#req-sr-019--converting-to-and-from-incidents) | Converting to and from incidents | SAME | V1 | Essentials |
| [REQ-SR-020](#req-sr-020--links-to-purchase-requests-and-orders) | Links to purchase requests and orders | SAME | LATER | Professional |
| [REQ-SR-021](#req-sr-021--approval-before-fulfilment) | Approval before fulfilment | SAME | MVP | Essentials |
| [REQ-SR-022](#req-sr-022--approver-by-name-or-the-requesters-manager) | Approver by name or the requester's manager | BETTER | MVP | Essentials |
| [REQ-SR-023](#req-sr-023--no-approval-waits-on-nobody) | No approval waits on nobody | BETTER | MVP | Essentials |
| [REQ-SR-024](#req-sr-024--everyone-involved-sees-the-approval-progress) | Everyone involved sees the approval progress | BETTER | MVP | Essentials |
| [REQ-SR-025](#req-sr-025--approve-or-reject-in-the-app) | Approve or reject in the app | SAME | MVP | Essentials |
| [REQ-SR-026](#req-sr-026--approve-by-email-with-safe-one-time-links) | Approve by email with safe one-time links | BETTER | MVP | Essentials |
| [REQ-SR-027](#req-sr-027--segregation-of-duties-in-approvals) | Segregation of duties in approvals | BETTER | MVP | Essentials |
| [REQ-SR-028](#req-sr-028--reasons-and-comments-on-decisions) | Reasons and comments on decisions | SAME | MVP | Essentials |
| [REQ-SR-029](#req-sr-029--multi-stage-approvals) | Multi-stage approvals | BETTER | V1 | Professional |
| [REQ-SR-030](#req-sr-030--parallel-approval-stages) | Parallel approval stages | NEW | V1 | Professional |
| [REQ-SR-031](#req-sr-031--approvers-from-roles-groups-and-form-fields) | Approvers from roles, groups and form fields | SAME | V1 | Professional |
| [REQ-SR-032](#req-sr-032--conditional-approval-stages) | Conditional approval stages | BETTER | V1 | Professional |
| [REQ-SR-033](#req-sr-033--automatic-approval-rules) | Automatic approval rules | SAME | V1 | Professional |
| [REQ-SR-034](#req-sr-034--approval-reminders-and-escalation) | Approval reminders and escalation | SAME | V1 | Essentials |
| [REQ-SR-035](#req-sr-035--delegate-approvals) | Delegate approvals | SAME | V1 | Essentials |
| [REQ-SR-036](#req-sr-036--backup-approvers) | Backup approvers | SAME | V1 | Essentials |
| [REQ-SR-037](#req-sr-037--ask-for-clarification) | Ask for clarification | NEW | V1 | Essentials |
| [REQ-SR-038](#req-sr-038--approve-by-replying-to-the-email) | Approve by replying to the email | SAME | V1 | Essentials |
| [REQ-SR-039](#req-sr-039--approve-on-the-mobile-app) | Approve on the mobile app | SAME | V1 | Essentials |
| [REQ-SR-040](#req-sr-040--approve-in-teams-and-slack) | Approve in Teams and Slack | SAME | LATER | Essentials |
| [REQ-SR-041](#req-sr-041--restart-approval-after-a-relevant-change) | Restart approval after a relevant change | SAME | V1 | Essentials |
| [REQ-SR-042](#req-sr-042--technicians-adjust-a-running-approval) | Technicians adjust a running approval | SAME | V1 | Essentials |
| [REQ-SR-043](#req-sr-043--what-an-approver-can-see) | What an approver can see | SAME | V1 | Essentials |
| [REQ-SR-044](#req-sr-044--approval-steps-in-visual-workflows) | Approval steps in visual workflows | BETTER | V1 | Professional |
| [REQ-SR-045](#req-sr-045--ai-approval-suggestions) | AI approval suggestions | SAME | LATER | Professional |
| [REQ-SR-046](#req-sr-046--fulfilment-tasks-from-the-catalog-item) | Fulfilment tasks from the catalog item | BETTER | MVP | Essentials |
| [REQ-SR-047](#req-sr-047--ordered-and-parallel-fulfilment-steps) | Ordered and parallel fulfilment steps | BETTER | V1 | Professional |
| [REQ-SR-048](#req-sr-048--conditional-fulfilment-tasks) | Conditional fulfilment tasks | SAME | V1 | Essentials |
| [REQ-SR-049](#req-sr-049--tasks-capture-data-for-later-steps) | Tasks capture data for later steps | NEW | V1 | Professional |
| [REQ-SR-050](#req-sr-050--fulfilment-tasks-for-people-outside-the-service-desk) | Fulfilment tasks for people outside the service desk | SAME | V1 | Professional |
| [REQ-SR-051](#req-sr-051--fulfilment-progress-the-requester-can-follow) | Fulfilment progress the requester can follow | BETTER | MVP | Essentials |
| [REQ-SR-052](#req-sr-052--cost-on-a-request) | Cost on a request | SAME | V1 | Professional |
| [REQ-SR-053](#req-sr-053--fulfilment-workflow-on-a-request) | Fulfilment workflow on a request | SAME | V1 | Professional |
| [REQ-SR-054](#req-sr-054--stop-a-fulfilment-workflow-with-a-record) | Stop a fulfilment workflow with a record | BETTER | V1 | Professional |
| [REQ-SR-055](#req-sr-055--automated-fulfilment-actions) | Automated fulfilment actions | NEW | LATER | Professional |
| [REQ-SR-056](#req-sr-056--hand-over-an-asset-on-fulfilment) | Hand over an asset on fulfilment | SAME | V1 | Professional |
| [REQ-SR-057](#req-sr-057--orchestration-across-department-desks) | Orchestration across department desks | SAME | LATER | Enterprise |
| [REQ-SR-058](#req-sr-058--fulfilled-when-the-work-is-done) | Fulfilled when the work is done | BETTER | MVP | Essentials |
| [REQ-SR-059](#req-sr-059--requester-confirms-receipt-then-auto-close) | Requester confirms receipt, then auto-close | SAME | MVP | Essentials |
| [REQ-SR-060](#req-sr-060--rejected-requests) | Rejected requests | BETTER | MVP | Essentials |
| [REQ-SR-061](#req-sr-061--withdraw-a-request-awaiting-approval) | Withdraw a request awaiting approval | BETTER | MVP | Essentials |
| [REQ-SR-062](#req-sr-062--requesters-follow-their-service-requests) | Requesters follow their service requests | SAME | MVP | Essentials |
| [REQ-CAT-001](#req-cat-001--service-categories-in-a-tree) | Service categories in a tree | SAME | MVP | Essentials |
| [REQ-CAT-002](#req-cat-002--catalog-items) | Catalog items | BETTER | MVP | Essentials |
| [REQ-CAT-003](#req-cat-003--incident-templates-in-the-catalog) | Incident templates in the catalog | SAME | MVP | Essentials |
| [REQ-CAT-004](#req-cat-004--one-admin-page-per-catalog-item) | One admin page per catalog item | BETTER | MVP | Essentials |
| [REQ-CAT-005](#req-cat-005--copy-move-disable-and-retire-items) | Copy, move, disable and retire items | SAME | MVP | Essentials |
| [REQ-CAT-006](#req-cat-006--item-content-in-every-language) | Item content in every language | BETTER | MVP | Essentials |
| [REQ-CAT-007](#req-cat-007--starter-catalog-for-a-new-tenant) | Starter catalog for a new tenant | SAME | MVP | Essentials |
| [REQ-CAT-008](#req-cat-008--questions-on-the-item-form) | Questions on the item form | SAME | MVP | Essentials |
| [REQ-CAT-009](#req-cat-009--lookups-to-my-assets-people-and-records) | Lookups to my assets, people and records | SAME | V1 | Professional |
| [REQ-CAT-010](#req-cat-010--repeating-rows-on-a-form) | Repeating rows on a form | SAME | V1 | Essentials |
| [REQ-CAT-011](#req-cat-011--form-rules-on-item-forms) | Form rules on item forms | BETTER | V1 | Essentials |
| [REQ-CAT-012](#req-cat-012--guidance-and-related-articles-on-an-item) | Guidance and related articles on an item | SAME | V1 | Essentials |
| [REQ-CAT-013](#req-cat-013--no-admin-scripts-in-item-forms) | No admin scripts in item forms | SKIP | LATER | Essentials |
| [REQ-CAT-014](#req-cat-014--show-or-hide-an-item-from-requesters) | Show or hide an item from requesters | SAME | MVP | Essentials |
| [REQ-CAT-015](#req-cat-015--audience-rules-per-item-and-category) | Audience rules per item and category | SAME | V1 | Professional |
| [REQ-CAT-016](#req-cat-016--approval-settings-per-item) | Approval settings per item | SAME | MVP | Essentials |
| [REQ-CAT-017](#req-cat-017--sla-per-item) | SLA per item | SAME | MVP | Essentials |
| [REQ-CAT-018](#req-cat-018--fulfilment-group-per-item) | Fulfilment group per item | SAME | MVP | Essentials |
| [REQ-CAT-019](#req-cat-019--fulfilment-plan-per-item) | Fulfilment plan per item | SAME | MVP | Essentials |
| [REQ-CAT-020](#req-cat-020--price-and-cost-per-item) | Price and cost per item | BETTER | V1 | Professional |
| [REQ-CAT-021](#req-cat-021--charge-back-information) | Charge-back information | NEW | V1 | Professional |
| [REQ-CAT-022](#req-cat-022--quantity-and-request-limits-per-item) | Quantity and request limits per item | NEW | V1 | Professional |
| [REQ-CAT-023](#req-cat-023--bundles) | Bundles | NEW | V1 | Professional |
| [REQ-CAT-024](#req-cat-024--draft-preview-publish-and-retire) | Draft, preview, publish and retire | BETTER | MVP | Essentials |
| [REQ-CAT-025](#req-cat-025--item-versions) | Item versions | NEW | V1 | Professional |
| [REQ-CAT-026](#req-cat-026--optional-second-person-check-before-publishing) | Optional second-person check before publishing | NEW | LATER | Professional |
| [REQ-CAT-027](#req-cat-027--order-and-featured-items) | Order and featured items | SAME | MVP | Essentials |
| [REQ-CAT-028](#req-cat-028--catalog-search) | Catalog search | BETTER | MVP | Essentials |
| [REQ-CAT-029](#req-cat-029--business-and-technical-catalog-views) | Business and technical catalog views | SAME | V1 | Professional |
| [REQ-CAT-030](#req-cat-030--catalog-figures) | Catalog figures | NEW | V1 | Professional |
| [REQ-CAT-031](#req-cat-031--export-and-import-catalog-items) | Export and import catalog items | NEW | LATER | Enterprise |
| [REQ-CAT-032](#req-cat-032--catalogs-per-customer-msp) | Catalogs per customer (MSP) | SAME | LATER | Enterprise |
| [REQ-PRT-001](#req-prt-001--portal-application-and-navigation) | Portal application and navigation | SAME | MVP | Essentials |
| [REQ-PRT-002](#req-prt-002--portal-home) | Portal home | BETTER | MVP | Essentials |
| [REQ-PRT-003](#req-prt-003--one-search-box-for-everything) | One search box for everything | BETTER | MVP | Essentials |
| [REQ-PRT-004](#req-prt-004--browse-the-catalog) | Browse the catalog | BETTER | MVP | Essentials |
| [REQ-PRT-005](#req-prt-005--submit-a-request-in-the-portal) | Submit a request in the portal | SAME | MVP | Essentials |
| [REQ-PRT-006](#req-prt-006--after-submitting-say-what-happens-next) | After submitting, say what happens next | BETTER | MVP | Essentials |
| [REQ-PRT-007](#req-prt-007--my-requests) | My requests | SAME | MVP | Essentials |
| [REQ-PRT-008](#req-prt-008--approvals-inbox) | Approvals inbox | SAME | MVP | Essentials |
| [REQ-PRT-009](#req-prt-009--announcements-in-the-portal) | Announcements in the portal | SAME | MVP | Essentials |
| [REQ-PRT-010](#req-prt-010--knowledge-in-the-portal) | Knowledge in the portal | SAME | MVP | Essentials |
| [REQ-PRT-011](#req-prt-011--my-assets) | My assets | SAME | V1 | Professional |
| [REQ-PRT-012](#req-prt-012--pending-surveys) | Pending surveys | SAME | V1 | Essentials |
| [REQ-PRT-013](#req-prt-013--profile-and-preferences) | Profile and preferences | SAME | MVP | Essentials |
| [REQ-PRT-014](#req-prt-014--other-records-in-the-portal) | Other records in the portal | SAME | LATER | Professional |
| [REQ-PRT-015](#req-prt-015--requester-reminders) | Requester reminders | SAME | LATER | Essentials |
| [REQ-PRT-016](#req-prt-016--tenant-branding-and-domains) | Tenant branding and domains | SAME | MVP | Essentials |
| [REQ-PRT-017](#req-prt-017--home-layouts-per-audience) | Home layouts per audience | BETTER | V1 | Professional |
| [REQ-PRT-018](#req-prt-018--no-code-based-portal-pages) | No code-based portal pages | SKIP | LATER | Essentials |
| [REQ-PRT-019](#req-prt-019--navigation-and-footer-links) | Navigation and footer links | SAME | V1 | Essentials |
| [REQ-PRT-020](#req-prt-020--languages-and-right-to-left-in-the-portal) | Languages and right-to-left in the portal | BETTER | MVP | Essentials |
| [REQ-PRT-021](#req-prt-021--accessible-portal) | Accessible portal | BETTER | MVP | Essentials |
| [REQ-PRT-022](#req-prt-022--mobile-first-portal) | Mobile-first portal | NEW | MVP | Essentials |
| [REQ-PRT-023](#req-prt-023--the-portal-loads-fast-on-a-phone) | The portal loads fast on a phone | NEW | V1 | Essentials |
| [REQ-PRT-024](#req-prt-024--requester-sign-in) | Requester sign-in | SAME | MVP | Essentials |
| [REQ-PRT-025](#req-prt-025--self-registration) | Self-registration | SAME | V1 | Essentials |
| [REQ-PRT-026](#req-prt-026--public-knowledge-and-announcements-without-sign-in) | Public knowledge and announcements without sign-in | NEW | V1 | Essentials |
| [REQ-PRT-027](#req-prt-027--guest-requests-with-email-verification) | Guest requests with email verification | NEW | V1 | Essentials |
| [REQ-PRT-028](#req-prt-028--assistant-as-the-portal-entry-point) | Assistant as the portal entry point | BETTER | V1 | Essentials |
| [REQ-PRT-029](#req-prt-029--assistant-settings-for-the-portal) | Assistant settings for the portal | SAME | V1 | Essentials |
| [REQ-PRT-030](#req-prt-030--live-chat-with-the-service-desk) | Live chat with the service desk | SAME | LATER | Essentials |
| [REQ-PRT-031](#req-prt-031--one-page-of-portal-settings) | One page of portal settings | BETTER | MVP | Essentials |
| [REQ-PRT-032](#req-prt-032--preview-the-portal-as-a-chosen-person) | Preview the portal as a chosen person | BETTER | MVP | Essentials |
| [REQ-PRT-033](#req-prt-033--department-desks-in-one-portal) | Department desks in one portal | SAME | LATER | Enterprise |
<!-- summary:end -->

---

## 1. The service request record

#### REQ-SR-001 — Service request is its own work item type

A service request is a work item of type `service_request` with its own ID counter and prefix
(SR-1, SR-2 ...), its own default life cycle (REQ-SR-004), its own SLA family and a form that
comes from a catalog item. Every service request has a catalog item; the item decides the
form, approvals, fulfilment plan, SLA and price.

- **Decision:** BETTER. In ServiceDesk Plus a service request is an incident record with an
  optional request type and a shared counter, and the form title says "incident" even on a
  service template. Our type is explicit and always tied to its catalog item.
- **Source:** sdp-area-02b §Fields (request type), §Weak spots; sdp-area-13 §Advanced Portal Settings (shared ID counter); architecture §2.2, §6.2; D-045
- **SDP weak spot fixed:** the request type is optional yet decides behaviour, and incidents
  and service requests share one unprefixed counter.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. The first service request in a new tenant is SR-1; incidents keep their own counter.
  2. A service request cannot be created without a catalog item; the API refuses it with a
     field error.
  3. The create form and record page title name the type and the catalog item, never
     "incident".

#### REQ-SR-002 — Service requests inherit the engine

Everything file 01 specifies for incidents applies to service requests unless a requirement
in this file says otherwise. This covers the engine requirements (REQ-WI-001 to 025) and the
incident behaviour for notes, conversations, worklogs, tasks, checklists, attachments,
reminders, followers, linking, merge and undo merge, cancel and reopen, closure codes, lists,
views, bulk actions, the record page, notifications, AI on records and the mobile app.

- **Decision:** SAME. One engine gives the same behaviour on every type (REQ-WI-001).
- **Source:** architecture §6.2; sdp-area-02c §Actions (service request actions match incident actions); REQ-WI-001
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. The shared engine contract test suite (REQ-WI-001 AC1) passes for the service request
     type.
  2. Every incident action in file 01 that is not overridden here is available on a service
     request with the same permission and the same action state rules.
  3. Service request events use the same event contract shape as incident events, with the
     type `service_request`.

#### REQ-SR-003 — Service request fields

On top of the shared work item fields (REQ-INC-001), a service request has:

- catalog item and its version (REQ-CAT-025), and the service category;
- requested by and requested for (REQ-SR-011);
- the answers to the item's form questions, shown as their own section;
- quantity (REQ-SR-014);
- approval status (not needed, pending, approved, rejected, withdrawn) and the current stage;
- fulfilment progress (done and total fulfilment steps);
- needed-by date and expected delivery date (REQ-SR-015);
- estimated cost and actual cost (REQ-SR-052);
- the parent order, if the item was part of one (REQ-SR-013).

- **Decision:** SAME. ServiceDesk Plus has service category, template, approval status,
  service cost and total cost on requests; we add fulfilment progress and delivery dates.
- **Source:** sdp-area-02a §Screens (columns Approval Status, Service Category, Service Cost, Total Cost, Template); sdp-area-03 §Fields (service template form, details dialog); sdp-area-02b §Fields (scheduled start time)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A service request created from an item with two questions shows both answers in an
     "item details" section of the record, labelled in the viewer's language.
  2. Approval status and fulfilment progress update live on the record and in lists when an
     approver decides or a task completes.
  3. Every field listed is available as a list column and a filter (REQ-SR-009).

#### REQ-SR-004 — Default life cycle for service requests

A new tenant gets a ready-made service request life cycle (Appendix A). It adds two statuses
to the incident set: "awaiting approval" (paused category, entered only by the system) and
"rejected" (closed category, entered only by an approval rejection). "Resolved" is labelled
"fulfilled" for service requests. Allowed transitions, reasons and automatic moves follow
REQ-INC-044 to 052. Admins can change the life cycle per catalog item with the life cycle
designer (REQ-INC-049).

- **Decision:** BETTER. ServiceDesk Plus has no service request life cycle out of the box, and
  its approval status settings (pause while waiting, open on approval, close on rejection) are
  all off by default.
- **Source:** sdp-area-13 §Approval Settings (approval process, all off); sdp-area-12 §Config (status types); REQ-INC-044, REQ-INC-045
- **SDP weak spot fixed:** an approval does nothing to the request's status unless an admin
  finds and ticks three separate settings.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Submitting a request whose item needs approval moves it to "awaiting approval" with the
     source "approval" in history.
  2. Final approval moves it to "assigned" if a group or technician is set, otherwise to "new".
  3. A rejection moves it to "rejected"; no user can choose "awaiting approval" or "rejected"
     by hand, in the UI or the API.
  4. Status labels show in English and Arabic, and "fulfilled" never shows as "resolved" on a
     service request.

#### REQ-SR-005 — Priority is never left blank on a new request

A service request gets its priority from its catalog item's default, or from the priority
matrix if the item uses impact and urgency, or from the tenant default (Appendix A). Requesters
cannot set the priority of a service request unless the item allows it. A request is never
left with no priority.

- **Decision:** BETTER. A portal request in ServiceDesk Plus arrived with no priority, no SLA
  and no technician, and nothing warned anyone.
- **Source:** sdp-area-03 §Behaviour (test request #41), §Weak spots; sdp-area-02b §Behaviour; REQ-INC-011
- **SDP weak spot fixed:** a service request from the portal had no priority, SLA or
  technician, with no warning.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A portal request from an item with default priority P2 is created with P2, recorded with
     the item as the source.
  2. A request from an item with no default gets the tenant default priority, marked as
     defaulted (REQ-INC-011).
  3. The requester layout never offers the priority field unless the item allows it.

#### REQ-SR-006 — SLA chosen by the item or by rules

A service request's SLA comes from, in order: the SLA linked to its catalog item
(REQ-CAT-017); otherwise the condition-based SLA rules (file 03); otherwise the tenant's
default service request SLA. The admin can change the order, for example to let rules win
over the item. The record shows which source chose the SLA.

- **Decision:** SAME. ServiceDesk Plus offers condition-based SLAs, a user-chosen SLA, or
  both, with an option for which wins. We keep the choice and show the source.
- **Source:** sdp-area-13 §Advanced Portal Settings (SLA for service requests); sdp-area-12 §Behaviour (service request SLA list empty); architecture §2.2 (service-specific SLAs); REQ-WI-004
- **SDP weak spot fixed:** the service request SLA list was empty by default, so requests had
  no due date.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A request from an item linked to SLA "access within 1 business day" gets that SLA, and
     history names the item as the reason.
  2. With precedence set to "rules first", a matching rule's SLA wins over the item's.
  3. A new tenant has a default service request SLA, so a request is never without due dates.

#### REQ-SR-007 — SLA clock waits for approval

By default the resolution clock of a service request is paused while it is awaiting approval
and starts when the approval completes. The response clock is not paused. Admins can change
this per tenant or per catalog item, for example to count approval time against the SLA.

- **Decision:** SAME. ServiceDesk Plus offers "stop the timer while waiting for approval" and
  "start the timer on approval"; ours is on by default.
- **Source:** sdp-area-13 §Approval Settings (approval process); sdp-area-12 §Config (stop timer statuses)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A request that waits 2 business days for approval has its resolution due date moved by 2
     business days, recorded in history.
  2. With the item setting "count approval time", the due date does not move.
  3. The SLA countdown on the record shows "paused: awaiting approval" while paused.

#### REQ-SR-008 — Assignment from the catalog item

A service request is assigned to the catalog item's fulfilment group, and optionally a default
technician, when it is created. If the item says "assign a technician only after approval", the
group is set at creation and the technician after the final approval. Auto-assignment inside
the group (file 03) runs at that point.

- **Decision:** SAME. ServiceDesk Plus service templates have associated technician groups and
  an "assign technician only after approval" option.
- **Source:** sdp-area-12 §Config (service template extras: associate technician groups, assign technician only after approval); sdp-area-03 §Behaviour (no assignment on portal request)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A request from an item with fulfilment group "Access team" is in that group's queue at
     creation, live.
  2. With "technician after approval", the technician is empty until approval, then set by
     auto-assignment, with history naming the method.
  3. A group that has been deleted or disabled since the item was set up is reported on the
     item page and the request falls back to the tenant's default group, recorded in history.

#### REQ-SR-009 — Service request lists, views and columns

Lists show incidents, service requests or both (REQ-INC-104 to 110). Service requests add these
built-in views:

- awaiting my approval;
- approved by me, and rejected by me;
- pending approval (all);
- awaiting fulfilment, and my fulfilment tasks;
- raised by my direct reports.

Columns and filters include catalog item, service category, approval status, current stage,
fulfilment progress, needed-by date, expected delivery and cost.

- **Decision:** SAME.
- **Source:** sdp-area-02a §Screens (public views, request type switch, columns, filterable columns)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. The type switch shows only service requests, only incidents, or both; the choice is kept
     per user.
  2. "Awaiting my approval" lists exactly the requests where the user has a pending approval,
     and drops a row live when they decide.
  3. Filtering by catalog item and by approval status works together with the time filter.

---

## 2. Raising service requests

#### REQ-SR-010 — Technicians raise requests from the catalog

In the console, a "new" menu offers a new incident, the service catalog and a search across
catalog items. Choosing an item opens the create form for that item with its technician
layout, prefilled from the item. The technician picks the requester (REQ-INC-003).

- **Decision:** SAME.
- **Source:** sdp-area-01 §Screens (raise a request panel); sdp-area-03 §Screens (technician-side catalog); sdp-area-02a §Actions (new incident dropdown template browser)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Typing three letters of an item name in the "new" menu lists matching items the
     technician may raise.
  2. Choosing an item opens its form with the item's defaults filled in.
  3. Items hidden from requesters but open to technicians (REQ-CAT-014) appear here.

#### REQ-SR-011 — Request on behalf of someone else

A requester can ask for something for another person. The form shows "for me" or "for someone
else"; the people they can pick depend on a tenant setting (same department, same site, all
requesters, or all users) plus their own direct reports. The request keeps requested by and
requested for apart. Approvals that use "the requester's manager" use the manager of the
person the request is for. Both people are notified and both see the request in the portal.

- **Decision:** SAME. ServiceDesk Plus has a "create requests on behalf of" scope setting. We
  also route manager approval to the right person.
- **Source:** sdp-area-13 §Requester Portal (on behalf of scope); sdp-area-03 §Config (scope dropdowns); REQ-INC-003
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. With scope "same department", the picker offers only people in the requester's
     department and their direct reports; the API refuses anyone else with 403.
  2. A manager-approval stage on a request for person B goes to B's manager, not to the
     submitter's manager.
  3. Both requested by and requested for see the request in "my requests" and get its
     notifications.

#### REQ-SR-012 — Request for several people at once

A requester or technician can submit one catalog item for a list of people (for example
"email account" for five new joiners). The system creates one service request per person,
grouped under one order (REQ-SR-013), each with its own approvals and fulfilment.

- **Decision:** NEW. ServiceDesk Plus needs one request per person.
- **Source:** architecture §2.2 (onboarding orchestration); product-plan §5 (service catalog: bundles)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Submitting an item for five people creates one order and five service requests, each
     with its own requested-for person.
  2. Each request's manager approval goes to that person's manager.
  3. A failure for one person (for example no permission to request for them) is reported per
     person; the others are still created.

#### REQ-SR-013 — Order several items at once

A requester can add several catalog items to a cart and submit them together, or request a
bundle (REQ-CAT-023). One submission creates an order: a parent record with one service
request per item. Each item keeps its own form, approvals, SLA and fulfilment. The order shows
the overall progress and closes when every item is closed, rejected or canceled.

- **Decision:** NEW. ServiceDesk Plus has no cart and no multi-item request; product-plan asks
  for bundles and a store-style catalog.
- **Source:** product-plan §5 (service catalog: store-style catalog, bundles); architecture §2.2 (store-style browsing)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Submitting a cart with three items creates one order and three service requests in one
     transaction; a retry with the same idempotency key creates nothing new.
  2. Rejecting one item's approval does not stop the other two; the order shows "2 of 3 in
     progress, 1 rejected".
  3. The order closes automatically when its last item reaches a closed, rejected or canceled
     status.
  4. A cart left unsent is kept as a personal draft (REQ-INC-019) and shows the item count
     live in the portal header.

#### REQ-SR-014 — Quantity on a request

An item can allow a quantity (for example three monitors). Quantity multiplies the price
(REQ-SR-052), is limited by the item's maximum (REQ-CAT-022) and can be used in approval
conditions (REQ-SR-032).

- **Decision:** NEW. ServiceDesk Plus has no quantity on service templates.
- **Source:** product-plan §5 (store-style catalog); architecture §2.2 (cost per item)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Quantity 3 on an item priced 100 shows an estimated cost of 300 before submitting.
  2. A quantity above the item's maximum is refused in the form and by the API with the same
     field error.

#### REQ-SR-015 — Needed-by date and expected delivery

A requester can say when they need the item, if the item asks for it. Before submitting, the
item page and the form show the expected delivery date, worked out from the item's SLA and the
operating hours. The request shows the expected date, updated after approval. If the needed-by
date is earlier than possible, the requester is told before submitting, and the technician
sees the gap on the record.

- **Decision:** BETTER. ServiceDesk Plus shows only SLA due dates to technicians and a
  scheduled start time on some templates; requesters get no delivery estimate.
- **Source:** sdp-area-02b §Fields (scheduled start time); sdp-area-03 §Fields (details dialog due dates); product-plan §5 (store-style catalog)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. An item with a 3-business-day SLA submitted on a Thursday shows the expected Tuesday
     delivery in the requester's time zone, skipping the weekend.
  2. A needed-by date before the expected date shows a warning on the form and a "needed
     earlier than expected" flag on the record.
  3. After approval completes, the expected date is recalculated and the requester sees the
     new date live.

#### REQ-SR-016 — Request again

From a past service request in the portal, a requester can "request again": a new request of
the same item (its current published version) with the earlier answers filled in.

- **Decision:** NEW.
- **Source:** product-plan §5 (store-style catalog)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. "Request again" on SR-12 opens the item form with SR-12's answers filled in and
     attachments not copied.
  2. Answers to questions removed from the current item version are listed and dropped.
  3. A retired item cannot be requested again; the action is disabled with a reason.

#### REQ-SR-017 — Service requests from email

Email creates incidents by default (REQ-INC-023). An admin can map a mailbox address or a
parsing rule (REQ-INC-025) to a catalog item, so those emails create service requests of that
item. If the item's form has required questions the email cannot answer, the requester gets a
link to complete the form in the portal, and the request waits in "awaiting requester".

- **Decision:** BETTER. In ServiceDesk Plus an email command can name a template, but required
  template fields are not checked and nothing asks the requester for the missing answers.
- **Source:** sdp-area-13 §Mail (email command keys incl. request template, request type); REQ-INC-023, REQ-INC-025
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. An email to the mapped "access@" address creates a service request of the mapped item
     with channel "email".
  2. With a required question unanswered, the request is "awaiting requester" and the
     requester receives a link that opens the form with the missing questions only.
  3. Approvals start only after the required answers are complete.

#### REQ-SR-018 — Scheduled recurring service requests

Admins can schedule service requests from a catalog item on a recurring timetable, as for
incidents (REQ-INC-034), for example a monthly access review.

- **Decision:** SAME.
- **Source:** sdp-area-13 §Announcement and Maintenance (request maintenance); REQ-INC-034
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. A monthly schedule creates one service request per month from its item, with the
     schedule as the source in history.
  2. A scheduled request goes through the item's approvals like any other request.

#### REQ-SR-019 — Converting to and from incidents

Conversion follows REQ-INC-089. Converting an incident into a service request asks the
technician to choose a catalog item; matching answers are mapped and the item's approvals
start if it has any. Converting a service request into an incident withdraws pending
approvals and keeps decided ones in history.

- **Decision:** SAME.
- **Source:** sdp-area-02c §Actions (convert as service request, convert as incident); architecture §2.2 (conversions); REQ-INC-089
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Converting INC-7 to a service request requires a catalog item and creates SR-n whose
     approvals start at stage 1.
  2. Converting a service request with a pending approval withdraws it; the approver's email
     link then shows "no longer needed".

#### REQ-SR-020 — Links to purchase requests and orders

A service request can be linked to purchase requests and purchase orders (file 07), for
example a laptop request that needs a purchase. The request shows the purchase status, and
receiving the order can complete a fulfilment task.

- **Decision:** SAME.
- **Source:** architecture §2.2 (link service requests to purchase requests and orders), §2.11 (purchase); sdp-area-07 §Screens (purchase order: associate service requests)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Creating a purchase request from a service request links both ways, with history on both.
  2. Receiving the linked order completes the fulfilment task marked "waits for purchase".

---

## 3. Approvals

#### REQ-SR-021 — Approval before fulfilment

A catalog item can require approval (REQ-CAT-016). The request then waits in "awaiting
approval" while the approvers decide. Fulfilment tasks, workflows and technician assignment
that the item marks "after approval" start only when the approval succeeds. A rejection ends
the request (REQ-SR-060). Approvals are the engine's approvals (REQ-INC-083), so they work
without email.

- **Decision:** SAME.
- **Source:** sdp-area-12 §Config (service template approvals); sdp-area-02b §Behaviour (tasks only after approval); architecture §2.2 (approvals); REQ-INC-083
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A request from an item with one approval stage has no fulfilment tasks until it is
     approved; on approval the tasks are created within one second.
  2. With no mail server configured, the approver can still find and decide the approval in
     the app.
  3. A rejection with a reason moves the request to "rejected" and notifies the requested by
     and requested for people.

#### REQ-SR-022 — Approver by name or the requester's manager

An approval stage names its approvers: specific users, or "the manager of the person the
request is for". Any user can be an approver, requester or technician; no special approver
licence or flag is needed.

- **Decision:** BETTER. ServiceDesk Plus needs a "request approver" flag on technicians and
  routes approvals mostly through its organisation roles.
- **Source:** sdp-area-11 §Fields (request approver checkbox, organisation roles), §Automation (organisation roles feed approvals); sdp-area-12 §Fields (approval action approvers)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A stage with "manager of requested for" sends the approval to that person's manager from
     their user record.
  2. A requester-only user (no technician role) can approve from the portal.
  3. Changing a person's manager after submission does not move a pending approval; an admin
     can reassign it (REQ-SR-042).

#### REQ-SR-023 — No approval waits on nobody

If a stage's approvers resolve to no active person (no manager on record, approver left the
organisation, empty group), the stage goes to the stage's backup approver (REQ-SR-036), else to
the tenant's approval administrators. The record shows why. A request never sits in "awaiting
approval" with no one able to act.

- **Decision:** BETTER. In ServiceDesk Plus the workflow waited at an approval node while the
  approvals tab showed nothing, so no one could see or act on it.
- **Source:** sdp-area-02b §Behaviour (#38 waiting at approval, nothing visible), §Weak spots; sdp-area-02c §Behaviour
- **SDP weak spot fixed:** an approval was pending with no visible approver and no way to act.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A request for a person with no manager sends the manager stage to the approval
     administrators, and the record says "no manager on record, sent to approval
     administrators".
  2. Deactivating a user who has pending approvals moves those approvals to the fallback
     within one minute and notifies the new approver.
  3. A daily check lists any approval with no active approver to the approval administrators.

#### REQ-SR-024 — Everyone involved sees the approval progress

The record and the portal show every stage: its approvers, each one's decision (pending,
approved, rejected, delegated, withdrawn), when, through which channel (app, email link,
email reply, mobile, chat, automatic, delegate) and the comment. Updates are live. Requesters
see approvals unless the tenant hides them (Appendix A).

- **Decision:** BETTER. In ServiceDesk Plus the approvals tab showed only a mail server error,
  and showing approvals to requesters is an off-by-default setting.
- **Source:** sdp-area-02b §Weak spots (approvals tab shows only a mail error); sdp-area-13 §Requester Portal (show incident approvals to requesters); sdp-area-12 §Config (show approval status to requesters)
- **SDP weak spot fixed:** you cannot see what or whom an approval is waiting for.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. When an approver decides in another browser, the record and the requester's portal page
     show the decision within one second.
  2. Each decision shows the channel; an email-link decision also records the time and the
     client address in history.
  3. With the tenant setting "hide approvals from requesters", the portal shows only "awaiting
     approval" without names or comments.

#### REQ-SR-025 — Approve or reject in the app

Approvers find their pending approvals in an approvals drawer in the console header, in the
portal approvals inbox (REQ-PRT-008) and in their notifications. The approval page shows the
request summary, the requested-for person, the item and its form answers, quantity and cost
(if shown to approvers), earlier stages' decisions and the conversation the approver may see.
They approve or reject with a comment.

- **Decision:** SAME.
- **Source:** sdp-area-01 §Screens (approvals drawer: my pending approvals); architecture §8.1 (approvals waiting on the user channel), §2.15 (my approvals in the portal)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A new pending approval raises the approver's approvals count in the console and the
     portal within one second.
  2. Approving from the drawer records the decision and removes the entry live.
  3. A user who is not an approver of the stage gets 403 from the decision API.

#### REQ-SR-026 — Approve by email with safe one-time links

The approval email has approve and reject links. Each link:

- is single-use, signed, and bound to one approver, one stage and the request version it was
  sent for;
- expires after a set time (Appendix A);
- opens a confirmation page before the decision is recorded (so mail scanners that open links
  do not decide), and the reject page asks for a reason;
- stops working once the stage is decided, the request changes in a way that restarts approval
  (REQ-SR-041), or the request is withdrawn, and then shows "no longer needed".

A tenant can require sign-in for email approvals, for all items or above a cost threshold.

- **Decision:** BETTER. ServiceDesk Plus approvals depend on mail and could not be sent at all
  without it; replay and scanner protection were not visible.
- **Source:** sdp-area-02c §Automation (submit for approval blocked without mail); sdp-area-13 §Approval Settings; architecture §2.2 (email approvals), §11
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Opening an approve link shows a confirmation page and records nothing until the approver
     confirms.
  2. Using the same link a second time records nothing and shows that the decision was already
     made.
  3. A link used after its expiry, or after another approver decided an "any one" stage, shows
     "no longer needed" and changes nothing.
  4. A link forwarded to another person cannot be used by them when sign-in is required; with
     sign-in off, the decision is recorded as the original approver via the link, with the
     channel "email link".

#### REQ-SR-027 — Segregation of duties in approvals

The person who requested, or the person the request is for, cannot approve their own request.
If they are the resolved approver, the stage goes to the backup approver or the approval
administrators, and the record says why. Admins can allow self-approval per catalog item.

- **Decision:** BETTER. ServiceDesk Plus offers the opposite: an option to auto-approve when
  the approver is a chosen user.
- **Source:** architecture §11.2 (segregation of duties); sdp-area-13 §Approval Settings (auto-approve if the approver is a chosen user)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A manager who requests an item for themselves does not get their own manager-stage
     approval; it goes to their own manager.
  2. The decision API returns 403 with a segregation reason code if the requester tries to
     approve their own request.
  3. With "self-approval allowed" on an item, the requester can approve and history marks it
     as a self-approval.

#### REQ-SR-028 — Reasons and comments on decisions

A rejection always needs a reason. An approval comment is optional unless the tenant or the
item requires it. Comments are visible to the requester unless the approver marks them
private.

- **Decision:** SAME. ServiceDesk Plus has a "mandate comments for all approvals" setting.
- **Source:** sdp-area-13 §Approval Settings (mandate comments)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Rejecting with no reason is refused in the app, on the email reject page and by the API.
  2. With "comments required" on, approving without a comment is refused.
  3. A private approval comment is not visible in the portal.

#### REQ-SR-029 — Multi-stage approvals

An item's approval can have several stages that run in order, with no fixed upper limit. Each
stage has its approvers and a decision rule:

- any one approver decides for the stage;
- all must approve (one rejection rejects);
- a majority decides;
- the first answer decides, whether approve or reject.

When a stage is decided, the other pending approvals in it are withdrawn and their email links
stop working. Other approvers in the stage can be told that someone acted.

- **Decision:** BETTER. ServiceDesk Plus limits service requests to 5 stages; product-plan asks
  for unlimited stages.
- **Source:** sdp-area-12 §Fields (approval rules: anyone, everyone, first response, majority); sdp-area-13 §Approval Settings (notify pending approvers when one has acted); architecture §2.2 (at least 5 stages); product-plan §5 (unlimited approval stages)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A request with three stages asks stage 2 only after stage 1 is approved, and stage 3 only
     after stage 2.
  2. With rule "majority" and three approvers, two approvals approve the stage and the third
     approver's pending approval is withdrawn.
  3. With rule "first answer", the first approver's rejection rejects the stage at once.
  4. An item with 10 stages can be saved, and a request through all 10 completes.

#### REQ-SR-030 — Parallel approval stages

Two or more stages can run at the same time (for example finance and security), and the
approval continues when all of them are approved. One rejection rejects the whole approval
unless the item says otherwise.

- **Decision:** NEW. ServiceDesk Plus stages run one after another only.
- **Source:** architecture §2.2 (multi-stage and multi-level approvals); product-plan §5 (unlimited approval stages)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Two parallel stages are both asked at once; the next sequential stage starts only when
     both are approved.
  2. A rejection in one parallel stage withdraws the pending approvals of the other.

#### REQ-SR-031 — Approvers from roles, groups and form fields

Besides named users and the manager, a stage's approvers can be:

- an organisation role relative to the person the request is for (department head, site
  manager, group head, the manager's manager);
- a user group or technician group;
- a person picked in a form question (for example "cost centre owner");
- the owner of the asset or configuration item named in the form.

- **Decision:** SAME. ServiceDesk Plus uses organisation roles and named approvers.
- **Source:** sdp-area-11 §Fields (organisation roles tree), §Automation (organisation roles feed approvals); sdp-area-11 §Actions (assign approval permissions); architecture §2.2 (approval by role or manager)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A stage with "department head of requested for" goes to the department head on that
     person's department record.
  2. A stage with "person in question 'budget owner'" goes to the user picked in that
     question.
  3. A stage with a group as approvers shows each member as a pending approver and follows
     the stage's decision rule.

#### REQ-SR-032 — Conditional approval stages

A stage can apply only when a condition on the request matches, for example cost above 1,000,
quantity above one, or a form answer. Stages that do not apply are shown as "skipped" with the
condition.

- **Decision:** BETTER. In ServiceDesk Plus conditional approvals need a workflow; here the
  condition sits on the stage.
- **Source:** sdp-area-12 §Config (approvals as trigger or template features, workflow conditions); architecture §2.2
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A finance stage with "cost greater than 1,000" is skipped for a 500 request and asked for
     a 1,500 request.
  2. The skipped stage shows on the record with the condition that skipped it.

#### REQ-SR-033 — Automatic approval rules

An item or the tenant can approve automatically when:

- the approver of a later stage already approved an earlier stage of the same request;
- the cost is below a set amount;
- a rule matches (for example the requester belongs to a group).

Automatic decisions show as "approved automatically" with the rule that decided.

- **Decision:** SAME. ServiceDesk Plus can auto-approve when the same approver approved an
  earlier level or the approver is a chosen user.
- **Source:** sdp-area-13 §Approval Settings (automatically approve if the same approver approved at an earlier level; if the approver is chosen users)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A manager who approved stage 1 and is also the stage 3 approver is not asked again; stage
     3 shows "approved automatically: already approved at stage 1".
  2. A request with cost 50 on an item with "auto-approve below 100" skips approval and starts
     fulfilment at once.

#### REQ-SR-034 — Approval reminders and escalation

Pending approvers get reminders: the first after a set number of business days without a
decision, then repeated up to a set count at a set time of day (Appendix A). After the last
reminder, the approval is escalated: to the backup approver, the approver's manager or the
fulfilment group, as the item says. Reminders and escalations appear in the request history.

- **Decision:** SAME. ServiceDesk Plus reminds approvers for 3 operational days after 2 days
  without action, at 10:00.
- **Source:** sdp-area-13 §Advanced Portal Settings (approval reminder); architecture §2.2 (reminders), §2.4 (backup approvers)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. With the defaults, an approval sent Monday morning gets its first reminder on Wednesday at
     10:00 in the approver's time zone, skipping non-working days.
  2. After the last reminder the approval is escalated as configured, and history records it.
  3. Reminders stop as soon as the stage is decided.

#### REQ-SR-035 — Delegate approvals

An approver can name a delegate for a date range, for example while on leave. New approvals in
that range go to the delegate; the original approver can still act. Admins can set a
delegation for someone else. The decision shows "approved by A for B".

- **Decision:** SAME. ServiceDesk Plus has approval delegation (disabled by default).
- **Source:** sdp-area-12 §Screens (delegation: request ownership and approval delegation); architecture §2.2 (delegation)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. With a delegation from B to A for this week, a new approval for B goes to A and is listed
     in A's inbox.
  2. A's decision is recorded as "A on behalf of B" in history and in the portal.
  3. When the delegation ends, approvals still pending move back to B.

#### REQ-SR-036 — Backup approvers

Each stage can name a backup approver who receives the approval when the primary approver is
missing, inactive or escalated (REQ-SR-023, REQ-SR-034).

- **Decision:** SAME.
- **Source:** architecture §2.2 (delegation and backup approvers)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A stage whose named approver is deactivated sends the approval to its backup and records
     why.
  2. An escalation to the backup keeps the primary's pending approval open until one decides.

#### REQ-SR-037 — Ask for clarification

An approver can ask a question instead of deciding. The question goes to the requester (or the
technician, by choice) as a public message; the stage stays pending, reminders pause, and the
answer returns to the approver with a notification.

- **Decision:** NEW. ServiceDesk Plus has no clarification step for request approvals;
  architecture names clarification requests for change approvals and this engine serves both.
- **Source:** architecture §2.4 (clarification requests)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. An approver's question appears in the requester's portal conversation and the approval
     shows "clarification asked".
  2. The requester's answer notifies the approver and the approver can then decide.
  3. Approval reminders do not run while a clarification is open.

#### REQ-SR-038 — Approve by replying to the email

An approver can reply to the approval email with "approve" or "reject" and an optional
comment, in English or Arabic (Urdu from V1). The reply must come from the approver's own
address, and the decision follows the same rules as a link. Unclear replies are not applied;
the approver is asked to use the link or the app.

- **Decision:** SAME. architecture lists email intent for approvals.
- **Source:** architecture §2.10 (email intent for approvals); sdp-area-10 §Screens (predictive email features); REQ-AI-056 (shared email reply reading)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A reply "Approved, thanks" from the approver's address approves the stage with channel
     "email reply".
  2. A reply from a different address is not applied and the sender is told why.
  3. A reply such as "approve only if cheaper" is not applied, and the approver gets a message
     with the link to decide.

#### REQ-SR-039 — Approve on the mobile app

Approvers get a push notification for a new approval and can approve or reject in the mobile
app with the same information and rules as in the console (REQ-SR-025).

- **Decision:** SAME.
- **Source:** architecture §2.2 (mobile approvals), §2.15 (approver apps), §9.1
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A push notification for a new approval opens the approval page in the app.
  2. A decision made in the app appears on the request in the console within one second.

#### REQ-SR-040 — Approve in Teams and Slack

When the Teams or Slack connector is set up (file 12), approvers can approve or reject from an
actionable message, with the same rules as in the app.

- **Decision:** SAME.
- **Source:** architecture §2.14 (Teams approvals, actionable messages); sdp-area-14 §Screens (Outlook actionable messages, Teams, Slack)
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. A decision from Teams is recorded with channel "Teams" and the approver's identity from
     the connector's user mapping.
  2. An actionable message for a stage that was already decided shows "no longer needed".

#### REQ-SR-041 — Restart approval after a relevant change

If someone changes an answer that affects approval (for example quantity, an option with a
price, or the requested-for person) after approval started, the approval restarts from the
first affected stage. The item lists which questions restart approval. Earlier decisions stay
in history; their links stop working.

- **Decision:** SAME. ServiceDesk Plus can restart the approval process after a resource
  update.
- **Source:** sdp-area-13 §Approval Settings (restart approval after a resource update)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Changing quantity from 1 to 3 on an approved request restarts stage 1 and moves the
     request back to "awaiting approval".
  2. Changing a question that is not marked "restarts approval" does not affect approvals.
  3. Old approval links for the request stop working after the restart.

#### REQ-SR-042 — Technicians adjust a running approval

A technician with the "modify approvers" permission can add an approver or a stage, replace an
approver or resend reminders on a running approval, with a reason. They can also send an ad
hoc approval on a service request as on an incident (REQ-INC-083).

- **Decision:** SAME.
- **Source:** sdp-area-11 §Fields (advanced permissions: modify approvers); sdp-area-02c §Actions (submit for approval)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Replacing an approver withdraws the old one's approval, notifies the new one and records
     the reason in history.
  2. A technician without "modify approvers" sees these actions disabled with a reason.

#### REQ-SR-043 — What an approver can see

An approver who is not a technician sees the request summary, the form answers that the item
marks as visible to approvers, the cost when the tenant shows cost to approvers, earlier
decisions and the public conversation. They never see private notes or fields hidden from
them.

- **Decision:** SAME. ServiceDesk Plus has a "show cost to approvers" setting.
- **Source:** sdp-area-13 §Requester Portal (show service and resource cost to requesters, approvers); sdp-area-03 §Config (cost display)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. An approver page never contains private notes; the API response for the approver has no
     private fields.
  2. A question marked "hidden from approvers" is absent from the approval page and email.
  3. With "show cost to approvers" off, cost is absent for approvers.

#### REQ-SR-044 — Approval steps in visual workflows

A visual workflow (file 03) can include an approval step that uses this approval engine, with
approved, rejected and timed-out outcomes. A trigger or business rule (file 03) can also start
an approval on a request, from the shared library of approval actions.

- **Decision:** BETTER. ServiceDesk Plus workflows have no approval node; approvals come from
  templates or triggers, and setting the approval status from a workflow failed on incidents.
- **Source:** sdp-area-12 §Config (no separate approval node), §Fields (approval action, trigger actions), §Screens (custom actions: approvals); sdp-area-12 (12b) §Behaviour (field update of approval status failed); architecture §6.7 (approval node)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A workflow approval step creates a stage on the request that behaves like REQ-SR-029.
  2. The step's rejected outcome follows its branch in the workflow and is shown on the
     execution view.

#### REQ-SR-045 — AI approval suggestions

The AI can suggest a decision to an approver, based on how similar requests were decided,
with the reasons. It never decides on its own unless an admin turns an automatic approval rule
on for that item (REQ-SR-033). AI settings are in file 10; model access follows D-049.

- **Decision:** SAME. ServiceDesk Plus has an AI feature that approves on the approver's behalf
  from learned behaviour. We suggest first, with the approver in control.
- **Source:** sdp-area-10 §Screens (request auto approval); product-plan §7.1 (safe by design); D-049
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. The approval page shows the suggestion and its reasons; the approver still decides.
  2. Every AI suggestion and whether it was followed is logged for outcome reporting.

---

## 4. Fulfilment

#### REQ-SR-046 — Fulfilment tasks from the catalog item

When a request is approved (or created, if it needs no approval), the item's fulfilment plan
(REQ-CAT-019) creates its tasks and checklists on the request. Each task gets its group and
owner from the plan. History records each task as created by the item's plan. Tasks behave as
in REQ-INC-072 to 076.

- **Decision:** BETTER. Same capability; in ServiceDesk Plus the creation of template tasks
  did not show in history.
- **Source:** sdp-area-12 §Config (service template tasks, checklists tabs); sdp-area-12 (12b) §Behaviour (template task not in history); sdp-area-02b §Behaviour (tasks after approval); REQ-INC-040
- **SDP weak spot fixed:** the template task's creation did not show in history.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Approving a request whose item has three tasks creates three tasks within one second,
     each with its planned group, and history names the plan.
  2. A request that needs no approval gets its tasks at creation.
  3. A rejected request never gets fulfilment tasks.

#### REQ-SR-047 — Ordered and parallel fulfilment steps

A fulfilment plan can order its tasks: a task can wait for others, and tasks without
predecessors start together. A waiting task is shown as "waiting" and its owner is notified
only when it can start. Dependencies are enforced (REQ-INC-075). The request shows the steps as
a simple flow with their state.

- **Decision:** BETTER. In ServiceDesk Plus ordering needs a workflow with task split and wait
  nodes; here it is part of the plan.
- **Source:** sdp-area-02b §Automation (split and handle tasks, wait for task completion); architecture §2.2 (task templates with dependencies); REQ-INC-075
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. In a plan where "create account" waits for "approve licence", the "create account" owner
     is notified only when "approve licence" is completed.
  2. Two tasks with no predecessors are both open at once.
  3. The flow view on the request updates live as tasks complete.

#### REQ-SR-048 — Conditional fulfilment tasks

A task in a plan can be created only when a form answer matches, for example "needs remote
access: yes" adds a VPN task.

- **Decision:** SAME.
- **Source:** sdp-area-12 (12b) §Config (template tasks); REQ-INC-040
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A request with "needs remote access: no" has no VPN task; with "yes" it has one.
  2. Changing the answer before fulfilment starts adds or removes the conditional task, with
     history.

#### REQ-SR-049 — Tasks capture data for later steps

A fulfilment task can have its own fields that its owner fills in (for example the new
account name or the asset tag). Later tasks, notifications to the requester and the
resolution can use those values.

- **Decision:** NEW. ServiceDesk Plus tasks have fixed fields only.
- **Source:** sdp-area-02c §Fields (add task fields); architecture §2.2 (fulfilment)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A task with a required field "account name" cannot be completed until the field is filled.
  2. The fulfilled notification to the requester can include the value of "account name".

#### REQ-SR-050 — Fulfilment tasks for people outside the service desk

A fulfilment task can be assigned to a person who is not a technician, for example the hiring
manager who must confirm a start date. They see and complete the task in the portal, without
access to the rest of the request.

- **Decision:** SAME. The ServiceDesk Plus portal summary shows task counts to requesters.
- **Source:** sdp-area-03 §Screens (portal my summary: task counts); sdp-area-11 §Fields (task technician access); REQ-INC-072
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A task assigned to a requester appears in "my tasks" in their portal and their task count
     rises live.
  2. They can complete it and add a comment, but cannot open private notes of the request.

#### REQ-SR-051 — Fulfilment progress the requester can follow

The requester sees where their request is in plain steps: submitted, approval (with the
current stage and who it waits for, unless hidden), in fulfilment (steps done out of total),
delivered, closed. The expected delivery date is shown next to it. Updates are live.

- **Decision:** BETTER. ServiceDesk Plus shows the requester only the status and the
  resolution text.
- **Source:** sdp-area-03 §Screens (post-submit details dialog), §Fields (details dialog); architecture §8 (portal live updates)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Completing one of three fulfilment tasks changes the requester's progress to "1 of 3"
     within one second, with no refresh.
  2. The progress never shows internal task names the item marks as internal; it shows "step 2
     of 3" instead.
  3. The progress steps are labelled in the requester's language and render right-to-left in
     Arabic.

#### REQ-SR-052 — Cost on a request

A request's estimated cost is the item price times quantity plus the prices of chosen options
(REQ-CAT-020), worked out when it is submitted and kept with the request. Its actual cost adds
fulfilment task costs and worklog costs (REQ-INC-068). The requester and approvers see the
estimate only if the tenant shows cost to them (Appendix A).

- **Decision:** SAME. ServiceDesk Plus has service cost and total cost on requests.
- **Source:** sdp-area-02a §Screens (service cost, total cost columns); sdp-area-02c §Fields (task additional cost); sdp-area-13 §Requester Portal (show cost to requesters, approvers); architecture §2.2 (cost per item)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Two monitors at 150 each plus a 20 cable option give an estimate of 320, shown before
     submitting when cost is visible to requesters.
  2. A later price change on the item does not change the estimate on requests already
     submitted.
  3. Actual cost updates live when a task cost or worklog cost is added.

#### REQ-SR-053 — Fulfilment workflow on a request

A catalog item can attach a visual workflow (file 03) that runs on each of its requests, for
example waiting for a start date, creating tasks, calling a webhook and closing. The request
shows the workflow's live state. A workflow that waits on something (an empty field, a date,
a task) says on the record what it waits for.

- **Decision:** SAME. ServiceDesk Plus runs workflows from service templates; we add the
  visible waiting reason.
- **Source:** sdp-area-02b §Automation (onboarding workflow structure), §Behaviour (#37 stuck at wait), §Weak spots; sdp-area-12 (12b) §Screens (workflow execution view)
- **SDP weak spot fixed:** a workflow stuck at a wait node showed only a red dot on a button.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A request whose workflow waits for an empty field shows a banner naming the field, and
     the assignee is notified.
  2. Filling the field resumes the workflow within one second, with history.
  3. The execution view highlights the path taken and the current step, live.

#### REQ-SR-054 — Stop a fulfilment workflow with a record

A technician with permission can stop the workflow on a request, with a reason. The request
stays as it is and the technician continues by hand. The workflow's execution log is kept.

- **Decision:** BETTER. In ServiceDesk Plus revoking a workflow clears its execution log.
- **Source:** sdp-area-02c §Automation (revoke workflow clears the execution log)
- **SDP weak spot fixed:** stopping a workflow erases the record of what it did.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Stopping a workflow requires a reason and records it in history.
  2. After stopping, the execution log still shows every step that ran.
  3. Tasks the workflow created stay on the request.

#### REQ-SR-055 — Automated fulfilment actions

A fulfilment step can run an automated action instead of a person: a webhook, a connector
action (for example create an account in the directory, file 12) or an Extravis product action
(install software through AgentX or PatchX). The result is recorded on the request. A failed
action creates a task for the fulfilment group and notifies it.

- **Decision:** NEW. product-plan asks for automated fulfilment; ServiceDesk Plus needs custom
  functions for this.
- **Source:** product-plan §5 (service catalog: automated fulfilment), §7.3 (L1 Resolver: access request); architecture §2.14 (identity, AgentX and PatchX)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A successful automated step completes its task and records the action's result.
  2. A failed step shows the failure on the request (REQ-WI-009) and creates a manual task for
     the fulfilment group.

#### REQ-SR-056 — Hand over an asset on fulfilment

Fulfilling a hardware item can pick an asset from stock, assign it to the requested-for person
and record the hand-over (file 07). The asset then appears in the person's "my assets".

- **Decision:** SAME.
- **Source:** sdp-area-03 §Screens (portal my assets); sdp-area-07 §Behaviour (assigning a user moves the asset to in use); architecture §2.11
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Completing the hand-over task with an asset assigns the asset to the requested-for person
     and links it to the request.
  2. The asset appears in that person's portal "my assets" within one second.

#### REQ-SR-057 — Orchestration across department desks

One request can drive fulfilment across department desks (HR, IT, facilities, file 12), for
example onboarding: each desk gets its tasks in its own queue, and the request shows progress
across all of them.

- **Decision:** SAME. ServiceDesk Plus handles this with separate instances and limited
  cross-instance flow.
- **Source:** architecture §2.2 (onboarding and offboarding orchestration across HR, IT and facilities), §2.15 (ESM); sdp-area-14 §Screens (instances and ESM: separate desk instances)
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. An onboarding request creates tasks in the HR, IT and facilities desks, each visible only
     to that desk's people and to the request's owner.
  2. The requester sees one progress view across all desks.

---

## 5. Closure, rejection and cancellation

#### REQ-SR-058 — Fulfilled when the work is done

By default, when the last required fulfilment task of a request is completed, the request
moves to "fulfilled" by itself, with a fulfilment note built from the tasks. Admins can turn
this off per item, so a technician marks it fulfilled by hand. Closing a request with open
fulfilment tasks follows REQ-INC-095, but for service requests open fulfilment tasks block by
default.

- **Decision:** BETTER. ServiceDesk Plus can move a request to closed when all tasks complete,
  but it is off by default, and closing with open tasks is allowed with no warning.
- **Source:** sdp-area-13 §Closure Rules (closing requests associated with tasks and checklists); sdp-area-02c §Behaviour (closed with open task); REQ-INC-095
- **SDP weak spot fixed:** requests close with open tasks and no warning.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Completing the last of three required tasks moves the request to "fulfilled" within one
     second, with the source "fulfilment plan" in history.
  2. Trying to close a request with an open fulfilment task is refused under default settings,
     naming the task.
  3. With the item setting off, completing all tasks leaves the status unchanged and notifies
     the assignee.

#### REQ-SR-059 — Requester confirms receipt, then auto-close

When a request is fulfilled, the requester is asked to confirm they received what they asked
for, as in REQ-INC-096. "Received" closes it; "not received" reopens it to "in progress" with
their comment. With no answer it closes after the tenant's set number of business days.

- **Decision:** SAME.
- **Source:** sdp-area-13 §Closure Rules (user acknowledgement, automated closure); REQ-INC-096
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. "Received" in the email or the portal closes the request with the requester as actor.
  2. "Not received" reopens it to "in progress" and adds the comment as a public entry.
  3. The confirm and reject links follow the same one-time rules as approval links
     (REQ-SR-026 AC2 and AC3).

#### REQ-SR-060 — Rejected requests

A rejected request is in "rejected" (closed category). The requester sees the rejection reason
and who rejected it, unless approvals are hidden from them. A rejected request cannot be
reopened; the requester can request again (REQ-SR-016). Rejection closes the request's
fulfilment work: no tasks are created and any created by a workflow are canceled.

- **Decision:** BETTER. ServiceDesk Plus can set a rejected request to closed, but the setting
  is off by default.
- **Source:** sdp-area-13 §Approval Settings (when rejected, set the status to closed); sdp-area-02b §Fields (status rejected)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A rejected request shows the reason in the portal and in the rejection email.
  2. Reopening a rejected request is refused, and "request again" is offered instead.
  3. Reports count rejected requests apart from canceled and closed ones.

#### REQ-SR-061 — Withdraw a request awaiting approval

The requester can withdraw their own request while it is awaiting approval, even when the
tenant only lets requesters ask for cancellation (REQ-INC-148). Pending approvals are
withdrawn, their links stop working and the approvers are told. After approval, cancellation
follows REQ-INC-148.

- **Decision:** BETTER. Nothing is being worked on yet, so withdrawal needs no technician.
- **Source:** sdp-area-13 §Requester Portal (cancel options); sdp-area-02c §Fields (cancel reasons); REQ-INC-100, REQ-INC-148
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Withdrawing a request awaiting approval cancels it with the reason "withdrawn by
     requester" and notifies pending approvers.
  2. An approver who then opens the email link sees "no longer needed".
  3. After approval, the portal offers "ask to cancel" under the tenant's cancel setting.

#### REQ-SR-062 — Requesters follow their service requests

The requester's view of a service request follows REQ-INC-147, plus the item and its answers,
the approval progress (REQ-SR-024), the fulfilment progress (REQ-SR-051), the expected
delivery date and the cost when shown. Requesters can reply, add files, answer
clarifications, withdraw (REQ-SR-061), confirm receipt and request again. Whether they may
edit answers after submitting follows the tenant setting (REQ-INC-148), which can apply to
incidents, service requests or both.

- **Decision:** SAME.
- **Source:** sdp-area-03 §Screens (portal requests, details dialog); sdp-area-13 §Requester Portal (request editing: incidents, service requests or both); REQ-INC-147, REQ-INC-148
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A requester sees their service request's item, answers, approval and fulfilment progress
     on one page, live.
  2. With editing allowed for service requests only, the requester can change an answer on a
     service request but not on an incident.
  3. A requester's edit to an answer is recorded in history with the requester as actor and
     the source "portal".

---

## 6. Catalog structure and items

#### REQ-CAT-001 — Service categories in a tree

Admins organise the catalog into service categories that can nest (a category inside a
category). A category has a name, a description and an icon, each name and description per
language, a display order and an enabled switch. A disabled category hides its items from
requesters but keeps them for existing requests.

- **Decision:** SAME.
- **Source:** sdp-area-03 §Screens (service category list), §Fields (new service category: icon, name, description, parent); sdp-area-12 §Config (service categories nest); architecture §2.2 (hierarchical service categories)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A category created under another shows nested in the portal and the console catalog.
  2. Disabling a category removes it and its items from the portal within one second, and
     existing requests of its items still open normally.
  3. A category cannot be deleted while it holds items or categories; the admin is told how
     many.

#### REQ-CAT-002 — Catalog items

A catalog item is one thing people can ask for. It has:

- a name, a short summary and a full description (rich text), per language;
- an icon or image;
- a primary category and optional extra categories it also appears in;
- keywords and synonyms for search;
- an owner (the person who maintains it);
- a status: draft, published or retired (REQ-CAT-024);
- the settings in REQ-CAT-008 to REQ-CAT-023.

- **Decision:** BETTER. Same capability as service templates. An item can appear in more than
  one category, so a requester finds it where they look.
- **Source:** sdp-area-03 §Screens (customize catalog), §Config (catalog contents); sdp-area-12 §Config (service template extras); architecture §2.2 (catalog items with their own forms)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. An item with primary category "Accounts" and extra category "New starters" appears in
     both in the portal, and its requests report the primary category.
  2. An item's name and summary show in the viewer's language, falling back to English when a
     translation is missing.
  3. A draft item is never visible in the portal or the console catalog.

#### REQ-CAT-003 — Incident templates in the catalog

Incident templates marked for requesters can appear in the catalog as "report a problem"
entries, in a category or in a general group, so requesters find "my printer does not work"
next to "I need a printer". Choosing one creates an incident (REQ-INC-028), not a service
request.

- **Decision:** SAME. ServiceDesk Plus shows incident templates in the catalog under a general
  pseudo-category.
- **Source:** sdp-area-03 §Screens (customize catalog: general incident templates), §Config; sdp-area-12 §Config (service categories hold incident templates)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. An incident template placed in category "Printing" shows there in the portal with a
     "report a problem" marker.
  2. Submitting it creates an INC record, not an SR record.
  3. The incident general group also shows in the portal's "report an issue" entry, not only
     in the console.

#### REQ-CAT-004 — One admin page per catalog item

Everything about an item is set on one admin page with tabs: details, form, visibility,
approvals, SLA and assignment, fulfilment, cost, versions and usage. The admin can search
items by name from the admin home. Each tab says what it controls in one line.

- **Decision:** BETTER. ServiceDesk Plus spreads a service template's settings over several
  places, and the research could not find one screen for layout, approvals and tasks.
- **Source:** sdp-area-03 §Weak spots (no single screen for a service template; setup search finds nothing); sdp-area-12 §Config (service template tabs)
- **SDP weak spot fixed:** no single admin screen for a service template, and the admin search
  returns nothing for it.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. An admin can set an item's form, approval stage, SLA, fulfilment group and tasks without
     leaving the item page.
  2. Searching the admin home for part of an item's name opens that item.
  3. A tab whose feature is outside the tenant's edition shows disabled with a hint
     (REQ-WI-025).

#### REQ-CAT-005 — Copy, move, disable and retire items

Admins can copy an item (the copy is a draft marked as a copy), move it to another category,
disable it, and delete it only while no request uses it; otherwise they retire it
(REQ-CAT-024).

- **Decision:** SAME.
- **Source:** sdp-area-03 §Actions (service category toolbar: copy template; row: edit, move, disable, delete); sdp-area-12 §Actions (template list rows: edit, move, delete, disable)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Copying an item creates an independent draft with all settings, named as a copy.
  2. Deleting an item that has requests is refused and "retire" is offered instead.
  3. Moving an item changes where it shows in the portal live, and existing requests keep
     their category in history.

#### REQ-CAT-006 — Item content in every language

Item and category names, summaries, descriptions, question labels, help texts and option
labels have one value per tenant language. The admin page shows which translations are
missing, and the preview shows each language, including right-to-left.

- **Decision:** BETTER. ServiceDesk Plus charges extra for multiple languages on-prem and has
  no per-language catalog content in the research.
- **Source:** D-006, D-048; architecture §9.5; product-plan §9.1 (no language surcharge); REQ-WI-013
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. An Arabic-speaking requester sees an item's Arabic name, question labels and options,
     right-to-left.
  2. A missing Arabic option label falls back to English, and the admin page lists it as
     missing.
  3. The item cannot be published while its English text is missing.

#### REQ-CAT-007 — Starter catalog for a new tenant

A new tenant gets a small starter catalog in English and Arabic (Appendix A), written in our
own words, with categories, items, forms, a manager approval on the items that need one and
simple fulfilment tasks. All of it is editable and can be deleted.

- **Decision:** SAME. ServiceDesk Plus ships sample categories and templates.
- **Source:** sdp-area-03 §Screens (service category list), §Config (catalog contents); D-041
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A new tenant's portal shows the starter categories and items with no admin set-up.
  2. Every starter item can be edited, retired or deleted like any other item.
  3. No starter text copies the vendor's sample wording.

---

## 7. Item forms

#### REQ-CAT-008 — Questions on the item form

Each item has its own form: the shared work item fields it uses (subject, description,
attachments, site ...) and its own questions. Question types include:

- short and long text, number, decimal, currency, date, date and time;
- single choice (list or radio), multiple choice, yes or no;
- email, phone, web address;
- person lookup;
- attachment.

Each question has a label, help text, a default, required or optional, and whether the
requester, the technician and the approver can see it. The subject can be built from answers
(for example "Access to {system} for {person}"). The form's structure is available through the
API, so other channels can render it.

- **Decision:** SAME. ServiceDesk Plus service templates have their own fields and new field
  types in the designer.
- **Source:** sdp-area-03 §Fields (service template form with custom resource details fields); sdp-area-12 §Config (template designers: new field types; mandatory, requester can set, requester can view); architecture §2.2 (service templates)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. An item with a required single-choice question refuses submission without an answer, in
     the portal and through the API, with the same field error.
  2. A question marked "hidden from requesters" never reaches the portal API.
  3. A subject pattern "Access to {system}" with answer "VPN" gives the subject "Access to
     VPN".
  4. The API returns the item's form structure in the caller's language, so the chat assistant
     can ask the same questions.

#### REQ-CAT-009 — Lookups to my assets, people and records

A question can look up records the requester may see: their own assets ("which of my
laptops?"), people, sites, departments, or configuration items. The tenant can limit asset
lookups to the requester's own assets.

- **Decision:** SAME. ServiceDesk Plus has resource information questions and a setting to show
  only the requester's own assets.
- **Source:** sdp-area-12 §Config (service template resource info); sdp-area-13 §Requester Portal (show only associated assets during request creation); architecture §2.2 (select one of my assets)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A "my assets" question lists only assets assigned to the requested-for person.
  2. A lookup never returns records the requester may not see; the API enforces it.
  3. The chosen asset is linked to the request (REQ-INC-015).

#### REQ-CAT-010 — Repeating rows on a form

A question group can repeat as rows, for example a list of people and their access level.
The admin sets the columns and a maximum number of rows.

- **Decision:** SAME. ServiceDesk Plus has subform types.
- **Source:** sdp-area-13 §Announcement and Maintenance (subform types)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A requester can add up to the maximum rows; one more is refused in the form and the API.
  2. Each row's answers show as a table on the record and in notifications.

#### REQ-CAT-011 — Form rules on item forms

Item forms use the same form rules as incident templates (REQ-INC-037), enforced in the
browser and on the server. On an item, rules can also show or hide whole sections, set an
option's price, and add a fulfilment task or approval stage condition (REQ-SR-032,
REQ-SR-048).

- **Decision:** BETTER. Rules are enforced on the server as well as in the browser.
- **Source:** sdp-area-12 §Config (service template form rules tab); sdp-area-12 (12b) §Config (form rules); REQ-INC-037
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A rule "if device type is laptop, show section 'laptop options'" works in the portal, and
     the API refuses answers for the hidden section.
  2. The browser and the server give identical results on the shared rule test suite.

#### REQ-CAT-012 — Guidance and related articles on an item

An item can show a help card and linked knowledge articles on its page and form, for example
"before asking for a new password, try self-service reset". Requesters can open the articles
without losing their form.

- **Decision:** SAME. ServiceDesk Plus templates have a help card and reference documents.
- **Source:** sdp-area-12 §Config (form customisation: help card and reference documents); REQ-INC-038
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. The help card shows on the item page in the requester's language.
  2. Opening a linked article and coming back keeps every typed answer.
  3. Reports count how often requesters opened a linked article and then left without
     submitting.

#### REQ-CAT-013 — No admin scripts in item forms

Admins cannot add their own scripts that run in the requester's browser on item forms.
Form rules (REQ-CAT-011) and server-side custom functions in the sandboxed runtime (file 03)
replace them.

- **Decision:** SKIP. Admin-written browser scripts are a cross-site scripting risk, break on
  upgrades, and bypass server validation (architecture §6.7, §11).
- **Source:** sdp-area-12 (12b) §Config (custom scripts); architecture §2.2 (form rules and scripts), §6.7; REQ-INC-043
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. No admin setting stores script code that the portal or console form executes.
  2. Every documented script use case from the research has a form rule or custom function
     equivalent listed in the admin guide.

---

## 8. Item settings: visibility, approvals, SLA, fulfilment and cost

#### REQ-CAT-014 — Show or hide an item from requesters

Each item is marked for requesters (portal and console), or for technicians only (console
only). A technician-only item can still be raised for a requester by a technician. The tenant
can also hide the default incident template from requesters.

- **Decision:** SAME. ServiceDesk Plus has "show to requester" per template and "do not show
  the default request template to requesters".
- **Source:** sdp-area-03 §Screens (incident template list: show to requester), §Automation (portal visibility controls); sdp-area-13 §Requester Portal (do not show default request template)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A technician-only item is absent from portal browse, portal search, the chat assistant
     and the portal API.
  2. A technician can raise that item for a requester from the console.
  3. Changing the setting updates the portal live.

#### REQ-CAT-015 — Audience rules per item and category

An item or a category can be limited to an audience made of any mix of:

- user groups (dynamic groups, file 11);
- departments, sites and regions;
- organisation roles and portal roles;
- named people.

An audience can also exclude people. Rules apply everywhere: portal browse and search, the
chat assistant, the API, and the "request on behalf" picker (a requester may only ask for an
item for someone in its audience).

- **Decision:** SAME. architecture asks for catalog visibility by user group, department, site
  and role; we enforce it in every channel.
- **Source:** architecture §2.2 (entitlements); sdp-area-11 §Screens (user groups as saved filters); sdp-area-03 §Automation (portal page access level)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. An item limited to the Finance department is not listed, found or submittable for a
     requester in Sales; the API returns 404 for it.
  2. A requester in Finance cannot request it on behalf of someone in Sales.
  3. Moving a requester to Finance shows the item to them without a new sign-in.

#### REQ-CAT-016 — Approval settings per item

On each item the admin sets whether approval is needed and, if so, its stages (approvers,
decision rule, condition, backup), the reminder and escalation settings (or the tenant
defaults), and:

- whether approval emails go out automatically;
- whether requesters see the approval progress;
- whether a technician is assigned only after approval;
- whether self-approval is allowed;
- which questions restart approval when changed.

A single stage with named approvers or the manager is in every edition; more stages,
parallel stages, conditions, role and field approvers and automatic rules need Professional
(REQ-SR-029 to 033).

- **Decision:** SAME. ServiceDesk Plus service templates have an approvals tab with these
  options.
- **Source:** sdp-area-12 §Config (service template approvals tab: auto-send notifications, show approval status to requesters, assign technician only after approval, approval rule, manage approval; approver field); sdp-area-13 §Approval Settings
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Saving an item with an approval stage that has no approver is refused with a clear
     message.
  2. A change to an item's approval settings applies to new requests only; requests already
     submitted keep theirs (REQ-CAT-025).
  3. The item page shows a plain-language summary of the approval ("the requester's manager,
     then IT security; any one approves").

#### REQ-CAT-017 — SLA per item

Each item can link an SLA policy (file 03), or use the rules. The item page shows the
response and delivery targets that result, and the portal shows the expected delivery time
(REQ-SR-015).

- **Decision:** SAME.
- **Source:** architecture §2.2 (service-specific SLAs); sdp-area-13 §Advanced Portal Settings (SLA for service requests)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Linking an SLA to an item shows its targets on the item page in business time.
  2. A disabled SLA linked to an item is reported on the item page, and requests fall back as
     in REQ-SR-006.

#### REQ-CAT-018 — Fulfilment group per item

Each item names the fulfilment group, an optional default technician and when to assign
(at creation, or after approval). These feed REQ-SR-008.

- **Decision:** SAME.
- **Source:** sdp-area-12 §Config (service template: associate technician groups, assign technician only after approval)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. An item cannot be published without a fulfilment group.
  2. The group picker offers only active groups the admin may manage.

#### REQ-CAT-019 — Fulfilment plan per item

Each item has a fulfilment plan: tasks and checklists, each with title, description, group or
owner, expected duration, order, dependencies and conditions, and whether it is internal (not
named to the requester). Tasks can come from task templates (REQ-INC-074). An item can
instead, or as well, attach a life cycle (REQ-INC-049) and a workflow (REQ-SR-053).

- **Decision:** SAME. ServiceDesk Plus service templates have tasks and checklists tabs and a
  workflow or life cycle picker.
- **Source:** sdp-area-12 §Config (service template tasks, checklists, workflow or life cycle picker; actions: add task, add task from template); sdp-area-02b §Automation (onboarding workflow)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. An item with three planned tasks creates them on each new request as in REQ-SR-046.
  2. A dependency loop in the plan is refused on save.
  3. Dependencies, conditions and workflows show disabled with an upgrade hint in Essentials,
     where only an ordered list of tasks is available.

#### REQ-CAT-020 — Price and cost per item

An item can have a price: one-time or recurring (per month or year), in a tenant currency,
with extra prices for options in its questions. The admin also sets an internal cost per item
when it differs from the price. Who sees prices (requesters, approvers) is a tenant setting
(REQ-PRT-031).

- **Decision:** BETTER. ServiceDesk Plus has cost details on service templates, but
  product-plan finds its costs work mostly through extra fields; we make price and options
  native.
- **Source:** sdp-area-12 §Config (service template cost details, resource info needs service cost); sdp-area-13 §Requester Portal (show service and resource cost); product-plan §5 (native pricing and charge-back); architecture §2.2 (cost per item)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. An item priced 500 one-time with a "+100 for extra memory" option shows 600 when that
     option is chosen.
  2. A recurring price shows per period in the portal ("40 per month").
  3. Prices show in the tenant's currency format for the viewer's language.

#### REQ-CAT-021 — Charge-back information

Fulfilled requests carry the cost and the department or cost centre to charge (from the
requested-for person or a form question), so that charge-back reports by department, cost
centre and item can be built (file 09).

- **Decision:** NEW. product-plan asks for native charge-back; ServiceDesk Plus has none.
- **Source:** product-plan §5 (native pricing and charge-back); architecture §2.2 (charge-back information)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A fulfilled request records the charge department at fulfilment, and later moves of the
     person do not change it.
  2. The charge-back data for a month can be exported by department and item.

#### REQ-CAT-022 — Quantity and request limits per item

An item can allow a quantity with a maximum, and can limit how often a person may request it
(for example one laptop per person per two years). A request over the limit is refused, or
allowed with an extra approval stage, as the item says.

- **Decision:** NEW.
- **Source:** product-plan §5 (store-style catalog); architecture §2.2
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A second laptop request within the limit period is refused with a message naming the
     earlier request, when the item says "refuse".
  2. With "extra approval", it is accepted and gets the extra stage.

#### REQ-CAT-023 — Bundles

A bundle is a catalog item made of other items, for example "new starter: laptop, email
account, building badge". The requester fills one form; questions shared by the items are
asked once. Submitting creates an order with one service request per item (REQ-SR-013). Items
can be optional in a bundle.

- **Decision:** NEW. product-plan asks for bundles; ServiceDesk Plus has none.
- **Source:** product-plan §5 (service catalog: bundles)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Submitting the "new starter" bundle creates one order and three service requests, each
     with the shared answers.
  2. Unticking an optional item in the bundle creates no request for it.
  3. A bundle that contains an item the requester may not see is offered without that item,
     and the requester is told.

---

## 9. Publishing, versions, ordering and search

#### REQ-CAT-024 — Draft, preview, publish and retire

An item is built as a draft. The admin previews it in the portal as a chosen requester (with
that person's audience and language) before publishing. Publishing can be immediate or
scheduled; retiring can also be scheduled. A retired item is no longer offered, but its
requests keep working.

- **Decision:** BETTER. ServiceDesk Plus has only an on/off switch, and its portal preview
  shows the technician's view, not a requester's.
- **Source:** sdp-area-03 §Behaviour (portal preview renders as the technician), §Weak spots; sdp-area-12 §Actions (disable)
- **SDP weak spot fixed:** the admin cannot check what requesters actually see without
  creating a real requester login.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Previewing a draft as requester R shows exactly the form R would see, with technician
     fields absent, and nothing can be submitted from the preview.
  2. An item scheduled to publish at 08:00 appears in the portal at 08:00 with no refresh.
  3. A retired item disappears from browse and search, and its open requests continue.

#### REQ-CAT-025 — Item versions

Each publish creates a new version of the item. A request keeps the version it was submitted
with: its form, approval settings and fulfilment plan. The admin can compare two versions and
restore an earlier one as a new draft.

- **Decision:** NEW. In ServiceDesk Plus a template change applies to everything at once and
  has no version history.
- **Source:** architecture §6.6 (versioned metadata), §3 (P5)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A request submitted on version 3 keeps version 3's approval stages after version 4 adds
     a stage.
  2. The version comparison lists added, removed and changed questions, stages and tasks.
  3. Restoring version 2 creates a draft equal to version 2; nothing changes until it is
     published.

#### REQ-CAT-026 — Optional second-person check before publishing

A tenant can require that a second admin approves an item before it is published, as for
announcements (D-032). Off by default.

- **Decision:** NEW.
- **Source:** D-032 (four-eyes publishing pattern); architecture §11 (least privilege)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. With the setting on, the author cannot publish their own change; a second admin can.
  2. The approval of the publish is recorded in the item's history.

#### REQ-CAT-027 — Order and featured items

Admins set the order of categories and of items inside a category by dragging, and can mark
items as featured. The portal home shows featured items and the most requested items for the
viewer's audience.

- **Decision:** SAME. ServiceDesk Plus lets admins reorder templates in its catalog view; we
  add featured and most requested items.
- **Source:** sdp-area-03 §Screens (customize catalog: drag reorder), §Fields (move-template popup: before or after)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Dragging an item to the top of its category shows it first in the portal, live.
  2. Reordering works with the keyboard as well as by dragging.
  3. "Most requested" counts only items the viewer may see.

#### REQ-CAT-028 — Catalog search

Requesters and technicians search the catalog by name, summary, description, keywords and
synonyms, in their language. Search tolerates small typos, ignores Arabic diacritics and
letter variants, and ranks by relevance and popularity. Results respect visibility
(REQ-CAT-014, REQ-CAT-015).

- **Decision:** BETTER. ServiceDesk Plus searches templates by name; we add synonyms, typo
  tolerance and Arabic normalisation.
- **Source:** sdp-area-03 §Screens (create a service request modal: template search); architecture §2.2 (store-style browsing and search); D-006
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Searching "pasword" finds the item "Password reset".
  2. Searching a synonym the admin added ("notebook" for "laptop") finds the laptop item.
  3. An Arabic search finds the item whether or not the query has diacritics.
  4. Results return within 500 ms (p95) for a catalog of 1,000 items.

#### REQ-CAT-029 — Business and technical catalog views

The catalog has two views: the business view of services as requesters understand them, and
the technical view for technicians, which also shows technician-only items, the business
service each item belongs to and the linked configuration items (file 07).

- **Decision:** SAME.
- **Source:** architecture §2.2 (business and technical catalog views)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. The technical view lists technician-only items; the business view in the portal never
     does.
  2. An item linked to a business service shows that service in the technical view.

#### REQ-CAT-030 — Catalog figures

For each item and category the system records requests, approval time, rejection rate,
fulfilment time against SLA, abandoned forms and satisfaction, for reports and dashboards
(file 09). The item page shows its own figures for the last 90 days.

- **Decision:** NEW.
- **Source:** product-plan §5 (self-service: deflection analytics); architecture §2.8
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. The item page shows request count, median approval time and median fulfilment time for
     the last 90 days.
  2. A form opened and left without submitting counts as abandoned.

#### REQ-CAT-031 — Export and import catalog items

Admins can export items and categories (with forms, approvals, plans and translations) to a
file and import them into another tenant or environment, with a preview of what will change.
Config-as-code promotion is part of this.

- **Decision:** NEW. ServiceDesk Plus moves configuration only through its sandbox.
- **Source:** architecture §17 (Stage 3: config-as-code); product-plan §8 (config-as-code); sdp-area-13 §Navigation (sandbox)
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. Exporting an item and importing it into an empty tenant creates the same item as a draft.
  2. The import preview lists references it cannot resolve (for example a missing group).

#### REQ-CAT-032 — Catalogs per customer (MSP)

For managed service providers, each customer organisation can have its own catalog items,
prices and branding, and see only its own catalog.

- **Decision:** SAME. ServiceDesk Plus sells this as a separate MSP product.
- **Source:** architecture §2.15 (MSP: per-customer catalogs); product-plan §5 (multi-site and MSP)
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. A requester of customer A never sees customer B's items or prices.
  2. An item can be shared with several customers with a different price per customer.

---

## 10. The portal shell and home

#### REQ-PRT-001 — Portal application and navigation

The portal is a separate, lightweight web app for requesters, served on the same host as the
console under its own path (D-038). Its main areas are home, catalog, my requests, approvals,
knowledge and announcements, plus the notification centre (REQ-INC-131) and the profile.
Areas the person cannot use (for example approvals for someone who never approves) are not
shown. Technicians can open the portal too, and see it as a requester would.

- **Decision:** SAME.
- **Source:** sdp-area-03 §Screens (portal preview: home, requests, solutions); sdp-area-13 §Navigation & Footer Settings (requester view tabs); architecture §9.1, §2.15 (self-service portal); D-038
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A requester signing in lands on the portal home, never on the console.
  2. A technician opening the portal sees requester screens, with no technician fields or
     actions.
  3. A requester with no pending or past approvals sees no approvals entry; it appears live
     when their first approval arrives.

#### REQ-PRT-002 — Portal home

The home page has:

- a greeting and one search box (REQ-PRT-003);
- three clear starting points: report an issue, request something, find an answer;
- featured and most requested items (REQ-CAT-027);
- a summary of the person's open requests by state, their pending approvals and their open
  tasks;
- current announcements (REQ-PRT-009);
- their assets with a "report an issue" action (REQ-PRT-011), when the tenant has assets.

Counts and lists update live.

- **Decision:** BETTER. Same content as the ServiceDesk Plus portal home; counts update live
  instead of on reload.
- **Source:** sdp-area-03 §Screens (portal home: three cards, global search, my summary, announcements with follow, my assets with report an issue); architecture §8.1 (portal channel), §2.15
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. When a technician resolves one of the requester's requests, the home summary changes
     within one second with no refresh.
  2. "Report an issue" opens the incident path (REQ-INC-028); "request something" opens the
     catalog; "find an answer" opens knowledge search.
  3. A new tenant's home shows sensible content with no admin set-up.

#### REQ-PRT-003 — One search box for everything

One search box looks through catalog items, knowledge articles, announcements and the
person's own requests, and shows grouped results. The admin chooses which sources are
searched and their order (Appendix A). If nothing matches, the person can report an issue
with the search text already filled in as the subject.

- **Decision:** BETTER. ServiceDesk Plus has the same sources and ordering; we add the
  no-result path to a request.
- **Source:** sdp-area-13 §Requester Portal (portal search: announcements, solutions, request templates, requests, orderable); sdp-area-03 §Config (portal search scope)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A search returns items, articles, announcements and the person's requests in separate
     groups, in the admin's order.
  2. Results never include another person's requests, hidden items or unpublished articles.
  3. "Nothing found? Report an issue" opens the incident form with the search text as the
     subject.

#### REQ-PRT-004 — Browse the catalog

The catalog page shows categories as tiles and their items as cards with name, summary,
icon, "needs approval" and expected delivery, and price when shown (REQ-PRT-031). Category
pages have a breadcrumb back to the top. "Report a problem" entries (REQ-CAT-003) are marked
as such.

- **Decision:** BETTER. In ServiceDesk Plus the catalog opens as a modal with a category list
  that leaves out the general incident templates.
- **Source:** sdp-area-03 §Screens (create a service request modal: template search, category list without the general incident category); architecture §2.2 (store-style browsing)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Opening a category shows its items and sub-categories with a breadcrumb.
  2. An item card shows "needs approval" when the item has an approval stage.
  3. Browsing works with the keyboard alone and with a screen reader.

#### REQ-PRT-005 — Submit a request in the portal

The item page shows its description, help card, related articles and the form in the
requester layout. The requester chooses "for me" or "for someone else" (REQ-SR-011), answers
the questions, attaches files and submits. Validation is the same as on the server, and a
double click never creates two requests (REQ-WI-008). Unsent drafts (REQ-INC-019) and keeping
answers when switching to another item (REQ-INC-039) apply here when they ship at V1.

- **Decision:** SAME.
- **Source:** sdp-area-03 §Screens (switch template link), §Fields (service template form); sdp-area-02b §Weak spots (first click did nothing); REQ-INC-019, REQ-INC-039, REQ-WI-008
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A requester submits an item with one required question and an attachment and gets the
     SR number.
  2. Pressing submit twice quickly creates one request.
  3. The form never shows technician-only fields (group, technician, priority unless the item
     allows it).

#### REQ-PRT-006 — After submitting, say what happens next

After submitting, the portal shows the request number and what happens next in plain words:
who must approve it (unless hidden), the expected delivery date, and where to follow it. It
offers to view the request, make another request or go home.

- **Decision:** BETTER. ServiceDesk Plus confirms "request added" with view, create another and
  close, but says nothing about next steps.
- **Source:** sdp-area-03 §Screens (post-submit screen), §Actions (post-submit buttons)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Submitting an item that needs manager approval shows "waiting for approval from your
     manager" with the manager's name.
  2. The screen shows the expected delivery date when the item has an SLA.
  3. The acknowledgement email says the same things in the requester's language.

#### REQ-PRT-007 — My requests

"My requests" lists the person's incidents and service requests together, with filters for
type, open or closed, and status, plus search and sort. Depending on their permission it can
also show requests of their site, department, direct reports, everyone, and requests shared
with them (REQ-INC-056). Rows update live. Each row shows the number, subject, item, status
label, last update and, for service requests, approval and progress.

- **Decision:** SAME. The ServiceDesk Plus portal preview showed the full technician list; the
  requester's own scoped list is the requirement.
- **Source:** sdp-area-03 §Behaviour (portal requests page showed the full technician list); sdp-area-11 §Fields (requester view permissions, direct reportees); sdp-area-02a §Screens (shared requests); REQ-INC-147
- **SDP weak spot fixed:** the portal "requests" page was the technician list, not the
  requester's own.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A requester with "own" scope sees only requests where they are requested by, requested
     for or on behalf of.
  2. A manager with "direct reports" sees their reports' requests under a separate filter.
  3. A status change by a technician updates the row within one second.
  4. A requester's live connection never receives an event about a request they cannot see.

#### REQ-PRT-008 — Approvals inbox

People who approve have an approvals page in the portal: pending approvals first, then
decided ones. Each opens the approval page (REQ-SR-025). They can approve several at once
with one comment, after a confirmation that lists them, up to a limit (Appendix A). Delegated
approvals are marked. The count updates live.

- **Decision:** SAME. ServiceDesk Plus offers approvals to requesters; bulk approval with a
  confirmation is our addition.
- **Source:** architecture §2.15 (my requests and approvals); sdp-area-01 §Screens (my pending approvals drawer); sdp-area-11 §Fields (service request approvers as an editor list)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Approving three requests at once records three decisions with the same comment, after a
     confirmation that names all three.
  2. Bulk reject is not offered; each rejection needs its own reason.
  3. A request withdrawn by its requester disappears from the inbox live.

#### REQ-PRT-009 — Announcements in the portal

Current announcements for the person's audience show as banners and in an announcements list
(module `announcements`, ADR-024). A scheduled announcement appears and ends on time with no
reload (D-032). People can dismiss a banner and follow an announcement to get its updates.

- **Decision:** SAME.
- **Source:** sdp-area-03 §Screens (portal announcements with follow); sdp-area-13 §Announcement and Maintenance (announcement types); D-032; ADR-024; REQ-INC-129
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. An announcement published for site Riyadh shows to Riyadh requesters within one second
     and not to others.
  2. A dismissed banner stays dismissed for that person on every device.
  3. Following an announcement notifies the person when it is updated or ended.

#### REQ-PRT-010 — Knowledge in the portal

The portal shows knowledge articles published for the person's audience: browse by topic,
search, read, rate as helpful or not, and comment when allowed. The knowledge module itself is
file 08; the tenant can hide knowledge from requesters.

- **Decision:** SAME.
- **Source:** sdp-area-08 §Config (publish in self-service portal, user groups, hide solutions from requesters); sdp-area-03 §Screens (portal solutions); architecture §2.15
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. An article published for "All users" is readable in the portal; an unpublished one is not
     found.
  2. Marking an article "not helpful" offers to report an issue with the article linked.

#### REQ-PRT-011 — My assets

The portal lists the assets assigned to the person. From an asset they can report an issue
or request something about it, with the asset filled in. They can confirm receipt of an
asset when asset acknowledgement is on (file 07).

- **Decision:** SAME.
- **Source:** sdp-area-03 §Screens (my assets with report an issue); sdp-area-07 §Actions (raise request from asset); sdp-area-07 (7b) §Config (asset acknowledgement); REQ-INC-029
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. "Report an issue" on an asset opens the incident form with the asset linked.
  2. An asset assigned to the person appears in the list within one second.
  3. Confirming receipt records the acknowledgement on the asset with the person as actor.

#### REQ-PRT-012 — Pending surveys

Satisfaction surveys sent for closed requests (REQ-INC-103) are listed in the portal until
answered or expired, and can be answered there in the person's language. Survey design is in
file 11.

- **Decision:** SAME.
- **Source:** sdp-area-13 §Surveys; REQ-INC-103
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A survey sent for SR-9 appears under "pending surveys" and disappears when answered,
     including when answered from the email.
  2. The survey shows in Arabic for an Arabic-speaking requester.

#### REQ-PRT-013 — Profile and preferences

Requesters see their profile and, if the tenant allows, edit their contact details. They set
their language, time zone and notification preferences, and name an approval delegate
(REQ-SR-035).

- **Decision:** SAME. ServiceDesk Plus has "allow requesters to edit their profile".
- **Source:** sdp-area-13 §Requester Portal (allow requesters to edit their profile); sdp-area-01 §Screens (preferences: language, time zone)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Changing the language to Arabic switches the portal to Arabic right-to-left at once.
  2. With profile editing off, contact fields are read-only and the API refuses changes.
  3. Fields synced from the identity provider are read-only with a note saying where they come
     from.

#### REQ-PRT-014 — Other records in the portal

Requesters can see other records they are part of, where the module is licensed: changes
they requested or must approve, projects they are members of and releases they are told
about (files 05 and 06). Approvals for those records use the same approvals inbox.

- **Decision:** SAME. The ServiceDesk Plus requester view has tabs for changes, projects and
  releases.
- **Source:** sdp-area-13 §Navigation & Footer Settings (requester view: dashboard, requests, changes, projects, releases, solutions, assets)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A requester who must approve a change sees it in the approvals inbox.
  2. A requester sees only changes they requested or approve, never the full change list.

#### REQ-PRT-015 — Requester reminders

When the tenant allows it, requesters can set personal reminders on their own requests
(REQ-INC-082).

- **Decision:** SAME. ServiceDesk Plus has "enable reminders for requesters", off by default.
- **Source:** sdp-area-13 §Requester Portal (enable reminders for requesters); REQ-INC-082
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. With the setting on, a requester can add a reminder on their request and is notified at
     the set time.
  2. With the setting off, the reminder action is not shown.

---

## 11. Branding, layout, languages, accessibility and mobile

#### REQ-PRT-016 — Tenant branding and domains

Each tenant brands its portal: logo, favicon, colours, portal name and welcome text, on light,
dark and high-contrast themes, applied to the portal, the sign-in page and emails (D-027). The portal is
reached on the tenant's subdomain, or a custom domain with automatic certificates. The admin
previews the branding before saving. Colours that fail the contrast check are refused.

- **Decision:** SAME. ServiceDesk Plus has theme settings and custom service URLs.
- **Source:** D-027; sdp-area-13 §Theme Settings; sdp-area-14 §Screens (custom service URLs); architecture §9.1 (brandable per tenant), §9.4 (brand colours via tokens)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Uploading a logo and a brand colour changes the portal, sign-in page and notification
     emails, and open portal sessions pick it up without a reload.
  2. A brand colour with text contrast below WCAG AA is refused with a message.
  3. A custom domain serves the tenant's portal with a valid certificate, and requests to it
     resolve to that tenant only.

#### REQ-PRT-017 — Home layouts per audience

Admins arrange the portal home from ready-made blocks (search, starting points, featured
items, a category, my summary, announcements, popular articles, my assets, a text and links
block) and can make different layouts for different audiences (for example a layout for
the HR team), with branding per department. Each layout has a draft, a preview as a chosen
person and publish.

- **Decision:** BETTER. ServiceDesk Plus offers portal pages built with a GUI or with code, per
  access level; we keep the layouts per audience without code.
- **Source:** sdp-area-03 §Screens (requester portal customisation: pages, access level, builder type), §Actions (preview, edit, configure, copy, set as default, delete, organise); architecture §2.15 (portal widgets and layouts per audience), §9.1 (brandable per department)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A layout for audience "HR team" shows to its members; everyone else gets the default.
  2. A person who matches two layouts gets the one with the higher order, as set by the admin.
  3. Editing a draft layout does not change the live portal until it is published.

#### REQ-PRT-018 — No code-based portal pages

Admins cannot upload their own HTML or scripts as portal pages. The block layouts
(REQ-PRT-017) and branding (REQ-PRT-016) replace them.

- **Decision:** SKIP. Code pages are a cross-site scripting and upgrade risk, break
  right-to-left and accessibility, and cannot be checked for labels (architecture §11, §9.5).
- **Source:** sdp-area-03 §Screens (portal page builder type: code based), §Fields (new portal page)
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. No admin setting stores HTML or script code that the portal renders as-is.
  2. A text block's content is sanitised on the server; script tags are removed.

#### REQ-PRT-019 — Navigation and footer links

Admins choose which portal areas show in the navigation and in what order (home stays first),
and add footer links such as the support phone number or a privacy notice.

- **Decision:** SAME.
- **Source:** sdp-area-13 §Navigation & Footer Settings (requester view tabs, footer menus)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Hiding "knowledge" removes it from the portal navigation for everyone, live.
  2. Footer link text has per-language values.

#### REQ-PRT-020 — Languages and right-to-left in the portal

The portal shows in the person's language: from their profile, else the browser, else the
tenant default. Pages before sign-in have a language switch. English and Arabic with
right-to-left are complete at MVP; Urdu from V1 (D-006, D-048). Admin content (items,
announcements, layouts) shows in the chosen language with English as fallback. The tenant
admin chooses which languages the portal offers.

- **Decision:** BETTER. ServiceDesk Plus charges more for multiple languages on-prem; every
  language is included here.
- **Source:** D-006, D-048; architecture §9.5, §2.15 (multi-language incl. Arabic and Urdu with RTL); product-plan §9.1; REQ-WI-013
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Every portal screen passes the e2e suite in Arabic with right-to-left layout.
  2. The sign-in page offers the tenant's languages and remembers the choice.
  3. CI fails if a portal string lacks an English label or Arabic translation.

#### REQ-PRT-021 — Accessible portal

Every portal screen meets WCAG 2.2 AA (REQ-WI-023): full keyboard use, screen reader labels,
visible focus, contrast, reduced motion, and text that can be enlarged to 200% without loss.

- **Decision:** BETTER. ServiceDesk Plus offers personal accessibility switches; we build the
  standard in.
- **Source:** architecture §9.4; sdp-area-01 §Config (accessibility toggles); REQ-WI-023
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. The automated accessibility check reports no serious or critical issues on home,
     catalog, item form, my requests and approvals, in English and Arabic.
  2. A requester can find an item, submit it and approve a request with the keyboard only.
  3. At 200% zoom no content or action is cut off.

#### REQ-PRT-022 — Mobile-first portal

The portal is designed for phones first: every screen works from 360 pixels wide with touch
targets of at least 44 pixels, and forms, attachments (including the camera) and approvals
work on a phone. It can be added to the home screen.

- **Decision:** NEW. architecture asks for a mobile-first portal.
- **Source:** architecture §9.1 (self-service portal: mobile-first)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. The e2e suite for submitting a request and approving one passes at 360 x 740 pixels.
  2. No portal page scrolls sideways at 360 pixels.
  3. A photo taken with the phone camera can be attached to a request.

#### REQ-PRT-023 — The portal loads fast on a phone

On a mid-range phone over a 4G connection, the portal home shows its main content within 2.5
seconds and responds to input within 200 milliseconds (p75).

- **Decision:** NEW.
- **Source:** architecture §9.1 (lightweight portal), §1.3 (design targets)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A lab test with mobile throttling measures largest contentful paint at or below 2.5 s on
     the home page.
  2. The portal's first-load script size stays under the budget set in CI, and the build fails
     above it.
  3. While data loads, pages show placeholders in the final layout, never a blank screen.

---

## 12. Access: sign-in, registration and guests

#### REQ-PRT-024 — Requester sign-in

Requesters sign in through the tenant's identity set-up (local accounts, the directory, or
single sign-on, file 11), on a sign-in page with the tenant's branding. A link in a
notification email takes a signed-in person straight to the record, and a signed-out person to
sign-in and then to the record.

- **Decision:** SAME. ServiceDesk Plus has self-service login per requester.
- **Source:** sdp-area-11 §Fields (enable self-service login); architecture §11.1; D-009, D-010, D-027
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A requester with single sign-on reaches the portal home with no second password prompt.
  2. A link to SR-5 from an email opens SR-5 after sign-in.
  3. A requester without portal access gets a clear message, not an error code.

#### REQ-PRT-025 — Self-registration

When the tenant allows it, people with an email address in an allowed domain can register for
the portal themselves after confirming their address. Off by default.

- **Decision:** SAME. The vendor lets users of verified domains join without an invitation.
- **Source:** sdp-area-14 §Screens (custom domains: join without invitation)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Registering with an allowed domain sends a confirmation link; the account works only
     after it is used.
  2. An address in another domain is refused with a message saying who to contact.

#### REQ-PRT-026 — Public knowledge and announcements without sign-in

A tenant can open selected knowledge articles and announcements to people who are not signed
in, for example status announcements during an outage. Off by default. No request data is ever
shown without sign-in.

- **Decision:** NEW.
- **Source:** architecture §2.15 (self-service portal), §11 (secure by default)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. With the setting on, an article marked "public" opens without sign-in; others redirect to
     sign-in.
  2. With the setting off, every portal page requires sign-in.
  3. The public pages make no API call that returns request or user data.

#### REQ-PRT-027 — Guest requests with email verification

A tenant can let people who have no account submit chosen catalog items or report an issue
as guests. The guest gives their email address and confirms it with a one-time code before
the request is created. They follow the request through emails and a one-time link. Off by
default; limited per address and per network to stop abuse.

- **Decision:** NEW. ServiceDesk Plus requires a requester account or email.
- **Source:** architecture §2.1 (omnichannel logging), §11 (secure by default); REQ-INC-027
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A guest cannot submit until the code sent to their email is entered.
  2. More than the set number of guest requests per address per day is refused.
  3. A guest's request is matched to an existing requester with that email, or creates an
     unverified requester (REQ-INC-027).

---

## 13. The chat entry point

#### REQ-PRT-028 — Assistant as the portal entry point

The portal offers the AI assistant as a starting point: a chat box on the home page and a chat
button on every page. It answers from knowledge articles with citations, finds and fills
catalog items by asking the item's questions (REQ-CAT-008 AC4), reports an issue, shows the
person's open requests and their status, and hands over to a person (REQ-PRT-030) or a
request when it cannot help. It works by text and voice, in English, Arabic and Urdu, with
the person's permissions only. AI administration is file 10; model access follows D-049.

- **Decision:** BETTER. ServiceDesk Plus has a portal chatbot with quick actions (create a
  request, search solutions, my open requests); ours fills real catalog forms and cites its
  sources, on every deployment including a local model.
- **Source:** sdp-area-10 §Screens (chat page quick chips, attachments, voice, help centre mode), §Fields (chatbot available to requesters); sdp-area-14 §Screens (portal chat window quick actions); architecture §9.1 (AI assistant as the landing experience), §2.10 (virtual agent in portal); product-plan §7.2 (RAG answers in the portal with citations); D-049
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Asking "I need VPN access" offers the VPN item and, when confirmed, asks its questions and
     submits a request with the same validation as the form.
  2. Every knowledge answer shows the articles it used as links; with no matching article it
     says so and offers to report an issue.
  3. The assistant never shows an item, article or request the person could not see in the
     portal.
  4. "What is the status of SR-12?" answers only when the person may see SR-12.

#### REQ-PRT-029 — Assistant settings for the portal

The tenant admin chooses whether requesters get the assistant, its name, avatar, welcome
message and quick actions, whether voice input is on, and which sources it may answer from.
The settings page shows a live preview of the chat window. Scripted conversations and the
assistant's actions are set up in file 10.

- **Decision:** SAME. ServiceDesk Plus has chatbot customisation (type, name, theme, avatar,
  welcome message, available to requesters, voice input, external sources).
- **Source:** sdp-area-10 §Fields (chatbot customisation), §Weak spots (external sources not explained); sdp-area-14 §Screens (chatbot customisation preview); REQ-AI-077, REQ-AI-078 (scripted conversations)
- **SDP weak spot fixed:** "search external sources" is offered with no explanation of what
  the sources are.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Turning the assistant off for requesters removes it from the portal live.
  2. The sources setting lists each source by name; none is enabled without the admin choosing
     it.
  3. Welcome message and quick action labels have per-language values.

#### REQ-PRT-030 — Live chat with the service desk

Requesters can chat with a technician from the portal (and from a website widget). The chat
becomes or joins a request with the whole conversation, attachments included. Chat is routed
to groups by topic, and technicians can use reply templates. When no one is available the
person is offered a request instead.

- **Decision:** SAME. ServiceDesk Plus provides live chat through a separate vendor product
  and licence.
- **Source:** sdp-area-14 §Screens (chat settings: separate chat product, representatives, per-group enable, website embed); sdp-area-01 §Screens (live chat in the footer); architecture §2.15 (live chat); REQ-INC-032
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. A chat that a technician turns into a request keeps the full transcript on the request.
  2. With no technician online in the group, the person is offered to submit a request.

---

## 14. Portal settings and preview

#### REQ-PRT-031 — One page of portal settings

All portal behaviour is set on one admin page, in groups with a one-line explanation each:

- **Requests:** requesters may close their own fulfilled or resolved requests; cancel directly
  or ask for cancellation (REQ-INC-148); edit after submitting, for incidents, service
  requests or both; hide the default incident template; whether technicians can also be
  requesters.
- **People:** who a requester may request on behalf of (REQ-SR-011); who they may add when
  replying or as followers; whose requests they may see (own, site, department, all, direct
  reports).
- **Approvals and cost:** show approvals to requesters; show cost to requesters; show cost to
  approvers.
- **Assets:** show only the person's own assets in questions; add the requester's assets to
  requests from email.
- **Portal:** search sources and order; profile editing; requester reminders; knowledge
  visible; public pages (REQ-PRT-026); guest requests (REQ-PRT-027); self-registration
  (REQ-PRT-025).

Every setting has a default (Appendix A) and a link to preview its effect (REQ-PRT-032).

- **Decision:** BETTER. ServiceDesk Plus splits portal behaviour across three settings pages
  with no explanation of which controls what, and repeats a reopen setting twice.
- **Source:** sdp-area-03 §Config (requester portal settings, advanced portal settings), §Weak spots; sdp-area-13 §Requester Portal, §Advanced Portal Settings
- **SDP weak spot fixed:** portal settings live in three places with no explanation, and two
  nearly identical reopen settings appear on one page.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Every portal setting listed is on one page, and the admin search finds each by name.
  2. Changing a setting takes effect in open portal sessions without a reload.
  3. Each setting change is recorded in the audit log with old and new value.

#### REQ-PRT-032 — Preview the portal as a chosen person

An admin can open the portal as a chosen requester, read-only: with that person's audience,
language, scope, approvals and settings, but without acting as them. The preview is clearly
marked and nothing can be submitted, approved or changed from it. It extends the requester
preview of REQ-INC-147 AC4 to the whole portal.

- **Decision:** BETTER. The ServiceDesk Plus portal preview renders as the signed-in
  technician, with technician fields on forms and the full request list.
- **Source:** sdp-area-03 §Behaviour (preview renders as the technician; no log-in-as option), §Weak spots; REQ-INC-147
- **SDP weak spot fixed:** the portal preview is not a requester view, so admins cannot check
  what requesters see.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Previewing as a Sales requester hides items limited to Finance and shows only that
     person's requests.
  2. Submit, approve and reply are disabled in the preview, and the API refuses writes from a
     preview session.
  3. Each preview is recorded in the audit log with the admin and the person previewed.

#### REQ-PRT-033 — Department desks in one portal

With department desks (file 12), one portal serves every desk: one search, one catalog
grouped by desk, one "my requests" across desks, with each desk's branding on its own pages.
The admin chooses whether the portal opens on the shared home or on a chosen desk.

- **Decision:** SAME. The vendor's enterprise service portal has a central portal with a
  preferred landing page.
- **Source:** sdp-area-14 §Screens (ESM portal: customise, preview, publish, preferred landing page); sdp-area-01 §Screens (ESM portal link); architecture §2.15 (unified portal)
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. A requester's "my requests" lists their IT and HR requests together.
  2. Searching "leave" finds the HR desk's item from the shared home.
  3. HR desk pages show the HR desk's branding.

---

## Appendix A — Proposed defaults (for product owner approval)

These are the defaults a new tenant gets. They are seed data, not fixed behaviour: a tenant
admin can change every one of them (D-041). The requirements above refer to this appendix.

**Service request statuses** (REQ-SR-004). Statuses not listed here are as in file 01
Appendix A.

| Status | Category | Reason needed to enter |
|---|---|---|
| new | open | no |
| awaiting approval (system only) | paused | set by the approval |
| assigned | open | no |
| in progress | open | no |
| awaiting requester | paused | yes |
| awaiting third party | paused | yes |
| fulfilled | resolved | fulfilment note required (built from the tasks when automatic) |
| closed | closed | closure code required |
| rejected (system only) | closed | rejection reason from the approver |
| canceled | canceled | yes (cancel or withdraw reason) |

**Allowed transitions:**

| From | To |
|---|---|
| new | awaiting approval (system), assigned, in progress, canceled |
| awaiting approval | new or assigned (system, on approval), rejected (system, on rejection), canceled (withdraw) |
| assigned | new (unassign), in progress, awaiting requester, awaiting third party, fulfilled, canceled |
| in progress | awaiting requester, awaiting third party, fulfilled, canceled |
| awaiting requester | in progress, fulfilled, canceled |
| awaiting third party | in progress, fulfilled, canceled |
| fulfilled | closed, in progress (reopen) |
| closed | in progress (reopen, permission and reopen window rules as for incidents) |
| rejected | none (the requester can request again, REQ-SR-016) |
| canceled | the previous status (undo cancel, permission) |

**Automatic moves:** submitted with approval needed → awaiting approval; final approval →
assigned if a group or technician is set, else new; rejection → rejected; last required
fulfilment task completed → fulfilled (REQ-SR-058); fulfilled → closed on the requester's
confirmation or after 3 business days without an answer (REQ-SR-059).

**Priority and SLA** (REQ-SR-005 to 007):

- priority: the item's default, else P3 marked as defaulted; requesters cannot set it;
- SLA order: the item's SLA, then the SLA rules, then the tenant's default service request
  SLA;
- default service request SLA: first response within 8 business hours, fulfilment within 5
  business days;
- while awaiting approval the fulfilment clock is paused and the response clock runs.

**Assignment** (REQ-SR-008): the fulfilment group is set at creation; for items that need
approval the technician is set after approval.

**Approvals** (REQ-SR-021 to 043):

- email approval links expire after 7 days; sign-in for email approvals is off;
- a rejection needs a reason; an approval comment is optional;
- other approvers in a stage are told when one has acted;
- self-approval is off;
- requesters see approval progress, with approver names and public comments;
- reminders: the first after 2 business days without a decision, then one each business day
  at 10:00 in the approver's time zone, 3 reminders in all;
- after the last reminder: escalate to the stage's backup approver, else the approver's
  manager; the fulfilment group is notified either way;
- fallback approvers (REQ-SR-023): an "approval administrators" group, seeded with the tenant
  admins;
- approval restart (REQ-SR-041): on for quantity, priced options and the requested-for person;
- bulk approval in the portal: up to 25 at once.

**Fulfilment and closing** (REQ-SR-046 to 061):

- move to fulfilled when the last required task completes: on;
- closing with open fulfilment tasks: blocked;
- auto-close after fulfilment with no answer from the requester: 3 business days;
- a requester can always withdraw a request that is awaiting approval.

**Portal settings** (REQ-PRT-031):

| Setting | Default |
|---|---|
| Requesters may confirm and close their own fulfilled or resolved requests | on |
| Cancel after approval | ask for cancellation (the technician decides) |
| Edit answers after submitting | off |
| Hide the default incident template from requesters | off |
| Technicians can also be requesters | on |
| Request on behalf of | same department, plus the person's direct reports |
| People a requester may add when replying or as followers | same department |
| Requests a requester sees | own; managers also see their direct reports' requests |
| Show approvals to requesters | on |
| Show cost to requesters | off |
| Show cost to approvers | on |
| Only the person's own assets in asset questions | on |
| Add the requester's assets to requests from email | off |
| Search sources, in order | catalog items, knowledge, announcements, my requests |
| Requesters edit their profile | on (fields from the identity provider stay read-only) |
| Requester reminders | off |
| Knowledge visible in the portal | on |
| Public pages without sign-in | off |
| Guest requests | off |
| Self-registration | off |
| Assistant for requesters (once AI is set up) | on |

**Limits:**

- items in a cart or a bundle: 20 (REQ-SR-013, REQ-CAT-023);
- rows in a repeating question group: 50 (REQ-CAT-010);
- guest requests per email address per day: 3 (REQ-PRT-027);
- catalog search results per group in the portal: 10, with "show more" (REQ-PRT-003).

**Starter catalog** (REQ-CAT-007), in English and Arabic. Items marked (A) have a manager
approval stage.

| Category | Items |
|---|---|
| Accounts and access | New user account (A); Access to an application or shared folder (A); Remove access for a leaver |
| Devices | New laptop or desktop (A); Monitor, keyboard or other accessory; Mobile phone (A) |
| Software | Install approved software; New software licence (A) |
| Email and collaboration | Shared mailbox; Change to a mailing list |
| Workplace | Desk or office move |
| Report an issue (incident templates) | Something is not working; I cannot sign in |

---

## Open questions for the product owner

1. **Catalog edition.** product-plan §9 puts "service catalog" in Professional, while
   Essentials has "incident and request, portal and KB". This file puts the catalog basics in
   Essentials (categories, items, forms, one approval stage, per-item SLA, group and an
   ordered task list), because a requester cannot raise a service request in the portal
   without them. Professional adds multi-stage, parallel and conditional approvals, audience
   rules, cost and charge-back, bundles and carts, versions, task dependencies and
   workflows. Agree with this line?
2. **Approvals at MVP.** Service request approval (one stage, in the app and by email link) is
   MVP here, because the Stage 1 go-live includes requests and catalog basics. REQ-INC-083
   (approvals on incidents) is V1 in file 01, but it is the same engine. Should REQ-INC-083
   move to MVP, or stay V1 with only service requests using approvals at MVP?
3. **Email approvals without sign-in.** One-time email links let an approver decide without
   signing in (REQ-SR-026). Is that acceptable for banks and government customers by default,
   or should sign-in be required by default, at least above a cost threshold?
4. **Mobile approvals.** REQ-SR-039 is V1 because architecture §17 puts the mobile app in
   Stage 2. File 01 has the technician mobile app as LATER (REQ-INC-149). Is the mobile app
   (at least for approvals) V1 or LATER?
5. **Portal assistant timing.** product-plan §7.2 lists portal answers with citations in its
   Phase 1, but architecture §17 puts the AI gateway in Stage 2 and wins (D-002). The
   assistant is V1 here (REQ-PRT-028). Confirm.
6. **Guests and public pages.** REQ-PRT-026 and REQ-PRT-027 (public knowledge, guest requests
   with email verification) are V1 and off by default. Do target customers need them at all,
   and if so is V1 right?
7. **Order model for carts and bundles.** Proposed: one parent order with one service request
   per item, each with its own approvals and fulfilment (REQ-SR-013). The alternative is one
   service request with line items. Agree with the parent order model?
8. **Request ownership delegation.** The vendor's delegation page covers approvals and the
   handover of a technician's requests while they are away. Approval delegation is here
   (REQ-SR-035). Should ownership delegation go to file 03 (assignment)?
9. **Announcements authoring.** The portal shows announcements (REQ-PRT-009), and file 01 has
   "announce from an incident" (REQ-INC-129). No parity file owns the announcements module
   itself (audiences, types, scheduling, four-eyes publishing, D-032). Should file 11 own it?
   *Proposed answer in file 11:* file 11 owns announcement authoring (REQ-ADM-077 to
   REQ-ADM-084).
10. **Requester-side research gap.** The research never signed in as a requester (Area 3
    could not; the planned Area 15 does not exist). The portal requirements come from the
    vendor's settings pages, its admin preview and our specs. Should a short requester-login
    research pass happen before the first portal work package?
11. **Default service request SLA.** Appendix A proposes first response within 8 business
    hours and fulfilment within 5 business days. Please confirm or give the figures Extravis
    support uses today.
12. **Prices in more than one currency.** REQ-CAT-020 shows prices in the tenant's currency.
    The vendor keeps a currency list with exchange rates. Do catalog prices need several
    currencies (for example per site), and at what priority?
