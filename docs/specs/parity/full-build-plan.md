# Full build plan: all 12 modules, MVP + V1

Maps every remaining **V1** requirement in the parity files, plus the product owner's asset discovery and remote assistance scope (2026-11-04), to work packages per lane, in build order. MVP requirements are covered by [mvp-build-plan.md](mvp-build-plan.md) and finish with the work in progress below. **LATER** stays later. Rules and IDs: [README.md](README.md).

**Status:** v0.1, 2026-11-04. Written by the coordinator from Haider's "new goal" instruction (the whole product, no pilot pause).
**Owner:** Haider (Product Owner).

## How to read this plan

- **Sessions** are Claude Code sessions of the size used so far (one session ≈ one focused build step with tests). The MVP plan's pace was about 6 requirements per session; this plan uses the same rate, with extra sessions where the work is mostly new platform (agents, probes, designers).
- **Every work package:** a plan first (big WPs get a written plan and the coordinator's OK, and product decisions go to Haider), then build, nightly tests (a red nightly is the owner's first task), then the daily QA round including the visual review.
- **Speed mode stays:** one PR per WP session, `gh pr merge --auto`, full-ci only for migrations that change existing data, numbers (migration, D-, ADR-) only from the coordinator.
- **V1 items still inside modules 01, 02, 03, 08, 09 and 11** go to the lane that owns that module.
- **WP-043** (the full CI gate including e2e returns) moves from "before the pilot" to the end of this plan, before the first full release.

## Work in progress (finish first, no pilot pause)

