> **Authority notice (D-002, 2026-10-22):** `docs/specs/architecture.md` is authoritative over this
> document on every conflict, including roadmap timing (architecture.md §17 replaces §10 below).
> In particular, SupportX does no monitoring or alert correlation (ADR-017), and migration from
> SupportX v1 is out of scope (D-005). See `docs/DECISIONS.md`.

**SupportX v2**

Product Planning Document

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<tbody>
<tr class="odd">
<td><p><strong>Building a next-generation ITSM platform that out-competes ManageEngine ServiceDesk Plus</strong></p>
<p>Based on a 47-page competitive teardown of ServiceDesk Plus (Cloud, On-Prem and MSP), October 2026</p></td>
</tr>
</tbody>
</table>

| **Item**           | **Detail**                             |
|--------------------|----------------------------------------|
| **Document**       | SupportX v2 Product Planning Document  |
| **Version**        | v0.1 (Draft for internal review)       |
| **Date**           | 22 October 2026                        |
| **Prepared by**    | Technical Project Management, Extravis |
| **Classification** | Internal / Confidential                |

**WWW.EXTRAVIS.CO**

**Contents**


# 1. Purpose and how to use this document

This document turns the ServiceDesk Plus (SDP) competitive teardown into a working plan for SupportX v2. It answers four questions: what SDP does today, where it is weak, what SupportX v2 must match, and where SupportX v2 should deliberately beat it.

It is a planning draft, not a final specification. Several sections contain columns marked "TBC" that the product and engineering teams need to complete, most importantly the SupportX v1 baseline in Section 5. Until that baseline is filled in, effort and phasing estimates should be treated as indicative.

## 1.1 Source and method

- Read-only review of 47 unique ServiceDesk Plus pages on manageengine.com, including product screenshots, the official Cloud vs On-Prem comparison (about 640 features), and the September 2026 pricing page.

- All competitor facts in this document come from that teardown. Where the vendor site was contradictory, the item is marked as unclear.

- SupportX v2 proposals are recommendations for discussion. Nothing in the plan is committed until the open decisions in Section 11 are closed.

## 1.2 Priority and phase legend

| **Code**         | **Meaning**                                                                                 |
|------------------|---------------------------------------------------------------------------------------------|
| **P0**           | Must have for launch. Without it SupportX v2 cannot credibly replace SDP in a tender.       |
| **P1**           | Strong differentiator or expected by enterprise buyers. Target in the release after launch. |
| **P2**           | Breadth feature. Needed for full ITIL coverage or specific verticals, can follow later.     |
| **Phase 0 to 3** | Delivery phases defined in Section 10 (Foundation, Core parity, Differentiation, Breadth).  |

# 2. Executive summary

ServiceDesk Plus is a mature, broad and aggressively priced ITSM and ESM platform. It has 15 years of ITIL depth, PinkVERIFY certification across up to 10 processes, a capable CMDB with baselines and data-quality scoring, and a fast-moving AI programme (Zia LLM, Zia Agents, and an MCP connector that exposes 90+ actions to Claude, ChatGPT and Copilot). A head-to-head feature race on breadth alone is not winnable in one release.

The teardown shows, however, that SDP has structural weaknesses that matter a great deal in the markets Extravis sells into, which are telecom, banking and government across MENA and South Asia:

- **Two-class deployment.** Cloud and On-Prem have diverged on 226 of about 640 compared features. Almost all AI, the sandbox, problem and asset workflows, and agent tooling are Cloud-only. Regulated customers that must stay on-prem get a reduced product.

- **No regional data residency.** SDP Cloud is hosted in the US, Canada, Europe, India, Australia, Japan and China. There is no GCC or Pakistan region.

- **ITOM lives in other products.** Alarm-to-ticket, Layer 2 discovery and dependency mapping all require OpManager or Applications Manager. There is no native event correlation, de-duplication or topology-aware root cause inside the service desk.

- **Agentic AI is gated.** Zia Agents are Enterprise-only, Agent Studio and the orchestrator are Cloud-only, and key outputs such as PIR and RCA ship as Marketplace extensions.

