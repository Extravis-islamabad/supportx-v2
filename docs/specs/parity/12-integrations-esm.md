# 12 — Integrations and enterprise service management

Parity requirements for integrations (architecture.md §2.14, §6.8), the public API and
webhooks (§10), the MCP server (§10, §2.10), native live chat (§2.15) and enterprise service
management with department desks (§2.15, §7.2). Rules, ID scheme and field meanings:
[README.md](README.md).

**Status:** Draft v0.1, 2026-10-24. Phase 2, first draft for product owner review.
**Owner:** Haider (Product Owner).

## Scope of this file

- **REQ-INT-*** are integration requirements, built in the `integrations` and
  `monitoring_integrations` modules:
  - the connector framework every connector uses: catalogue, enable and disable, credentials,
    health, sync logs, retries, rate limits and audit;
  - the public REST API, API keys and OAuth clients, outbound and inbound webhooks, and the
    generic alert webhook set-up;
  - each connector: MonetX, email, Microsoft Teams and Slack, identity directories, calendars,
    DevOps tools, endpoint tools, AgentX and PatchX, telephony, WhatsApp and SMS, automation
    platforms, the BI connector, knowledge sources and AI providers;
  - the intranet relay agent, extensions, the MCP server as an API surface and native live
    chat.
- **REQ-ESM-*** are enterprise service management requirements, built in the `esm` module:
  department desks inside one tenant, isolation and delegated administration between desks,
  work across desks, HR case management and facilities (spaces, bookings, visitors,
  maintenance).
- **What other files own, and this file only connects to:**
  - how an incident uses email, MonetX and the alert webhook (file 01: REQ-INC-023 to
    REQ-INC-032, REQ-INC-145, REQ-INC-146);
  - approvals from Teams and Slack (REQ-SR-040, REQ-CHG-051), automated fulfilment
    (REQ-SR-055), orchestration across desks (REQ-SR-057) and the shared portal
    (REQ-PRT-033), and the requester's side of live chat (REQ-PRT-030) (file 02);
  - the webhook action, connections, custom functions, custom menus and runbooks (file 03:
    REQ-RUL-014 to REQ-RUL-024, REQ-RUL-032), the SMS channel (REQ-NTF-006);
  - MonetX health on changes (REQ-CHG-085 to REQ-CHG-087), DevOps links on changes and
    releases (REQ-CHG-115, REQ-REL-042 to REQ-REL-045);
  - topology import and live health on the CMDB (REQ-CMDB-012 to REQ-CMDB-014), endpoint
    inventory reconciliation (REQ-DSC-013, REQ-DSC-024), remote control (REQ-AST-057);
  - external knowledge sources (REQ-KB-061), the BI connector and cross-desk reports
    (REQ-RPT-060, REQ-RPT-064), MonetX wallboard widgets (REQ-DSH-035);
  - the AI gateway, AI provider set-up and keys (REQ-AI-006, REQ-AI-007, REQ-AI-009,
    REQ-AI-010, REQ-AI-015), model choice per capability, agents, the assistant and the MCP
    server's tools and sign-in (REQ-AI-104 to REQ-AI-107) (file 10, AI);
  - sign-in, SSO and MFA in Keycloak, users, roles, custom modules, import and export, audit
    and privacy (file 11, admin).
- **Monitoring is out of scope** (ADR-017, D-001). The MonetX connector receives problems and
  reads health, problems and topology from the MonetX API, read-only. SupportX never writes to
  MonetX, never polls devices and never correlates or de-duplicates alerts (REQ-INC-146). The
  generic alert webhook keys one alert to one incident; it does no correlation either.
- **Editions** (product-plan §9): the framework, API, webhooks, email, Teams and Slack are
  Essentials; MonetX, DevOps and endpoint connectors and extensions are Professional; department
  desks, the BI connector and HR system connectors are Enterprise. **Timing** (architecture §17): email
  and the API are Stage 1 (MVP); MonetX and most connectors are Stage 2 (V1); ESM is Stage 3
  (LATER).

## Words used in this file

| Word | Meaning |
|---|---|
| Connector | A built-in integration with one outside system, for example MonetX, Teams or Jira. |
| Connection | A saved, encrypted credential to an outside system (REQ-RUL-016). Connectors, webhooks and functions use connections by name. |
| Service identity | The SupportX account a connector or API client acts as. Its permissions limit what it can do, and history shows it as the actor. |
| Sync run | One execution of a connector job (a mailbox fetch, a directory sync, a topology read), with counts and errors. |
| Webhook subscription | An outbound registration: SupportX sends chosen events to an outside URL. |
| Inbound endpoint | A SupportX URL that an outside system calls to create or update records. |
| Relay agent | A small service installed on a customer network that lets SaaS reach internal systems over one outbound connection. |
| Extension | An installable, versioned package that adds configuration, functions, widgets or a connector to a tenant. |
| Department desk | A service desk for one business function (IT, HR, facilities, finance, legal or custom) inside one tenant, with its own configuration and team. |
| Desk admin | A person who administers one desk's configuration without being a tenant admin. |
| Confidential case | A record visible only to named handlers, even inside its own desk. |

## Requirement summary

<!-- summary:start -->
**Counts by decision and priority**

| Decision | MVP | V1 | LATER | Total |
|---|---|---|---|---|
| SAME | 6 | 6 | 22 | 34 |
| BETTER | 8 | 15 | 26 | 49 |
| NEW | 3 | 24 | 24 | 51 |
| SKIP | 0 | 2 | 5 | 7 |
| **Total** | **17** | **47** | **77** | **141** |

Edition (lowest edition that includes it): Essentials 67, Professional 31, Enterprise 43. By prefix: REQ-INT 100, REQ-ESM 41.

