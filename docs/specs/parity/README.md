# Parity requirements: index

This folder is the requirements contract that every feature work package is built and tested
against. It turns the ServiceDesk Plus research (`docs/specs/reference/`) and our own specs
(architecture.md, product-plan.md, ADRs, `docs/DECISIONS.md`) into numbered, testable
requirements, one file per module.

Order of authority, as everywhere in this repo: product owner decisions (`DECISIONS.md`), then
architecture.md, then product-plan.md. A requirement that conflicts with them is wrong and must
be fixed here. The reference notes are input, not authority.

**Status:** Phase 2, 2026-10-24. Module 01 is updated with the product owner's answers
(D-039 to D-050); the other modules are added in batches, in build order. The module list was
regrouped into twelve files by the product owner in Phase 2. **Owner:** Haider (Product Owner).

## Modules in build order

The order follows architecture.md §17 and the dependencies between modules. The work item
engine comes first, because every ticket-like module reuses it (architecture.md §6.2).

| # | File | Module | ID prefixes | Draws on reference areas | Requirements (MVP / V1 / LATER) |
|---|---|---|---|---|---|
| 01 | [01-work-items-incidents.md](01-work-items-incidents.md) | Work item engine and incidents | WI, INC | 01, 02a, 02b, 02c (main); 03, 04, 05, 06, 07, 08, 10, 11, 12, 13 (cross-references) | **176** (84 / 76 / 16) |
| 02 | [02-service-requests-catalog-portal.md](02-service-requests-catalog-portal.md) | Service requests, service catalog, requester portal | SR, CAT, PRT | 03, 02a-c, 12, 13 (requester portal, approval settings), 10 and 14 (chatbot entry) | **127** (60 / 51 / 16) |
| 03 | [03-sla-assignment-rules-workflows-notifications.md](03-sla-assignment-rules-workflows-notifications.md) | SLA and OLA, operating hours, auto-assignment, business rules, triggers and schedules, custom actions, life cycles and visual workflows, notification engine | SLA, ASG, RUL, WF, NTF | 12 (incl. 12b), 13, 11 (sites, operating hours), 02c, 14 (custom functions) | **146** (60 / 73 / 13) |
| 04 | [04-problems.md](04-problems.md) | Problem management, known errors | PRB | 04, 10 (cluster analysis), 08 (problem solutions), 14 (closure rules) | **81** (0 / 74 / 7) |
| 05 | [05-changes.md](05-changes.md) | Change enablement, CAB, calendar, freeze windows | CHG | 05 (incl. 5b), 07b (asset links), 12 (change templates), 14 (closure rules) | **118** (0 / 100 / 18) |
| 06 | [06-releases-projects.md](06-releases-projects.md) | Release management; projects, milestones, Gantt, timesheets | REL, PRJ | 06 (incl. 6b) | **112** (0 / 54 / 58) |
| 07 | [07-assets-cmdb-software-purchase-contracts.md](07-assets-cmdb-software-purchase-contracts.md) | Assets, discovery, software and licences, CMDB, purchase, contracts, vendors | AST, DSC, SAM, CMDB, PUR, CON | 07 (incl. 7b), 11 and 14 (fine-grained access), 14 (probes and discovery) | **183** (0 / 145 / 38) |
| 08 | [08-knowledge.md](08-knowledge.md) | Knowledge base | KB | 08, 10 (solution assist and generator), 03, 04 | **93** (38 / 50 / 5) |
| 09 | [09-reports-dashboards.md](09-reports-dashboards.md) | Reports, dashboards, visual query builder, wallboards | RPT, DSH | 09, 01 (home dashboards, widgets), 10, 11, 13, 14 | **116** (40 / 61 / 15) |
| 10 | 10-ai.md | AI gateway, AI administration, agents, chatbot, MCP | AI | 10, 14 (agents, chatbot, AI providers) | not yet written |
| 11 | 11-admin-users-security-audit.md | Users, roles, groups, sites, customisation, settings, mail, surveys, data administration, login and MFA, security, audit | ADM, SEC, AUD | 11, 13, 14, 01 (preferences, navigation) | not yet written |
| 12 | 12-integrations-esm.md | Connectors (MonetX read-only, email, Teams, Slack, DevOps, identity ...), webhooks, API, extensions; enterprise service management (department desks, HR, facilities) | INT, ESM | 14 (integrations, ESM), 13 (mail), 12 (webhooks), 10 (AI providers), 03 (ESM portal); architecture §2.14, §2.15 | not yet written |

Notes on the table:

- **Where a capability lives.** A capability lives in the file of the module that owns it
  (architecture.md §6.1). Other files only refer to its ID. Examples: notes, tasks, worklogs,
  links and merge are engine features (REQ-WI and REQ-INC in file 01); problems and changes
  list only how they differ. The SLA engine is in file 03; file 01 says only how an incident
  uses it. The approval engine (stages, parallel and conditional approvers, delegation,
  backups, reminders, safe one-time email links) is specified once in file 02 (REQ-SR-021 to
  REQ-SR-039) and built in the engine; incidents, changes and releases reuse it. The
  notification engine is file 03 (REQ-NTF-*); each module lists only its own events. Stages
  that group statuses (changes, releases) are one engine model (REQ-WI-026).
- **Gaps in the research.** Area 14 (data administration, integrations, ESM instances) is in
  `docs/specs/reference/` (D-039). Area 15 (multi-user assignment, requester-side views) is
  not there yet. ESM has no research area of its own beyond Area 14's instance and directory
  screens; file 12 relies on architecture.md §2.15 for it.
- **Counts** for each file are kept in that file's summary table, which is the source of
  truth. This index repeats them when a file is added or changed.