| Lane | WP | What's left | Sessions |
|---|---|---|---|
| A | WP-031 | Catalog admin S2 (admin screens, portal wiring), #200 | 1 |
| A | WP-032 | Portal home, catalog, approvals inbox and preview | 2 |
| B | WP-014b | S2 backups, restore and upgrade (#206); S3 monitoring | 2 |
| C | WP-038 | AI on incidents: S1 screens (#207), S2 writing help and eval | 2 |
| B | WP-013, WP-014c | Licence core (private repo), offline installer. These stay in lane B's queue and never block feature work. | 5 |

## Lane split for the remaining modules

- **Lane A:** Problems (file 04), then Changes (file 05: risk scoring, CAB, change calendar, freeze and maintenance windows), then the V1 items of files 01, 02 and 03 (incidents, service requests and catalog, SLA, assignment and rules); then integrations and ESM V1 (file 12, not §5) and notifications V1 (file 03 §16-19), moved from lane B (D-149).
- **Lane B:** Assets, CMDB, software, purchase and contracts (file 07), including asset discovery, the SupportX Agent and remote assistance, and the MonetX read-only connector; plus WP-013 and WP-014c. **Lane B reviews every PR, in any lane, that touches identity, sign-in, sessions, MFA, secrets or security; the review is blocking (D-149).**
- **Lane C:** Releases (file 06; projects are LATER), the remaining AI (file 10), knowledge V1 (file 08), reports and dashboards V1 (file 09) with reports and dashboards for every new module, admin V1 (file 11 §1-13), and the visual workflow designer (file 03 §15), moved from lane A to balance the lanes; and sign-in, security and audit V1 (file 11 §14-21), moved from lane B (D-149), each PR reviewed and approved by lane B. UI pass 3 (D-147, about 7 sessions) also sits with lane C.

## Asset discovery (lane B, WP-050; file 07 §16-18 plus the product owner's scope)

- **Agentless probe**, installed per site: AD/domain scan, WMI for Windows, SSH for Linux and macOS, SNMP basics, scheduled scans, a credential vault (secrets in the existing secrets store, never in logs), scan history, exclusions.
- **SupportX inventory agent** for Windows, macOS and Linux: hardware, software, licence usage, last user. It works offline, is signed, and auto-updates from the customer's own SupportX server, never the internet.
- **AgentX compatibility:** the agent's data format matches AgentX's, so customers who already run AgentX feed SupportX without a second agent.
- **MonetX read-only connector** supplies network devices (file 12 §5, in WP-053).
- **Reconciliation:** every source reconciles into one asset/CI record, matched on serial, MAC and hostname. Conflicts are shown to an admin and never silently merged.
- **New dependencies** (Go or Rust for the agent, SNMP and WMI libraries, code signing) are named in the WP-050 plan for the product owner's approval before building (CLAUDE.md §3).

## Remote assistance (lane B, WP-051; file 07 §15 plus the product owner's rules)

- Integrate; don't build remote desktop from scratch:
  - attended remote control of user devices through AgentX's remote control if it offers it (Haider confirms), otherwise **MeshCentral** (Apache-2.0, self-hosted, works offline);
  - RDP, SSH and VNC to servers through **Apache Guacamole** (Apache-2.0), in the browser.
- Launched from the incident and the asset ("Remote session").
- **Rules:**
  - the end user approves each session and sees a "being viewed" banner they can use to end it;
  - only roles with the remote-control permission can start one, and MFA is required;
  - every session is audited and linked to the incident;
  - recording is optional;
  - sessions have time limits;
  - a tenant switch disables it.
- **No AGPL components** (e.g. not RustDesk). MeshCentral and Guacamole are new components, so the WP-051 plan names them for approval.

## Work packages in order

### Lane A (about 69 sessions; WP-055 and WP-056 added by D-149)

| WP | Title | V1 requirements (file §) | Count | Sessions |
|---|---|---|---|---|
| WP-044a | Problems: record, creation, templates, statuses, assignment | 04 §1-5 | 28 | 5 |
| WP-044b | Problems: analysis, known errors, links, work, resolution | 04 §6-10 | 29 | 5 |
| WP-044c | Problems: lists, proactive detection and AI, permissions, notifications | 04 §11-15 | 18 | 3 |
| WP-045a | Changes: work item, types and models, fields, templates, stages, roles | 05 §1-6 | 38 | 6 |
| WP-045b | Changes: CAB and approvals, risk assessment and scoring | 05 §7-8 | 19 | 4 |
| WP-045c | Changes: calendar, downtime, conflicts, freeze and maintenance windows, impact, MonetX health | 05 §9-12 | 22 | 4 |
| WP-045d | Changes: tasks, review and closure, lists, notifications, automation, requester, reports | 05 §13-21 | 22 | 4 |
| WP-046a | Incidents V1: engine, channels, templates, life cycle, worklogs, tasks, checklists, attachments, reminders | 01 §1-12 | 42 | 7 |
| WP-046b | Incidents V1: approvals, linking and merging, closure, views, bulk, record page, major incidents, requester | 01 §13-23 | 31 | 5 |
| WP-047a | Service requests V1: raising, approvals, fulfilment | 02 §2-4 | 29 | 5 |
| WP-047b | Catalog and portal V1: forms, item settings, publishing, portal shell, branding, access, chat entry | 02 §7-13 | 22 | 4 |
| WP-048a | SLA, routing, business rules, triggers, custom actions and functions, automation safety, life cycles | 03 §1-14 (not NTF) | 41 | 9 |
| WP-055 | Integrations and ESM V1: framework, REST API, webhooks, email, chat tools, calendars, DevOps, endpoint, relay, MCP | 12 (not §5) | 37 | 6 |
| WP-056 | Notifications V1: engine, templates, preferences, digests, quiet hours, delivery | 03 §16-19 | 11 | 2 |

### Lane B (about 47 sessions; WP-055, WP-056 and WP-057 moved out by D-149)

| WP | Title | V1 requirements (file §) | Count | Sessions |
|---|---|---|---|---|
| WP-049a | Assets: foundations, products, the asset record, life cycle, ownership, components, loans | 07 §1-7 | 31 | 5 |
| WP-049b | Assets: consumables, financials, barcodes and RFID, audits, links, asset pages, scan history | 07 §8-14 | 21 | 4 |
| WP-050 | Discovery: probe, credential vault, scans, inventory agent (3 OS, signed, self-updating, offline), AgentX format, reconciliation | 07 §16-18 + scope | 27 | 13 |
| WP-051 | Remote assistance: MeshCentral or AgentX, Guacamole, approval, banner, MFA, audit, recording, limits, switch | 07 §15 + scope | 5 | 4 |
| WP-052 | Software asset management: catalogue, licences, compliance and metering | 07 §19-21 | 17 | 3 |
| WP-053 | CMDB: CI types, relationships and map, impact, reconciliation, downtimes, baselines, access; MonetX read-only connector | 07 §22-28, 12 §5 | 36 | 7 |
| WP-054 | Purchase and contracts | 07 §29-32 | 16 | 3 |
| (WIP) | WP-014b S2-S3, WP-013, WP-014c | | | 7 |

### Lane C (about 62 sessions; WP-057 added by D-149)

| WP | Title | V1 requirements (file §) | Count | Sessions |
|---|---|---|---|---|
| WP-058a | Releases: record, templates, stages, roles, planning and deployment, approvals, associations | 06 §1-7 | 35 | 6 |
| WP-058b | Releases: calendar, DevOps, work on the record, closure, lists, notifications, reports | 06 §8-14 | 19 | 3 |
| WP-059a | AI V1: gateway and providers, guardrails, permissions, logging, quotas | 10 §1-5 | 30 | 5 |
| WP-059b | AI V1: evaluation and human review, predictions, semantic search, generative | 10 §6-9 | 20 | 4 |
| WP-059c | AI V1: technician assistant, requester assistant and channels, MCP server | 10 §10-14 | 18 | 4 |
| WP-060a | Knowledge V1: articles, authoring, versions, approval, review, known issues, visibility | 08 §1-7 | 24 | 4 |
| WP-060b | Knowledge V1: languages, search and AI answers, on records, feedback, portal, import/export | 08 §8-14 | 26 | 4 |
| WP-061a | Reports V1: foundation, built-in, the visual query builder, viewer, scheduling, BI | 09 §1-6 | 38 | 6 |
| WP-061b | Dashboards V1: home, widgets, builder, filters, sharing, wallboards, KPIs and scorecards | 09 §7-16 | 24 | 4 |
| WP-063 | Reports and dashboards for every new module (problems, changes, releases, assets, CMDB, software, contracts) | new | — | 4 |
| WP-062a | Admin V1: people, roles, groups, organisation, customisation, instance, preferences | 11 §1-7 | 31 | 5 |
| WP-062b | Admin V1: mail, surveys, announcements, data administration, privacy, setup and licence page | 11 §8-13 | 32 | 5 |
| WP-048b | The visual workflow designer (React Flow) | 03 §15 | 22 | 4 |
| WP-057 | Sign-in, MFA, sessions, network and API access, data protection, audit V1 | 11 §14-21 | 25 | 4 |

## Totals and calendar

| Measure | Value |
|---|---|
| V1 requirements mapped | **886** of 886, each exactly once (checked by script; list below) |
| Extra scope | discovery probe and agent, remote assistance, reports for new modules |
| Sessions, work in progress | about 12 |
| Sessions, new work packages | Original split: A about 61, B about 59, C about 58, **about 178**. After D-149: A about 69, B about 47, C about 62 |
| Pace observed (3 lanes, 24 h) | about 1.5 to 2 sessions per lane per day, plus about 15% for merge choreography, QA fixes and red nightlies |
| **Calendar, all lanes in parallel** | Original: about 35 to 46 days, feature-complete about 10 to 21 December 2026. **Re-estimate 2026-11-09 (after D-147 and D-149, see below): feature-complete about 8 to 18 December 2026** |
| Then | WP-043 (the full gate returns) and hardening: about 3 to 5 days, so **the first full release is about 13 to 23 December 2026** (re-estimate 2026-11-09; was 15 to 26 December) |
| Critical path | After D-149: lane A (Changes, incidents and SLA V1, then integrations) and lane C (UI pass 3, the workflow designer, security V1); lane B (discovery and agent) is no longer the longest |

**Re-estimate, 2026-11-09:**
- **Done:** 423 of 1,283 MVP and V1 requirements were on main (33%: MVP 93%, V1 6%), and 24 of about 204 sessions had merged.
- **Plan size:** it grew by 14 sessions, mostly UI pass 3 (D-147).
- **Lost time:** the weekly usage limit stopped all lanes for about 2.5 days (11-06 to 11-09).
- **Remaining after D-149:** about A 63, B 55, C 62 sessions.
- **Pace:** 1.7 sessions per lane per day, outage included, and about 2.4 with work in flight. That puts feature-complete at about 8 to 18 December.

**Risks to the calendar:**
- the weekly usage limit at full three-lane speed;
- the discovery agent: three operating systems, signing and auto-update are new territory;
- MeshCentral and Guacamole integration;
- WP-013 (Rust, private repo);
- product decisions per WP;
- daily QA majors, especially from the visual review.

## Requirement map (every V1 requirement → work package)

- **WP-044a**: REQ-PRB-001, REQ-PRB-002, REQ-PRB-003, REQ-PRB-004, REQ-PRB-005, REQ-PRB-006, REQ-PRB-007, REQ-PRB-008, REQ-PRB-009, REQ-PRB-010, REQ-PRB-011, REQ-PRB-012, REQ-PRB-013, REQ-PRB-014, REQ-PRB-015, REQ-PRB-017, REQ-PRB-018, REQ-PRB-019, REQ-PRB-020, REQ-PRB-021, REQ-PRB-022, REQ-PRB-023, REQ-PRB-024, REQ-PRB-025, REQ-PRB-026, REQ-PRB-027, REQ-PRB-028, REQ-PRB-029
- **WP-044b**: REQ-PRB-030, REQ-PRB-032, REQ-PRB-033, REQ-PRB-034, REQ-PRB-035, REQ-PRB-036, REQ-PRB-037, REQ-PRB-038, REQ-PRB-039, REQ-PRB-040, REQ-PRB-041, REQ-PRB-042, REQ-PRB-043, REQ-PRB-044, REQ-PRB-045, REQ-PRB-046, REQ-PRB-047, REQ-PRB-048, REQ-PRB-049, REQ-PRB-050, REQ-PRB-051, REQ-PRB-052, REQ-PRB-053, REQ-PRB-054, REQ-PRB-055, REQ-PRB-056, REQ-PRB-057, REQ-PRB-058, REQ-PRB-059
- **WP-044c**: REQ-PRB-060, REQ-PRB-061, REQ-PRB-062, REQ-PRB-063, REQ-PRB-064, REQ-PRB-065, REQ-PRB-066, REQ-PRB-067, REQ-PRB-068, REQ-PRB-069, REQ-PRB-070, REQ-PRB-071, REQ-PRB-072, REQ-PRB-073, REQ-PRB-074, REQ-PRB-075, REQ-PRB-076, REQ-PRB-080
- **WP-045a**: REQ-CHG-001, REQ-CHG-002, REQ-CHG-003, REQ-CHG-004, REQ-CHG-005, REQ-CHG-006, REQ-CHG-007, REQ-CHG-008, REQ-CHG-009, REQ-CHG-010, REQ-CHG-011, REQ-CHG-012, REQ-CHG-013, REQ-CHG-015, REQ-CHG-016, REQ-CHG-017, REQ-CHG-018, REQ-CHG-019, REQ-CHG-020, REQ-CHG-021, REQ-CHG-022, REQ-CHG-023, REQ-CHG-024, REQ-CHG-025, REQ-CHG-026, REQ-CHG-027, REQ-CHG-028, REQ-CHG-029, REQ-CHG-030, REQ-CHG-031, REQ-CHG-032, REQ-CHG-033, REQ-CHG-034, REQ-CHG-035, REQ-CHG-036, REQ-CHG-037, REQ-CHG-038, REQ-CHG-039
- **WP-045b**: REQ-CHG-040, REQ-CHG-041, REQ-CHG-042, REQ-CHG-043, REQ-CHG-044, REQ-CHG-045, REQ-CHG-046, REQ-CHG-047, REQ-CHG-048, REQ-CHG-049, REQ-CHG-050, REQ-CHG-052, REQ-CHG-053, REQ-CHG-055, REQ-CHG-056, REQ-CHG-057, REQ-CHG-058, REQ-CHG-059, REQ-CHG-060
- **WP-045c**: REQ-CHG-062, REQ-CHG-063, REQ-CHG-064, REQ-CHG-065, REQ-CHG-066, REQ-CHG-067, REQ-CHG-068, REQ-CHG-069, REQ-CHG-070, REQ-CHG-072, REQ-CHG-073, REQ-CHG-074, REQ-CHG-075, REQ-CHG-076, REQ-CHG-077, REQ-CHG-079, REQ-CHG-080, REQ-CHG-081, REQ-CHG-082, REQ-CHG-083, REQ-CHG-084, REQ-CHG-085
- **WP-045d**: REQ-CHG-088, REQ-CHG-090, REQ-CHG-091, REQ-CHG-092, REQ-CHG-093, REQ-CHG-094, REQ-CHG-095, REQ-CHG-096, REQ-CHG-097, REQ-CHG-098, REQ-CHG-100, REQ-CHG-101, REQ-CHG-102, REQ-CHG-103, REQ-CHG-104, REQ-CHG-105, REQ-CHG-106, REQ-CHG-107, REQ-CHG-109, REQ-CHG-110, REQ-CHG-116, REQ-CHG-117
- **WP-046a**: REQ-WI-006, REQ-WI-016, REQ-WI-022, REQ-WI-024, REQ-WI-025, REQ-WI-026, REQ-INC-004, REQ-INC-007, REQ-INC-015, REQ-INC-018, REQ-INC-019, REQ-INC-025, REQ-INC-026, REQ-INC-029, REQ-INC-030, REQ-INC-031, REQ-INC-033, REQ-INC-036, REQ-INC-037, REQ-INC-039, REQ-INC-040, REQ-INC-041, REQ-INC-042, REQ-INC-048, REQ-INC-049, REQ-INC-052, REQ-INC-056, REQ-INC-062, REQ-INC-063, REQ-INC-066, REQ-INC-068, REQ-INC-069, REQ-INC-070, REQ-INC-071, REQ-INC-073, REQ-INC-074, REQ-INC-075, REQ-INC-076, REQ-INC-077, REQ-INC-078, REQ-INC-080, REQ-INC-082
- **WP-046b**: REQ-INC-083, REQ-INC-086, REQ-INC-087, REQ-INC-088, REQ-INC-150, REQ-INC-089, REQ-INC-091, REQ-INC-092, REQ-INC-099, REQ-INC-101, REQ-INC-102, REQ-INC-103, REQ-INC-107, REQ-INC-111, REQ-INC-112, REQ-INC-113, REQ-INC-114, REQ-INC-115, REQ-INC-116, REQ-INC-117, REQ-INC-121, REQ-INC-124, REQ-INC-125, REQ-INC-126, REQ-INC-127, REQ-INC-129, REQ-INC-132, REQ-INC-135, REQ-INC-141, REQ-INC-148, REQ-INC-149
- **WP-047a**: REQ-SR-013, REQ-SR-014, REQ-SR-015, REQ-SR-016, REQ-SR-017, REQ-SR-019, REQ-SR-029, REQ-SR-030, REQ-SR-031, REQ-SR-032, REQ-SR-033, REQ-SR-034, REQ-SR-035, REQ-SR-036, REQ-SR-037, REQ-SR-038, REQ-SR-039, REQ-SR-041, REQ-SR-042, REQ-SR-043, REQ-SR-044, REQ-SR-047, REQ-SR-048, REQ-SR-049, REQ-SR-050, REQ-SR-052, REQ-SR-053, REQ-SR-054, REQ-SR-056
- **WP-047b**: REQ-CAT-009, REQ-CAT-010, REQ-CAT-011, REQ-CAT-012, REQ-CAT-015, REQ-CAT-020, REQ-CAT-021, REQ-CAT-022, REQ-CAT-023, REQ-CAT-025, REQ-CAT-029, REQ-CAT-030, REQ-PRT-011, REQ-PRT-012, REQ-PRT-017, REQ-PRT-019, REQ-PRT-023, REQ-PRT-025, REQ-PRT-026, REQ-PRT-027, REQ-PRT-028, REQ-PRT-029
- **WP-048a**: REQ-SLA-006, REQ-SLA-007, REQ-SLA-008, REQ-SLA-009, REQ-SLA-011, REQ-SLA-017, REQ-SLA-021, REQ-SLA-026, REQ-SLA-030, REQ-SLA-031, REQ-SLA-032, REQ-SLA-033, REQ-ASG-005, REQ-ASG-007, REQ-ASG-008, REQ-ASG-009, REQ-ASG-010, REQ-ASG-012, REQ-ASG-013, REQ-ASG-014, REQ-ASG-015, REQ-RUL-008, REQ-RUL-011, REQ-RUL-012, REQ-RUL-013, REQ-RUL-014, REQ-RUL-015, REQ-RUL-016, REQ-RUL-017, REQ-RUL-018, REQ-RUL-019, REQ-RUL-020, REQ-RUL-021, REQ-RUL-024, REQ-RUL-025, REQ-RUL-026, REQ-RUL-027, REQ-RUL-031, REQ-WF-005, REQ-WF-006, REQ-WF-007
- **WP-048b**: REQ-WF-008, REQ-WF-009, REQ-WF-010, REQ-WF-011, REQ-WF-012, REQ-WF-013, REQ-WF-014, REQ-WF-015, REQ-WF-016, REQ-WF-017, REQ-WF-018, REQ-WF-019, REQ-WF-020, REQ-WF-021, REQ-WF-022, REQ-WF-023, REQ-WF-024, REQ-WF-025, REQ-WF-026, REQ-WF-027, REQ-WF-028, REQ-WF-029
- **WP-049a**: REQ-AST-001, REQ-AST-002, REQ-AST-003, REQ-AST-004, REQ-AST-005, REQ-AST-006, REQ-AST-007, REQ-AST-008, REQ-AST-009, REQ-AST-010, REQ-AST-011, REQ-AST-012, REQ-AST-013, REQ-AST-014, REQ-AST-015, REQ-AST-016, REQ-AST-017, REQ-AST-018, REQ-AST-019, REQ-AST-020, REQ-AST-021, REQ-AST-022, REQ-AST-023, REQ-AST-024, REQ-AST-025, REQ-AST-026, REQ-AST-027, REQ-AST-028, REQ-AST-029, REQ-AST-030, REQ-AST-031
- **WP-049b**: REQ-AST-033, REQ-AST-034, REQ-AST-035, REQ-AST-036, REQ-AST-037, REQ-AST-038, REQ-AST-039, REQ-AST-042, REQ-AST-043, REQ-AST-044, REQ-AST-045, REQ-AST-046, REQ-AST-047, REQ-AST-048, REQ-AST-049, REQ-AST-050, REQ-AST-051, REQ-AST-052, REQ-AST-053, REQ-AST-054, REQ-AST-056
- **WP-050**: REQ-DSC-001, REQ-DSC-002, REQ-DSC-003, REQ-DSC-004, REQ-DSC-005, REQ-DSC-006, REQ-DSC-007, REQ-DSC-008, REQ-DSC-009, REQ-DSC-010, REQ-DSC-011, REQ-DSC-012, REQ-DSC-013, REQ-DSC-015, REQ-DSC-016, REQ-DSC-017, REQ-DSC-018, REQ-DSC-019, REQ-DSC-020, REQ-DSC-021, REQ-DSC-022, REQ-DSC-023, REQ-DSC-025, REQ-DSC-026, REQ-DSC-027, REQ-DSC-028, REQ-DSC-029
- **WP-051**: REQ-AST-058, REQ-AST-059, REQ-AST-060, REQ-AST-061, REQ-AST-062
- **WP-052**: REQ-SAM-001, REQ-SAM-002, REQ-SAM-003, REQ-SAM-004, REQ-SAM-005, REQ-SAM-006, REQ-SAM-009, REQ-SAM-010, REQ-SAM-011, REQ-SAM-012, REQ-SAM-013, REQ-SAM-014, REQ-SAM-015, REQ-SAM-018, REQ-SAM-019, REQ-SAM-021, REQ-SAM-022
- **WP-053**: REQ-CMDB-001, REQ-CMDB-002, REQ-CMDB-003, REQ-CMDB-004, REQ-CMDB-005, REQ-CMDB-006, REQ-CMDB-007, REQ-CMDB-008, REQ-CMDB-009, REQ-CMDB-010, REQ-CMDB-011, REQ-CMDB-012, REQ-CMDB-013, REQ-CMDB-014, REQ-CMDB-015, REQ-CMDB-016, REQ-CMDB-017, REQ-CMDB-018, REQ-CMDB-019, REQ-CMDB-020, REQ-CMDB-022, REQ-CMDB-023, REQ-CMDB-024, REQ-CMDB-025, REQ-CMDB-026, REQ-CMDB-029, REQ-CMDB-030, REQ-CMDB-031, REQ-CMDB-032, REQ-INT-042, REQ-INT-043, REQ-INT-044, REQ-INT-045, REQ-INT-046, REQ-INT-047, REQ-INT-048
- **WP-054**: REQ-PUR-001, REQ-PUR-017, REQ-CON-001, REQ-CON-002, REQ-CON-003, REQ-CON-004, REQ-CON-005, REQ-CON-006, REQ-CON-007, REQ-CON-008, REQ-CON-010, REQ-CON-011, REQ-CON-012, REQ-CON-013, REQ-CON-015, REQ-CON-017
- **WP-055**: REQ-INT-006, REQ-INT-007, REQ-INT-008, REQ-INT-009, REQ-INT-010, REQ-INT-011, REQ-INT-014, REQ-INT-015, REQ-INT-018, REQ-INT-020, REQ-INT-022, REQ-INT-026, REQ-INT-027, REQ-INT-028, REQ-INT-030, REQ-INT-031, REQ-INT-032, REQ-INT-033, REQ-INT-034, REQ-INT-035, REQ-INT-036, REQ-INT-037, REQ-INT-038, REQ-INT-039, REQ-INT-052, REQ-INT-054, REQ-INT-056, REQ-INT-057, REQ-INT-069, REQ-INT-071, REQ-INT-074, REQ-INT-075, REQ-INT-085, REQ-INT-086, REQ-INT-087, REQ-INT-093, REQ-INT-100
- **WP-056**: REQ-NTF-004, REQ-NTF-005, REQ-NTF-015, REQ-NTF-016, REQ-NTF-017, REQ-NTF-018, REQ-NTF-019, REQ-NTF-021, REQ-NTF-025, REQ-NTF-027, REQ-NTF-028
- **WP-057**: REQ-SEC-009, REQ-SEC-010, REQ-SEC-011, REQ-SEC-014, REQ-SEC-015, REQ-SEC-016, REQ-SEC-021, REQ-SEC-023, REQ-SEC-026, REQ-SEC-027, REQ-SEC-030, REQ-SEC-033, REQ-SEC-034, REQ-SEC-036, REQ-SEC-037, REQ-SEC-038, REQ-SEC-040, REQ-SEC-044, REQ-SEC-045, REQ-SEC-047, REQ-AUD-011, REQ-AUD-014, REQ-AUD-015, REQ-AUD-016, REQ-AUD-017
- **WP-058a**: REQ-REL-001, REQ-REL-002, REQ-REL-003, REQ-REL-004, REQ-REL-005, REQ-REL-006, REQ-REL-007, REQ-REL-008, REQ-REL-009, REQ-REL-010, REQ-REL-011, REQ-REL-012, REQ-REL-013, REQ-REL-014, REQ-REL-015, REQ-REL-016, REQ-REL-017, REQ-REL-018, REQ-REL-019, REQ-REL-020, REQ-REL-021, REQ-REL-022, REQ-REL-023, REQ-REL-024, REQ-REL-025, REQ-REL-026, REQ-REL-027, REQ-REL-028, REQ-REL-030, REQ-REL-031, REQ-REL-032, REQ-REL-033, REQ-REL-034, REQ-REL-035, REQ-REL-037
- **WP-058b**: REQ-REL-038, REQ-REL-039, REQ-REL-040, REQ-REL-041, REQ-REL-042, REQ-REL-047, REQ-REL-048, REQ-REL-049, REQ-REL-050, REQ-REL-051, REQ-REL-052, REQ-REL-053, REQ-REL-054, REQ-REL-055, REQ-REL-056, REQ-REL-057, REQ-REL-058, REQ-REL-059, REQ-REL-060
- **WP-059a**: REQ-AI-005, REQ-AI-006, REQ-AI-007, REQ-AI-008, REQ-AI-009, REQ-AI-010, REQ-AI-011, REQ-AI-012, REQ-AI-013, REQ-AI-014, REQ-AI-015, REQ-AI-016, REQ-AI-017, REQ-AI-019, REQ-AI-020, REQ-AI-021, REQ-AI-022, REQ-AI-023, REQ-AI-024, REQ-AI-026, REQ-AI-028, REQ-AI-029, REQ-AI-030, REQ-AI-032, REQ-AI-033, REQ-AI-034, REQ-AI-035, REQ-AI-036, REQ-AI-037, REQ-AI-039
- **WP-059b**: REQ-AI-040, REQ-AI-041, REQ-AI-042, REQ-AI-043, REQ-AI-044, REQ-AI-045, REQ-AI-046, REQ-AI-047, REQ-AI-048, REQ-AI-049, REQ-AI-050, REQ-AI-051, REQ-AI-052, REQ-AI-053, REQ-AI-054, REQ-AI-056, REQ-AI-059, REQ-AI-060, REQ-AI-061, REQ-AI-062
- **WP-059c**: REQ-AI-068, REQ-AI-069, REQ-AI-070, REQ-AI-071, REQ-AI-072, REQ-AI-073, REQ-AI-074, REQ-AI-075, REQ-AI-076, REQ-AI-077, REQ-AI-078, REQ-AI-079, REQ-AI-080, REQ-AI-081, REQ-AI-104, REQ-AI-105, REQ-AI-106, REQ-AI-107
- **WP-060a**: REQ-KB-009, REQ-KB-010, REQ-KB-011, REQ-KB-014, REQ-KB-015, REQ-KB-016, REQ-KB-017, REQ-KB-018, REQ-KB-019, REQ-KB-022, REQ-KB-023, REQ-KB-024, REQ-KB-029, REQ-KB-030, REQ-KB-032, REQ-KB-036, REQ-KB-037, REQ-KB-038, REQ-KB-039, REQ-KB-040, REQ-KB-041, REQ-KB-042, REQ-KB-046, REQ-KB-047
- **WP-060b**: REQ-KB-050, REQ-KB-051, REQ-KB-054, REQ-KB-055, REQ-KB-056, REQ-KB-057, REQ-KB-058, REQ-KB-059, REQ-KB-060, REQ-KB-065, REQ-KB-066, REQ-KB-067, REQ-KB-068, REQ-KB-070, REQ-KB-071, REQ-KB-072, REQ-KB-073, REQ-KB-074, REQ-KB-075, REQ-KB-083, REQ-KB-084, REQ-KB-087, REQ-KB-088, REQ-KB-089, REQ-KB-091, REQ-KB-092
- **WP-061a**: REQ-RPT-003, REQ-RPT-007, REQ-RPT-010, REQ-RPT-011, REQ-RPT-012, REQ-RPT-014, REQ-RPT-018, REQ-RPT-020, REQ-RPT-022, REQ-RPT-023, REQ-RPT-024, REQ-RPT-025, REQ-RPT-026, REQ-RPT-027, REQ-RPT-028, REQ-RPT-030, REQ-RPT-031, REQ-RPT-032, REQ-RPT-033, REQ-RPT-034, REQ-RPT-035, REQ-RPT-036, REQ-RPT-038, REQ-RPT-039, REQ-RPT-040, REQ-RPT-041, REQ-RPT-043, REQ-RPT-046, REQ-RPT-047, REQ-RPT-049, REQ-RPT-051, REQ-RPT-052, REQ-RPT-053, REQ-RPT-054, REQ-RPT-055, REQ-RPT-056, REQ-RPT-057, REQ-RPT-066
- **WP-061b**: REQ-DSH-004, REQ-DSH-006, REQ-DSH-010, REQ-DSH-011, REQ-DSH-012, REQ-DSH-013, REQ-DSH-014, REQ-DSH-018, REQ-DSH-020, REQ-DSH-023, REQ-DSH-025, REQ-DSH-027, REQ-DSH-030, REQ-DSH-031, REQ-DSH-033, REQ-DSH-035, REQ-DSH-036, REQ-DSH-037, REQ-DSH-038, REQ-DSH-040, REQ-DSH-041, REQ-DSH-042, REQ-DSH-043, REQ-DSH-048
- **WP-062a**: REQ-ADM-005, REQ-ADM-006, REQ-ADM-007, REQ-ADM-008, REQ-ADM-011, REQ-ADM-012, REQ-ADM-014, REQ-ADM-020, REQ-ADM-022, REQ-ADM-023, REQ-ADM-024, REQ-ADM-025, REQ-ADM-026, REQ-ADM-027, REQ-ADM-029, REQ-ADM-032, REQ-ADM-033, REQ-ADM-034, REQ-ADM-036, REQ-ADM-038, REQ-ADM-042, REQ-ADM-044, REQ-ADM-046, REQ-ADM-048, REQ-ADM-053, REQ-ADM-054, REQ-ADM-056, REQ-ADM-057, REQ-ADM-061, REQ-ADM-063, REQ-ADM-065
- **WP-062b**: REQ-ADM-068, REQ-ADM-069, REQ-ADM-070, REQ-ADM-071, REQ-ADM-072, REQ-ADM-073, REQ-ADM-074, REQ-ADM-075, REQ-ADM-076, REQ-ADM-080, REQ-ADM-081, REQ-ADM-082, REQ-ADM-083, REQ-ADM-085, REQ-ADM-086, REQ-ADM-087, REQ-ADM-088, REQ-ADM-089, REQ-ADM-091, REQ-ADM-092, REQ-ADM-093, REQ-ADM-094, REQ-ADM-096, REQ-ADM-099, REQ-ADM-100, REQ-ADM-101, REQ-ADM-102, REQ-ADM-103, REQ-ADM-110, REQ-ADM-111, REQ-ADM-112, REQ-ADM-113
