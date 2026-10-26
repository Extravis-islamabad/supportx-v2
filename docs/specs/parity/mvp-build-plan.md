# MVP build plan

Maps every MVP requirement in the parity files (after the Area 15 updates and decisions
D-057 to D-068) to one work package, in build order. MVP is the Stage 1 internal go-live plus
one design-partner customer (D-042), both on-prem on a single node (D-070). Rules and IDs:
[README.md](README.md).

**Status:** v0.2, 2026-10-24: product owner decisions D-070 to D-074 applied; WP-020 done.
**Owner:** Haider (Product Owner).

## How to read this plan

- **Order** starts from the WP-020 sequence agreed in the WP-020 plan (020, 020b to 020f,
  021 to 028) and continues from WP-029. Already-planned WP-017 (branding) and WP-018 (audit
  log, MVP per D-058) keep their numbers.
- **Sessions** are Claude Code sessions of the size used so far (one session ≈ one focused
  working day with tests). They are estimates, not commitments.
- **Depends on** lists only work packages that are not yet done. Done: WP-006, WP-009,
  WP-010, WP-012, WP-014, WP-016, WP-020.
- A work package is done when every acceptance criterion of its requirements has a passing
  test (README, "Acceptance criteria become tests"). Requirements of other priorities that a
  work package touches are not in its scope unless listed.
- **Defaults to decide** lists the tenant defaults each work package settles in its own plan,
  with the product owner, before building (D-074).

## Decisions applied

- **D-070:** the internal go-live and the design partner run on-prem, single node (the
  design partner is pending confirmation). WP-014c (offline installer) is on the MVP path;
  WP-014d (SaaS cell) moves after MVP.
- **D-071:** on-prem installs connect to AD/LDAP directly; the relay agent (REQ-INT-087) stays
  V1; SaaS supports Entra ID only at MVP.
- **D-072:** no local AI model is fixed yet. Rules: permissive licence (Apache-2.0 or MIT),
  good Arabic and English (Urdu a plus), runs on one 24 GB GPU, plus a smaller CPU-only
  fallback. WP-037's plan proposes the model and sizing.
- **D-073:** the first-run setup asks the technician-visibility question (D-052) with "group"
  preselected.
- **D-074:** the remaining flagged defaults are decided in each work package's own plan.

## Totals

| Measure | Value |
|---|---|
| MVP requirements mapped | **397** of 397 (every one, exactly once; checked by script) |
| Work packages with requirements | 31 (1 done) |
| Sessions left, requirement work packages | 62 |
| Sessions, platform work packages (WP-013, WP-014b, WP-014c) | 6 |
| **Sessions to MVP, one lane** | **68** (about 14 working weeks) |
| **Calendar to MVP, two lanes** | **34 session-days** (about 7 working weeks) |
| Critical path | **14 sessions**: WP-020c → WP-026 → WP-029 → WP-030 → WP-031 → WP-032 |
| After MVP | WP-014d SaaS cell (2 sessions, D-070) |

By file: 01 92, 02 61, 03 60, 08 38, 09 40, 10 11, 11 75, 12 20.

## Work packages in order

| # | WP | Title | Requirements | Sessions | Depends on | Lane | Defaults to decide |
|---|---|---|---|---|---|---|---|
| 1 | WP-020 | Work item engine and incident record | 40 | done | — | done | — |
| 2 | WP-020b | Conversation, notes and followers | 5 | 2 | — | A | — |
| 3 | WP-020c | Incident settings screens and templates | 6 | 2 | — | A | — |
| 4 | WP-020d | Views, search in lists and bulk actions | 10 | 2 | — | A | — |
| 5 | WP-020e | Tasks, worklogs (time) and links | 3 | 2 | WP-020b | A | — |
| 6 | WP-020f | Resolution, closure, reopen and cancel | 9 | 2 | WP-020b | A | — |
| 7 | WP-021 | People, sites, departments, groups and desks | 13 | 2 | — | A | — |
| 8 | WP-022 | Files and safe attachments | 1 | 1 | WP-020b | B | — |
| 9 | WP-023 | Notification engine and in-app notifications | 17 | 2 | WP-020b, WP-021 | A | — |
| 10 | WP-024 | Email channel: mailboxes, inbound and outbound | 12 | 2 | WP-023, WP-022 | A | — |
| 11 | WP-025 | SLA v1 on Temporal | 26 | 3 | WP-020c, WP-021 | A | 2 |
| 12 | WP-026 | Custom fields for every module | 2 | 2 | WP-020c | A | — |
| 13 | WP-027 | Search (OpenSearch) and record pickers | 1 | 1 | — | B | — |
| 14 | WP-028 | Portal: shell, sign-in and requester incidents | 9 | 2 | WP-020f, WP-023 | A | — |
| 15 | WP-029 | Business rules, triggers, routing and auto-assignment | 20 | 3 | WP-020c, WP-021, WP-026 | A | 1 |
| 16 | WP-030 | Service requests and the approval engine | 27 | 3 | WP-029, WP-025, WP-023 | A | 1 |
| 17 | WP-031 | Service catalog administration | 16 | 2 | WP-030, WP-026 | A | 1 |
| 18 | WP-032 | Portal: home, catalog, approvals inbox and preview | 9 | 2 | WP-028, WP-031 | A | — |
| 19 | WP-033 | Knowledge base: authoring, versions, approval, visibility | 31 | 3 | WP-022 | B | 1 |
| 20 | WP-034 | Knowledge search, suggestions and portal knowledge | 9 | 2 | WP-033, WP-027, WP-028 | B | — |
| 21 | WP-035 | Reporting foundation and built-in reports | 19 | 3 | WP-025, WP-026 | B | 2 |
| 22 | WP-036 | Home page and live dashboards | 21 | 2 | WP-035 | B | — |
| 23 | WP-037 | Minimal AI gateway and local model | 11 | 2 | — | B | — |
| 24 | WP-038 | AI on incidents: summary, reply drafts, similar incidents | 3 | 1 | WP-037, WP-020b | A | — |
| 25 | WP-017 | Tenant branding and domains | 4 | 2 | — | B | — |
| 26 | WP-039 | Identity: SSO, MFA, invitations, sessions, my account | 18 | 3 | WP-017, WP-023, WP-021 | B | — |
| 27 | WP-040 | Connector framework and directory sync | 12 | 2 | WP-021, WP-039 | B | — |
| 28 | WP-041 | Public API: keys, scopes, documentation | 7 | 1 | — | B | — |
| 29 | WP-042 | Admin setup, roles screens, preferences and licence page | 21 | 3 | WP-021, WP-013 | B | — |
| 30 | WP-018 | Tamper-evident audit log | 13 | 2 | — | B | 1 |
| 31 | WP-043 | Security hardening and go-live readiness | 2 | 1 | WP-014b, WP-039 | B | — |

