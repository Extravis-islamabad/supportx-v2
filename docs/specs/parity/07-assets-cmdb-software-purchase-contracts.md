# 07 — Assets, discovery, software, CMDB, purchase and contracts

Parity requirements for IT asset management and software asset management (architecture.md
§2.11), the CMDB (architecture.md §2.12), discovery (architecture.md §2.13, §6.9), purchasing,
vendors and contracts (architecture.md §2.11). Rules, ID scheme and field meanings:
[README.md](README.md).

**Status:** Draft v0.1, 2026-10-24. Phase 2, first draft for product owner review.
**Owner:** Haider (Product Owner).

## Scope of this file

- **Assets, configuration items, software, licences, vendors, contracts and purchase orders
  are not work items.** They live in their own modules (architecture.md §6.1): `assets`
  (assets, software, licences, loans, consumables), `discovery` (agents, probes, scans,
  reconciliation), `cmdb` (CI types, CIs, relationships, baselines, data quality) and
  `procurement` (vendors, products, purchase orders, invoices, contracts, renewals). Each
  module owns its tables and talks to the others only through public service interfaces or
  events.
- **Engine behaviour still applies where it fits.** Where one of these records behaves like a
  work item feature (field history, live updates, safe concurrent editing, fixed actions and
  tabs, trash, notes, attachments, approvals, lists and bulk actions), the requirement cites the
  file 01 ID and lists only what differs. Platform rules (tenant isolation, outbox, optimistic
  concurrency, entitlements, one policy layer, labels not codes) apply to everything and are
  not repeated.
- **REQ-AST-*** cover IT and non-IT assets: product types and products, the asset record,
  states and life cycle, ownership, loans, components, consumables, financials, barcodes,
  audits, links to work items, scan history and the asset pages.
- **REQ-DSC-*** cover discovery: the agent, site probes, the credential vault, network and
  domain scans, other inventory sources, identification rules and reconciliation.
- **REQ-SAM-*** cover software and licences: the software catalogue, software types,
  installations, licence types, agreements, allocation, compliance and metering.
- **REQ-CMDB-*** cover CI types, CIs, relationships, the relationship map, business views,
  impact analysis, downtimes, MonetX topology and health (read-only), baselines, data quality
  and fine-grained access for assets and CIs.
- **REQ-PUR-*** cover purchase requests and orders, approvals, receiving, invoices, payments,
  vendors, products, cost centres and budgets.
- **REQ-CON-*** cover contracts, renewals, expiry notifications and links to assets, licences
  and vendors.
- **Not in this file** (each has its own module file, see the README):
  - How a work item uses assets and CIs: the asset field on incidents (REQ-INC-015), create
    from an asset (REQ-INC-029), CI and asset links on changes (REQ-CHG-012, REQ-CHG-080),
    problems (REQ-PRB-006) and releases (REQ-REL-035), impact analysis from a change
    (REQ-CHG-082) and change downtimes (REQ-CHG-063, REQ-CHG-064). This file owns the
    asset and CI side of those links.
  - The rules, triggers, workflow and notification engines (file 03). This file says which
    events and fields asset-side records offer them (REQ-RUL-008, REQ-WF-031, REQ-NTF-008).
  - Vendor contract targets tracked like an OLA (REQ-SLA-034) and customer contract SLAs for
    managed service providers (REQ-SLA-035), in file 03.
  - The service catalogue and the requester portal shell (file 02), reports and dashboards
    (file 09), AI administration and the agent framework (file 10), roles, users, sites,
    import and export tooling (file 11), and connector set-up for Intune, SCCM, AgentX,
    PatchX and MonetX (file 12).
- **Monitoring is out of scope** (ADR-017, D-001). Discovery is inventory only: what a machine
  is and what is installed on it. SupportX never monitors performance, never polls devices for
  health and never correlates alerts (REQ-INC-146). Live health on CIs and MonetX topology are
  **read** from the MonetX API, read-only, through `monitoring_integrations`.
- **Stage and priority.** ITAM, SAM, discovery and the CMDB are Stage 2 modules
  (architecture §17), so their parity items are `V1` and "beyond SDP" items are mostly
  `LATER`. Procurement is Stage 3, so purchasing is `LATER`. Vendors and the basic contract
  record are `V1` because assets and warranties need them (open question 2). This file has no
  `MVP` items (open question 1). ITAM, discovery and the CMDB are in the Professional edition
  (product-plan §9); this file proposes Professional for purchasing and contracts too (open
  question 3).

## Words used in this file

| Word | Meaning |
|---|---|
| Asset | A physical or logical item the organisation owns and tracks: a laptop, a server, a projector, a phone. |
| IT / non-IT | Whether an asset is information technology (computers, network gear) or not (furniture, projectors). |
| Product type | A node in the asset type tree, for example "computer > workstation". It decides the asset form and kind. |
| Asset kind | The fixed meaning behind a product type: `asset`, `component` or `consumable` (REQ-AST-003). |
| Product | A make and model of a product type, for example a specific laptop model, with its manufacturer and cost. |
| Component | A part that is fitted to an asset and tracked with it, for example a monitor or a keyboard. |
| Consumable | Stock tracked by quantity, not one by one, for example toner or cables. |
| State category | The fixed meaning behind an admin-defined asset state: `in_stock`, `in_use`, `in_repair`, `retired`, `disposed` (REQ-AST-012). |
| Managed asset | An asset counted against the licensed limit (REQ-AST-002). |
| Loan | A time-limited hand-out of one or more assets to a user or department. |
| Discovery | Collecting inventory (hardware, software, OS) from machines and devices, by agent or agentless scan. |
| Agent | The SupportX inventory program installed on a computer (ADR-015). |
| Probe | A SupportX scanner installed at a site that runs agentless scans and relays agent traffic. |
| Reconciliation | Matching a scan result to an existing asset or CI, or creating a new one, and merging attributes by source. |
| Software type category | The fixed meaning behind a software type: `managed`, `prohibited`, `freeware`, `shareware`, `excluded`, `unidentified` (REQ-SAM-002). |
| Compliance | Whether the licences owned for a piece of software cover its installations: compliant, under-licensed or over-licensed. |
| CI | Configuration item: a component of a service recorded in the CMDB, with relationships to other CIs. |
| Business service | A CI that represents a service the business uses. |
| Relationship type | A named link between CIs with one label per direction, for example "runs on" / "hosts". |
| Impact path | The chain of CIs and services reached from a starting CI by following relationships in a chosen direction and depth. |
| Business view | A saved relationship map for one service or CI. |
| Baseline | A frozen snapshot of selected CIs and their attributes, used to compare against later. |
| Downtime | A period when a CI or service is expected to be (scheduled) or was (actual) unavailable. |
| Purchase request | An internal request to buy something, before a purchase order exists. |
| Purchase order (PO) | An order to a vendor with items, prices, approvals, receipts, invoices and payments. |
| Contract | An agreement with a vendor: maintenance, lease, warranty, support or software. |
| FGA | Fine-grained access: rules that narrow which assets or CIs a technician may see or change. |

## Requirement summary

<!-- summary:start -->
**Counts by decision and priority**

| Decision | MVP | V1 | LATER | Total |
|---|---|---|---|---|
| SAME | 0 | 90 | 15 | 105 |
| BETTER | 0 | 43 | 7 | 50 |
| NEW | 0 | 13 | 13 | 26 |
| SKIP | 0 | 0 | 2 | 2 |
| **Total** | **0** | **146** | **37** | **183** |

Edition (lowest edition that includes it): Essentials 0, Professional 182, Enterprise 1. By prefix: REQ-AST 62, REQ-DSC 30, REQ-SAM 22, REQ-CMDB 32, REQ-PUR 20, REQ-CON 17.

