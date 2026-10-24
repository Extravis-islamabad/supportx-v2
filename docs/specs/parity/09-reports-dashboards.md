# 09 — Reports and dashboards

Parity requirements for reporting (architecture.md §2.8), the visual query builder (§2.9) and
the reporting engine behind them (§6.10), and for dashboards, widgets and wallboards (§2.7,
§9.6, §8). Rules, ID scheme and field meanings: [README.md](README.md).

**Status:** Draft v0.1, 2026-10-24. Phase 2, first draft for product owner review.
**Owner:** Haider (Product Owner).

## Scope of this file

- **REQ-RPT-*** are reporting requirements: the semantic layer and query engine, the built-in
  report catalogue, custom reports and the visual query builder, charts, drill-down, folders and
  sharing, scheduling and delivery, export, query limits, the analytics store and advanced BI.
- **REQ-DSH-*** are dashboard requirements: the home page, ready-made and custom dashboards,
  widgets, live updates, the dashboard builder, filters and drill-down, sharing, wallboards and
  TV mode, scorecards, and time zone, language, right-to-left and accessibility rules for every
  chart, report and dashboard.
- **Measures come from the modules.** Each module file says which measures its records give to
  reports and dashboards. This file builds the engine, the catalogue and the screens that show
  them, and does not repeat the measure lists:
  - incidents and the engine: list export (REQ-INC-116), charting a list (REQ-INC-117), time
    analysis (REQ-INC-071), first-contact resolution (REQ-INC-102), personal counters
    (REQ-INC-128);
  - SLA: SLA result fields and events (REQ-SLA-039), paused time (REQ-SLA-018), breach reasons
    (REQ-SLA-021), experience level measures (REQ-SLA-036), notification delivery metrics
    (REQ-NTF-028);
  - problems (REQ-PRB-073, REQ-PRB-074), changes (REQ-CHG-116, REQ-CHG-117), releases
    (REQ-REL-060) and projects (REQ-PRJ-045).
  - Assets, software, contracts and purchase (file 07), knowledge (file 08), AI (file 10) and
    surveys (file 11): this file names what their reports must cover; the measures are
    defined in those files.
- **Not in this file** (each has its own module file, see the README):
  - list views, the filter builder and list export (file 01, REQ-INC-104 to REQ-INC-117);
  - the team availability calendar (file 03, REQ-ASG-009), tasks and reminders (file 01);
  - the requester portal home page (file 02);
  - AI model access and the natural-language engine (file 10); this file says how reports use
    them;
  - roles and the permission screens (file 11); this file lists the reporting permissions;
  - the MonetX connector and the read-only BI connector set-up (file 12);
  - regional compliance evidence packs (file 11).
- **Monitoring is out of scope** (ADR-017, D-001). Wallboards and dashboards may show health
  and open problems **read** from the MonetX API, read-only. SupportX never polls devices,
  never stores metric time series and never correlates alerts (REQ-INC-146).
- **Editions** (product-plan §9): basic reports and dashboards are Essentials; MonetX status
  on wallboards is Professional; advanced BI is Enterprise. **Timing** (architecture §17):
  dashboards v1 and built-in reports are Stage 1 (MVP); the report builder, the ClickHouse
  analytics store and wallboards are Stage 2 (V1).

## Words used in this file

| Word | Meaning |
|---|---|
| Report | A saved question about records: columns, filters, grouping, measures and an optional chart. |
| Built-in report | A report shipped with the product. It is read-only and can be copied. |
| Report definition | A report stored as a JSON query in the shared format (architecture §6.10). Built-in reports, custom reports and widgets use the same format. |
| Semantic layer | The model of every reportable entity: fields with labels, relationships, measures and permission rules. Users build on it, never on tables. |
| Entity | A kind of record that can be reported on, for example incident, worklog, asset or survey response. |
| Dimension | A field used to group or filter, for example priority or group. |
| Measure | A number worked out over records, for example count, average time to resolve, SLA compliance. |
| KPI | A named measure with a fixed definition, a target and thresholds, for example mean time to resolve. |
| Reporting store | Where reports read from: PostgreSQL reporting views on small installs, ClickHouse at scale. |
| Dashboard | A page of widgets with shared filters. |
| Widget | One tile on a dashboard: a KPI, chart, list, text, embedded page or a saved report. |
| Wallboard | A dashboard shown on a large screen in TV mode, read-only, often rotating between pages. |
| Display | A screen paired to show wallboards without a user signing in. |
| Scorecard | A set of KPIs with targets for one technician, group, service, site or customer. |
| Drill-down | Opening the records behind a number, bar or cell. |
| Cross-filter | Clicking a part of one widget to filter the whole dashboard. |

## Requirement summary

<!-- summary:start -->
**Counts by decision and priority**

| Decision | MVP | V1 | LATER | Total |
|---|---|---|---|---|
| SAME | 16 | 21 | 3 | 40 |
| BETTER | 19 | 20 | 1 | 40 |
| NEW | 5 | 21 | 6 | 32 |
| SKIP | 0 | 0 | 4 | 4 |
| **Total** | **40** | **62** | **14** | **116** |

Edition (lowest edition that includes it): Essentials 103, Professional 8, Enterprise 5. By prefix: REQ-RPT 66, REQ-DSH 50.