- **Pricing and UI complexity.** Problem, change, catalog, CMDB and projects are paid add-ons below Enterprise, ESM desks are licensed per instance, and the UI mixes 2019-era screens with the new Cloud experience.

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<tbody>
<tr class="odd">
<td><p><strong>Recommended positioning for SupportX v2</strong></p>
<p><em>"The NOC-native, sovereign, AI-agentic service management platform, with the same full product on SaaS, on-prem and air-gapped."</em></p>
<p>SupportX v2 should match SDP on core ITSM (P0), then win on five things SDP structurally cannot offer quickly: deployment parity including air-gapped, sovereign local AI, native integration with MonetX monitoring and topology, AI agents in every edition, and regional compliance packs for GCC and Pakistan regulators.</p></td>
</tr>
</tbody>
</table>

# 3. Competitor snapshot: ServiceDesk Plus

| **Dimension**              | **What the teardown found**                                                                                                                                                                 |
|----------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Vendor**                 | ManageEngine (Zoho Corp.). Marketed as an "AI-driven unified service management platform".                                                                                                  |
| **Scale claims**           | 100,000+ help desks; 37 to 40+ languages; Gartner 4.4/5 (1,214 ratings), Capterra 4.4/5, TrustRadius 9.2/10 (Feb 2026).                                                                     |
| **Certifications**         | PinkVERIFY for 10 ITIL processes (one page says 7). Zoho cloud: ISO 27001/27017/27018, SOC 2 Type II, HIPAA BA.                                                                             |
| **Deployment**             | Cloud (Zoho data centres), On-Prem (Windows/Linux, MSSQL or PostgreSQL), and a separate MSP product. FIPS mode on-prem only.                                                                |
| **Editions**               | Standard (service desk), Professional (+ asset management), Enterprise (+ problem, change, release, catalog, projects, CMDB, Zia Agents, Custom Functions).                                 |
| **Entry price**            | Cloud from US\$13 / US\$27 / US\$67 per technician per month. On-prem from US\$120 / US\$248 / US\$598 per technician per year. Free for up to 5 technicians.                               |
| **AI stack**               | Local supervised ML, Zia LLM (self-hosted open-source models such as Qwen and Llama), Zia Agents, and BYOK OpenAI, Azure OpenAI, Google AI Studio. Marketed as no extra cost and unmetered. |
| **Direction (Oct 2026)**   | New Cloud UX: always-on Ask Zia side panel, Custom Pages ("vibe-coded" screens), Peek View, dark modes, broader MCP support. All Cloud-first.                                               |
| **Key strengths to match** | ITIL breadth, mature ITAM/SAM with purchase and contracts, CMDB baselines and data quality, visual workflows with Workflow Assist, very low entry price.                                    |

## 3.1 What this means for SupportX v2

SDP wins small and mid-market deals on price and breadth. SupportX v2 should not try to undercut a free tier. It should compete where buying criteria are data residency, on-prem completeness, integration with network operations, and regulatory evidence, which is where Extravis already sells MonetX.

# 4. SupportX v2 vision and differentiation pillars

## 4.1 Vision statement

SupportX v2 is the service management platform for organisations that run critical networks and cannot compromise on where their data and AI live. It unifies IT service management, network operations and enterprise service delivery in one product that runs identically in the cloud, on-premises and fully air-gapped.

## 4.2 Target customers

- **Primary:** telecom operators, banks and financial institutions, government and public-sector bodies, and utilities in MENA and South Asia, especially existing MonetX customers.

- **Secondary:** managed service providers and shared-services organisations that need native multi-tenancy, which SDP sells as a separate MSP product.

- **Internal:** Extravis itself, since SupportX is already the support and ticketing channel for all Extravis customers. v2 must keep that use case first-class.

## 4.3 The six differentiation pillars