| ID | Title | Decision | Priority | Edition |
|---|---|---|---|---|
| [REQ-AST-001](#req-ast-001--asset-side-records-reuse-engine-behaviour) | Asset-side records reuse engine behaviour | BETTER | V1 | Professional |
| [REQ-AST-002](#req-ast-002--managed-assets-are-a-licensed-limit) | Managed assets are a licensed limit | SAME | V1 | Professional |
| [REQ-AST-003](#req-ast-003--product-type-tree) | Product type tree | SAME | V1 | Professional |
| [REQ-AST-004](#req-ast-004--custom-fields-and-forms-per-product-type) | Custom fields and forms per product type | BETTER | V1 | Professional |
| [REQ-AST-005](#req-ast-005--product-catalogue) | Product catalogue | SAME | V1 | Professional |
| [REQ-AST-006](#req-ast-006--change-an-assets-product) | Change an asset's product | BETTER | V1 | Professional |
| [REQ-AST-007](#req-ast-007--asset-core-fields) | Asset core fields | SAME | V1 | Professional |
| [REQ-AST-008](#req-ast-008--asset-tags-generated-by-pattern) | Asset tags generated by pattern | NEW | V1 | Professional |
| [REQ-AST-009](#req-ast-009--hardware-details-from-discovery) | Hardware details from discovery | SAME | V1 | Professional |
| [REQ-AST-010](#req-ast-010--create-and-copy-assets) | Create and copy assets | BETTER | V1 | Professional |
| [REQ-AST-011](#req-ast-011--asset-age) | Asset age | SAME | V1 | Professional |
| [REQ-AST-012](#req-ast-012--asset-states-with-a-fixed-meaning) | Asset states with a fixed meaning | BETTER | V1 | Professional |
| [REQ-AST-013](#req-ast-013--asset-life-cycle-with-allowed-transitions) | Asset life cycle with allowed transitions | BETTER | V1 | Professional |
| [REQ-AST-014](#req-ast-014--state-changes-with-comments-and-state-history) | State changes with comments and state history | SAME | V1 | Professional |
| [REQ-AST-015](#req-ast-015--assignment-moves-the-state-sensibly) | Assignment moves the state sensibly | BETTER | V1 | Professional |
| [REQ-AST-016](#req-ast-016--asset-workflows-rules-and-triggers) | Asset workflows, rules and triggers | SAME | V1 | Professional |
| [REQ-AST-017](#req-ast-017--retire-and-dispose-with-a-record) | Retire and dispose with a record | BETTER | V1 | Professional |
| [REQ-AST-018](#req-ast-018--owner-user-department-site-parent-asset) | Owner: user, department, site, parent asset | SAME | V1 | Professional |
| [REQ-AST-019](#req-ast-019--assignment-history) | Assignment history | SAME | V1 | Professional |
| [REQ-AST-020](#req-ast-020--allocation-lookup-by-user-or-department) | Allocation lookup by user or department | SAME | V1 | Professional |
| [REQ-AST-021](#req-ast-021--auto-assign-assets-from-logins) | Auto-assign assets from logins | SAME | V1 | Professional |
| [REQ-AST-022](#req-ast-022--user-and-workstation-mapping) | User and workstation mapping | SAME | V1 | Professional |
| [REQ-AST-023](#req-ast-023--users-acknowledge-their-assets) | Users acknowledge their assets | BETTER | V1 | Professional |
| [REQ-AST-024](#req-ast-024--my-assets-for-technicians-and-requesters) | My assets for technicians and requesters | SAME | V1 | Professional |
| [REQ-AST-025](#req-ast-025--the-requesters-assets-on-requests) | The requester's assets on requests | SAME | V1 | Professional |
| [REQ-AST-026](#req-ast-026--components-fitted-to-assets) | Components fitted to assets | SAME | V1 | Professional |
| [REQ-AST-027](#req-ast-027--asset-relationships-view) | Asset relationships view | SAME | V1 | Professional |
| [REQ-AST-028](#req-ast-028--static-and-dynamic-asset-groups) | Static and dynamic asset groups | SAME | V1 | Professional |
| [REQ-AST-029](#req-ast-029--loanable-assets) | Loanable assets | SAME | V1 | Professional |
| [REQ-AST-030](#req-ast-030--loan-an-asset) | Loan an asset | SAME | V1 | Professional |
| [REQ-AST-031](#req-ast-031--return-loaned-assets) | Return loaned assets | BETTER | V1 | Professional |
| [REQ-AST-032](#req-ast-032--book-assets-ahead) | Book assets ahead | NEW | LATER | Professional |
| [REQ-AST-033](#req-ast-033--consumable-stock) | Consumable stock | SAME | V1 | Professional |
| [REQ-AST-034](#req-ast-034--allocate-consumables) | Allocate consumables | SAME | V1 | Professional |
| [REQ-AST-035](#req-ast-035--replenishment-thresholds) | Replenishment thresholds | BETTER | V1 | Professional |
| [REQ-AST-036](#req-ast-036--cost-lines-and-total-cost-of-ownership) | Cost lines and total cost of ownership | SAME | V1 | Professional |
| [REQ-AST-037](#req-ast-037--depreciation) | Depreciation | SAME | V1 | Professional |
| [REQ-AST-038](#req-ast-038--cost-centre-and-gl-code-on-assets) | Cost centre and GL code on assets | SAME | V1 | Professional |
| [REQ-AST-039](#req-ast-039--generate-barcodes-and-qr-codes) | Generate barcodes and QR codes | SAME | V1 | Professional |
| [REQ-AST-040](#req-ast-040--label-designer) | Label designer | NEW | LATER | Professional |
| [REQ-AST-041](#req-ast-041--scan-barcodes-and-rfid-tags-in-the-mobile-app) | Scan barcodes and RFID tags in the mobile app | SAME | LATER | Professional |
| [REQ-AST-042](#req-ast-042--plan-an-asset-audit) | Plan an asset audit | SAME | V1 | Professional |
| [REQ-AST-043](#req-ast-043--run-an-audit-and-settle-discrepancies) | Run an audit and settle discrepancies | BETTER | V1 | Professional |
| [REQ-AST-044](#req-ast-044--associations-with-counters-on-the-asset) | Associations with counters on the asset | BETTER | V1 | Professional |
| [REQ-AST-045](#req-ast-045--raise-a-work-item-from-an-asset) | Raise a work item from an asset | BETTER | V1 | Professional |
| [REQ-AST-046](#req-ast-046--linked-items-in-pickers) | Linked items in pickers | SAME | V1 | Professional |
| [REQ-AST-047](#req-ast-047--asset-list-and-product-type-tree) | Asset list and product type tree | BETTER | V1 | Professional |
| [REQ-AST-048](#req-ast-048--asset-record-page) | Asset record page | BETTER | V1 | Professional |
| [REQ-AST-049](#req-ast-049--history-with-filters) | History with filters | BETTER | V1 | Professional |
| [REQ-AST-050](#req-ast-050--notes-and-attachments-on-assets) | Notes and attachments on assets | BETTER | V1 | Professional |
| [REQ-AST-051](#req-ast-051--bulk-actions-on-assets) | Bulk actions on assets | SAME | V1 | Professional |
| [REQ-AST-052](#req-ast-052--merge-duplicate-assets) | Merge duplicate assets | BETTER | V1 | Professional |
| [REQ-AST-053](#req-ast-053--import-and-export-assets) | Import and export assets | BETTER | V1 | Professional |
| [REQ-AST-054](#req-ast-054--scan-history-per-asset) | Scan history per asset | BETTER | V1 | Professional |
| [REQ-AST-055](#req-ast-055--notify-on-hardware-and-software-changes) | Notify on hardware and software changes | NEW | LATER | Professional |
| [REQ-AST-056](#req-ast-056--action-on-assets-not-scanned-for-too-long) | Action on assets not scanned for too long | BETTER | V1 | Professional |
| [REQ-AST-057](#req-ast-057--remote-control-from-an-asset-or-a-ticket) | Remote control from an asset or a ticket | SAME | LATER | Professional |
| [REQ-AST-058](#req-ast-058--asset-permissions-by-action) | Asset permissions by action | SAME | V1 | Professional |
| [REQ-AST-059](#req-ast-059--asset-notifications) | Asset notifications | SAME | V1 | Professional |
| [REQ-AST-060](#req-ast-060--asset-data-for-reports-and-dashboards) | Asset data for reports and dashboards | SAME | V1 | Professional |
| [REQ-AST-061](#req-ast-061--assets-in-the-mobile-app) | Assets in the mobile app | SAME | V1 | Professional |
| [REQ-AST-062](#req-ast-062--warranty-tracking) | Warranty tracking | SAME | V1 | Professional |
| [REQ-DSC-001](#req-dsc-001--discovery-is-inventory-never-monitoring) | Discovery is inventory, never monitoring | NEW | V1 | Professional |
| [REQ-DSC-002](#req-dsc-002--discovery-agent-for-windows-macos-and-linux) | Discovery agent for Windows, macOS and Linux | BETTER | V1 | Professional |
| [REQ-DSC-003](#req-dsc-003--agent-enrolment-and-identity) | Agent enrolment and identity | SAME | V1 | Professional |
| [REQ-DSC-004](#req-dsc-004--scheduled-and-on-demand-scans) | Scheduled and on-demand scans | SAME | V1 | Professional |
| [REQ-DSC-005](#req-dsc-005--site-probes) | Site probes | BETTER | V1 | Professional |
| [REQ-DSC-006](#req-dsc-006--credential-vault) | Credential vault | BETTER | V1 | Professional |
| [REQ-DSC-007](#req-dsc-007--network-scan) | Network scan | SAME | V1 | Professional |
| [REQ-DSC-008](#req-dsc-008--directory-domain-scan) | Directory (domain) scan | SAME | V1 | Professional |
| [REQ-DSC-009](#req-dsc-009--agentless-windows-linux-unix-and-macos-scans) | Agentless Windows, Linux, Unix and macOS scans | SAME | V1 | Professional |
| [REQ-DSC-010](#req-dsc-010--snmp-inventory-of-network-devices-and-printers) | SNMP inventory of network devices and printers | SAME | V1 | Professional |
| [REQ-DSC-011](#req-dsc-011--unknown-snmp-device-identifiers) | Unknown SNMP device identifiers | SAME | V1 | Professional |
| [REQ-DSC-012](#req-dsc-012--virtual-hosts-and-machines) | Virtual hosts and machines | SAME | V1 | Professional |
| [REQ-DSC-013](#req-dsc-013--import-from-sccm-intune-and-other-endpoint-tools) | Import from SCCM, Intune and other endpoint tools | SAME | V1 | Professional |
| [REQ-DSC-014](#req-dsc-014--cloud-accounts) | Cloud accounts | NEW | LATER | Professional |
| [REQ-DSC-015](#req-dsc-015--self-scan-scripts) | Self-scan scripts | SAME | V1 | Professional |
| [REQ-DSC-016](#req-dsc-016--exclude-devices) | Exclude devices | SAME | V1 | Professional |
| [REQ-DSC-017](#req-dsc-017--network-devices-from-monetx-read-only) | Network devices from MonetX, read-only | NEW | V1 | Professional |
| [REQ-DSC-018](#req-dsc-018--identification-rules) | Identification rules | SAME | V1 | Professional |
| [REQ-DSC-019](#req-dsc-019--reconciliation-by-source-and-attribute) | Reconciliation by source and attribute | BETTER | V1 | Professional |
| [REQ-DSC-020](#req-dsc-020--ambiguous-matches-go-to-a-review-queue) | Ambiguous matches go to a review queue | NEW | V1 | Professional |
| [REQ-DSC-021](#req-dsc-021--name-normalisation) | Name normalisation | SAME | V1 | Professional |
| [REQ-DSC-022](#req-dsc-022--scan-failure-list-with-reasons) | Scan failure list with reasons | BETTER | V1 | Professional |
| [REQ-DSC-023](#req-dsc-023--scan-history-and-audit) | Scan history and audit | SAME | V1 | Professional |
| [REQ-DSC-024](#req-dsc-024--patches-and-services-from-inventory) | Patches and services from inventory | SAME | LATER | Professional |
| [REQ-DSC-025](#req-dsc-025--discovery-overview) | Discovery overview | NEW | V1 | Professional |
| [REQ-DSC-026](#req-dsc-026--asset-limit-at-reconciliation) | Asset limit at reconciliation | BETTER | V1 | Professional |
| [REQ-DSC-027](#req-dsc-027--discovery-works-on-prem-and-air-gapped) | Discovery works on-prem and air-gapped | NEW | V1 | Professional |
| [REQ-DSC-028](#req-dsc-028--probe-and-agent-counts) | Probe and agent counts | BETTER | V1 | Professional |
| [REQ-DSC-029](#req-dsc-029--scan-credentials-for-one-asset) | Scan credentials for one asset | SAME | V1 | Professional |
| [REQ-DSC-030](#req-dsc-030--no-monitors-turned-into-assets) | No monitors turned into assets | SKIP | LATER | Professional |
| [REQ-SAM-001](#req-sam-001--software-catalogue) | Software catalogue | SAME | V1 | Professional |
| [REQ-SAM-002](#req-sam-002--software-types-with-a-fixed-meaning) | Software types with a fixed meaning | BETTER | V1 | Professional |
| [REQ-SAM-003](#req-sam-003--software-categories-and-manufacturers) | Software categories and manufacturers | SAME | V1 | Professional |
| [REQ-SAM-004](#req-sam-004--software-suites) | Software suites | SAME | V1 | Professional |
| [REQ-SAM-005](#req-sam-005--installations) | Installations | SAME | V1 | Professional |
| [REQ-SAM-006](#req-sam-006--software-users-and-history) | Software users and history | SAME | V1 | Professional |
| [REQ-SAM-007](#req-sam-007--service-packs-and-versions) | Service packs and versions | SAME | LATER | Professional |
| [REQ-SAM-008](#req-sam-008--email-the-users-of-a-title) | Email the users of a title | SAME | LATER | Professional |
| [REQ-SAM-009](#req-sam-009--licence-types) | Licence types | SAME | V1 | Professional |
| [REQ-SAM-010](#req-sam-010--licence-records) | Licence records | SAME | V1 | Professional |
| [REQ-SAM-011](#req-sam-011--licence-keys-are-protected) | Licence keys are protected | NEW | V1 | Professional |
| [REQ-SAM-012](#req-sam-012--licence-agreements) | Licence agreements | SAME | V1 | Professional |
| [REQ-SAM-013](#req-sam-013--allocate-licences) | Allocate licences | SAME | V1 | Professional |
| [REQ-SAM-014](#req-sam-014--upgrade-and-downgrade-rights) | Upgrade and downgrade rights | SAME | V1 | Professional |
| [REQ-SAM-015](#req-sam-015--licence-compliance) | Licence compliance | BETTER | V1 | Professional |
| [REQ-SAM-016](#req-sam-016--software-metering) | Software metering | NEW | LATER | Professional |
| [REQ-SAM-017](#req-sam-017--reclaim-unused-licences) | Reclaim unused licences | NEW | LATER | Professional |
| [REQ-SAM-018](#req-sam-018--prohibited-software-alerts) | Prohibited software alerts | BETTER | V1 | Professional |
| [REQ-SAM-019](#req-sam-019--licence-expiry-and-renewal) | Licence expiry and renewal | SAME | V1 | Professional |
| [REQ-SAM-020](#req-sam-020--microsoft-365-and-saas-subscriptions) | Microsoft 365 and SaaS subscriptions | NEW | LATER | Professional |
| [REQ-SAM-021](#req-sam-021--software-page-layout) | Software page layout | BETTER | V1 | Professional |
| [REQ-SAM-022](#req-sam-022--software-and-licence-data-for-reports) | Software and licence data for reports | SAME | V1 | Professional |
| [REQ-CMDB-001](#req-cmdb-001--ci-types-with-attributes-and-inheritance) | CI types with attributes and inheritance | SAME | V1 | Professional |
| [REQ-CMDB-002](#req-cmdb-002--ci-records) | CI records | SAME | V1 | Professional |
| [REQ-CMDB-003](#req-cmdb-003--ci-states-active-and-end-of-life) | CI states: active and end of life | SAME | V1 | Professional |
| [REQ-CMDB-004](#req-cmdb-004--create-copy-and-change-cis) | Create, copy and change CIs | SAME | V1 | Professional |
| [REQ-CMDB-005](#req-cmdb-005--ci-lists-and-views) | CI lists and views | SAME | V1 | Professional |
| [REQ-CMDB-006](#req-cmdb-006--relationship-types-with-one-name-per-direction) | Relationship types with one name per direction | BETTER | V1 | Professional |
| [REQ-CMDB-007](#req-cmdb-007--add-and-remove-relationships) | Add and remove relationships | SAME | V1 | Professional |
| [REQ-CMDB-008](#req-cmdb-008--relationship-map) | Relationship map | BETTER | V1 | Professional |
| [REQ-CMDB-009](#req-cmdb-009--business-views) | Business views | SAME | V1 | Professional |
| [REQ-CMDB-010](#req-cmdb-010--impact-path-analysis-by-depth-and-direction) | Impact path analysis by depth and direction | BETTER | V1 | Professional |
| [REQ-CMDB-011](#req-cmdb-011--one-impact-service-for-every-module) | One impact service for every module | NEW | V1 | Professional |
| [REQ-CMDB-012](#req-cmdb-012--live-health-from-monetx-on-cis-and-maps) | Live health from MonetX on CIs and maps | NEW | V1 | Professional |
| [REQ-CMDB-013](#req-cmdb-013--topology-import-from-monetx) | Topology import from MonetX | NEW | V1 | Professional |
| [REQ-CMDB-014](#req-cmdb-014--topology-that-disappears-is-marked-not-deleted) | Topology that disappears is marked, not deleted | NEW | V1 | Professional |
| [REQ-CMDB-015](#req-cmdb-015--sync-rules-from-assets-and-discovery) | Sync rules from assets and discovery | SAME | V1 | Professional |
| [REQ-CMDB-016](#req-cmdb-016--source-of-every-ci-attribute) | Source of every CI attribute | SAME | V1 | Professional |
| [REQ-CMDB-017](#req-cmdb-017--merge-duplicate-cis) | Merge duplicate CIs | BETTER | V1 | Professional |
| [REQ-CMDB-018](#req-cmdb-018--import-cis-and-relationships) | Import CIs and relationships | SAME | V1 | Professional |
| [REQ-CMDB-019](#req-cmdb-019--associations-on-a-ci-with-counters) | Associations on a CI with counters | BETTER | V1 | Professional |
| [REQ-CMDB-020](#req-cmdb-020--ci-downtime-records) | CI downtime records | BETTER | V1 | Professional |
| [REQ-CMDB-021](#req-cmdb-021--downtime-that-spreads-to-services) | Downtime that spreads to services | NEW | LATER | Professional |
| [REQ-CMDB-022](#req-cmdb-022--contracts-on-cis) | Contracts on CIs | SAME | V1 | Professional |
| [REQ-CMDB-023](#req-cmdb-023--rules-triggers-and-notifications-on-cis) | Rules, triggers and notifications on CIs | SAME | V1 | Professional |
| [REQ-CMDB-024](#req-cmdb-024--ci-version-history) | CI version history | NEW | V1 | Professional |
| [REQ-CMDB-025](#req-cmdb-025--baselines) | Baselines | SAME | V1 | Professional |
| [REQ-CMDB-026](#req-cmdb-026--compare-against-a-baseline) | Compare against a baseline | SAME | V1 | Professional |
| [REQ-CMDB-027](#req-cmdb-027--data-quality-policies-and-scores) | Data quality policies and scores | SAME | LATER | Professional |
| [REQ-CMDB-028](#req-cmdb-028--cmdb-steward-agent) | CMDB steward agent | NEW | LATER | Professional |
| [REQ-CMDB-029](#req-cmdb-029--fine-grained-access-for-assets-and-cis) | Fine-grained access for assets and CIs | BETTER | V1 | Professional |
| [REQ-CMDB-030](#req-cmdb-030--restricted-items-on-maps-and-impact-paths) | Restricted items on maps and impact paths | NEW | V1 | Professional |
| [REQ-CMDB-031](#req-cmdb-031--cmdb-permissions) | CMDB permissions | SAME | V1 | Professional |
| [REQ-CMDB-032](#req-cmdb-032--cmdb-data-for-reports-and-dashboards) | CMDB data for reports and dashboards | SAME | V1 | Professional |
| [REQ-PUR-001](#req-pur-001--vendors-as-first-class-records) | Vendors as first-class records | BETTER | V1 | Professional |
| [REQ-PUR-002](#req-pur-002--purchase-requests) | Purchase requests | NEW | LATER | Professional |
| [REQ-PUR-003](#req-pur-003--vendor-price-lists-and-quote-comparison) | Vendor price lists and quote comparison | NEW | LATER | Professional |
| [REQ-PUR-004](#req-pur-004--purchasable-services) | Purchasable services | SAME | LATER | Professional |
| [REQ-PUR-005](#req-pur-005--purchase-order-record) | Purchase order record | BETTER | LATER | Professional |
| [REQ-PUR-006](#req-pur-006--items-and-totals) | Items and totals | SAME | LATER | Professional |
| [REQ-PUR-007](#req-pur-007--po-statuses-and-life-cycle) | PO statuses and life cycle | BETTER | LATER | Professional |
| [REQ-PUR-008](#req-pur-008--po-approvals-with-limits-and-segregation) | PO approvals with limits and segregation | BETTER | LATER | Professional |
| [REQ-PUR-009](#req-pur-009--order-and-send-to-the-vendor) | Order and send to the vendor | SAME | LATER | Professional |
| [REQ-PUR-010](#req-pur-010--receive-items-into-assets-consumables-and-licences) | Receive items into assets, consumables and licences | BETTER | LATER | Professional |
| [REQ-PUR-011](#req-pur-011--invoices) | Invoices | SAME | LATER | Professional |
| [REQ-PUR-012](#req-pur-012--matching-order-receipt-and-invoice) | Matching order, receipt and invoice | NEW | LATER | Professional |
| [REQ-PUR-013](#req-pur-013--payments) | Payments | SAME | LATER | Professional |
| [REQ-PUR-014](#req-pur-014--other-po-actions) | Other PO actions | SAME | LATER | Professional |
| [REQ-PUR-015](#req-pur-015--purchase-defaults-templates-and-closure-rules) | Purchase defaults, templates and closure rules | SAME | LATER | Professional |
| [REQ-PUR-016](#req-pur-016--po-notifications) | PO notifications | SAME | LATER | Professional |
| [REQ-PUR-017](#req-pur-017--cost-centres-and-gl-codes) | Cost centres and GL codes | SAME | V1 | Professional |
| [REQ-PUR-018](#req-pur-018--budgets-per-cost-centre) | Budgets per cost centre | NEW | LATER | Professional |
| [REQ-PUR-019](#req-pur-019--currencies) | Currencies | BETTER | LATER | Professional |
| [REQ-PUR-020](#req-pur-020--purchase-permissions-and-data) | Purchase permissions and data | SAME | LATER | Professional |
| [REQ-CON-001](#req-con-001--contract-record) | Contract record | SAME | V1 | Professional |
| [REQ-CON-002](#req-con-002--contract-types) | Contract types | SAME | V1 | Professional |
| [REQ-CON-003](#req-con-003--contract-statuses-and-views) | Contract statuses and views | SAME | V1 | Professional |
| [REQ-CON-004](#req-con-004--cover-many-assets-and-licences) | Cover many assets and licences | BETTER | V1 | Professional |
| [REQ-CON-005](#req-con-005--parent-and-child-contracts) | Parent and child contracts | SAME | V1 | Professional |
| [REQ-CON-006](#req-con-006--expiry-notifications-and-renewal-requests) | Expiry notifications and renewal requests | BETTER | V1 | Professional |
| [REQ-CON-007](#req-con-007--renew-a-contract) | Renew a contract | SAME | V1 | Professional |
| [REQ-CON-008](#req-con-008--auto-renewal) | Auto-renewal | SAME | V1 | Professional |
| [REQ-CON-009](#req-con-009--contract-usage) | Contract usage | BETTER | LATER | Professional |
| [REQ-CON-010](#req-con-010--contracts-used-on-work-items) | Contracts used on work items | SAME | V1 | Professional |
| [REQ-CON-011](#req-con-011--conversations-notes-and-history-on-contracts) | Conversations, notes and history on contracts | SAME | V1 | Professional |
| [REQ-CON-012](#req-con-012--cancel-and-delete-contracts) | Cancel and delete contracts | SAME | V1 | Professional |
| [REQ-CON-013](#req-con-013--contract-templates) | Contract templates | SAME | V1 | Professional |
| [REQ-CON-014](#req-con-014--contract-documents-with-versions) | Contract documents with versions | BETTER | LATER | Professional |
| [REQ-CON-015](#req-con-015--contract-permissions-notifications-and-data) | Contract permissions, notifications and data | SAME | V1 | Professional |
| [REQ-CON-016](#req-con-016--customer-contracts-for-managed-service-providers) | Customer contracts for managed service providers | SKIP | LATER | Enterprise |
| [REQ-CON-017](#req-con-017--custom-fields-on-procurement-and-licence-records) | Custom fields on procurement and licence records | SAME | V1 | Professional |
<!-- summary:end -->

---

## 1. Foundations for asset-side records

#### REQ-AST-001 — Asset-side records reuse engine behaviour

Assets, CIs, software, licences, contracts, vendors and purchase orders are not work items, but
they behave like them where it matters:

- field history with actor, time, source and reason, on both sides of every link (REQ-WI-003,
  REQ-WI-004);
- live updates on every screen (REQ-WI-005) and safe concurrent editing (REQ-WI-007);
- actions decided by the server in a fixed order, and fixed tabs (REQ-WI-010, REQ-WI-011);
- trash and restore (REQ-WI-020), audit of privileged actions (REQ-WI-021);
- lists, custom views, export and bulk actions with per-record results (REQ-INC-104 to
  REQ-INC-121).

Each module builds these on the shared platform components, not by importing the work item
module.

- **Decision:** BETTER. In ServiceDesk Plus the asset history tab went stale while the state
  history was right, and asset tabs and setup tabs move around. One behaviour everywhere.
- **Source:** architecture §6.1, §6.2, §7.4; sdp-area-07 §Weak spots (stale history); sdp-area-07 (7b) §7b.1 (tab strip shifts), §7b.2 (tabs reorder)
- **SDP weak spot fixed:** the asset History tab was stale; tab strips shift and reorder
  themselves around the last tab opened.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. One shared contract test suite (history, live update, concurrency, trash, fixed tabs) runs
     against assets, CIs, licences, contracts and purchase orders and passes for each.
  2. Changing an asset's state in one browser shows the new state and a new history line in a
     second browser within 1 second.
  3. Opening a record's third tab and reloading keeps the tabs in the same order.
  4. An import-linter contract proves `assets`, `cmdb`, `discovery` and `procurement` do not
     import each other's internals.

#### REQ-AST-002 — Managed assets are a licensed limit

The number of managed assets is a counted entitlement (architecture §13.1). Assets count
while they exist and are not disposed. Components, consumables, software and CIs that are not
assets do not count. The licence page shows used and allowed. When the limit is reached,
creating or discovering one more asset is refused with a clear reason; discovered assets wait
in a pending queue (REQ-DSC-026) and are never dropped silently.

- **Decision:** SAME. ServiceDesk Plus licenses by asset band (500 IT assets on the trial).
  The count is checked only through the entitlement interface (REQ-WI-017).
- **Source:** architecture §6.9 (asset limit enforced at reconciliation), §13.1, §13.5; sdp-area-14 §Licence and plan
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. With a limit of 10 and 10 assets, creating an 11th by hand is refused with a labelled
     reason naming the limit.
  2. Disposing one asset frees one slot, and the licence page shows the new count live.
  3. Adding a consumable or a component never changes the managed asset count.
  4. No code outside the licensing module reads the licence file; the count comes from
     `check_limit` and `remaining`.

---

## 2. Product types and products

#### REQ-AST-003 — Product type tree

Admins keep a tree of product types under one root. Each type has a name, an icon, an API
name, a parent, a category (IT or non-IT), an asset kind (asset, component or consumable) and
a description. A child type inherits its parent's fields and kind. A new tenant gets a seed
tree (Appendix A).

- **Decision:** SAME.
- **Source:** sdp-area-07 §Screens (asset tree), sdp-area-07 (7b) §7b.1 (product type tree, new product type form); architecture §2.11 (asset model)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Creating "Tablet" under "Mobile device" makes it inherit the mobile device fields.
  2. The asset kind of a type is shown as a label, never as a code, and cannot change once
     assets of that type exist.
  3. A type with assets cannot be deleted; the admin is told how many assets use it.
  4. The API name is unique per tenant and never shown to end users.

#### REQ-AST-004 — Custom fields and forms per product type

Each product type has its own form: sections and fields, including fields inherited from
parent types. Fields can be added on the type form at creation time, not only after a first
save. The asset form changes with the chosen product type.

- **Decision:** BETTER. ServiceDesk Plus unlocks the fields tab only after the type is saved.
- **Source:** sdp-area-07 §Screens (new asset form changes with product type), sdp-area-07 (7b) §7b.1 (fields tab disabled until first save); architecture §2.11 (custom forms per product type), §6.6
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A field added to "Computer" appears on the form of a new "Workstation" asset.
  2. Choosing a different product type on a new asset swaps the type-specific sections and
     keeps the common fields that were typed.
  3. A custom field can be filtered on in asset views and exported.

#### REQ-AST-005 — Product catalogue

Admins and asset managers keep products: product type, name, manufacturer, part number,
default cost, GL code, a flag to hide it from purchase orders, depreciation defaults
(REQ-AST-037) and a description. Assets, purchase orders and contracts pick products from it.

- **Decision:** SAME.
- **Source:** sdp-area-07 (7b) §7b.1 (product list and form); architecture §2.11 (product catalogues), §6.1 (procurement owns products); D-067 (products and vendors arrive in Stage 2 with assets)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A product marked "hide from purchase orders" never appears in the PO item picker but can
     still be chosen for an asset.
  2. Changing a product's default cost does not change the purchase cost of existing assets.
  3. Products can be filtered by product type and manufacturer.

#### REQ-AST-006 — Change an asset's product

A user with permission can change an asset's product or product type. A preview shows which
type-specific fields will be lost or mapped. The change is recorded in history.

- **Decision:** BETTER. A preview before fields are dropped.
- **Source:** sdp-area-07 §Screens (Modify Product action), sdp-area-07 (7b) §7b.6 (modify product dialog)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Moving an asset from "Workstation" to "Server" lists the workstation-only fields whose
     values will be removed before the user confirms.
  2. Removed values stay readable in history.
  3. A bulk product change on 50 assets reports success or the reason per asset.

---

## 3. The asset record

#### REQ-AST-007 — Asset core fields

Every asset has a name, product, product type, asset tag, serial number, discovered serial,
barcode or QR value, vendor, purchase cost, acquisition date, warranty expiry date, expiry
date, location, site, region, the purchase order it came from, created and updated by and
time. Asset tag and serial number are unique per tenant when filled.

- **Decision:** SAME.
- **Source:** sdp-area-07 (7b) §7b.3 (details tab: asset details); sdp-area-07 §Screens (right panel: product, state, PO link, age)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Saving a second asset with an existing asset tag is refused and names the asset that
     holds it.
  2. Searching by serial number, discovered serial, asset tag or barcode value finds the asset.
  3. An asset created from a purchase order shows a link to that PO.

#### REQ-AST-008 — Asset tags generated by pattern

Admins can set an asset tag pattern per product type or for all, for example a prefix and a
counter (Appendix A). New assets get the next tag automatically; a user with permission may
overwrite it. The counter never reuses a value.

- **Decision:** NEW. ServiceDesk Plus leaves the tag to the user.
- **Source:** sdp-area-07 (7b) §7b.3 (asset tag as free text); architecture §7.1 (display IDs from per-tenant sequences)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. With pattern `LT-{n}`, two laptops created at the same moment get two different tags.
  2. Deleting an asset does not free its tag for reuse.
  3. Assets created by discovery and by receiving a PO get tags from the same pattern.

#### REQ-AST-009 — Hardware details from discovery

An asset of a computer type shows hardware details collected by discovery: computer system
(model, manufacturer, domain, last logged-in user, BIOS and SMBIOS data), operating system,
memory and memory modules, processors, network adapters (IP, MAC, DHCP, DNS name), hard disks,
logical and physical drives, printers, keyboard, mouse, sound, monitors, video cards, ports and
USB controllers. Discovered values are read-only; manual assets can fill the main ones by hand.

- **Decision:** SAME.
- **Source:** sdp-area-07 (7b) §7b.3 (details and hardware tabs); architecture §2.13 (agent collects hardware, OS, peripherals)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. After a scan, the hardware tab lists each disk with capacity and free space as reported.
  2. A discovered field cannot be edited by hand; the field shows its source and last scan
     time.
  3. A manual asset with no scan shows "not scanned yet" instead of empty tables.

#### REQ-AST-010 — Create and copy assets

Users create assets from the asset list, the "new" menu, a product page or by receiving a PO
(REQ-PUR-010). Copy makes up to a set number of copies of an asset (Appendix A); unique
fields (asset tag, serial, barcode, discovered data) are not copied, and the new assets start
in the default in-stock state.

- **Decision:** BETTER. ServiceDesk Plus copies the serial number into the copy, creating
  duplicates.
- **Source:** sdp-area-07 (7b) §7b.6 (copy asset: same product and serial); sdp-area-01 §Screens (new menu: asset)
- **SDP weak spot fixed:** a copied asset kept the original serial number.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Copying an asset 5 times creates 5 assets with new tags and empty serial numbers.
  2. The copies are in the default in-stock state and their history names the source asset.
  3. A copy request above the limit is refused with the limit shown.

#### REQ-AST-011 — Asset age

Each asset shows its age, calculated from the acquisition date or another date the admin
picks. Admins choose the age format (years, months, days and the words used); the words come
from labels in every language.

- **Decision:** SAME.
- **Source:** sdp-area-07 (7b) §7b.1 (configurations: asset age basis and format); sdp-area-07 §Screens (right panel: age); architecture §2.11 (asset age)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. An asset acquired 1 year, 2 months and 3 days ago shows that age in English and in Arabic.
  2. Switching the basis to warranty start date recalculates every asset's age without a
     refresh.
  3. An asset with no basis date shows "unknown", not zero.

---

## 4. States and life cycle

#### REQ-AST-012 — Asset states with a fixed meaning

Admins define asset states. Each state maps to one fixed category: in stock, in use, in
repair, retired or disposed. Rules, reports, the licence count and loans use the category, not
the state name. A new tenant gets the states in Appendix A.

- **Decision:** BETTER. ServiceDesk Plus states are free names, so behaviour such as "assign
  moves to in use" is tied to built-in names.
- **Source:** sdp-area-07 §Actions (asset states), sdp-area-07 (7b) §7b.1 (asset state list); REQ-INC-044 (status categories)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A new state "with courier" in category in stock is treated as in stock by loans and
     reports.
  2. A state's category cannot change while assets are in it.
  3. Disposed assets do not count as managed assets (REQ-AST-002).

#### REQ-AST-013 — Asset life cycle with allowed transitions

Each product type uses an asset life cycle: the states allowed and the transitions between
them, drawn on the same designer as work item life cycles (REQ-INC-049). Transitions can ask
for a reason, required fields or a permission. A default life cycle ships switched on and
applies to every product type (Appendix A).

- **Decision:** BETTER. The ServiceDesk Plus sample asset life cycle ships switched off and
  applies to nothing, so state changes are unrestricted.
- **Source:** sdp-area-07 §Automation (sample asset life cycle off, applies to nothing), §Fields (new asset life cycle); sdp-area-12 §Screens (life cycles: asset); architecture §2.11 (drag-and-drop asset life cycle)
- **SDP weak spot fixed:** the asset life cycle and workflow show "not assigned" on assets
  out of the box.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Under the default life cycle, moving a disposed asset back to in use is refused on the
     UI, the API, bulk edit and import.
  2. A transition that needs a reason refuses to save without one.
  3. A new tenant's assets show the default life cycle, not "not assigned".

#### REQ-AST-014 — State changes with comments and state history

Changing an asset's state records the old and new state, the site, a comment and who did it.
The asset shows a state history: each state with when it started, when it ended and how long
it lasted.

- **Decision:** SAME.
- **Source:** sdp-area-07 (7b) §7b.6 (modify state dialog: state, site, comments), §7b.3 (history: state history); architecture §2.11 (ownership history)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Moving an asset to in repair and back writes two state history rows with durations.
  2. The state history is right even when a bulk action or a loan changed the state.
  3. State durations are available to reports (file 09).

#### REQ-AST-015 — Assignment moves the state sensibly

Assigning an asset to a user or department moves it from an in-stock state to the default
in-use state. Removing the last owner moves it back to the default in-stock state, unless the
user chooses another state. Each move is recorded as automatic.

- **Decision:** BETTER. ServiceDesk Plus moves in store to in use on assignment, but does not
  move it back on unassignment.
- **Source:** sdp-area-07 §Actions (assigning a user flips in store to in use), §Behaviour (loan return state not re-checked); REQ-INC-050
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Assigning an in-stock laptop to a user sets it in use, with a history entry marked
     automatic.
  2. Unassigning it returns it to in stock unless the user picks in repair.
  3. Assigning an asset in repair asks for confirmation and does not change its state.

#### REQ-AST-016 — Asset workflows, rules and triggers

Business rules, triggers, scheduled rules and visual workflows run on assets, using asset
fields and events (created, state changed, assigned, scanned, warranty expiring). They are
built on the engines in file 03 (REQ-RUL-008, REQ-WF-031). Every automatic change leaves a
trace (REQ-WI-004).

- **Decision:** SAME.
- **Source:** sdp-area-12 §Screens (workflows: asset module); sdp-area-07 §Navigation path (workflows > asset); architecture §2.11 (asset workflows and triggers)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A trigger "when an asset moves to in repair, create an incident for the hardware group"
     creates one incident per state change, linked to the asset.
  2. The asset history names the trigger that changed it.

#### REQ-AST-017 — Retire and dispose with a record

Retiring or disposing an asset records the date, reason, method (for example resale,
recycling, donation, destruction), disposal cost, who approved it and an optional certificate
of data wiping or destruction. A disposed asset is read-only, kept for reports and audit, and
its open links, loans and licence allocations are listed for clean-up first.

- **Decision:** BETTER. ServiceDesk Plus has a disposed state and a disposal cost factor, but
  no disposal record.
- **Source:** sdp-area-07 §Actions (asset states: disposed), sdp-area-07 (7b) §7b.3 (add cost: disposal cost); architecture §2.11 (lifecycle)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Disposing an asset with an active loan is refused until the loan is closed.
  2. Disposing an asset with allocated licences offers to release them in the same step.
  3. A disposed asset cannot be edited except by a user with the "edit disposed assets"
     permission, and every such edit asks for a reason.
  4. The disposal cost appears in the asset's cost table and total cost of ownership.

---

## 5. Ownership, allocation and acknowledgement

#### REQ-AST-018 — Owner: user, department, site, parent asset

An asset can be assigned to a user, a department, or another asset (for example a monitor to
a workstation), and always has a site. When it is attached to a user or parent asset, the
tenant decides whether the asset keeps its own site or follows the owner's site.

- **Decision:** SAME.
- **Source:** sdp-area-07 (7b) §7b.3 (asset state block: user, associated to asset, department, site, retain site); sdp-area-07 §Screens (assign to department/site)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Assigning a monitor to a workstation shows the monitor on the workstation's relationships
     tab and the workstation on the monitor.
  2. With "follow owner's site" on, moving the user to another site moves their assets' site,
     with history on each asset.
  3. An asset cannot be assigned to itself or to one of its own children.

#### REQ-AST-019 — Assignment history

Every asset keeps an assignment history: each user, department or parent asset it was
assigned to, from when to when, and who made the change, including loans.

- **Decision:** SAME.
- **Source:** sdp-area-07 (7b) §7b.3 (history: assignment history); architecture §2.11 (ownership history)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. An asset assigned to A, then B, then loaned to C shows three rows with dates.
  2. A user's page lists every asset they have held, current and past.

#### REQ-AST-020 — Allocation lookup by user or department

Technicians can look up all assets, components, consumables and licences currently allocated
to a user or a department, from the asset area and from the user's page.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Navigation path (asset allocation details by user or department); sdp-area-01 §Screens (assets: asset allocation details)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Looking up a user lists their assets, consumables allocated to them and software licences
     allocated to their machines.
  2. The result only shows items the technician may see (REQ-CMDB-029).

#### REQ-AST-021 — Auto-assign assets from logins

When enabled, an asset scanned with the same last logged-in user for a set number of
consecutive scans is assigned to that user. A fallback field can be used when scans collect no
email. Admins can exclude product types or single assets. Auto-assign is off by default.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Fields (asset auto assign), §Automation; sdp-area-07 (7b) §7b.1 (related setup: asset auto assign); architecture §2.11 (asset auto-assignment, user and workstation mapping)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. With the count at 2, the first matching scan does not assign; the second does, with a
     history entry naming auto-assign.
  2. An excluded asset is never auto-assigned.
  3. An asset assigned by hand is not reassigned by auto-assign unless the admin allows it.

#### REQ-AST-022 — User and workstation mapping

From discovery data, SupportX keeps which users log in to which computers and when they last
did. Technicians see a user's usual machines on the user page and in incident forms.

- **Decision:** SAME.
- **Source:** architecture §2.11 (user and workstation mapping), §2.13 (logged-on users); sdp-area-07 (7b) §7b.3 (last logged-in user)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A user who logged in to two computers in the last 30 days shows both, with last login
     times.
  2. Logging an incident for that user offers both computers first in the asset picker.

#### REQ-AST-023 — Users acknowledge their assets

Admins can require acknowledgement for chosen product types. When such an asset is assigned,
the user is asked to confirm receipt in the portal, by email or in the mobile app. The
acknowledgement list shows status (pending, accepted, disputed) by product and site; a
technician can send reminders and download the list. An optional AI step reads the user's
email reply to set the status (file 10).

- **Decision:** BETTER. Acknowledgement works from the portal and the mobile app, not only by
  email, and a user can dispute.
- **Source:** sdp-area-07 §Screens (acknowledgements), sdp-area-07 (7b) §7b.1 (asset acknowledgement setting); sdp-area-10 §Fields (asset acknowledgement AI feature); architecture §2.10 (email intent for asset acknowledgement), §2.11 (asset acknowledgement by user); REQ-AI-056 (shared email reply reading)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Assigning a laptop of an acknowledged type creates a pending acknowledgement that the user
     sees in the portal.
  2. The user's "accept" sets the status to accepted, live, with time and channel recorded.
  3. A "dispute" with a comment notifies the assigning technician.
  4. Acknowledgement works with mail not configured, through the portal.

#### REQ-AST-024 — My assets for technicians and requesters

Each user has a "my assets" view: the assets, components and consumables assigned to them,
with state and warranty. In the portal, requesters see their assets and can report a problem
with one, which opens the incident form with the asset filled in.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Navigation path (my assets); sdp-area-13 §Requester Portal (requester view tab: assets); architecture §2.15 (portal: my assets)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A requester sees only assets assigned to them or to their department if the tenant
     allows department assets.
  2. "Report a problem" from a portal asset opens the incident form with that asset attached.
  3. A newly assigned asset appears in the requester's list without a refresh.

#### REQ-AST-025 — The requester's assets on requests

Tenants decide whether request forms offer only the requester's own assets, and whether
incidents created by email include the requester's assets automatically.

- **Decision:** SAME.
- **Source:** sdp-area-13 §Requester Portal (show only associated assets during request creation; include requester's assets for email requests); REQ-INC-015
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. With "own assets only" on, the portal asset picker lists only the requester's assets.
  2. With "include assets for email" on, an emailed incident from a user with one laptop has
     that laptop attached.

---

## 6. Components, groups and relationships

#### REQ-AST-026 — Components fitted to assets

Component product types (for example keyboard, monitor, memory module) can be tracked as
their own records and attached to a parent asset. Moving or disposing the parent asks what to
do with its components.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Screens (asset tree: components), sdp-area-07 (7b) §7b.1 (type: component); architecture §2.11 (components)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Attaching a monitor component to a workstation shows it under the workstation's
     components.
  2. Disposing the workstation asks whether to detach or dispose its components.

#### REQ-AST-027 — Asset relationships view

The asset page shows a relationship view: the asset in the centre, its assigned user, parent
and child assets, components, connected assets, business services and CIs. Users with
permission add relationships from there, using the CMDB relationship types (REQ-CMDB-006).

- **Decision:** SAME.
- **Source:** sdp-area-07 §Screens (relationships tab diagram), sdp-area-07 (7b) §7b.3
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Adding a "connected to" relationship from a workstation to a switch shows on both asset
     pages and in both histories.
  2. The view is keyboard-navigable and readable in right-to-left.

#### REQ-AST-028 — Static and dynamic asset groups

Users create asset groups. A static group holds assets picked by hand. A dynamic group holds
the assets that match criteria (field, condition, value) and updates itself. Groups can be
used in views, bulk actions, rules and reports.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Screens (groups), §Fields (new group: static or dynamic); sdp-area-01 §Screens (manage groups, new group)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A dynamic group "laptops with warranty ending this quarter" gains an asset when its
     warranty date is changed to match, without a refresh.
  2. A static group can be filled from the list selection in one step.
  3. A group shows a member count that matches its list.

---

## 7. Loans and bookings

#### REQ-AST-029 — Loanable assets

Assets can be marked loanable, one by one, in bulk or by scanning barcodes. The loanable list
filters by product type, product and site.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Screens (asset loan: loanable assets), §Actions (mark as loanable)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Scanning three barcodes in the mobile app marks those three assets loanable.
  2. Only loanable assets in an in-stock state can be added to a new loan.

#### REQ-AST-030 — Loan an asset

A loan has a display ID, one or more assets, a user or a department, a start (today by
default), an expiry, a site, who handed it over and comments. Starting a loan moves the assets
to an in-use state and shows "loaned to" on each asset. The loan register lists loans with
status (on loan, overdue, closed) and filters by status and site.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Screens (loan registry), §Fields (new loan), §Automation (loans), §Behaviour (loan)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Loaning two assets to a user sets both in use and adds the loan to both assignment
     histories.
  2. A loan whose expiry passes shows as overdue, live, and the borrower and the loan creator
     are notified.
  3. An asset already on loan cannot be added to a second loan for an overlapping period.

#### REQ-AST-031 — Return loaned assets

Returning records the assets, return date, who received them and comments, with an option to
move them to in repair. When all assets of a loan are back, the loan closes. Returned assets
go back to their in-stock state unless sent to repair.

- **Decision:** BETTER. The asset's state after return is defined and tested.
- **Source:** sdp-area-07 §Fields (return assets: move to in repair), §Behaviour (loan closed; state after return not checked), sdp-area-07 (7b) §7b.4 (in store after return)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Returning one of two loaned assets leaves the loan open with one asset outstanding.
  2. Returning the last asset closes the loan and sets the asset back in stock.
  3. Returning with "move to repair" sets the asset in repair and records the comment.

#### REQ-AST-032 — Book assets ahead

Users can book loanable assets for a future period, for example projectors for a training
day. The booking calendar shows availability by product and site and prevents double booking.
A booking turns into a loan when the asset is handed over.

- **Decision:** NEW. ServiceDesk Plus has loans but no advance booking.
- **Source:** architecture §2.11 (asset loan and booking)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Booking a projector for a day that another booking holds is refused and the next free day
     is suggested.
  2. Handing over a booked asset converts the booking into a loan with the same dates.
  3. A requester can book from the portal if the tenant allows it.

---

## 8. Consumables and replenishment

#### REQ-AST-033 — Consumable stock

Consumables are tracked by quantity per product and site: product, quantity, vendor,
location, purchase cost, barcode, site and comments. A consumable can be tracked with batches
(reference, batch or lot number, manufacture and expiry dates); this choice is made when the
consumable is created. Users add quantity as stock arrives.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Screens (consumables), §Fields (new consumable), sdp-area-07 (7b) §7b.1 (consumable product types); sdp-area-01 §Screens (new: add quantity, consumable); architecture §2.11 (consumables)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Adding 20 toner cartridges at site A raises site A's stock by 20 and leaves site B
     unchanged.
  2. A batch-tracked consumable shows each batch with its expiry date; an expired batch is
     flagged.
  3. Trying to switch batch tracking on an existing consumable is refused with the reason.

#### REQ-AST-034 — Allocate consumables

Technicians allocate consumables to a user, a department or an asset, with quantity and date,
optionally linked to a request. Stock falls by the allocated amount and can never go below
zero.

- **Decision:** SAME.
- **Source:** sdp-area-01 §Screens (new: allocate); sdp-area-09 §Screens (consumables reports: allocations); architecture §2.11 (consumable allocation)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Allocating 3 cables when 2 are in stock is refused with the available amount shown.
  2. Allocating from a service request links the allocation to the request on both sides.
  3. Two technicians allocating the last unit at the same moment: one succeeds, one is told
     stock ran out.

#### REQ-AST-035 — Replenishment thresholds

Admins set minimum stock per product type or product and site, with who is notified. When
stock falls below the threshold, they are notified once, and optionally a draft purchase
request is created (REQ-PUR-002).

- **Decision:** BETTER. Threshold alerts can also start a purchase.
- **Source:** sdp-area-07 §Screens (replenishment), §Automation (replenishment threshold alerts); architecture §2.11 (replenishment thresholds per site)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Stock falling from 6 to 4 with a threshold of 5 sends one notification; falling to 3
     sends no second one until stock has risen above 5 again.
  2. With "create purchase request" on and procurement licensed, a draft purchase request
     for the configured quantity is created and linked.

---

## 9. Financials

#### REQ-AST-036 — Cost lines and total cost of ownership

Each asset has a cost table: purchase cost, operational costs (for example move, service,
contract and other costs) and disposal cost, each with date, amount and description. Summary
cards show purchase cost, current book value, operational cost and total cost of ownership.
Amounts use the tenant's currencies (file 11).

- **Decision:** SAME.
- **Source:** sdp-area-07 (7b) §7b.3 (financials: costs, add cost dialog); architecture §2.11 (financials)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Adding a service cost of 200 to an asset bought for 1,200 shows operational cost 200 and
     total cost of ownership 1,400.
  2. Contract costs from linked contracts can be included as operational cost lines.
  3. Cost totals use exact decimal arithmetic; no rounding drift over 1,000 lines.

#### REQ-AST-037 — Depreciation

Depreciation is set per product (default for its assets) or per asset: purchase cost,
acquisition date, method, useful life and salvage value. Methods are straight line, declining
balance, double declining balance and sum of the years' digits. The asset shows its current
book value and a depreciation schedule by year.

- **Decision:** SAME.
- **Source:** sdp-area-07 (7b) §7b.3 (depreciation tab and dialog), §7b.1 (product: configure depreciation); sdp-area-07 §Screens (actions: configure depreciation); architecture §2.11 (depreciation methods)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A 1,200 asset with 3-year straight line and no salvage shows a book value of 800 after
     one year.
  2. Setting depreciation on the product applies to its assets that have no own settings.
  3. Each method has a unit test against a worked example.

#### REQ-AST-038 — Cost centre and GL code on assets

Assets carry a cost centre and a GL code, defaulted from the product or the purchase order.
Reports can total asset value and depreciation by cost centre.

- **Decision:** SAME.
- **Source:** architecture §2.11 (cost centres, GL codes); sdp-area-07 (7b) §7b.1 (product: GL code); sdp-area-07 §Fields (PO cost center, GL code)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. An asset received from a PO with cost centre CC-10 gets CC-10.
  2. A report of book value by cost centre matches the sum of the assets' book values.

---

## 10. Barcodes, QR codes and RFID

#### REQ-AST-039 — Generate barcodes and QR codes

Users generate barcode (Code 128) or QR labels for new assets, existing assets and vendor
codes, singly or in bulk, and reprint them. A label history shows what was printed, when and
by whom. A QR code opens the asset page for a signed-in technician.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Screens (barcode/QR code: generate code and history), §Actions (reprint barcode); architecture §2.11 (barcode and QR generation)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Generating labels for 100 selected assets produces one printable PDF.
  2. A QR label scanned by a signed-in technician opens that asset; scanned by anyone else it
     reveals nothing about the asset.
  3. Reprinting writes a label history row.

#### REQ-AST-040 — Label designer

Admins design label layouts: size, which fields appear (tag, name, site, logo) and code type,
with a preview. Several layouts can exist, for example small cable labels and laptop labels.

- **Decision:** NEW. ServiceDesk Plus offers fixed label cards.
- **Source:** architecture §2.11 (label designer)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A layout with tag and site in Arabic prints right to left.
  2. The preview matches the printed PDF.

#### REQ-AST-041 — Scan barcodes and RFID tags in the mobile app

The mobile app scans barcodes and QR codes to open an asset, check it in or out of a loan,
receive PO items or record an audit. RFID bulk scanning reads many tags at once during audits.

- **Decision:** SAME.
- **Source:** architecture §2.11 (RFID bulk scanning in the mobile app), §2.15 (mobile: barcode and RFID scanning); sdp-area-07 §Fields (receive with barcode / QR code)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Scanning an unknown barcode offers to create an asset with that barcode.
  2. An RFID sweep of a room records every tag read against the running audit.
  3. Scans made offline are sent when the device reconnects, without duplicates.

---

## 11. Asset audits

#### REQ-AST-042 — Plan an asset audit

Asset managers create audits: name, type (done by technicians, or self-audit by users),
description, scope (sites, product types, groups), planned start and end, and auditors.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Screens (asset audit), §Fields (new asset audit); sdp-area-11 §Fields (roles: asset audit admin, asset auditor); architecture §2.11 (asset audits)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. An audit scoped to site A lists exactly the assets at site A as expected items.
  2. A user self-audit asks each user in scope to confirm the assets assigned to them.

#### REQ-AST-043 — Run an audit and settle discrepancies

Auditors mark each expected asset as found, missing, in the wrong place or damaged, by
scanning or by hand, and record unexpected assets they find. At the end the audit shows a
discrepancy list; the asset manager can apply fixes (move site, change state, assign) in bulk.
A closed audit is read-only.

- **Decision:** BETTER. Settling discrepancies is part of the audit, with each fix recorded.
- **Source:** sdp-area-07 §Screens (asset audit); sdp-area-11 §Fields (asset audit scan privileges); sdp-area-09 §Screens (report modules: asset audit)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. An asset scanned at site B during a site A audit is listed as "wrong place".
  2. Applying "move to site B" updates the asset and its history names the audit.
  3. Progress (found / expected) updates live for every auditor.

---

## 12. Links to work items

#### REQ-AST-044 — Associations with counters on the asset

An asset shows every linked incident, service request, problem, change, release, project,
contract and purchase order, grouped by kind, each with open and total counters. The links are
made on the work item side (REQ-INC-015, REQ-PRB-006, REQ-CHG-080, REQ-REL-035) or from the
asset, recorded on both records, and counted live.

- **Decision:** BETTER. Every kind has a counter on the asset.
- **Source:** sdp-area-07 §Screens (right panel: associated requests counter), §Behaviour (links to requests), sdp-area-07 (7b) §7b.5 (no changes counter on the asset)
- **SDP weak spot fixed:** an asset linked to a change shows no change counter.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Linking an asset to a change raises the asset's open change counter by one, live.
  2. Closing the change moves it from open to closed in the counter.
  3. Each counter opens a list of the linked records the user may see; records they may not
     see are counted but not listed.

#### REQ-AST-045 — Raise a work item from an asset

From an asset, a user raises an incident, service request or change after picking a
template; the form opens with the asset and its user filled in (REQ-INC-029). The creation is
recorded in the asset's history.

- **Decision:** BETTER. The asset history records the new request.
- **Source:** sdp-area-07 §Actions (raise request), §Fields (new incident from an asset), sdp-area-07 (7b) §7b.3 (request creation missing from asset history)
- **SDP weak spot fixed:** creating a request from an asset did not appear in the asset's
  history.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Raising an incident from an asset adds "incident INC-n raised" to the asset history.
  2. The template list only offers templates the user may use.

#### REQ-AST-046 — Linked items in pickers

Asset pickers on work items filter by product type and site, search by name, tag, barcode,
serial and discovered serial, page through results and show only assets the user may see.

- **Decision:** SAME.
- **Source:** sdp-area-07 (7b) §7b.5 (select assets involved picker); REQ-INC-085
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Typing part of a serial number finds the asset.
  2. An asset outside the user's fine-grained access never appears (REQ-CMDB-029).

---

## 13. The asset pages

#### REQ-AST-047 — Asset list and product type tree

The asset area shows a product type tree beside a list. Default columns are name, user,
department, parent asset, product, product type, state, asset tag and site. Built-in views
include all assets, my assets, scan failures, loanable assets, assets in stock, warranty
expiring and recently discovered. Users can save custom views and mark favourites
(REQ-INC-106, REQ-INC-107). The tree scrolls normally and works with the keyboard.

- **Decision:** BETTER. The tree is accessible and the list scales.
- **Source:** sdp-area-07 §Navigation path (asset tree), §Screens (asset tree and list), §Weak spots (tree scrolls oddly, responds only to real clicks)
- **SDP weak spot fixed:** the asset tree scrolled oddly and only responded to real mouse
  clicks.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Selecting "Workstation" in the tree lists only workstations and their counts.
  2. The tree can be navigated with arrow keys and passes the accessibility checks
     (REQ-WI-023).
  3. A list of 50,000 assets opens its first page in under 1 second at design load
     (REQ-WI-024).

#### REQ-AST-048 — Asset record page

The asset page has fixed tabs: details, hardware, software, relationships, associations,
financials, contracts, scan history and history. A side panel shows state, life cycle,
workflow, owner, loan, purchase order, age, last scan result and time, and association
counters. Actions include edit, assign, scan now, remote control, copy, change product, mark
loanable, configure depreciation, raise a work item, print and dispose. The layout stays
readable in a narrow window.

- **Decision:** BETTER.
- **Source:** sdp-area-07 §Screens (asset detail page), §Weak spots (layout compresses badly, vertical text), sdp-area-07 (7b) §7b.3
- **SDP weak spot fixed:** detail pages compressed into vertical text in a narrow window.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. At 360 px width the asset page shows the side panel below the tabs with no vertical text.
  2. Actions the user may not run show disabled with a reason (REQ-WI-010).
  3. The scan history tab shows the result of the last scan within 1 second of it arriving.

#### REQ-AST-049 — History with filters

The asset history shows every change, newest first, with sub-views for state history and
assignment history, a text filter and a date filter. It includes changes from discovery
scans, loans, links, licence allocations, rules and imports, each with its source.

- **Decision:** BETTER. The history is complete and live.
- **Source:** sdp-area-07 (7b) §7b.3 (history tab), §Weak spots (history tab stale); REQ-WI-003
- **SDP weak spot fixed:** the general history tab was stale.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A scan that changes the RAM size writes one history line with source "discovery" and the
     probe or agent name.
  2. Filtering to "assignment" shows only owner changes and loans.

#### REQ-AST-050 — Notes and attachments on assets

Users add notes and attachments to an asset, for example repair notes or invoices. Notes
follow the engine rules for edit, delete and mentions (REQ-INC-061, REQ-INC-062, REQ-INC-063);
attachments follow REQ-INC-079.

- **Decision:** BETTER. ServiceDesk Plus assets have attachments but no notes.
- **Source:** sdp-area-07 §Screens (right panel: attachments)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A note on an asset appears live for other viewers.
  2. An infected attachment is refused as on incidents.

#### REQ-AST-051 — Bulk actions on assets

From the list, users with permission can act on many assets: assign to user, department or
site, change state, change product, add to group, configure depreciation, mark loanable,
reprint labels, scan now, merge duplicates and delete. Each runs as a background job for large
selections and reports success or the reason per asset (REQ-INC-119, REQ-INC-120).

- **Decision:** SAME.
- **Source:** sdp-area-07 §Screens (toolbar and actions menu), sdp-area-07 (7b) §7b.6 (workstation actions menu)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Changing the state of 300 assets streams progress and ends with a per-asset result.
  2. Assets the life cycle does not allow to move are listed with the reason and left
     unchanged.

#### REQ-AST-052 — Merge duplicate assets

A user can merge duplicate assets with a preview: which asset survives, and for each field
which value is kept. By default the discovered asset wins over one created by hand or from a
PO, and the newest scan wins between discovered ones. Links, history, loans, costs and
licence allocations move to the survivor; the other asset goes to trash.

- **Decision:** BETTER. ServiceDesk Plus merges after a yes/no prompt with no preview and
  deletes the loser.
- **Source:** sdp-area-07 (7b) §7b.6 (reconcile: merges duplicates, keeps one, deletes the other)
- **SDP weak spot fixed:** selecting one asset gives only an alert; there is no field-level
  preview.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Merging a PO-created asset into its discovered twin keeps the PO link and purchase cost
     and the discovered hardware.
  2. Both asset IDs open the survivor afterwards.
  3. The removed asset can be restored from trash within the retention period.

#### REQ-AST-053 — Import and export assets

Assets, consumables, licences, CIs, CI relationships, vendors, contracts and purchase orders
can be imported from CSV or XLSX with field mapping, a dry run, matching on asset tag or serial
number, and modes: add only, update only, add and update. Large files run as background jobs
with progress. Lists export as in REQ-INC-116.

- **Decision:** BETTER. No 3,000-row cap, a dry run, and no "delete existing and add" mode.
- **Source:** sdp-area-07 §Screens (import), §Config (import wizard: max 3000 records), §Weak spots (native select hard to read); sdp-area-14 §Screens (import data: modes, limit); sdp-area-11 §Fields (import wizard modules); architecture §2.13 (CSV import), §6.8 (imports)
- **SDP weak spot fixed:** imports are capped at 3,000 records, and one mode deletes existing
  records first.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A 20,000-row asset file imports as one job with streamed progress and a per-row error
     file.
  2. A dry run reports what would be created and updated, and changes nothing.
  3. A row matching an existing asset by serial number updates it in "add and update" mode.

---

## 14. Scan history and overdue scans

#### REQ-AST-054 — Scan history per asset

Each asset keeps a list of scans: time, source (agent, probe and scan type, import), result
and what changed since the previous scan (hardware added or removed, software installed or
removed). Admins set how long scan history is kept (Appendix A).

- **Decision:** BETTER. Each scan shows what it changed.
- **Source:** sdp-area-07 §Config (discovery settings: scan history cleanup), sdp-area-14 §Screens (settings: scan history cleanup); architecture §2.13 (change tracking, scan history)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A scan that finds a new disk lists "disk added" with model and capacity.
  2. Scan history older than the retention period is removed by a scheduled job; the asset
     and its history lines stay.
  3. A failed scan appears in the list with its reason.

#### REQ-AST-055 — Notify on hardware and software changes

Admins can be notified when a scan finds chosen changes, for example memory removed, a disk
replaced or a prohibited program installed (REQ-SAM-018).

- **Decision:** NEW.
- **Source:** architecture §2.13 (change tracking); sdp-area-09 §Screens (scan report type: historical inventory by scan time)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A rule "memory reduced" notifies the asset manager when a scan shows less RAM than the
     previous scan.
  2. No notification is sent for an unchanged scan.

#### REQ-AST-056 — Action on assets not scanned for too long

Admins can set an overdue-scan action: for chosen product types and criteria, an asset not
scanned for a set number of days is moved to a chosen state, or moved to trash. It is off by
default. Assets that would be affected are previewed before the rule is saved, and each run
lists what it changed.

- **Decision:** BETTER. ServiceDesk Plus can delete the asset outright; here the strongest
  action is trash, which can be restored, and the rule shows its effect first.
- **Source:** sdp-area-07 §Config (overdue-scan handling: delete asset or move to state), sdp-area-14 §Screens (overdue asset scan action), §Automation
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. With 60 days and "move to missing", a laptop last scanned 61 days ago moves to missing at
     the next run with a history entry naming the rule.
  2. Saving the rule shows how many assets it would affect now.
  3. An asset moved to trash by the rule can be restored with its history.

---

## 15. Remote support, access and other modules

#### REQ-AST-057 — Remote control from an asset or a ticket

A technician with the remote-control permission can start a remote session to a discovered
computer from its asset page or from a work item that has it attached, through AgentX or a
TeamViewer or AnyDesk integration (ADR-016, still open). The session start and end are logged
on the asset and the work item.

- **Decision:** SAME. Native through Extravis AgentX instead of a separate add-on.
- **Source:** architecture §2.13 (remote support); ADR-016; sdp-area-07 §Screens (toolbar: remote control); sdp-area-11 §Fields (role: remote control); sdp-area-14 §Licence and plan (remote control add-on)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A technician without the permission sees the action disabled with a reason.
  2. Starting a session from an incident writes a note to the incident and a history line to
     the asset.
  3. If no remote tool is connected, the action says so and offers no dead link.

#### REQ-AST-058 — Asset permissions by action

Roles grant view, add, edit and delete on assets, and separate permissions for asset
configuration, discovery configuration, asset audits, audit scanning, remote control, editing
disposed assets and revealing licence keys. Fine-grained access narrows the scope
(REQ-CMDB-029).

- **Decision:** SAME.
- **Source:** sdp-area-11 §Fields (role matrix: inventory; roles asset config, asset manager, asset audit admin, auditor, remote control); REQ-WI-015
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A role with view-only on assets sees no edit, assign or delete actions, and the API
     refuses them.
  2. Only a role with discovery configuration can open probe and credential settings.

#### REQ-AST-059 — Asset notifications

Asset events can notify chosen recipients through the notification engine (REQ-NTF-001,
REQ-NTF-008): asset assigned, acknowledgement pending, loan due and overdue, warranty
expiring, stock below threshold, scan failed and state changed. The defaults on are in
Appendix A.

- **Decision:** SAME.
- **Source:** sdp-area-12 §Screens (notification rules: asset tab); sdp-area-07 §Automation
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A loan reaching its expiry notifies the borrower on the day, under the defaults.
  2. A warranty expiring in 30 days notifies the asset manager once.

#### REQ-AST-060 — Asset data for reports and dashboards

Assets, scans, states, loans, consumables, depreciation and audits are available to the
report builder and dashboards (file 09), including scan-based reports of inventory as it was
at a past scan time.

- **Decision:** SAME.
- **Source:** sdp-area-09 §Screens (asset report modules, canned asset reports, scan report type); sdp-area-01 §Screens (asset dashboard widgets); architecture §2.8 (prebuilt reports)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A report of computers by OS version as at a chosen past date uses scan history.
  2. The asset dashboard counters change live when an asset changes state.

#### REQ-AST-061 — Assets in the mobile app

Technicians look up assets in the mobile app by search or scan, see details and links, change
state, assign, and raise an incident from an asset.

- **Decision:** SAME.
- **Source:** architecture §2.15 (mobile apps), §9.1; D-065
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Scanning an asset's QR code opens it in the app.
  2. A state change in the app follows the asset life cycle (REQ-AST-013).

#### REQ-AST-062 — Warranty tracking

Each asset has a warranty end date, optionally from a linked warranty contract (REQ-CON-001).
Views and rules can find assets whose warranty ends within a period.

- **Decision:** SAME.
- **Source:** sdp-area-07 (7b) §7b.3 (warranty expiry date); sdp-area-07 §Fields (contract type: warranty)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Linking a warranty contract ending 2027-03-31 sets the asset's warranty end date to that
     date unless it already has its own.
  2. The "warranty expiring" view lists assets ending within 90 days by default.

---

## 16. Discovery: boundary and agent

Discovery replaces what ServiceDesk Plus gets from another vendor's endpoint agent and probes
(architecture §2.13, §6.9). It lives in the `discovery` module and hands results to `assets`
and `cmdb` through their service interfaces.

#### REQ-DSC-001 — Discovery is inventory, never monitoring

Discovery collects what a machine or device is and what is installed on it. It does not
measure performance, check availability, collect metrics or raise alerts. SNMP is used only to
read inventory. Device health comes from MonetX, read-only (REQ-CMDB-012).

- **Decision:** NEW. A written boundary, tested in CI.
- **Source:** architecture §2.13 (SNMP inventory only, no monitoring), §6.9 (inventory only); ADR-017; D-001; CLAUDE.md §1
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. An architecture test checks that no discovery component schedules availability checks or
     stores time-series metrics.
  2. SNMP scans issue only read requests for inventory objects; a test asserts no SNMP set or
     trap listener exists.
  3. The scan payload schema holds inventory attributes only.

#### REQ-DSC-002 — Discovery agent for Windows, macOS and Linux

A small SupportX agent runs on Windows, macOS and Linux. It collects hardware, software,
operating system, patches, services, logged-on users and peripherals; sends only changes after
the first full scan; caches results while offline; and updates itself from signed packages.
The agent technology is chosen in ADR-015 (reuse the AgentX agent first, or a new agent).

- **Decision:** BETTER. ServiceDesk Plus needs another product's agent.
- **Source:** architecture §2.13 (agent-based), §6.9 (discovery agent); ADR-015; product-plan §5 (discovery via AgentX)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. After the first full scan, installing one program sends a delta holding only that change.
  2. A machine offline for 3 days sends its cached scans when it reconnects, in order.
  3. An update package with a bad signature is refused and the refusal is reported.
  4. The agent stays within the footprint limits in Appendix A on a reference machine.

#### REQ-DSC-003 — Agent enrolment and identity

Agents enrol with a tenant-scoped enrolment token and receive an identity certificate. They
talk to the server or the nearest probe over HTTPS with mutual TLS. Admins can list agents
(machine, version, last contact, site), revoke one, and rotate tokens. Deployment packages
for mass install (for example through group policy or endpoint tools) are available to
download.

- **Decision:** SAME.
- **Source:** architecture §6.9 (agent communication)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. An agent enrolled with tenant A's token can never send data into tenant B.
  2. A revoked agent's next connection is refused and its asset shows "agent revoked".
  3. An expired enrolment token cannot enrol a new agent.

#### REQ-DSC-004 — Scheduled and on-demand scans

Admins set scan schedules for agents and for each agentless scan. Technicians can start a scan
now for one asset or a selection. The result reaches the asset page live.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Screens (scan now on asset and list); architecture §2.13 (scheduled and on-demand scans, scan schedules)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. "Scan now" on an online agent updates the asset's last scan time within 2 minutes.
  2. "Scan now" on an offline agent says it is offline and queues the request.
  3. A schedule set to daily at 02:00 site time runs in the site's time zone.

---

## 17. Discovery: probes, credentials and scans

#### REQ-DSC-005 — Site probes

A probe is a container that admins install at a site or in an isolated network. It runs
agentless scans, relays agent traffic and uploads results over one outbound connection. The
probe list shows name, host, site, last contact, version and status. Probes can be downloaded,
registered with a key, renamed, moved to a site and removed.

- **Decision:** BETTER. Only outbound connections, no inbound firewall opening.
- **Source:** sdp-area-07 §Screens (probes & discovery), §Config (probe columns); sdp-area-14 §Screens (probe list); architecture §2.13 (distributed scanning), §6.9 (site probe)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A probe behind a firewall that allows only outbound HTTPS registers and uploads results.
  2. A probe silent for longer than the set period shows offline and notifies discovery
     admins once.
  3. Removing a probe stops its schedules and keeps the scan history it produced.

#### REQ-DSC-006 — Credential vault

Scan credentials are kept in a vault: name, protocol (Windows, SSH, SNMP v1, v2c and v3,
VMware, Hyper-V, directory), and secret. Secrets are encrypted with the tenant key, are never
shown again after entry, are released only to the probe that needs them for a scan, and every
use is logged.

- **Decision:** BETTER. Secrets are write-only and each use is logged.
- **Source:** sdp-area-07 §Config (credential library columns); sdp-area-14 §Screens (credential library); architecture §2.13 (credential vault), §6.9 (credential vault)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. No API returns a stored secret; editing a credential can only replace it.
  2. A probe at site A cannot fetch a credential used only by scans at site B.
  3. The credential's usage log shows each scan that used it.
  4. Secrets never appear in logs (a log-scanning test checks this).

#### REQ-DSC-007 — Network scan

A network scan covers a whole network or an IP range or subnet, runs from a chosen probe with
chosen credentials for Windows, Linux and Unix, SNMP and VMware, optionally includes a software
scan, and runs on a schedule or now. Each run lists devices found, identified, failed and
excluded.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Config (network scan form); sdp-area-14 §Screens (network scan); architecture §2.13 (agentless)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A scan of a /24 range reports found, identified, failed and excluded counts that add up.
  2. A device inside an exclusion is not contacted (REQ-DSC-016).

#### REQ-DSC-008 — Directory (domain) scan

A domain scan imports computers from Active Directory: domain name, domain controller, account,
SSL, base DN or organisational units, exclusions, a probe and a software-scan option for
non-Windows machines. Found computers are then scanned for inventory.

- **Decision:** SAME.
- **Source:** sdp-area-11 §Fields (domain scan form), §Screens (domain scan discovers computers, not users); sdp-area-14 §Screens (domain scan); sdp-area-07 §Config (domain scan columns); architecture §2.13 (Active Directory computer import)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A domain scan limited to one OU imports only computers in that OU.
  2. Computers disabled in the directory are flagged on their assets.

#### REQ-DSC-009 — Agentless Windows, Linux, Unix and macOS scans

Probes scan Windows through WMI and WinRM, and Linux, Unix (including Solaris and AIX) and
macOS through SSH, collecting the same inventory as the agent where the protocol allows.

- **Decision:** SAME.
- **Source:** architecture §2.13 (agentless), §6.9; sdp-area-07 §Config (credentials for Windows, Linux/Mac/Solaris/AIX)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A WinRM scan of a Windows server fills OS, memory, disks and installed software.
  2. An SSH scan with a wrong password fails with "authentication failed" in the scan failure
     list.

#### REQ-DSC-010 — SNMP inventory of network devices and printers

Probes read inventory from SNMP devices (switches, routers, access points, printers): name,
model, serial, firmware, interfaces and MAC addresses. The device's object identifier decides
its product type and product. Admins can let discovery create product types it does not yet
know.

- **Decision:** SAME. Inventory only (REQ-DSC-001).
- **Source:** sdp-area-07 §Config (discovery settings: create custom product types during SNMP discovery); architecture §2.13 (SNMP inventory)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. An SNMP v3 switch with a known identifier becomes a switch asset with its serial number.
  2. With "create product types" off, an unknown device goes to the unknown-identifier list
     (REQ-DSC-011) instead.

#### REQ-DSC-011 — Unknown SNMP device identifiers

Devices that SNMP reached but could not identify are listed with their identifier,
description and address. An admin maps an identifier to a product type and product; the
device and every later device with that identifier are then classified.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Config (discovery settings: unknown OID tab); sdp-area-14 §Screens (unknown OID)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Mapping an identifier to "printer" turns every listed device with it into a printer asset.
  2. A later scan finding the same identifier classifies it without a list entry.

#### REQ-DSC-012 — Virtual hosts and machines

Probes read VMware vCenter and Hyper-V: hosts, clusters and virtual machines. Virtual
machines become assets of a virtual machine type, linked to their host by a "runs on"
relationship, and the link moves when a machine moves host.

- **Decision:** SAME.
- **Source:** architecture §2.13 (VMware vCenter and Hyper-V); sdp-area-07 §Screens (asset tree: virtual hosts, virtual machines), §Config (VMware credentials)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A vCenter scan with 3 hosts and 40 machines creates 43 assets and 40 "runs on" links.
  2. Moving a machine to another host updates the link at the next scan, with history on both.

#### REQ-DSC-013 — Import from SCCM, Intune and other endpoint tools

Admins connect Microsoft SCCM/MECM (database host and name, probe, schedule) and Microsoft
Intune (computers and mobile devices) as inventory sources. Each connection shows its status
and the result of the last run. Lansweeper and AgentX are further sources. Connector set-up is
in file 12; this requirement covers how their data is reconciled.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Config (SCCM integration columns); sdp-area-14 §Screens (SCCM integration; integrations: Microsoft Intune); architecture §2.13 (other sources), §2.14 (endpoint and UEM)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. An Intune phone and the same phone found by another source reconcile into one asset.
  2. A failed SCCM connection shows "connection failed" with the reason on the integration.
  3. Each attribute shows which source set it (REQ-DSC-018).

#### REQ-DSC-014 — Cloud accounts

Admins connect AWS, Azure and Google Cloud accounts read-only. Discovery imports virtual
machines, databases, storage, load balancers and networks as assets or CIs with their tags and
relationships.

- **Decision:** NEW.
- **Source:** architecture §2.13 (cloud accounts); product-plan §5 (CMDB: cloud discovery), Appendix B (cloud discovery)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Connecting an AWS account with read-only access imports its virtual machines with region
     and tags.
  2. A machine deleted in the cloud is marked retired in SupportX at the next run, not deleted.

#### REQ-DSC-015 — Self-scan scripts

For machines without the agent and unreachable by probes, admins download a signed self-scan
program and script (Windows, macOS, Linux) that users or a logon script run. The script sends
one inventory scan with a tenant token.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Config (discovery settings: scan script); sdp-area-14 §Screens (scan script: self-scan, AD logon script)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Running the script on a Windows machine creates or updates its asset with source
     "self-scan".
  2. A script with an expired or revoked token is refused.

#### REQ-DSC-016 — Exclude devices

Admins exclude devices from discovery by IP address, range or name, globally or per scan.
Excluded devices are never contacted and never created.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Config (discovery settings: exclude devices); sdp-area-14 §Screens (exclude devices by IP, range or name); sdp-area-11 §Fields (domain scan: exclude devices)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A range exclusion stops a network scan from contacting any address inside it.
  2. A name exclusion stops the matching computer from being created by a domain scan.

#### REQ-DSC-017 — Network devices from MonetX, read-only

Tenants with the MonetX connector can import the network devices MonetX already knows as
assets, read from the MonetX API, read-only. This replaces turning another product's monitors
into assets. Topology links between them are imported into the CMDB (REQ-CMDB-013).

- **Decision:** NEW.
- **Source:** product-plan §5 (IT asset: network assets from MonetX); D-001; ADR-017; sdp-area-07 §Config (discovery settings: create monitors as assets)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A MonetX device becomes one asset with source MonetX, and a second import updates it.
  2. The connector makes no write call to MonetX.
  3. If MonetX cannot be reached, the run is marked failed with the reason; existing assets
     are untouched.

---

## 18. Discovery: identification and reconciliation

#### REQ-DSC-018 — Identification rules

Discovery matches a scan to an existing asset or CI by identification rules in order: serial
number, SMBIOS UUID, then MAC address plus host name (Appendix A). Admins can:

- keep a list of invalid serial numbers that are ignored for matching (seeded with common
  placeholder values);
- switch matching by MAC address on or off;
- choose the computer name format (directory domain name, DNS domain name, or none).

- **Decision:** SAME.
- **Source:** sdp-area-07 §Config (discovery settings: invalid service-tag list, MAC identification, computer name format); sdp-area-14 §Screens (settings: general); architecture §6.9 (reconciliation: identification rules)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Two machines both reporting a listed placeholder serial are not matched to each other.
  2. With MAC matching off, a machine with a new serial and an old MAC becomes a new asset.
  3. With DNS name format on, the asset name shows the fully qualified DNS name.

#### REQ-DSC-019 — Reconciliation by source and attribute

Reconciliation merges a scan into the matched asset or CI, or creates one. Admins set which
source wins for each attribute (for example the agent for software, the directory for owner,
the purchase order for cost). Every attribute records its source and when it was set. Values
typed by hand are protected from being overwritten unless the admin allows it.

- **Decision:** BETTER. ServiceDesk Plus uses one rule for the whole record.
- **Source:** architecture §2.12 (population: reconciliation, integration mapping showing each CI's source), §6.9 (reconciliation); sdp-area-07 (7b) §7b.6 (reconcile: discovered wins over PO-created)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A scan never overwrites a purchase cost that came from a PO.
  2. Each attribute on an asset can show its source and time.
  3. Scanning the same machine twice with no change writes no history.

#### REQ-DSC-020 — Ambiguous matches go to a review queue

When a scan could match more than one asset, or matches an asset that a different machine
reported recently, it is not merged automatically. It goes to a review queue where an admin
merges it, creates a new asset or discards it.

- **Decision:** NEW. Prevents silent wrong merges.
- **Source:** architecture §6.9 (de-duplicate); sdp-area-07 (7b) §7b.6 (reconcile)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A scan whose serial matches asset A and whose MAC matches asset B goes to the queue.
  2. Choosing "merge into A" applies the scan to A and records the admin's decision.

#### REQ-DSC-021 — Name normalisation

Discovery normalises manufacturer names and software titles (for example different spellings
of one vendor) before storing them, from a shared list that admins can extend.

- **Decision:** SAME.
- **Source:** architecture §6.9 (discovery service: name normalisation); sdp-area-07 (7b) §7b.1 (software manufacturers: reconcile)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Two scans reporting the same vendor with different spellings link to one manufacturer.
  2. An admin-added alias applies to the next scan.

#### REQ-DSC-022 — Scan failure list with reasons

Failed scans are listed with the device, scan, probe, time, reason and a suggested fix (for
example wrong credentials, host unreachable, protocol disabled). Admins can retry one or many.

- **Decision:** BETTER. Each failure has a labelled reason and a suggested fix.
- **Source:** sdp-area-07 §Screens (scan failures); architecture §2.13 (scan failure list with reasons)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A WinRM scan blocked by a firewall shows "host unreachable" with a suggested fix.
  2. Retrying a failure that now succeeds removes it from the list and updates the asset.

#### REQ-DSC-023 — Scan history and audit

Every scan run (schedule or manual) is recorded: who or what started it, probe, credentials
used (by name), start, end, counts and errors. Changes to discovery settings are audited.

- **Decision:** SAME.
- **Source:** architecture §2.13 (scan history and audit)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Each scheduled run appears in the run list with its counts.
  2. Changing an exclusion writes an audit entry with old and new values.

#### REQ-DSC-024 — Patches and services from inventory

The agent reports installed patches and services. The asset shows them, and incidents and
changes can see which patches a machine has. Deploying patches is done through PatchX
(file 12).

- **Decision:** SAME.
- **Source:** architecture §2.13 (agent collects patches, services), §2.14 (patch deployment via PatchX)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A machine's patches tab lists installed patches with install date.
  2. A view can find machines missing a named patch.

#### REQ-DSC-025 — Discovery overview

Discovery admins see an overview: agents online and offline, probes and their status, scans
run today, failures, pending assets and the last run of each source.

- **Decision:** NEW.
- **Source:** architecture §2.13 (scan management); sdp-area-14 §Screens (probes & discovery: separate empty lists)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. An agent going offline changes the online count without a refresh.
  2. Each number opens the matching list.

#### REQ-DSC-026 — Asset limit at reconciliation

When the managed asset limit is reached, newly discovered assets are held in a pending list
instead of being created. Updates to existing assets continue. Admins are notified once and
can approve pending assets as slots free up.

- **Decision:** BETTER. Nothing discovered is lost when the limit is hit.
- **Source:** architecture §6.9 (managed assets limit enforced at reconciliation); REQ-AST-002
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. At the limit, a scan of a new machine adds it to the pending list and notifies admins.
  2. A scan of an existing machine still updates it.
  3. Disposing one asset lets an admin approve one pending asset.

#### REQ-DSC-027 — Discovery works on-prem and air-gapped

Agents, probes and self-scan scripts work with no internet access. Agent and probe updates can
be loaded from the offline update bundle.

- **Decision:** NEW. ServiceDesk Plus discovery features differ between cloud and on-prem.
- **Source:** architecture §1.2, §14.2; product-plan §4.3 (pillar 1: one product, every deployment)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. In an air-gapped install, an agent enrols, scans and updates from the offline bundle.
  2. No discovery component calls an external address in an air-gapped profile.

#### REQ-DSC-028 — Probe and agent counts

The number of probes and agents is not limited separately; only managed assets are counted
(REQ-AST-002).

- **Decision:** BETTER. ServiceDesk Plus counts probes as a separate licensed item.
- **Source:** sdp-area-14 §Licence and plan (10 probes); architecture §6.9, §13.1 (counted limits)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Registering a 20th probe needs no extra entitlement.
  2. The licence page shows no probe or agent limit.

#### REQ-DSC-029 — Scan credentials for one asset

A technician with discovery permission can set which vault credential is used to scan one
asset, overriding the scan's credentials, for example a server with its own local account.
The secret itself is never shown (REQ-DSC-006).

- **Decision:** SAME.
- **Source:** sdp-area-07 §Screens (asset actions: update credentials)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. The next scan of that asset uses the chosen credential, and the scan history names it.
  2. The asset page shows the credential's name only.

#### REQ-DSC-030 — No monitors turned into assets

SupportX does not create assets from monitoring objects (monitors, probes of health or
performance checks). Network devices known to MonetX come in as inventory through the
read-only device import (REQ-DSC-017).

- **Decision:** SKIP. Turning monitors into assets depends on a monitoring product inside the
  service desk, which is MonetX's job (ADR-017, D-001). REQ-DSC-017 replaces it.
- **Source:** sdp-area-07 §Config (discovery settings: create monitors as assets); ADR-017; D-001
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Discovery settings offer no "create assets from monitors" option.
  2. Only device inventory from MonetX is imported; monitor definitions are never read.

---

## 19. Software catalogue

#### REQ-SAM-001 — Software catalogue

The software catalogue lists every software title known to the tenant, from scans and by hand:
name, version, manufacturer, category, software type, suite flag, cost, description and
images. Built-in views include all software, software with no installations, suites and
software by type. Users with permission add software by hand.

- **Decision:** SAME.
- **Source:** sdp-area-07 (7b) §7b.2 (software list, views, details tab); architecture §2.11 (software catalogue)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A title found by a scan appears in the catalogue with type "unidentified" until someone
     classifies it.
  2. The "no installations" view lists titles with zero installations.
  3. Versions of one title are grouped under it and can be listed separately.

#### REQ-SAM-002 — Software types with a fixed meaning

Admins classify software by type. Each type maps to one fixed category: managed, prohibited,
freeware, shareware, excluded (not tracked) or unidentified. Compliance, alerts and reports use
the category. Types can be changed one by one or in bulk.

- **Decision:** BETTER. Admin-added types keep a fixed meaning.
- **Source:** sdp-area-07 (7b) §7b.1 (software type list), §7b.2 (modify software type); architecture §2.11 (prohibited software)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Setting a title to a type in category prohibited starts prohibited-software alerts for it
     (REQ-SAM-018).
  2. Excluded titles do not appear in compliance or installation counts.
  3. Changing the type of 50 titles at once reports a result per title.

#### REQ-SAM-003 — Software categories and manufacturers

Admins keep software categories (for example database, development, graphics) and software
manufacturers (display name, name, description). Duplicate manufacturers can be merged, moving
their software and licence types to the survivor.

- **Decision:** SAME.
- **Source:** sdp-area-07 (7b) §7b.1 (software category, software manufacturers: reconcile), §7b.2 (modify category, modify manufacturer)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Merging two manufacturers moves all their titles to the survivor with history.
  2. A category in use cannot be deleted until its titles are moved.

#### REQ-SAM-004 — Software suites

A title can be a suite made of other titles. A suite licence covers its member titles.
A title can be converted to a suite.

- **Decision:** SAME.
- **Source:** sdp-area-07 (7b) §7b.2 (new software suite, convert as software suite); architecture §2.11 (suites)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A machine with all members of an office suite installed uses one suite licence, not one
     per member.
  2. Converting a title to a suite keeps its installations and licences.

#### REQ-SAM-005 — Installations

Each title shows the computers it is installed on (from scans or added by hand): computer,
version, user and licence, split into licensed and unlicensed. The asset's software tab shows
the same from the machine's side, filterable by software type, with licence key, product ID,
installed on and added by. Users can add or remove manual installations.

- **Decision:** SAME.
- **Source:** sdp-area-07 (7b) §7b.2 (installations tab), §7b.3 (asset software tab)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A scan that finds an uninstalled title removes the installation and records "uninstalled"
     in the title's history.
  2. A manual installation is marked "added by hand" and is not removed by a scan.
  3. The asset's software tab filtered to "prohibited" shows only prohibited titles.

#### REQ-SAM-006 — Software users and history

Each title shows its users and departments (from the machines it is installed on) and a
history of installs, updates, uninstalls and licence allocations, filterable by operation and
date.

- **Decision:** SAME.
- **Source:** sdp-area-07 (7b) §7b.2 (usages tab, history tab)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. The usage view lists each user with department and computer.
  2. Filtering history to "uninstalled this month" lists only uninstalls in that period.

#### REQ-SAM-007 — Service packs and versions

Service packs and updates of titles are recorded with the machines that have them, and can be
listed per title.

- **Decision:** SAME.
- **Source:** sdp-area-07 (7b) §7b.2 (sub-lists: service packs)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A title's service pack list shows each pack with its installation count.

#### REQ-SAM-008 — Email the users of a title

From a title, a technician can send a message to all its users, for example before removing
it.

- **Decision:** SAME.
- **Source:** sdp-area-07 (7b) §7b.2 (actions: notification > email users)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Sending to a title with 12 users sends 12 messages, each in the recipient's language,
     and logs them on the title.

---

## 20. Licences, agreements and allocation

#### REQ-SAM-009 — Licence types

Admins keep licence types per manufacturer. Each type says what it tracks (computer or user),
how many installations it allows (single, volume, unlimited, OEM, or multiple), whether it is
perpetual, whether it is free, and its licence options (for example retail, volume
agreement). Seeded types cover individual, volume, enterprise perpetual, enterprise
subscription, OEM, client access, concurrent, node-locked, named user, trial and subscription
licences (Appendix A).

- **Decision:** SAME.
- **Source:** sdp-area-07 (7b) §7b.1 (software licence types table and dialog); architecture §2.11 (licence types)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A named-user type counts one use per user, whatever the number of machines.
  2. A concurrent type is checked against peak use where metering data exists
     (REQ-SAM-016), and otherwise against installations.
  3. A type in use cannot be deleted.

#### REQ-SAM-010 — Licence records

A licence holds: manufacturer, title, name, licence type, option, vendor, licence keys,
organisation-wide flag, site, renewal type (monthly to annual or custom), acquisition date,
expiry date, purchase cost, purchased for, description, the purchase order and the contract.
Standard and upgrade licences are supported.

- **Decision:** SAME.
- **Source:** sdp-area-07 (7b) §7b.2 (new standard licence form, licences tab), §7b.2 (new upgrade licence)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. An upgrade licence must name the licence it upgrades and does not add installations of
     its own.
  2. A licence with an expiry date is excluded from compliance after it expires.
  3. A licence received from a PO links to that PO.

#### REQ-SAM-011 — Licence keys are protected

Licence keys are stored encrypted, shown masked, and revealed only to users with the reveal
permission. Each reveal is audited.

- **Decision:** NEW. ServiceDesk Plus shows keys in plain text in lists.
- **Source:** sdp-area-07 (7b) §7b.2 (licences tab: licence key column); architecture §11.3 (field-level encryption)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A licence list shows keys masked for every user.
  2. Revealing a key needs the permission and writes an audit entry.
  3. Exports include keys only for users with the reveal permission.

#### REQ-SAM-012 — Licence agreements

A licence agreement groups licences bought under one deal: agreement number, manufacturer,
vendor, acquisition and expiry dates, purchase order, status and documents. Agreements show
days to expiry.

- **Decision:** SAME.
- **Source:** sdp-area-07 (7b) §7b.2 (licence agreements tab and columns, new licence agreement)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. An agreement lists its licences and their total installations allowed.
  2. An agreement expiring in 30 days shows in the expiring view.

#### REQ-SAM-013 — Allocate licences

Technicians allocate a licence to an installation (computer-tracked) or a user (user-tracked),
by hand or with auto-allocate. Auto-allocate fills free licences against unlicensed
installations, using the most specific licence first. Licences can be moved between sites.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Behaviour (auto allocate licence turns under-licensed to compliant), sdp-area-07 (7b) §7b.2 (licences tab: auto allocate, move licence to site)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. With one free single licence and one unlicensed installation, auto-allocate links them
     and compliance turns compliant, live.
  2. A licence cannot be allocated beyond its allowed installations.
  3. Uninstalling software frees its allocation.

#### REQ-SAM-014 — Upgrade and downgrade rights

A licence can list the earlier versions or other titles it may cover (downgrade rights) and
upgrades it receives. Compliance counts allocations to downgrades.

- **Decision:** SAME.
- **Source:** sdp-area-07 (7b) §7b.2 (downgrade rights section; summary: downgrade, allocated to downgrades); architecture §2.11 (upgrade and downgrade)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A licence for version 2024 with downgrade rights to 2021 can be allocated to a 2021
     installation.
  2. The licence summary shows "allocated to downgrades" separately.

---

## 21. Compliance, metering and alerts

#### REQ-SAM-015 — Licence compliance

Each managed title shows its compliance: compliant, under-licensed or over-licensed, by site
and for the whole organisation, with a summary of installations (licensed, unlicensed, all)
and licences (purchased, installations allowed, allocated, available, downgrade). A compliance
overview lists every managed title with its status and the gap, and updates live when scans,
allocations or licences change.

- **Decision:** BETTER. ServiceDesk Plus has no compliance overview; status shows only on each
  title.
- **Source:** sdp-area-07 (7b) §7b.2 (compliance type dropdown, summaries), §7b.2 (compliance: no standalone screen); architecture §2.11 (compliance: over and under licensed)
- **SDP weak spot fixed:** there is no screen that shows compliance across all software.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A title with 5 installations and 3 licences shows under-licensed by 2.
  2. A new installation found by a scan changes the overview within 1 second of the scan
     being stored.
  3. Organisation-wide licences count for every site; site licences count only for their site.

#### REQ-SAM-016 — Software metering

The agent records when each managed title was last used and how much. Titles and machines
show last-used dates, and a view lists installations unused for a set period.

- **Decision:** NEW. ServiceDesk Plus has no usage metering in the researched edition.
- **Source:** architecture §2.11 (software metering)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A title not started on a machine for 90 days appears in the unused view for that machine.
  2. Metering stores usage counts and last-used dates only, never content or window titles.

#### REQ-SAM-017 — Reclaim unused licences

From the unused view, a technician can reclaim licences: notify the user, uninstall through
the endpoint tool where available, and free the allocation. Reclaimed counts show in reports.

- **Decision:** NEW.
- **Source:** architecture §2.11 (software metering); product-plan §5 (IT asset: licence compliance)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Reclaiming a licence frees its allocation and records the reason.
  2. The user is notified before uninstall if the tenant requires it.

#### REQ-SAM-018 — Prohibited software alerts

When a scan finds a prohibited title, the asset's owner and chosen technicians are notified,
and optionally an incident is created and linked to the asset. A view lists every machine with
prohibited software.

- **Decision:** BETTER. The finding can start work, not only show in a filter.
- **Source:** architecture §2.11 (prohibited software); sdp-area-07 (7b) §7b.3 (software tab type filter: prohibited)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A scan finding a prohibited title on a laptop sends one alert and, if set, one incident
     linked to the laptop.
  2. The next scan finding the same title on the same laptop does not send a second alert.
  3. Uninstalling the title clears the machine from the view.

#### REQ-SAM-019 — Licence expiry and renewal

Licences and agreements with expiry dates notify chosen users before expiry (Appendix A) and
can create a renewal request. Subscriptions show their renewal type and next renewal date.

- **Decision:** SAME.
- **Source:** sdp-area-07 (7b) §7b.2 (renewal type, expiry date); architecture §2.11 (subscription)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A subscription expiring in 30 days notifies the licence owner once at each lead time.
  2. A renewed licence keeps the previous period in its history.

#### REQ-SAM-020 — Microsoft 365 and SaaS subscriptions

SupportX reads Microsoft 365 licence assignments (read-only) and shows, per subscription, the
licences bought, assigned and unused, and which users hold them.

- **Decision:** NEW. ServiceDesk Plus needs a separate SaaS management product.
- **Source:** architecture §2.11 (Microsoft 365 licence tracking); sdp-area-14 §Screens (integrations: SaaS management product)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A tenant with 100 bought and 92 assigned licences shows 8 unused.
  2. The connector makes only read calls.

#### REQ-SAM-021 — Software page layout

The software page has fixed tabs (details, licence agreements, installations, licences,
users, history) and a header with a site filter and the compliance status. The tab order never
changes with use.

- **Decision:** BETTER.
- **Source:** sdp-area-07 (7b) §7b.2 (tab strip reorders itself around the last tab opened; header site selector and compliance); REQ-WI-011
- **SDP weak spot fixed:** the software tab strip reorders itself around the last tab opened.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Opening the history tab and coming back keeps the tabs in the same order.
  2. Changing the site filter updates the compliance status and summaries for that site.

#### REQ-SAM-022 — Software and licence data for reports

Software, installations, licences, allocations, compliance and usage are available to reports
and dashboards (file 09), including a canned software dashboard.

- **Decision:** SAME.
- **Source:** sdp-area-09 §Screens (report modules: software, software installations, software licences; canned software dashboard)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A report of under-licensed titles by site matches the compliance overview.
  2. The software dashboard updates live when compliance changes.

---

## 22. CI types, CIs and states

#### REQ-CMDB-001 — CI types with attributes and inheritance

Admins keep a tree of CI types: name, API name, parent type, icon and description. A type has
attributes (custom fields), inherits its parent's attributes, and lists which relationship
types it allows. A new tenant gets a seed tree (Appendix A). Attributes can be defined when
the type is created.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Fields (new CI type: name, API name, parent, icon, description; tabs unlock after saving), §Config (CMDB: 53 CI types); architecture §2.12 (CI model)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. An attribute added to "Server" appears on every "Database server" CI.
  2. A type with CIs cannot be deleted; the admin sees how many CIs use it.
  3. Type names render through labels in every language; the API name is never shown to
     users.

#### REQ-CMDB-002 — CI records

A CI has a name, CI type, description, state, location, site, managed by, owned by, business
impact, the asset it comes from (if any), attached documents, source and the attributes of its
type. Business services also have a service status, support hours and criticality.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Fields (new business service CI), §Screens (CI right panel: state, attached documents); architecture §2.12 (CI model: attached documents)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A business service records its support hours and criticality, and both are available to
     incident and change rules.
  2. A CI made from an asset shows a link to the asset and the asset shows the CI.
  3. Attaching a document to a CI follows REQ-INC-079.

#### REQ-CMDB-003 — CI states: active and end of life

Admins define CI states. Each maps to active or end of life. By default, end-of-life CIs are
left out of CI pickers in all modules; the tenant can switch this off. A new tenant gets the
states in Appendix A.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Fields (state grouped active / EOL), §Config (CI states; configurations: exclude EOL CIs from system CI fields)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A decommissioned CI does not appear in the incident CI picker under the defaults.
  2. Existing links to a CI that becomes end of life are kept and marked.

#### REQ-CMDB-004 — Create, copy and change CIs

Users with permission create CIs, copy a CI, change its type (with a preview of attributes that
will be lost, as in REQ-AST-006), change its state in bulk, delete CIs (to trash) and turn
selected assets into CIs.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Screens (business service list: new, modify CI type, modify state, delete, mark as CIs; CI toolbar), §Actions (copy CI, modify CI type)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Copying a CI copies its attributes but not its relationships unless the user chooses to.
  2. Deleting a CI with relationships lists them and removes them with history on both sides;
     restoring the CI restores them.
  3. "Make CI" on 10 selected servers creates 10 CIs linked to their assets.

#### REQ-CMDB-005 — CI lists and views

The CMDB area shows business views, baselines and the CI type tree beside a list per type.
Users can save custom views, filter on any attribute, export and run bulk actions with
per-record results (REQ-INC-106, REQ-INC-116, REQ-INC-120).

- **Decision:** SAME.
- **Source:** sdp-area-07 §Screens (CMDB home: business views, baseline configurations, CI-type tree)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Selecting a CI type lists its CIs and those of its child types.
  2. A filter on a type-specific attribute is offered only when one type is selected.

---

## 23. Relationships, the map and business views

#### REQ-CMDB-006 — Relationship types with one name per direction

Admins keep relationship types. Each has a name for each direction (for example "runs on" /
"hosts", "depends on" / "used by"), whether it carries impact, and which CI types it may join.
Some types are suggested for a CI type. Seed types are in Appendix A.

- **Decision:** BETTER. A type can say whether impact flows through it, and which CI types it
  joins.
- **Source:** sdp-area-07 §Config (relationship types with inverse names), §Fields (add relationship dialog: suggested or custom with inverse); architecture §2.12 (custom relationship types)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A link "A runs on B" shows on B as "B hosts A", in every language.
  2. A relationship type limited to server-to-rack refuses a link between two applications.
  3. A relationship type marked "no impact" is not followed by impact analysis
     (REQ-CMDB-010).

#### REQ-CMDB-007 — Add and remove relationships

From a CI, a user adds relationships to one or more CIs at once, picking the type and the
targets from a picker with a type tree and search. Each add or remove is recorded in both CIs'
histories.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Fields (add relationship dialog), §Behaviour (history logged "relationship added"); REQ-WI-003
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Adding "depends on" from one application to three databases writes a history line on all
     four CIs.
  2. A duplicate relationship (same type, same two CIs) is refused.
  3. A relationship added in one browser appears on the open map in another within 1 second.

#### REQ-CMDB-008 — Relationship map

The relationship map shows a CI and its neighbours on a canvas. Users choose a layout (radial,
hierarchical, tree), zoom, expand a node's neighbours, filter by relationship type and CI
type, show or hide end-of-life CIs, and export the map as an image or as CSV. Each node shows
its state and open ticket counts. Escape closes only the open menu or dialog, never the whole
map.

- **Decision:** BETTER.
- **Source:** sdp-area-07 §Screens (relationship map: layouts, expand, export, show EOL; Escape closes the whole map); architecture §2.12 (visualisation: map canvas, export as image or CSV), §5 (React Flow for CMDB maps)
- **SDP weak spot fixed:** pressing Escape closed the whole map.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Expanding a node adds its direct neighbours without moving nodes already placed.
  2. Pressing Escape in an open node menu closes the menu and leaves the map open.
  3. The CSV export lists every relationship on the map with both CIs and the type.
  4. The map is usable with the keyboard and mirrors correctly in right-to-left.

#### REQ-CMDB-009 — Business views

A business view is a saved map for one base CI, usually a business service, with a name and
description. It shows open incident, problem and change counts on each node. Views can be
listed as a list or as cards and deleted by their owner or an admin.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Screens (business views list), §Fields (new business view), §Behaviour (saved a business view); architecture §2.12 (business views per service with ticket counters)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A new incident on a CI in a business view raises that node's counter without a refresh.
  2. "Save as new" creates a second view and leaves the first unchanged.

---

## 24. Impact analysis

#### REQ-CMDB-010 — Impact path analysis by depth and direction

An impact view starts from one or more CIs and follows relationships that carry impact, in a
chosen direction (what depends on these CIs, what these CIs depend on, or both) to a chosen
depth. It lists affected CIs, business services, sites and an estimate of affected users, with
the path that reaches each. It opens from a CI and from incidents, problems, changes and
releases (REQ-CHG-082, REQ-REL-035).

- **Decision:** BETTER. ServiceDesk Plus has no impact view; the map must be read by hand.
- **Source:** sdp-area-07 §Behaviour (impact analysis: no dedicated page), §Weak spots (no impact-analysis view); architecture §2.12 (impact path by depth and direction); REQ-CHG-082
- **SDP weak spot fixed:** there is no dedicated impact-analysis view.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. For a database that two applications depend on, each used by one service, the
     "dependents" view at depth 2 lists both applications and both services with their paths.
  2. Changing the depth from 2 to 1 drops the services.
  3. A cycle in the relationships does not loop; each CI is listed once.
  4. On a CMDB of 100,000 CIs, depth 5 returns within 2 seconds at design load.

#### REQ-CMDB-011 — One impact service for every module

Incidents, problems, changes, releases, AI agents and reports get impact results from one
`cmdb` service interface, so the same question gives the same answer everywhere. Results only
include CIs the asking user may see, with the rest counted as restricted (REQ-CMDB-030).

- **Decision:** NEW.
- **Source:** architecture §6.1 (modules talk through service interfaces), §11.2 (one policy layer used by the API, search, realtime and AI)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. The change impact view and the CI impact view return the same services for the same CI,
     depth and direction.
  2. No other module queries CMDB tables (import-linter contract).

#### REQ-CMDB-012 — Live health from MonetX on CIs and maps

CIs monitored by MonetX show their current health and open MonetX problems on the CI page, the
relationship map, business views and impact views, read from the MonetX API, read-only, with a
link to open them in MonetX. The same panel is used on incidents (REQ-INC-145) and changes
(REQ-CHG-085).

- **Decision:** NEW. ServiceDesk Plus needs another monitoring product for this.
- **Source:** D-001; ADR-017; product-plan §5 (CMDB: impact maps with live health), §6 (topology-aware impact)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A business view with a CI that turns unhealthy in MonetX shows the new health on that
     node while the view is open.
  2. If MonetX cannot be reached, the map says health is unavailable and still works.
  3. SupportX makes only read calls to MonetX and stores no metrics (REQ-CHG-087).

#### REQ-CMDB-013 — Topology import from MonetX

The MonetX connector reads devices and their network links (for example from neighbour
discovery) from the MonetX API, read-only, on a schedule. Devices become or update CIs, and
links become relationships with source MonetX. Admins map MonetX device kinds to CI types and
link kinds to relationship types.

- **Decision:** NEW.
- **Source:** architecture §2.12 (population: MonetX topology import), §6.1 (monitoring_integrations: topology sync to CMDB); ADR-017; D-001; product-plan §5 (live CMDB fed by MonetX topology)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A MonetX link between two switches becomes one "connected to" relationship with source
     MonetX.
  2. A second import with no change writes no history.
  3. The connector makes no write call to MonetX (contract test).

#### REQ-CMDB-014 — Topology that disappears is marked, not deleted

When a device or link no longer appears in MonetX, its CI or relationship is marked stale,
then ended after a set number of imports (Appendix A), never silently deleted. Relationships
added by hand are never removed by an import.

- **Decision:** NEW.
- **Source:** architecture §2.12 (data quality: staleness); ADR-017
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A link missing from one import is marked stale; missing from three it is ended, with
     history.
  2. A hand-made relationship between two MonetX CIs survives every import.

---

## 25. Populating and reconciling the CMDB

#### REQ-CMDB-015 — Sync rules from assets and discovery

Sync rules decide which assets and discovered items become CIs of which type, and how their
fields map to CI attributes. A rule can be previewed before it is switched on, and each run
lists what it created and updated.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Config (CMDB: sync rules), §Fields (CI type: sync rules tab); architecture §2.12 (population: sync rules, field mapping)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A rule "servers become server CIs" previews the 40 servers it would sync before it is
     saved.
  2. A field change on a synced asset updates the CI attribute at the next run, with source
     "sync rule".

#### REQ-CMDB-016 — Source of every CI attribute

Each CI attribute and relationship records its source (hand, asset sync, discovery, MonetX,
import, integration) and when it was last set. Admins set which source wins per attribute, as
for assets (REQ-DSC-019).

- **Decision:** SAME.
- **Source:** architecture §2.12 (integration mapping showing each CI's source), §6.9 (record the source of every attribute)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Hovering an attribute shows its source and time.
  2. A MonetX import does not overwrite an attribute where "hand" wins.

#### REQ-CMDB-017 — Merge duplicate CIs

Users merge duplicate CIs with a preview of the surviving values, as for assets
(REQ-AST-052). Relationships, links to work items, downtimes and history move to the
survivor.

- **Decision:** BETTER.
- **Source:** architecture §2.12 (reconciliation and de-duplication)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Merging two CIs that both relate to the same service leaves one relationship, not two.
  2. Both CI IDs open the survivor afterwards.

#### REQ-CMDB-018 — Import CIs and relationships

CIs and relationships can be imported from CSV or XLSX, with the same mapping, dry run and
background job behaviour as asset imports (REQ-AST-053). Relationship rows name the two CIs by
a unique attribute.

- **Decision:** SAME.
- **Source:** sdp-area-11 §Fields (import modules: configuration items, CI relationships); sdp-area-14 §Screens (import data)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A relationship row naming a CI that does not exist is reported, not half-imported.
  2. Re-importing the same file creates no duplicates.

---

## 26. Links, downtimes and operations

#### REQ-CMDB-019 — Associations on a CI with counters

A CI shows its linked incidents, service requests, problems, changes, releases and contracts,
each with open and total counters, live, as for assets (REQ-AST-044). From a CI, users raise
an incident, service request or change with the CI filled in; every template the user may use
is offered, and the CI is attached even if the template has no CI field on its form.

- **Decision:** BETTER.
- **Source:** sdp-area-07 §Screens (CI right panel: association counters; CI actions: associations > create incident / service request / change), §Behaviour (CI create incident dialog showed no templates)
- **SDP weak spot fixed:** raising an incident from a CI offered no templates when no template
  had a CI field.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Raising an incident from a CI with the default template attaches the CI.
  2. Linking a contract raises the CI's contract counter, live.

#### REQ-CMDB-020 — CI downtime records

A CI has downtime records: scheduled, active and completed, each with type, start, end,
description and source. Planned and actual downtimes of changes create and update them
(REQ-CHG-063, REQ-CHG-064). Users with permission can also record an unplanned downtime by
hand or from an incident. The CI shows counts of scheduled, active and completed downtimes
and a downtime tab.

- **Decision:** BETTER. Unplanned outages can be recorded too, not only change downtimes.
- **Source:** sdp-area-07 §Screens (CI tabs: downtimes; right panel: downtime counts); architecture §2.12 (CI downtime records); REQ-CHG-064
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A change's planned downtime on a CI appears as scheduled on the CI, and becomes active at
     its start time without a refresh.
  2. Changing the change's downtime times updates the CI record.
  3. Recording an unplanned downtime from a major incident links the downtime and the incident.

#### REQ-CMDB-021 — Downtime that spreads to services

A downtime on a CI can be shown on the business services that depend on it, through the
impact relationships (REQ-CMDB-010), so service availability can be reported.

- **Decision:** NEW.
- **Source:** architecture §2.12 (impact analysis, CI downtime records); product-plan §6 (which services are affected)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A downtime on a database shows as an inherited downtime on the service above it.
  2. Service availability for a month is reported from these records (file 09).

#### REQ-CMDB-022 — Contracts on CIs

CIs can be linked to contracts (support, maintenance), and the CI page shows active contracts
and their expiry.

- **Decision:** SAME.
- **Source:** architecture §2.12 (operations: contract associations); sdp-area-07 §Screens (CI association counters: contracts)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A CI with an expired support contract shows the contract as expired.

#### REQ-CMDB-023 — Rules, triggers and notifications on CIs

Business rules, triggers, custom actions and notifications run on CI events (created, state
changed, relationship added or removed, downtime started), using the engines in file 03
(REQ-RUL-008, REQ-WF-031, REQ-NTF-008).

- **Decision:** SAME.
- **Source:** architecture §2.12 (operations: triggers and custom actions); sdp-area-12 §Screens (notification rules: CMDB tab)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A trigger "when a production server's state becomes maintenance, notify its owner" sends
     one notification per change.

---

## 27. Baselines, versions and data quality

#### REQ-CMDB-024 — CI version history

Every change to a CI's attributes or relationships creates a version. Users can view a CI as
it was at a past date and compare two versions.

- **Decision:** NEW. ServiceDesk Plus keeps a history list but no versions to view or compare.
- **Source:** architecture §2.12 (governance: CI version history)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Viewing a server as of last month shows the memory and relationships it had then.
  2. Comparing two versions lists added, removed and changed attributes and relationships.

#### REQ-CMDB-025 — Baselines

Users with permission create baselines: name, description, kind (by configuration, or by
business view), the CI type and criteria it applies to, and a preview of the CIs it will
capture. A baseline freezes those CIs' attributes and relationships at that time.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Screens (baseline configurations list), §Fields (new baseline configuration); sdp-area-11 §Fields (CMDB: create baselines, delete baselines permissions)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A baseline of "all production servers" captures exactly the CIs the preview showed.
  2. Only users with the create-baseline permission can create one; deleting needs the delete
     permission.

#### REQ-CMDB-026 — Compare against a baseline

A baseline can be compared with the current CMDB or with another baseline, listing CIs added,
removed and modified, with the attribute differences.

- **Decision:** SAME.
- **Source:** architecture §2.12 (governance: baselines with compare)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Adding memory to a server after the baseline shows it as modified with old and new
     values.
  2. A CI deleted after the baseline shows as removed.

#### REQ-CMDB-027 — Data quality policies and scores

Admins set data quality policies per CI type: required attributes (completeness), maximum age
since last update or scan (staleness), CIs with no relationships (orphans) and possible
duplicates. Each CI gets a score, and a CMDB dashboard shows scores and problems by type,
with lists to fix them.

- **Decision:** SAME.
- **Source:** architecture §2.12 (governance: data quality policies, per-CI scores, CMDB dashboard); sdp-area-07 §Fields (CI type: data quality tab); product-plan §6.1 (CMDB data-quality scoring)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A server missing two of four required attributes scores 50% completeness.
  2. Filling one attribute raises the score live.
  3. The orphan list shows every CI of the type with no relationships.

#### REQ-CMDB-028 — CMDB steward agent

An AI agent looks for stale, orphaned and duplicate CIs, using discovery and MonetX data, and
proposes fixes that a person approves. It acts through the same permissions as a user
(file 10).

- **Decision:** NEW.
- **Source:** product-plan §7.3 (agent library: CMDB steward); D-049
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. The agent proposes merging two CIs with the same serial number; nothing changes until a
     person approves.
  2. Every applied fix names the agent and the approver in history.

---

## 28. Access to assets and the CMDB

#### REQ-CMDB-029 — Fine-grained access for assets and CIs

Admins create fine-grained access rules for assets and for CIs. A rule names technicians or
groups and limits what they may see and change by product type or CI type, state, site, and
user attributes (for example only assets of their department), with optional advanced
criteria (field, operator, value). The rules apply everywhere through the one policy layer:
lists, record pages, search, pickers, maps, impact views, reports, exports, live events and AI.

- **Decision:** BETTER. One policy layer for every path, including live events and AI.
- **Source:** sdp-area-07 §Fields (new FGA for asset); sdp-area-11 §Screens (fine-grained access), §Fields (FGA form: asset and CMDB scopes); sdp-area-14 §Screens (fine-grained access: asset and CMDB only); architecture §2.11 (access by product type, state, site and user attribute), §2.12 (fine-grained CI access), §11.2
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A technician limited to printers sees only printers in the list, in global search, in the
     incident asset picker and in report results.
  2. That technician receives no live event about a laptop.
  3. A technician's page lists the fine-grained rules that apply to them.
  4. An API call for a hidden asset returns "not found", not "forbidden".

#### REQ-CMDB-030 — Restricted items on maps and impact paths

When a map or impact path passes through CIs the user may not see, they are shown as
"restricted item" placeholders with no name or attributes, so the path is not misleading and
nothing leaks.

- **Decision:** NEW.
- **Source:** architecture §11.2 (one policy layer); REQ-CMDB-010
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A service reached through a hidden database still shows in the impact list, with the
     database as a placeholder.
  2. The placeholder reveals no name, type or attribute in the API response.

#### REQ-CMDB-031 — CMDB permissions

Roles grant view, add, edit and delete on CIs, and separate permissions for CMDB
configuration (CI types, relationship types, sync rules), relationship management, and
creating and deleting baselines.

- **Decision:** SAME.
- **Source:** sdp-area-11 §Fields (role matrix: CMDB; advanced: create and delete baselines; roles CMDB admin and CMDB manager)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A role without relationship management sees no "add relationship" action, and the API
     refuses it.
  2. Only CMDB configuration can create CI types.

#### REQ-CMDB-032 — CMDB data for reports and dashboards

CIs, relationships, downtimes, baselines and data quality scores are available to the report
builder and dashboards (file 09), including a CI relationships report.

- **Decision:** SAME.
- **Source:** sdp-area-09 §Screens (report modules: CMDB, CI relationships); architecture §2.12 (CMDB dashboard)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A report of CIs by type and state matches the CMDB list counts.
  2. A report never includes CIs outside the user's fine-grained access.

---

## 29. Vendors and products for purchasing

#### REQ-PUR-001 — Vendors as first-class records

Vendors have their own list and page, not only a setup screen: name, currency, description,
contact person, address, email, phone, fax and website, and an active flag. The vendor page
shows the vendor's contracts, purchase orders, products and price list, licences and assets.
Users with permission can add a vendor inline from a contract, licence or PO form.

- **Decision:** BETTER. ServiceDesk Plus keeps vendors only under setup, with no page that
  shows what the vendor supplies.
- **Source:** sdp-area-07 §Navigation path (vendors only under setup and inline), §Fields (new vendor); sdp-area-11 §Fields (purchase: adding new vendor permission); architecture §2.11 (vendor catalogue); D-067 (products and vendors arrive in Stage 2 with assets)
- **SDP weak spot fixed:** vendors are hidden under setup.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A vendor's page lists its 3 contracts and 5 assets, each opening the record.
  2. An inactive vendor cannot be picked on new records but stays on old ones.
  3. Adding a vendor inline needs the "add vendor" permission.

#### REQ-PUR-002 — Purchase requests

A purchase request is an internal request to buy: requester, items (products, services or
free text) with quantities, needed-by date, reason, cost centre and site. It can be raised by
a technician, from a service request (for example a "new laptop" catalogue item), or by a
replenishment threshold (REQ-AST-035). After approval, one or more purchase orders are created
from it, and the request shows their progress.

- **Decision:** NEW. ServiceDesk Plus starts at the purchase order and links service requests
  only by attaching them.
- **Source:** architecture §2.11 (purchase requests and orders); sdp-area-07 §Screens (PO right panel: associate service requests)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Approving a purchase request with items from two vendors offers to create two POs, both
     linked to the request.
  2. The service request that started it shows the purchase request and PO status, live.
  3. Receiving all items marks the purchase request fulfilled.

#### REQ-PUR-003 — Vendor price lists and quote comparison

Each vendor can have a price list of products and services with price, currency, lead time
and validity. For a purchase request, buyers can record quotes from several vendors and
compare them side by side before choosing.

- **Decision:** NEW.
- **Source:** architecture §2.11 (vendor and product catalogues, price comparison)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Comparing three quotes shows unit price, total, lead time and validity in one table, in
     the tenant's base currency.
  2. Choosing a quote fills the PO with that vendor and prices.

#### REQ-PUR-004 — Purchasable services

Admins keep service types (for example training, labour, annual maintenance) and services
with part number and GL code. Services can be ordered on POs alongside products.

- **Decision:** SAME.
- **Source:** sdp-area-07 (7b) §7b.1 (service type, service, add service form); sdp-area-11 §Fields (purchase: adding new vendor service)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A disabled service cannot be added to a new PO.
  2. Receiving a service line creates no asset.

---

## 30. Purchase orders

#### REQ-PUR-005 — Purchase order record

A purchase order has a display ID (prefix and counter), name, template, required-by date,
site, vendor (with contact details), shipping address, billing address, currency, cost centre,
GL code (or per item), requested by, owner, remarks, terms, place, signing authority and
attachments. Required fields are enforced on every path.

- **Decision:** BETTER. Required fields are actually enforced.
- **Source:** sdp-area-07 §Fields (new purchase order), §Weak spots (shipping address marked required but not enforced); sdp-area-07 §Config (purchase defaults: PO prefix and start)
- **SDP weak spot fixed:** the shipping address was marked required but the PO saved without
  one.
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Saving a PO without a shipping address is refused by the UI and the API.
  2. The first PO in a new tenant is PO-1; the prefix can be changed by an admin.
  3. Choosing a vendor fills its contact details and currency.

#### REQ-PUR-006 — Items and totals

A PO has item lines: category (product, service, other), product type, product, part number,
unit price (from the product or price list), tax rate, quantity and amount, with optional cost
centre and GL code per line. Totals cover subtotal, discount (percentage or amount), shipping,
sales tax, additional tax, an adjustment and the total, with tax on shipping as a tenant
choice.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Fields (item grid, totals), §Config (purchase defaults: tax, tax on shipping), §Behaviour (PO total 6300)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Two items at 3,000 with 5% tax total 6,300, as a worked test.
  2. All money maths uses exact decimals and the currency's minor units.
  3. A product added to a PO line can be created inline only with the "add product"
     permission.

#### REQ-PUR-007 — PO statuses and life cycle

A PO moves through statuses with fixed meanings: open, waiting for approval, approved,
rejected, ordered, partly received, received, invoice received, paid, closed and canceled.
Transitions are allowed only as in Appendix A, on every path. Built-in views include all,
open, waiting for approval, approved, ordered, partly received, overdue, due in 7 and 30 days,
invoice received, paid, closed, canceled and trash.

- **Decision:** BETTER. Transitions are enforced and the views follow from statuses.
- **Source:** sdp-area-07 §Screens (PO list: 16 views), §Actions (PO actions vary by status), §Behaviour (purchase flow)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Ordering a PO that is still waiting for approval is refused.
  2. A PO past its required-by date and not fully received shows in "overdue", live.
  3. A received PO cannot be deleted; it can be closed.

#### REQ-PUR-008 — PO approvals with limits and segregation

A PO goes through approval stages with approvers by user, role or the requester's manager.
Approver limits apply: an approver can approve only up to their amount, and a larger PO needs
a higher approver. The PO owner and the requester cannot approve their own PO unless the
tenant explicitly allows it. Approvals work in the app, the mobile app and by email when mail
is set up, never depend on mail, and cannot be replayed (as REQ-CHG-045).

- **Decision:** BETTER. ServiceDesk Plus lets an owner approve their own PO and blocks
  "submit for approval" when mail is not configured.
- **Source:** sdp-area-07 §Automation (approval stages, PO owner as approver, approver limit), §Behaviour (owner approved own PO; submit blocked by missing mail server), §Weak spots (same-user approval); sdp-area-11 §Fields (purchase order approver flag); REQ-INC-083
- **SDP weak spot fixed:** a PO owner can approve their own PO; submitting for approval fails
  without a mail server.
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Under the defaults, the owner of a PO cannot approve it; the action shows the reason.
  2. A PO of 50,000 sent to an approver with a 10,000 limit escalates to the next stage
     approver.
  3. With no mail server, a PO can be submitted and approved in the app.
  4. An approval link used twice records one decision.

#### REQ-PUR-009 — Order and send to the vendor

Ordering a PO records the order date and can email the vendor a PDF of the PO in the vendor's
language. The PO keeps a conversation with the vendor and the owner (REQ-INC-057).

- **Decision:** SAME.
- **Source:** sdp-area-07 §Actions (order, email the vendor, email the owner), §Screens (PO detail: conversations)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Ordering with "email the vendor" sends one email with the PO PDF and records it in the
     conversation.
  2. A vendor reply to that email is added to the PO conversation.

#### REQ-PUR-010 — Receive items into assets, consumables and licences

Users receive PO items in full or in part: for each line, quantity and site, by hand or by
scanning barcodes. Receiving creates the matching records: an asset per unit (with product,
vendor, purchase cost, acquisition date, site, PO link and an asset tag), consumable stock, or
software licences. The tenant decides whether purchase cost includes tax.

- **Decision:** BETTER. Licences and consumables are received too, and tax handling is a
  tenant choice.
- **Source:** sdp-area-07 §Fields (receive items dialog: site, quantity, receive with barcode / QR code), §Behaviour (receiving created an asset in store with PO link), §Weak spots (purchase cost excludes tax); architecture §2.11 (delivery, reconcile received items into assets)
- **SDP weak spot fixed:** the purchase cost on received assets always left out tax.
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Receiving 1 of 2 laptops creates 1 asset in stock and sets the PO to partly received.
  2. With "cost includes tax" on, a 3,000 laptop at 5% tax gets a purchase cost of 3,150.
  3. Receiving a licence line creates a licence linked to the PO.
  4. A received asset later found by discovery merges with it, keeping the PO data
     (REQ-DSC-019).

#### REQ-PUR-011 — Invoices

A PO can have one or more invoices: invoice number, received date, payment due date,
amount, comments and attachments, with an optional payment reminder. The PO shows invoiced and
outstanding amounts.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Fields (add invoice), §Screens (PO detail: invoice tab), §Actions (add invoice)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Adding an invoice moves the PO to invoice received if it was received.
  2. An invoice due in 3 days with a reminder on notifies the owner.

#### REQ-PUR-012 — Matching order, receipt and invoice

Before payment, SupportX checks that invoiced quantities and prices match what was ordered and
received, within a set tolerance, and flags differences for a person to accept or dispute.

- **Decision:** NEW.
- **Source:** architecture §2.11 (invoices and payments, reconcile received items)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. An invoice for 3 units on a PO where 2 were received is flagged.
  2. Accepting a flagged invoice records who accepted it and why.

#### REQ-PUR-013 — Payments

A PO records payments: amount, date, comments and attachments, with an optional notification.
Partial payments are allowed; when the total paid equals the total invoiced, the PO moves to
paid.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Fields (add payment), §Screens (PO detail: payment tab), §Actions (add payment)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Two payments of 3,000 and 3,300 on a 6,300 invoice move the PO to paid.
  2. A payment above the outstanding amount asks for confirmation and a reason.

#### REQ-PUR-014 — Other PO actions

Users can duplicate a PO, cancel it with a reason (permission), delete it only before
ordering, add notes, print or save as PDF, and link service requests, changes and contracts
to it, recorded on both sides.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Actions (PO actions: duplicate, cancel, add note, email), §Screens (associate service requests and contracts), §Behaviour (delete button disappears after receiving); sdp-area-11 §Fields (purchase: cancel purchase order); REQ-CHG-079
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Duplicating a PO copies vendor and items into a new open PO with a new number.
  2. Delete is disabled with a reason once a PO is ordered.
  3. Linking a PO to a service request shows the PO on the request.

#### REQ-PUR-015 — Purchase defaults, templates and closure rules

Admins set purchase defaults: tax rate, signing authority, tax on shipping, default shipping
and billing addresses, cost centre, approvers, terms, remarks, display prefix and start
number. Closure rules say what must be done before a PO can close (for example all items
received and all invoices paid). PO templates set the form layout and default values.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Config (purchase management default values), §Fields (PO template), §Behaviour (PO template editor not covered); sdp-area-14 §Screens (closure rules: purchase order tab)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A new PO is filled with the default addresses and terms.
  2. Closing a PO with an unpaid invoice is refused under the default closure rule.

#### REQ-PUR-016 — PO notifications

Purchase events notify chosen recipients through the notification engine (REQ-NTF-008):
submitted for approval, approved, rejected, ordered, due soon, overdue, received, invoice due
and paid.

- **Decision:** SAME.
- **Source:** sdp-area-12 §Screens (notification rules: purchase tab); sdp-area-07 §Automation (mail notification checkboxes in approve and order dialogs)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A PO overdue by one day notifies its owner once.
  2. With mail not configured, the in-app notification still arrives (REQ-INC-060).

---

## 31. Cost centres, budgets and currency

#### REQ-PUR-017 — Cost centres and GL codes

Admins keep cost centres and GL codes. POs, items, assets and contracts carry them. Each can be
switched off for new use without changing old records.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Config (purchase management: cost center tab, GL code tab), §Fields (PO cost center, GL code, item level); sdp-area-11 §Fields (import: GL code, cost center); architecture §2.11 (cost centres, GL codes)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. An inactive cost centre is not offered on new POs and stays on old ones.
  2. Reports total spend by cost centre across POs.

#### REQ-PUR-018 — Budgets per cost centre

Admins set budgets per cost centre and period. Approved POs count as committed and invoices as
spent. A PO that would exceed the remaining budget is warned or blocked, as the tenant
chooses, and the cost centre shows budget, committed, spent and remaining.

- **Decision:** NEW. ServiceDesk Plus has cost centres but no budgets.
- **Source:** architecture §2.11 (financials: cost centres); product-plan §5 (purchase and contracts)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A 6,000 PO against a cost centre with 5,000 remaining warns the approver, or is refused
     in "block" mode.
  2. Approving a PO raises the committed amount live.

#### REQ-PUR-019 — Currencies

Vendors, POs, contracts and licences can use any currency the tenant has set up. Amounts are
stored in their own currency and in the base currency at the rate of the day, so reports add
up in one currency.

- **Decision:** BETTER. ServiceDesk Plus shows PO and contract currency read-only from the
  vendor.
- **Source:** sdp-area-07 §Fields (contract cost: currency read-only; vendor currency; PO currency read-only); sdp-area-14 §Screens (currency page, exchange rates); architecture §2.15 (multi-currency)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A PO in euros shows its total in euros and in the base currency.
  2. A later change of exchange rate does not change the stored base amount of a past PO.

#### REQ-PUR-020 — Purchase permissions and data

Roles grant view, add, edit and delete on purchases, plus adding products, vendors and vendor
services, cancelling POs and approving POs. Purchase data is available to reports and
dashboards (file 09) and can be imported (REQ-AST-053).

- **Decision:** SAME.
- **Source:** sdp-area-11 §Fields (role matrix: purchase; advanced purchase permissions; purchase order approver; role purchase config); sdp-area-09 §Screens (purchase reports, canned purchase dashboard)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A role without "cancel PO" sees the action disabled with a reason.
  2. The purchase dashboard counts update live when a PO changes status.

---

## 32. Contracts

#### REQ-CON-001 — Contract record

A contract has a display ID (prefix and counter), template, name, vendor, term (fixed or open
ended), parent contract, cost, owner (the creator by default), type, active period, sites,
support details, comments, attachments, and the assets, CIs, licences and purchase orders it
covers. A contract can be saved as a draft.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Fields (new contract, buttons save and save draft), §Screens (contract detail right panel), §Behaviour (contract CON-7 active, linked to asset); sdp-area-07 §Config (contract management: ID prefix, starts from); architecture §2.11 (contracts with documents)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A contract needs a name, vendor, term, owner and active period; a fixed-term contract
     needs an end date after its start.
  2. Linking an asset shows the contract on the asset's contracts tab, live.
  3. The first contract in a new tenant is CON-1.

#### REQ-CON-002 — Contract types

Admins keep contract types with a colour, for example maintenance, lease, support, warranty
and software. Seed types are in Appendix A.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Config (contract type list with colours)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Contract lists show the type with its colour and label.
  2. A type in use cannot be deleted.

#### REQ-CON-003 — Contract statuses and views

Contracts have statuses with fixed meanings: draft, active, expired, renewed and canceled.
Built-in views include all, active, expiring soon, expired, expired in the last 7 days, all
including renewed, and trash. Status changes at the start and end dates happen automatically.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Screens (contract list views)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A contract whose end date passes becomes expired at midnight in the tenant's time zone,
     with a history entry marked automatic.
  2. The "expired in the last 7 days" view gains the contract without a refresh.

#### REQ-CON-004 — Cover many assets and licences

A contract can cover any number of assets, CIs and licences, picked one by one, by filter or
by asset group, or imported. Each covered item shows the contract.

- **Decision:** BETTER. ServiceDesk Plus caps a contract at 100 assets and 100 licences.
- **Source:** sdp-area-07 §Fields (associated assets max 100, software licences max 100), §Screens (associations tab: assets, software licences, purchase orders)
- **SDP weak spot fixed:** a contract can cover at most 100 assets.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Adding a dynamic asset group of 2,500 laptops to a contract covers all of them.
  2. The contract page pages through covered items without loading them all at once.

#### REQ-CON-005 — Parent and child contracts

A contract can have child contracts, for example one framework agreement with yearly
orders. The parent shows its children with status and cost; a child shows its parent.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Fields (parent contract), §Actions (select parent, associate child), §Screens (contract relationship); architecture §2.11 (parent and child contracts)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A contract cannot be the parent of its own parent.
  2. The parent shows the total cost of its children.

#### REQ-CON-006 — Expiry notifications and renewal requests

A contract can notify chosen users and email addresses at several lead times before expiry
(Appendix A), and can also create a renewal request at a set lead time from a chosen template.
Both can be on together.

- **Decision:** BETTER. ServiceDesk Plus greys out "create request before expiry" while
  expiry notifications are on.
- **Source:** sdp-area-07 §Fields (expiry notification: users, emails max 10, notify before up to 10 rows; create request before expiry greyed out), §Automation (expiry notification emails, auto-created request), §Config (contract expiry request template); architecture §2.11 (expiry alerts)
- **SDP weak spot fixed:** notifications and an auto-created renewal request cannot be used
  together.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. With lead times 60, 30 and 7 days, the owner gets three notifications, one at each.
  2. With both on, the renewal request is created at its lead time and linked to the contract.
  3. Renewing the contract before a lead time cancels the remaining notifications.

#### REQ-CON-007 — Renew a contract

Renewing records the new period, cost and any changed terms as a renewal, keeps the previous
periods in a renewals tab, and keeps covered items unless the user removes some.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Actions (renew), §Screens (contract tabs: renewals; views: all including renewed); architecture §2.11 (renewals)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Renewing a contract for one more year shows two periods in the renewals tab with their
     costs.
  2. Covered assets stay linked after renewal.

#### REQ-CON-008 — Auto-renewal

A contract can renew itself at expiry for a set period (for example 12 months), notifying
chosen users before and after.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Fields (auto-renewal: users, prolongation), §Automation (auto-renewal); architecture §2.11 (auto-renewal)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. An auto-renewing contract ending today has a new period of 12 months tomorrow, with a
     history entry marked automatic.
  2. Switching auto-renewal off before the end date stops it.

#### REQ-CON-009 — Contract usage

A contract can hold entitlements, for example support hours or call-outs, and records their
use from linked work items and worklogs, showing used and remaining.

- **Decision:** BETTER. Use is fed from linked work, not typed by hand.
- **Source:** sdp-area-07 §Screens (contract tabs: contract usage); architecture §2.11 (usage tracking)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A worklog of 2 hours on an incident linked to a 40-hour support contract shows 38 hours
     remaining.
  2. Reaching 80% use notifies the contract owner.

#### REQ-CON-010 — Contracts used on work items

A work item can name the contract under which a vendor was engaged. The contract lists the
work items that invoked it, and the vendor contract targets can be tracked (REQ-SLA-034).

- **Decision:** SAME.
- **Source:** sdp-area-07 §Behaviour (request associations: invoked contracts); REQ-SLA-034
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Linking a contract to an incident shows the incident on the contract, with history on
     both.
  2. The contract picker offers only active contracts that cover the incident's assets or CIs
     first.

#### REQ-CON-011 — Conversations, notes and history on contracts

Contracts have notes, a conversation with the owner and the vendor (email the owner, email
the vendor), attachments and full history, as on work items (REQ-INC-057, REQ-INC-061,
REQ-INC-079, REQ-WI-003). Contracts can be printed or saved as PDF (REQ-INC-126).

- **Decision:** SAME.
- **Source:** sdp-area-07 §Actions (add note, email the owner, email the vendor), §Screens (contract tabs: conversations, history; detail toolbar: print)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Emailing the vendor records the message in the contract conversation.
  2. Changing the cost writes a history entry with old and new values.

#### REQ-CON-012 — Cancel and delete contracts

A user with the cancel permission cancels a contract with a reason; its notifications and
auto-renewal stop. Delete moves a contract to trash.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Actions (contract actions: delete, cancel); sdp-area-11 §Fields (contracts: cancel contract)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Canceling needs a reason and the permission.
  2. A canceled contract sends no further expiry notifications.

#### REQ-CON-013 — Contract templates

Admins create contract templates that set the form layout, default values and default
notification settings for a contract type.

- **Decision:** SAME.
- **Source:** sdp-area-07 §Fields (contract template), §Behaviour (contract template editor not covered)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A warranty template sets the type to warranty and lead times of 90 and 30 days.

#### REQ-CON-014 — Contract documents with versions

Contract documents (the signed agreement, amendments) are kept with versions: uploading a new
version keeps the older ones, with who uploaded and when.

- **Decision:** BETTER.
- **Source:** architecture §2.11 (contracts with documents)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Uploading an amendment as a new version keeps version 1 downloadable.

#### REQ-CON-015 — Contract permissions, notifications and data

Roles grant view, add, edit and delete on contracts, plus contract configuration and
cancelling. Contract events notify through the notification engine (REQ-NTF-008). Contracts
are available to reports and dashboards (file 09), and can be imported.

- **Decision:** SAME.
- **Source:** sdp-area-11 §Fields (role matrix: contract; role contract config); sdp-area-12 §Screens (notification rules: contract tab); sdp-area-09 §Screens (contract reports, canned contract dashboard); sdp-area-11 §Fields (import: contracts)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A role with view-only on contracts cannot renew or cancel, and the API refuses it.
  2. A report of contracts expiring next quarter by vendor matches the contract list.

#### REQ-CON-016 — Customer contracts for managed service providers

Contracts with customer organisations, with their SLAs (REQ-SLA-035) and billing, belong to
the MSP capability and are not built in this module at V1. The contract record here covers
vendor contracts only.

- **Decision:** SKIP. Customer contracts and billing come with MSP multi-tenancy (Enterprise,
  Stage 3); building them inside vendor contracts would mix two different things.
- **Source:** architecture §2.15 (MSP: contracts and billing), §17 (Stage 3: MSP billing); REQ-SLA-035; D-063 (MSP is LATER, no parity file yet)
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. The vendor contract form offers no customer billing fields.
  2. MSP customer contracts are specified with MSP billing (file 12 or a later file).

#### REQ-CON-017 — Custom fields on procurement and licence records

Admins add custom fields to contracts, vendors, purchase orders, licences and licence
agreements, as for work items (REQ-INC-014). The fields appear on forms, in views, filters,
exports and reports.

- **Decision:** SAME.
- **Source:** sdp-area-13 §Screens (additional fields module list: purchase, contract, licence, agreement, vendor), §Limits (asset, CMDB, purchase and contract customisation not opened); architecture §6.6
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A custom "framework agreement number" field on contracts can be filtered on in a view and
     exported.
  2. A custom field key is never shown to users; its label is.

---

## Appendix A — Proposed defaults

These are the defaults a new tenant gets, proposed for product owner approval. They are seed
data, not fixed behaviour: **a tenant admin can change every one of them** (D-041). Names are
our own; they become labels in English and Arabic (Urdu from V1). The requirements above refer
to this appendix.

**Display IDs** (REQ-AST-008, REQ-AST-030, REQ-PUR-002, REQ-PUR-005, REQ-CON-001): asset tag
pattern `AST-{n}` for all product types; loans `LN`; asset audits `AUD`; purchase requests
`PR`; purchase orders `PO`; contracts `CON`. Each has its own per-tenant counter starting at 1.

**Product type tree** (REQ-AST-003):

| Branch | Product types | Kind |
|---|---|---|
| IT | Computer > Workstation, Laptop, Server, Virtual host, Virtual machine | asset |
| IT | Mobile device > Phone, Tablet | asset |
| IT | Network device > Router, Switch, Firewall, Wireless access point | asset |
| IT | Printer, Storage device, IP phone | asset |
| Non-IT | Furniture, Projector, Office equipment, Vehicle | asset |
| Components | Monitor, Keyboard, Mouse, Docking station, Memory module, Disk | component |
| Consumables | Toner and ink, Cables, Paper, Batteries | consumable |

**Asset states and transitions** (REQ-AST-012, REQ-AST-013):

| State | Category | Reason needed to enter |
|---|---|---|
| In stock | in stock | no |
| In use | in use | no |
| On loan | in use | no (set by loans) |
| In repair | in repair | yes |
| Missing | retired | yes |
| Retired | retired | yes |
| Disposed | disposed | yes, with the disposal record (REQ-AST-017) |

| From | To |
|---|---|
| In stock | in use, on loan, in repair, missing, retired |
| In use | in stock, on loan, in repair, missing, retired |
| On loan | in stock (return), in repair (return to repair), missing |
| In repair | in stock, in use, retired |
| Missing | in stock, in use, retired |
| Retired | in stock (permission), disposed |
| Disposed | none |

**Assets:**

- copy limit: 50 copies per action (REQ-AST-010);
- asset age basis: acquisition date; format: years, months and days (REQ-AST-011);
- after unassignment the asset goes to "In stock" (REQ-AST-015);
- site follows the owner: off (REQ-AST-018);
- auto-assign from logins: off; when on, 2 consecutive scans (REQ-AST-021);
- acknowledgement: off; when on, for computers and mobile devices, reminder after 3 days
  (REQ-AST-023);
- requester's own assets only on portal forms: on; include assets on email incidents: off
  (REQ-AST-025);
- warranty expiring view: 90 days ahead (REQ-AST-062);
- scan history kept for 6 months (REQ-AST-054);
- overdue-scan action: off; when switched on, the proposed rule is "not scanned for 60 days:
  move to Missing" (REQ-AST-056);
- depreciation: none until configured; when configured, straight line over 3 years with no
  salvage value (REQ-AST-037).

**Asset notifications on by default** (REQ-AST-059): acknowledgement request to the user;
loan due (1 day before) and loan overdue (once) to the borrower and the loan creator; warranty
expiring in 30 days to the asset managers; stock below threshold to the configured recipients;
prohibited software found to the asset managers (REQ-SAM-018).

**Discovery** (REQ-DSC-002, REQ-DSC-004, REQ-DSC-005, REQ-DSC-018):

- agent: full inventory at first start, then changes every 24 hours and at each restart;
  footprint target under 1% average CPU, under 100 MB memory and under 200 MB disk;
- network and domain scans: weekly, Sunday 02:00 site time, when created;
- a probe counts as offline after 30 minutes without contact;
- identification order: serial number, then SMBIOS UUID, then MAC address plus host name;
- matching by MAC address: on; computer name format: host name only;
- placeholder serial numbers ignored for matching: "To Be Filled By O.E.M.", "Default string",
  "System Serial Number", "0", "None", "0123456789", "1234567890", "SERIALNUMBER";
- create product types for unknown SNMP devices: off (REQ-DSC-010);
- source precedence: agent and probe for hardware and software; directory for owner and
  department; purchase order for cost, vendor and acquisition date; hand-entered values are
  protected (REQ-DSC-019).

**Software types** (REQ-SAM-002): Managed (managed), Prohibited (prohibited), Freeware
(freeware), Shareware (shareware), Not tracked (excluded), Unclassified (unidentified).

**Software categories** (REQ-SAM-003): operating system, office and productivity,
development, database, security, browser and internet, graphics and media, communication,
utility, game, other.

**Licence types** (REQ-SAM-009):

| Licence type | Tracked by | Installations | Perpetual |
|---|---|---|---|
| Single | computer | one | yes |
| Volume | computer | as bought | yes |
| Site-wide perpetual | computer | unlimited | yes |
| Site-wide subscription | computer | unlimited | no |
| Bundled with hardware (OEM) | computer | one, tied to the machine | yes |
| Client access | user or device | as bought | yes |
| Concurrent | user | peak concurrent use | yes |
| Machine-locked | computer | one | yes |
| Named user | user | one per user | yes |
| Subscription per user | user | one per user | no |
| Trial | computer | as bought | no |

**Licence and agreement expiry notifications** (REQ-SAM-019): 60, 30 and 7 days before
expiry, to the licence owner.

**CI types** (REQ-CMDB-001): Business service, IT service, Application, Database, Web site,
Server (Physical server, Virtual machine), Cluster, Network device (Switch, Router, Firewall,
Load balancer, Wireless access point), Storage, Cloud resource, Data centre, Rack, Document.

**CI states** (REQ-CMDB-003): Operational (active, default), Under maintenance (active), Not
operational (active), Decommissioned (end of life). End-of-life CIs are left out of pickers.

**Relationship types** (REQ-CMDB-006):

| Name | Inverse name | Carries impact |
|---|---|---|
| depends on | used by | yes |
| runs on | hosts | yes |
| connected to | connected to | yes |
| part of | contains | yes |
| virtualised by | virtualises | yes |
| backed up by | backs up | no |
| located in | houses | no |
| managed by | manages | no |

**Impact view** (REQ-CMDB-010): direction "what depends on these CIs", depth 3.

**MonetX topology** (REQ-CMDB-013, REQ-CMDB-014): import every hour; a missing device or link
is marked stale at the first missing import and ended after 3 missing imports.

**Data quality** (REQ-CMDB-027): stale after 30 days without an update or scan.

**Contract types** (REQ-CON-002): Maintenance (blue), Support (teal), Lease (purple), Warranty
(green), Software subscription (orange).

**Contracts** (REQ-CON-006, REQ-CON-008): expiry notifications at 60, 30 and 7 days to the
owner; renewal request off; auto-renewal off.

**Purchase order statuses and transitions** (REQ-PUR-007):

| From | To |
|---|---|
| open | waiting for approval, canceled |
| waiting for approval | approved, rejected, open (withdraw) |
| rejected | open (edit and resubmit), canceled |
| approved | ordered, canceled |
| ordered | partly received, received, canceled (permission) |
| partly received | received |
| received | invoice received, closed |
| invoice received | paid |
| paid | closed |

**Purchasing** (REQ-PUR-006, REQ-PUR-008, REQ-PUR-010, REQ-PUR-015, REQ-PUR-018): tax rate 0%;
tax on shipping off; purchase cost includes tax: off; one approval stage by the requester's
manager; owner and requester may not approve their own PO; approver limits off; close only
when all items are received and all invoices are paid; budget mode "warn".

**Imports** (REQ-AST-053): no row limit; files up to 50 MB; mode "add and update".

---

## Open questions for the product owner

1. **MVP scope.** ITAM, discovery and the CMDB are Stage 2 (architecture §17), so this file
   has no MVP items. Does the design-partner customer (D-042) need a basic asset register at
   MVP?
2. **Contracts, vendors and products before procurement.** architecture §2.11 lists contracts
   under ITAM (Stage 2), but §6.1 puts vendors, products and contracts in the `procurement`
   module and §17 schedules procurement for Stage 3. product-plan §5 says "vendor and contract
   management first". This file makes vendors, the product catalogue and the basic contract
   record V1 and purchasing LATER. Confirm, and confirm that the `procurement` module starts
   at Stage 2 with these parts only.
   *Answered:* D-067: vendors, the product catalogue and basic contracts move to Stage 2 with
   assets (V1); purchase orders stay Stage 3. architecture.md §17 updated.
3. **Editions.** The plan places ITAM and the CMDB in Professional but does not place
   purchasing, contracts or discovery. This file proposes Professional for all. Should
   purchasing (POs, invoices, budgets) be Enterprise, and is `discovery` (a separate feature
   in architecture §13.1) included in Professional or sold as an add-on?
4. **What counts as a managed asset.** Proposed: every IT and non-IT asset that is not
   disposed; components, consumables and software do not count (REQ-AST-002). ServiceDesk Plus
   counts IT assets only. Should non-IT assets count?
5. **Probes and agents unlimited.** ServiceDesk Plus licenses probes separately. We propose no
   probe or agent limit, only the managed asset limit (REQ-DSC-028). Confirm.
6. **Discovery agent (ADR-015) and remote control (ADR-016)** are still open. REQ-DSC-002 and
   REQ-AST-057 depend on them. A new Go agent needs approval of Go for the stack.
7. **MonetX API contract.** REQ-DSC-017 (device inventory), REQ-CMDB-012 (health) and
   REQ-CMDB-013 (topology) need a read-only MonetX API for devices, links and health
   (ADR-017 consequence). Which MonetX version provides it, and when?
8. **Purchase cost and tax.** Should a received asset's purchase cost include tax by default
   (REQ-PUR-010)? Proposed: off, because recoverable tax is usually not part of an asset's
   value.
9. **Software metering and privacy.** Usage metering (REQ-SAM-016) records when each user
   runs which program. Is this acceptable in the target markets, and should it need an
   explicit tenant opt-in?
10. **Cloud discovery timing.** product-plan Appendix B rates cloud discovery P1, while this
    file makes it LATER (REQ-DSC-014) with Stage 2 focused on agent, probe, directory and
    MonetX sources. Confirm.
11. **Baselines V1, data quality LATER.** Baselines and compare are V1 (common in tenders);
    data quality scores and the CMDB steward agent are LATER. Confirm.