Platform work packages (no parity requirements of their own):

| WP | Title | Sessions | Depends on | Lane | Note |
|---|---|---|---|---|---|
| WP-013 | Licence core prototype (Rust) | 2 | — | B | Needed for the licence page and on-prem activation. |
| WP-014b | Deployment part 2: HA, backups, monitoring | 2 | — | B | Needed before any production go-live. |
| WP-014c | Deployment part 3: release pipeline and offline (air-gapped) installer | 2 | WP-014b | B | On the MVP path: the internal go-live and the design partner run on-prem, single node (D-070). |
| WP-014d | Deployment part 4: SaaS cell | 2 | WP-014b, WP-017 | after MVP | After MVP (D-070). |

## Critical path

The longest chain of dependent work is 14 sessions:

WP-020c (2) → WP-026 (2) → WP-029 (3) → WP-030 (3) → WP-031 (2) → WP-032 (2).

## Two lanes

Two sessions can run at the same time when they do not touch the same code. **Lane A** is
the WP-020 chain: the work item engine, incidents, service requests, the catalog and the
portal (modules `work_items`, `organization`, `notifications`, `sla`, `automation`,
`service_catalog`, the console incident screens and `apps/portal`). **Lane B** takes the work
that lives in other modules or outside the application: the audit log (`audit`), file storage
and scanning, the search index (OpenSearch), the licence
core (`licence-core/`, `licensing`), deployment (`deploy/`), the AI gateway (`ai`), branding,
identity (`identity_access`), integrations, the public API, knowledge, reports and dashboards
(`knowledge`, `analytics`), admin setup and go-live hardening.

Rules that keep the lanes apart:

- **One Alembic head.** Each lane merges latest `main` before its PR; if the other lane merged
  a migration first, the later branch rebases its migration onto the new head (renumbers its
  revision and `down_revision`). Never two heads on `main`.
- **Shared files are touched by one lane at a time:** `backend/app/core/modules.py`, the
  permission catalogue, `packages/labels` (merge conflicts are expected but small; the later
  PR resolves them), the console navigation and `docs/PROGRESS.md`.
- **Lane B waits for lane A** where it depends on it (for example knowledge needs files from
  WP-022; reports need SLA and custom fields; identity needs notifications for invitations).
  The schedule below already includes these waits.
- Decision IDs: each lane takes the next free number on `main` when it records a decision.

Schedule (session-days from now, start → end; a gap means the lane waits for the other):

| Lane A | Days | Lane B | Days |
|---|---|---|---|
| WP-020b Conversation, notes and followers | 0–2 | WP-018 Tamper-evident audit log | 0–2 |
| WP-020c Incident settings screens and templates | 2–4 | WP-022 Files and safe attachments | 2–3 |
| WP-020d Views, search in lists and bulk actions | 4–6 | WP-027 Search (OpenSearch) and record pickers | 3–4 |
| WP-020e Tasks, worklogs (time) and links | 6–8 | WP-013 Licence core prototype (Rust) | 4–6 |
| WP-020f Resolution, closure, reopen and cancel | 8–10 | WP-014b Deployment part 2: HA, backups, monitoring | 6–8 |
| WP-021 People, sites, departments, groups and desks | 10–12 | WP-014c Deployment part 3: release pipeline and offline (air-gapped) installer | 8–10 |
| WP-023 Notification engine and in-app notifications | 12–14 | WP-037 Minimal AI gateway and local model | 10–12 |
| WP-024 Email channel: mailboxes, inbound and outbound | 14–16 | WP-017 Tenant branding and domains | 12–14 |
| WP-025 SLA v1 on Temporal | 16–19 | WP-041 Public API: keys, scopes, documentation | 14–15 |
| WP-026 Custom fields for every module | 19–21 | WP-033 Knowledge base: authoring, versions, approval, visibility | 15–18 |
| WP-028 Portal: shell, sign-in and requester incidents | 21–23 | WP-039 Identity: SSO, MFA, invitations, sessions, my account | 18–21 |
| WP-029 Business rules, triggers, routing and auto-assignment | 23–26 | WP-040 Connector framework and directory sync | 21–23 |
| WP-030 Service requests and the approval engine | 26–29 | WP-035 Reporting foundation and built-in reports | 23–26 |
| WP-031 Service catalog administration | 29–31 | WP-036 Home page and live dashboards | 26–28 |
| WP-032 Portal: home, catalog, approvals inbox and preview | 31–33 | WP-042 Admin setup, roles screens, preferences and licence page | 28–31 |
| WP-038 AI on incidents: summary, reply drafts, similar incidents | 33–34 | WP-034 Knowledge search, suggestions and portal knowledge | 31–33 |
|  |  | WP-043 Security hardening and go-live readiness | 33–34 |

With two lanes the MVP takes about **34 session-days (about 7 working weeks)** instead
of 68 (about 14 weeks) with one. Lane A is busy 34 days and lane B 34;
lane B idles 0 days waiting for lane A work it depends on. The calendar assumes five
sessions a week, no rework and product owner answers within a day; review time, holidays and
the design partner's own testing come on top.

## Work package details

### WP-020 — Work item engine and incident record