| **Pillar**                           | **SDP today**                                                                                 | **SupportX v2 answer**                                                                                                                                    | **Why it wins**                                                                       |
|--------------------------------------|-----------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------|
| **1. One product, every deployment** | On-prem lacks most AI, sandbox, problem and asset workflows. 226 features differ.             | Single codebase with full parity across SaaS, private cloud, on-prem and air-gapped. Offline installer and offline updates.                               | Government, banks and telcos often cannot use foreign SaaS.                           |
| **2. Sovereign AI**                  | Zia LLM is hosted only in Zoho data centres; on-prem gets a reduced AI set.                   | Local LLM shipped with the product (runs on customer GPU or CPU-optimised small models), BYOK cloud models optional per capability.                       | AI that never leaves the customer network is a tender requirement in our markets.     |
| **3. NOC-native ITSM**               | Alarm-to-ticket and L2 discovery need OpManager. No native correlation or topology-aware RCA. | Native MonetX integration: alert-to-incident with de-dup and correlation, live topology in CMDB, impact from real health data, auto-remediation runbooks. | Extravis already owns the monitoring layer. No competitor can bundle this as tightly. |
| **4. Agents in every edition**       | Zia Agents are Enterprise-only and young; Studio is Cloud-only.                               | Agent library in all paid tiers, agent builder on all deployments, human-in-the-loop approvals and outcome metrics.                                       | Clear, demonstrable AI value in every deal, not only the top tier.                    |
| **5. Regional compliance**           | Compliance is narrative only and maps global frameworks (ISO, SOC 2, DORA).                   | Built-in control mapping and evidence packs for NCA ECC, SAMA, UAE IA, Qatar NIA, SBP and PTA, plus ISO 27001.                                            | Turns audits into a feature buyers can see in a demo.                                 |
| **6. Simple, honest packaging**      | Add-on sprawl, per-instance ESM licensing, multilingual surcharge.                            | All ITIL practices in every paid tier, unlimited department desks, no language surcharge, AI included.                                                    | Easier procurement, fewer surprise costs in renewal.                                  |

# 5. Feature parity matrix

This matrix lists every SDP module from the teardown, what SupportX v1 does today, and the v2 target. The "SupportX v1 today" column is intentionally left as TBC. The product team should fill it in as Phase 0 work, because the gap between v1 and the v2 target drives effort estimates.