| ID | Title | Decision | Priority | Edition |
|---|---|---|---|---|
| [REQ-RPT-001](#req-rpt-001--one-reporting-engine-with-a-semantic-layer) | One reporting engine with a semantic layer | BETTER | MVP | Essentials |
| [REQ-RPT-002](#req-rpt-002--results-contain-only-what-the-viewer-may-see) | Results contain only what the viewer may see | BETTER | MVP | Essentials |
| [REQ-RPT-003](#req-rpt-003--hidden-and-masked-fields-stay-hidden-in-reports) | Hidden and masked fields stay hidden in reports | NEW | V1 | Professional |
| [REQ-RPT-004](#req-rpt-004--one-definition-for-every-standard-measure) | One definition for every standard measure | BETTER | MVP | Essentials |
| [REQ-RPT-005](#req-rpt-005--labels-never-codes-in-every-result) | Labels, never codes, in every result | BETTER | MVP | Essentials |
| [REQ-RPT-006](#req-rpt-006--reports-never-slow-down-the-service-desk) | Reports never slow down the service desk | NEW | MVP | Essentials |
| [REQ-RPT-007](#req-rpt-007--clickhouse-analytics-store) | ClickHouse analytics store | NEW | V1 | Essentials |
| [REQ-RPT-008](#req-rpt-008--fresh-data-and-the-user-knows-how-fresh) | Fresh data, and the user knows how fresh | NEW | MVP | Essentials |
| [REQ-RPT-009](#req-rpt-009--query-limits-timeouts-and-fair-use) | Query limits, timeouts and fair use | NEW | MVP | Essentials |
| [REQ-RPT-010](#req-rpt-010--caching-that-respects-permissions) | Caching that respects permissions | NEW | V1 | Essentials |
| [REQ-RPT-011](#req-rpt-011--report-definitions-as-versioned-json) | Report definitions as versioned JSON | NEW | V1 | Essentials |
| [REQ-RPT-012](#req-rpt-012--every-module-can-be-reported-on) | Every module can be reported on | SAME | V1 | Essentials |
| [REQ-RPT-013](#req-rpt-013--custom-fields-in-reports) | Custom fields in reports | SAME | MVP | Essentials |
| [REQ-RPT-014](#req-rpt-014--a-catalogue-of-at-least-150-built-in-reports) | A catalogue of at least 150 built-in reports | SAME | V1 | Essentials |
| [REQ-RPT-015](#req-rpt-015--incident-and-service-request-reports-at-go-live) | Incident and service request reports at go-live | SAME | MVP | Essentials |
| [REQ-RPT-016](#req-rpt-016--sla-reports) | SLA reports | SAME | MVP | Essentials |
| [REQ-RPT-017](#req-rpt-017--time-spent-and-worklog-reports) | Time spent and worklog reports | SAME | MVP | Essentials |
| [REQ-RPT-018](#req-rpt-018--survey-reports) | Survey reports | SAME | V1 | Essentials |
| [REQ-RPT-019](#req-rpt-019--copy-a-built-in-report-to-change-it) | Copy a built-in report to change it | SAME | MVP | Essentials |
| [REQ-RPT-020](#req-rpt-020--problem-change-and-release-reports) | Problem, change and release reports | SAME | V1 | Professional |
| [REQ-RPT-021](#req-rpt-021--project-reports) | Project reports | SAME | LATER | Professional |
| [REQ-RPT-022](#req-rpt-022--asset-software-contract-and-purchase-reports) | Asset, software, contract and purchase reports | SAME | V1 | Professional |
| [REQ-RPT-023](#req-rpt-023--knowledge-reports) | Knowledge reports | BETTER | V1 | Essentials |
| [REQ-RPT-024](#req-rpt-024--quick-reports-from-any-list) | Quick reports from any list | SAME | V1 | Essentials |
| [REQ-RPT-025](#req-rpt-025--visual-query-builder) | Visual query builder | BETTER | V1 | Essentials |
| [REQ-RPT-026](#req-rpt-026--a-column-chooser-you-can-scan) | A column chooser you can scan | BETTER | V1 | Essentials |
| [REQ-RPT-027](#req-rpt-027--calculated-columns-and-durations) | Calculated columns and durations | BETTER | V1 | Essentials |
| [REQ-RPT-028](#req-rpt-028--date-grouping-and-trend-reports) | Date grouping and trend reports | SAME | V1 | Essentials |
| [REQ-RPT-029](#req-rpt-029--filters-with-the-shared-filter-format) | Filters with the shared filter format | BETTER | MVP | Essentials |
| [REQ-RPT-030](#req-rpt-030--run-time-prompts-and-parameters) | Run-time prompts and parameters | NEW | V1 | Essentials |
| [REQ-RPT-031](#req-rpt-031--grouping-sorting-and-summaries) | Grouping, sorting and summaries | BETTER | V1 | Essentials |
| [REQ-RPT-032](#req-rpt-032--tabular-and-summary-reports) | Tabular and summary reports | SAME | V1 | Essentials |
| [REQ-RPT-033](#req-rpt-033--matrix-reports) | Matrix reports | SAME | V1 | Essentials |
| [REQ-RPT-034](#req-rpt-034--combined-reports) | Combined reports | SAME | V1 | Essentials |
| [REQ-RPT-035](#req-rpt-035--history-reports) | History reports | BETTER | V1 | Essentials |
| [REQ-RPT-036](#req-rpt-036--inventory-snapshot-reports) | Inventory snapshot reports | SAME | V1 | Professional |
| [REQ-RPT-037](#req-rpt-037--drill-down-from-any-number-to-the-records) | Drill down from any number to the records | BETTER | MVP | Essentials |
| [REQ-RPT-038](#req-rpt-038--drill-down-explorer-for-every-module) | Drill-down explorer for every module | BETTER | V1 | Essentials |
| [REQ-RPT-039](#req-rpt-039--live-preview-and-validation-while-building) | Live preview and validation while building | BETTER | V1 | Essentials |
| [REQ-RPT-040](#req-rpt-040--save-as-a-report-or-a-widget) | Save as a report or a widget | SAME | V1 | Essentials |
| [REQ-RPT-041](#req-rpt-041--report-display-options) | Report display options | BETTER | V1 | Essentials |
| [REQ-RPT-042](#req-rpt-042--read-only-sql-reports-for-advanced-administrators) | Read-only SQL reports for advanced administrators | SAME | LATER | Enterprise |
| [REQ-RPT-043](#req-rpt-043--report-versions) | Report versions | NEW | V1 | Essentials |
| [REQ-RPT-044](#req-rpt-044--one-chart-kit-for-reports-and-dashboards) | One chart kit for reports and dashboards | BETTER | MVP | Essentials |
| [REQ-RPT-045](#req-rpt-045--report-folders-and-finding-reports) | Report folders and finding reports | SAME | MVP | Essentials |
| [REQ-RPT-046](#req-rpt-046--share-reports-by-role-group-or-user) | Share reports by role, group or user | BETTER | V1 | Essentials |
| [REQ-RPT-047](#req-rpt-047--safe-defaults-when-saving) | Safe defaults when saving | BETTER | V1 | Essentials |
| [REQ-RPT-048](#req-rpt-048--reporting-permissions) | Reporting permissions | SAME | MVP | Essentials |
| [REQ-RPT-049](#req-rpt-049--ownership-moves-when-a-user-leaves) | Ownership moves when a user leaves | NEW | V1 | Essentials |
| [REQ-RPT-050](#req-rpt-050--the-report-viewer) | The report viewer | SAME | MVP | Essentials |
| [REQ-RPT-051](#req-rpt-051--print-a-report) | Print a report | SAME | V1 | Essentials |
| [REQ-RPT-052](#req-rpt-052--scheduled-reports) | Scheduled reports | SAME | V1 | Essentials |
| [REQ-RPT-053](#req-rpt-053--each-recipient-gets-their-own-data) | Each recipient gets their own data | BETTER | V1 | Essentials |
| [REQ-RPT-054](#req-rpt-054--delivery-by-email-and-to-the-report-library) | Delivery by email and to the report library | BETTER | V1 | Essentials |
| [REQ-RPT-055](#req-rpt-055--scheduling-when-mail-is-not-working) | Scheduling when mail is not working | BETTER | V1 | Essentials |
| [REQ-RPT-056](#req-rpt-056--schedule-failures-are-never-silent) | Schedule failures are never silent | BETTER | V1 | Essentials |
| [REQ-RPT-057](#req-rpt-057--email-a-report-now) | Email a report now | SAME | V1 | Essentials |
| [REQ-RPT-058](#req-rpt-058--export-to-csv-excel-and-pdf) | Export to CSV, Excel and PDF | BETTER | MVP | Essentials |
| [REQ-RPT-059](#req-rpt-059--legacy-export-formats) | Legacy export formats | SKIP | LATER | Essentials |
| [REQ-RPT-060](#req-rpt-060--read-only-bi-connector) | Read-only BI connector | NEW | LATER | Enterprise |
| [REQ-RPT-061](#req-rpt-061--a-separate-bi-add-on-is-not-needed) | A separate BI add-on is not needed | SKIP | LATER | Enterprise |
| [REQ-RPT-062](#req-rpt-062--ask-questions-in-plain-language) | Ask questions in plain language | BETTER | LATER | Essentials |
| [REQ-RPT-063](#req-rpt-063--forecasts-and-unusual-changes) | Forecasts and unusual changes | NEW | LATER | Enterprise |
| [REQ-RPT-064](#req-rpt-064--reports-across-department-desks-and-customers) | Reports across department desks and customers | NEW | LATER | Enterprise |
| [REQ-RPT-065](#req-rpt-065--report-definitions-from-servicedesk-plus) | Report definitions from ServiceDesk Plus | SAME | LATER | Essentials |
| [REQ-RPT-066](#req-rpt-066--reporting-speed-targets) | Reporting speed targets | NEW | V1 | Essentials |
| [REQ-DSH-001](#req-dsh-001--the-home-page) | The home page | SAME | MVP | Essentials |
| [REQ-DSH-002](#req-dsh-002--default-dashboard-per-role-and-the-users-own-choice) | Default dashboard per role, and the user's own choice | BETTER | MVP | Essentials |
| [REQ-DSH-003](#req-dsh-003--ready-made-dashboards) | Ready-made dashboards | SAME | MVP | Essentials |
| [REQ-DSH-004](#req-dsh-004--technician-manager-and-executive-dashboards) | Technician, manager and executive dashboards | SAME | V1 | Essentials |
| [REQ-DSH-005](#req-dsh-005--find-and-pick-dashboards) | Find and pick dashboards | SAME | MVP | Essentials |
| [REQ-DSH-006](#req-dsh-006--approvers-and-requesters-see-their-own-summary) | Approvers and requesters see their own summary | SAME | V1 | Essentials |
| [REQ-DSH-007](#req-dsh-007--widget-library) | Widget library | BETTER | MVP | Essentials |
| [REQ-DSH-008](#req-dsh-008--kpi-tiles) | KPI tiles | BETTER | MVP | Essentials |
| [REQ-DSH-009](#req-dsh-009--chart-widgets-from-a-quick-definition) | Chart widgets from a quick definition | SAME | MVP | Essentials |
| [REQ-DSH-010](#req-dsh-010--any-saved-report-as-a-widget) | Any saved report as a widget | BETTER | V1 | Essentials |
| [REQ-DSH-011](#req-dsh-011--list-widgets-with-actions) | List widgets with actions | SAME | V1 | Essentials |
| [REQ-DSH-012](#req-dsh-012--text-widgets) | Text widgets | SAME | V1 | Essentials |
| [REQ-DSH-013](#req-dsh-013--embedded-web-pages-from-allowed-sites-only) | Embedded web pages from allowed sites only | BETTER | V1 | Essentials |
| [REQ-DSH-014](#req-dsh-014--widgets-reused-across-dashboards-with-one-sharing-rule) | Widgets reused across dashboards, with one sharing rule | BETTER | V1 | Essentials |
| [REQ-DSH-015](#req-dsh-015--expand-switch-type-and-refresh-a-widget) | Expand, switch type and refresh a widget | SAME | MVP | Essentials |
| [REQ-DSH-016](#req-dsh-016--every-widget-updates-live) | Every widget updates live | BETTER | MVP | Essentials |
| [REQ-DSH-017](#req-dsh-017--connection-state-and-recovery) | Connection state and recovery | NEW | MVP | Essentials |
| [REQ-DSH-018](#req-dsh-018--live-updates-at-scale) | Live updates at scale | NEW | V1 | Essentials |
| [REQ-DSH-019](#req-dsh-019--build-dashboards-on-a-grid) | Build dashboards on a grid | BETTER | MVP | Essentials |
| [REQ-DSH-020](#req-dsh-020--sections-inside-a-dashboard) | Sections inside a dashboard | SAME | V1 | Essentials |
| [REQ-DSH-021](#req-dsh-021--copy-a-dashboard) | Copy a dashboard | SAME | MVP | Essentials |
| [REQ-DSH-022](#req-dsh-022--dashboard-filters) | Dashboard filters | BETTER | MVP | Essentials |
| [REQ-DSH-023](#req-dsh-023--click-to-filter-the-whole-dashboard) | Click to filter the whole dashboard | NEW | V1 | Essentials |
| [REQ-DSH-024](#req-dsh-024--drill-down-from-any-widget) | Drill down from any widget | BETTER | MVP | Essentials |
| [REQ-DSH-025](#req-dsh-025--compare-periods) | Compare periods | NEW | V1 | Essentials |
| [REQ-DSH-026](#req-dsh-026--private-and-shared-dashboards) | Private and shared dashboards | SAME | MVP | Essentials |
| [REQ-DSH-027](#req-dsh-027--share-by-role-group-and-user-with-view-or-edit-rights) | Share by role, group and user, with view or edit rights | BETTER | V1 | Essentials |
| [REQ-DSH-028](#req-dsh-028--each-viewer-sees-their-own-scope) | Each viewer sees their own scope | BETTER | MVP | Essentials |
| [REQ-DSH-029](#req-dsh-029--dashboard-permissions) | Dashboard permissions | SAME | MVP | Essentials |
| [REQ-DSH-030](#req-dsh-030--tv-mode-with-rotation) | TV mode with rotation | NEW | V1 | Essentials |
| [REQ-DSH-031](#req-dsh-031--displays-paired-without-a-user-sign-in) | Displays paired without a user sign-in | NEW | V1 | Essentials |
| [REQ-DSH-032](#req-dsh-032--wallboard-alert-states) | Wallboard alert states | NEW | LATER | Essentials |
| [REQ-DSH-033](#req-dsh-033--noc-wallboard) | NOC wallboard | NEW | V1 | Professional |
| [REQ-DSH-034](#req-dsh-034--service-health-board) | Service health board | NEW | LATER | Professional |
| [REQ-DSH-035](#req-dsh-035--monetx-status-widgets-read-only) | MonetX status widgets, read-only | NEW | V1 | Professional |
| [REQ-DSH-036](#req-dsh-036--scorecards) | Scorecards | NEW | V1 | Essentials |
| [REQ-DSH-037](#req-dsh-037--leaderboards) | Leaderboards | NEW | V1 | Essentials |
| [REQ-DSH-038](#req-dsh-038--targets-and-thresholds) | Targets and thresholds | NEW | V1 | Essentials |
| [REQ-DSH-039](#req-dsh-039--notify-when-a-kpi-crosses-a-threshold) | Notify when a KPI crosses a threshold | NEW | LATER | Essentials |
| [REQ-DSH-040](#req-dsh-040--measures-about-people-are-protected) | Measures about people are protected | NEW | V1 | Essentials |
| [REQ-DSH-041](#req-dsh-041--ai-usage-and-outcome-dashboard) | AI usage and outcome dashboard | BETTER | V1 | Essentials |
| [REQ-DSH-042](#req-dsh-042--operations-dashboard-for-admins) | Operations dashboard for admins | NEW | V1 | Essentials |
| [REQ-DSH-043](#req-dsh-043--dashboard-snapshots-as-pdf-and-on-a-schedule) | Dashboard snapshots as PDF, and on a schedule | NEW | V1 | Essentials |
| [REQ-DSH-044](#req-dsh-044--time-zones-in-reports-and-dashboards) | Time zones in reports and dashboards | BETTER | MVP | Essentials |
| [REQ-DSH-045](#req-dsh-045--languages-in-reports-and-dashboards) | Languages in reports and dashboards | BETTER | MVP | Essentials |
| [REQ-DSH-046](#req-dsh-046--right-to-left-charts-reports-and-exports) | Right-to-left charts, reports and exports | NEW | MVP | Essentials |
| [REQ-DSH-047](#req-dsh-047--accessible-charts-and-dashboards) | Accessible charts and dashboards | BETTER | MVP | Essentials |
| [REQ-DSH-048](#req-dsh-048--dashboards-on-phones-and-the-mobile-app) | Dashboards on phones and the mobile app | SAME | V1 | Essentials |
| [REQ-DSH-049](#req-dsh-049--no-refresh-timers-or-unexplained-switches) | No refresh timers or unexplained switches | SKIP | LATER | Essentials |
| [REQ-DSH-050](#req-dsh-050--no-anonymous-public-links) | No anonymous public links | SKIP | LATER | Essentials |
<!-- summary:end -->

---

## 1. Reporting foundation

#### REQ-RPT-001 — One reporting engine with a semantic layer

Reports, dashboard widgets, list views, counters and the AI's data answers all run through one
reporting engine. Users build against a semantic layer, not tables. For each entity it holds
the fields with their labels, the relationships to other entities, the measures and the
permission rules. A query is a JSON definition in the shared format; the engine validates it,
adds tenant and permission filters, and turns it into SQL for the reporting store.

- **Decision:** BETTER. ServiceDesk Plus builds reports, widgets, list views and its AI
  answers separately, and the same question gives different numbers in different places. One
  engine gives one answer.
- **Source:** architecture §6.10, §2.9 (reuse); sdp-area-10 §Behaviour (AI count differs from
  the dashboard); sdp-area-09 §Weak spots (chart types differ between widgets and reports)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. The same filter and grouping, run as a report, a widget and a list view, return the same
     counts for the same user.
  2. A query that names a field or relationship not in the semantic layer is refused with a
     clear problem code; no raw table or column name reaches the user.
  3. Every generated query carries the tenant filter; a test running a query for tenant A on a
     store holding tenant B data returns no tenant B row.
  4. Adding a new reportable field to the semantic layer needs no change to the report screens.

#### REQ-RPT-002 — Results contain only what the viewer may see

Every report, widget, export, scheduled delivery and AI data answer contains only records the
viewer may see, using the same scopes as lists (REQ-WI-015): all, site, group or own. Totals,
averages and percentages are worked out over the visible records only, so a hidden record
cannot be inferred from a total. A shared report shows each viewer their own data.

- **Decision:** BETTER. ServiceDesk Plus applies role scope to lists, but report sharing is
  only public or private and its effect on scope could not be confirmed. We test it on every
  path, including schedules and caches.
- **Source:** architecture §11.2, §6.10 (permission filters); sdp-area-09 §Limits (visibility to
  a non-admin technician untested); sdp-area-11 §Behaviour (report sharing)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A technician scoped to group A runs "incidents by group" and sees only group A, with a
     total equal to the group A count.
  2. The same shared report opened by a manager with scope "all" and by a group A technician
     shows each of them a different, correct total.
  3. Drilling down from a number never opens a record the viewer cannot open (no 404 after a
     click; the record is simply not counted).
  4. Removing a user's access to a site changes their open report results on the next run and
     their live widgets within 2 seconds, without a new login.

#### REQ-RPT-003 — Hidden and masked fields stay hidden in reports

Field-level visibility (REQ-WI-016) applies to reports. A field hidden from a role cannot be
chosen as a column, filter, grouping or measure by that role, and never appears in a result,
export, schedule or chart tooltip for them. A masked field shows masked and cannot be grouped
or filtered.

- **Decision:** NEW. ServiceDesk Plus has no field-level permission.
- **Source:** architecture §11.2 (field level); REQ-WI-016
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A role without visibility of the cost field does not see it in the column chooser, and a
     saved report that uses it shows the column as "not available to you" with no values.
  2. A scheduled export to that role's user leaves the hidden column out.
  3. Grouping by a masked field is refused for that role with a translated reason.

#### REQ-RPT-004 — One definition for every standard measure

Standard measures have one definition in the semantic layer, used everywhere: mean time to
acknowledge, mean time to respond, mean time to resolve, SLA compliance, first-contact
resolution rate, reopen rate, reassignment count, backlog, ageing, satisfaction score and the
module measures (REQ-PRB-073, REQ-CHG-116, REQ-REL-060). Each definition states what is
counted, the start and end events, whether paused time and business hours count, and is shown
to users as a short help text next to the measure.

- **Decision:** BETTER. In ServiceDesk Plus the AI answer said 24 open requests while the
  dashboard said 25, with no way to tell why.
- **Source:** sdp-area-10 §Behaviour, §Weak spots (24 vs 25); architecture §6.10 (measures);
  product-plan §7.4 (MTTA, MTTR)
- **SDP weak spot fixed:** two screens give different counts for "open requests" and neither
  says what it counts.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. "Open incidents" is the same number on the home counter, the helpdesk dashboard, the
     incident report and the AI answer for the same user at the same time.
  2. Each standard measure shows its definition in a tooltip in the user's language.
  3. Mean time to resolve excludes paused time when the definition says so, and a test with a
     known paused period proves it.
  4. An admin can read every measure definition; a tenant can add its own measures but cannot
     change the built-in ones.

#### REQ-RPT-005 — Labels, never codes, in every result

Every value in a report, chart, legend, tooltip, export and email goes through the labels
package (REQ-WI-013). Empty values show a clear, translatable placeholder ("not set"), not a
blank or a code.

- **Decision:** BETTER.
- **Source:** CLAUDE.md §5d; architecture §9.5; sdp-area-09 §Screens (report settings: empty
  value text)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A report grouped by status shows "In progress", never `in_progress`, in the screen, the
     CSV, the XLSX and the PDF.
  2. An admin-defined value shows its translated label in Arabic and falls back to English.
  3. Records with no priority are grouped under the "not set" placeholder in the user's
     language.

#### REQ-RPT-006 — Reports never slow down the service desk

Reports and dashboards read from the reporting store, never from the primary database that
takes writes. On small installs the reporting store is a set of PostgreSQL reporting views on
a replica; at scale it is ClickHouse (REQ-RPT-007). A heavy report can never delay saving an
incident.

- **Decision:** NEW. Architecture rule; ServiceDesk Plus runs reports on its main database.
- **Source:** architecture §6.10, §7.3 (analytics offload), §4.1 (ClickHouse optional for small
  on-prem); ADR-008
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A load test running 20 heavy reports at once keeps incident save latency within the
     REQ-WI-024 targets.
  2. No report query runs on the primary database; a test inspects the connection used.
  3. The same report gives the same result on a single-node install (PostgreSQL views) and on
     an install with ClickHouse.

#### REQ-RPT-007 — ClickHouse analytics store

At scale, an event consumer loads denormalised facts into ClickHouse from domain events
(REQ-WI-019), so aggregations over hundreds of millions of rows return in under a second. The
store can be rebuilt from PostgreSQL and the event log at any time. ClickHouse is optional on
single-node installs.

- **Decision:** NEW.
- **Source:** architecture §6.10, §7.3, §5 (analytics), §14.2, §14.4 (rebuildable); ADR-008
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A committed change reaches ClickHouse within 60 seconds at design load (REQ-SLA-039 AC1).
  2. A rebuild of one tenant's analytics data from PostgreSQL gives the same report results as
     before the rebuild.
  3. A grouped count over 100 million incident rows returns in under 1 second (p95).
  4. Redelivered events do not double-count; a test replays an event and the count stays the
     same.

#### REQ-RPT-008 — Fresh data, and the user knows how fresh

Every report and widget shows when its data was last updated. Operational numbers (counts of
open work, queues, SLA at risk, lists) reflect a committed change within 2 seconds. Analytical
numbers (trends over weeks or months, from ClickHouse) reflect it within 60 seconds. If data is
older than the expected freshness, the widget says so.

- **Decision:** NEW. ServiceDesk Plus reports show a generated-at time but widgets do not.
- **Source:** architecture §8, §9.6; sdp-area-09 §Behaviour (generated-at stamp, manual
  refresh); CLAUDE.md §5c
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Each report and widget shows an "as of" time in the user's time zone.
  2. Closing an incident lowers the "open incidents" widget within 2 seconds.
  3. If the analytics load falls more than 5 minutes behind, affected widgets show a stale-data
     marker and admins are notified.

#### REQ-RPT-009 — Query limits, timeouts and fair use

The engine protects the tenant and the platform:

- interactive queries stop after a time limit and tell the user, with a suggestion (narrow the
  date range, or run in the background);
- results over the interactive row limit run as background jobs with live progress;
- each tenant has a limit on concurrent heavy queries, and further runs queue visibly;
- the engine estimates the cost of a query before running it and warns on very large ones.

The limits are tenant settings within platform maximums (Appendix A).

- **Decision:** NEW. ServiceDesk Plus has a fixed export cap and no visible query limits.
- **Source:** architecture §6.10 (statement timeouts, row limits, background execution);
  sdp-area-14 §Screens (export capped at 3000 records)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A query that passes the interactive time limit is cancelled in the database, and the user
     sees a translated message with the "run in background" option.
  2. A report of 200,000 rows runs as a background job with progress, and the user is notified
     when it is ready.
  3. With the tenant's concurrent limit reached, the next run shows its place in the queue.
  4. One tenant running many heavy reports does not raise another tenant's report latency
     beyond the targets (REQ-RPT-066).

#### REQ-RPT-010 — Caching that respects permissions

Interactive results are cached briefly to keep dashboards fast. A cached result is reused only
for viewers with the same permission scope, and it is dropped when a relevant change event
arrives.

- **Decision:** NEW.
- **Source:** architecture §6.10 (caching), §9.6 (cached aggregations)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Two users with different scopes never receive each other's cached result; a test checks
     the cache key includes the scope.
  2. A change to an incident drops cached results that include incidents, and the next view
     shows the new number.
  3. Fifty viewers of the same dashboard with the same scope cause one query per widget, not
     fifty.

#### REQ-RPT-011 — Report definitions as versioned JSON

Every report, widget and dashboard is stored as a definition in one JSON format, with a schema
version. Built-in content ships in the same format. Definitions can be exported and imported
between tenants and environments; an import checks every field against the target tenant's
semantic layer and lists anything missing.

- **Decision:** NEW. ServiceDesk Plus cannot move report definitions between instances.
- **Source:** architecture §6.10 (prebuilt content in the same JSON format), §2.15 and
  product-plan §6 (config-as-code)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Exporting a custom report and importing it into another tenant gives the same columns,
     filters and chart.
  2. Importing a report that uses a custom field the target tenant lacks lists the missing
     field and imports nothing until it is mapped or dropped.
  3. A definition saved by an older schema version still opens after an upgrade.

#### REQ-RPT-012 — Every module can be reported on

The semantic layer covers every entity a tenant is licensed for:

- work items of every type and their parts: notes, conversations, notifications sent, tasks
  and task comments, checklists, approvals, worklogs and time spent, links, field history;
- SLA results, escalations and OLAs; surveys and their answers;
- knowledge articles and their use; announcements;
- assets, hardware details, software, licences and installations, consumables, loans,
  contracts, purchase orders, vendors, CMDB items and relationships, asset state history;
- projects, milestones and project tasks; scheduled recurring work;
- users, requesters, technicians, groups, sites, departments, organisation roles and technician
  unavailability.

Archived records (REQ-INC-118) are included when the user chooses.

- **Decision:** SAME. ServiceDesk Plus offers about 58 report modules.
- **Source:** sdp-area-09 §Fields (new custom report: module list), §Built-in reports
  (archived requests); architecture §2.8
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Each listed entity can be chosen as the starting point of a report once its module is
     built and licensed.
  2. An entity from a module outside the tenant's edition is shown disabled with an upgrade
     hint, or hidden by the admin's choice (REQ-WI-025).
  3. A report on incidents with "include archived" on counts archived incidents; with it off,
     it does not.

#### REQ-RPT-013 — Custom fields in reports

Custom fields (REQ-INC-014) of every type can be used as columns, filters, groupings and, for
number and currency fields, as measures, in built-in and custom reports and in widgets. A
custom field added by an admin is available to reports at once, with its translated label.

- **Decision:** SAME.
- **Source:** sdp-area-09 §Fields (tabular wizard: additional fields); architecture §6.6;
  REQ-INC-014
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A new pick-list custom field can be used to group a built-in report within 1 minute of
     being added, with no deployment.
  2. A currency custom field can be summed and averaged.
  3. A deleted custom field still shows its old values in reports run over the period it
     existed, labelled as removed.

---

## 2. Built-in reports

#### REQ-RPT-014 — A catalogue of at least 150 built-in reports

The product ships at least 150 built-in reports, grouped in read-only folders by module, each
with a short description of what it shows. They cover:

- incidents and service requests, SLA, time spent, satisfaction surveys;
- problems, changes, releases and projects;
- assets, software, contracts and purchase;
- knowledge, notifications, notes and announcements.

Built-in reports are definitions in the shared format (REQ-RPT-011), so customers can copy and
change them (REQ-RPT-019).

- **Decision:** SAME. ServiceDesk Plus ships about 39 folders of built-in reports.
- **Source:** sdp-area-09 §Built-in reports, §Screens (reports home); architecture §2.8,
  §6.10
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A new tenant with every module licensed shows at least 150 built-in reports.
  2. Each built-in report has a translated name and description in English and Arabic (and
     Urdu from V1).
  3. Built-in reports for unlicensed modules follow REQ-WI-025.
  4. A product upgrade can add or improve built-in reports without touching customer copies.

#### REQ-RPT-015 — Incident and service request reports at go-live

The MVP catalogue covers incidents and service requests:

- all, open, completed and canceled, by category, priority, group, technician, site,
  department, requester, channel, level and status;
- received and completed per day, week and month, and the open backlog over time;
- ageing of open work in buckets (Appendix A);
- first-contact resolution (REQ-INC-102) by category, group, priority and technician;
- reopen counts, reassignment counts, on-hold counts and on-hold periods;
- average response and resolution time;
- approvals: by approver and approval status.

- **Decision:** SAME.
- **Source:** sdp-area-09 §Built-in reports (request reporting: all, incident, service,
  completed, pending, summary, metrics, average response and resolution, assessment)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A new tenant has every listed report, and each runs with no set-up.
  2. "Reopen count by technician" for last month matches the reopen counters on the records.
  3. The ageing report puts an incident open for 4 days into the "3 to 7 days" bucket.

#### REQ-RPT-016 — SLA reports

SLA reports use the SLA result fields (REQ-SLA-039):

- compliance and breaches by group, technician, priority, category, site, service and customer
  contract, for first response and resolution;
- work approaching breach now, and breached work still open;
- breach reasons (REQ-SLA-021) and paused time (REQ-SLA-018);
- OLA results shown apart from SLA results;
- experience level measures per service (REQ-SLA-036), when enabled.

- **Decision:** SAME.
- **Source:** sdp-area-09 §Built-in reports (SLA violated requests); sdp-area-01 §Config
  (canned SLA widgets); architecture §2.6 (compliance reports and widgets)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. "Resolution compliance by group, last month" matches the met and breached counts in the
     records (REQ-SLA-039 AC3).
  2. "Approaching breach" lists exactly the open records past their warning threshold, live.
  3. An incident breached and then reopened counts once as breached in last month's report.

#### REQ-RPT-017 — Time spent and worklog reports

Time reports cover time in each status, with each group and each technician; running, idle and
paused hours (REQ-INC-071); worklog hours per technician, group, record type and period; and,
from V1, billable time and worklog cost (REQ-INC-068).

- **Decision:** SAME.
- **Source:** sdp-area-09 §Built-in reports (request time spent reports), §Fields (module list:
  time spent, worklogs); D-047
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Time in status for one incident in the report equals its time analysis on the record.
  2. Worklog hours per technician for a week equal the sum of their worklogs that week.
  3. Billable and cost columns are present only from V1 and only for roles allowed to see cost.

#### REQ-RPT-018 — Survey reports

Satisfaction survey reports show the overview and results by category, department, level,
channel, priority, requester, technician, group and service, with response rates and trend over
time.

- **Decision:** SAME.
- **Source:** sdp-area-09 §Built-in reports (survey reports); REQ-INC-103
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. The overview shows the response rate as responses divided by surveys sent in the period.
  2. Results by technician are visible only to roles allowed to see per-person results
     (REQ-DSH-040).

#### REQ-RPT-019 — Copy a built-in report to change it

Any built-in report can be copied into the user's own folder, then changed and saved. Before
the report builder exists (V1), a copy can change the date range, filters, columns, grouping
and chart. The original stays untouched.

- **Decision:** SAME.
- **Source:** sdp-area-09 §Actions (save report as on a built-in report); architecture §6.10
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Copying "open incidents by priority" and adding a site filter saves a new private report;
     the built-in one is unchanged.
  2. A built-in report cannot be edited or deleted; its edit action is disabled with a reason.

#### REQ-RPT-020 — Problem, change and release reports

The catalogue includes the problem, change and release reports and measures their module files
ask for: REQ-PRB-073, REQ-CHG-116 and REQ-REL-060. Each chart drills down to the records
behind it (REQ-RPT-037).

- **Decision:** SAME.
- **Source:** sdp-area-09 §Built-in reports (problems, changes, releases); REQ-PRB-073;
  REQ-CHG-116; REQ-REL-060
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Every measure listed in REQ-PRB-073, REQ-CHG-116 and REQ-REL-060 is available as a
     report and as a widget.
  2. "Changes that caused incidents" drills down to the list of those changes.

#### REQ-RPT-021 — Project reports

The catalogue includes the project reports of REQ-PRJ-045: by status, priority and type;
estimated against actual hours and cost; overdue and delayed work; time per member; closed and
canceled per quarter; projects by linked requests.

- **Decision:** SAME.
- **Source:** sdp-area-09 §Built-in reports (projects); REQ-PRJ-045
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Results respect project visibility (REQ-PRJ-013) and the cost permission.
  2. "Estimated against actual hours" per project matches the project's own summary.

#### REQ-RPT-022 — Asset, software, contract and purchase reports

The catalogue includes asset and finance reports (data from file 07):

- computers, servers and workstations; assets by product type, vendor, site and state;
- software installed, licences, licence users and compliance;
- depreciation; asset loans; inventory scan history by computer, timeline and changes;
- contracts by status, expiry and vendor; purchase orders by status, vendor and cost.

- **Decision:** SAME.
- **Source:** sdp-area-09 §Built-in reports (assets, contracts, purchase); architecture §2.8,
  §2.11
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. "Contracts expiring in the next 30 days" lists exactly those contracts.
  2. The depreciation report's value for an asset equals the value on the asset record.

#### REQ-RPT-023 — Knowledge reports

Knowledge reports show more than template use: article views, use in resolutions, deflection
(portal searches or article views not followed by a new request), helpful and unhelpful votes,
articles due for review or expired, and knowledge gaps (frequent incident topics with no
article). Data comes from file 08.

- **Decision:** BETTER. ServiceDesk Plus has one knowledge report (most used solution
  templates).
- **Source:** sdp-area-09 §Built-in reports (solutions); product-plan §5 (article deflection
  analytics)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. An article linked to 12 resolved incidents last month shows 12 uses in resolutions.
  2. The deflection rate is shown with its definition (REQ-RPT-004).

#### REQ-RPT-024 — Quick reports from any list

From any list, a user can turn the current view into a report with the same filters and
columns, or into a quick chart (REQ-INC-117). A set of one-click quick charts per module (for
example "open by status", "created this week by day") is available without building anything.

- **Decision:** SAME. Covers the "flash report" and instant graph capability.
- **Source:** architecture §2.8 (flash reports), §2.7 (instant graph view inside any list view);
  REQ-INC-117
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. "Save as report" on a filtered incident view creates a report with the same filter and
     columns, and the counts match.
  2. Each module with a list offers at least three quick charts.

---

## 3. Custom reports and the visual query builder

#### REQ-RPT-025 — Visual query builder

Users build reports in a visual query builder, without SQL. They pick a starting entity, then
add related entities (requester, technician, group, asset, configuration item, SLA results,
approvals, tasks) by following relationships; joins are made automatically. The builder shows
each step on one screen with the result preview beside it, not in collapsed numbered steps.

- **Decision:** BETTER. ServiceDesk Plus uses a step wizard with a fixed module list and no way
  to follow relationships.
- **Source:** architecture §2.9 (entity selection), §6.10; sdp-area-09 §Fields (new custom
  report, tabular wizard), §Weak spots (collapsed steps hide errors)
- **SDP weak spot fixed:** the wizard's collapsed numbered steps hide errors.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A user builds "incidents with the requester's department and the linked asset's model"
     without typing any query text.
  2. Adding a related entity with a one-to-many link (incident to tasks) offers a choice:
     one row per task, or a measure per incident (for example task count); the preview shows
     the effect.
  3. Every builder action is keyboard reachable and works in right-to-left layout.

#### REQ-RPT-026 — A column chooser you can scan

Columns are grouped by entity and kind (people, dates, times, classification, custom fields),
searchable by label, and show recently used columns first. The chosen columns can be
reordered by dragging or with the keyboard.

- **Decision:** BETTER.
- **Source:** sdp-area-09 §Fields (tabular wizard: about 125 request columns), §Weak spots
  (125 entries in one flat list)
- **SDP weak spot fixed:** about 125 columns in one flat list.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Typing "due" lists every due-date column of the chosen entities and nothing else.
  2. Columns are shown under group headings, and custom fields sit in their own group.
  3. Reordering with the keyboard gives the same result as dragging.

#### REQ-RPT-027 — Calculated columns and durations

Users can add calculated columns: arithmetic on number fields, conditions ("if priority is P1
then ..."), text joins, date differences, and ready-made durations (time to respond, time to
resolve, time in status, time with a group), each in calendar time or business time under the
record's SLA calendar (REQ-SLA-013). Formulas are built with a guided editor that checks them
as they are typed.

- **Decision:** BETTER. ServiceDesk Plus has fixed time columns and no calculated columns.
- **Source:** architecture §2.8 (calculated columns), §2.9 (calculated fields, duration
  calculations)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. "Resolution business hours" for an incident equals the business time shown on the record.
  2. A formula with an error shows the error at the place it occurs before the report can be
     run.
  3. A calculated column can be used for grouping, sorting and filtering.

#### REQ-RPT-028 — Date grouping and trend reports

Any date can be grouped by hour, day, week, month, quarter or year, and by hour of day or day
of week. Trend reports show a measure over time, with empty periods shown as zero, not
skipped. Weeks start on the day the tenant sets.

- **Decision:** SAME.
- **Source:** architecture §2.9 (date bucketing), §2.8 (trend reports); sdp-area-09 §Fields
  (matrix wizard: column grouping with a date format)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Incidents per week over 12 weeks shows 12 points, including weeks with zero.
  2. In a tenant whose week starts on Saturday, the weekly grouping starts on Saturday.
  3. A heatmap of volume by hour of day and day of week uses the viewer's time zone
     (REQ-DSH-044).

#### REQ-RPT-029 — Filters with the shared filter format

Reports use the same filter format and builder as lists, rules and SLAs (REQ-INC-106): AND
and OR groups, type-appropriate operators, relative dates and empty or not empty. The date
filter names the date field and the period together in one control, and its default is shown
in words ("created in the last 30 days"). A filter row with a field but no value cannot be run.

- **Decision:** BETTER.
- **Source:** architecture §2.9 (filters), §6.5 (filter DSL); sdp-area-09 §Fields (filter
  options: date filter periods, advanced filter operators), §Weak spots (filter without value
  ran; "during" defaults to today with no date column)
- **SDP weak spot fixed:** a filter column with no value runs silently, and the date filter
  defaults to "today" with no date column, which is easy to misread.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A filter saved in a list view can be applied to a report unchanged, and the reverse.
  2. A filter row with a field and no value shows an inline error and the run action is
     disabled with a reason.
  3. Every period in the reference (today, this and last week, month, quarter and year, last
     7, 30 days, 6 and 12 months, next 7 and 30 days and so on) and a custom range is
     available.

#### REQ-RPT-030 — Run-time prompts and parameters

A report can ask for values when it runs: a date range, a group, a site, a technician or any
filter field. Defaults are set by the author. Scheduled runs use the defaults or values set on
the schedule. A dashboard filter can feed a report widget's parameters.

- **Decision:** NEW. ServiceDesk Plus reports have fixed filters.
- **Source:** architecture §2.9 (run-time prompts and parameters)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Opening a report with a "group" prompt asks for the group before running, with the
     default preselected.
  2. A schedule of the same report can set a different group for its runs.
  3. A prompt only offers values the viewer may see.

#### REQ-RPT-031 — Grouping, sorting and summaries

Reports can group by several levels, sort by any column or measure, and show summary rows per
group and in total: count, distinct count, sum, average, minimum, maximum, median and
percentiles (for example the 90th percentile of resolution time). Groups can be limited to the
top N with the rest as "others".

- **Decision:** BETTER. Adds distinct count, median, percentiles and top N to ServiceDesk
  Plus's count, sum, average, minimum and maximum.
- **Source:** sdp-area-09 §Fields (tabular wizard: group by, summary type); architecture §2.9
  (aggregation, percentiles)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Grouping by group then priority shows a subtotal per group and a grand total.
  2. The 90th percentile of resolution time on a known data set equals the value computed in
     the test.
  3. Top 5 categories with "others" adds up to the full total.

#### REQ-RPT-032 — Tabular and summary reports

A tabular report lists records with chosen columns, optionally grouped with summaries. A
summary report shows only the grouped measures, without the record rows. Both can have a chart.

- **Decision:** SAME.
- **Source:** sdp-area-09 §Fields (type: tabular), §Behaviour (test report); architecture §2.8
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A tabular report of 41 records shows the total "41 records" and pages through them.
  2. Switching a grouped tabular report to summary keeps the groups and measures and hides the
     rows.

#### REQ-RPT-033 — Matrix reports

A matrix report shows a measure in a grid: one or more fields down the side and one or more
across the top, with dates grouped by period, totals per row and column, and colour scaling
of cells. Any summary report can be pivoted to a matrix.

- **Decision:** SAME.
- **Source:** sdp-area-09 §Fields (matrix wizard: simple and advanced matrix, column grouping);
  architecture §2.9 (pivot to matrix)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Priority by group, counting open incidents, shows row and column totals that equal the
     grand total.
  2. A cell drills down to the records behind it (REQ-RPT-037).
  3. A matrix with months across the top shows each month of the range, including empty ones.

#### REQ-RPT-034 — Combined reports

A combined report puts several reports (sub-reports) on one module into one output, for
example an asset summary with loan details, or a monthly service review pack with SLA,
volumes and satisfaction. It runs, exports and schedules as one.

- **Decision:** SAME.
- **Source:** sdp-area-09 §Fields (type: summary; summary wizard with sub-reports)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A combined report of three sub-reports exports to one PDF with each part under its own
     heading.
  2. Each part applies the viewer's permissions on its own entity.

#### REQ-RPT-035 — History reports

A history report shows changes over time from field history (REQ-WI-003): who changed which
field, from what, to what, when and through which source. Examples: "priority changes by
rules last month", "status changes per incident", "asset state history", "assignments moved
between groups". It also answers "what was the state on a date", for example the open backlog
as it was on the first of each month.

- **Decision:** BETTER. ServiceDesk Plus has history report modules for asset state and audit
  only; we report on the history of every record type, including the source of each change.
- **Source:** architecture §2.8 (audit reports), §7.4; sdp-area-09 §Fields (module list: asset
  audit, asset state history); REQ-WI-003; REQ-WI-004
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. "Priority changes made by rules last week" lists each change with the rule's name.
  2. "Open backlog on the first of each month" for the last six months gives six values that
     match a manual count from history.
  3. History rows show labels for old and new values, never codes.

#### REQ-RPT-036 — Inventory snapshot reports

An inventory snapshot report shows asset and software inventory as it was at each scan time,
for example software installed on a computer over time or hardware changes between scans.
Data comes from discovery (file 07).

- **Decision:** SAME. Covers the vendor's scan report type.
- **Source:** sdp-area-09 §Fields (type: scan), §Built-in reports (scan reports); architecture
  §2.8
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A computer scanned on two dates shows the software added and removed between them.
  2. The report shows the scan time of each snapshot in the viewer's time zone.

#### REQ-RPT-037 — Drill down from any number to the records

Every number, bar, slice, point and matrix cell in a report or widget opens the list of records
behind it. The list uses the same filters, so its row count equals the number clicked. From
the list the user can open any record, keep filtering, or save the list as a view.

- **Decision:** BETTER. In ServiceDesk Plus drill-down is a separate tool for requests only.
- **Source:** architecture §2.7 (drill-down to records), §9.6 (interactive); sdp-area-09
  §Weak spots (drill-down limited to requests)
- **SDP weak spot fixed:** no drill-down for problems, changes or assets.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Clicking the "P1" bar showing 8 opens a list of exactly 8 incidents.
  2. Drill-down works the same on incidents, service requests and, once built, problems,
     changes, releases, assets and projects.
  3. The drill-down list can be saved as a private view in one action.

#### REQ-RPT-038 — Drill-down explorer for every module

A drill-down explorer starts from a total for a period (for example all incidents created this
quarter, with open, completed and SLA breached counts) and splits it step by step by any
dimension: site, group, department, requester, technician, priority, category and so on. Each
branch shows its count and can be split again or opened as a list. It works for every
reportable entity.

- **Decision:** BETTER. Same exploration, for every module instead of requests only.
- **Source:** sdp-area-09 §Screens (drill down analysis), §Behaviour (drill down), §Weak spots
- **SDP weak spot fixed:** the explorer works only on requests.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Splitting 41 incidents by priority shows branch counts that add up to 41.
  2. The explorer works on changes and assets with the same controls.
  3. The explorer is usable with the keyboard and a screen reader, with the tree also shown as
     an indented list.

#### REQ-RPT-039 — Live preview and validation while building

The builder shows a live preview of the first rows and the chart as the user changes columns,
filters or grouping. Errors show where they occur, at once. The report cannot be saved or run
in a state that cannot work, and the reason is shown.

- **Decision:** BETTER.
- **Source:** architecture §2.9 (live preview); sdp-area-09 §Weak spots (errors hidden, run
  with defaults); REQ-WI-009
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Changing the grouping updates the preview within 2 seconds on a tenant of 1 million
     incidents.
  2. A matrix with no row field shows an inline error and the save action is disabled with a
     reason.
  3. A preview over the interactive limit shows a sample with a clear "sample" label.

#### REQ-RPT-040 — Save as a report or a widget

A built report can be saved as a report in a folder (REQ-RPT-045), as a dashboard widget, or
both. Saving asks for a name, an optional description and the folder; sharing is set
separately (REQ-RPT-046). An unsaved run shows as "unsaved" and can be saved later.

- **Decision:** SAME.
- **Source:** sdp-area-09 §Fields (save report dialog), §Behaviour (unsaved report);
  architecture §2.9 (save as report or dashboard widget)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Saving a report as a widget places it on a chosen dashboard and it shows the same numbers.
  2. Closing an unsaved report asks before discarding it.

#### REQ-RPT-041 — Report display options

Each report can set display options: show or hide links to records, start each group on a new
page in PDF, the text for empty values, cell size for matrices, and number formats. Column
widths fit the content automatically and can be dragged. Dates use the shared formatter
(REQ-WI-014); a report can choose a date grouping format. Tenant-wide defaults are set by an
admin.

- **Decision:** BETTER. ServiceDesk Plus sets column widths in pixels per data type for the
  whole instance.
- **Source:** sdp-area-09 §Screens (report settings: column widths, disable links, one group
  per page, empty value text, matrix cell size, date formats)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. With "start each group on a new page" on, a PDF of a report grouped by group has one
     group per page.
  2. Column widths fit the longest value up to a maximum, with no pixel set-up.
  3. Changing the tenant default for empty values changes reports that do not set their own.

#### REQ-RPT-042 — Read-only SQL reports for advanced administrators

Advanced administrators can write SQL reports. They run read-only against reporting views that
already apply tenant and permission filters, with a statement time limit and a row limit. The
editor offers the view and column names of the semantic layer, with completion. Results can be
charted, saved, shared and scheduled like any report.

- **Decision:** SAME. The vendor's cloud edition has no SQL report type; architecture asks for
  one.
- **Source:** architecture §2.8 (SQL query reports), §6.10 (safe SQL mode), §7.5;
  sdp-area-09 §Edition notes (no raw SQL report type)
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. A SQL report that tries to write (insert, update, delete, DDL) is refused before it runs.
  2. A SQL report run by a technician scoped to group A returns only group A rows.
  3. A query over the time limit is cancelled and the author sees the limit in the message.
  4. Only roles with the "SQL reports" permission can create or edit them; others can run
     shared ones.

#### REQ-RPT-043 — Report versions

Each save of a shared report or dashboard keeps a version with who changed it and when. The
owner can compare two versions and restore an earlier one.

- **Decision:** NEW. ServiceDesk Plus keeps no report history.
- **Source:** architecture §7.4 (history for every change)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Restoring the previous version of a report brings back its columns and filters, and the
     restore itself is a new version.
  2. The version list shows editor, time and a summary of what changed.

---

## 4. Charts and the report viewer

#### REQ-RPT-044 — One chart kit for reports and dashboards

Reports and widgets use one chart kit on Apache ECharts, with the same types, colours and
behaviour everywhere: bar, stacked and grouped bar, line, area and stacked area, pie and
doughnut, gauge, funnel, KPI tile with sparkline, table, heatmap, treemap, sankey, calendar
heatmap, map per site and top-N leaderboard. Values keep their colour on every chart (P1 is
always the same colour). Three-dimensional charts are not offered.

- **Decision:** BETTER. In ServiceDesk Plus the same data looks different in widgets and in
  reports, and 3D charts distort values.
- **Source:** architecture §9.6 (widget library), §5; sdp-area-09 §Fields (graph types, chart
  types), §Weak spots (chart types differ between widgets and reports)
- **SDP weak spot fixed:** chart types differ between widgets (2D and 3D pie) and reports
  (doughnut, pyramid, dial).
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A chart saved in a report and the same chart as a widget render with the same type,
     colours and order.
  2. "Critical" has the same colour on every chart for that tenant.
  3. The MVP ships bar, stacked bar, line, area, doughnut, gauge, KPI tile and table; the other
     types follow at V1.
  4. Large series (100,000 points) render without freezing the page.

#### REQ-RPT-045 — Report folders and finding reports

Reports live in folders. Built-in folders are read-only. Each user has a private "My reports"
folder, and users with permission create shared folders. The reports home shows folders with
owner, report count and sharing, a search over report names and descriptions, favourites and
recently run reports. Reports can be moved between folders.

- **Decision:** SAME.
- **Source:** sdp-area-09 §Screens (reports home: folder tree, new folder, organise folders),
  §Actions (folder actions)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Searching "SLA" lists every report whose name or description contains it, in the user's
     language.
  2. A built-in folder cannot be renamed, deleted or saved into.
  3. Deleting a shared folder that holds reports asks where to move them first.

#### REQ-RPT-046 — Share reports by role, group or user

A report or folder can be shared with roles, groups or users, with view or edit rights. Shared
reports still apply each viewer's own data scope (REQ-RPT-002). The report shows who it is
shared with.

- **Decision:** BETTER. ServiceDesk Plus offers only public or private.
- **Source:** architecture §2.8 (report folders with permissions); sdp-area-11 §Behaviour
  (report sharing public or private only), §Limits; sdp-area-09 §Limits
- **SDP weak spot fixed:** no sharing by role, group or user.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A report shared with group A appears for group A members and no one else.
  2. A user with view rights can run and copy it but not change it.
  3. Sharing a folder shares the reports in it, and the report shows that it inherits the
     folder's sharing.

#### REQ-RPT-047 — Safe defaults when saving

A new report is private and saved to "My reports" unless the user chooses otherwise. Saving to
a shared folder, or sharing a report, shows who will be able to see it before confirming.

- **Decision:** BETTER.
- **Source:** sdp-area-09 §Weak spots (save dialog defaults to a system folder; new folder only
  through a small "+")
- **SDP weak spot fixed:** the save dialog lists only system folders and saves into one by
  default.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Saving with no choices made puts the report in "My reports", private.
  2. A new shared folder can be created from the save dialog with a visible action, not an
     icon alone.

#### REQ-RPT-048 — Reporting permissions

Roles carry reporting permissions: run reports, create and edit own reports, share reports,
manage shared folders, schedule reports, send reports to external addresses, export, SQL
reports, and see per-person measures (REQ-DSH-040). Each is granted on its own. Built-in
roles show what they grant (REQ-WI-015).

- **Decision:** SAME.
- **Source:** sdp-area-11 §Screens (role matrix: reports row), §Fields (role "SDReport"),
  (advanced permissions: export from list view); architecture §11.2
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A role without "export" sees export disabled with a reason, and the API refuses it with
     403.
  2. A role with "run reports" only can run and drill down but sees create and edit disabled.
  3. Removing "schedule reports" from a role pauses that role's users' schedules and tells
     them why.

#### REQ-RPT-049 — Ownership moves when a user leaves

When a user is deactivated, their shared reports, dashboards and schedules do not break. An
admin is asked to pick a new owner. Until then shared items keep working, private items are
kept for the retention period, and schedules pause with a notice to the admin.

- **Decision:** NEW. Not observed in ServiceDesk Plus.
- **Source:** architecture §2.8 (report folders with permissions); REQ-WI-009 (no silent
  failures)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Deactivating a user with 3 schedules pauses them and creates an admin task listing them.
  2. Transferring ownership moves reports, dashboards and schedules to the new owner, and each
     move is in the audit log.

#### REQ-RPT-050 — The report viewer

A report opens with a header: the tenant logo, title, description, who ran it, when, the time
zone, the filters and date range applied (in words), and the total record count. Rows are
paged. The user can switch between table and chart, sort by any column, change prompts and
filters and run again, and see the definition of each measure. A built-in report runs on open
with its default range shown, which the user can change.

- **Decision:** SAME.
- **Source:** sdp-area-09 §Screens (report view), §Actions (graph view toggle), §Behaviour
  (built-in report runs on open with the current week)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. The header lists the applied filters in words, in the user's language.
  2. Switching between table and chart keeps the filters and page.
  3. A built-in report opens with its default range visible in the filter bar, not hidden.

#### REQ-RPT-051 — Print a report

A report can be printed from a print preview that shows exactly what will print, with header,
filters, page numbers and the chart.

- **Decision:** SAME.
- **Source:** sdp-area-09 §Actions (print preview); REQ-INC-126
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. The print preview of a report and its PDF export have the same pages.
  2. Printing in Arabic gives a right-to-left page with Arabic labels (REQ-DSH-046).

---

## 5. Scheduling, delivery and export

#### REQ-RPT-052 — Scheduled reports

A report, combined report or dashboard snapshot (REQ-DSH-043) can be scheduled: once, daily,
on chosen weekdays, weekly, monthly (by date or by "first Monday"), or quarterly, at a time in
a chosen time zone, with a start and optional end date. Recipients are users, groups or (with
permission) external addresses. Each schedule has a format, a subject and a message. The
schedules list shows report, next run, last result, owner and recipients.

- **Decision:** SAME.
- **Source:** sdp-area-09 §Fields (new scheduled report), §Screens (schedule reports tab),
  §Automation; architecture §2.8 (scheduled reports by email), §6.10 (execution)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A weekly schedule for Monday 07:00 Asia/Riyadh runs at that time across a daylight-saving
     change in the owner's zone.
  2. The schedules list shows the next run time and the result of the last run for each.
  3. A schedule with an end date stops after it and shows as finished.

#### REQ-RPT-053 — Each recipient gets their own data

A scheduled report is run separately for each user recipient with that user's permissions, so
nobody receives rows they cannot see. Reports to external addresses run with the owner's
permissions, need the "send to external addresses" permission, are off by default per tenant,
and are audited.

- **Decision:** BETTER. Prevents a schedule from leaking data the recipient cannot see.
- **Source:** architecture §11.2, §11.3; sdp-area-09 §Fields (to: free addresses)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. One schedule to a manager (scope all) and a technician (scope group A) sends two different
     results, each matching what they see on screen.
  2. Adding an external address without the permission is refused with a reason.
  3. Every delivery to an external address creates an audit entry with the report, the
     address and the row count.

#### REQ-RPT-054 — Delivery by email and to the report library

Each run is delivered by email, to the report library, or both. Email carries the file as an
attachment up to a size limit and otherwise a secure link that needs sign-in and expires; it
can also carry the summary inline in the body. The report library keeps each run's output for
a set period, so earlier runs can be opened again.

- **Decision:** BETTER. Adds the report library, secure links for large files and expiry.
- **Source:** architecture §6.10 (deliver by email or to the report library); sdp-area-09
  §Fields (format: inline HTML)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. An output above the attachment limit arrives as a link; opening it asks for sign-in and
     works only for that recipient.
  2. The link stops working after its expiry (Appendix A).
  3. The report library lists each run with time, format, size and row count, and removes them
     after the retention period.

#### REQ-RPT-055 — Scheduling when mail is not working

If outgoing mail is not configured, the schedule form says so at the top before anything is
filled in, and offers delivery to the report library instead. "Email this report" is shown
disabled with the reason. When mail starts working, pending email deliveries can be resent.

- **Decision:** BETTER.
- **Source:** sdp-area-09 §Behaviour (schedule form, mail warning), §Weak spots (form can be
  filled while mail is missing); REQ-INC-060
- **SDP weak spot fixed:** the mail error is only a banner, and every field can still be filled
  in.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. With no mail server, the schedule form preselects the report library and explains why.
  2. "Email this report" is disabled with a translated reason.

#### REQ-RPT-056 — Schedule failures are never silent

A failed scheduled run (timeout, too many rows, mail rejected, owner lost permission) is shown
on the schedule with the reason, the owner is notified in the app, and the run can be retried.
Three failures in a row pause the schedule and tell the owner.

- **Decision:** BETTER.
- **Source:** REQ-WI-009; sdp-area-09 §Automation (scheduled delivery could not be tested
  without mail)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A run that times out shows "failed: took too long" on the schedule and notifies the owner.
  2. After three failures in a row the schedule pauses, and the owner can resume it.
  3. Admins can list all failed schedules in the tenant.

#### REQ-RPT-057 — Email a report now

From the report viewer, a user can email the current result to users or groups (and, with
permission, external addresses) at once, with a format and a message. The same per-recipient
rules apply (REQ-RPT-053).

- **Decision:** SAME.
- **Source:** sdp-area-09 §Actions (mail this report)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Emailing a report to a group sends each member their own result.
  2. The sent email appears in the notification log (REQ-NTF-028).

#### REQ-RPT-058 — Export to CSV, Excel and PDF

Any report, list and widget can be exported to CSV, Excel (XLSX) and PDF. Exports use labels,
the viewer's language and time zone, and keep grouping and summaries in Excel and PDF. The PDF
includes the header of REQ-RPT-050 and the chart. Large exports run in the background
(REQ-RPT-009, REQ-INC-116).

- **Decision:** BETTER. ServiceDesk Plus caps data exports at a few thousand records.
- **Source:** sdp-area-09 §Actions (export as: HTML, PDF, XLS, XLSX, CSV); architecture §2.8
  (export); REQ-INC-116; sdp-area-14 §Screens (export data capped at 3000)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. An XLSX export of a grouped report has one row per record, group subtotals and a grand
     total, with numbers stored as numbers and dates as dates.
  2. A CSV export opens correctly in a spreadsheet with Arabic text (UTF-8 with byte order
     mark).
  3. Every export is recorded in the audit log with the user, report and row count
     (REQ-WI-021).

#### REQ-RPT-059 — Legacy export formats

Export to the old binary Excel format (XLS) and to a standalone HTML file is not offered.

- **Decision:** SKIP. XLSX opens everywhere XLS does, and HTML files invite unsafe sharing.
  Replaced by XLSX and PDF (REQ-RPT-058) and the inline email summary (REQ-RPT-054).
- **Source:** sdp-area-09 §Actions (export as HTML, XLS), §Fields (schedule formats)
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. The export menu offers CSV, XLSX and PDF only.
  2. The migration tool maps schedules in XLS or HTML format to XLSX and PDF and lists each
     change.

---

## 6. Advanced analytics and BI

#### REQ-RPT-060 — Read-only BI connector

External BI tools (Power BI and others that use standard SQL or OData access) can read the
tenant's reporting data through a read-only connector. It exposes the semantic layer's views
with tenant and permission filters applied for a named service account. For customers whose
policy requires SQL Server, a scheduled export into their SQL Server is available. Set-up of
the connection is in file 12.

- **Decision:** NEW. The vendor sells a separate BI product; we give direct, governed access.
- **Source:** architecture §2.14 (analytics: Power BI through a read-only reporting connector),
  §7.5 (SQL Server reporting connector); product-plan §5 (reports and dashboards)
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. A BI tool connected with a service account scoped to site A reads only site A rows.
  2. The connector refuses every write.
  3. Each connection and query is logged with the account, and an admin can revoke the
     account at once.

#### REQ-RPT-061 — A separate BI add-on is not needed

SupportX does not depend on a separate analytics product for advanced reporting. Advanced BI
(SQL reports, the BI connector, forecasting, cross-desk reporting) is built in and licensed
through the entitlement interface.

- **Decision:** SKIP. The vendor promotes a separate analytics product for advanced BI;
  replaced by REQ-RPT-042, REQ-RPT-060, REQ-RPT-063 and REQ-RPT-064.
- **Source:** sdp-area-14 §Screens (analytics add-on promo page); product-plan §5 (advanced BI
  via add-on), §9 (advanced BI in Enterprise)
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. Every advanced BI capability is switched on by the entitlement interface only, with no
     separate install.
  2. Advanced BI works the same on SaaS and on-prem, including air-gapped installs.

#### REQ-RPT-062 — Ask questions in plain language

A user can ask a question in plain language ("open P1 incidents by group this week as a
chart") in English, Arabic or Urdu. The AI turns it into a report definition in the shared
format, shows the result, and shows the filters it used in words so the user can check and
change them. The answer can be saved as a report or a widget. It uses the same engine and
permissions as any report, so its numbers match (REQ-RPT-004). Model access follows D-049 and
file 10.

- **Decision:** BETTER. The vendor's AI assistant answers data questions, but its counts did
  not match the dashboard and it did not show what it counted.
- **Source:** architecture §2.10 (natural-language reports); product-plan §5 (built-in BI with
  natural-language queries), §7.2; sdp-area-10 §Behaviour (AI data answers and charts),
  §Weak spots; D-049
- **SDP weak spot fixed:** the AI answer counted 24 open requests and the dashboard 25.
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. The question "how many open incidents are there" gives the same number as the "open
     incidents" widget for that user.
  2. The answer shows the generated filters in words, and the user can edit them before
     saving.
  3. A question about data the user cannot see returns only their visible data, never a hint
     of the rest.
  4. On an air-gapped install the feature uses the local model.

#### REQ-RPT-063 — Forecasts and unusual changes

Trend reports and widgets can show a forecast (for example incident volume for the next four
weeks, with a range) and mark unusual changes (a spike in a category compared with its normal
level). Each forecast states the period it learned from. AI can explain a chart in a short
summary, on request.

- **Decision:** NEW. ServiceDesk Plus has no forecasting or anomaly marking in reports.
- **Source:** product-plan §5 (built-in BI with forecasting); sdp-area-10 §Limits (no AI in
  reports or anomaly detection)
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. A forecast on a known seasonal data set falls within its shown range for at least 80 % of
     test periods.
  2. A spike of three times the normal weekly volume in one category is marked on the chart.
  3. The explanation names only data the viewer may see.

#### REQ-RPT-064 — Reports across department desks and customers

In tenants with department desks (ESM) or MSP customers, reports can group, filter and compare
by department desk and by customer, and a customer-facing report can be scheduled to a
customer's contacts with only that customer's data.

- **Decision:** NEW. In ServiceDesk Plus each ESM instance reports on its own.
- **Source:** architecture §7.2 (shared reporting across departments), §2.15; product-plan §6
  (native multi-tenancy, contract SLAs)
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. A report grouped by department desk shows IT, HR and facilities side by side for a user
     who can see all three.
  2. A scheduled customer report sent to customer A's contact contains no customer B rows.

#### REQ-RPT-065 — Report definitions from ServiceDesk Plus

The ServiceDesk Plus migration tool lists the custom reports, schedules and dashboards it
finds, and proposes an equivalent SupportX definition for each for an admin to review. Nothing
is created until the admin accepts it.

- **Decision:** SAME. architecture §18 migrates report and dashboard definitions as a report
  for manual rebuild.
- **Source:** architecture §18.2, §18.3
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. The migration report lists every custom report found with its proposed equivalent and any
     field it could not map.
  2. Accepting a proposal creates a private report owned by the admin.

#### REQ-RPT-066 — Reporting speed targets

Reporting meets these targets at design load (p95):

- built-in reports and widgets on operational data return in under 1 second;
- grouped reports over 12 months of data on ClickHouse return in under 2 seconds;
- a dashboard of 12 widgets is fully drawn in under 3 seconds on first open.

- **Decision:** NEW (architecture design targets).
- **Source:** architecture §1.3, §9.6 (performance)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A load test with 10 million incidents meets each target for the ten most used built-in
     reports.
  2. The targets are checked in CI against a reference data set, and a regression of more than
     20 % fails the build.

---

## 7. Home page and ready-made dashboards

#### REQ-DSH-001 — The home page

After sign-in a technician lands on their home page. It shows their default dashboard and,
in fixed places, their personal counters (REQ-INC-128, REQ-PRB-074, REQ-CHG-117), approvals
waiting for them, their tasks (REQ-INC-076) and reminders (REQ-INC-082), current announcements,
and a link to the team availability calendar (REQ-ASG-009). Every part updates live.

- **Decision:** SAME.
- **Source:** sdp-area-01 §Screens (home page tabs, my summary panel, dashboard tab, scheduler,
  tech availability chart, tasks, reminders, announcements); sdp-area-09 §Navigation path;
  architecture §2.7 (dashboard types)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A new technician signing in for the first time sees a working home page with no set-up.
  2. A new approval for the user appears in "waiting for me" within 1 second.
  3. Each counter opens the matching list, with a row count equal to the counter.
  4. The home page keeps its layout in right-to-left mode.

#### REQ-DSH-002 — Default dashboard per role, and the user's own choice

An admin sets a default home dashboard per role. A user can choose another dashboard they can
see as their own home, and go back to the role default.

- **Decision:** BETTER. ServiceDesk Plus has one shared default dashboard for everyone.
- **Source:** architecture §2.7 (custom dashboards per role or team); sdp-area-09 §Screens
  (default helpdesk dashboard)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A technician and a manager see different home dashboards in a new tenant.
  2. A user who picks another dashboard sees it at next sign-in; "reset" returns to the role
     default.

#### REQ-DSH-003 — Ready-made dashboards

Each module ships a ready-made dashboard. The MVP ships the service desk dashboard (open work by
technician with open, paused and overdue counts; open by channel and by priority; received and
completed per day for 20 days; unassigned open work; SLA breaches by technician; work
approaching breach) and the SLA dashboard. Problem, change, release, asset, software, contract,
purchase, project and activity dashboards come with their modules (REQ-PRB-074, REQ-CHG-116,
REQ-REL-060, REQ-PRJ-045). Ready-made dashboards are read-only and can be copied.

- **Decision:** SAME.
- **Source:** sdp-area-09 §Screens (home dashboard widgets, canned dashboards: 11 entries);
  sdp-area-01 §Config (helpdesk dashboard default widgets, canned request widgets)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A new tenant has the service desk and SLA dashboards working with no set-up.
  2. Each module's dashboard appears when the module is licensed, and follows REQ-WI-025 when
     it is not.
  3. A ready-made dashboard cannot be edited; its copy can.

#### REQ-DSH-004 — Technician, manager and executive dashboards

The product ships three role dashboards:

- **technician:** my open work, due today, overdue, waiting for me, my SLA at risk;
- **service desk manager:** queue health by group, unassigned work, SLA risk, backlog trend,
  reopen and first-contact rates, technician load;
- **executive:** service health per service and site, SLA compliance trend, satisfaction,
  major incidents, change success rate.

- **Decision:** SAME. Covers the vendor's executive dashboard option.
- **Source:** architecture §2.7 (technician, manager and executive dashboards); sdp-area-09
  §Fields (executive dashboard checkbox); sdp-area-01 §Edition notes
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Each role dashboard is the default for its role in a new tenant (Appendix A).
  2. The executive dashboard shows no record-level data, only measures, and drills down only
     for users allowed to see the records.
  3. Change and problem tiles on the executive dashboard follow REQ-WI-025 in Essentials.

#### REQ-DSH-005 — Find and pick dashboards

The dashboard picker has a search box, favourites first, then ready-made dashboards, dashboards
shared with the user and the user's own, each in its own group. Each entry shows whether it is
private or shared.

- **Decision:** SAME.
- **Source:** sdp-area-09 §Screens (dashboard selector: search, favourites, canned group, custom
  group); sdp-area-01 §Screens (dashboard tab)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Starring a dashboard moves it to the favourites group at once.
  2. Typing part of a name filters the list as the user types, in either language.

#### REQ-DSH-006 — Approvers and requesters see their own summary

Users who are not technicians but approve or follow work (department heads, line managers)
can see a summary of the requests of their department or direct reports when the tenant allows
it, with the same live updates. The requester portal's own home page is in file 02.

- **Decision:** SAME. ServiceDesk Plus gives requesters a dashboard tab and lets managers see
  their reports' requests.
- **Source:** sdp-area-13 §Navigation & Footer Settings (requester view: dashboard);
  sdp-area-11 §Fields (view requests of direct reportees), §Behaviour (requester visibility)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A department head with the tenant setting on sees open requests of their department by
     status, and nothing outside it.
  2. Technician-only widgets (for example technician load) cannot be added to a requester's
     summary.

---

## 8. Widgets

#### REQ-DSH-007 — Widget library

Dashboards are built from one widget library:

- KPI tiles (REQ-DSH-008);
- charts from a quick definition (REQ-DSH-009) or from any saved report (REQ-DSH-010);
- lists of records, with actions (REQ-DSH-011);
- text (REQ-DSH-012) and embedded pages (REQ-DSH-013);
- approvals waiting, my tasks, my reminders, announcements;
- the team availability calendar (REQ-ASG-009);
- MonetX status (REQ-DSH-035).

A single "add widget" action opens the library, with search and a preview of each widget.

- **Decision:** BETTER. ServiceDesk Plus has two separate paths to add widgets (a source and
  module picker, and a "new" menu).
- **Source:** sdp-area-09 §Fields (customise panel: widget sources, new menu); sdp-area-01
  §Config (widget sources, new widget types), §Weak spots (two creation paths); architecture
  §2.7 (widgets), §9.6 (widget library)
- **SDP weak spot fixed:** dashboard creation needs a source, a module and ticking widgets one
  by one, and there are two ways to create widgets.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. One "add widget" action reaches every widget type, with search over names.
  2. Each widget shows a preview with real data before it is added.
  3. MVP ships KPI, chart, list, approvals, tasks and reminders widgets; text, embedded page,
     availability and MonetX status follow at V1.

#### REQ-DSH-008 — KPI tiles

A KPI tile shows one measure in large type with its trend against the previous period (up or
down, by how much), a sparkline, and, when a target is set, a colour from its thresholds
(REQ-DSH-038). The tile says whether up is good or bad for this measure.

- **Decision:** BETTER. ServiceDesk Plus shows plain counts.
- **Source:** architecture §2.7 (KPI cards), §9.6 (KPI tiles with sparklines and trend deltas)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. "Mean time to resolve, this week" shows the value, the change from last week and a
     sparkline of 8 weeks.
  2. A rise in mean time to resolve shows as a bad change; a rise in SLA compliance as good.
  3. The tile's value equals the same measure in a report (REQ-RPT-004).

#### REQ-DSH-009 — Chart widgets from a quick definition

A user creates a chart widget by choosing the entity, an optional filter, the chart type, a
grouping field (and a second for stacked charts), the measure, and number or percent. A
preview shows the result before saving.

- **Decision:** SAME.
- **Source:** sdp-area-09 §Fields (new graph widget), §Behaviour (test dashboard: doughnut by
  priority); sdp-area-01 §Config (graph widget form)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A doughnut of open incidents by priority shows the same counts as the report "open
     incidents by priority".
  2. Switching from number to percent shows shares that add up to 100 %.
  3. Every field that can group a report can group a chart widget.

#### REQ-DSH-010 — Any saved report as a widget

Any report the user can see can be added to a dashboard as a widget, showing its chart, its
table or both. No separate "publish to dashboard" switch is needed. If the report changes, the
widget follows; if the report is deleted, the widget says so.

- **Decision:** BETTER.
- **Source:** architecture §2.7 (charts from any report); sdp-area-09 §Actions (access to
  dashboard toggle), §Weak spots (toggle only on built-in rows, unexplained)
- **SDP weak spot fixed:** an unexplained per-report switch decides which reports can become
  widgets.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A custom report saved by a user can be added to their dashboard at once.
  2. Changing the report's grouping changes the widget on next load.
  3. Deleting the report leaves the widget showing "report removed", with a remove action.

#### REQ-DSH-011 — List widgets with actions

A list widget shows records from a view or filter, as rows or cards, with chosen columns. The
owner can enable actions in the widget: on the selection (assign, take, close, merge, link,
delete, new) and on each row (edit). Actions follow the same rules and action states as the
list (REQ-WI-010) and the rows update live.

- **Decision:** SAME.
- **Source:** sdp-area-09 §Fields (new table widget: view type, header actions, row actions);
  architecture §2.7 (lists with in-widget actions)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Taking an incident from an "unassigned" list widget removes it from the widget for every
     viewer within 1 second.
  2. An action the user may not run shows disabled with its reason, as in the list.
  3. A list widget shows at most its set row count, with a link to the full list.

#### REQ-DSH-012 — Text widgets

A text widget shows formatted text, links and images, for example team notices or links to
procedures. Content is sanitised on the server (REQ-INC-064, D-040) and can be written per
language.

- **Decision:** SAME.
- **Source:** sdp-area-09 §Fields (new info widget); D-036; D-040
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A script tag pasted into a text widget is removed on save, and the stored content has no
     script.
  2. A widget with English and Arabic text shows the viewer's language.

#### REQ-DSH-013 — Embedded web pages from allowed sites only

An embedded page widget shows an external web page inside the dashboard. Only sites on the
tenant's allow-list can be embedded; the page runs in a sandbox with no access to SupportX
data or the session. The list is empty by default.

- **Decision:** BETTER. ServiceDesk Plus embeds any address.
- **Source:** sdp-area-09 §Fields (new URL widget); architecture §11 (security baseline)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Adding an address not on the allow-list is refused with a reason.
  2. An embedded page cannot read SupportX cookies or call the SupportX API as the user; a
     security test checks the sandbox.
  3. Removing a site from the allow-list blanks existing widgets for it with a message.

#### REQ-DSH-014 — Widgets reused across dashboards, with one sharing rule

A widget can be saved to a personal or shared widget library and placed on several
dashboards. A widget created on a dashboard takes that dashboard's sharing by default. A widget
never shows data to someone who could not see it in a report (REQ-RPT-002).

- **Decision:** BETTER.
- **Source:** sdp-area-09 §Behaviour (widget visibility, reuse through graph widgets source),
  §Weak spots (new dashboard private, new widget public); sdp-area-01 §Weak spots
- **SDP weak spot fixed:** a new dashboard defaults to private while a new widget defaults to
  public, so a private dashboard can publish its widget by accident.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A widget created on a private dashboard is private.
  2. Editing a shared library widget changes it on every dashboard that uses it, after a
     warning that lists those dashboards.
  3. Sharing a widget shows who will see it before confirming.

#### REQ-DSH-015 — Expand, switch type and refresh a widget

Each widget can be expanded to full screen, switched to another suitable chart type for the
viewer, refreshed by hand, exported (REQ-RPT-058) and opened as a report.

- **Decision:** SAME.
- **Source:** sdp-area-09 §Screens (widget header menu: expand, refresh, switch chart type),
  §Actions (dashboard widgets)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Switching a bar widget to a table for one viewer does not change it for others.
  2. Expanding a widget keeps its filters and drill-down.

---

## 9. Live updates

#### REQ-DSH-016 — Every widget updates live

Every widget on every dashboard and wallboard updates live when data changes, with no page
refresh and no refresh timer. Widgets subscribe to their dashboard's channel; a change patches
the numbers, and the widget refetches when the change is ambiguous. Changes animate gently,
or not at all for users who ask for reduced motion.

- **Decision:** BETTER. ServiceDesk Plus widgets load on open and refresh on a timer that is
  off by default.
- **Source:** architecture §8 (channels: dash, wall), §8.3, §9.6 (live by default); CLAUDE.md
  §5c; sdp-area-09 §Configuration options (refresh frequency default never), §Behaviour
  (nothing updates live by push); REQ-WI-005
- **SDP weak spot fixed:** dashboards show stale numbers until someone presses refresh.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. With a dashboard open in two browsers, creating an incident raises the "open" KPI in both
     within 2 seconds.
  2. A widget whose filter a changed record leaves (for example priority changed from P1 to
     P2) moves the record between the bars live.
  3. A user who asks for reduced motion sees no animation on updates.
  4. A viewer receives no event about records outside their scope (REQ-WI-005 AC5).

#### REQ-DSH-017 — Connection state and recovery

If the live connection drops, the dashboard shows a small indicator and falls back to
streaming or timed polling. On reconnect, missed changes are replayed or the widgets refetch;
no stale number stays on screen without a marker.

- **Decision:** NEW.
- **Source:** architecture §8.3 (recovery, graceful degradation)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Cutting the network for 30 seconds shows the indicator; after reconnect the widgets
     match the reporting store.
  2. With WebSockets blocked by a proxy, widgets still update within the polling interval
     (Appendix A).

#### REQ-DSH-018 — Live updates at scale

Bursts of changes (a bulk edit of 1,000 records, an alert storm turned into incidents by
MonetX) are coalesced, so a dashboard redraws at most once per second per widget. Hundreds of
viewers of the same dashboard or wallboard do not add database load beyond one query per
widget per change batch (REQ-RPT-010).

- **Decision:** NEW.
- **Source:** architecture §8.4 (coalescing, per-tenant fan-out limits)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A bulk edit of 1,000 incidents causes at most a few redraws per widget, and the final
     numbers are right.
  2. 500 open viewers of one dashboard keep reporting store load within the target of a single
     viewer plus 10 %.

---

## 10. The dashboard builder

#### REQ-DSH-019 — Build dashboards on a grid

Users with permission create dashboards with a name and description, then add widgets and
arrange them on a responsive grid by dragging and resizing. Edit mode shows handles to move,
resize, edit and remove each widget; leaving edit mode saves the layout. Changes can be
undone while editing.

- **Decision:** BETTER. ServiceDesk Plus offers a fixed number of columns (2, 4, 6 or 8) and
  ticks widgets in a side panel.
- **Source:** sdp-area-09 §Fields (new dashboard, customise panel: widget columns), §Actions
  (widget edit mode: drag, resize); sdp-area-01 §Weak spots (dashboard creation is heavy);
  architecture §9.6 (builder: drag-and-drop grid with resize)
- **SDP weak spot fixed:** creating a dashboard is heavy, with a drawer, a source, a module and
  one tick per widget.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A user creates a dashboard with three widgets and arranges them in under two minutes in a
     usability test.
  2. Moving and resizing widgets can be done with the keyboard as well as the mouse.
  3. Undo restores the last layout change while still in edit mode.
  4. The layout adapts to narrow screens without horizontal scrolling.

#### REQ-DSH-020 — Sections inside a dashboard

A dashboard can be split into named sections or tabs (up to 10 widgets each by default), so a
large dashboard stays readable. Sections can be collapsed and reordered.

- **Decision:** SAME.
- **Source:** sdp-area-01 §Config (builder empty-state: grouping up to 10 widgets per group)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A dashboard with three tabs loads only the visible tab's widgets first.
  2. A collapsed section stays collapsed for that user at the next visit.

#### REQ-DSH-021 — Copy a dashboard

Any dashboard the user can see can be copied into a new private dashboard, including
ready-made ones.

- **Decision:** SAME.
- **Source:** sdp-area-09 §Screens (copy icon next to the dashboard name); sdp-area-01
  §Actions (copy dashboard)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Copying the service desk dashboard gives an editable private copy with the same widgets.
  2. The copy's widgets are independent of the original's.

---

## 11. Filters and interaction

#### REQ-DSH-022 — Dashboard filters

A dashboard has a filter bar that applies to every widget that can use it: site, group and time
range at MVP, and any shared field (category, priority, service, customer) from V1. The owner
sets defaults; each viewer can change them for their session. Widgets that cannot use a filter
say so.

- **Decision:** BETTER. Adds time range and any field to ServiceDesk Plus's site and group
  filters.
- **Source:** sdp-area-09 §Screens (home dashboard header: all sites, all groups); architecture
  §2.7 (site and group filters), §9.6 (per-widget filters)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Choosing site A changes every site-aware widget to site A in one step.
  2. A widget that has no site field shows a "not filtered by site" marker.
  3. The filter bar only offers sites and groups the viewer may see.

#### REQ-DSH-023 — Click to filter the whole dashboard

Clicking a bar, slice or cell in one widget filters the whole dashboard by that value
(cross-filtering). The active cross-filters show in the filter bar and can be cleared one by
one.

- **Decision:** NEW. ServiceDesk Plus widgets are independent.
- **Source:** architecture §9.6 (cross-filtering)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Clicking "network" in a category chart filters every other widget to the network category.
  2. Clearing the cross-filter restores every widget.

#### REQ-DSH-024 — Drill down from any widget

Every number, bar and cell on a widget drills down to the records behind it (REQ-RPT-037), with
the dashboard's filters applied. Drill-down opens beside the dashboard so the user keeps their
place.

- **Decision:** BETTER.
- **Source:** architecture §2.7 (drill-down to records), §9.6; sdp-area-09 §Actions (open
  detail icon); sdp-area-01 §Weak spots (search lands on a different screen)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Clicking "overdue: 4" on the service desk dashboard opens a list of those 4 records in a
     side panel, and closing it returns to the dashboard as it was.
  2. The drill-down list respects the dashboard's site and group filters.

#### REQ-DSH-025 — Compare periods

Time-based widgets can compare the current period with the previous one or the same period
last year, shown as a second series or as a change value.

- **Decision:** NEW.
- **Source:** architecture §9.6 (time range comparison)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. "Incidents per day, this week against last week" shows both series with aligned weekdays.
  2. The change value equals (this − last) ÷ last, and shows "no data" when last is zero.

---

## 12. Sharing and permissions

#### REQ-DSH-026 — Private and shared dashboards

A new dashboard is private. The owner can share it with everyone in the tenant, or keep it
private. The picker shows which dashboards are private and which are shared.

- **Decision:** SAME.
- **Source:** sdp-area-09 §Fields (dashboard name with private or public lock), §Configuration
  options; sdp-area-11 §Behaviour (dashboards private or shared)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A new dashboard is visible only to its owner.
  2. Sharing with everyone makes it appear in every user's picker under "shared with me".

#### REQ-DSH-027 — Share by role, group and user, with view or edit rights

A dashboard can be shared with chosen roles, groups and users, each with view or edit rights,
and published as a role's default (REQ-DSH-002).

- **Decision:** BETTER. ServiceDesk Plus shares dashboards only as public or private.
- **Source:** architecture §2.7 (dashboard permissions by role, group and user), §9.6 (sharing
  by role); sdp-area-11 §Behaviour (not by role)
- **SDP weak spot fixed:** no sharing by role, group or user.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A dashboard shared with group A for viewing appears for group A members, who cannot edit
     it.
  2. A user given edit rights can change the layout; their changes are versioned (REQ-RPT-043).

#### REQ-DSH-028 — Each viewer sees their own scope

A shared dashboard shows each viewer the data they may see. A small marker tells the viewer
that the numbers reflect their access, so two people comparing numbers understand why they
differ.

- **Decision:** BETTER.
- **Source:** REQ-RPT-002; architecture §8.2 (subscription tokens permission-checked), §11.2
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. The same shared dashboard shows a group A technician only group A counts and a manager all
     counts.
  2. A viewer's dashboard channel subscription is refused if they lose access to the
     dashboard, and the dashboard closes with a message.

#### REQ-DSH-029 — Dashboard permissions

Roles carry dashboard permissions: create own dashboards, share dashboards, publish role
defaults, manage the shared widget library, manage wallboards and displays, and add embedded
page widgets.

- **Decision:** SAME.
- **Source:** sdp-area-11 §Screens (role matrix); architecture §2.7 (sharing), §11.2
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A role without "share dashboards" sees sharing disabled with a reason, and the API refuses
     it with 403.
  2. Only roles with "manage wallboards" can pair a display (REQ-DSH-031).

---

## 13. Wallboards and TV mode

#### REQ-DSH-030 — TV mode with rotation

Any dashboard can be shown in TV mode: full screen, no menus, large type, no hover-only
information, and an automatic rotation through chosen dashboards or sections at a set
interval. TV mode stays live (REQ-DSH-016) and shows a clock and the "as of" time.

- **Decision:** NEW. ServiceDesk Plus has a full-screen button but no wallboard mode.
- **Source:** architecture §9.6 (TV/wallboard mode with auto-rotation), §8.1 (wall channel);
  product-plan §5 (executive and NOC wallboards); sdp-area-09 §Screens (full-screen button)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A wallboard rotating three pages every 30 seconds runs for 24 hours without a reload and
     without memory growth beyond 10 %.
  2. Text on a wallboard page is readable at 4 metres on a 55-inch screen (minimum type size in
     Appendix A).
  3. Changes still arrive live while a page is not on screen, and show when it rotates in.

#### REQ-DSH-031 — Displays paired without a user sign-in

A wall screen is paired as a display: an admin enters a short code shown on the screen and
picks the wallboards it may show and the data scope it runs with (for example one site or one
customer). The display holds a revocable token that can only read those wallboards; it cannot
open records or other screens. Each display shows in a list with its last contact time.

- **Decision:** NEW.
- **Source:** architecture §8.1 (wall channel), §8.2 (subscription tokens), §11.1
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A paired display shows its wallboards and nothing else; calls to any other API with its
     token return 403.
  2. Revoking a display blanks its screen within 5 seconds.
  3. A display scoped to site A never shows site B data.
  4. Pairing, scope changes and revocation are audited.

#### REQ-DSH-032 — Wallboard alert states

Wallboard tiles change colour when a threshold is crossed (REQ-DSH-038) and can flash or play
a sound for chosen events, for example a major incident declared (REQ-INC-141) or a P1 breach.
The alert stays visible until the condition clears.

- **Decision:** NEW.
- **Source:** product-plan §6 (NOC wallboards); architecture §9.6
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. Declaring a major incident shows the alert state on every wallboard with that widget
     within 2 seconds.
  2. Flashing respects reduced motion settings of the display (a steady colour instead).

#### REQ-DSH-033 — NOC wallboard

A ready-made NOC wallboard combines, per site or per customer: open incidents by priority, SLA
risk, major incidents, changes in progress and in the next hours, and the monitoring status of
the site's or customer's key items read from MonetX (REQ-DSH-035).

- **Decision:** NEW. Differentiator; ServiceDesk Plus dashboards are generic.
- **Source:** product-plan §6 (NOC wallboards), §4.3 (pillar 3); D-001; architecture §9.6
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A new Professional tenant with MonetX connected has the NOC wallboard with no set-up.
  2. Choosing a site shows that site's incidents, changes and monitoring status only.
  3. A MonetX problem turned into an incident (REQ-INC-030) appears on the wallboard within
     2 seconds of the incident being created.

#### REQ-DSH-034 — Service health board

A service health board shows each business service with its state worked out from open
incidents, major incidents and planned changes in SupportX, plus MonetX health where
available. Each service drills down to its records.

- **Decision:** NEW.
- **Source:** architecture §2.7 (executive dashboards); product-plan §6 (topology-aware impact,
  NOC wallboards); D-001
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A service with an open major incident shows as degraded within 2 seconds of the
     declaration.
  2. The rule that turns records into a service state is shown to the viewer in words.

#### REQ-DSH-035 — MonetX status widgets, read-only

Monitoring status widgets show health and open problems of chosen items, sites or customers,
read from the MonetX API through the monitoring integrations module, read-only. They refresh
while on screen, show when MonetX last answered, and link to MonetX for detail. SupportX stores
no metrics, polls no devices and correlates no alerts.

- **Decision:** NEW.
- **Source:** D-001; ADR-017; CLAUDE.md §1 (monitoring boundary); REQ-INC-145; REQ-INC-146
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. If MonetX cannot be reached, the widget shows "monitoring status unavailable" with the
     last good time; the rest of the wallboard works.
  2. SupportX makes no write call to MonetX, and no table stores metric values (architecture
     test, as REQ-CHG-087).
  3. A display scoped to customer A shows only customer A's monitoring status.

---

## 14. KPIs, targets and scorecards

#### REQ-DSH-036 — Scorecards

A scorecard shows a set of KPIs with targets for a technician, group, service, site or
customer: for example mean time to respond and to resolve, SLA compliance, first-contact
resolution, reopen rate, backlog, satisfaction. Each KPI shows its value, target, trend and
status. Ready-made scorecards exist for groups and services; tenants build their own.

- **Decision:** NEW. ServiceDesk Plus has per-technician counts but no scorecards with targets.
- **Source:** architecture §9.6 (top-N leaderboards, gauges for SLA compliance); product-plan
  §7.4 (MTTA and MTTR by queue and service)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A group scorecard for last month shows each KPI with value, target, trend and status.
  2. Each KPI value equals the same measure in a report (REQ-RPT-004).
  3. A scorecard can be scheduled as a PDF (REQ-RPT-052).

#### REQ-DSH-037 — Leaderboards

A leaderboard ranks groups, services, categories or, with permission, technicians by a
measure (top N). It updates live.

- **Decision:** NEW.
- **Source:** architecture §9.6 (top-N leaderboards)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. "Top 5 categories by open incidents" re-ranks live when an incident changes category.
  2. A technician leaderboard is offered only to roles allowed to see per-person measures
     (REQ-DSH-040).

#### REQ-DSH-038 — Targets and thresholds

Any KPI can have a target and thresholds that colour it (for example green, amber and red),
with the colours also shown by icon and text so they do not rely on colour alone. Tenants set
defaults; a dashboard or scorecard can override them.

- **Decision:** NEW.
- **Source:** architecture §9.6 (gauges for SLA compliance); product-plan §6
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. With the default SLA thresholds (Appendix A), 92 % compliance shows amber with an amber
     icon and the word "at risk".
  2. A threshold change applies to open dashboards live.

#### REQ-DSH-039 — Notify when a KPI crosses a threshold

A user can ask to be notified when a KPI crosses a threshold, for example "SLA compliance for
group A today drops below 90 %" or "more than 20 unassigned incidents". Notifications go
through the notification engine (file 03), once per crossing, not repeatedly.

- **Decision:** NEW. ServiceDesk Plus has no threshold alerts on reports or widgets.
- **Source:** sdp-area-09 §Automation (no threshold alerts or report-based triggers)
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. Crossing the threshold sends one notification; staying below it sends no more until it
     recovers and crosses again.
  2. The notification links to the dashboard with the right filters applied.

#### REQ-DSH-040 — Measures about people are protected

Measures about one named person (technician scorecards, leaderboards, per-technician
satisfaction) are visible only to that person and to roles with the "see per-person measures"
permission. By default only group managers have it for their own groups. Service and group
measures are not restricted this way.

- **Decision:** NEW. ServiceDesk Plus shows per-technician widgets to anyone who can see the
  dashboard.
- **Source:** architecture §11.3 (data protection); REQ-SLA-036 (per service, never per person,
  by default); sdp-area-09 §Screens (requests by technician, SLA violation by technician)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A technician sees their own scorecard but not a colleague's.
  2. A shared dashboard with a per-technician widget shows that widget as "not available to
     you" to viewers without the permission.
  3. A group manager sees per-person measures for their groups only.

---

## 15. Special dashboards and dashboard output

#### REQ-DSH-041 — AI usage and outcome dashboard

A ready-made AI dashboard shows usage (predictions and generations per feature, provider and
user, tokens used, chatbot conversations) and, more importantly, outcomes: deflection rate and
hours saved, response and resolution times with and without AI help, breaches prevented by
prediction, suggestion acceptance and override rates, and model cost per resolved record for
cloud models or GPU use for local models. Data comes from file 10.

- **Decision:** BETTER. The vendor's AI dashboard shows adoption only; we show business
  outcomes.
- **Source:** architecture §2.7 (AI usage dashboard), §2.10 (usage and outcome dashboard);
  product-plan §7.4; sdp-area-01 §Screens (AI dashboard in the canned list)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. The dashboard shows the acceptance rate of classification suggestions for last month.
  2. Each outcome measure shows its definition (REQ-RPT-004).
  3. Usage per user is visible only with the per-person permission (REQ-DSH-040).

#### REQ-DSH-042 — Operations dashboard for admins

A ready-made dashboard for tenant admins shows the health of the service desk's own machinery:
email intake and sending, notification delivery and bounces (REQ-NTF-028), failed workflow and
rule steps, failed schedules (REQ-RPT-056), background job queues, analytics freshness
(REQ-RPT-008) and licence use against limits.

- **Decision:** NEW.
- **Source:** architecture §15 (observability); REQ-NTF-028; REQ-WI-009
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A failed workflow step appears on the operations dashboard within 2 seconds, with a link
     to the record.
  2. The analytics lag tile turns red when the lag passes the stale-data limit (Appendix A).

#### REQ-DSH-043 — Dashboard snapshots as PDF, and on a schedule

A dashboard can be exported as a PDF or image snapshot with its filters, "as of" time and time
zone, and scheduled like a report (REQ-RPT-052), for example a weekly service review to
managers. Each recipient gets their own data (REQ-RPT-053).

- **Decision:** NEW. ServiceDesk Plus cannot export or schedule a dashboard.
- **Source:** architecture §6.10 (execution and delivery); sdp-area-09 §Actions (no dashboard
  export observed)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A PDF snapshot shows every widget as on screen, with the filters in words.
  2. A scheduled snapshot to two users with different scopes sends two different PDFs.

#### REQ-DSH-044 — Time zones in reports and dashboards

All dates and times in reports, widgets and exports show in the viewer's time zone through the
shared formatter (REQ-WI-014), and every header states the zone. Grouping by day, week or
month uses the viewer's zone by default; a report or dashboard can fix a zone (for example a
site's zone for a site report), and then says so. Scheduled outputs use the schedule's zone.
Durations in business time use the record's SLA calendar (REQ-SLA-013).

- **Decision:** BETTER. ServiceDesk Plus sets one date format for all reports and does not say
  which zone a report uses.
- **Source:** sdp-area-09 §Screens (report settings: date format, group date format);
  sdp-area-01 §Fields (time zone preference); REQ-WI-014
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. An incident created at 23:30 UTC counts on the next day for a viewer in Asia/Karachi and
     on the same day for a viewer in UTC.
  2. A report fixed to the Riyadh site's zone shows "times in Asia/Riyadh" in its header for
     every viewer.
  3. Daily grouping over a daylight-saving change has no missing or doubled day.

---

## 16. Languages, right-to-left, accessibility and devices

#### REQ-DSH-045 — Languages in reports and dashboards

Report and dashboard screens, built-in report and dashboard names, measure definitions, chart
labels, legends, tooltips and exports work in English and Arabic at MVP and in Urdu from V1
(D-006, D-048). Numbers, percentages and dates use the viewer's locale. User-made report and
dashboard names can carry translations. A scheduled report is produced in each recipient's
language.

- **Decision:** BETTER. ServiceDesk Plus charges extra for multiple languages on-prem and its
  reports follow one instance format.
- **Source:** architecture §9.5; CLAUDE.md §5d; D-006; D-048; REQ-WI-013; REQ-INC-133
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Every built-in report and dashboard name has English and Arabic labels; CI fails if one is
     missing (and Urdu from V1).
  2. A scheduled report to an Arabic-speaking and an English-speaking user arrives in Arabic
     and in English respectively.
  3. A user-made dashboard name with no Arabic translation falls back to its original name.

#### REQ-DSH-046 — Right-to-left charts, reports and exports

In Arabic and Urdu, report tables, dashboards and charts are laid out right to left: the
first column and the start of time axes are on the right, legends and tooltips are mirrored,
and bidirectional text (Arabic names next to Latin IDs) displays correctly. PDF and print
outputs are right to left with fonts that render Arabic and Urdu script correctly.

- **Decision:** NEW. Right-to-left charts were not observed in ServiceDesk Plus.
- **Source:** architecture §9.4, §9.5; CLAUDE.md §5d; D-006
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A line chart in Arabic draws time from right to left, and the e2e suite checks the axis
     direction.
  2. A PDF export in Arabic shows joined Arabic letters (not separate glyphs) and right-aligned
     tables.
  3. A record ID such as INC-1042 inside Arabic text displays in the right order.
  4. Every report and dashboard screen passes the e2e suite in Arabic.

#### REQ-DSH-047 — Accessible charts and dashboards

Charts, reports and dashboards meet WCAG 2.2 AA (REQ-WI-023):

- each chart has a data table view and a short text summary for screen readers;
- chart parts can be reached with the keyboard, and drill-down works with Enter;
- colours pass contrast and are safe for colour-blind users, and status never relies on colour
  alone;
- live updates are announced politely, never stealing focus.

- **Decision:** BETTER. ServiceDesk Plus offers personal accessibility switches but its charts
  have no text alternative.
- **Source:** architecture §9.4; sdp-area-01 §Config (accessibility toggles); REQ-WI-023
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. The automated accessibility check reports no serious or critical issues on the reports
     home, the report viewer, the builder and the service desk dashboard, in English and
     Arabic.
  2. A screen reader user can read the values of a bar chart through its table view.
  3. Every chart is distinguishable in a colour-blindness simulation test.

#### REQ-DSH-048 — Dashboards on phones and the mobile app

Dashboards and reports work on phone and tablet browsers: widgets stack in one column, charts
stay readable, and drill-down opens the record list. The mobile app shows the home dashboard
and personal counters.

- **Decision:** SAME. ServiceDesk Plus offers mobile apps.
- **Source:** sdp-area-01 §Screens (profile drawer: mobile apps); architecture §9.1 (mobile
  apps); D-065
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. The service desk dashboard on a 375-pixel-wide screen shows every widget with no
     horizontal scrolling.
  2. The mobile app's home counters update live, as on the web.

#### REQ-DSH-049 — No refresh timers or unexplained switches

Dashboards have no refresh-frequency setting and no hidden display switches. Live updates
(REQ-DSH-016) replace the timer, and every dashboard option is explained on screen.

- **Decision:** SKIP. The vendor's refresh timer (off by default) and an unexplained display
  toggle are not reproduced; replaced by REQ-DSH-016 and REQ-DSH-017.
- **Source:** sdp-area-09 §Fields (dashboard settings: refresh frequency, an unexplained view
  toggle), §Weak spots; sdp-area-01 §Automation
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. No dashboard setting asks for a refresh interval.
  2. Every dashboard setting has a help text in the user's language.

#### REQ-DSH-050 — No anonymous public links

Dashboards and reports cannot be opened through an anonymous public link. Large screens use
paired displays (REQ-DSH-031); people outside the tenant receive scheduled outputs
(REQ-RPT-053).

- **Decision:** SKIP. Anonymous links leak data and cannot apply permissions; replaced by
  REQ-DSH-031 and REQ-RPT-053.
- **Source:** architecture §11.2, §8.2
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. No API issues a dashboard or report link that works without sign-in or a display token.
  2. A security test confirms that a dashboard URL opened in a private browser window asks for
     sign-in.

---

## Appendix A — Proposed defaults

These are the defaults a new tenant gets. They are seed data, not fixed behaviour: a tenant
admin can change every one of them (D-041). Platform maximums, where given, cap what a tenant
can set. The requirements above refer to this appendix.

**Query limits** (REQ-RPT-009, REQ-RPT-042):

| Setting | Default | Platform maximum |
|---|---|---|
| Interactive query time limit | 30 seconds | 60 seconds |
| Rows shown per page in the viewer | 50 | 500 |
| Rows before a report runs in the background | 10,000 | 50,000 |
| Rows per export file | 1,000,000 | 1,000,000 (larger exports are split) |
| Background report time limit | 15 minutes | 60 minutes |
| Concurrent heavy reports per tenant | 5 | set per plan |
| SQL report time limit and row limit | 60 seconds, 100,000 rows | 120 seconds, 1,000,000 rows |
| Result cache lifetime | 60 seconds, dropped early on a relevant change | 5 minutes |

**Freshness** (REQ-RPT-008, REQ-DSH-017): operational widgets within 2 seconds; analytical
widgets within 60 seconds; stale-data marker and admin notice when the analytics load is more
than 5 minutes behind; polling interval when live connections are blocked: 15 seconds.

**Built-in reports** (REQ-RPT-015, REQ-RPT-050): default range "last 30 days"; ageing
buckets: under 1 day, 1 to 3 days, 3 to 7 days, 7 to 30 days, over 30 days; weeks start on
Sunday in tenants created with Arabic as the default language and on Monday otherwise.

**Folders and sharing** (REQ-RPT-045, REQ-RPT-047, REQ-DSH-026): built-in folders per
module (read-only); "My reports" per user; one empty "Shared reports" folder. New reports and
new dashboards are private; a widget created on a dashboard takes the dashboard's sharing.

**Scheduling and delivery** (REQ-RPT-052 to REQ-RPT-056):

- default send time 07:00 in the owner's time zone; weekly on the tenant's first weekday;
  monthly on the 1st;
- attachment limit 10 MB, above which a secure link is sent; link expiry 7 days, sign-in
  required;
- report library retention 90 days;
- sending to external addresses: off;
- a schedule pauses after 3 failed runs in a row.

**Role dashboards** (REQ-DSH-002, REQ-DSH-004): technicians get "My work"; group managers
and service desk managers get "Service desk overview"; administrators get "Service desk
overview" and the operations dashboard (REQ-DSH-042); executives (if the role exists) get
"Service health".

**Standard measure choices** (REQ-RPT-004): mean time to respond and to resolve exclude
paused time and use calendar time; SLA measures use business time under the record's SLA
calendar; first-contact resolution counts records resolved at creation or by the first
technician with no reassignment and no reopen (REQ-INC-102).

**Thresholds** (REQ-DSH-038): SLA compliance green at 95 % or more, amber from 90 % to under
95 %, red under 90 %; unassigned open work amber at 10, red at 25.

**Wallboards** (REQ-DSH-030, REQ-DSH-031): rotation every 30 seconds; minimum type size for
KPI values 48 px and for labels 24 px at 1080p; display tokens valid for 1 year and
revocable at any time.

**Per-person measures** (REQ-DSH-040): visible to the person and to group managers for their
own groups.

**Embedded pages** (REQ-DSH-013): allow-list empty.

**Dashboard sections** (REQ-DSH-020): up to 10 widgets per section.

---

## Open questions for the product owner

1. **Scheduled reports at MVP?** Scheduling (REQ-RPT-052 to REQ-RPT-057) is set to V1. The
   internal go-live may want a weekly email to managers. Move basic scheduling of built-in
   reports to MVP?
2. **Two freshness levels.** Operational widgets update within 2 seconds; analytical widgets
   from ClickHouse within 60 seconds, with an "as of" time (REQ-RPT-008). Does this meet
   CLAUDE.md §5c, or must every widget update within 2 seconds?
3. **Edition of the report builder.** The visual query builder (REQ-RPT-025) is set to
   Essentials, since custom reports are standard in every tender. product-plan §9 says only
   "basic reports" for Essentials. Keep it in Essentials, or make it Professional?
4. **What "advanced BI" contains.** Enterprise is set to hold SQL reports (REQ-RPT-042), the
   BI connector (REQ-RPT-060), forecasting (REQ-RPT-063) and cross-desk and customer reports
   (REQ-RPT-064). Natural-language questions (REQ-RPT-062) are Essentials, as AI is in every
   tier. Confirm the split.
5. **External recipients.** Scheduled reports to addresses outside the tenant are off by
   default and need a permission (REQ-RPT-053). Confirm.
6. **Per-person measures.** Technician scorecards and leaderboards are visible only to the
   person and their group managers by default (REQ-DSH-040), because some markets limit
   individual performance tracking. Confirm the default.
7. **Hijri dates.** Should reports and dashboards offer the Hijri calendar for display and for
   grouping (for example months), for Saudi public sector tenders?
8. **Built-in catalogue size.** architecture §2.8 asks for 150 or more built-in reports. The
   MVP ships the incident, service request, SLA and time reports (REQ-RPT-015 to
   REQ-RPT-017), about 40. Is 150 at V1 the right target, or should V1 ship fewer, better
   reports?
9. **Wallboard displays.** Displays are paired with a code and a revocable token, without a
   user signing in (REQ-DSH-031). Is that acceptable to customers' security teams, or must a
   service account sign in?
10. **ClickHouse on small installs.** On single-node installs (up to about 50 technicians,
    architecture §14.2) reports read PostgreSQL views and ClickHouse is off. Confirm the
    threshold, and whether a tenant may switch ClickHouse on later without losing history.