## ID scheme

- **Format:** `REQ-<PREFIX>-<NNN>`, for example `REQ-INC-001`. `NNN` is three digits with
  leading zeros and counts from 001 in each prefix.
- **Prefixes** are listed in the module table. `REQ-WI-*` holds engine-wide requirements that
  apply to every work item type. Every other prefix is module-specific.
- **IDs are permanent.** A requirement is never renumbered and its ID is never reused. A
  dropped requirement stays in its file, marked `Withdrawn` with a reason. A new requirement
  takes the next free number in its prefix, even if it belongs in an earlier section.
- **Referencing:** work packages, ADRs, commits, PRs and tests cite requirement IDs. A
  requirement cites another by ID, never by section number.

## What each requirement contains

| Field | Rule |
|---|---|
| **ID and title** | As above. The title says what the product does, in a few words. |
| **Statement** | What the product must do, in plain English and our own words. It describes the outcome for the user, not ServiceDesk Plus's screens. |
| **Decision** | `SAME`: parity, the same capability and outcome. `BETTER`: parity plus our improvement, and the requirement says what and why. `NEW`: ServiceDesk Plus lacks it. `SKIP`: deliberately not built, and the requirement says why and what replaces it. |
| **Source** | Where it comes from. A reference file and section, for example `sdp-area-02c §Actions`, or `architecture §6.5`, `product-plan §7.3`, `ADR-017`, `D-001`. Section short names: §Screens, §Fields, §Actions, §Config, §Automation, §Behaviour, §Edition notes, §Weak spots (the "Weak spots / confusing UX" list), §Limits. Follow-up parts are written in brackets: `sdp-area-12 (12b) §Behaviour`. |
| **SDP weak spot fixed** | Only when the requirement fixes one: the research finding, briefly, in our own words. |
| **Priority** | `MVP`: needed for the Stage 1 internal go-live (architecture.md §17) plus one design-partner customer (D-042). `V1`: needed for the first external release and a standard ITSM tender. `LATER`: after V1. |
| **Edition** | The lowest edition that includes it: `Essentials`, `Professional` or `Enterprise` (product-plan.md §9). Higher editions include everything below. Editions are enforced only through the entitlement interface (CLAUDE.md §5f). Features outside a tenant's edition show disabled with an upgrade hint, or are hidden if the admin chooses (D-044, REQ-WI-025). |
| **Acceptance criteria** | Two to five numbered, testable statements. Each becomes at least one automated test (see below). |

### Acceptance criteria become tests

- Tests name the criterion they prove. Python:
  `test_req_inc_046_ac1_api_refuses_disallowed_transition`. Playwright:
  `test('REQ-INC-046 AC1: ...')`.
- A requirement is done only when every one of its criteria has a passing test at the right
  layer (CLAUDE.md §9), or the work package report explains why a criterion cannot be tested
  yet.
- Changing a criterion is a change to the contract. It goes through a PR that updates the
  requirement and its tests together.

## Rules for every module file

**Writing**

1. **Own words only.** Describe capabilities and outcomes. Never copy ServiceDesk Plus's UI
   text, labels, help text, screen layouts, icons or artwork (architecture.md §2, CLAUDE.md §2).
   Value lists from the research are examples, not seed data.
2. **Cover everything.** Every capability ServiceDesk Plus has in the module must appear:
   fields, actions, statuses, views, filters, bulk actions, notes, worklogs, tasks, checklists,
   attachments, linking, merge, history, print, templates and notifications. Our own
   requirements from product-plan.md and architecture.md belong there too. A capability we will
   not build is a `SKIP` with its reason. It is never left out silently.
3. **Monitoring stays out.** No device monitoring, polling, alert correlation or
   de-duplication (ADR-017, D-001). Only the MonetX connector (receive problems, read health,
   problems and topology read-only) and the generic alert webhook are in scope.
4. **Open questions** for the product owner go at the end of each module file.
5. **Defaults are seed data.** Each file lists its proposed tenant defaults in an appendix.
   Every default must be editable per tenant by an admin (D-041).

**Cross-cutting lessons from the research.** Every module applies these. The engine
requirements in file 01 implement them once:

| Lesson | Implemented by |
|---|---|
| No silent failures: every action shows its outcome, and background failures show on the record | REQ-WI-009, REQ-INC-059, REQ-INC-060 |
| Fixed menus and tabs: actions keep their place; unavailable ones are disabled with a reason | REQ-WI-010, REQ-WI-011 |
| Status changes only through allowed transitions, on every path | REQ-INC-046, REQ-INC-052 |
| Reasons on status changes | REQ-INC-047 |
| Field history with who, when, old, new, source and reason, on both sides of every link | REQ-WI-003, REQ-WI-004 |
| Live updates on every screen, no refresh | REQ-WI-005 |
| A priority matrix that ships filled in with sensible defaults | REQ-INC-009, REQ-INC-011 |
| Closing is warned or blocked while tasks, checklists or approvals are open | REQ-INC-095 |
| Assignment moves the status sensibly | REQ-INC-050, REQ-INC-054 |
| One date and time formatter, in the user's time zone | REQ-WI-014 |
| Labels, never raw codes; English and Arabic (Urdu from Stage 2) with right-to-left | REQ-WI-013, REQ-INC-133 |
| Stable layout: nothing moves under the pointer while typing | REQ-WI-012 |
| No duplicate records from double clicks or retries | REQ-WI-008 |

**Platform rules** apply to every requirement even when they are not repeated: tenant
isolation with RLS, the transactional outbox, optimistic concurrency, the entitlement
interface, permission checks in one policy layer, and the API conventions (CLAUDE.md §5–§8).