| **Module**                       | **ServiceDesk Plus today**                                                                                                                         | **SupportX v1 today** | **SupportX v2 target**                                                                                                                  | **Priority**              | **Phase**    |
|----------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------|-----------------------|-----------------------------------------------------------------------------------------------------------------------------------------|---------------------------|--------------|
| **Incident and request**         | Omnichannel logging, email parser, templates with form rules, drag-drop request life cycle, Kanban, auto-assign, link/merge, tasks and checklists. | TBC                   | Full parity plus unified inbox (email, portal, WhatsApp, Teams, Slack), AI triage on every deployment, alert-to-incident from MonetX.   | P0                        | Phase 1      |
| **Major incident and PIR**       | Major-incident template and workflows; AI PIR via widget or Marketplace extension.                                                                 | TBC                   | Native war room: timeline, bridge, stakeholder updates, status page; auto PIR drafted from timeline, monitoring and changes.            | P1                        | Phase 2      |
| **Problem**                      | Problem records, RCA, known errors; Zia problem prediction and life cycle (Cloud-only).                                                            | TBC                   | Known error database, incident clustering on all deployments, AI RCA using CMDB, metrics and change history.                            | P1                        | Phase 2      |
| **Change enablement**            | Templates, up to 8 stages, CAB, risk questionnaire, Zia risk prediction, calendar, freeze windows, conflict detection.                             | TBC                   | Parity, plus risk scoring from incident and monitoring history, automatic pre/post change health checks via MonetX.                     | P0 core / P1 AI           | Phase 1 to 2 |
| **Release**                      | Thin: templates, stages, calendar; DevOps limited to Jira, Azure DevOps, GitLab links.                                                             | TBC                   | Pipeline-aware releases, environments, GitHub/GitLab/Jenkins/ArgoCD hooks, auto change records from deployments.                        | P2                        | Phase 3      |
| **Service catalog**              | Service templates, up to 5-stage approvals, entitlements, costs only via extra fields.                                                             | TBC                   | Store-style catalog, native pricing and charge-back, bundles, unlimited approval stages, automated fulfilment.                          | P0                        | Phase 1      |
| **Self-service and KB**          | Portal, KB with approvals and expiry, versions (Cloud), RAG Solution Assist.                                                                       | TBC                   | AI-first portal, KCS workflow, article deflection analytics, Arabic and Urdu with RTL from day one.                                     | P0                        | Phase 1      |
| **SLA and escalation**           | Response and resolution SLAs, 1+4 escalation levels, OLAs, red-flag cues.                                                                          | TBC                   | SLA, OLA and XLA; breach prediction; prioritisation by service criticality; customer contract SLAs for MSP.                             | P0 (XLA P1)               | Phase 1 to 2 |
| **IT asset and software**        | Agent and agentless discovery, licences, financials, loan, consumables, barcode/RFID.                                                              | TBC                   | Discovery via AgentX/MonetX agents, network assets from MonetX, licence compliance, lifecycle workflows.                                | P1                        | Phase 2      |
| **CMDB**                         | CI types and relationships, business views, impact analysis, baselines, data-quality scoring, sync rules.                                          | TBC                   | Live CMDB fed by MonetX topology (LLDP/CDP), cloud discovery (AWS/Azure/GCP), impact maps with live health.                             | P1                        | Phase 2      |
| **Projects**                     | Projects, milestones, Gantt, resource heatmap, timesheets.                                                                                         | TBC                   | Basic parity: projects, tasks, Gantt, timesheets, links to changes.                                                                     | P2                        | Phase 3      |
| **Purchase and contracts**       | PO lifecycle, vendor catalog, invoices, contracts with renewals.                                                                                   | TBC                   | Vendor and contract management first (renewal alerts, SLA linkage); full purchasing later.                                              | P2                        | Phase 3      |
| **Enterprise service mgmt**      | Separate instances (up to 15), each licensed; HR desk; facilities space tree.                                                                      | TBC                   | One data model with secure department partitioning, unlimited desks, HR confidential cases, facilities floor plans.                     | P2                        | Phase 3      |
| **Automation and extensibility** | Business rules, visual workflows, Deluge custom functions with quotas, single Cloud sandbox, Qntrl Circuit.                                        | TBC                   | Visual workflow engine, Python/JS functions without quotas on-prem, config-as-code with git and multi-env promotion, endpoint runbooks. | P0 workflows / P1 sandbox | Phase 1 to 2 |
| **Reports and dashboards**       | 150+ reports, custom and scheduled reports, widget dashboards; advanced BI via Analytics Plus.                                                     | TBC                   | Built-in BI with natural-language queries, forecasting, executive and NOC wallboards.                                                   | P0 basic / P1 advanced    | Phase 1 to 2 |
| **Mobile**                       | iOS and Android technician apps; dated screenshots; no offline mode shown.                                                                         | TBC                   | Offline-capable technician app, approvals, on-call alert acknowledgement, field dispatch, Ask AI on mobile.                             | P1                        | Phase 2      |
| **Multi-site and MSP**           | Sites with own hours, SLAs and rules; MSP is a separate product.                                                                                   | TBC                   | Native multi-tenancy, customer portals, contracts and billing in the same product.                                                      | P0                        | Phase 1      |
| **Security and access**          | Custom roles, site/group scoping, SSO (AD, SAML, Entra ID, Okta), GDPR and HIPAA controls, audit logs.                                             | TBC                   | RBAC plus attribute-based rules, segregation-of-duties checks, field-level encryption, tamper-evident audit.                            | P0                        | Phase 1      |
| **AI**                           | Field prediction, GenAI assists, Ask Zia, Zia Agents (Ent), MCP (Cloud).                                                                           | TBC                   | See Section 7: local LLM, assist features on all deployments, agent library, self-hosted MCP server.                                    | P0 core / P1 agents       | Phase 1 to 2 |

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<tbody>
<tr class="odd">
<td><p><strong>Action for the team</strong></p>
<p>For each row, record v1 status as one of: Available, Partial, or Missing. Add a one-line note on what exists today. This single exercise converts the matrix into a backlog.</p></td>
</tr>
</tbody>
</table>

# 6. Where SupportX v2 beats SDP

These are the capabilities that should feature in every demo and tender response. Each one targets a gap confirmed in the teardown.