| ID | Title | Decision | Priority | Edition |
|---|---|---|---|---|
| [REQ-INT-001](#req-int-001--one-connector-catalogue) | One connector catalogue | BETTER | MVP | Essentials |
| [REQ-INT-002](#req-int-002--set-up-test-enable-and-disable-a-connector) | Set up, test, enable and disable a connector | BETTER | MVP | Essentials |
| [REQ-INT-003](#req-int-003--credentials-kept-in-a-secrets-store) | Credentials kept in a secrets store | SAME | MVP | Essentials |
| [REQ-INT-004](#req-int-004--health-and-last-sync-on-every-connector) | Health and last sync on every connector | BETTER | MVP | Essentials |
| [REQ-INT-005](#req-int-005--failures-are-visible-never-silent) | Failures are visible, never silent | BETTER | MVP | Essentials |
| [REQ-INT-006](#req-int-006--retries-backoff-and-a-dead-letter-list) | Retries, backoff and a dead-letter list | NEW | V1 | Essentials |
| [REQ-INT-007](#req-int-007--respect-outside-rate-limits) | Respect outside rate limits | NEW | V1 | Essentials |
| [REQ-INT-008](#req-int-008--audit-and-call-log-per-connector) | Audit and call log per connector | BETTER | V1 | Essentials |
| [REQ-INT-009](#req-int-009--sync-runs-with-counts-and-drill-down) | Sync runs with counts and drill-down | BETTER | V1 | Essentials |
| [REQ-INT-010](#req-int-010--field-and-value-mapping) | Field and value mapping | SAME | V1 | Essentials |
| [REQ-INT-011](#req-int-011--match-people-across-systems) | Match people across systems | BETTER | V1 | Essentials |
| [REQ-INT-012](#req-int-012--connectors-act-as-a-service-identity) | Connectors act as a service identity | BETTER | MVP | Essentials |
| [REQ-INT-013](#req-int-013--who-may-set-up-integrations) | Who may set up integrations | SAME | MVP | Essentials |
| [REQ-INT-014](#req-int-014--same-connectors-on-saas-on-prem-and-air-gapped) | Same connectors on SaaS, on-prem and air-gapped | NEW | V1 | Essentials |
| [REQ-INT-015](#req-int-015--outbound-network-safety) | Outbound network safety | NEW | V1 | Essentials |
| [REQ-INT-016](#req-int-016--connector-settings-in-configuration-packages) | Connector settings in configuration packages | NEW | LATER | Enterprise |
| [REQ-INT-017](#req-int-017--a-documented-versioned-public-api) | A documented, versioned public API | BETTER | MVP | Essentials |
| [REQ-INT-018](#req-int-018--api-documentation-inside-the-product) | API documentation inside the product | BETTER | V1 | Essentials |
| [REQ-INT-019](#req-int-019--api-keys) | API keys | BETTER | MVP | Essentials |
| [REQ-INT-020](#req-int-020--oauth-clients) | OAuth clients | NEW | V1 | Essentials |
| [REQ-INT-021](#req-int-021--scopes-and-least-privilege) | Scopes and least privilege | NEW | MVP | Essentials |
| [REQ-INT-022](#req-int-022--rate-limits-with-headers) | Rate limits with headers | BETTER | V1 | Essentials |
| [REQ-INT-023](#req-int-023--safe-writes-idempotency-and-versions) | Safe writes: idempotency and versions | NEW | MVP | Essentials |
| [REQ-INT-024](#req-int-024--lists-filters-and-expansions) | Lists, filters and expansions | SAME | MVP | Essentials |
| [REQ-INT-025](#req-int-025--errors-with-stable-codes) | Errors with stable codes | SAME | MVP | Essentials |
| [REQ-INT-026](#req-int-026--bulk-operations-as-jobs) | Bulk operations as jobs | SAME | V1 | Essentials |
| [REQ-INT-027](#req-int-027--change-feed-for-integrations) | Change feed for integrations | NEW | V1 | Essentials |
| [REQ-INT-028](#req-int-028--api-usage-for-admins) | API usage for admins | NEW | V1 | Essentials |
| [REQ-INT-029](#req-int-029--client-libraries) | Client libraries | NEW | LATER | Essentials |
| [REQ-INT-030](#req-int-030--webhook-subscriptions-per-event-type) | Webhook subscriptions per event type | NEW | V1 | Essentials |
| [REQ-INT-031](#req-int-031--signed-deliveries) | Signed deliveries | NEW | V1 | Essentials |
| [REQ-INT-032](#req-int-032--retries-auto-pause-and-alerts) | Retries, auto-pause and alerts | NEW | V1 | Essentials |
| [REQ-INT-033](#req-int-033--delivery-log-and-replay) | Delivery log and replay | NEW | V1 | Essentials |
| [REQ-INT-034](#req-int-034--ordering-and-delivery-guarantees-documented) | Ordering and delivery guarantees, documented | NEW | V1 | Essentials |
| [REQ-INT-035](#req-int-035--inbound-endpoints-that-create-and-update-records) | Inbound endpoints that create and update records | NEW | V1 | Essentials |
| [REQ-INT-036](#req-int-036--test-an-inbound-mapping-with-a-sample) | Test an inbound mapping with a sample | NEW | V1 | Essentials |
| [REQ-INT-037](#req-int-037--replay-protection-on-inbound-calls) | Replay protection on inbound calls | NEW | V1 | Essentials |
| [REQ-INT-038](#req-int-038--generic-alert-webhook-set-up) | Generic alert webhook set-up | NEW | V1 | Professional |
| [REQ-INT-039](#req-int-039--protection-against-alert-floods) | Protection against alert floods | NEW | V1 | Professional |
| [REQ-INT-040](#req-int-040--ready-made-adapters-for-common-alert-tools) | Ready-made adapters for common alert tools | NEW | LATER | Professional |
| [REQ-INT-041](#req-int-041--ticket-validation-for-privileged-access-tools) | Ticket validation for privileged access tools | SAME | LATER | Professional |
| [REQ-INT-042](#req-int-042--connect-monetx) | Connect MonetX | NEW | V1 | Professional |
| [REQ-INT-043](#req-int-043--receive-monetx-problems-without-gaps) | Receive MonetX problems without gaps | BETTER | V1 | Professional |
| [REQ-INT-044](#req-int-044--problem-policies) | Problem policies | NEW | V1 | Professional |
| [REQ-INT-045](#req-int-045--monetx-scope-by-site-and-customer) | MonetX scope by site and customer | NEW | V1 | Professional |
| [REQ-INT-046](#req-int-046--one-read-only-health-service-for-every-screen) | One read-only health service for every screen | NEW | V1 | Professional |
| [REQ-INT-047](#req-int-047--open-in-monetx) | Open in MonetX | NEW | V1 | Professional |
| [REQ-INT-048](#req-int-048--no-writes-to-monetx) | No writes to MonetX | SKIP | V1 | Professional |
| [REQ-INT-049](#req-int-049--more-than-one-monetx-instance) | More than one MonetX instance | NEW | LATER | Professional |
| [REQ-INT-050](#req-int-050--mailbox-connections-with-modern-sign-in) | Mailbox connections with modern sign-in | BETTER | MVP | Essentials |
| [REQ-INT-051](#req-int-051--several-mailboxes-each-with-its-own-routing) | Several mailboxes, each with its own routing | SAME | MVP | Essentials |
| [REQ-INT-052](#req-int-052--fetch-interval-and-push) | Fetch interval and push | BETTER | V1 | Essentials |
| [REQ-INT-053](#req-int-053--outgoing-mail-per-mailbox) | Outgoing mail per mailbox | SAME | MVP | Essentials |
| [REQ-INT-054](#req-int-054--sending-domain-set-up-on-saas) | Sending domain set-up on SaaS | NEW | V1 | Essentials |
| [REQ-INT-055](#req-int-055--no-pop3-mailboxes) | No POP3 mailboxes | SKIP | LATER | Essentials |
| [REQ-INT-056](#req-int-056--connect-teams-and-slack) | Connect Teams and Slack | SAME | V1 | Essentials |
| [REQ-INT-057](#req-int-057--notifications-to-teams-and-slack) | Notifications to Teams and Slack | SAME | V1 | Essentials |
| [REQ-INT-058](#req-int-058--approve-and-decide-from-chat) | Approve and decide from chat | SAME | LATER | Essentials |
| [REQ-INT-059](#req-int-059--create-and-update-records-from-chat) | Create and update records from chat | SAME | LATER | Essentials |
| [REQ-INT-060](#req-int-060--outlook-add-in-and-actionable-messages) | Outlook add-in and actionable messages | SAME | LATER | Essentials |
| [REQ-INT-061](#req-int-061--google-chat) | Google Chat | NEW | LATER | Essentials |
| [REQ-INT-062](#req-int-062--on-call-tools) | On-call tools | NEW | LATER | Professional |
| [REQ-INT-063](#req-int-063--sync-users-and-groups-from-entra-id) | Sync users and groups from Entra ID | SAME | V1 | Essentials |
| [REQ-INT-064](#req-int-064--leavers-are-disabled-never-deleted) | Leavers are disabled, never deleted | BETTER | V1 | Essentials |
| [REQ-INT-065](#req-int-065--active-directory-and-ldap-sync) | Active Directory and LDAP sync | BETTER | V1 | Essentials |
| [REQ-INT-066](#req-int-066--provisioning-by-scim) | Provisioning by SCIM | NEW | LATER | Essentials |
| [REQ-INT-067](#req-int-067--directory-actions-for-fulfilment) | Directory actions for fulfilment | BETTER | LATER | Professional |
| [REQ-INT-068](#req-int-068--self-service-password-reset-and-unlock) | Self-service password reset and unlock | BETTER | LATER | Professional |
| [REQ-INT-069](#req-int-069--calendar-feeds-for-schedules) | Calendar feeds for schedules | NEW | V1 | Professional |
| [REQ-INT-070](#req-int-070--microsoft-365-and-google-calendars) | Microsoft 365 and Google calendars | SAME | LATER | Professional |
| [REQ-INT-071](#req-int-071--connect-jira-azure-devops-gitlab-and-github) | Connect Jira, Azure DevOps, GitLab and GitHub | BETTER | V1 | Professional |
| [REQ-INT-072](#req-int-072--signed-pipeline-webhook-and-gate-tokens) | Signed pipeline webhook and gate tokens | NEW | LATER | Professional |
| [REQ-INT-073](#req-int-073--ticket-exchange-with-other-service-desks) | Ticket exchange with other service desks | NEW | LATER | Professional |
| [REQ-INT-074](#req-int-074--microsoft-intune-sccm-and-lansweeper-connectors) | Microsoft Intune, SCCM and Lansweeper connectors | SAME | V1 | Professional |
| [REQ-INT-075](#req-int-075--agentx-natively) | AgentX, natively | BETTER | V1 | Professional |
| [REQ-INT-076](#req-int-076--patchx-patches-from-tickets-and-changes) | PatchX: patches from tickets and changes | BETTER | LATER | Professional |
| [REQ-INT-077](#req-int-077--remote-access-tools) | Remote access tools | SAME | LATER | Professional |
| [REQ-INT-078](#req-int-078--telephony) | Telephony | SAME | LATER | Essentials |
| [REQ-INT-079](#req-int-079--whatsapp) | WhatsApp | SAME | LATER | Essentials |
| [REQ-INT-080](#req-int-080--sms-gateways) | SMS gateways | BETTER | LATER | Essentials |
| [REQ-INT-081](#req-int-081--zapier-power-automate-and-n8n) | Zapier, Power Automate and n8n | BETTER | LATER | Essentials |
| [REQ-INT-082](#req-int-082--bi-connector-set-up) | BI connector set-up | NEW | LATER | Enterprise |
| [REQ-INT-083](#req-int-083--hr-systems-and-business-applications) | HR systems and business applications | NEW | LATER | Enterprise |
| [REQ-INT-084](#req-int-084--confluence-and-sharepoint-as-knowledge-sources) | Confluence and SharePoint as knowledge sources | NEW | LATER | Professional |
| [REQ-INT-085](#req-int-085--ai-providers-in-the-connector-catalogue) | AI providers in the connector catalogue | BETTER | V1 | Essentials |
| [REQ-INT-086](#req-int-086--one-credential-store-for-connectors-webhooks-and-functions) | One credential store for connectors, webhooks and functions | BETTER | V1 | Essentials |
| [REQ-INT-087](#req-int-087--the-intranet-relay-agent) | The intranet relay agent | BETTER | V1 | Essentials |
| [REQ-INT-088](#req-int-088--installable-extension-packages) | Installable extension packages | BETTER | LATER | Professional |
| [REQ-INT-089](#req-int-089--extensions-run-sandboxed) | Extensions run sandboxed | BETTER | LATER | Professional |
| [REQ-INT-090](#req-int-090--custom-widgets) | Custom widgets | SAME | LATER | Professional |
| [REQ-INT-091](#req-int-091--who-publishes-extensions) | Who publishes extensions | BETTER | LATER | Professional |
| [REQ-INT-092](#req-int-092--no-public-marketplace-with-payments-for-now) | No public marketplace with payments, for now | SKIP | LATER | Professional |
| [REQ-INT-093](#req-int-093--the-mcp-server-as-an-api-surface) | The MCP server as an API surface | BETTER | V1 | Professional |
| [REQ-INT-094](#req-int-094--native-live-chat-no-separate-product) | Native live chat, no separate product | BETTER | LATER | Essentials |
| [REQ-INT-095](#req-int-095--technician-chat-console-and-availability) | Technician chat console and availability | SAME | LATER | Essentials |
| [REQ-INT-096](#req-int-096--chat-routing-queues-and-transfer) | Chat routing, queues and transfer | SAME | LATER | Essentials |
| [REQ-INT-097](#req-int-097--chat-widget-for-websites) | Chat widget for websites | SAME | LATER | Essentials |
| [REQ-INT-098](#req-int-098--hand-over-from-the-assistant-to-a-person) | Hand-over from the assistant to a person | BETTER | LATER | Essentials |
| [REQ-INT-099](#req-int-099--no-integrations-with-the-vendors-own-suite) | No integrations with the vendor's own suite | SKIP | LATER | Essentials |
| [REQ-INT-100](#req-int-100--no-outside-account-platform-for-security-settings) | No outside account platform for security settings | SKIP | V1 | Essentials |
| [REQ-ESM-001](#req-esm-001--one-product-one-login-desks-as-configuration) | One product, one login, desks as configuration | BETTER | LATER | Enterprise |
| [REQ-ESM-002](#req-esm-002--every-record-belongs-to-a-desk-from-day-one) | Every record belongs to a desk from day one | NEW | MVP | Essentials |
| [REQ-ESM-003](#req-esm-003--desk-settings) | Desk settings | SAME | LATER | Enterprise |
| [REQ-ESM-004](#req-esm-004--create-a-desk-from-a-template) | Create a desk from a template | BETTER | LATER | Enterprise |
| [REQ-ESM-005](#req-esm-005--each-desk-owns-its-configuration) | Each desk owns its configuration | SAME | LATER | Enterprise |
| [REQ-ESM-006](#req-esm-006--desk-specific-numbering) | Desk-specific numbering | SAME | LATER | Enterprise |
| [REQ-ESM-007](#req-esm-007--desk-names-for-record-types) | Desk names for record types | NEW | LATER | Enterprise |
| [REQ-ESM-008](#req-esm-008--archive-and-reactivate-a-desk) | Archive and reactivate a desk | BETTER | LATER | Enterprise |
| [REQ-ESM-009](#req-esm-009--records-are-private-to-their-desk) | Records are private to their desk | BETTER | LATER | Enterprise |
| [REQ-ESM-010](#req-esm-010--desk-isolation-holds-on-every-path) | Desk isolation holds on every path | NEW | LATER | Enterprise |
| [REQ-ESM-011](#req-esm-011--desk-admins) | Desk admins | BETTER | LATER | Enterprise |
| [REQ-ESM-012](#req-esm-012--people-who-work-in-several-desks) | People who work in several desks | BETTER | LATER | Enterprise |
| [REQ-ESM-013](#req-esm-013--ai-stays-inside-desk-boundaries) | AI stays inside desk boundaries | NEW | LATER | Enterprise |
| [REQ-ESM-014](#req-esm-014--one-directory-for-every-desk) | One directory for every desk | BETTER | LATER | Enterprise |
| [REQ-ESM-015](#req-esm-015--desks-in-the-shared-portal) | Desks in the shared portal | SAME | LATER | Enterprise |
| [REQ-ESM-016](#req-esm-016--desk-addresses) | Desk addresses | SAME | LATER | Enterprise |
| [REQ-ESM-017](#req-esm-017--desk-announcements-and-knowledge-in-the-portal) | Desk announcements and knowledge in the portal | SAME | LATER | Enterprise |
| [REQ-ESM-018](#req-esm-018--move-a-record-to-another-desk) | Move a record to another desk | BETTER | LATER | Enterprise |
| [REQ-ESM-019](#req-esm-019--ask-another-desk-for-help) | Ask another desk for help | BETTER | LATER | Enterprise |
| [REQ-ESM-020](#req-esm-020--links-to-records-you-cannot-see) | Links to records you cannot see | NEW | LATER | Enterprise |
| [REQ-ESM-021](#req-esm-021--search-and-lists-across-desks) | Search and lists across desks | BETTER | LATER | Enterprise |
| [REQ-ESM-022](#req-esm-022--confidential-cases) | Confidential cases | NEW | LATER | Enterprise |
| [REQ-ESM-023](#req-esm-023--sensitive-hr-fields-protected) | Sensitive HR fields protected | NEW | LATER | Enterprise |
| [REQ-ESM-024](#req-esm-024--onboarding-journeys) | Onboarding journeys | BETTER | LATER | Enterprise |
| [REQ-ESM-025](#req-esm-025--offboarding-journeys) | Offboarding journeys | BETTER | LATER | Enterprise |
| [REQ-ESM-026](#req-esm-026--transfer-journeys) | Transfer journeys | SAME | LATER | Enterprise |
| [REQ-ESM-027](#req-esm-027--cases-about-another-person) | Cases about another person | NEW | LATER | Enterprise |
| [REQ-ESM-028](#req-esm-028--retention-and-legal-hold-per-desk) | Retention and legal hold per desk | NEW | LATER | Enterprise |
| [REQ-ESM-029](#req-esm-029--spaces-and-floor-plans) | Spaces and floor plans | BETTER | LATER | Enterprise |
| [REQ-ESM-030](#req-esm-030--spaces-on-records-and-in-the-portal) | Spaces on records and in the portal | NEW | LATER | Enterprise |
| [REQ-ESM-031](#req-esm-031--room-and-seat-booking) | Room and seat booking | SAME | LATER | Enterprise |
| [REQ-ESM-032](#req-esm-032--booking-rules-and-approvals) | Booking rules and approvals | NEW | LATER | Enterprise |
| [REQ-ESM-033](#req-esm-033--visitor-management) | Visitor management | NEW | LATER | Enterprise |
| [REQ-ESM-034](#req-esm-034--planned-maintenance-for-buildings) | Planned maintenance for buildings | SAME | LATER | Enterprise |
| [REQ-ESM-035](#req-esm-035--finance-and-legal-desk-starter-content) | Finance and legal desk starter content | SAME | LATER | Enterprise |
| [REQ-ESM-036](#req-esm-036--custom-desks-for-any-function) | Custom desks for any function | BETTER | LATER | Enterprise |
| [REQ-ESM-037](#req-esm-037--desk-dashboards-and-reports-across-desks) | Desk dashboards and reports across desks | BETTER | LATER | Enterprise |
| [REQ-ESM-038](#req-esm-038--unlimited-desks-in-enterprise) | Unlimited desks in Enterprise | BETTER | LATER | Enterprise |
| [REQ-ESM-039](#req-esm-039--no-separate-instance-per-desk) | No separate instance per desk | SKIP | LATER | Enterprise |
| [REQ-ESM-040](#req-esm-040--no-asset-only-instance-type) | No asset-only instance type | SKIP | LATER | Enterprise |
| [REQ-ESM-041](#req-esm-041--servicedesk-plus-instances-become-desks) | ServiceDesk Plus instances become desks | NEW | LATER | Enterprise |
<!-- summary:end -->

## 1. The integrations framework

#### REQ-INT-001 — One connector catalogue

Admins find every integration on one catalogue screen, grouped by category (monitoring, email,
collaboration, identity, DevOps, endpoint, telephony, automation, analytics, knowledge, AI).
Each entry shows its status (not set up, active, degraded, failed, paused), the edition that
includes it, and a short description. The catalogue is searchable by name and by keywords such
as "API", "key" or "webhook". Connectors that are set up on the outside system's side are
listed too, with the steps to finish set-up and their status.

- **Decision:** BETTER. The vendor spreads integrations over three tabs, enables several from
  the other product's side with no status here, and its set-up search finds page names only.
- **Source:** sdp-area-14 §Screens (integrations: three tabs, enabled from the other side), §Behaviour (set-up search: "API" and "key" found nothing), §Weak spots; architecture §2.14
- **SDP weak spot fixed:** searching set-up for "API" or "key" returns nothing; integrations
  enabled from the other product show no status in the catalogue.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Searching the catalogue for "key" lists the API keys page and every connector that uses a
     key.
  2. A connector outside the tenant's edition is shown disabled with an upgrade hint, or hidden
     if the admin chose that (REQ-WI-025).
  3. Each catalogue entry shows its live status; a mailbox failure turns its entry to "failed"
     within 1 minute without a page refresh.

#### REQ-INT-002 — Set up, test, enable and disable a connector

Each connector has a guided set-up: connection details, a "test connection" step that reports
what worked and what did not, mapping choices, and a final enable. A connector can be disabled
and enabled again without losing its configuration, and deleted only when nothing depends on
it.

- **Decision:** BETTER. Every set-up has a test step that works before go-live, for example
  without a mail server.
- **Source:** sdp-area-14 §Screens (integrations: per-connector enable), §Limits; sdp-area-12 §Behaviour (webhook "save and test" blocked without mail)
- **SDP weak spot fixed:** testing a webhook needed a mail server.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. "Test connection" on a mailbox with a wrong password reports "authentication failed" with
     the server's reason, and saves nothing until the admin chooses to.
  2. Disabling a connector stops its jobs within 1 minute and keeps its settings; enabling it
     resumes from the last sync point.
  3. Deleting a connector used by a workflow or a webhook is refused and lists the users.

#### REQ-INT-003 — Credentials kept in a secrets store

Passwords, tokens, client secrets, private keys and webhook secrets are stored encrypted
(envelope encryption with keys in a KMS on SaaS or the install keystore on-prem). After saving,
a secret is never shown again; only its name, type, last four characters and age. Secrets never
appear in logs, exports, configuration packages, API responses or error messages. They can be
rotated without changing the things that use them.

- **Decision:** SAME. The vendor masks credentials too; we add rotation and age.
- **Source:** architecture §11.3 (secrets manager, envelope encryption); CLAUDE.md §8; REQ-RUL-016
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Reading a connector through the API returns the secret's name and last four characters,
     never its value.
  2. A configuration export or package contains a placeholder for each secret, not its value.
  3. A secret older than the rotation reminder age (Appendix A) shows a warning to admins.
  4. A log scan test over a full connector run finds no secret value.

#### REQ-INT-004 — Health and last sync on every connector

Each connector shows its health: status, the time of the last successful run, the last error
with its reason, the next scheduled run, and simple counts for the last 24 hours (calls,
records created, updated, skipped, failed). Credentials that expire (OAuth refresh tokens,
certificates, client secrets) show their expiry date and warn ahead of time.

- **Decision:** BETTER. The vendor shows only enabled or disabled.
- **Source:** sdp-area-14 §Screens (integrations: all show "Disabled" only); sdp-area-07 §Config (SCCM connection status); architecture §6.8
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. After a mailbox fetch, the mailbox shows the fetch time and the number of messages read.
  2. A client secret that expires in 14 days shows a warning on the connector and notifies the
     admins.
  3. The health view updates live while open.

#### REQ-INT-005 — Failures are visible, never silent

When a connector fails (authentication, network, quota, mapping error), the failure shows on
the connector, in the admin alert list and, where a record is involved, on that record
(REQ-WI-009). Admins are notified once per incident of failure, not once per call
(REQ-NTF-027). Recovery is notified too.

- **Decision:** BETTER. The vendor's integration failures surface mostly in logs or not at
  all.
- **Source:** sdp-area-14 §Screens (system log), §Weak spots; README cross-cutting lessons (no silent failures); REQ-WI-009; REQ-NTF-027
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A Teams message that fails to send shows "not delivered to Teams" on the record's
     notification log with the reason.
  2. Fifty failed calls in an hour send the connector's owners one alert, and one "recovered"
     message when it works again.
  3. Failures are kept in the connector's error list for the retention period (Appendix A).

#### REQ-INT-006 — Retries, backoff and a dead-letter list

Calls to outside systems that fail with a temporary error are retried with exponential backoff.
Messages that still fail go to a dead-letter list per connector, where an admin can see the
payload (with secrets masked), fix the cause and replay one or all. Replays are idempotent: a
record is never created twice.

- **Decision:** NEW. The vendor shows no retry or replay for integrations.
- **Source:** architecture §6.5 (idempotent consumers), §10 (webhooks: retries, replay)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A Jira call that gets a 503 is retried on the Appendix A schedule and then moved to the
     dead-letter list.
  2. Replaying a dead-letter item that already succeeded in a later retry changes nothing.
  3. Bulk replay of 100 items runs as a background job with progress.

#### REQ-INT-007 — Respect outside rate limits

Connectors respect each outside system's rate limits: they honour Retry-After and rate-limit
headers, spread calls over time, and keep a per-connector call budget. When the budget is
reached, work is queued, not dropped, and the connector shows "throttled" with the expected
catch-up time.

- **Decision:** NEW.
- **Source:** architecture §2.14, §10 (rate limiting); sdp-area-12 §Fields (webhook daily limit)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A 429 answer with "Retry-After: 30" delays the next call to that system by at least 30
     seconds.
  2. A directory sync over its budget completes later with no lost changes, and the connector
     shows "throttled" while waiting.

#### REQ-INT-008 — Audit and call log per connector

Each connector has two logs. The audit log records every configuration change (who, when,
old and new value, secrets masked) and is part of the tenant audit trail (file 11). The call
log records each inbound and outbound call: time, direction, endpoint, status, duration,
record touched, and the body with sensitive fields masked. Call logs are kept for a set period.

- **Decision:** BETTER. The vendor has one general audit log and a webhook call counter; it
  shows no call bodies or retention setting.
- **Source:** sdp-area-14 §Screens (audit log, system log), §Weak spots (no retention setting); sdp-area-12 §Fields (webhook daily limit counter); CLAUDE.md §8 (audit privileged actions)
- **SDP weak spot fixed:** no retention setting for logs is visible.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Changing a connector's group mapping writes an audit entry with old and new values.
  2. A call log entry links to the record it created or changed.
  3. Call log entries older than the retention period (Appendix A) are removed by a job, and
     the retention is editable per tenant.

#### REQ-INT-009 — Sync runs with counts and drill-down

Scheduled connectors (directory, topology, endpoint inventory, knowledge sources) record each
sync run: start, end, outcome, and counts of created, updated, unchanged, skipped and failed
items. An admin can open a run and see each failed item with its reason, and can start a run
now, pause the schedule, or run a full resync.

- **Decision:** BETTER. The vendor's import and scan lists show little about each run.
- **Source:** sdp-area-14 §Screens (import data history tab, probes and discovery lists); sdp-area-07 §Config (SCCM integration columns)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A directory sync that skips 3 users without an email shows them in the run with the
     reason "no email".
  2. "Sync now" starts a run within 10 seconds and its progress shows live.
  3. A full resync after a mapping change updates existing records and creates no duplicates.

#### REQ-INT-010 — Field and value mapping

Connectors that move data map outside fields and values to SupportX fields and values in a
mapping screen. Outside values are shown as the outside system names them, SupportX values
through labels (REQ-WI-013). Unmapped values follow a chosen rule: use a default, skip the
item, or flag it. Mappings can be tested with a sample.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Config (SCCM integration); architecture §6.6 (metadata), §2.14
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Mapping Jira status "In Review" to the label "in progress" shows the label, never a code.
  2. An unmapped value with the rule "flag" creates the item and lists it in the run with a
     warning.
  3. Testing a mapping with a sample payload shows the resulting fields before saving.

#### REQ-INT-011 — Match people across systems

Connectors that act for a person (Teams, Slack, WhatsApp, telephony, DevOps tools) map the
outside identity to a SupportX user, by verified email or directory ID by default, with manual
links for exceptions. Actions from an unmatched or ambiguous identity are refused, never
guessed.

- **Decision:** BETTER. The vendor does not show how chat identities map to users.
- **Source:** architecture §11.2 (one policy layer); REQ-SR-040 (approver identity from the connector's user mapping); REQ-CHG-051
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A Slack user whose verified email matches a SupportX user is linked automatically.
  2. An approval from a Teams account with no link is refused with a message telling the user
     how to link the account.
  3. An admin can see and remove any link; removal takes effect on the next action.

#### REQ-INT-012 — Connectors act as a service identity

Every connector and API client acts as a named service identity with its own role and scope.
Changes it makes show that identity and the source "integration" in history (REQ-WI-003).
Where a connector acts for a mapped person (an approval from Teams), the person is the actor and
the channel is recorded.

- **Decision:** BETTER. In the vendor, integrations act as the admin who set them up.
- **Source:** architecture §7.4 (source in history), §11.2; REQ-WI-003
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. An incident created by the alert webhook shows the webhook's service identity as creator
     and the source "integration".
  2. A service identity limited to one site cannot create records on another site.
  3. Service identities do not count as technicians for licensing.

#### REQ-INT-013 — Who may set up integrations

Setting up connectors, API clients, webhooks and extensions is a separate permission from using
them. A role can hold it for all connectors or for named connector categories. Desk admins can
set up connectors only for their own desk where the connector allows it (REQ-ESM-011).

- **Decision:** SAME. The vendor has integration permissions per module role.
- **Source:** sdp-area-11 §Fields (role permissions include webhooks and custom functions); architecture §11.2
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A technician without the permission sees the catalogue read-only, with a reason on each
     action.
  2. A role with "collaboration connectors" can change the Teams set-up but not the directory
     sync.

#### REQ-INT-014 — Same connectors on SaaS, on-prem and air-gapped

Every connector works the same on SaaS and on-prem, gated only through the entitlement
interface. On-prem installs can send outbound calls through an HTTP proxy and trust a customer
certificate authority. On air-gapped installs, connectors that need the internet show "needs
an outside network" and stay disabled; local connectors (directory, mail server, local AI,
MonetX on the same network) work.

- **Decision:** NEW. The vendor's cloud and on-prem editions differ in integrations.
- **Source:** architecture §1.2, §2 (features in both editions), §13.1; product-plan §4.3 (pillar 1); CLAUDE.md §5f
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. An on-prem install with a proxy set reaches Microsoft Graph through the proxy.
  2. A connector trusting a customer CA certificate connects to an internal TLS endpoint.
  3. No connector code branches on deployment mode; an architecture test checks this.

#### REQ-INT-015 — Outbound network safety

Every outbound call from a connector, webhook or function goes through one egress layer. It
refuses private ranges, link-local and cloud metadata addresses and the platform itself unless
an admin allowlists them (or they are reached through the relay agent, REQ-INT-087). It
enforces TLS by default and records each call (REQ-INT-008).

- **Decision:** NEW. Protects against calls into internal networks from a shared SaaS.
- **Source:** architecture §11, §6.7 (network allowlist for functions); REQ-RUL-015
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A connector URL pointing to 169.254.169.254 is refused at save with a clear reason.
  2. A plain HTTP URL is refused unless the admin turns off the TLS requirement for that
     connector, which is recorded in the audit log.
  3. A hostname that resolves to a private address at call time is refused even if it looked
     public at save time.

#### REQ-INT-016 — Connector settings in configuration packages

Connector settings (without secrets) are part of configuration-as-code: they can be exported,
compared and promoted between environments. Secrets are re-entered or mapped to the target
environment's secrets.

- **Decision:** NEW. The vendor's sandbox does not cover integrations.
- **Source:** product-plan §6 (config-as-code), §9 (Enterprise: config-as-code and multiple environments); sdp-area-14 §Screens (sandbox: what it covers); REQ-RUL-030
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. Promoting a Jira connector from test to production keeps its mappings and asks for the
     production credential.
  2. The exported package contains no secret value.

---

## 2. The public REST API

#### REQ-INT-017 — A documented, versioned public API

Every action in the UI is available through the public REST API (REQ-WI-018), under `/api/v1`.
The OpenAPI 3.1 contract is generated from the code and published with each release. Changes
within a version are additive; breaking changes need a new major version, and old versions
get deprecation headers and a 12-month sunset.

- **Decision:** BETTER. The vendor's set-up has no visible API page; we publish a full,
  versioned contract.
- **Source:** architecture §10 (style, contract, versioning); product-plan §8 (API-first); sdp-area-14 §Limits (no API key or OAuth console found)
- **SDP weak spot fixed:** no API key or OAuth console was found in set-up.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Every action shown on a record page has an API operation, checked by a test that compares
     action codes with the OpenAPI document.
  2. A CI check fails a change that removes or renames a field in `/api/v1`.
  3. A call to a deprecated operation returns Deprecation and Sunset headers.

#### REQ-INT-018 — API documentation inside the product

Admins and developers can read the API reference inside the product, with examples, error
codes, event types and webhook payloads. They can try a read call with their own permissions.
The documentation is available on-prem and air-gapped, from the installed version.

- **Decision:** BETTER. The documentation always matches the installed version.
- **Source:** architecture §10 (contract published per release); product-plan §8 (documented REST API)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. An air-gapped install shows its API reference without internet access.
  2. A "try it" read call returns only what the signed-in user may see.
  3. Every error code in the reference has a human message in English and Arabic.

#### REQ-INT-019 — API keys

Users with permission create API keys for themselves, and admins create keys for service
identities. A key has a name, scopes (REQ-INT-021), an expiry date, an optional IP allowlist
and a last-used time. It is shown once at creation. Keys can be revoked at once, and expire by
default. Whether technicians may create their own keys is a tenant policy (REQ-SEC-037 in
file 11); it is off by default.

- **Decision:** BETTER. The vendor shows no API key console in set-up.
- **Source:** architecture §10 (scoped API keys); sdp-area-14 §Limits (no API key console, no IP restriction found); §6.1 (identity_access: API tokens)
- **SDP weak spot fixed:** no API key or IP restriction page in set-up.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A new key is shown once; reading it later shows only its name and last four characters.
  2. A revoked key is refused within 5 seconds of revocation.
  3. A key with an IP allowlist is refused from another address, and the refusal is logged.
  4. A key without an expiry is refused at creation unless the admin allowed non-expiring keys.

#### REQ-INT-020 — OAuth clients

Integrations can use OAuth 2.0 client credentials for machine access. Third-party apps can use
the authorisation code flow with PKCE to act for a user, after the user consents to the
requested scopes. Admins see, limit and revoke clients and consents.

- **Decision:** NEW. The vendor offers OAuth only through its own account platform.
- **Source:** architecture §10 (OAuth client credentials), §11.1 (Keycloak); sdp-area-14 §Weak spots (security controls outside the product)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A client-credentials token for a service identity can create an incident within its
     scopes.
  2. A user who revokes an app's consent stops that app's access at once.
  3. Tokens are issued by Keycloak; SupportX stores no user password for API access.

#### REQ-INT-021 — Scopes and least privilege

API keys, OAuth clients and tokens carry scopes per resource and action (for example
`work_items:read`, `work_items:write`, `assets:read`). A call needs both the scope and the
caller's permission; a key can never do more than its owner may.

- **Decision:** NEW.
- **Source:** architecture §10 (scoped API keys), §11.2
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A key with only `work_items:read` gets 403 with a problem code on a create call.
  2. When the owner loses a permission, their key loses it too on the next call.

#### REQ-INT-022 — Rate limits with headers

The API applies rate limits per token and per tenant, with higher limits for higher editions
set through the entitlement interface. Every answer carries standard RateLimit headers; a call
over the limit gets 429 with Retry-After.

- **Decision:** BETTER. Limits are visible on every answer, not only when hit.
- **Source:** architecture §10 (rate limiting); sdp-area-12 §Fields (webhook daily limit), §Edition notes
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Each answer has RateLimit-Limit, RateLimit-Remaining and RateLimit-Reset headers.
  2. The call after the limit returns 429 with Retry-After and a problem code.
  3. One noisy token cannot use up the whole tenant's limit (per-token limit lower than the
     tenant limit).

#### REQ-INT-023 — Safe writes: idempotency and versions

Create calls accept an Idempotency-Key; a retry with the same key and body returns the first
answer, and a reuse with a different body is refused. Updates need the version read
(If-Match); a stale version gets 409 with the fields that changed.

- **Decision:** NEW.
- **Source:** architecture §6.5 (idempotency keys, optimistic concurrency), §10; REQ-WI-007; REQ-WI-008
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Two POSTs with the same Idempotency-Key create one incident and return the same ID.
  2. A PATCH with an old ETag returns 409 listing the changed fields.
  3. The same key with a different body returns a 422 problem code.

#### REQ-INT-024 — Lists, filters and expansions

List calls use cursor pagination with a capped page size, the shared JSON filter language
(architecture §6.5) and simple query parameters for common cases, sorting, field selection
and expansion of related items.

- **Decision:** SAME.
- **Source:** architecture §10 (pagination, filtering), §6.5 (filtering DSL)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Paging through 10,000 incidents while new ones are created returns each existing incident
     once.
  2. A filter saved in the UI can be sent unchanged to the API and returns the same rows.
  3. A page size above the cap is reduced to the cap and the answer says so.

#### REQ-INT-025 — Errors with stable codes

API errors are RFC 9457 problem details with a stable machine code, parameters and
field-level errors. The UI maps codes to labels; integrators get the code list in the
documentation. No stack trace or internal name is ever returned.

- **Decision:** SAME.
- **Source:** architecture §10 (errors); CLAUDE.md §5d
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A create with a missing required field returns 422 with the field name and a code.
  2. A test sends invalid input to every operation and checks that no answer holds a stack
     trace.

#### REQ-INT-026 — Bulk operations as jobs

Bulk endpoints accept up to 1,000 items, run as background jobs, stream progress and return a
result per item. A partial failure never hides which items failed.

- **Decision:** SAME.
- **Source:** architecture §10 (bulk); sdp-area-14 §Screens (import data limit 3000)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A bulk update of 500 incidents returns a job ID, and the job reports 500 results.
  2. 1,001 items are refused with a problem code naming the limit.
  3. Progress is available through the API and live in the UI.

#### REQ-INT-027 — Change feed for integrations

Integrators can read a change feed of domain events since a cursor (the same events as webhook
subscriptions, filtered by the caller's permissions). This lets a system that missed webhooks
catch up without a full resync.

- **Decision:** NEW. product-plan asks for an event stream next to the API and webhooks.
- **Source:** product-plan §8 (API-first: webhooks and an event stream); architecture §6.5 (outbox)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Reading the feed from a cursor returns every event after it, in order, once.
  2. Events for records the caller may not see are not returned.
  3. Events are kept for the feed retention period (Appendix A); an older cursor gets a clear
     "resync needed" code.

#### REQ-INT-028 — API usage for admins

Admins see API usage per key and client: calls, errors, throttled calls and last use, with a
filter by time. Keys unused for a set period are flagged for review.

- **Decision:** NEW.
- **Source:** architecture §10 (rate limiting), §15 (observability)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. The usage page shows yesterday's call count for each key.
  2. A key unused for 90 days (Appendix A) is listed as "unused".

#### REQ-INT-029 — Client libraries

Typed client libraries for Python and TypeScript are generated from the OpenAPI contract and
published with each release, for customers and for extension authors.

- **Decision:** NEW.
- **Source:** architecture §10 (contract generated from code); CLAUDE.md §3 (openapi-typescript)
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. Each release has client libraries whose version matches the API contract version.
  2. A sample script using the Python client creates an incident against a test tenant.

---

## 3. Outbound webhooks

#### REQ-INT-030 — Webhook subscriptions per event type

Admins subscribe an outside URL to chosen event types (for example incident created,
status changed, approval decided), optionally with a filter in the shared filter language.
Each delivery carries the event ID, type, time, record ID, display ID, changed fields and
version; full record data is included only if the subscription asks for it and its service
identity may read it. These subscriptions are separate from the webhook action in automation
(REQ-RUL-014), which is called from a rule or workflow.

- **Decision:** NEW. The vendor has webhook actions in automation only, not event
  subscriptions.
- **Source:** architecture §10 (webhooks: subscriptions per event type); sdp-area-12 §Fields (webhook action)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A subscription to "incident created" with the filter "priority is P1" receives P1
     incidents only.
  2. A subscription whose identity may not see HR records receives no HR desk events.
  3. A delivery holds the event ID, so the receiver can drop repeats.

#### REQ-INT-031 — Signed deliveries

Every delivery is signed with HMAC-SHA256 over the timestamp and body, with the signature and
timestamp in headers. Each subscription can hold two secrets during rotation. The
documentation shows how to verify a signature and reject old timestamps.

- **Decision:** NEW.
- **Source:** architecture §10 (HMAC-SHA256 signatures)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A receiver using the documented check accepts a real delivery and rejects a changed body.
  2. During rotation, deliveries carry signatures for both secrets until the old one is
     removed.

#### REQ-INT-032 — Retries, auto-pause and alerts

Failed deliveries are retried with exponential backoff (the same schedule as REQ-RUL-015). A
subscription that keeps failing for a set time is paused, its owner is notified, and events
are kept for replay when it is resumed. Deliveries run outside the user's request and never
slow it down.

- **Decision:** NEW.
- **Source:** architecture §10 (retries with exponential backoff); REQ-RUL-015
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A receiver returning 500 gets the delivery again on the backoff schedule.
  2. After 24 hours of failures (Appendix A) the subscription is paused and the owner notified.
  3. Resuming a paused subscription delivers the held events in order.

#### REQ-INT-033 — Delivery log and replay

Each subscription has a delivery log: event, time, attempts, status code, duration, and the
request and response bodies with secrets masked. An admin can replay one delivery or all
deliveries in a time range.

- **Decision:** NEW.
- **Source:** architecture §10 (delivery log and replay in the UI)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A failed delivery shows the receiver's status code and the first part of its answer.
  2. Replaying a delivery sends the same event ID again.
  3. Replaying a time range runs as a background job with progress.

#### REQ-INT-034 — Ordering and delivery guarantees, documented

Deliveries are at least once. Events for the same record are delivered in order; events for
different records may arrive in any order. The documentation states this, and each delivery
carries the record version so a receiver can ignore stale events.

- **Decision:** NEW.
- **Source:** architecture §6.5 (outbox, idempotent consumers), §8 (payloads carry version)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Two quick changes to one incident arrive in the order made, with increasing versions.
  2. A delivery replayed after a newer one carries the older version, so the receiver can tell.

---

## 4. Inbound webhooks and the generic alert webhook

#### REQ-INT-035 — Inbound endpoints that create and update records

Admins create inbound endpoints that let an outside system create or update work items with a
JSON payload. Each endpoint has its own URL, a secret (HMAC signature or bearer token), a
service identity, a target type and template, and a mapping from payload fields to record
fields. A key field in the payload links later calls to the same record.

- **Decision:** NEW. The vendor has no generic inbound webhook.
- **Source:** architecture §2.14 (generic webhooks in and out); product-plan §8 (API-first)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A signed payload creates an incident with the mapped subject, priority and group.
  2. A second payload with the same key adds a note to that incident instead of creating one.
  3. A payload with a bad signature is refused with 401 and logged; nothing is created.

#### REQ-INT-036 — Test an inbound mapping with a sample

When building an inbound endpoint, the admin pastes a sample payload and sees the record
that would be created, field by field, with any mapping errors, before saving.

- **Decision:** NEW.
- **Source:** architecture §6.6 (metadata-driven); REQ-INT-010
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Pasting a sample shows the resulting subject and priority labels without creating a
     record.
  2. A payload field mapped to a missing required field shows an error naming it.

#### REQ-INT-037 — Replay protection on inbound calls

Inbound calls are refused when their timestamp is outside the allowed window or their delivery
ID was already processed. Refused calls are logged with the reason.

- **Decision:** NEW.
- **Source:** architecture §6.5 (idempotent consumers), §11
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A call with a timestamp older than 5 minutes (Appendix A) is refused and logged.
  2. The same delivery ID sent twice is processed once and the second call gets 200 with "already
     processed".

#### REQ-INT-038 — Generic alert webhook set-up

The generic alert webhook (REQ-INC-031) is set up per source tool: a URL and secret per
source, a documented payload (alert key, state, severity, title, description, item, site or
customer, time, link back), a severity-to-priority map, a template and group per source, and
the recovery policy (D-050). Each source has its own service identity and call log. The
webhook keys one alert to one incident and does no correlation, grouping or suppression
(REQ-INC-146).

- **Decision:** NEW. The vendor needs separate monitoring products for alert-to-ticket.
- **Source:** architecture §2.14 (monitoring: generic alert webhook), §6.1 (monitoring_integrations); ADR-017; D-001; D-050; REQ-INC-031
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Two sources each with their own secret create incidents with different templates and
     groups.
  2. A "resolved" alert follows the source's recovery policy: resolve, or add a "source
     recovered" note when a technician owns the incident.
  3. Alerts with different keys create separate incidents even if their text is the same.

#### REQ-INT-039 — Protection against alert floods

Each alert source has a rate limit on new incidents per minute. Above it, calls get 429 with
Retry-After so the sender keeps and resends them; nothing is merged or dropped, and admins are
alerted once. This protects the service desk without doing correlation.

- **Decision:** NEW.
- **Source:** architecture §10 (rate limiting); ADR-017; REQ-NTF-022 (storm protection)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. The 101st new alert in a minute from a source with a limit of 100 (Appendix A) gets 429.
  2. Updates to existing alert keys are still accepted while new ones are limited.
  3. The admin gets one "alert flood" notice per source per hour.

#### REQ-INT-040 — Ready-made adapters for common alert tools

Payload adapters turn the native webhook formats of common tools into the documented alert
payload: Prometheus Alertmanager, Grafana, Zabbix, and security tools as incident sources
(Wazuh, Splunk, Microsoft Sentinel, QRadar). Each adapter is a mapping the admin can view and
adjust.

- **Decision:** NEW.
- **Source:** architecture §2.14 (security tools as incident sources); product-plan Appendix B (monitoring and events); ADR-017
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. An Alertmanager webhook with two alerts creates two incidents keyed by fingerprint.
  2. A Wazuh alert creates an incident with the security category from the adapter's mapping.
  3. No adapter groups alerts; each alert key stays one incident.

#### REQ-INT-041 — Ticket validation for privileged access tools

Privileged access tools can ask SupportX whether a ticket ID is valid for an access request:
the record exists, is approved, is in an allowed status, is assigned to the person asking and
is inside its scheduled window. The answer is yes or no with reasons, and each check is recorded
on the record.

- **Decision:** SAME. The vendor offers this through a marketplace extension for its own
  privileged access product.
- **Source:** architecture §2.14 (security tools: privileged access tools for ticket validation); sdp-area-14 §Screens (marketplace: privileged access extension)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A check for an approved change in its window, by its implementer, returns "valid".
  2. A check outside the window returns "not valid" with the reason "outside window".
  3. The check appears in the change's history with the tool's identity.

---

## 5. The MonetX connector

#### REQ-INT-042 — Connect MonetX

An admin connects one MonetX instance with its base URL, a read-only API credential and a
webhook secret for problem delivery. The test step checks that the credential can read
problems, health and topology, and warns if it has write rights it does not need. The
connector shows its health like any other (REQ-INT-004).

- **Decision:** NEW. The vendor needs separate monitoring products for this.
- **Source:** architecture §2.14 (MonetX connector), §6.8 (monitoring connector); ADR-017; D-001; product-plan §4.3 (pillar 3)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A credential that cannot read topology fails the test with "topology read not allowed".
  2. A credential with write rights shows a warning recommending a read-only one.
  3. The connector page shows the time of the last problem received and the last read call.

#### REQ-INT-043 — Receive MonetX problems without gaps

MonetX problems arrive by signed webhook. After an outage of either side, the connector reads
the problems changed since its last cursor from the MonetX API, so no problem is missed. Each
problem is processed once by its problem ID and version, then handed to the incident policy
(REQ-INC-030). The connector measures the delay from MonetX problem time to incident creation.

- **Decision:** BETTER. Adds catch-up after outages and delay measurement to alarm-to-ticket.
- **Source:** architecture §6.8 (webhook and API receiver for MonetX problems); ADR-017; REQ-INC-030
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Problems raised in MonetX while SupportX was down create their incidents after restart,
     each once.
  2. A repeated delivery of the same problem version changes nothing.
  3. The connector shows the median delay from problem to incident for the last hour.

#### REQ-INT-044 — Problem policies

Admins define which MonetX problems create incidents, by severity, device group, site,
customer, tags and problem type. Each policy sets the template, the priority mapping, the
group, the desk and the recovery behaviour (D-050). Policies are tried in order; problems
that match no policy are listed but create nothing. A policy can be simulated against the last
24 hours of problems.

- **Decision:** NEW.
- **Source:** architecture §6.1 (monitoring_integrations: problem-to-incident policies); REQ-INC-030; D-050
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A "critical, core routers" policy above a "critical, any" policy wins for a core router.
  2. Simulating a new policy lists the problems it would have turned into incidents, without
     creating any.
  3. A problem matching no policy appears in the unmatched list with its MonetX link.

#### REQ-INT-045 — MonetX scope by site and customer

MonetX sites, customers and device groups are mapped to SupportX sites and customers. Every
read (health panels, wallboards, topology) and every incident created is scoped through this
map, so users see monitoring status only for the sites and customers they may see.

- **Decision:** NEW.
- **Source:** D-001; product-plan §6 (NOC wallboards per site or customer); REQ-DSH-035; architecture §7.2 (customer partitions)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A technician scoped to site A sees MonetX health for site A devices only.
  2. A problem on a device of customer B creates an incident for customer B.
  3. A MonetX site with no mapping is listed for the admin; its problems use the policy's
     default site.

#### REQ-INT-046 — One read-only health service for every screen

Health, open problems and topology are read through one read-only client in
`monitoring_integrations`, used by incidents (REQ-INC-145), changes and health checks
(REQ-CHG-085, REQ-CHG-086), the CMDB (REQ-CMDB-012, REQ-CMDB-013) and wallboards
(REQ-DSH-035). It caches answers briefly, times out quickly, stops calling for a while after
repeated failures, and always says how old the data is. Pages that show health refresh it
live while open.

- **Decision:** NEW.
- **Source:** D-001; ADR-017; architecture §6.1; CLAUDE.md §1 (monitoring boundary)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Fifty users opening the same CI within 10 seconds cause one MonetX read (cache time in
     Appendix A).
  2. After 5 failed reads in a row, the client stops calling for 60 seconds and panels show
     "monitoring status unavailable" with the last good time.
  3. No module except `monitoring_integrations` calls MonetX (import-linter contract).

#### REQ-INT-047 — Open in MonetX

Every MonetX device, problem and topology item shown in SupportX links to the same item in
MonetX. Where both use the same identity provider, the user lands signed in.

- **Decision:** NEW.
- **Source:** REQ-INC-145; REQ-CMDB-012; REQ-DSH-035
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. "Open in MonetX" on an incident created from a problem opens that problem in MonetX.
  2. If the MonetX URL is not set, the link is not shown (no dead link).

#### REQ-INT-048 — No writes to MonetX

SupportX never writes to MonetX: it does not acknowledge, close or comment on MonetX problems,
change devices or run actions on network devices. Technicians who need to act in MonetX use
the link (REQ-INT-047).

- **Decision:** SKIP. MonetX is read-only for SupportX (D-001, ADR-017); write-back is replaced
  by deep links.
- **Source:** D-001; ADR-017; CLAUDE.md §1; file 03 open question 12 (runbooks through MonetX)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. The MonetX client has no write method; a contract test fails if one is added.
  2. Resolving an incident from MonetX makes no call to MonetX.

#### REQ-INT-049 — More than one MonetX instance

A tenant can connect more than one MonetX instance (for example one per region or per
managed customer). Each has its own credential, scope map and policies, and every item shows
which instance it came from.

- **Decision:** NEW.
- **Source:** architecture §2.15 (MSP), §7.2; product-plan §4.2 (telcos and MSPs)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Problems from two instances with the same problem ID create two different incidents.
  2. Health panels name the instance an item comes from.

---

## 6. Email channels

#### REQ-INT-050 — Mailbox connections with modern sign-in

Admins connect support mailboxes over Microsoft Graph (Microsoft 365) and the Gmail API
(Google Workspace) using OAuth 2.0 with admin consent, or over IMAP with TLS for other mail
servers. No password is stored for Microsoft 365 or Google. Expiring consents and tokens warn
ahead of time (REQ-INT-004). Parsing and threading are specified in REQ-INC-023 to
REQ-INC-027.

- **Decision:** BETTER. The vendor's mail set-up takes a user name and password and offers
  POP and IMAP only.
- **Source:** sdp-area-13 §Mail (incoming: server, user name, password, POP/IMAP); architecture §6.8 (IMAP, Microsoft Graph, Gmail API); REQ-INC-023
- **SDP weak spot fixed:** password-based mail fetching, which Microsoft 365 and Google no
  longer allow by default.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Connecting a Microsoft 365 mailbox uses an admin consent screen and stores no password.
  2. Revoking consent in Microsoft makes the mailbox show "failed: consent revoked" and
     notifies admins.
  3. An IMAP mailbox without TLS is refused unless the admin allows it, with an audit entry.

#### REQ-INT-051 — Several mailboxes, each with its own routing

A tenant can connect many mailboxes. Each mailbox sets what it creates (incident, service
request, or nothing), the template, the group, the desk, the unknown-sender policy
(REQ-INC-027) and whether new records may be created from it at all,
or only replies threaded.

- **Decision:** SAME. The vendor has a "disable new request creation through email" switch.
- **Source:** sdp-area-13 §Mail (email request settings: disable creation); REQ-INC-023; REQ-INC-027; architecture §2.15 (ESM)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Mail to hr@ creates a record in the HR desk and mail to it@ in the IT desk.
  2. With "replies only", a new mail creates nothing and the sender gets the configured reply.

#### REQ-INT-052 — Fetch interval and push

Mailboxes are checked on a schedule (default in Appendix A). Where the provider supports
change notifications (Microsoft Graph subscriptions, Gmail push) and SupportX can be reached,
new mail is fetched within seconds; polling stays as a safety net.

- **Decision:** BETTER. The vendor polls every 2 to 60 minutes only.
- **Source:** sdp-area-13 §Mail (fetch mails every 2, 5, 15, 30 or 60 minutes); architecture §6.8
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. With push active, a mail to the mailbox creates its record within 30 seconds.
  2. If push stops, the poll still picks up the mail on schedule and the mailbox shows "push
     inactive".

#### REQ-INT-053 — Outgoing mail per mailbox

Outgoing mail is sent through SMTP with TLS, Microsoft Graph or the Gmail API. Each mailbox can
send replies as itself, so a requester always gets answers from the address they wrote to. A
tenant-wide default sender is used for notifications that do not come from a mailbox. The
sender name and reply-to address are set per mailbox.

- **Decision:** SAME. The vendor has one outgoing server with sender name and reply-to.
- **Source:** sdp-area-13 §Mail (outgoing: server, sender's name, reply-to, SMTP/SMTPS/TLS); architecture §6.8; REQ-NTF-002
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A reply on a record that came in to hr@ is sent from hr@.
  2. A failed send shows on the record's notification log and is retried (REQ-NTF-020).
  3. SMTP without TLS is refused unless the admin allows it.

#### REQ-INT-054 — Sending domain set-up on SaaS

On SaaS, a tenant that sends from its own domain through SupportX's mail service verifies the
domain with DNS records (SPF, DKIM and a return path). The page shows each record and whether
it is found. Until verified, mail goes from a SupportX address with the tenant's name and the
tenant's reply-to.

- **Decision:** NEW. The vendor pushes its own mail server as an upgrade.
- **Source:** sdp-area-13 §Mail (upgrade banner for the vendor's own mail server); sdp-area-14 §Screens (custom domains)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Adding the DKIM record turns its check to "found" within 10 minutes of DNS publishing.
  2. Before verification, notifications are sent from the SupportX address with the tenant's
     reply-to.

#### REQ-INT-055 — No POP3 mailboxes

SupportX does not fetch mail over POP3.

- **Decision:** SKIP. POP3 cannot mark or move messages on the server, so mail could only be
  deleted after fetching (the vendor's behaviour). IMAP, Microsoft Graph and the Gmail API
  replace it (REQ-INT-050).
- **Source:** sdp-area-13 §Mail (POP, POPS options; mailbox emptied after fetch); REQ-INC-023
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. The mailbox set-up offers no POP3 option.
  2. The migration tool reports POP3 mailboxes from ServiceDesk Plus with the advice to use
     IMAP.

---

## 7. Microsoft Teams, Slack and other chat tools

#### REQ-INT-056 — Connect Teams and Slack

Admins install the SupportX app in a Microsoft Teams tenant or a Slack workspace through the
provider's consent flow. Set-up maps users (REQ-INT-011), and maps groups and desks to channels
for group notifications. One SupportX tenant can connect one Teams tenant and several Slack
workspaces.

- **Decision:** SAME.
- **Source:** sdp-area-14 §Screens (integrations: Microsoft Teams, Slack); architecture §2.14 (collaboration); product-plan Appendix B (collaboration P0)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. After install, users whose emails match are linked and the count is shown.
  2. Mapping the Network group to a Teams channel sends that group's notifications there.
  3. Removing the app on the provider's side turns the connector to "failed: app removed".

#### REQ-INT-057 — Notifications to Teams and Slack

The notification engine (file 03) can deliver to Teams and Slack, to a person's chat or to a
group's channel, as a card with the key fields and buttons that open the record. Messages
follow the recipient's language and the record's permissions; a person never gets a card for
a record they cannot see.

- **Decision:** SAME.
- **Source:** architecture §6.8 (channel adapters: Teams, Slack); REQ-NTF-001; REQ-NTF-010
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Assigning an incident to a linked technician sends a Teams card within 10 seconds.
  2. The card shows labels in the technician's language, never codes.
  3. When the record changes status, an earlier card is updated to show the new status.

#### REQ-INT-058 — Approve and decide from chat

Approval requests can be delivered to Teams and Slack with approve, reject and ask-for-detail
buttons (REQ-SR-040, REQ-CHG-051). Decisions use the approver's mapped identity, are
single-use, and update the card for everyone once decided. A card for a stage that was already
decided says so.

- **Decision:** SAME.
- **Source:** architecture §2.14 (Teams approvals, actionable messages); sdp-area-14 §Screens (integrations: Outlook actionable messages, Teams, Slack); REQ-SR-040; REQ-CHG-051; REQ-REL-031
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. Approving from a Slack card records the decision with channel "Slack" within 1 second.
  2. Pressing approve twice records one decision.
  3. A card whose approval was decided in the app shows "already decided" and no buttons.

#### REQ-INT-059 — Create and update records from chat

People can raise a request from Teams or Slack: from a message ("create incident from this
message"), from a bot conversation, or with a command. They can look up a record by its ID,
list their open items, add a note and change status where allowed. A thread on a chat-created
record stays linked to the record's conversation both ways (REQ-INC-032).

- **Decision:** SAME.
- **Source:** architecture §2.14 (Teams bot), §2.10 (virtual agent in Teams); REQ-INC-032; product-plan §5 (unified inbox)
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. "Create incident from this message" makes an incident with the message as description and
     channel Teams.
  2. A requester's reply in the thread appears in the incident's conversation.
  3. A technician's public reply in SupportX appears in the thread.

#### REQ-INT-060 — Outlook add-in and actionable messages

Technicians can create a record from an email in Outlook or link the email to an existing
record through an Outlook add-in. Approval and notification emails to Outlook users can carry
actionable buttons with the same single-use rules as email links (REQ-NTF-024).

- **Decision:** SAME.
- **Source:** sdp-area-14 §Screens (integrations: Outlook actionable messages; marketplace: Outlook); architecture §2.14 (Outlook add-in, actionable messages)
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. Creating an incident from an email in Outlook attaches the email and its attachments.
  2. An actionable approval in Outlook records the decision with channel "Outlook".

#### REQ-INT-061 — Google Chat

Notifications, approvals and record creation work in Google Chat as in Teams and Slack.

- **Decision:** NEW. The vendor offers its own chat product instead.
- **Source:** architecture §2.14 (collaboration: Google Chat)
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. An assignment notification reaches a linked Google Chat user.
  2. An approval from Google Chat is recorded with channel "Google Chat".

#### REQ-INT-062 — On-call tools

P1 and major incidents can open, update and resolve an incident in PagerDuty or Opsgenie, and
acknowledgements there are shown on the SupportX incident.

- **Decision:** NEW.
- **Source:** product-plan Appendix B (on-call and alerting: PagerDuty, Opsgenie)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Declaring a major incident opens a PagerDuty incident and links it.
  2. An acknowledgement in PagerDuty adds a system note naming the person.
  3. Resolving the SupportX incident resolves the PagerDuty incident.

---

## 8. Identity and directories

#### REQ-INT-063 — Sync users and groups from Entra ID

Admins sync users and groups from Microsoft Entra ID: chosen groups or all users, attribute
mapping (name, email, phone, job title, department, site, manager, employee ID), group to user
group mapping, and changes by delta every interval. Sign-in itself goes through Keycloak
(file 11).

- **Decision:** SAME.
- **Source:** sdp-area-14 §Screens (integrations: Entra ID, Entra ID user sync); architecture §2.14 (identity), §11.1; product-plan Appendix B (identity P0)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A new user in a synced Entra group appears in SupportX by the next sync with mapped
     department and manager.
  2. A changed manager in Entra changes the manager used for approvals (file 02).
  3. Each run shows counts and skipped users (REQ-INT-009).

#### REQ-INT-064 — Leavers are disabled, never deleted

When a user is removed or disabled in the directory, SupportX disables their login and keeps
the person and all their records. Their open work is flagged for reassignment and their
pending approvals go to the backup approver. Deleting people is only possible through privacy
erasure (file 11).

- **Decision:** BETTER. The vendor's default deletes the user when they are removed from the
  directory.
- **Source:** sdp-area-13 §Advanced Portal Settings (directory sync: removed user is deleted by default); CLAUDE.md §6 (soft delete)
- **SDP weak spot fixed:** removing a user in the directory deletes them in the help desk by
  default.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Disabling a user in Entra disables their SupportX login by the next sync; their incidents
     still show them as requester.
  2. The disabled technician's open incidents appear in a "needs reassignment" view.
  3. A pending approval of the disabled user moves to the backup approver with a history entry.

#### REQ-INT-065 — Active Directory and LDAP sync

Users and groups sync from on-premise Active Directory or LDAP, with the same mapping as
REQ-INT-063. On-prem installs connect directly; SaaS tenants connect through the relay agent
(REQ-INT-087), so no directory port is opened to the internet.

- **Decision:** BETTER. The vendor needs a downloaded provisioning app and has no directory
  sync in its main product.
- **Source:** sdp-area-14 §Screens (ESM directory: Active Directory settings, provisioning app); sdp-area-11 §Behaviour (no LDAP or AD user sync found); architecture §2.14 (identity), §11.1
- **SDP weak spot fixed:** no LDAP or AD user sync in set-up.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A SaaS tenant syncs 5,000 AD users through the relay agent with no inbound firewall rule.
  2. LDAPS is used by default; plain LDAP needs an admin choice recorded in the audit log.
  3. An AD group mapped to a SupportX user group keeps membership in step.

#### REQ-INT-066 — Provisioning by SCIM

Identity providers that push users (Okta, Entra ID, others) can provision and deprovision
users and groups through a SCIM 2.0 endpoint with its own token. Deprovisioning disables the
user (REQ-INT-064).

- **Decision:** NEW.
- **Source:** architecture §2.14 (identity: Okta, Google, user and group sync)
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. Okta assigning a user to the SupportX app creates the user within 1 minute.
  2. Okta unassigning the user disables, not deletes, them.

#### REQ-INT-067 — Directory actions for fulfilment

Fulfilment steps and workflows can run directory actions through the identity connectors:
create an account, add or remove group membership, disable an account, reset a password or
unlock an account. Each action needs its own permission on the connector, runs through the
relay for on-premise directories, and records the result on the record (REQ-SR-055).

- **Decision:** BETTER. The vendor needs a separate directory management product for this.
- **Source:** sdp-area-14 §Screens (integrations: directory management product); architecture §2.14 (identity), §2.2 (onboarding and offboarding); REQ-SR-055
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. An approved "add to VPN group" request adds the user to the AD group and notes the result.
  2. A failed action creates a manual task (REQ-SR-055) with the directory's error.
  3. A workflow without the "disable account" permission on the connector cannot choose that
     action.

#### REQ-INT-068 — Self-service password reset and unlock

Requesters can reset their directory password or unlock their account from the portal, after
verifying themselves with a second factor. The request and outcome are logged as a service
request without the password ever being stored or shown.

- **Decision:** BETTER. Built in; the vendor needs a separate self-service product.
- **Source:** architecture §2.14 (identity: AD self-service password reset and unlock built in)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A verified requester resets their AD password through the relay agent and a closed
     service request records it.
  2. No password appears in any log, record or event.
  3. Five failed verifications lock the reset for that user for the lock period (Appendix A).

---

## 9. Calendars

#### REQ-INT-069 — Calendar feeds for schedules

Users can subscribe their calendar app to read-only feeds: the change and release calendar,
their own on-call and shift schedule, and their bookings. Feed links are personal, can be
revoked, and only show what the user may see.

- **Decision:** NEW.
- **Source:** architecture §2.4 (change calendar); sdp-area-14 §Screens (integrations: Office 365 calendar)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A change scheduled for Friday appears in a subscribed Outlook calendar after its next
     refresh.
  2. A revoked feed link returns 404.
  3. A change the user may not see is not in their feed.

#### REQ-INT-070 — Microsoft 365 and Google calendars

With the Microsoft 365 or Google calendar connector:

- CAB meetings and change windows can be sent as calendar invites and kept up to date;
- technicians' out-of-office events can mark them unavailable for assignment (file 03);
- bookable rooms can be linked to room calendars (REQ-ESM-031).

- **Decision:** SAME. The vendor has an Office 365 calendar integration.
- **Source:** sdp-area-14 §Screens (integrations: Office 365 calendar); architecture §2.14 (Microsoft 365 calendar), §2.15 (room booking)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Rescheduling a CAB meeting updates the invite in attendees' calendars.
  2. An out-of-office event in Outlook makes the technician unavailable for auto-assignment
     for that period.
  3. A room booked in Outlook shows as booked in SupportX within 1 minute.

---

## 10. DevOps and ITSM tools

#### REQ-INT-071 — Connect Jira, Azure DevOps, GitLab and GitHub

Admins connect Jira (cloud and data centre), Azure DevOps, GitLab and GitHub with OAuth or a
token, choose projects or repositories, and map item types and states. Linked items read back
their key, title, state and assignee, updated through the tool's webhooks where available, and
by polling otherwise. These connectors power the links on changes and releases (REQ-CHG-115,
REQ-REL-042) and on incidents and problems.

- **Decision:** BETTER. GitHub is added, and the state of linked items is read back and shown
  live.
- **Source:** sdp-area-14 §Screens (integrations: Jira, Azure DevOps); architecture §2.14 (DevOps), §2.5; product-plan §5 (release: DevOps limited to links); REQ-CHG-115; REQ-REL-042
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Linking a GitHub issue to a problem shows its title and state; closing it in GitHub shows
     "closed" on the problem without a refresh.
  2. Creating a Jira issue from an incident links both ways and puts the incident's link in
     the issue.
  3. If the tool cannot be reached, the panel says so and the record still works.

#### REQ-INT-072 — Signed pipeline webhook and gate tokens

Admins create a pipeline endpoint per CI/CD tool (GitHub Actions, GitLab CI, Jenkins, Azure
Pipelines, ArgoCD) with its own secret and service identity. The page shows the URL, the
payload format, a copy-ready example for each tool, and the token for the deployment gate. It
feeds REQ-REL-043 to REQ-REL-045.

- **Decision:** NEW.
- **Source:** product-plan §5 (release: pipeline-aware, hooks), Appendix B (DevOps); REQ-REL-043; REQ-REL-044; REQ-REL-045
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A pipeline event signed with the endpoint's secret is accepted; one signed with another
     endpoint's secret is refused.
  2. The gate token can only call the gate check, not other API operations.
  3. Each event appears in the endpoint's call log with the release it changed.

#### REQ-INT-073 — Ticket exchange with other service desks

Records can be exchanged with another organisation's service desk (ServiceNow, Jira Service
Management or another SupportX tenant): sending a record, receiving status and comments back,
and keeping both sides in step for chosen fields. Each exchange partner has its own mapping and
log.

- **Decision:** NEW.
- **Source:** architecture §2.14 (ITSM and knowledge: ServiceNow and Jira Service Management ticket sync)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Sending an incident to a partner's ServiceNow creates their record and stores its number.
  2. A comment added on their side appears as a note on ours with the partner as source.
  3. A loop between the two systems stops after the first echo.

---

## 11. Endpoint tools and Extravis products

#### REQ-INT-074 — Microsoft Intune, SCCM and Lansweeper connectors

Admins connect Microsoft Intune (through Microsoft Graph), Microsoft SCCM or MECM (database
read through the relay agent or a site probe) and Lansweeper as inventory sources, with a
schedule and a scope. Reconciliation into assets is specified in REQ-DSC-013.

- **Decision:** SAME.
- **Source:** sdp-area-14 §Screens (integrations: Microsoft Intune; probes and discovery: SCCM integration); sdp-area-07 §Config (SCCM columns); architecture §2.14 (endpoint and UEM); REQ-DSC-013
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. An Intune connection imports managed devices and shows the run counts.
  2. An SCCM database reachable only on the customer network is read through the relay agent.
  3. A failed SCCM connection shows "connection failed" with the reason.

#### REQ-INT-075 — AgentX, natively

AgentX is connected natively: pairing an AgentX server or service with the tenant, then using
its agents for discovery (file 07), remote control (REQ-AST-057), runbooks (REQ-RUL-032) and
software installs in fulfilment (REQ-SR-055). The connector shows paired agents, their last
contact and version.

- **Decision:** BETTER. The vendor needs separate endpoint products for these.
- **Source:** architecture §2 (parity rule: AgentX), §2.14 (endpoint and UEM); product-plan Appendix B (AgentX native); REQ-AST-057; REQ-RUL-032; REQ-SR-055
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. After pairing, agents appear with last contact time, and an agent silent for 7 days is
     flagged.
  2. Unpairing stops all AgentX actions at once, and records using them show the action
     disabled with a reason.

#### REQ-INT-076 — PatchX: patches from tickets and changes

With PatchX connected, technicians see a machine's missing patches on its asset (REQ-DSC-024)
and can request a patch deployment from an incident or a change. The deployment runs in PatchX
after the change's approvals; its progress and result are written back to the record.

- **Decision:** BETTER. Native through PatchX instead of a separate endpoint product.
- **Source:** architecture §2.14 (patch deployment from tickets via PatchX); product-plan Appendix B (PatchX native); REQ-DSC-024
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Requesting a patch from an unapproved change is refused with "approval pending".
  2. PatchX deployment results per machine appear on the change as they arrive.

#### REQ-INT-077 — Remote access tools

Remote control through AgentX is native. TeamViewer and AnyDesk can be connected as remote
tools for REQ-AST-057, with session start and end recorded on the record and the asset. The
choice of tools follows ADR-016.

- **Decision:** SAME. The vendor sells remote control as an add-on licence.
- **Source:** architecture §2.14 (remote access: TeamViewer, AnyDesk, AgentX); sdp-area-14 §Licence and plan (remote control add-on); ADR-016; REQ-AST-057
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Starting a TeamViewer session from an incident adds a note with the session start.
  2. With no remote tool connected, the action is disabled with a reason.

---

## 12. Telephony, WhatsApp and SMS

#### REQ-INT-078 — Telephony

Phone systems (generic SIP, 3CX and cloud telephony providers) connect through an adapter.
Incoming calls pop the caller's details and open records to the technician; calls can be
logged as a new record or a note with duration and recording link; technicians can click to
call. A telephony log lists calls with caller, receiver, record and time.

- **Decision:** SAME.
- **Source:** sdp-area-14 §Screens (integrations: cloud telephony; telephony log columns); architecture §2.14 (telephony: screen pop and call logging)
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. An incoming call from a known number shows the requester and their open records within
     2 seconds.
  2. Ending a call offers "log as incident" with the call time filled in.
  3. The telephony log shows each call with a link to its record.

#### REQ-INT-079 — WhatsApp

Requesters can raise and follow requests over WhatsApp Business. Outbound messages outside the
provider's reply window use approved message templates in the requester's language. Requesters
opt in and can opt out.

- **Decision:** SAME.
- **Source:** sdp-area-14 §Screens (integrations: WhatsApp); architecture §2.14 (collaboration: WhatsApp), §6.8; product-plan Appendix B (WhatsApp Business P0)
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. A WhatsApp message from a known number creates an incident with channel WhatsApp.
  2. A technician's public reply after the reply window is sent with an approved template.
  3. A requester who opted out gets no WhatsApp messages.

#### REQ-INT-080 — SMS gateways

Admins connect an SMS gateway for the text channel (REQ-NTF-006): a generic HTTP gateway with
a request template, and ready set-ups for common providers including local ones in the
target markets. Optional two-way texts let a requester reply to a record.

- **Decision:** BETTER. The vendor's default sends texts through carrier email addresses.
- **Source:** sdp-area-14 §Screens (SMS settings: mobile service or SMS gateway); REQ-NTF-006; REQ-NTF-007; product-plan Appendix B (local SMS gateways)
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. A test text through a generic HTTP gateway shows the gateway's answer.
  2. A reply text from a requester's number adds a note to the record named in the text.

---

## 13. Automation platforms, BI and business systems

#### REQ-INT-081 — Zapier, Power Automate and n8n

SupportX has published connectors for Zapier, Microsoft Power Automate and n8n, with triggers
(record created, status changed, approval decided) built on webhook subscriptions and actions
(create record, add note, change status) built on the public API with OAuth. n8n, which can be
self-hosted, gives on-prem customers the same option.

- **Decision:** BETTER. Adds Power Automate and self-hosted n8n to the vendor's Zapier option.
- **Source:** sdp-area-14 §Screens (integrations: Zapier, enabled from the other side); architecture §2.14 (automation and iPaaS)
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. A Zapier trigger on "incident created" fires within 1 minute of creation.
  2. A Power Automate action can create an incident with OAuth consent from the user.

#### REQ-INT-082 — BI connector set-up

Admins set up the read-only BI connector (REQ-RPT-060): create a BI service account with a
scope (sites, desks, customers), get connection details for SQL or OData access, and schedule
an export into a customer's SQL Server where policy needs it. Accounts can be revoked at once.

- **Decision:** NEW. The vendor sells a separate analytics product.
- **Source:** architecture §2.14 (analytics: read-only reporting connector), §7.5; sdp-area-14 §Screens (analytics add-on promo); REQ-RPT-060; REQ-RPT-061
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. Creating a BI account shows the connection string once and records the account in the
     audit log.
  2. A BI account scoped to the IT desk reads no HR desk rows.
  3. A scheduled SQL Server export shows each run's row counts and errors.

#### REQ-INT-083 — HR systems and business applications

HR systems (Workday, SAP SuccessFactors, local HR systems) can send joiner, mover and leaver
events that start the matching journeys (REQ-ESM-024 to REQ-ESM-026). Other business systems
(SAP, Oracle, Salesforce) connect through inbound endpoints, webhook subscriptions or
packaged extensions.

- **Decision:** NEW.
- **Source:** product-plan Appendix B (business systems: SAP, Oracle, Salesforce, Workday, local HRIS); architecture §2.2 (onboarding orchestration)
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. A new-hire event from the HR system starts an onboarding journey with the start date
     and manager from the event.
  2. The same event delivered twice starts one journey.

---

## 14. Knowledge sources and AI providers

#### REQ-INT-084 — Confluence and SharePoint as knowledge sources

Admins connect Confluence spaces and SharePoint sites as knowledge sources (REQ-KB-061): choose
spaces or sites, a crawl schedule, and whether to apply the source's permissions per user or
limit the source to chosen groups. Each crawl is a sync run (REQ-INT-009). Content is indexed
for search and AI retrieval, and never copied into the knowledge base.

- **Decision:** NEW.
- **Source:** architecture §2.14 (Confluence and SharePoint knowledge sources); sdp-area-10 §Fields (chatbot: search external sources), §Weak spots; REQ-KB-061
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A crawl of one Confluence space shows the number of pages indexed.
  2. A page removed in Confluence disappears from search after the next crawl.
  3. With per-user permissions, a page restricted in SharePoint is not returned to a user
     without access there.

#### REQ-INT-085 — AI providers in the connector catalogue

AI providers (the local model runtime and cloud providers) appear in the connector catalogue
(REQ-INT-001) with their health, and link to their set-up in AI administration. Provider
types, bring-your-own-key, the connection test, terms and key storage are specified in file 10
(REQ-AI-006, REQ-AI-007, REQ-AI-009, REQ-AI-010, REQ-AI-015); this file adds only the shared
catalogue entry and the shared egress rules (REQ-INT-015).

- **Decision:** BETTER. In the vendor, providers are enabled in the integration catalogue but
  chosen in a separate AI area with no link between them.
- **Source:** sdp-area-14 §Screens (integrations: Azure OpenAI, ChatGPT, Claude, Google AI Studio); sdp-area-10 §Fields (providers disabled until enabled under third-party integration), §Weak spots; architecture §2.14 (AI); D-049
- **SDP weak spot fixed:** providers are switched on in one area and chosen in another, with
  no link.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A configured provider shows in the catalogue with the same health as on the AI settings
     page.
  2. The catalogue entry opens the provider's set-up in AI administration (REQ-AI-009).
  3. Calls to a cloud provider go through the shared egress layer and appear in its call log
     with prompts masked.

---

## 15. Connections and the intranet relay

#### REQ-INT-086 — One credential store for connectors, webhooks and functions

Connectors, webhook actions (REQ-RUL-014) and custom functions (REQ-RUL-018) use the same
connections (REQ-RUL-016). A connector's connection can be reused by a function, so a function
that calls Jira does not need its own Jira secret. Each connection lists everything that uses
it.

- **Decision:** BETTER. In the vendor, function connections and integration settings are
  separate.
- **Source:** sdp-area-14 §Screens (developer space: connections); REQ-RUL-016; architecture §11.3
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A function that uses the "Jira production" connection calls Jira with that connector's
     token.
  2. The connection page lists the connector, two webhooks and one function that use it.

#### REQ-INT-087 — The intranet relay agent

SaaS tenants can install a relay agent on their own network so SupportX can reach internal
systems: directories (REQ-INT-065), SCCM databases, internal mail servers, intranet webhooks
and functions. The agent keeps one outbound, mutually authenticated connection; no inbound
port is opened. Admins allowlist the internal hosts and ports it may reach. Two agents can run
for resilience. It may be the same component as the discovery site probe (file 07).

- **Decision:** BETTER. The vendor offers "intranet" webhook endpoints from its cloud with no
  visible agent model; we make the path explicit and controlled.
- **Source:** sdp-area-12 §Fields (webhook endpoint: cloud or intranet); architecture §6.9 (site probe: one outbound connection); file 03 open question 11
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. With the relay installed, a webhook to an intranet host on the allowlist succeeds; a host
     not on the allowlist is refused by the agent.
  2. The relay shows online or offline, version and last contact; offline for 5 minutes
     notifies admins.
  3. Stopping one of two agents does not interrupt calls.

---

## 16. Extensions

#### REQ-INT-088 — Installable extension packages

An extension is a signed, versioned package that adds configuration (fields, templates,
workflows, reports), custom functions, UI widgets or a connector. Its manifest declares the
permissions and outbound hosts it needs; an admin reviews and consents to them at install.
Extensions can be upgraded, rolled back to the previous version and uninstalled, which removes
what they added but keeps records created with them.

- **Decision:** BETTER. The vendor has a marketplace; we add declared permissions, rollback
  and clean uninstall.
- **Source:** sdp-area-14 §Screens (extensions: marketplace, my extensions), §Edition notes
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Installing an extension shows its permissions and hosts; declining installs nothing.
  2. Rolling back to the previous version restores its configuration and functions.
  3. Uninstalling removes its widgets and functions, and records it created stay readable.

#### REQ-INT-089 — Extensions run sandboxed

Extension code never runs in the API process or in the console's page. Server code runs in
the custom function sandbox (REQ-RUL-019, ADR-011) with its declared hosts only. UI widgets
run in a sandboxed frame and talk to the page through a small, permission-checked interface,
with the user's permissions.

- **Decision:** BETTER. Strict isolation of third-party code.
- **Source:** architecture §6.7 (custom functions never in the API process), §11.4 (strict CSP); ADR-011; REQ-RUL-019
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A widget cannot read the session cookie or the page's DOM.
  2. Extension server code calling a host it did not declare is refused.
  3. A widget asking for a record the user may not see gets an access error.

#### REQ-INT-090 — Custom widgets

Admins and extension authors can add widgets to record pages, the home page, dashboards and
the portal, built with a documented widget kit and run as in REQ-INT-089. A widget can be
tested in a preview before it is published.

- **Decision:** SAME. The vendor offers custom widgets built with its own toolkit.
- **Source:** sdp-area-14 §Screens (developer space: custom widgets, toolkit)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A widget added to the incident page shows data from an outside system through a
     connection.
  2. A widget fails visibly with a message in its frame, without breaking the page.

#### REQ-INT-091 — Who publishes extensions

Only extensions signed by Extravis or by publishers the tenant trusts can be installed. Admins
can also install their own unsigned extensions in a sandbox environment for development.
On-prem and air-gapped installs install extensions from a file.

- **Decision:** BETTER. Signing and offline install.
- **Source:** sdp-area-14 §Screens (marketplace: filters for deployment type), §Edition notes; architecture §11.4 (signed artefacts), §14.2 (air-gapped)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. An extension with a broken signature is refused at install.
  2. An air-gapped install installs a signed extension file with no internet access.

#### REQ-INT-092 — No public marketplace with payments, for now

SupportX does not run a public marketplace with third-party listings, ratings and payments in
this plan. A catalogue of extensions published by Extravis (and later partners) is shown in
the product.

- **Decision:** SKIP. A public store needs review, payments and support processes that are not
  yet planned; open question 6. Replaced by Extravis-published extensions (REQ-INT-088) and
  the connector catalogue (REQ-INT-001).
- **Source:** sdp-area-14 §Screens (marketplace with ratings, price and edition filters)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. The in-product catalogue lists only Extravis-published or tenant-trusted extensions.
  2. No payment flow exists in the product.

---

## 17. MCP server

#### REQ-INT-093 — The MCP server as an API surface

The MCP server (file 10: REQ-AI-104 to REQ-AI-107) is served by the `integrations` module next
to the REST API. It uses the same OAuth clients and consents (REQ-INT-020), the same rate
limits (REQ-INT-022) and the same API usage view (REQ-INT-028), and it appears in the connector
catalogue. Tool choice, sign-in as a user and logging are specified in file 10.

- **Decision:** BETTER. The vendor's MCP connector is cloud only and needs its own account.
- **Source:** architecture §6.1 (integrations: MCP server), §10 (MCP server); product-plan §7.1 (open interface); REQ-AI-104
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Revoking an MCP client's consent on the OAuth clients page (REQ-INT-020) stops its tool
     calls at once.
  2. MCP tool calls count against the caller's API rate limit and show in API usage.

---

## 18. Live chat

#### REQ-INT-094 — Native live chat, no separate product

Live chat is built into SupportX: no separate chat product, account or add-on licence. It
works on SaaS and on-prem. The requester's side is REQ-PRT-030.

- **Decision:** BETTER. The vendor's live chat runs on a separate chat product with an add-on
  licence, and its advanced settings live in that product.
- **Source:** sdp-area-14 §Screens (chat settings: separate chat product, advanced settings outside), §Licence and plan (live chat add-on), §Weak spots; product-plan Appendix A (live chat price per technician); architecture §2.15 (live chat)
- **SDP weak spot fixed:** chat set-up lives outside the product and is licensed separately.
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. All chat settings are in SupportX admin; no outside account is needed.
  2. Live chat works on an on-prem install with no internet access.

#### REQ-INT-095 — Technician chat console and availability

Technicians who handle chat set their chat availability, see waiting and active chats, handle
several chats at once up to a set limit, use reply templates, send and receive files, see the
requester's context (open records, assets) and turn a chat into a record or add it to one.
Typing and read states update live.

- **Decision:** SAME.
- **Source:** sdp-area-14 §Screens (chat settings: representatives); architecture §2.15 (live chat: attachments, canned responses); REQ-PRT-030
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. A technician at their chat limit (Appendix A) gets no new chats until one ends.
  2. Turning a chat into an incident keeps the full transcript and files on the incident.
  3. The requester's open records show beside the chat.

#### REQ-INT-096 — Chat routing, queues and transfer

Chats are routed by topic to groups, then to available technicians in the group, in turn or by
load. Waiting requesters see their place in the queue. A technician can transfer a chat to a
person or group with a note. Groups choose whether chat is on for them.

- **Decision:** SAME. The vendor enables chat per group.
- **Source:** sdp-area-14 §Screens (chat settings: per-group enable); architecture §2.15 (routing to expert groups)
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. A chat on the topic "network" goes to an available member of the Network group.
  2. A transferred chat keeps its transcript and the transfer note.
  3. With no one available, the requester is offered a request (REQ-PRT-030).

#### REQ-INT-097 — Chat widget for websites

The chat can be embedded on the tenant's websites with a script. Admins list the allowed
website domains; the widget refuses to load elsewhere. Visitors who are not signed in verify
their email before a record is created (REQ-PRT-027).

- **Decision:** SAME. The vendor offers a website embed script.
- **Source:** sdp-area-14 §Screens (chat settings: website embed script); architecture §2.15 (website widget); REQ-PRT-027
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. The widget loads on an allowed domain and refuses to start on another.
  2. A guest chat creates a record only after the guest verifies their email.

#### REQ-INT-098 — Hand-over from the assistant to a person

When the portal assistant (file 10, REQ-PRT-028) cannot help, the requester can ask for a
person, and the conversation so far moves into a live chat. Chat measures (wait time, missed
chats, chat to record rate) feed reports (file 09).

- **Decision:** BETTER. The vendor's scripted chat flows are web only and separate from live
  chat.
- **Source:** sdp-area-10 §Screens (blended conversations, web only); sdp-area-14 §Screens (chatbot tabs); architecture §2.10 (virtual agent); REQ-PRT-028
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. "Talk to a person" moves the assistant transcript into the chat queue.
  2. Missed chats in a day are counted in the chat report.

---

## 19. The vendor's own products

#### REQ-INT-099 — No integrations with the vendor's own suite

SupportX does not integrate with the vendor's own products and suite: its device management,
directory management, endpoint management, network and application monitoring, alert
management and SaaS management products, its analytics, survey, chat, workflow and
orchestration products, or its account and directory platform.

- **Decision:** SKIP. These exist because the vendor splits features across its own products.
  SupportX delivers them natively (surveys, analytics, live chat, directory sync, workflows,
  file 09, file 11) or through Extravis products (MonetX, AgentX, PatchX).
- **Source:** sdp-area-14 §Screens (integrations: vendor and suite tabs; analytics and survey promos; chat settings; ESM directory notice); architecture §2 (parity rule)
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. The connector catalogue has no entry for a vendor product.
  2. Each capability those products give the vendor maps to a SupportX requirement in the
     migration tool's report.

#### REQ-INT-100 — No outside account platform for security settings

Every security and access setting for integrations (API keys, OAuth clients, IP allowlists,
connection secrets) is managed inside SupportX admin, not in an outside account platform.

- **Decision:** SKIP of the vendor's model. The vendor keeps security, sessions and domain
  policy in its account and directory platform. Replaced by REQ-INT-019 to REQ-INT-021 and
  file 11.
- **Source:** sdp-area-14 §Weak spots (security controls outside the product), §Limits (no API key console, no IP restriction)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A tenant admin can create, limit and revoke API access without any outside account.
  2. Every page named in REQ-INT-019 to REQ-INT-021 is found by the admin search in SupportX.

---

## 20. Department desks in one tenant

#### REQ-ESM-001 — One product, one login, desks as configuration

Enterprise service management runs inside one tenant. HR, facilities, finance, legal and any
other function each get a department desk, which is configuration in the same product: the
same login, the same directory, the same console and portal, the same engine (REQ-WI-001).
Adding a desk needs no new install, URL, licence key or user import.

- **Decision:** BETTER. The vendor creates each desk as a separate instance with its own URL,
  its own settings and users added per instance, managed from a separate directory console.
- **Source:** sdp-area-14 §Screens (instances and ESM: new instance form, instance types, ESM directory, service instances), §Weak spots (directory end-of-support notice); architecture §2.15 (ESM), §7.2 (desks are partitions inside a tenant), §6.1 (esm); product-plan §5 (ESM: one data model, unlimited desks), §8 (multi-tenant data model)
- **SDP weak spot fixed:** separate instances per function, each with its own URL and user
  membership, and a directory console that is being retired.
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. A technician who works in IT and facilities signs in once and switches desk without a new
     sign-in.
  2. Creating a desk takes effect at once, with no new URL, install or licence file.
  3. A person added to the directory is available as a requester in every desk.

#### REQ-ESM-002 — Every record belongs to a desk from day one

Every work item, catalog item, template, group, SLA policy, knowledge category and mailbox
belongs to a desk. Each tenant starts with one IT desk, which holds everything until more desks
are added. Tenants without ESM never see the desk field. This way ESM adds data, not a
migration.

- **Decision:** NEW. Designs the desk partition into the engine from the start (architecture
  §7.2).
- **Source:** architecture §7.2 (department partitions in the core data model); product-plan §8 (multi-tenant data model: tenant, department and site partitioning)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A new tenant has one IT desk, and every incident created is in it.
  2. In a tenant without ESM, no screen, list column or filter shows a desk.
  3. Turning ESM on later needs no data migration of existing records.

#### REQ-ESM-003 — Desk settings

Each desk has a name, a type (IT, HR, facilities, finance, legal or custom), a description, an
owner, desk admins, a time zone, operating hours and holidays (file 03), an icon and branding
for its portal pages, and a status: draft, active or archived. A draft desk is visible only to
its admins while it is built.

- **Decision:** SAME. The vendor's instance form has name, type, owner, time zone and access.
- **Source:** sdp-area-14 §Screens (instance settings: name, type, time zone, owner, access, week start), §Fields (new instance form); architecture §2.15
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. An HR desk in a different time zone shows its SLA due times in its own operating hours.
  2. A draft desk does not appear in the portal until it is made active.
  3. Each settings change is recorded in the desk's history.

#### REQ-ESM-004 — Create a desk from a template

Admins create a desk from a starter template (HR, facilities, finance, legal), from a blank
desk, or by copying an existing desk. A starter template brings categories, catalog items,
record templates, statuses and life cycles, SLA policies, groups, notification templates and
knowledge categories (Appendix A), all editable after creation.

- **Decision:** BETTER. The vendor's instance types start almost empty.
- **Source:** sdp-area-14 §Fields (instance types: IT help desk, facilities, finance, HR); architecture §2.15 (HR, facilities, finance and legal desks)
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. Creating an HR desk from its template gives a desk with HR categories, catalog items and
     SLA policies ready to use.
  2. Copying the HR desk copies its configuration but no records.
  3. Changing the starter template later does not change desks already created from it.

#### REQ-ESM-005 — Each desk owns its configuration

Each desk has its own catalog, record templates, form layouts, categories, statuses and life
cycles, workflows and rules, SLA policies, groups and technicians, notification templates,
custom fields, knowledge categories, mailboxes and reports. Tenant admins can also make items
shared across desks (for example a common priority matrix or a VIP list). Every list in admin
filters by desk, and each item shows whether it is desk-owned or shared.

- **Decision:** SAME. The vendor's instances each have their own templates, workflows and
  users.
- **Source:** sdp-area-14 §Screens (ESM directory: separate instances with own templates, workflows and users); architecture §2.15, §6.6
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. An HR status "with payroll" is offered only on HR desk records.
  2. A shared priority matrix change applies in every desk at once.
  3. A facilities workflow cannot be attached to an IT template.

#### REQ-ESM-006 — Desk-specific numbering

Each desk can have its own display ID prefix per record type with its own counter, for example
HR-12 or FAC-40, from the per-tenant sequence table (REQ-WI-002, D-045). Moving a record to
another desk keeps its ID (REQ-ESM-018).

- **Decision:** SAME. The vendor's instances number records independently.
- **Source:** architecture §7.1 (display IDs per tenant sequence); D-045; REQ-WI-002; sdp-area-14 §Screens (instances)
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. The first record in a new HR desk with prefix HR gets HR-1, while IT incidents keep INC
     numbers.
  2. Searching "HR-1" opens that record for users who may see it.

#### REQ-ESM-007 — Desk names for record types

A desk can rename how its record types are shown, for example "case" in HR or "work order" in
facilities, through labels in each language. The engine type underneath stays the same, so
rules, SLAs and reports work as for IT.

- **Decision:** NEW.
- **Source:** architecture §6.1 (esm: HR cases), §9.5 (labels); CLAUDE.md §5d
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. HR desk screens say "case" in English and its Arabic label, never "incident".
  2. A report across desks groups HR cases with IT incidents by the engine type when asked.

#### REQ-ESM-008 — Archive and reactivate a desk

A desk with records cannot be deleted. It can be archived: it disappears from the portal and
from new-record choices, its records stay readable to people who could see them, and it can be
reactivated. An empty draft desk can be deleted.

- **Decision:** BETTER. The vendor's instances can be deleted from the instance list.
- **Source:** sdp-area-14 §Screens (service instances: actions edit, delete); CLAUDE.md §6 (soft delete)
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. Archiving the legal desk hides it in the portal and keeps its cases searchable for its
     members.
  2. Delete is refused on a desk with records, with the reason.

---

## 21. Isolation, permissions and delegated administration

#### REQ-ESM-009 — Records are private to their desk

By default, a desk's records are visible only to that desk's technicians and to the people on
the record (requester, on-behalf-of person, approvers, followers). Tenant admins can open a
desk to named groups from other desks, read-only or with edit rights. IT technicians do not
see HR cases unless given access.

- **Decision:** BETTER. Isolation is a permission rule inside one data model, not a separate
  instance, so cross-desk reporting stays possible (architecture §7.2).
- **Source:** architecture §11.2 (attribute: HR case records visible only to the HR group), §7.2; product-plan §5 (secure department partitioning)
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. An IT technician opening an HR case by its URL gets "not found", not "forbidden".
  2. Giving the IT service desk group read access to facilities lets them see facilities
     records but not change them.
  3. A requester sees their own HR case in the portal.

#### REQ-ESM-010 — Desk isolation holds on every path

Desk isolation is enforced in the one policy layer, so it holds in lists, search, record
pages, reports and dashboards, realtime events, notifications, exports, the API, webhook
subscriptions, the BI connector and AI features.

- **Decision:** NEW.
- **Source:** architecture §11.2 (one policy layer for API, search, realtime and AI), §8.2
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. A search for an HR case's subject by an IT technician returns no hit and no count.
  2. An IT technician's browser receives no realtime event for an HR case.
  3. A webhook subscription whose identity lacks HR access receives no HR events.

#### REQ-ESM-011 — Desk admins

Each desk has desk admins who manage that desk's configuration (REQ-ESM-005), its groups and
technician membership, and its connectors where the connector allows desk scope, without
tenant admin rights. They cannot change other desks, tenant-wide settings, shared items,
licensing or security. Every change they make is audited.

- **Decision:** BETTER. In the vendor, each instance has its own admins but directory and
  security are managed in a separate console.
- **Source:** sdp-area-14 §Screens (instance owner, access permissions, ESM directory user management); architecture §11.2
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. The HR desk admin can add an HR catalog item but cannot open the IT desk's settings.
  2. The HR desk admin cannot change the shared priority matrix; the action is disabled with a
     reason.
  3. The HR desk admin can add a technician to the HR desk only if the tenant has a free
     technician licence.

#### REQ-ESM-012 — People who work in several desks

A technician can belong to several desks with a different role in each. The console has a desk
switcher and an "all my desks" view, and lists show a desk column when more than one desk is
in view. A technician counts once for licensing, however many desks they work in.

- **Decision:** BETTER. The vendor adds users to each instance separately.
- **Source:** sdp-area-14 §Screens (ESM directory: add or remove user to an instance; left-rail instance switcher); product-plan §9.1 (price per technician)
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. A technician in IT and facilities sees both desks' queues in "all my desks".
  2. The licence count shows the technician once.
  3. A technician who is a desk admin in facilities and a technician in IT has admin rights in
     facilities only.

#### REQ-ESM-013 — AI stays inside desk boundaries

AI features (similar records, suggested answers, summaries, classification models) use only
records the user may see, and models trained on one desk's records are not used to suggest in
another desk unless the tenant allows it. Confidential cases (REQ-ESM-022) are never used for
training or retrieval outside their handlers.

- **Decision:** NEW.
- **Source:** architecture §12 (retrieval applies permissions; predictions trained per tenant), §11.2
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. "Similar records" on an IT incident never lists an HR case.
  2. A confidential case's text does not appear in any AI answer for a user outside its
     handlers.

---

## 22. Directory, requesters and portal

#### REQ-ESM-014 — One directory for every desk

Requesters and technicians come from one directory for the tenant (file 11 and REQ-INT-063 to
REQ-INT-066). A person has one profile, one set of assets and one history across desks. Desks
do not import users.

- **Decision:** BETTER. The vendor's desks rely on a separate directory product, whose own
  user management is being retired.
- **Source:** sdp-area-14 §Screens (ESM directory: user management, custom domains, SAML, AD settings; end-of-support banner), §Weak spots
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. A requester's profile shows their IT incidents and HR cases (to people allowed to see
     both).
  2. A new employee synced from Entra ID can raise a facilities request without any desk
     set-up.

#### REQ-ESM-015 — Desks in the shared portal

The shared portal (REQ-PRT-033) shows each active desk to the audiences the desk chooses (all
employees, chosen sites, departments or groups). The tenant chooses a preferred landing page
per audience: the shared home or a chosen desk. Each record in the portal shows which desk
handles it, with that desk's names and status labels.

- **Decision:** SAME. The vendor's enterprise portal has a preferred landing page.
- **Source:** sdp-area-14 §Screens (ESM portal: customise, preview, publish, preferred landing page); sdp-area-01 §Screens (ESM portal link); REQ-PRT-033
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. A desk limited to the head-office site is not shown to requesters of other sites.
  2. With landing set to the HR desk for the HR department, HR staff open the portal on the
     HR desk.
  3. "My requests" shows the desk name next to each record.

#### REQ-ESM-016 — Desk addresses

Each desk has its own portal path under the tenant's address (for example `/portal/hr`), and
can have its own branded domain with automatic TLS (D-027). Desk links in emails use the
desk's address.

- **Decision:** SAME. The vendor offers custom service URLs per instance.
- **Source:** sdp-area-14 §Screens (ESM directory: custom service URLs with SSL status; instance URL name); D-027
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. Opening `/portal/hr` lands on the HR desk's portal page.
  2. A branded domain for facilities shows its TLS status and serves the facilities pages
     once verified.

#### REQ-ESM-017 — Desk announcements and knowledge in the portal

Each desk publishes announcements and knowledge to its own audiences in the portal. A desk's
internal knowledge stays inside the desk. The portal search finds content from every desk the
requester may see.

- **Decision:** SAME.
- **Source:** architecture §2.15 (unified portal, knowledge); sdp-area-13 §Requester Portal (portal search scope); REQ-KB-045
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. An HR policy article published to employees is found from the shared portal search.
  2. An HR internal article is not found by IT technicians.

---

## 23. Work across desks

#### REQ-ESM-018 — Move a record to another desk

A technician can move a record that reached the wrong desk to another desk, with a reason. The
record keeps its ID and history; it takes the target desk's template mapping, statuses and SLA,
and its private notes stay hidden from the target desk unless the technician chooses to share
them. The requester is told which desk now handles it.

- **Decision:** BETTER. The vendor's separate instances cannot hand a record over cleanly.
- **Source:** sdp-area-14 §Screens (instances and ESM: separate desks); architecture §2.15; REQ-WI-003
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. Moving an IT incident about payroll to the HR desk keeps its ID and adds a history entry
     with the reason.
  2. The HR desk sees the public conversation but not the IT private notes, unless shared.
  3. A status with no match in the target desk asks the technician to choose one.

#### REQ-ESM-019 — Ask another desk for help

From a record, a technician can create a task or a linked record in another desk (for example
facilities to install a desk for a new hire). The other desk works it in its own queue; the
first record shows its status and is notified when it is done. This is the ad-hoc form of the
planned orchestration in REQ-SR-057.

- **Decision:** BETTER. Cross-desk work without separate instances.
- **Source:** architecture §2.2 (orchestration across HR, IT and facilities); REQ-SR-057
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. A task created for facilities from an IT incident appears in the facilities queue.
  2. Completing it updates the IT incident live and notifies its assignee.

#### REQ-ESM-020 — Links to records you cannot see

When a record links to a record in a desk the user cannot see, the link shows only "restricted
record" with its desk and status category, never its subject or content.

- **Decision:** NEW.
- **Source:** architecture §11.2; REQ-WI-003 (links on both sides)
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. An IT technician sees "restricted record (HR desk), open" on an incident linked to an HR
     case.
  2. The API returns the same restricted view for that link.

#### REQ-ESM-021 — Search and lists across desks

People with access to several desks can search and build list views across them, with a desk
filter and column. Saved views can be limited to one desk or cover all.

- **Decision:** BETTER. Each vendor instance is searched on its own.
- **Source:** sdp-area-14 §Screens (instance switcher); architecture §7.2 (shared reporting across departments)
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. A manager with IT and facilities access finds records from both with one search.
  2. Filtering the view by desk "facilities" shows only facilities records.

---

## 24. HR case management

#### REQ-ESM-022 — Confidential cases

A case can be marked confidential, by template default or by a handler. A confidential case
is visible only to its named handlers and a chosen HR group, not to every HR desk member. Other
HR staff see neither its content nor that it exists. A person with the "confidential access"
permission can open one with a stated reason; the access is logged and the case owner is told.

- **Decision:** NEW. product-plan asks for HR confidential cases; the vendor separates HR only
  by instance.
- **Source:** product-plan §5 (ESM: HR confidential cases); architecture §11.2 (attribute rules), §7.4 (data-access logs)
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. An HR technician who is not a handler cannot find a confidential case by search, list or
     ID.
  2. Opening it with "confidential access" requires a reason, logs the access and notifies the
     owner.
  3. Making a case confidential removes it from other HR staff's open views live.

#### REQ-ESM-023 — Sensitive HR fields protected

HR desks can mark fields as sensitive (for example salary, medical details, disciplinary
outcome). Sensitive fields are encrypted at rest at field level, masked for roles without
permission, left out of notifications and search snippets, and never sent to an external AI
model.

- **Decision:** NEW.
- **Source:** architecture §11.2 (field: salary or PII hidden or masked), §11.3 (field-level encryption, PII masking before external AI); product-plan §8 (field-level encryption)
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. A role without permission sees a sensitive field as masked in the record, list and export.
  2. A notification template that refers to a sensitive field sends a masked value.
  3. A summary made with an external model receives the field masked.

#### REQ-ESM-024 — Onboarding journeys

An onboarding journey turns one new-hire request or HR system event (REQ-INT-083) into a plan
across HR, IT and facilities: tasks with deadlines relative to the start date (for example
account five days before, desk and laptop one day before), approvals, and a checklist for the
manager. The new hire and manager see progress in the portal. It builds on REQ-SR-057.

- **Decision:** BETTER. The vendor ships onboarding templates and workflows inside one
  instance.
- **Source:** sdp-area-03 §Config (employee onboarding templates); sdp-area-02b §Behaviour (onboarding workflow started); architecture §2.2 (onboarding orchestration across HR, IT and facilities); product-plan §7.2 (onboarding across HR, IT and facilities); REQ-SR-057
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. A new hire starting on the 10th creates an IT account task due on the 3rd and a
     facilities task due on the 9th.
  2. Changing the start date moves every open task's deadline.
  3. The manager's portal page shows each desk's progress live.

#### REQ-ESM-025 — Offboarding journeys

An offboarding journey plans the steps for a leaver across desks, relative to the last working
day: access removal (REQ-INT-067), asset return (file 07), final pay and documents. Access
removal can be set to happen at a fixed time on the last day. Open steps after the last day are
escalated.

- **Decision:** BETTER.
- **Source:** sdp-area-03 §Config (payroll: employee leaving template); architecture §2.2 (offboarding orchestration)
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. A leaver's journey lists the assets assigned to them for return.
  2. With automatic access removal, the account is disabled at the set time on the last day and
     the result is noted.
  3. An asset not returned one day after the last day escalates to the IT desk.

#### REQ-ESM-026 — Transfer journeys

A transfer journey handles a change of department, site or role: access changes, asset moves,
seat moves and approvals from both managers.

- **Decision:** SAME. The vendor ships a department-change request template.
- **Source:** sdp-area-03 §Config (payroll: department change of a user; change of place)
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. A transfer creates tasks for the old and new site's facilities teams.
  2. Both managers must approve before access changes run.

#### REQ-ESM-027 — Cases about another person

An HR case can have a subject person who is not the requester (for example a manager raising a
concern about an employee). The subject is not notified and cannot see the case unless a
handler chooses so. Cases about a person are listed on that person's profile only for HR
handlers.

- **Decision:** NEW.
- **Source:** architecture §2.15 (HR desk), §11.2 (attribute rules)
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. A case with a subject person sends no notification to that person.
  2. The subject person's portal does not show the case.

#### REQ-ESM-028 — Retention and legal hold per desk

Each desk can set how long closed records are kept before they are anonymised, and handlers
can place a legal hold on a record that stops it from being anonymised or deleted until the
hold is lifted. Holds and their reasons are audited. Erasure itself is in file 11.

- **Decision:** NEW. The vendor has one archive rule for requests and no legal hold.
- **Source:** sdp-area-13 §Data Archive (one rule); architecture §11.3 (retention policies per record type), §2.15 (compliance tooling)
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. An HR case closed longer than the desk's retention is anonymised by the nightly job.
  2. A case under legal hold is skipped by that job and listed in the hold report.

---

## 25. Facilities

#### REQ-ESM-029 — Spaces and floor plans

Facilities desks keep a space hierarchy: campus, building, floor, room or zone, and seat. Each
space has a type, capacity, equipment, accessibility notes, an owner and a status. A floor can
have a floor plan image with spaces drawn on it, and spaces link to sites (file 11) and to
assets located there (file 07).

- **Decision:** BETTER. The vendor has a space tree; product-plan asks for floor plans.
- **Source:** architecture §2.15 (space management: campus, building, floor, room); product-plan §5 (facilities floor plans); sdp-area-14 §Fields (facilities desk instance type)
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. A floor plan shows rooms as clickable areas that open their space record.
  2. A room lists the assets located in it.
  3. Spaces can be imported from a file with their parent spaces.

#### REQ-ESM-030 — Spaces on records and in the portal

Any record can name the space it concerns. In the portal, requesters choose a space from a
search or by tapping it on the floor plan. A space shows its open records, so a technician can
see that a room already has an open fault.

- **Decision:** NEW.
- **Source:** architecture §2.15 (space management); product-plan §5 (facilities floor plans)
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. A requester reports a broken light by tapping the room on the floor plan.
  2. The room's page lists its open records, updated live.

#### REQ-ESM-031 — Room and seat booking

People book rooms and seats from the portal, the console and the mobile app: by time, capacity
and equipment, one-off or recurring. Double bookings are prevented, availability updates live,
bookings can require check-in, and bookings with no check-in are released after a set time
(Appendix A). Rooms can be linked to Microsoft 365 or Google room calendars (REQ-INT-070).

- **Decision:** SAME. The vendor lists room booking for facilities.
- **Source:** architecture §2.15 (room booking); REQ-INT-070
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. Two people booking the same room for the same hour: the second is refused with the next
     free slot offered.
  2. A booking with no check-in 15 minutes after start (Appendix A) is released and the room
     shows free live.
  3. A recurring weekly booking that clashes with one existing booking shows the clash before
     saving.

#### REQ-ESM-032 — Booking rules and approvals

Facilities admins set who may book which spaces, how far ahead, for how long at most, and
which spaces need approval (using the approval engine, file 02). Requests for catering, set-up
or equipment can be added to a booking and become tasks for the facilities team.

- **Decision:** NEW.
- **Source:** architecture §2.15 (room booking); REQ-SR-021
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. Booking the boardroom creates an approval for its owner, and the room is held until
     decided.
  2. Adding catering to a booking creates a facilities task due before the start time.

#### REQ-ESM-033 — Visitor management

Hosts pre-register visitors with name, company, date and host. On arrival, reception checks
the visitor in and the host is notified. The visitor log can be searched and exported, and
visitor personal data is removed after a set period (Appendix A).

- **Decision:** NEW. Not in the vendor's product; common in facilities desks.
- **Source:** architecture §2.15 (ESM: facilities); product-plan §5 (ESM)
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. Checking in a pre-registered visitor notifies the host within 10 seconds.
  2. Visitor names older than the retention period are removed by a job and the log keeps only
     counts.

#### REQ-ESM-034 — Planned maintenance for buildings

Facilities desks schedule planned maintenance for spaces and building assets (lifts, air
conditioning, generators): recurring schedules that create work orders with checklists, using
scheduled recurring records (REQ-INC-034) and non-IT assets (file 07).

- **Decision:** SAME. The vendor has maintenance schedules.
- **Source:** sdp-area-13 §Announcement and Maintenance (maintenance types); architecture §2.15 (preventive maintenance tasks); REQ-INC-034
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. A quarterly generator check creates a facilities work order with its checklist each
     quarter.
  2. The generator's asset page lists past and upcoming maintenance.

---

## 26. Finance, legal and custom desks

#### REQ-ESM-035 — Finance and legal desk starter content

Starter templates for finance (expense questions, supplier payments, supplier set-up, budget
requests) and legal (contract review, NDA, legal advice, compliance questions) come with
categories, catalog items, SLA policies and groups. Legal matters use confidential cases
(REQ-ESM-022) by default.

- **Decision:** SAME. The vendor offers a finance desk type.
- **Source:** sdp-area-14 §Fields (instance types: finance desk); architecture §2.15 (finance and legal desks)
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. A legal desk created from its template marks new contract reviews confidential.
  2. A finance desk created from its template has a supplier set-up catalog item with an
     approval stage.

#### REQ-ESM-036 — Custom desks for any function

Admins can create a desk for any function (for example marketing, security operations or
procurement) from a blank or copied desk, with every capability in this section.

- **Decision:** BETTER. The vendor offers four fixed instance types.
- **Source:** sdp-area-14 §Fields (instance type list: four fixed types); architecture §2.15
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. A "marketing" desk can be created, given its own catalog and published in the portal.
  2. A custom desk can rename its record types (REQ-ESM-007) and set its own prefix
     (REQ-ESM-006).

---

## 27. Reporting, licensing and migration

#### REQ-ESM-037 — Desk dashboards and reports across desks

Each desk gets a default dashboard for its managers (open by status, SLA results, ageing,
satisfaction). Reports can compare desks (REQ-RPT-064), and every report and widget respects
desk isolation (REQ-ESM-010).

- **Decision:** BETTER. Each vendor instance reports on its own.
- **Source:** architecture §7.2 (shared reporting across departments); REQ-RPT-064
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. A new desk has a dashboard for its managers on creation.
  2. A tenant-wide report shows HR counts but no HR case content to a user with only
     reporting access to HR totals.

#### REQ-ESM-038 — Unlimited desks in Enterprise

Enterprise includes unlimited department desks. The desk count is still read through the
entitlement interface (`check_limit`, architecture §13.1), so other plans can be offered
without code changes. There is no per-desk licence key, and technicians count once across
desks (REQ-ESM-012).

- **Decision:** BETTER. The vendor licenses each desk instance separately, with a cap.
- **Source:** product-plan §4.3 (pillar 6: unlimited department desks), §5 (separate instances, each licensed), §9 (Enterprise); architecture §13.1 (counted limit: department desks); sdp-area-14 §Licence and plan
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. An Enterprise tenant creates a 30th desk with no licence change.
  2. A tenant whose entitlement allows one desk sees "create desk" disabled with an upgrade
     hint.

#### REQ-ESM-039 — No separate instance per desk

SupportX does not create separate instances, each with its own URL, settings and user list,
for each business function.

- **Decision:** SKIP. Separate instances split data, directory and reporting. Replaced by desks
  inside one tenant (REQ-ESM-001, REQ-ESM-009).
- **Source:** sdp-area-14 §Screens (new instance form, service instances, ESM directory)
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. No admin screen creates a second tenant or URL for a business function.
  2. Desk isolation tests (REQ-ESM-010) pass inside one tenant.

#### REQ-ESM-040 — No asset-only instance type

SupportX does not offer an instance or desk that only manages assets.

- **Decision:** SKIP. Assets are a module available to every desk (file 07); the vendor's
  asset-only service type exists because it sells asset management separately.
- **Source:** sdp-area-14 §Fields (instance service type: asset-only product)
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. The desk type list has no asset-only type.
  2. Technicians in any desk with the asset permission can open assets (file 07).

#### REQ-ESM-041 — ServiceDesk Plus instances become desks

The ServiceDesk Plus migration tool maps each source instance to a desk in one tenant, with
its templates, statuses, SLAs, groups and records, and merges users that appear in several
instances into one person.

- **Decision:** NEW.
- **Source:** architecture §18 (migration from ServiceDesk Plus); sdp-area-14 §Screens (service instances)
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. Migrating two instances creates two desks and one person for a user present in both.
  2. Each migrated record keeps its source instance and ID in its history.

---

## Appendix A — Proposed defaults

These are the defaults a new tenant gets. They are seed data, not fixed behaviour: a tenant
admin can change every one of them (D-041). Platform maximums, where given, cap what a tenant
can set. The requirements above refer to this appendix.

**Connector framework** (REQ-INT-003 to REQ-INT-009):

- secret rotation reminder: 365 days after a secret was set;
- connector error list and call logs kept 30 days (platform maximum 365);
- retries for temporary errors: 5 retries with exponential backoff, about 1, 5, 15, 60 minutes
  and 3 hours (as file 03, REQ-RUL-015); then the dead-letter list, kept 14 days;
- expiry warnings for credentials and consents: 30, 14 and 3 days before.

**Public API** (REQ-INT-019 to REQ-INT-028):

| Setting | Default | Platform maximum |
|---|---|---|
| API key expiry | 90 days | 1 year; non-expiring keys off |
| Unused key flagged after | 90 days | — |
| Rate limit per token | 600 calls per minute | set by edition |
| Rate limit per tenant | 1,200 / 3,000 / 6,000 calls per minute (Essentials / Professional / Enterprise) | set by edition |
| Idempotency key kept | 24 hours | — |
| List page size | 50 | 200 |
| Change feed kept | 7 days | 30 days |

**Webhooks** (REQ-INT-030 to REQ-INT-039): delivery timeout 10 seconds; retries as above; a
subscription is paused after 24 hours of failures and its held events are kept 7 days; inbound
timestamp window 5 minutes; alert sources may open 100 new incidents per minute each.

**MonetX** (REQ-INT-043, REQ-INT-046): health answers cached 15 seconds; after 5 failed reads
in a row, no calls for 60 seconds; catch-up after an outage reads up to 7 days back.

**Email** (REQ-INT-052): mailbox poll every 2 minutes, plus push where available; largest
accepted message 35 MB.

**Identity** (REQ-INT-063, REQ-INT-068): directory delta sync every 15 minutes; self-service
password reset locks for 30 minutes after 5 failed verifications.

**Relay and agents** (REQ-INT-075, REQ-INT-087): relay offline alert after 5 minutes; AgentX
agent flagged after 7 days without contact.

**Live chat** (REQ-INT-095): 3 chats at once per technician; offer a request after 3 minutes
of waiting with no technician.

**Desks** (REQ-ESM-004, REQ-ESM-006, REQ-ESM-022, REQ-ESM-035):

| Starter desk | Prefix | Starter categories | Confidential by default |
|---|---|---|---|
| IT (every tenant) | INC, SR (as file 01) | as file 01 | no |
| HR | HR | leave, pay, benefits, policies, employee relations, onboarding, offboarding | employee relations |
| Facilities | FAC | repairs, cleaning, moves, access cards, parking, catering, room set-up | no |
| Finance | FIN | expenses, supplier payments, supplier set-up, budgets | no |
| Legal | LEG | contract review, NDA, legal advice, compliance questions | all cases |

**HR retention** (REQ-ESM-028): no automatic anonymisation until the desk admin sets a period;
the HR desk set-up prompts for one (open question 8).

**Bookings and visitors** (REQ-ESM-031 to REQ-ESM-033): book up to 30 days ahead; rooms up to
8 hours per booking; release after 15 minutes without check-in; visitor personal data kept 90
days.

---

## Open questions for the product owner

1. **Who owns mail set-up.** REQ-NTF-002 (file 03) points to file 11 for the outgoing mail
   set-up. This file holds mailbox connections, OAuth and outgoing mail per mailbox
   (REQ-INT-050 to REQ-INT-055), because architecture §6.1 puts inbound email in the
   `integrations` module. Confirm, so file 03 and file 11 can point here.
   *Proposed answer:* this file owns mailbox connections; files 03 and 11 now reference
   REQ-INT-050 to REQ-INT-055.
2. **Directory sync at MVP?** Entra ID and AD sync (REQ-INT-063, REQ-INT-065) are set to V1.
   Does the internal go-live or the design partner need them at MVP?
3. **Teams and Slack timing.** Notifications to Teams and Slack are V1 (REQ-INT-057); actions
   from chat are LATER, matching REQ-SR-040 and REQ-INC-032. product-plan Appendix B lists
   collaboration as P0. Move Teams notifications to MVP?
4. **The intranet relay agent** (answers file 03 open question 11). REQ-INT-087 sets it to V1,
   Essentials, and suggests it is the same component as the discovery site probe. Agree?
5. **Edition of extensions.** Extensions and custom widgets (REQ-INT-088 to REQ-INT-091) are
   set to Professional, LATER. Agree?
6. **Public marketplace.** REQ-INT-092 skips a public third-party marketplace with payments and
   keeps an Extravis-published catalogue. Do you want a partner marketplace later?
7. **Desks below Enterprise.** product-plan offers unlimited desks in Enterprise only, while
   architecture §13.1 counts desks as a limit. Proposal: Essentials and Professional have one
   desk (IT); Enterprise unlimited. Or allow one or two extra desks in Professional?
8. **HR retention default.** REQ-ESM-028 starts with no automatic anonymisation and prompts the
   admin. Do you want a default period (for example 7 years after closure)?
9. **Visitor management** (REQ-ESM-033) is new and not named in architecture §2.15. Keep it in
   scope for Stage 3?
10. **Where MSP lives.** The file list has no home for MSP multi-customer support (customer
    portals, contracts, billing); REQ-CON-016 points to "file 12 or a later file". This file
    covers only the customer scope of MonetX (REQ-INT-045). Add a file 13 for MSP?
11. **Desk partition at MVP.** REQ-ESM-002 asks the engine to carry a desk on every record from
    MVP, with one IT desk, so ESM needs no migration later. This touches file 01 (display IDs,
    lists). Agree?