- **Sessions:** done · **Depends on:** nothing open · **Requirements:** 40
- **Note:** Done 2026-10-24 (PR #42): engine, incidents API, console screens, Tiptap editor (D-069). Keeping a handed-over incident followed (REQ-INC-151) moved to WP-020b.

| ID | Title | File |
|---|---|---|
| REQ-WI-001 | One engine for every ticket-like record | 01 |
| REQ-WI-002 | Human-readable IDs per type | 01 |
| REQ-WI-003 | Field history for every change | 01 |
| REQ-WI-005 | Live updates on every screen | 01 |
| REQ-WI-007 | Safe concurrent editing | 01 |
| REQ-WI-008 | No duplicate records from retries | 01 |
| REQ-WI-009 | No silent failures | 01 |
| REQ-WI-010 | Actions decided by the server, shown in a fixed order | 01 |
| REQ-WI-011 | Fixed tabs on the record page | 01 |
| REQ-WI-012 | Stable layout while working | 01 |
| REQ-WI-013 | Labels, languages and right-to-left | 01 |
| REQ-WI-014 | One date and time formatter | 01 |
| REQ-WI-015 | Permissions by action and by scope | 01 |
| REQ-WI-017 | Licensing through entitlements only | 01 |
| REQ-WI-019 | Domain events for every change | 01 |
| REQ-WI-020 | Trash and restore | 01 |
| REQ-WI-023 | Accessible to WCAG 2.2 AA | 01 |
| REQ-INC-001 | Incident record and core fields | 01 |
| REQ-INC-002 | The type decides the form and the behaviour | 01 |
| REQ-INC-003 | Requester, on behalf of, and requester context | 01 |
| REQ-INC-005 | Channel recorded automatically | 01 |
| REQ-INC-006 | Category, subcategory and item | 01 |
| REQ-INC-008 | Impact and urgency on clean scales | 01 |
| REQ-INC-009 | Priority matrix with sensible defaults | 01 |
| REQ-INC-010 | Priority override with permission and reason | 01 |
| REQ-INC-013 | System times and counters | 01 |
| REQ-INC-017 | Create form for technicians | 01 |
| REQ-INC-044 | Statuses with a fixed meaning | 01 |
| REQ-INC-045 | Default statuses and life cycle | 01 |
| REQ-INC-046 | Status changes only through allowed transitions | 01 |
| REQ-INC-047 | Reasons for status changes | 01 |
| REQ-INC-050 | Assignment moves the status sensibly | 01 |
| REQ-INC-053 | Assign to a group and a technician | 01 |
| REQ-INC-054 | Take ownership | 01 |
| REQ-INC-055 | Reassign with a record of why | 01 |
| REQ-INC-064 | Safe rich text | 01 |
| REQ-INC-122 | Record page layout | 01 |
| REQ-INC-123 | Edit fields on the record | 01 |
| REQ-WF-001 | Life cycles for every work item type | 03 |
| REQ-WF-002 | Every template has a life cycle; a workflow works through it | 03 |

### WP-020b — Conversation, notes and followers

- **Sessions:** 2 · **Depends on:** nothing open · **Requirements:** 5 · **Lane:** A
- **Note:** Includes REQ-INC-151 (keep following after hand-over, D-068). Done 2026-10-26 in one session (D-079, D-080).

| ID | Title | File |
|---|---|---|
| REQ-INC-057 | One conversation timeline | 01 |
| REQ-INC-058 | Reply, reply to all, forward | 01 |
| REQ-INC-061 | Public and private notes | 01 |
| REQ-INC-065 | First response is stamped automatically | 01 |
| REQ-INC-151 | The escalating technician can keep following | 01 |

### WP-020c — Incident settings screens and templates

- **Sessions:** 2 · **Depends on:** nothing open · **Requirements:** 6 · **Lane:** A
- **Note:** Matrix, scales, reasons, categories, prefixes (REQ-ADM-045), pick lists, templates; people pickers (REQ-WI-027). Admins edit values only at MVP (D-056).

| ID | Title | File |
|---|---|---|
| REQ-INC-011 | Never silently without priority or SLA | 01 |
| REQ-INC-020 | Log an incident already resolved | 01 |
| REQ-INC-035 | Incident templates | 01 |
| REQ-WI-027 | People can be told apart in every picker | 01 |
| REQ-ADM-043 | Pick lists with translations, order and colour | 11 |
| REQ-ADM-045 | Numbering for every record type on one page | 11 |

### WP-020d — Views, search in lists and bulk actions

- **Sessions:** 2 · **Depends on:** nothing open · **Requirements:** 10 · **Lane:** A

| ID | Title | File |
|---|---|---|
| REQ-INC-104 | Incident list with chosen columns | 01 |
| REQ-INC-105 | Built-in views | 01 |
| REQ-INC-106 | Custom views and the filter builder | 01 |
| REQ-INC-108 | Quick time range | 01 |
| REQ-INC-109 | Search with chips, without losing your place | 01 |
| REQ-INC-110 | Counts and paging | 01 |
| REQ-INC-119 | Select across pages | 01 |
| REQ-INC-120 | Bulk edit, assign, take, resolve and close | 01 |
| REQ-INC-128 | Personal counters | 01 |
| REQ-INC-152 | Default views never hide records silently | 01 |

### WP-020e — Tasks, worklogs (time) and links

- **Sessions:** 2 · **Depends on:** WP-020b · **Requirements:** 3 · **Lane:** A
- **Note:** Worklog time only; costs and billable time are V1 (D-047).

| ID | Title | File |
|---|---|---|
| REQ-INC-067 | Worklogs | 01 |
| REQ-INC-072 | Tasks on an incident | 01 |
| REQ-INC-084 | Link related incidents | 01 |

### WP-020f — Resolution, closure, reopen and cancel

- **Sessions:** 2 · **Depends on:** WP-020b · **Requirements:** 9 · **Lane:** A

| ID | Title | File |
|---|---|---|
| REQ-INC-051 | Requester reply resumes a paused incident | 01 |
| REQ-INC-090 | Resolve with a resolution | 01 |
| REQ-INC-093 | Closure codes | 01 |
| REQ-INC-094 | Closure rules | 01 |
| REQ-INC-095 | Closing with open work is warned or blocked | 01 |
| REQ-INC-096 | Requester confirms the resolution, then auto-close | 01 |
| REQ-INC-097 | Reopen keeps the past | 01 |
| REQ-INC-098 | Requester replies after resolution | 01 |
| REQ-INC-100 | Cancel with a reason, and undo it | 01 |

### WP-021 — People, sites, departments, groups and desks

- **Sessions:** 2 · **Depends on:** nothing open · **Requirements:** 13 · **Lane:** A
- **Note:** Adds the desk on every record from MVP (REQ-ESM-002, D-061). The first-run setup asks the technician-visibility question with "group" preselected (D-073).

| ID | Title | File |
|---|---|---|
| REQ-ADM-001 | One list of people | 11 |
| REQ-ADM-002 | The person record | 11 |
| REQ-ADM-003 | One person, technician, requester or both | 11 |
| REQ-ADM-004 | Sign-in access without hidden prerequisites | 11 |
| REQ-ADM-009 | Technician seats against the licence; requesters unlimited | 11 |
| REQ-ADM-010 | Deactivate instead of delete | 11 |
| REQ-ADM-013 | Import people | 11 |
| REQ-ADM-031 | Support groups | 11 |
| REQ-ADM-035 | Reporting lines | 11 |
| REQ-ADM-037 | Sites | 11 |
| REQ-ADM-039 | Departments | 11 |
| REQ-INC-016 | Site and department | 01 |
| REQ-ESM-002 | Every record belongs to a desk from day one | 12 |

### WP-022 — Files and safe attachments

- **Sessions:** 1 · **Depends on:** WP-020b · **Requirements:** 1 · **Lane:** B
- **Note:** aioboto3 (D-054); ClamAV scanning.

| ID | Title | File |
|---|---|---|
| REQ-INC-079 | Safe attachments | 01 |

### WP-023 — Notification engine and in-app notifications

- **Sessions:** 2 · **Depends on:** WP-020b, WP-021 · **Requirements:** 17 · **Lane:** A

| ID | Title | File |
|---|---|---|
| REQ-NTF-001 | One notification engine for every module | 03 |
| REQ-NTF-003 | In-app channel for every module | 03 |
| REQ-NTF-008 | Notification rules per module and event | 03 |
| REQ-NTF-009 | Recipients, including people relative to the record | 03 |
| REQ-NTF-010 | Access is checked when sending | 03 |
| REQ-NTF-011 | Template editor | 03 |
| REQ-NTF-012 | Preview and test send | 03 |
| REQ-NTF-013 | Default templates for every module, with versions and reset | 03 |
| REQ-NTF-014 | Notifications in English and Arabic, Urdu from V1 | 03 |
| REQ-NTF-020 | Delivery status, retries and resend | 03 |
| REQ-NTF-022 | Throttling and storm protection | 03 |
| REQ-NTF-024 | Secure action links | 03 |
| REQ-NTF-026 | Group notifications without hidden switches | 03 |
| REQ-INC-130 | Incident notifications with sensible defaults | 01 |
| REQ-INC-131 | In-app notification centre | 01 |
| REQ-INC-133 | Notifications in the recipient's language | 01 |
| REQ-INC-134 | Notification log on the incident | 01 |

### WP-024 — Email channel: mailboxes, inbound and outbound

- **Sessions:** 2 · **Depends on:** WP-023, WP-022 · **Requirements:** 12 · **Lane:** A

| ID | Title | File |
|---|---|---|
| REQ-INC-023 | Email creates incidents | 01 |
| REQ-INC-024 | Email replies thread into the incident | 01 |
| REQ-INC-027 | Unknown senders | 01 |
| REQ-INC-059 | Delivery status of outgoing messages | 01 |
| REQ-INC-060 | Work goes on when mail is not configured | 01 |
| REQ-NTF-002 | Email channel | 03 |
| REQ-NTF-023 | No mail loops and no notifications to robots | 03 |
| REQ-INT-050 | Mailbox connections with modern sign-in | 12 |
| REQ-INT-051 | Several mailboxes, each with its own routing | 12 |
| REQ-INT-053 | Outgoing mail per mailbox | 12 |
| REQ-ADM-066 | One mail page in setup | 11 |
| REQ-ADM-067 | Fetched mail is kept, not deleted | 11 |

### WP-025 — SLA v1 on Temporal

- **Sessions:** 3 · **Depends on:** WP-020c, WP-021 · **Requirements:** 26 · **Lane:** A
- **Note:** Temporal comes in here (D-055).
- **Default to decide in the WP plan:** Default working week (file 03 question 4)
- **Default to decide in the WP plan:** Priority change rule default (file 03 question 5)

| ID | Title | File |
|---|---|---|
| REQ-SLA-001 | SLA policies for every work item type | 03 |
| REQ-SLA-002 | Policy conditions with the shared filter grammar | 03 |
| REQ-SLA-003 | First match wins, in an order the admin sees | 03 |
| REQ-SLA-004 | Why this SLA applies | 03 |
| REQ-SLA-005 | Targets by priority inside one policy | 03 |
| REQ-SLA-010 | Operating-hours calendars | 03 |
| REQ-SLA-012 | Holiday calendars | 03 |
| REQ-SLA-013 | Which calendar and time zone a record uses | 03 |
| REQ-SLA-014 | Business-time arithmetic that can be trusted | 03 |
| REQ-SLA-015 | Pause and resume by status category | 03 |
| REQ-SLA-016 | No separate stop-the-clock button | 03 |
| REQ-SLA-018 | Pause history and paused time | 03 |
| REQ-SLA-019 | Near-breach warning | 03 |
| REQ-SLA-020 | Breaches are flagged and stay flagged | 03 |
| REQ-SLA-022 | Escalation levels before and after the due time | 03 |
| REQ-SLA-023 | Escalation recipients, including people relative to the record | 03 |
| REQ-SLA-024 | Escalation actions | 03 |
| REQ-SLA-025 | Escalations stop when they no longer apply | 03 |
| REQ-SLA-027 | What happens when priority or conditions change | 03 |
| REQ-SLA-028 | Due dates set by hand | 03 |
| REQ-SLA-029 | Reopen | 03 |
| REQ-SLA-037 | Durable, accurate SLA clocks | 03 |
| REQ-SLA-038 | The SLA panel on the record | 03 |
| REQ-SLA-039 | SLA data for reports and events | 03 |
| REQ-INC-012 | Due dates from the SLA, overrides recorded | 01 |
| REQ-ADM-040 | Calendars and absence types linked to sites and groups | 11 |

### WP-026 — Custom fields for every module

- **Sessions:** 2 · **Depends on:** WP-020c · **Requirements:** 2 · **Lane:** A

| ID | Title | File |
|---|---|---|
| REQ-INC-014 | Custom fields on incidents | 01 |
| REQ-ADM-041 | Custom fields for every module from one place | 11 |

### WP-027 — Search (OpenSearch) and record pickers

- **Sessions:** 1 · **Depends on:** nothing open · **Requirements:** 1 · **Lane:** B
- **Note:** Search index used later by knowledge, catalog and portal search.

| ID | Title | File |
|---|---|---|
| REQ-INC-085 | Link and merge pickers search everything you can see | 01 |

### WP-028 — Portal: shell, sign-in and requester incidents

- **Sessions:** 2 · **Depends on:** WP-020f, WP-023 · **Requirements:** 9 · **Lane:** A

| ID | Title | File |
|---|---|---|
| REQ-INC-028 | Requesters report incidents in the portal | 01 |
| REQ-INC-147 | Requesters follow their incidents | 01 |
| REQ-PRT-001 | Portal application and navigation | 02 |
| REQ-PRT-007 | My requests | 02 |
| REQ-PRT-013 | Profile and preferences | 02 |
| REQ-PRT-020 | Languages and right-to-left in the portal | 02 |
| REQ-PRT-021 | Accessible portal | 02 |
| REQ-PRT-022 | Mobile-first portal | 02 |
| REQ-PRT-024 | Requester sign-in | 02 |

### WP-029 — Business rules, triggers, routing and auto-assignment

- **Sessions:** 3 · **Depends on:** WP-020c, WP-021, WP-026 · **Requirements:** 20 · **Lane:** A
- **Default to decide in the WP plan:** Business rule processing default: continue unless "stop" (file 03 question 6)

| ID | Title | File |
|---|---|---|
| REQ-RUL-001 | Business rules run inside the save | 03 |
| REQ-RUL-002 | Rule conditions | 03 |
| REQ-RUL-003 | Rule actions that change the record | 03 |
| REQ-RUL-004 | Refuse a save with a clear message | 03 |
| REQ-RUL-005 | Order and "stop here" | 03 |
| REQ-RUL-006 | One documented order for all automation | 03 |
| REQ-RUL-007 | Rules apply on every path | 03 |
| REQ-RUL-009 | Triggers on any committed event | 03 |
| REQ-RUL-010 | Trigger actions | 03 |
| REQ-RUL-028 | Loop protection | 03 |
| REQ-RUL-029 | Checked when saved, switched on deliberately | 03 |
| REQ-ASG-001 | Routing rules choose the group | 03 |
| REQ-ASG-002 | Auto-assignment set up per group | 03 |
| REQ-ASG-003 | Round robin | 03 |
| REQ-ASG-004 | Load balancing | 03 |
| REQ-ASG-006 | Who counts as available | 03 |
| REQ-ASG-011 | Load caps and what happens when nobody is available | 03 |
| REQ-WI-004 | Automation leaves a visible trace | 01 |
| REQ-WF-003 | Before, during and after a transition | 03 |
| REQ-WF-004 | Who may run a transition | 03 |

### WP-030 — Service requests and the approval engine

- **Sessions:** 3 · **Depends on:** WP-029, WP-025, WP-023 · **Requirements:** 27 · **Lane:** A
- **Default to decide in the WP plan:** Email approvals without sign-in (file 02 question 3)

| ID | Title | File |
|---|---|---|
| REQ-SR-001 | Service request is its own work item type | 02 |
| REQ-SR-002 | Service requests inherit the engine | 02 |
| REQ-SR-003 | Service request fields | 02 |
| REQ-SR-004 | Default life cycle for service requests | 02 |
| REQ-SR-005 | Priority is never left blank on a new request | 02 |
| REQ-SR-006 | SLA chosen by the item or by rules | 02 |
| REQ-SR-007 | SLA clock waits for approval | 02 |
| REQ-SR-008 | Assignment from the catalog item | 02 |
| REQ-SR-009 | Service request lists, views and columns | 02 |
| REQ-SR-010 | Technicians raise requests from the catalog | 02 |
| REQ-SR-011 | Request on behalf of someone else | 02 |
| REQ-SR-021 | Approval before fulfilment | 02 |
| REQ-SR-022 | Approver by name or the requester's manager | 02 |
| REQ-SR-023 | No approval waits on nobody | 02 |
| REQ-SR-024 | Everyone involved sees the approval progress | 02 |
| REQ-SR-025 | Approve or reject in the app | 02 |
| REQ-SR-026 | Approve by email with safe one-time links | 02 |
| REQ-SR-027 | Segregation of duties in approvals | 02 |
| REQ-SR-028 | Reasons and comments on decisions | 02 |
| REQ-SR-046 | Fulfilment tasks from the catalog item | 02 |
| REQ-SR-051 | Fulfilment progress the requester can follow | 02 |
| REQ-SR-058 | Fulfilled when the work is done | 02 |
| REQ-SR-059 | Requester confirms receipt, then auto-close | 02 |
| REQ-SR-060 | Rejected requests | 02 |
| REQ-SR-061 | Withdraw a request awaiting approval | 02 |
| REQ-SR-062 | Requesters follow their service requests | 02 |
| REQ-SR-063 | One approver model for requests and changes | 02 |

### WP-031 — Service catalog administration

- **Sessions:** 2 · **Depends on:** WP-030, WP-026 · **Requirements:** 16 · **Lane:** A
- **Note:** Starter catalog content (REQ-CAT-007) needs product owner review.
- **Default to decide in the WP plan:** Catalog edition line: basics Essentials, advanced Professional (file 02 question 1)

| ID | Title | File |
|---|---|---|
| REQ-CAT-001 | Service categories in a tree | 02 |
| REQ-CAT-002 | Catalog items | 02 |
| REQ-CAT-003 | Incident templates in the catalog | 02 |
| REQ-CAT-004 | One admin page per catalog item | 02 |
| REQ-CAT-005 | Copy, move, disable and retire items | 02 |
| REQ-CAT-006 | Item content in every language | 02 |
| REQ-CAT-007 | Starter catalog for a new tenant | 02 |
| REQ-CAT-008 | Questions on the item form | 02 |
| REQ-CAT-014 | Show or hide an item from requesters | 02 |
| REQ-CAT-016 | Approval settings per item | 02 |
| REQ-CAT-017 | SLA per item | 02 |
| REQ-CAT-018 | Fulfilment group per item | 02 |
| REQ-CAT-019 | Fulfilment plan per item | 02 |
| REQ-CAT-024 | Draft, preview, publish and retire | 02 |
| REQ-CAT-027 | Order and featured items | 02 |
| REQ-CAT-028 | Catalog search | 02 |

### WP-032 — Portal: home, catalog, approvals inbox and preview

- **Sessions:** 2 · **Depends on:** WP-028, WP-031 · **Requirements:** 9 · **Lane:** A

| ID | Title | File |
|---|---|---|
| REQ-PRT-002 | Portal home | 02 |
| REQ-PRT-003 | One search box for everything | 02 |
| REQ-PRT-004 | Browse the catalog | 02 |
| REQ-PRT-005 | Submit a request in the portal | 02 |
| REQ-PRT-006 | After submitting, say what happens next | 02 |
| REQ-PRT-008 | Approvals inbox | 02 |
| REQ-PRT-009 | Announcements in the portal | 02 |
| REQ-PRT-031 | One page of portal settings | 02 |
| REQ-PRT-032 | Preview the portal as a chosen person | 02 |

### WP-033 — Knowledge base: authoring, versions, approval, visibility

- **Sessions:** 3 · **Depends on:** WP-022 · **Requirements:** 31 · **Lane:** B
- **Default to decide in the WP plan:** Articles in review hidden from other technicians by default (file 08 question 2)

| ID | Title | File |
|---|---|---|
| REQ-KB-001 | Knowledge article record and core fields | 08 |
| REQ-KB-002 | Article IDs with a prefix | 08 |
| REQ-KB-003 | Topic tree | 08 |
| REQ-KB-004 | Managing topics | 08 |
| REQ-KB-005 | Keywords that help search | 08 |
| REQ-KB-006 | Rich-text article body | 08 |
| REQ-KB-007 | Attachments and images on articles | 08 |
| REQ-KB-008 | Article types | 08 |
| REQ-KB-012 | Create and edit articles | 08 |
| REQ-KB-013 | Drafts are saved automatically | 08 |
| REQ-KB-020 | Every published change is a version | 08 |
| REQ-KB-021 | Edit a published article without taking it offline | 08 |
| REQ-KB-026 | Article statuses with a fixed meaning | 08 |
| REQ-KB-027 | Submit, approve and reject | 08 |
| REQ-KB-028 | Approving your own article | 08 |
| REQ-KB-031 | Withdraw an article | 08 |
| REQ-KB-033 | Article and topic owners | 08 |
| REQ-KB-034 | Review dates and review without a new version | 08 |
| REQ-KB-035 | Expiry | 08 |
| REQ-KB-043 | Knowledge permissions | 08 |
| REQ-KB-044 | Technician visibility by group, set on topics and articles | 08 |
| REQ-KB-045 | Requester audiences | 08 |
| REQ-KB-048 | Visibility is enforced everywhere | 08 |
| REQ-KB-049 | Translations of an article | 08 |
| REQ-KB-052 | Right-to-left and Arabic text in articles and search | 08 |
| REQ-KB-077 | Knowledge list with topic tree and views | 08 |
| REQ-KB-078 | Article page | 08 |
| REQ-KB-079 | Trash and restore | 08 |
| REQ-KB-080 | History and audit | 08 |
| REQ-KB-086 | Knowledge notifications with sensible defaults | 08 |
| REQ-KB-090 | Knowledge settings on one page | 08 |

### WP-034 — Knowledge search, suggestions and portal knowledge

- **Sessions:** 2 · **Depends on:** WP-033, WP-027, WP-028 · **Requirements:** 9 · **Lane:** B

| ID | Title | File |
|---|---|---|
| REQ-KB-053 | Full-text knowledge search | 08 |
| REQ-KB-062 | One suggestion service for every entry point | 08 |
| REQ-KB-063 | Search and insert from the editors | 08 |
| REQ-KB-064 | Link articles to records | 08 |
| REQ-KB-069 | "Did this help?" | 08 |
| REQ-KB-081 | Knowledge in the portal | 08 |
| REQ-KB-082 | Knowledge in portal search | 08 |
| REQ-INC-021 | Knowledge suggestions while typing | 01 |
| REQ-PRT-010 | Knowledge in the portal | 02 |

### WP-035 — Reporting foundation and built-in reports

- **Sessions:** 3 · **Depends on:** WP-025, WP-026 · **Requirements:** 19 · **Lane:** B
- **Note:** PostgreSQL views on single node; ClickHouse threshold is file 09 question 10.
- **Default to decide in the WP plan:** Scheduled reports at MVP? (file 09 question 1)
- **Default to decide in the WP plan:** Report builder edition (file 09 question 3)

| ID | Title | File |
|---|---|---|
| REQ-RPT-001 | One reporting engine with a semantic layer | 09 |
| REQ-RPT-002 | Results contain only what the viewer may see | 09 |
| REQ-RPT-004 | One definition for every standard measure | 09 |
| REQ-RPT-005 | Labels, never codes, in every result | 09 |
| REQ-RPT-006 | Reports never slow down the service desk | 09 |
| REQ-RPT-008 | Fresh data, and the user knows how fresh | 09 |
| REQ-RPT-009 | Query limits, timeouts and fair use | 09 |
| REQ-RPT-013 | Custom fields in reports | 09 |
| REQ-RPT-015 | Incident and service request reports at go-live | 09 |
| REQ-RPT-016 | SLA reports | 09 |
| REQ-RPT-017 | Time spent and worklog reports | 09 |
| REQ-RPT-019 | Copy a built-in report to change it | 09 |
| REQ-RPT-029 | Filters with the shared filter format | 09 |
| REQ-RPT-037 | Drill down from any number to the records | 09 |
| REQ-RPT-044 | One chart kit for reports and dashboards | 09 |
| REQ-RPT-045 | Report folders and finding reports | 09 |
| REQ-RPT-048 | Reporting permissions | 09 |
| REQ-RPT-050 | The report viewer | 09 |
| REQ-RPT-058 | Export to CSV, Excel and PDF | 09 |

### WP-036 — Home page and live dashboards

- **Sessions:** 2 · **Depends on:** WP-035 · **Requirements:** 21 · **Lane:** B

| ID | Title | File |
|---|---|---|
| REQ-DSH-001 | The home page | 09 |
| REQ-DSH-002 | Default dashboard per role, and the user's own choice | 09 |
| REQ-DSH-003 | Ready-made dashboards | 09 |
| REQ-DSH-005 | Find and pick dashboards | 09 |
| REQ-DSH-007 | Widget library | 09 |
| REQ-DSH-008 | KPI tiles | 09 |
| REQ-DSH-009 | Chart widgets from a quick definition | 09 |
| REQ-DSH-015 | Expand, switch type and refresh a widget | 09 |
| REQ-DSH-016 | Every widget updates live | 09 |
| REQ-DSH-017 | Connection state and recovery | 09 |
| REQ-DSH-019 | Build dashboards on a grid | 09 |
| REQ-DSH-021 | Copy a dashboard | 09 |
| REQ-DSH-022 | Dashboard filters | 09 |
| REQ-DSH-024 | Drill down from any widget | 09 |
| REQ-DSH-026 | Private and shared dashboards | 09 |
| REQ-DSH-028 | Each viewer sees their own scope | 09 |
| REQ-DSH-029 | Dashboard permissions | 09 |
| REQ-DSH-044 | Time zones in reports and dashboards | 09 |
| REQ-DSH-045 | Languages in reports and dashboards | 09 |
| REQ-DSH-046 | Right-to-left charts, reports and exports | 09 |
| REQ-DSH-047 | Accessible charts and dashboards | 09 |

### WP-037 — Minimal AI gateway and local model

- **Sessions:** 2 · **Depends on:** nothing open · **Requirements:** 11 · **Lane:** B
- **Note:** D-057. Masking and call logging are in scope even with the local model. The WP plan proposes the model and sizing within the rules of D-072: permissive licence (Apache-2.0 or MIT), good Arabic and English (Urdu a plus), runs on one 24 GB GPU, plus a smaller CPU-only fallback.

| ID | Title | File |
|---|---|---|
| REQ-AI-001 | One AI gateway for every AI feature | 10 |
| REQ-AI-002 | One provider interface for chat, completion, embeddings and tools | 10 |
| REQ-AI-003 | A local model ships with every deployment | 10 |
| REQ-AI-004 | CPU-only mode and an optional GPU node | 10 |
| REQ-AI-018 | Personal data masked before external models | 10 |
| REQ-AI-025 | AI acts with the user's permissions | 10 |
| REQ-AI-027 | AI master switch and per-feature switches | 10 |
| REQ-AI-031 | Every AI call is logged | 10 |
| REQ-AI-057 | One embedding and retrieval service | 10 |
| REQ-AI-058 | Local embeddings on every deployment | 10 |
| REQ-AI-108 | AI features gated only through entitlements | 10 |

### WP-038 — AI on incidents: summary, reply drafts, similar incidents

- **Sessions:** 1 · **Depends on:** WP-037, WP-020b · **Requirements:** 3 · **Lane:** A
- **Note:** D-057.

| ID | Title | File |
|---|---|---|
| REQ-INC-022 | Possible duplicate warning | 01 |
| REQ-INC-136 | Writing help in replies and notes | 01 |
| REQ-INC-137 | Conversation summary | 01 |

### WP-017 — Tenant branding and domains

- **Sessions:** 2 · **Depends on:** nothing open · **Requirements:** 4 · **Lane:** B
- **Note:** Already planned (D-027).

| ID | Title | File |
|---|---|---|
| REQ-PRT-016 | Tenant branding and domains | 02 |
| REQ-ADM-055 | Branding for the console, sign-in and email | 11 |
| REQ-SEC-003 | Tenant-branded sign-in page | 11 |
| REQ-SEC-004 | Finding the tenant at sign-in | 11 |

### WP-039 — Identity: SSO, MFA, invitations, sessions, my account

- **Sessions:** 3 · **Depends on:** WP-017, WP-023, WP-021 · **Requirements:** 18 · **Lane:** B
- **Note:** SAML/OIDC Essentials MVP (D-059); MFA defaults (D-060).

| ID | Title | File |
|---|---|---|
| REQ-SEC-001 | Sign-in through Keycloak and the backend-for-frontend | 11 |
| REQ-SEC-002 | No outside vendor account | 11 |
| REQ-SEC-005 | Local accounts and password policy | 11 |
| REQ-SEC-006 | Password reset | 11 |
| REQ-SEC-007 | SAML single sign-on per tenant | 11 |
| REQ-SEC-008 | OpenID Connect single sign-on per tenant | 11 |
| REQ-SEC-013 | First sign-in creates the person | 11 |
| REQ-SEC-017 | All identity settings inside the product | 11 |
| REQ-SEC-018 | Invitations in the tenant's name | 11 |
| REQ-SEC-019 | No personal address of the inviter | 11 |
| REQ-SEC-020 | Invitation life cycle | 11 |
| REQ-SEC-022 | MFA with standard authenticator apps | 11 |
| REQ-SEC-024 | MFA policy | 11 |
| REQ-SEC-025 | Recovery codes and MFA reset | 11 |
| REQ-SEC-028 | My account inside the product | 11 |
| REQ-SEC-029 | Session timeouts | 11 |
| REQ-SEC-031 | Sessions end when access ends | 11 |
| REQ-SEC-035 | Brute-force and rate limits | 11 |

### WP-040 — Connector framework and directory sync

- **Sessions:** 2 · **Depends on:** WP-021, WP-039 · **Requirements:** 12 · **Lane:** B
- **Note:** D-062, D-071: on-prem installs connect to AD/LDAP directly; SaaS supports Entra ID only at MVP; the relay agent (REQ-INT-087) stays V1.

| ID | Title | File |
|---|---|---|
| REQ-INT-001 | One connector catalogue | 12 |
| REQ-INT-002 | Set up, test, enable and disable a connector | 12 |
| REQ-INT-003 | Credentials kept in a secrets store | 12 |
| REQ-INT-004 | Health and last sync on every connector | 12 |
| REQ-INT-005 | Failures are visible, never silent | 12 |
| REQ-INT-012 | Connectors act as a service identity | 12 |
| REQ-INT-013 | Who may set up integrations | 12 |
| REQ-INT-063 | Sync users and groups from Entra ID | 12 |
| REQ-INT-064 | Leavers are disabled, never deleted | 12 |
| REQ-INT-065 | Active Directory and LDAP sync | 12 |
| REQ-SEC-012 | Directory sign-in on-prem | 11 |
| REQ-SEC-042 | Secrets in settings are write-only | 11 |

### WP-041 — Public API: keys, scopes, documentation

- **Sessions:** 1 · **Depends on:** nothing open · **Requirements:** 7 · **Lane:** B

| ID | Title | File |
|---|---|---|
| REQ-INT-017 | A documented, versioned public API | 12 |
| REQ-INT-019 | API keys | 12 |
| REQ-INT-021 | Scopes and least privilege | 12 |
| REQ-INT-023 | Safe writes: idempotency and versions | 12 |
| REQ-INT-024 | Lists, filters and expansions | 12 |
| REQ-INT-025 | Errors with stable codes | 12 |
| REQ-WI-018 | Everything the UI does, the API does | 01 |

### WP-042 — Admin setup, roles screens, preferences and licence page

- **Sessions:** 3 · **Depends on:** WP-021, WP-013 · **Requirements:** 21 · **Lane:** B
- **Note:** Announcements (REQ-ADM-077 to 084) mostly exist from WP-012; this verifies and closes gaps.

| ID | Title | File |
|---|---|---|
| REQ-ADM-015 | Roles built from module, action and scope | 11 |
| REQ-ADM-016 | One permission catalogue from every module | 11 |
| REQ-ADM-017 | Built-in roles can be read, compared and copied | 11 |
| REQ-ADM-018 | Roles a new tenant starts with | 11 |
| REQ-ADM-019 | Configuration rights per area | 11 |
| REQ-ADM-021 | No privilege escalation, no lock-out | 11 |
| REQ-ADM-049 | Instance settings | 11 |
| REQ-ADM-050 | Base currency | 11 |
| REQ-ADM-052 | Languages offered in the tenant | 11 |
| REQ-ADM-058 | One preferences page that follows the person | 11 |
| REQ-ADM-059 | Language, time zone and formats per person | 11 |
| REQ-ADM-060 | Navigation layout | 11 |
| REQ-ADM-062 | Theme and text size | 11 |
| REQ-ADM-077 | Announcements | 11 |
| REQ-ADM-078 | Publish window and status flow, live everywhere | 11 |
| REQ-ADM-079 | Second-person publishing | 11 |
| REQ-ADM-084 | Announcement permissions | 11 |
| REQ-ADM-106 | Setup home organised by task | 11 |
| REQ-ADM-107 | Setup search by keyword and meaning | 11 |
| REQ-ADM-108 | Stable setup navigation | 11 |
| REQ-ADM-109 | Licence and plan page | 11 |

### WP-018 — Tamper-evident audit log

- **Sessions:** 2 · **Depends on:** nothing open · **Requirements:** 13 · **Lane:** B
- **Note:** MVP per D-058.
- **Default to decide in the WP plan:** Audit retention minimum and default (file 11 question 6)

| ID | Title | File |
|---|---|---|
| REQ-WI-021 | Audit of privileged actions | 01 |
| REQ-AUD-001 | Tamper-evident audit log | 11 |
| REQ-AUD-002 | What is audited | 11 |
| REQ-AUD-003 | What an entry shows | 11 |
| REQ-AUD-004 | Reads of sensitive settings and data | 11 |
| REQ-AUD-005 | Refused and failed attempts | 11 |
| REQ-AUD-006 | Audit and field history linked | 11 |
| REQ-AUD-007 | Search and filters | 11 |
| REQ-AUD-008 | Who may read the audit log | 11 |
| REQ-AUD-009 | Export for auditors | 11 |
| REQ-AUD-010 | Verify the chain | 11 |
| REQ-AUD-012 | Audit retention and archive | 11 |
| REQ-AUD-013 | Erasure keeps the chain verifiable | 11 |

### WP-043 — Security hardening and go-live readiness

- **Sessions:** 1 · **Depends on:** WP-014b, WP-039 · **Requirements:** 2 · **Lane:** B
- **Note:** Encryption at rest and in transit, application security baseline, final checks.

| ID | Title | File |
|---|---|---|
| REQ-SEC-039 | Encryption in transit and at rest | 11 |
| REQ-SEC-046 | Application security baseline | 11 |

## Still open

1. **Design partner confirmation** (D-070): the on-prem single-node assumption holds until the
   partner is confirmed.
2. **Fair-use allowance and SaaS AI capacity** (D-049, D-064): pending the pricing decision;
   it does not affect MVP, which runs on-prem with the local model.
3. **WP-025 plan:** Default working week (file 03 question 4) (D-074).
4. **WP-025 plan:** Priority change rule default (file 03 question 5) (D-074).
5. **WP-029 plan:** Business rule processing default: continue unless "stop" (file 03 question 6) (D-074).
6. **WP-030 plan:** Email approvals without sign-in (file 02 question 3) (D-074).
7. **WP-031 plan:** Catalog edition line: basics Essentials, advanced Professional (file 02 question 1) (D-074).
8. **WP-033 plan:** Articles in review hidden from other technicians by default (file 08 question 2) (D-074).
9. **WP-035 plan:** Scheduled reports at MVP? (file 09 question 1) (D-074).
10. **WP-035 plan:** Report builder edition (file 09 question 3) (D-074).
11. **WP-018 plan:** Audit retention minimum and default (file 11 question 6) (D-074).