| **Capability**                   | **What it does**                                                                                                                                                                      | **Gap it exploits**                                    |
|----------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------|
| **Alert-to-incident engine**     | Ingest MonetX/Zabbix, Prometheus and syslog events; de-duplicate, correlate by topology and time, suppress alert storms; open one incident per root event and auto-close on recovery. | SDP needs OpManager and has no native correlation.     |
| **Topology-aware impact**        | Use MonetX topology and CMDB relationships to show which services and customers are affected by a failing device, with live health on the impact map.                                 | SDP impact analysis is static and partly an extension. |
| **Pre/post change health check** | Before and after a change window, automatically compare key metrics of affected CIs and flag regressions on the change record.                                                        | Not offered by SDP.                                    |
| **NOC wallboards**               | Real-time wallboards combining open incidents, SLA risk and monitoring status per site or customer.                                                                                   | SDP dashboards are generic and dated.                  |
| **Runbook automation**           | Approved scripts executed on endpoints and network devices from tickets or workflows (via AgentX agents and MonetX), with full audit.                                                 | SDP relies on Qntrl Circuit, mostly Cloud.             |
| **Config-as-code**               | All configuration exportable to git, diffable, and promotable dev to test to prod on every deployment model.                                                                          | SDP has one Cloud-only sandbox without versioning.     |
| **Regional compliance packs**    | Pre-mapped controls and evidence reports for NCA ECC, SAMA, UAE IA, Qatar NIA, SBP and PTA.                                                                                           | SDP maps only global frameworks, narratively.          |
| **Native multi-tenancy**         | Enterprise, MSP and shared-services models in one product with customer portals and contract SLAs.                                                                                    | SDP MSP is a separate SKU.                             |

## 6.1 Capabilities we must match, not beat

These are areas where SDP is strong. SupportX v2 needs credible parity but should not over-invest in trying to exceed them in the first releases:

- Breadth of ITIL practices and certification (consider PinkVERIFY assessment once Phase 2 completes).

- ITAM and SAM depth, including licence compliance, purchase and contracts.

- CMDB baselines and data-quality scoring.

- Visual workflow builder with AI-assisted creation (SDP Workflow Assist builds workflows from text, voice or an image).

- Broad integration catalogue and an MCP interface for external AI assistants.

# 7. AI and agents plan

## 7.1 AI architecture principles

- **Local first.** A local LLM ships with every deployment, including air-gapped. Cloud models (OpenAI, Azure OpenAI, Anthropic, Google) are optional per capability, with bring-your-own-key.

- **Same AI everywhere.** Every AI feature works on SaaS and on-prem. This directly answers SDP's Cloud-only AI.

- **Grounded and cited.** Answers cite KB articles, tickets, CIs or metrics. No ungrounded answers to end users.

- **Safe by design.** PII masking before any external model, per-agent permissions by role, and a full audit trail of every agent action.

- **Open interface.** A self-hosted MCP server exposes SupportX actions to approved AI assistants, on-prem as well as cloud. SDP's MCP connector is Cloud-only and depends on a Zoho account.

## 7.2 AI capabilities by phase

| **Phase**   | **Capabilities**                                                                                                                                                         |
|-------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Phase 1** | Category, priority and group prediction; reply and summary assist; RAG answers in the portal with citations; similar-ticket suggestions; AI workflow drafting from text. |
| **Phase 2** | Agent library and agent builder; problem clustering; change risk scoring; SLA breach prediction; PIR and RCA generation; sentiment; natural-language reporting.          |
| **Phase 3** | Multi-agent orchestration (for example employee onboarding across HR, IT and facilities); AIOps root cause across monitoring and ITSM; voice channel agent.              |

## 7.3 Proposed agent library

| **Agent**                | **What it does**                                                                                                                      | **Data and tools**                | **Human control**             |
|--------------------------|---------------------------------------------------------------------------------------------------------------------------------------|-----------------------------------|-------------------------------|
| **L1 Resolver**          | Answers end-user requests from KB and past tickets, performs safe actions (password reset, access request), escalates with a summary. | KB, ticket history, AD/Entra ID   | Auto for approved actions     |
| **Triage Agent**         | Sets category, priority, service and group; detects duplicates and links to open major incidents.                                     | Ticket text, CMDB, open incidents | Suggest or auto by confidence |
| **NOC First Responder**  | On a correlated alert, gathers metrics and topology, runs diagnostic runbooks, drafts the incident and likely cause.                  | MonetX events, topology, runbooks | Human approves remediation    |
| **Change Risk Reviewer** | Scores change risk from history, affected CIs and calendar conflicts; drafts rollout/backout plans and CAB summary.                   | Change history, CMDB, calendar    | Advisory to CAB               |
| **SLA Guardian**         | Predicts breaches, reprioritises or reassigns, notifies owners before the breach.                                                     | SLA timers, workload, skills      | Auto with limits              |
| **CMDB Steward**         | Finds stale, orphaned or duplicate CIs and proposes fixes from discovery data.                                                        | CMDB, discovery, MonetX           | Human approves changes        |
| **PIR and RCA Writer**   | Builds post-incident review and root-cause draft from the incident timeline, alerts and changes.                                      | Timeline, alerts, changes         | Human edits and publishes     |
| **Knowledge Author**     | Turns resolved tickets into KB drafts and flags knowledge gaps from repeated issues.                                                  | Resolved tickets, KB              | Approval workflow             |

## 7.4 Measuring AI by outcomes

SDP's Zia Dashboard reports adoption (predictions made, tokens used). SupportX v2 should report business outcomes so customers and sales can prove value:

- Ticket deflection rate and estimated hours saved.

- MTTA and MTTR before and after AI, by queue and service.

- SLA breaches prevented by prediction.

- Prediction and agent accuracy, confidence, and human override rate.

- Model cost per resolved ticket for cloud models; GPU utilisation for local models.

# 8. Platform and architecture principles

These principles are proposals for the engineering team to validate in Phase 0. They are written to protect the differentiation pillars, not to prescribe a technology stack.

| **Principle**               | **Description**                                                                                                                                        |
|-----------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Single codebase**         | One product built and released for SaaS, private cloud, on-prem and air-gapped. Feature flags control licensing, never deployment model.               |
| **Containerised delivery**  | Container-based deployment for large customers and a simplified single-host install for small sites. Offline installer and offline update bundles.     |
| **API-first**               | Every UI action backed by a documented REST API with OpenAPI spec, webhooks and an event stream. The MCP server is built on the same API.              |
| **Event ingestion layer**   | A dedicated pipeline for monitoring events (MonetX/Zabbix, Prometheus, syslog, SNMP traps) with correlation and de-duplication before ticket creation. |
| **Multi-tenant data model** | Tenant, department and site partitioning in the core data model, so MSP and ESM are configurations rather than separate products.                      |
| **Config-as-code**          | All configuration serialisable to files, version-controlled, diffable and promotable between environments.                                             |
| **Local AI runtime**        | Pluggable model serving for local LLMs, with a provider abstraction so each AI capability can use local or external models.                            |
| **Internationalisation**    | Arabic and Urdu with full RTL, site-specific locale, calendars and time zones from day one.                                                            |
| **Security baseline**       | SSO (SAML, OIDC, LDAP/AD), MFA, encryption at rest and in transit, field-level encryption for sensitive data, tamper-evident audit logs.               |
| **Migration path**          | Import tools for SupportX v1 data and for SDP exports (requests, assets, KB), to support competitive replacements.                                     |

# 9. Packaging and pricing approach

SDP's pricing matrix multiplies deployment model, edition, technician band, asset band, language, billing cycle, add-ons and ESM instances. SupportX v2 should be simpler. The tiers below are a starting proposal; actual prices need commercial input and are deliberately left out.

| **Tier**         | **Includes**                                                                                                                                                                                                     | **Intended buyer**                                     |
|------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------|
| **Essentials**   | Incident and request, portal and KB, SLA, email and chat channels, basic reports, AI assist features, mobile app.                                                                                                | Single IT team replacing a basic help desk.            |
| **Professional** | Everything in Essentials plus problem, change, release, service catalog, CMDB, IT asset management, visual workflows, agent library, MonetX integration.                                                         | Enterprise IT and NOC teams. Main tier for most deals. |
| **Enterprise**   | Everything in Professional plus unlimited department desks (ESM), native MSP multi-tenancy and billing, config-as-code and multiple environments, advanced BI, air-gapped AI runtime, regional compliance packs. | Telcos, banks, government, MSPs.                       |

## 9.1 Packaging rules to consider

- Price per technician. End users always unlimited (SDP also does this, so anything less is a disadvantage).

- All ITIL practices available from Professional, with no paid add-ons for problem, change, catalog or CMDB.

- No surcharge for Arabic, Urdu or other languages (SDP charges about 20% more for multilingual on-prem).

- AI included in all tiers; cloud model usage either BYOK or with a clear fair-use allowance.

- Bundle discount for customers who also license MonetX, to make the NOC-native story commercially concrete.

**Reference:** SDP benchmark prices are listed in Appendix A.

# 10. Phased roadmap

Durations are indicative and assume a dedicated team. They must be re-estimated once the v1 baseline (Section 5) and architecture decisions (Section 11) are complete.

| **Phase**                    | **Indicative duration** | **Scope**                                                                                                                                                                                    | **Exit criteria**                                                                         |
|------------------------------|-------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------|
| **Phase 0: Foundation**      | 4 to 6 weeks            | v1 baseline audit; customer and sales interviews; architecture decisions; data model for multi-tenancy; UX design system; MVP scope sign-off.                                                | Signed-off MVP scope, architecture document, design system, filled parity matrix.         |
| **Phase 1: Core parity**     | 4 to 6 months           | Incident and request, portal and KB, SLA, service catalog, visual workflows, RBAC and SSO, multi-tenancy, basic reports, AI assist features, MonetX alert-to-incident (basic), Arabic/RTL.   | Can replace SupportX v1 for Extravis customers and pass a standard ITSM tender checklist. |
| **Phase 2: Differentiation** | 4 to 6 months           | Problem and change (full), CMDB with MonetX topology, ITAM, major incident war room, agent library and builder, correlation engine, NOC wallboards, mobile app, config-as-code, advanced BI. | Live demo of all six pillars; at least two design-partner customers in production.        |
| **Phase 3: Breadth**         | 6 months                | Release with DevOps hooks, ESM (HR, facilities), projects, purchase and contracts, regional compliance packs, multi-agent orchestration, SDP migration tool.                                 | Full ITIL coverage; ready for certification assessment.                                   |

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<tbody>
<tr class="odd">
<td><p><strong>Design partners</strong></p>
<p>Pick two or three existing Extravis customers that already run MonetX and use SupportX as design partners from Phase 1. Their NOC and service desk teams validate the NOC-native features in real conditions and become the first reference sites.</p></td>
</tr>
</tbody>
</table>

# 11. Risks and open decisions

## 11.1 Key risks

| **Risk**                            | **Impact**                                                    | **Mitigation**                                                                                         |
|-------------------------------------|---------------------------------------------------------------|--------------------------------------------------------------------------------------------------------|
| **Scope creep chasing SDP breadth** | Launch slips; product ships wide but shallow.                 | Hold to P0 for Phase 1; win on pillars, not feature count.                                             |
| **Local AI hardware cost on-prem**  | Customers lack GPUs; poor AI performance damages perception.  | Support small CPU-friendly models for core features; publish sizing guide; optional GPU appliance.     |
| **Dependency on MonetX roadmap**    | NOC-native features blocked by MonetX changes.                | Define a stable event and topology API contract between products early.                                |
| **Shared engineering capacity**     | v2 competes with ongoing product work for the same engineers. | Ring-fence a core v2 team; agree capacity at Phase 0 sign-off.                                         |
| **Migration of v1 customers**       | Disruption to the existing Extravis support channel.          | Migration tool, parallel run period, staged rollout per customer.                                      |
| **SDP pace of change**              | SDP closes gaps (e.g. on-prem AI parity) during our build.    | Re-run the teardown every 6 months; keep focus on regional and NOC advantages they cannot easily copy. |

## 11.2 Open decisions

| **Decision**                    | **Options**                                                   | **Owner** | **Target date**       |
|---------------------------------|---------------------------------------------------------------|-----------|-----------------------|
| **Rebuild vs evolve v1**        | Extend v1 codebase, or new platform with migration.           | TBC       | End of Phase 0        |
| **Local LLM choice and sizing** | Model family, minimum hardware, CPU fallback.                 | TBC       | End of Phase 0        |
| **Multi-tenancy model**         | Shared schema with tenant IDs, or schema/database per tenant. | TBC       | End of Phase 0        |
| **Workflow engine**             | Build in-house, or embed an open-source engine.               | TBC       | End of Phase 0        |
| **Pricing levels**              | Price points per tier and MonetX bundle discount.             | TBC       | Before Phase 1 launch |
| **First compliance pack**       | NCA ECC, SAMA, SBP, or PTA first.                             | TBC       | Phase 2 planning      |

# 12. Next steps

1.  Circulate this draft to product, engineering, presales and support leads for comments.

2.  Complete the "SupportX v1 today" column in the parity matrix (Section 5).

3.  Run five to eight interviews with existing customers and presales on what they lack in SupportX and what they value in SDP-style tools.

4.  Hold architecture workshops to close the open decisions in Section 11.2.

5.  Select two or three design-partner customers.

6.  Produce the Phase 1 backlog and estimate, then update the roadmap with real dates.

# Appendix A: ServiceDesk Plus pricing benchmark

Prices as published by ManageEngine in September 2026, in US dollars per year, English edition.

Cloud (annual, by technicians and assets)

| **Tier**                                 | **Standard** | **Professional** | **Enterprise** |
|------------------------------------------|--------------|------------------|----------------|
| **Entry ("from", per tech/month)**       | \$13         | \$27             | \$67           |
| **10 techs / 500 assets**                | \$1,545      | \$2,945          | \$7,795        |
| **50 techs / 1,000 assets (Ent 2,000)**  | \$6,245      | \$13,945         | \$27,995       |
| **200 techs / 1,000 assets (Ent 3,000)** | \$19,545     | \$42,845         | \$59,795       |

On-premises (annual, English)

| **Tier**                               | **Standard** | **Professional** | **Enterprise** |
|----------------------------------------|--------------|------------------|----------------|
| **Entry ("from", per tech/year)**      | \$120        | \$248            | \$598          |
| **10 techs / 500 assets**              | \$1,195      | \$2,295          | \$5,995        |
| **200 techs**                          | \$14,995     | \$32,995         | \$45,995       |
| **Multilingual entry (per tech/year)** | \$145        | \$298            | \$723          |

Add-ons below Enterprise (Cloud / On-prem, per year)

| **Add-on**                            | **Price**                    | **Notes**                   |
|---------------------------------------|------------------------------|-----------------------------|
| **Service catalog, Problem, Project** | \$1,595 / \$1,195 each       | Standard and Professional   |
| **Change and Release**                | \$3,195 / \$2,395            | Standard and Professional   |
| **CMDB**                              | \$1,595 / \$1,195            | Professional only           |
| **Custom Functions (Cloud)**          | \$1,195 to \$5,195           | By technician band          |
| **Live chat**                         | \$65 per technician          | All editions                |
| **Remote control**                    | \$315 per concurrent session | Professional and Enterprise |
| **Failover (on-prem)**                | \$2,395                      | Standard and Professional   |

# Appendix B: Integration targets for SupportX v2

Integrations SDP lacks are the most valuable to build first, followed by those buyers expect as standard.

| **Category**              | **Priority integrations**                                                                              | **Priority**         |
|---------------------------|--------------------------------------------------------------------------------------------------------|----------------------|
| **Monitoring and events** | MonetX / Zabbix (native), Prometheus and Alertmanager, Grafana, syslog and SNMP traps, Elastic, Splunk | P0 MonetX, P1 others |
| **On-call and alerting**  | PagerDuty, Opsgenie, native on-call schedules                                                          | P1                   |
| **Identity**              | Active Directory / LDAP, Entra ID, Okta, SAML, OIDC; national e-ID where applicable                    | P0                   |
| **Collaboration**         | Microsoft Teams, Slack, WhatsApp Business, email (Exchange, Gmail), local SMS gateways                 | P0                   |
| **Endpoint and RMM**      | AgentX (native), PatchX (native), Intune, SCCM/MECM                                                    | P1                   |
| **Cloud discovery**       | AWS, Azure, GCP resource discovery into CMDB                                                           | P1                   |
| **DevOps**                | GitHub, GitLab, Jenkins, ArgoCD, Azure DevOps, Jira                                                    | P2                   |
| **Business systems**      | SAP, Oracle, Salesforce, Workday, local HRIS                                                           | P2                   |
| **AI**                    | Local LLM runtime, OpenAI, Azure OpenAI, Anthropic, Google; self-hosted MCP server                     | P0 local, P1 others  |
