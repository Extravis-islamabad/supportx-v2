# 04 — Problems and known errors

Parity requirements for problem management (architecture.md §2.3) as a work item type on the
shared engine (architecture.md §6.2). Rules, ID scheme and field meanings: [README.md](README.md).

**Status:** Draft v0.1, 2026-10-24. Written in Phase 2 against the decisions D-039 to D-050.
**Owner:** Haider (Product Owner).

## Scope of this file

- **REQ-PRB-*** are problem requirements. A problem is a work item of type `problem` on the
  engine in file 01. It inherits every engine requirement (REQ-WI-*) and the shared work item
  behaviour described with incidents: notes, conversations, worklogs, tasks, checklists,
  attachments, reminders, approvals, links, merge, lists, views, bulk actions, the record page,
  trash, history and live updates. This file does not restate them. It lists only how a problem
  differs from an incident or what it adds.
- **How a problem differs from an incident:**
  - it has no requester waiting on it; it is owned by a technician and a group, and its
    "reported by" person is a source, not a customer;
  - it carries analysis fields (impact details, root cause, symptoms) and a solution split into
    workaround and permanent resolution;
  - it can be marked a known error, which feeds the known error database, incident suggestions
    and, if chosen, the portal;
  - it is linked to many incidents and acts on them when it is resolved or closed;
  - it is normally fixed through a change (file 05) and may cause or be caused by a release
    (file 06);
  - by default it has no response and resolution SLA; it has target dates instead.
- **Not in this file** (each has its own module file, see the README):
  - the life cycle designer, visual workflows, business rules, notification engine and
    templates (file 03); this file says only which problem events and defaults exist;
  - the knowledge base and its approval flow (file 08); this file says how workarounds and
    resolutions become articles;
  - reports and dashboards (file 09), AI administration and model access (file 10), roles and
    permission screens (file 11), the MonetX connector (file 12), changes (file 05), releases
    (file 06), assets and the CMDB (file 07).
- **Monitoring is out of scope** (ADR-017, D-001). Proactive problem detection works only on
  incidents already in SupportX. SupportX never correlates or de-duplicates monitoring alerts
  (REQ-INC-146, REQ-PRB-077).

## Words used in this file

| Word | Meaning |
|---|---|
| Problem | A work item of type `problem`: the unknown or known cause of one or more incidents. |
| Root cause | The underlying reason the incidents happened, recorded on the problem. |
| Workaround | A way to reduce or remove the effect of a problem before it is fixed for good. |
| Known error | A problem whose root cause or workaround is documented. It is a flag on the problem, not a separate record. |
| Known error database | The searchable register of all problems marked as known errors (REQ-PRB-037). |
| Linked incident | An incident associated with a problem as "caused by" (REQ-PRB-043). |
| Follow-up actions | What closing or resolving a problem does to its linked incidents (REQ-PRB-055). |
| Cluster | A group of similar incidents found by analysis that may share a cause (REQ-PRB-066). |
| Problem review | A structured look back at a problem after it is fixed (REQ-PRB-053). |

## Requirement summary

<!-- summary:start -->
**Counts by decision and priority**

| Decision | MVP | V1 | LATER | Total |
|---|---|---|---|---|
| SAME | 0 | 30 | 1 | 31 |
| BETTER | 0 | 32 | 0 | 32 |
| NEW | 0 | 13 | 3 | 16 |
| SKIP | 0 | 0 | 2 | 2 |
| **Total** | **0** | **75** | **6** | **81** |

Edition (lowest edition that includes it): Essentials 0, Professional 81, Enterprise 0. By prefix: REQ-PRB 81.

| ID | Title | Decision | Priority | Edition |
|---|---|---|---|---|
| [REQ-PRB-001](#req-prb-001--problems-are-a-work-item-type-on-the-engine) | Problems are a work item type on the engine | BETTER | V1 | Professional |
| [REQ-PRB-002](#req-prb-002--problem-record-and-core-fields) | Problem record and core fields | SAME | V1 | Professional |
| [REQ-PRB-003](#req-prb-003--human-readable-problem-ids) | Human-readable problem IDs | BETTER | V1 | Professional |
| [REQ-PRB-004](#req-prb-004--impact-urgency-and-priority-from-a-matrix) | Impact, urgency and priority from a matrix | BETTER | V1 | Professional |
| [REQ-PRB-005](#req-prb-005--problem-type-outage-window-and-root-cause-category) | Problem type, outage window and root cause category | BETTER | V1 | Professional |
| [REQ-PRB-006](#req-prb-006--services-assets-and-configuration-items-affected) | Services, assets and configuration items affected | BETTER | V1 | Professional |
| [REQ-PRB-007](#req-prb-007--impact-view-from-the-cmdb) | Impact view from the CMDB | SAME | V1 | Professional |
| [REQ-PRB-008](#req-prb-008--target-dates-instead-of-an-sla) | Target dates instead of an SLA | BETTER | V1 | Professional |
| [REQ-PRB-009](#req-prb-009--custom-fields-on-problems) | Custom fields on problems | SAME | V1 | Professional |
| [REQ-PRB-010](#req-prb-010--create-a-problem-from-the-console) | Create a problem from the console | BETTER | V1 | Professional |
| [REQ-PRB-011](#req-prb-011--create-a-problem-from-an-incident) | Create a problem from an incident | SAME | V1 | Professional |
| [REQ-PRB-012](#req-prb-012--create-one-problem-from-many-incidents) | Create one problem from many incidents | NEW | V1 | Professional |
| [REQ-PRB-013](#req-prb-013--create-a-problem-from-other-records) | Create a problem from other records | SAME | V1 | Professional |
| [REQ-PRB-014](#req-prb-014--similar-problems-and-known-errors-while-creating) | Similar problems and known errors while creating | NEW | V1 | Professional |
| [REQ-PRB-015](#req-prb-015--copy-a-problem) | Copy a problem | BETTER | V1 | Professional |
| [REQ-PRB-016](#req-prb-016--no-problems-from-email-or-the-portal) | No problems from email or the portal | SKIP | LATER | Professional |
| [REQ-PRB-017](#req-prb-017--problem-templates) | Problem templates | SAME | V1 | Professional |
| [REQ-PRB-018](#req-prb-018--analysis-and-solution-sections-on-the-template) | Analysis and solution sections on the template | SAME | V1 | Professional |
| [REQ-PRB-019](#req-prb-019--form-rules-on-problem-templates) | Form rules on problem templates | BETTER | V1 | Professional |
| [REQ-PRB-020](#req-prb-020--tasks-from-the-problem-template) | Tasks from the problem template | SAME | V1 | Professional |
| [REQ-PRB-021](#req-prb-021--templates-limited-to-groups) | Templates limited to groups | SAME | V1 | Professional |
| [REQ-PRB-022](#req-prb-022--template-designer-that-explains-itself) | Template designer that explains itself | BETTER | V1 | Professional |
| [REQ-PRB-023](#req-prb-023--problem-statuses-and-the-default-life-cycle) | Problem statuses and the default life cycle | BETTER | V1 | Professional |
| [REQ-PRB-024](#req-prb-024--status-changes-only-through-transitions-with-prompts) | Status changes only through transitions, with prompts | BETTER | V1 | Professional |
| [REQ-PRB-025](#req-prb-025--guided-analysis-life-cycle-for-major-problems) | Guided analysis life cycle for major problems | SAME | V1 | Professional |
| [REQ-PRB-026](#req-prb-026--problem-workflows) | Problem workflows | BETTER | V1 | Professional |
| [REQ-PRB-027](#req-prb-027--triggers-and-rules-on-problems) | Triggers and rules on problems | SAME | V1 | Professional |
| [REQ-PRB-028](#req-prb-028--assign-a-problem-owner) | Assign a problem owner | BETTER | V1 | Professional |
| [REQ-PRB-029](#req-prb-029--investigators-besides-the-owner) | Investigators besides the owner | NEW | V1 | Professional |
| [REQ-PRB-030](#req-prb-030--analysis-tab-impact-details-root-cause-and-symptoms) | Analysis tab: impact details, root cause and symptoms | SAME | V1 | Professional |
| [REQ-PRB-031](#req-prb-031--structured-analysis-worksheets) | Structured analysis worksheets | NEW | LATER | Professional |
| [REQ-PRB-032](#req-prb-032--evidence-panel) | Evidence panel | NEW | V1 | Professional |
| [REQ-PRB-033](#req-prb-033--impact-assessment-from-linked-incidents) | Impact assessment from linked incidents | NEW | V1 | Professional |
| [REQ-PRB-034](#req-prb-034--workaround-and-resolution) | Workaround and resolution | BETTER | V1 | Professional |
| [REQ-PRB-035](#req-prb-035--knowledge-articles-referred-to-by-a-problem) | Knowledge articles referred to by a problem | SAME | V1 | Professional |
| [REQ-PRB-036](#req-prb-036--mark-a-problem-as-a-known-error) | Mark a problem as a known error | BETTER | V1 | Professional |
| [REQ-PRB-037](#req-prb-037--known-error-database) | Known error database | BETTER | V1 | Professional |
| [REQ-PRB-038](#req-prb-038--known-error-suggestions-on-incidents) | Known error suggestions on incidents | NEW | V1 | Professional |
| [REQ-PRB-039](#req-prb-039--publish-a-workaround-to-technicians) | Publish a workaround to technicians | BETTER | V1 | Professional |
| [REQ-PRB-040](#req-prb-040--publish-a-workaround-to-the-portal) | Publish a workaround to the portal | BETTER | V1 | Professional |
| [REQ-PRB-041](#req-prb-041--save-the-resolution-as-knowledge) | Save the resolution as knowledge | SAME | V1 | Professional |
| [REQ-PRB-042](#req-prb-042--retire-a-known-error-when-the-fix-is-in) | Retire a known error when the fix is in | NEW | V1 | Professional |
| [REQ-PRB-043](#req-prb-043--link-many-incidents-to-a-problem) | Link many incidents to a problem | BETTER | V1 | Professional |
| [REQ-PRB-044](#req-prb-044--link-changes-that-fix-the-problem) | Link changes that fix the problem | SAME | V1 | Professional |
| [REQ-PRB-045](#req-prb-045--link-releases) | Link releases | SAME | V1 | Professional |
| [REQ-PRB-046](#req-prb-046--related-problems-and-merging-duplicate-problems) | Related problems and merging duplicate problems | NEW | V1 | Professional |
| [REQ-PRB-047](#req-prb-047--announcements-from-a-problem) | Announcements from a problem | SAME | V1 | Professional |
| [REQ-PRB-048](#req-prb-048--tasks-on-a-problem-with-progress) | Tasks on a problem with progress | SAME | V1 | Professional |
| [REQ-PRB-049](#req-prb-049--approvals-on-a-problem) | Approvals on a problem | BETTER | V1 | Professional |
| [REQ-PRB-050](#req-prb-050--accept-a-known-error-without-a-fix) | Accept a known error without a fix | NEW | V1 | Professional |
| [REQ-PRB-051](#req-prb-051--worklogs-notes-and-reminders-on-problems) | Worklogs, notes and reminders on problems | SAME | V1 | Professional |
| [REQ-PRB-052](#req-prb-052--send-a-message-from-a-problem) | Send a message from a problem | BETTER | V1 | Professional |
| [REQ-PRB-053](#req-prb-053--problem-review) | Problem review | NEW | V1 | Professional |
| [REQ-PRB-054](#req-prb-054--problem-closure-rules) | Problem closure rules | BETTER | V1 | Professional |
| [REQ-PRB-055](#req-prb-055--follow-up-actions-on-linked-incidents) | Follow-up actions on linked incidents | BETTER | V1 | Professional |
| [REQ-PRB-056](#req-prb-056--close-with-a-closure-code-in-one-step) | Close with a closure code in one step | BETTER | V1 | Professional |
| [REQ-PRB-057](#req-prb-057--reopen-a-problem) | Reopen a problem | BETTER | V1 | Professional |
| [REQ-PRB-058](#req-prb-058--cancel-a-problem) | Cancel a problem | SAME | V1 | Professional |
| [REQ-PRB-059](#req-prb-059--editing-closed-problems-is-controlled) | Editing closed problems is controlled | SAME | V1 | Professional |
| [REQ-PRB-060](#req-prb-060--problem-list-and-columns) | Problem list and columns | SAME | V1 | Professional |
| [REQ-PRB-061](#req-prb-061--built-in-problem-views) | Built-in problem views | SAME | V1 | Professional |
| [REQ-PRB-062](#req-prb-062--search-across-problems-and-known-errors) | Search across problems and known errors | SAME | V1 | Professional |
| [REQ-PRB-063](#req-prb-063--bulk-actions-on-problems) | Bulk actions on problems | SAME | V1 | Professional |
| [REQ-PRB-064](#req-prb-064--the-problem-record-page) | The problem record page | BETTER | V1 | Professional |
| [REQ-PRB-065](#req-prb-065--print-a-problem) | Print a problem | SAME | V1 | Professional |
| [REQ-PRB-066](#req-prb-066--incident-cluster-analysis) | Incident cluster analysis | BETTER | V1 | Professional |
| [REQ-PRB-067](#req-prb-067--admin-defined-cluster-analyses) | Admin-defined cluster analyses | SAME | V1 | Professional |
| [REQ-PRB-068](#req-prb-068--repeat-incident-rules-without-ai) | Repeat incident rules without AI | NEW | V1 | Professional |
| [REQ-PRB-069](#req-prb-069--ai-help-on-a-problem) | AI help on a problem | BETTER | V1 | Professional |
| [REQ-PRB-070](#req-prb-070--problem-permissions) | Problem permissions | SAME | V1 | Professional |
| [REQ-PRB-071](#req-prb-071--incident-technicians-see-what-they-need-of-a-problem) | Incident technicians see what they need of a problem | NEW | V1 | Professional |
| [REQ-PRB-072](#req-prb-072--problem-notifications-with-sensible-defaults) | Problem notifications with sensible defaults | BETTER | V1 | Professional |
| [REQ-PRB-073](#req-prb-073--problem-reports-and-metrics) | Problem reports and metrics | BETTER | V1 | Professional |
| [REQ-PRB-074](#req-prb-074--problem-counters-and-dashboard-widgets) | Problem counters and dashboard widgets | SAME | V1 | Professional |
| [REQ-PRB-075](#req-prb-075--what-requesters-see) | What requesters see | NEW | V1 | Professional |
| [REQ-PRB-076](#req-prb-076--live-updates-on-problem-screens) | Live updates on problem screens | BETTER | V1 | Professional |
| [REQ-PRB-077](#req-prb-077--no-alert-correlation-for-problem-detection) | No alert correlation for problem detection | SKIP | LATER | Professional |
| [REQ-PRB-078](#req-prb-078--health-and-history-of-affected-items-from-monetx) | Health and history of affected items from MonetX | NEW | LATER | Professional |
| [REQ-PRB-079](#req-prb-079--problem-investigation-agent) | Problem investigation agent | NEW | LATER | Professional |
| [REQ-PRB-080](#req-prb-080--problems-on-the-mobile-app) | Problems on the mobile app | SAME | V1 | Professional |
| [REQ-PRB-081](#req-prb-081--import-problems) | Import problems | SAME | LATER | Professional |
<!-- summary:end -->

---

## 1. The problem record and its classification

#### REQ-PRB-001 — Problems are a work item type on the engine

Problems run on the work item engine (REQ-WI-001). Everything a work item gets from the engine
works on a problem without problem-specific code:

- notes, the conversation timeline, attachments, reminders and followers;
- tasks with dependencies, checklists and worklogs;
- approvals, links, merge and its undo;
- field history, live updates, trash and restore, the API and domain events.

Notes on a problem have the same public and private split as on an incident. "Public" on a
problem means visible to technicians who can see the problem and to the people the problem
notifies, never to requesters directly.

- **Decision:** BETTER. ServiceDesk Plus rebuilds these features for problems, so they behave
  differently; for example problem notes have no private option.
- **Source:** architecture §2.3, §6.2; sdp-area-04 §Screens (tabs, reminders, worklogs,
  conversations, history, trashed problems), §Weak spots (no public/private notes)
- **SDP weak spot fixed:** problem notes cannot be marked private, unlike request notes.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. The engine's shared contract test suite (notes, tasks, checklists, attachments, links,
     history) passes for the problem type.
  2. A private note on a problem is never included in any notification or in any linked
     incident's view.
  3. A deleted problem goes to trash and can be restored within the trash retention period
     (30 days by default, REQ-WI-020).
  4. Every problem action available in the console is available through the public API with
     the same permission checks.

#### REQ-PRB-002 — Problem record and core fields

A problem has these fields:

- title (required) and description (rich text);
- reported by, created by and source (manual, from incidents, from a cluster, from a change or
  release, from a review, API);
- site, group and technician (the problem owner);
- category, subcategory and item;
- impact, urgency and priority;
- problem type, status and the known error flag;
- target date, resolved time and closed time;
- services affected, assets involved and configuration items involved;
- impact start and end time, and outage reason;
- analysis fields: impact details, root cause, root cause category and symptoms;
- solution fields: workaround and resolution;
- template, tags and custom fields.

- **Decision:** SAME. The same field set as the ServiceDesk Plus problem form, in our own
  layout, plus a recorded source.
- **Source:** sdp-area-04 §Fields (new problem form), §Screens (details tab, right panel);
  sdp-area-12 §Config (problem template extra fields); architecture §2.3
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A problem can be created with only a title; every other field is optional unless a
     template, rule or closure rule requires it.
  2. Each field is readable and writable through the API and can be used as a list column, a
     filter and a report field.
  3. The source is set by the system from how the problem was created and cannot be edited.
  4. Analysis and solution fields keep their own history entries, separate from the details
     fields.

#### REQ-PRB-003 — Human-readable problem IDs

Problems get their own display ID counter with the prefix PRB, for example PRB-12. An admin can
change the prefix (D-045). The counter cannot be set back to a number already used.

- **Decision:** BETTER. ServiceDesk Plus lets an admin edit the "starts with" number, which can
  collide with existing IDs.
- **Source:** sdp-area-04 §Config (problem ID prefix and start number); D-045; REQ-WI-002
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. The first problem in a new tenant is PRB-1, independent of the incident counter.
  2. Changing the prefix to PBM makes the next problem PBM-n, and PRB-1 still opens by its
     old ID.
  3. Setting the next number lower than the highest used number is refused with a reason.

#### REQ-PRB-004 — Impact, urgency and priority from a matrix

Problems use the same clean impact and urgency scales as incidents (REQ-INC-008). Priority is
calculated from a problem priority matrix, which starts as a copy of the incident matrix and
can be changed separately. Overriding the calculated priority needs permission and a reason
(as REQ-INC-010). A problem is never left silently without a priority (as REQ-INC-011).

- **Decision:** BETTER. ServiceDesk Plus has no matrix for problems, so priority stays unset,
  and its impact list mixes scopes ("affects group") with levels ("high").
- **Source:** sdp-area-04 §Fields (impact, urgency, priority), §Behaviour (priority not
  assigned), §Weak spots
- **SDP weak spot fixed:** priority is not calculated from impact and urgency and stays "not
  assigned"; the impact values mix two different scales.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. In a new tenant, a problem with impact "a department or site" and urgency "high" gets P2
     with no admin set-up (Appendix A).
  2. Changing the problem matrix does not change the incident matrix, and the reverse.
  3. A problem saved without impact and urgency gets the default priority, marked as
     defaulted.

#### REQ-PRB-005 — Problem type, outage window and root cause category

Admins define problem types (for example reactive and proactive) and root cause categories
(Appendix A). A problem can record when its impact started and ended and the reason for the
outage. The root cause category is a pick list next to the free-text root cause, so reports can
group problems by cause.

- **Decision:** BETTER. ServiceDesk Plus offers problem type, impact times and outage reason as
  optional fields; we add a structured root cause category for reporting.
- **Source:** sdp-area-04 §Config (template designer available fields); sdp-area-12 §Config
  (problem extra fields); product-plan §5 (problem: RCA)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. An impact end time earlier than the impact start time is refused with a field error.
  2. A report can group closed problems by root cause category.
  3. Disabling a root cause category hides it for new problems and keeps it on old ones.

#### REQ-PRB-006 — Services, assets and configuration items affected

A problem records the services affected, the assets involved and the configuration items
involved, picked from the asset register and the CMDB (file 07). The pickers search every
record the user may see. The asset and CI pages show their linked problems with live counts.

- **Decision:** BETTER. The links are counted on both sides, which ServiceDesk Plus does not
  always do.
- **Source:** sdp-area-04 §Fields (services affected, assets involved, CIs involved);
  sdp-area-07 (7b.5) §Behaviour (asset side missing a change counter); architecture §2.3
  (associate CIs)
- **SDP weak spot fixed:** a link made from one record does not always show a counter on the
  other.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Adding an asset to a problem shows the problem on the asset page and raises its problem
     counter live.
  2. The picker finds an asset by name, tag or serial number.
  3. Removing the asset records the removal in the history of both records.

#### REQ-PRB-007 — Impact view from the CMDB

From a problem with configuration items or services, the technician opens an impact view: the
CMDB relationship map around the affected items, the services that depend on them, and the
open incidents and changes on those items.

- **Decision:** SAME.
- **Source:** architecture §2.3 (CMDB impact view), §2.12; product-plan §5 (problem)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A problem linked to a server CI shows the business services that depend on that server.
  2. Open incidents on any item in the view are listed with their display IDs.
  3. Items the user may not see are shown as present but unnamed.

#### REQ-PRB-008 — Target dates instead of an SLA

A problem has a target date for the fix. It can be set by hand or from a target policy by
priority (for example P1 within 5 business days), defined with the SLA engine (file 03). The
target date counts down on the record and in lists, pauses in paused statuses and raises an
escalation when missed. Response and resolution SLAs are off for problems by default.

- **Decision:** BETTER. ServiceDesk Plus problems only have a free due-by date with nothing
  driving it.
- **Source:** sdp-area-04 §Fields (due by date), §Behaviour (no SLA or due date on creation)
- **SDP weak spot fixed:** nothing sets or watches the due date of a problem.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. With a target policy "P2: 10 business days", a P2 problem created on Monday gets a target
     date ten business days later in the tenant's operating hours.
  2. Moving the problem to a paused status stops the countdown, and history records the pause.
  3. A missed target date notifies the problem owner and the group head.
  4. A target date set by hand is recorded with actor and reason, and is not overwritten by
     the policy.

#### REQ-PRB-009 — Custom fields on problems

Admins add custom fields to problems through the metadata engine, with the same field types as
on incidents (REQ-INC-014), and place them in any section of a problem template, including the
analysis and solution sections.

- **Decision:** SAME.
- **Source:** sdp-area-04 §Config (template designer new-field types); architecture §6.6
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A custom pick-list field added to problems appears on the form, in list columns and in
     filters.
  2. A custom field added to problems never shows on incidents.
  3. A custom field placed in the analysis section is edited with the analysis permission
     (REQ-PRB-070).

---

## 2. Creating problems

#### REQ-PRB-010 — Create a problem from the console

A technician with permission creates a problem from the problems list, the global "new" menu or
a keyboard shortcut, choosing a template first. "Reported by" defaults to the creator and can be
changed to any user.

- **Decision:** BETTER. ServiceDesk Plus leaves "reported by" empty and shows "N/A".
- **Source:** sdp-area-04 §Navigation path, §Screens (new problem form), §Behaviour (reported by
  N/A); sdp-area-01 §Screens (quick actions, new problem shortcut)
- **SDP weak spot fixed:** a problem can be saved with no reporter and no owner.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A problem created with only a title shows the creator as reported by.
  2. The create form opens with the default problem template selected.
  3. The new problem appears in every open problems list within one second.

#### REQ-PRB-011 — Create a problem from an incident

From an incident, a technician creates a problem that is pre-filled and linked. The new problem
copies the incident's subject, description, category, subcategory, item, impact, urgency,
site, services, assets and configuration items. The technician sees the pre-filled form and
can change it before saving. The incident and the problem are linked as "caused by" (REQ-INC-087).

- **Decision:** SAME.
- **Source:** architecture §2.3 (created from incidents); REQ-INC-087; sdp-area-02c §Screens
  (associations)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Creating a problem from INC-40 opens a form with INC-40's subject and category already
     filled.
  2. After saving, INC-40 shows the problem and the problem shows INC-40, with history on both.
  3. Attachments are offered for copying but are not copied unless chosen.

#### REQ-PRB-012 — Create one problem from many incidents

A technician selects several incidents in a list, or a cluster (REQ-PRB-066), and creates one
problem from them. The form is pre-filled from the incident they mark as the main one, and
every selected incident is linked to the new problem. Incidents already linked to another
problem are listed first, and the technician chooses to move them or leave them.

- **Decision:** NEW. ServiceDesk Plus creates a problem from one incident at a time and attaches
  the others one by one.
- **Source:** architecture §2.3 (link many incidents to one problem); sdp-area-04 §Screens
  (associated incidents attach)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Selecting 12 incidents and creating a problem links all 12 in one step.
  2. An incident already linked to another problem is listed before saving, and is moved only
     if the technician confirms.
  3. The new problem's history lists every incident linked at creation.
  4. A selection larger than 1,000 incidents is refused with the limit explained.

#### REQ-PRB-013 — Create a problem from other records

A problem can also be created, pre-filled and linked, from:

- a change or release, for example when a release causes new faults;
- an asset or configuration item;
- a follow-up action in a post-incident review (REQ-INC-144) or a problem review
  (REQ-PRB-053).

- **Decision:** SAME.
- **Source:** sdp-area-04 §Screens (release that initiated problem); sdp-area-06 §Behaviour
  (problems caused by release); REQ-INC-144
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Creating a problem from a release links them as "release that caused the problem" on both
     records.
  2. Creating a problem from a CI fills the CI into "configuration items involved".
  3. The problem's source field records where it was created from.

#### REQ-PRB-014 — Similar problems and known errors while creating

While a technician types the title of a new problem, open problems and known errors with
similar titles, symptoms or root causes are listed. The technician can open one, or link the
incidents to it instead of creating a duplicate.

- **Decision:** NEW. ServiceDesk Plus gives no warning of a duplicate problem.
- **Source:** sdp-area-04 §Weak spots (duplicate-looking rows); REQ-INC-022
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Typing a title close to an open problem's title lists that problem within one second.
  2. Choosing "link to this problem instead" links the source incidents and creates no new
     problem.
  3. Only problems the user may see are listed.

#### REQ-PRB-015 — Copy a problem

A technician copies a problem and chooses which parts to carry over: fields, attachments,
tasks, analysis (impact details, root cause, symptoms) and solution (workaround, resolution).
The copy gets a new ID, a title marked as a copy, and a history entry naming the original.
Links to incidents, conversations, worklogs and history are never copied.

- **Decision:** BETTER. ServiceDesk Plus copies the title unchanged, so copies look like
  duplicates.
- **Source:** sdp-area-04 §Actions (copy problem), §Behaviour (copy kept title), §Weak spots;
  architecture §2.3 (copy problem); REQ-INC-033
- **SDP weak spot fixed:** the copy keeps the identical title.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Copying PRB-5 with only "fields" and "analysis" ticked creates a problem with those parts
     and no tasks or attachments.
  2. The copy's title is marked as a copy, and its history names PRB-5.
  3. Values that are now disabled (for example a retired category) are listed before
     confirming and are left empty on the copy.

#### REQ-PRB-016 — No problems from email or the portal

Problems are not created from inbound email or by requesters in the portal. Email and portal
reports create incidents, which technicians then link to problems.

- **Decision:** SKIP. Problems are an internal technician practice; letting requesters or mail
  create them would bypass triage. Replaced by incident channels (file 01) and REQ-PRB-011,
  REQ-PRB-012.
- **Source:** sdp-area-04 §Navigation path (console-only creation); architecture §2.3
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A mail rule cannot target the problem type; the rule editor does not offer it.
  2. The portal API has no endpoint that creates a problem.

---

## 3. Templates and forms

#### REQ-PRB-017 — Problem templates

Admins create problem templates with the same designer as incident templates (REQ-INC-035,
REQ-INC-036). A problem template sets the fields shown, their defaults and which are required,
and attaches a life cycle (REQ-PRB-023) and a workflow (file 03). A new tenant gets two
templates (Appendix A): a standard problem and a major problem template with the analysis and
solution sections on the create form.

- **Decision:** SAME.
- **Source:** sdp-area-04 §Config (problem template list, template designer); sdp-area-12
  §Config (problem template designer); architecture §2.3 (problem templates with form rules)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A new tenant has a default standard problem template and a major problem template.
  2. A template with default group "Network" fills that group on the create form.
  3. A disabled template is not offered for new problems but still opens on problems created
     from it.

#### REQ-PRB-018 — Analysis and solution sections on the template

A problem template has sections for details, analysis and solution. Each section can be shown
on the create form or only on the record later. Fields can be added to any section, and each
section can be required at a chosen point in the life cycle (REQ-PRB-024).

- **Decision:** SAME.
- **Source:** sdp-area-04 §Fields (major problem template sections), §Config (template tabs
  details, analysis, solution)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. On a template with the analysis section on the create form, root cause and symptoms can be
     entered when the problem is created.
  2. On a template without it, the create form shows no analysis fields, and the analysis tab
     is available on the record after saving.

#### REQ-PRB-019 — Form rules on problem templates

Problem templates have form rules that show, hide, require, lock or set fields, enforced in the
browser and on the server alike (REQ-INC-037). Editing a single field in place on the record
obeys the same rules, so there is no need to switch in-place editing off when rules exist.

- **Decision:** BETTER. ServiceDesk Plus offers a setting to turn off in-place editing when a
  form rule exists, because in-place edits would otherwise skip the rule.
- **Source:** sdp-area-04 §Config (disable spot edit when a form rule is configured, form rules
  tab); architecture §2.3 (form rules)
- **SDP weak spot fixed:** in-place edits can get around form rules, so admins must choose
  between rules and quick editing.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A rule "if impact is the whole organisation, require services affected" blocks an
     in-place edit of impact that leaves services affected empty.
  2. The API returns the same field error code as the UI for that rule.

#### REQ-PRB-020 — Tasks from the problem template

A problem template can include tasks with owners, groups, dependencies and order. They are
created when the problem is created, or when it enters a chosen status (for example
"investigating"). Their creation is recorded in history (REQ-INC-040).

- **Decision:** SAME.
- **Source:** sdp-area-04 §Config (template tasks tab: add task, organise, task dependency);
  sdp-area-12 (12b) §Config (template tasks)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A problem created from a template with three tasks has those three tasks, and history
     names the template.
  2. A template task set to "on entering investigating" is created only when that transition
     runs.
  3. A dependent task cannot start before the task it depends on is done (REQ-INC-075).

#### REQ-PRB-021 — Templates limited to groups

A problem template can be limited to chosen technician groups. Only members of those groups see
it when creating a problem. Admins see all templates.

- **Decision:** SAME.
- **Source:** sdp-area-04 §Config (additional settings: associate groups to template)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A template limited to the network group is not offered to a technician outside that group.
  2. A problem already created from that template stays visible to anyone with access to the
     problem.

#### REQ-PRB-022 — Template designer that explains itself

A new problem template can be designed fully before its first save. Where a part of the
designer cannot be used yet, it says why and what to do. All problem settings are reachable
from one problem management area in admin: templates, statuses, life cycles, closure codes,
closure rules, root cause categories, target policies and the ID prefix.

- **Decision:** BETTER.
- **Source:** sdp-area-04 §Weak spots (greyed tabs with no reason, deep click path to settings,
  empty workflow tab)
- **SDP weak spot fixed:** on a new template the analysis, solution, tasks and rules tabs are
  greyed with no explanation; problem settings are spread across two admin menus.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Tasks and form rules can be added to a new template before its first save, and all are
     saved together.
  2. Any disabled designer control shows a reason on hover and focus.
  3. The problem admin area links to every problem setting listed above.

---

## 4. Statuses, life cycles and workflows

#### REQ-PRB-023 — Problem statuses and the default life cycle

Problem statuses use the same fixed status categories as incidents (REQ-INC-044). A new tenant
gets a ready-made problem life cycle (Appendix A): new, assigned, investigating, root cause
found, awaiting fix, on hold, resolved, closed and canceled, with the allowed transitions. It
works with no set-up. Admins can copy and change it in the life cycle designer (REQ-INC-049).

- **Decision:** BETTER. ServiceDesk Plus ships problem statuses as a flat list with no
  transitions on the standard template.
- **Source:** sdp-area-04 §Fields (status list), §Automation (life cycles); sdp-area-12
  §Screens (life cycles for problems); architecture §2.3 (problem life cycle canvas)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A new tenant's first problem follows the default life cycle with no admin set-up.
  2. Only the transitions in Appendix A are offered from each status.
  3. A status in the paused category pauses the target date countdown (REQ-PRB-008).

#### REQ-PRB-024 — Status changes only through transitions, with prompts

A problem's status changes only through allowed transitions, on every path (REQ-INC-046).
There is no free status field in the edit form. Transitions can require fields and reasons
(REQ-INC-047, REQ-INC-048), for example root cause before "root cause found" and a workaround
before marking a known error. Resolved and closed times are stamped by the system and cannot be
edited by hand.

- **Decision:** BETTER. In ServiceDesk Plus the edit form lets anyone set any status, including
  "closed", and edit the closed date by hand.
- **Source:** sdp-area-04 §Behaviour (edit form, reopen via edit), §Fields (closed date);
  sdp-area-12 (12b) §Screens (transition during: mandatory fields)
- **SDP weak spot fixed:** status and closed date are freely editable, which bypasses closure
  rules and makes report dates unreliable.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. The problem edit form and the API field update both refuse a status value; only the
     transition endpoint changes status.
  2. Running "root cause found" without a root cause opens a prompt for that field only.
  3. The closed time is set by the close transition, and the API refuses a direct write to it.

#### REQ-PRB-025 — Guided analysis life cycle for major problems

A new tenant also gets a guided life cycle for major problems (Appendix A) that walks the team
through structured analysis: record the facts, ask why until the cause is found, confirm the
cause, plan the fix, verify it. Each step can require its own fields. It is attached to the
major problem template.

- **Decision:** SAME. ServiceDesk Plus ships a ready-made major problem life cycle; the
  architecture asks for a five-whys style flow.
- **Source:** sdp-area-04 §Edition notes (major problem life cycle), §Screens (transitions box);
  architecture §2.3 (life cycle canvas, for example a Five Whys flow)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A problem from the major problem template shows the guided steps and the next allowed
     transition above its tabs.
  2. The "cause confirmed" step cannot run while the root cause field is empty.
  3. An admin can copy the guided life cycle and change its steps.

#### REQ-PRB-026 — Problem workflows

Admins attach visual workflows (file 03) to problem templates, for example to create tasks,
request approval or notify a team when a problem enters a status. Problems appear in the
workflow designer's type list, and a workflow can wait on problem events such as "incident
linked" and "known error marked".

- **Decision:** BETTER. In ServiceDesk Plus the workflow picker on a problem template showed no
  workflows, so only life cycles could be used.
- **Source:** sdp-area-04 §Weak spots (empty workflow tab); sdp-area-12 §Screens (workflows per
  module); architecture §2.3 (visual problem workflows)
- **SDP weak spot fixed:** problem workflows could not be attached from the template designer.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A workflow published for problems is offered in the problem template's workflow picker.
  2. A workflow step that waits for "known error marked" continues when a technician marks the
     problem.
  3. Each workflow action on a problem is recorded in its history with the workflow's name
     (REQ-WI-004).

#### REQ-PRB-027 — Triggers and rules on problems

Business rules and triggers (file 03) can run on problems when they are created, edited or
change status, and on problem events such as an incident being linked. Typical uses: set the
group from the category, notify the problem manager when a P1 problem is created.

- **Decision:** SAME.
- **Source:** sdp-area-12 §Screens (triggers offer the problem module)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A rule "category is network → group network" sets the group on a new problem and records
     the rule in history.
  2. A trigger on "incident linked" fires once per linked incident.

---

## 5. Assignment and ownership

#### REQ-PRB-028 — Assign a problem owner

A problem is assigned to a group and a technician, who owns it. Technicians can pick up an
unassigned problem from the list or the record, singly or in bulk. The technician picker shows
only members of the chosen group first, with an option to search all. Assignment moves the
status from new to assigned (REQ-INC-050).

- **Decision:** BETTER. ServiceDesk Plus does not filter the technician list by group, and
  assignment does not move the status.
- **Source:** sdp-area-04 §Fields (assign technician dialog), §Actions (pick up, assign),
  §Behaviour (status stayed open), §Weak spots (technician list not filtered by group)
- **SDP weak spot fixed:** the technician list ignores the chosen group; assigning leaves the
  status unchanged.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Choosing the network group lists network members first in the technician picker.
  2. Picking up a new problem sets the technician to the current user and the status to
     assigned.
  3. Bulk assigning 20 problems reports which were changed and which were skipped and why.

#### REQ-PRB-029 — Investigators besides the owner

Besides the owner, a problem can have investigators: technicians from other groups who work on
it through tasks, notes and worklogs. Investigators can see and work on the problem even if
their scope would not otherwise include it, and are notified like followers.

- **Decision:** NEW. ServiceDesk Plus has one technician per problem; others only reach it
  through task ownership.
- **Source:** sdp-area-04 §Fields (technician, task owner); sdp-area-11 §Fields (granular scope
  for problems)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Adding an investigator from another site gives them access to that problem only.
  2. An investigator receives notifications for public notes on the problem.
  3. Removing an investigator removes their access, and history records both changes.

---

## 6. Analysis

#### REQ-PRB-030 — Analysis tab: impact details, root cause and symptoms

The analysis tab holds impact details, root cause and symptoms. Each is a rich-text field with
its own attachments, edited in place and recorded separately in history. Editing them needs the
"modify analysis" permission (REQ-PRB-070). The tab shows who last changed each field and when.

- **Decision:** SAME.
- **Source:** sdp-area-04 §Screens (analysis tab with impact details, root cause, symptoms);
  sdp-area-11 §Fields (modify analysis details); architecture §2.3 (analysis)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Saving a root cause writes one history entry for the root cause only.
  2. A technician without "modify analysis" sees the analysis read-only, and the API refuses
     their change with 403.
  3. An image pasted into symptoms is stored as an attachment and survives sanitising.

#### REQ-PRB-031 — Structured analysis worksheets

A technician can add a structured analysis to a problem: a why-chain (each answer leads to the
next question), a cause-and-effect breakdown by cause area, or a timeline of events. The
worksheet is stored as data on the problem, printed with it and searchable. The confirmed cause
can be copied into the root cause field.

- **Decision:** NEW. ServiceDesk Plus has only free-text analysis fields.
- **Source:** architecture §2.3 (five whys); product-plan §5 (problem: RCA)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A why-chain with five levels is saved and shown in order on the analysis tab.
  2. Marking one entry as the confirmed cause copies it into the root cause field, recorded in
     history.
  3. Worksheets render correctly right-to-left in Arabic and Urdu.

#### REQ-PRB-032 — Evidence panel

The analysis tab shows the evidence around a problem, gathered automatically:

- a timeline of its linked incidents, by when they were reported;
- changes and releases on the affected items in a chosen window before the first incident
  (72 hours by default, Appendix A);
- other problems on the same items;
- MonetX problem history for the affected items, read-only, if the connector is set up
  (REQ-PRB-078).

- **Decision:** NEW. ServiceDesk Plus leaves the technician to search for related changes and
  incidents.
- **Source:** product-plan §5 (AI RCA using CMDB, metrics and change history); D-001
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A change implemented on an affected CI 24 hours before the first linked incident appears
     in the panel.
  2. Linking a new incident adds it to the timeline live.
  3. Records the user may not see are left out of the panel.

#### REQ-PRB-033 — Impact assessment from linked incidents

The problem shows figures calculated from its linked incidents: how many there are, how many
are still open, how many people and sites they affect, the total time they were open, worklog
time and cost spent on them, and the trend over the last weeks. The figures update as incidents
are linked, unlinked and resolved.

- **Decision:** NEW. ServiceDesk Plus shows only a count of associated incidents.
- **Source:** sdp-area-04 §Screens (association counts); sdp-area-09 §Screens (problem reports:
  incident counts, cost)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Linking an incident raises the linked and open counts on the problem within one second.
  2. Total worklog time equals the sum of worklogs on the linked incidents.
  3. Cost figures follow the worklog cost rules (REQ-INC-068) and are hidden from users without
     cost permission.

---

## 7. Workaround, resolution and known errors

#### REQ-PRB-034 — Workaround and resolution

The solution tab holds the workaround and the permanent resolution, each in rich text with
attachments. From either editor the technician can search the knowledge base (starting with
the problem title as the query), copy an article in, or use a resolution template
(REQ-INC-042). Editing them needs the "modify solution" permission.

- **Decision:** BETTER. ServiceDesk Plus does not pre-fill the knowledge search on a problem.
- **Source:** sdp-area-04 §Screens (solution tab: workaround, resolution); sdp-area-08
  §Behaviour (problem to solution, search not pre-filled); sdp-area-11 §Fields (modify solution
  details)
- **SDP weak spot fixed:** knowledge search from a problem starts empty and lists everything.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A knowledge search from the workaround editor starts with the problem title.
  2. Saving a workaround writes a history entry and notifies followers.
  3. Without "modify solution", the solution tab is read-only and the API refuses changes.

#### REQ-PRB-035 — Knowledge articles referred to by a problem

A technician can link knowledge articles to a problem. The problem lists its referred
articles, and each article lists the problems that refer to it, with history on both sides.

- **Decision:** SAME.
- **Source:** sdp-area-08 §Screens (solution right panel: referred in problems), §Behaviour
  (problem to solution)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Linking an article to PRB-3 shows PRB-3 under the article's referring problems.
  2. A user who cannot see the article sees that a link exists, but not its title.

#### REQ-PRB-036 — Mark a problem as a known error

A technician with permission marks a problem as a known error, with a comment. By default a
workaround or a root cause must be recorded first (Appendix A). The known error flag, who set
it and when show on the record header, in lists and on every linked incident. The flag can be
removed with a reason. The action keeps its place in the menu whether the problem is a known
error or not; the opposite action replaces it in the same position.

- **Decision:** BETTER. ServiceDesk Plus hides the menu item once used, so other menu items
  shift and get clicked by mistake, and it does not check that anything is documented.
- **Source:** sdp-area-04 §Fields (mark as known error dialog), §Behaviour, §Weak spots
  (menu items move); architecture §2.3 (mark as known error); REQ-WI-010
- **SDP weak spot fixed:** the menu changes shape after marking; a known error can be marked
  with nothing documented.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Marking a problem with no workaround and no root cause is refused under default settings,
     and the message names the missing fields.
  2. After marking, the action menu has the same number of entries in the same order.
  3. Every linked incident shows the known error marker live.
  4. Removing the flag needs a reason, recorded in history.

#### REQ-PRB-037 — Known error database

All problems marked as known errors form the known error database: a dedicated, searchable view
with title, symptoms, root cause, workaround, status, affected services and CIs, the number of
linked incidents and the linked fix (change or release). Technicians search it by symptoms and
error text. Retired known errors stay searchable with a retired marker.

- **Decision:** BETTER. ServiceDesk Plus has only a "known errors" list view of problems, with
  no search across symptoms and workaround.
- **Source:** sdp-area-04 §Screens (public views: known errors); architecture §2.3 (known error
  database); product-plan §5 (known error database)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Searching for an error message that appears only in a known error's symptoms finds that
     known error.
  2. The view shows linked incident counts that update live.
  3. A retired known error is found by search and labelled retired.

#### REQ-PRB-038 — Known error suggestions on incidents

When a technician logs or works an incident, known errors that match its subject, description,
category or affected items are suggested. With one action the technician links the incident to
the problem and copies the workaround into a reply or the resolution. The suggestion records
whether it was used.

- **Decision:** NEW. In ServiceDesk Plus a workaround reaches incidents only if someone turns it
  into a knowledge article.
- **Source:** architecture §2.3 (known error database); product-plan §5 (known error
  database); sdp-area-08 §Behaviour (suggested solutions)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. An incident whose description contains a known error's error text shows that known error
     as a suggestion.
  2. "Apply workaround" links the incident to the problem and inserts the workaround into the
     reply editor, without sending it.
  3. Suggestions are not shown for known errors the technician may not see.

#### REQ-PRB-039 — Publish a workaround to technicians

A technician can publish a problem's workaround as a knowledge article for technicians. The
article is created as a draft in the knowledge approval flow (file 08), is linked to the
problem, and shows the problem's status. When the workaround on the problem changes, the
article's owner is asked to update it.

- **Decision:** BETTER. In ServiceDesk Plus the workaround and a knowledge article are separate
  copies that drift apart.
- **Source:** sdp-area-08 §Actions (save and add to solutions), §Behaviour (problem to
  solution); sdp-area-04 §Screens (solution tab)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Publishing creates a draft article linked to the problem, not visible to requesters.
  2. Editing the workaround on the problem creates a review task for the article's owner.
  3. The article shows the problem's current status live.

#### REQ-PRB-040 — Publish a workaround to the portal

A technician with permission can also publish a workaround to requesters, as a known issue in
the portal and in the portal knowledge base, for chosen audiences. Publishing goes through the
knowledge approval flow. The text shown to requesters is separate from the internal workaround,
so internal detail stays internal. Requesters whose incidents are linked to the problem see it
on their incident.

- **Decision:** BETTER. ServiceDesk Plus publishes a workaround only by copying it into a
  solution and publishing that; there is no separate requester-facing text.
- **Source:** sdp-area-08 §Fields (publish in self-service portal, user groups); architecture
  §2.3 (known error database); sdp-area-04 §Actions (notify incident requesters)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A published known issue appears in the portal for the chosen audience only, after
     approval.
  2. The requester-facing text never includes the internal workaround or root cause unless the
     technician copied it there.
  3. A requester with a linked incident sees the known issue on that incident in the portal
     within one second of approval.

#### REQ-PRB-041 — Save the resolution as knowledge

From the resolution, a technician saves a knowledge article draft, pre-filled with the problem
title, root cause and resolution, linked to the problem (as REQ-INC-091).

- **Decision:** SAME.
- **Source:** sdp-area-08 §Behaviour (problem to solution: save and add to solutions)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. "Save as knowledge" creates an unpublished draft linked to the problem.
  2. The draft keeps the resolution's formatting and images.

#### REQ-PRB-042 — Retire a known error when the fix is in

When a problem with the known error flag is resolved with a permanent fix, the known error is
retired. Workaround articles and portal known issues linked to it are flagged for review or
withdrawn, as the tenant chooses (Appendix A). Incidents still open and linked are listed for
follow-up (REQ-PRB-055).

- **Decision:** NEW. ServiceDesk Plus leaves the known error flag and published workarounds as
  they are after the fix.
- **Source:** sdp-area-04 §Behaviour (known error flag kept on copy and close); sdp-area-08
  §Screens (expired solutions)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Resolving a known error problem marks it retired, recorded in history.
  2. Under the default setting, its portal known issue is withdrawn and disappears from the
     portal live.
  3. Its technician workaround article gets a review flag and stays published until reviewed.

---

## 8. Linking incidents, changes, releases and other records

#### REQ-PRB-043 — Link many incidents to a problem

A technician links incidents to a problem from either side, singly or in bulk, and unlinks them
with history on both sides. An incident is caused by at most one problem; linking it to a
second problem asks to move it. The problem lists its linked incidents with ID, subject,
requester, technician, due date, status and created time, and the incident shows its problem,
the problem's status and the known error marker.

- **Decision:** BETTER. Links are recorded on both sides with a single label pair
  (REQ-INC-087), and the incident shows the problem's state.
- **Source:** sdp-area-04 §Screens (associations: associated incidents attach and detach);
  sdp-area-05 §Behaviour (5b: request side has no history); architecture §2.3 (link many
  incidents to one problem)
- **SDP weak spot fixed:** only one side of a link records it.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Linking 50 incidents from the incident list in one bulk action links all 50 and writes
     history on each incident and on the problem.
  2. Linking an incident that already has a problem asks to move it, and moving it is recorded
     on all three records.
  3. The incident record shows the problem's status and changes it live when the problem moves.

#### REQ-PRB-044 — Link changes that fix the problem

From a problem, a technician creates a change that is pre-filled and linked, or links existing
changes. The new change copies the title, root cause, resolution plan, services, assets and
configuration items. The relation reads "resolved by change" on the problem and "fixes problem"
on the change. The change's status shows on the problem.

- **Decision:** SAME.
- **Source:** sdp-area-04 §Screens (associated changes: new change, attach, detach);
  sdp-area-05 §Behaviour (5b: problem attached to change); architecture §2.3
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Creating a change from PRB-7 opens the change form with PRB-7's CIs filled and links the
     two on save.
  2. The problem shows each linked change with its status, updated live.
  3. When the linked change is completed, the problem owner is notified and offered the
     "resolved" transition.

#### REQ-PRB-045 — Link releases

A problem can be linked to releases in two directions: releases that fix the problem and the
release that caused the problem. A new release can be created from the problem, pre-filled and
linked. Each direction uses one label pair on both records.

- **Decision:** SAME.
- **Source:** sdp-area-04 §Screens (releases caused by problem, release that initiated
  problem); sdp-area-06 §Behaviour (release side sections)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Linking a release as "caused the problem" shows "caused PRB-n" on the release, with history
     on both.
  2. A problem has at most one release that caused it; a second one asks to replace it.

#### REQ-PRB-046 — Related problems and merging duplicate problems

Problems can be linked as related to other problems. Duplicate problems can be merged with the
engine's merge (REQ-INC-088), which moves linked incidents, changes, releases, analysis notes
and tasks to the target, and can be undone (REQ-INC-150).

- **Decision:** NEW. ServiceDesk Plus has no problem-to-problem link or merge.
- **Source:** REQ-INC-084; REQ-INC-088; sdp-area-04 §Weak spots (duplicate-looking rows)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Merging PRB-4 into PRB-2 moves PRB-4's linked incidents to PRB-2, and each incident's
     history names both problems.
  2. The analysis text of PRB-4 is kept on PRB-2 as a note naming PRB-4, not overwritten.
  3. Undoing the merge moves the incidents back to PRB-4.

#### REQ-PRB-047 — Announcements from a problem

From a problem, a technician publishes an announcement to chosen audiences (REQ-INC-129), for
example "known issue with VPN on Windows laptops; use the web client". The problem lists its
announcements, and resolving the problem offers to end them.

- **Decision:** SAME.
- **Source:** sdp-area-04 §Screens (announcements tab), §Actions (notify: make an announcement);
  architecture §2.3 (announcements linked to problems); ADR-024
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Announcing from a problem creates a linked announcement shown on the problem.
  2. Resolving the problem offers to end each linked announcement.

---

## 9. Work on the problem: tasks, approvals, worklogs and messages

#### REQ-PRB-048 — Tasks on a problem with progress

Tasks on a problem work as on an incident (REQ-INC-072 to REQ-INC-076). The problem shows task
progress (done and total) on the record and as a list column, updated live. Adding and editing
problem tasks needs the "manage problem tasks" permission.

- **Decision:** SAME.
- **Source:** sdp-area-04 §Screens (list task progress ring, tasks tab), §Fields (add task
  dialog), §Behaviour (tasks 0/1); sdp-area-11 §Fields (adding/editing problem tasks)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Completing one of three tasks changes the progress to 1 of 3 in the list and on the record
     within one second.
  2. A technician without the task permission sees the add task action disabled with a reason.

#### REQ-PRB-049 — Approvals on a problem

A problem can ask for approval with the engine's approvals (REQ-INC-083), for example to
confirm a root cause, accept a known error without a fix, or approve closure. Approvals can
have several stages. Approval status is a list column and filter. Adding, changing and deleting
problem approvals need their own permissions. Approvals work with no mail configured.

- **Decision:** BETTER. ServiceDesk Plus shows only a mail error on the problem approvals tab.
- **Source:** sdp-area-04 §Screens (approvals tab: mail not configured), §Behaviour; sdp-area-11
  §Fields (problem approvals permissions); architecture §2.3 (problem approvals)
- **SDP weak spot fixed:** problem approvals cannot be used or even seen without a mail server.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. With no mail server, an approver approves a problem in the app and the problem shows the
     decision live.
  2. A list filter "approval pending" returns only problems with an open approval.
  3. A two-stage approval moves to stage two only after stage one is approved.

#### REQ-PRB-050 — Accept a known error without a fix

When a permanent fix is too costly or risky, the owner can propose to accept the known error:
the problem stays a known error with its workaround, and is closed with the closure code
"accepted, no fix". By default this needs approval from the problem manager role (Appendix A).
Accepted known errors stay in the known error database and are reviewed on a set date.

- **Decision:** NEW. ServiceDesk Plus has no way to record a decision not to fix.
- **Source:** sdp-area-04 §Config (closure codes such as postponed); architecture §2.3 (known
  error database)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Closing with "accepted, no fix" without an approved acceptance is refused under default
     settings.
  2. An accepted known error stays searchable in the known error database and is not retired.
  3. On its review date, the owner is notified and the problem appears in a "due for review"
     view.

#### REQ-PRB-051 — Worklogs, notes and reminders on problems

Worklogs (with costs, REQ-INC-067, REQ-INC-068), notes and personal reminders work on problems
as on incidents. A tenant setting can stop worklogs being added to closed problems. Worklog
time on a problem is reported separately from time on its linked incidents.

- **Decision:** SAME.
- **Source:** sdp-area-04 §Fields (add worklog, add reminder, add notes dialogs), §Screens
  (worklogs, reminders tabs); sdp-area-13 §Config (prevent worklog on closed records);
  sdp-area-11 §Fields (worklog permissions)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. With "no worklogs on closed problems" on, adding a worklog to a closed problem is refused
     with a reason.
  2. A report of problem time shows worklogs on the problem without the linked incidents'
     worklogs, and offers both.

#### REQ-PRB-052 — Send a message from a problem

From a problem, a technician sends an email or in-app message to chosen people: technicians,
groups, followers, the linked incidents' technicians or the linked incidents' requesters. The
message is kept on the problem's conversation timeline with its delivery status
(REQ-INC-059). Messages to requesters use a requester-safe template and are also added to each
linked incident's timeline.

- **Decision:** BETTER. ServiceDesk Plus has the same notify actions, but they fail silently
  without mail and leave no trace on the incidents.
- **Source:** sdp-area-04 §Actions (notify: send notification, notify incident technicians,
  notify incident requesters), §Screens (conversations tab); REQ-INC-060
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. "Message linked incident requesters" on a problem with 10 linked incidents sends one
     message per requester, in their language, and adds it to each incident's timeline.
  2. A requester linked through two incidents gets one message, not two.
  3. With no mail server, in-app and portal delivery still work and the email failure shows on
     the problem.

#### REQ-PRB-053 — Problem review

After a problem is resolved, a problem review can be held. It is a structured record on the
problem from a template: what happened, how the cause was found, what went well, what to
improve and follow-up actions. Follow-up actions become tasks, problems or changes in one step.
A review is required for problems from the major problem template by default (Appendix A),
and can be required by priority.

- **Decision:** NEW. ServiceDesk Plus has no problem review.
- **Source:** architecture §2.1 (post-incident review), §2.3; product-plan §7.3 (PIR and RCA
  writer)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A major problem cannot be closed until its review is completed, under default settings.
  2. A follow-up action turned into a change is linked to both the review and the problem.
  3. The review is printed with the problem and kept read-only after the problem is closed.

---

## 10. Resolution, closure and follow-up on incidents

#### REQ-PRB-054 — Problem closure rules

Admins set problem closure rules, separately from incident closure rules (REQ-INC-094):

- fields required before resolving and before closing, from all standard and custom problem
  fields, for example root cause, workaround, symptoms, impact details, resolution, category
  and technician;
- conditions required before closing: all tasks done; at least one change linked; all linked
  changes completed; at least one incident linked; all approvals approved; a review completed
  where required;
- whether closing asks for a closure code and closure comments.

The rules apply on every path: record, bulk, API and automation. A blocked user sees a short
list of what is missing. Open work is warned or blocked as in REQ-INC-095.

- **Decision:** BETTER. Same rules, applied on every path, and the default warns about open
  tasks.
- **Source:** sdp-area-14 §Screens (closure rules, problem tab: mandatory fields, mandatory
  conditions, closure confirmation); sdp-area-12 §Screens (closure rules tabs); sdp-area-04
  §Behaviour (closed with open task), §Weak spots
- **SDP weak spot fixed:** a problem can be closed while its tasks are still open.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. With "linked changes completed" on, closing a problem whose linked change is still in
     progress is refused, and the message names the change.
  2. With root cause required, the close prompt asks only for the root cause.
  3. Closing with one open task shows a warning that names the task under default settings.
  4. A bulk close applies the rules to each problem and reports the ones it skipped and why.

#### REQ-PRB-055 — Follow-up actions on linked incidents

When a problem is resolved or closed, the technician chooses what happens to its open linked
incidents, with tenant defaults (Appendix A):

- notify their technicians, their requesters, or both;
- copy the workaround, the resolution, or both into each incident (as a public note or as the
  incident's resolution);
- move each incident to a chosen status through its allowed transitions.

Before confirming, the technician sees the list of incidents that will change and can untick
some. The actions run in the background with progress shown live and a result per incident.
Each incident's own closure rules apply; an incident that cannot move is reported with the
reason and left as it was.

- **Decision:** BETTER. ServiceDesk Plus offers the same follow-ups only as fixed closure-rule
  settings, defaults to moving incidents straight to closed, and gives no preview or result.
- **Source:** sdp-area-14 §Screens (closure rules, problem tab: optional follow-ups after
  closing); REQ-INC-092; REQ-WI-009
- **SDP weak spot fixed:** incidents are closed without their requesters confirming, and
  failures are invisible.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Resolving a problem with 30 open linked incidents shows the list of 30 before confirming,
     and unticking 2 leaves those 2 unchanged.
  2. Under the default settings, each selected incident gets the resolution and moves to
     resolved, so its requester confirms or rejects the fix (REQ-INC-096).
  3. An incident whose closure rules block the move is listed with the reason, and the rest
     still move.
  4. Each incident's history says the change came from the problem, with its ID.

#### REQ-PRB-056 — Close with a closure code in one step

Closing a problem opens one dialog with the closure code, closure comments and any missing
required fields. Admins manage problem closure codes separately from incident closure codes
(Appendix A), with translations. The closure code is a list column, filter and report field.

- **Decision:** BETTER. ServiceDesk Plus asks "are you sure" and then opens a second dialog.
- **Source:** sdp-area-04 §Config (closure codes), §Fields (closure details dialog),
  §Actions (close), §Weak spots (two dialogs)
- **SDP weak spot fixed:** closing needs two dialogs in a row.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Closing a problem with all rules met needs one dialog and one confirm.
  2. Disabling a closure code hides it for new closures and keeps it on closed problems.
  3. A report can group closed problems by closure code.

#### REQ-PRB-057 — Reopen a problem

A closed or resolved problem has an explicit reopen action that needs permission and a reason.
Reopening keeps the analysis, solution, links and known error state, clears the resolved and
closed times, and notifies the owner and investigators. It does not reopen linked incidents.

- **Decision:** BETTER. ServiceDesk Plus has no reopen button; users must edit the status.
- **Source:** sdp-area-04 §Behaviour (reopen via edit), §Weak spots (no reopen button);
  REQ-INC-097
- **SDP weak spot fixed:** reopening is hidden in the edit form.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Reopening a closed problem without a reason is refused.
  2. After reopening, the analysis and solution text are unchanged and history records the
     reopen.
  3. Incidents resolved by the problem's follow-up stay as they are.

#### REQ-PRB-058 — Cancel a problem

A problem that turns out not to be a problem (for example a one-off, or a duplicate) is canceled
with a reason. Canceling offers to unlink its incidents or move them to another problem.

- **Decision:** SAME.
- **Source:** sdp-area-04 §Fields (status: canceled), §Config (closure code: canceled)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Canceling without a reason is refused.
  2. Choosing "move incidents to PRB-9" relinks every incident and records it on all records.

#### REQ-PRB-059 — Editing closed problems is controlled

Closed problems are read-only except for notes, links to knowledge articles and the known
error review date, unless the user has the "edit closed problems" permission (as REQ-INC-101).

- **Decision:** SAME.
- **Source:** sdp-area-04 §Behaviour (edit form editable at any time); sdp-area-11 §Fields
  (editing closed records)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A technician without the permission cannot change the root cause of a closed problem; the
     API returns 403.
  2. Adding a note to a closed problem is allowed and recorded.

---

## 11. Lists, views, search and the record page

#### REQ-PRB-060 — Problem list and columns

The problems list works as the incident list (REQ-INC-104 to REQ-INC-117): columns, filters,
sorting, card list and board, split view and quick peek, in-list editing, export and charts.
Problem-specific columns and filters are: task progress, known error, linked incident count,
open linked incident count, linked changes, root cause category, target date, approval status,
closure code and workflow.

- **Decision:** SAME.
- **Source:** sdp-area-04 §Screens (problem list, custom view builder column choices)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A filter "known error is yes and open linked incidents more than 5" returns the matching
     problems.
  2. The linked incident count column changes live when an incident is linked.
  3. Every problem-specific column above can be exported.

#### REQ-PRB-061 — Built-in problem views

A new tenant has built-in problem views (Appendix A), for example all open problems, my open
problems, my group's problems, unassigned, awaiting fix, on hold, known errors, accepted known
errors due for review, resolved, closed and trash. Users can star views as favourites and build
their own (REQ-INC-106, REQ-INC-107).

- **Decision:** SAME.
- **Source:** sdp-area-04 §Screens (public views, favourites, trashed problems)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. "Unassigned" lists exactly the open problems with no technician.
  2. A problem moves in and out of built-in views live as its status changes.

#### REQ-PRB-062 — Search across problems and known errors

Global search covers problems by ID, title, description, root cause, symptoms and workaround,
and labels known errors in the results. A search for a display ID opens the problem.

- **Decision:** SAME.
- **Source:** sdp-area-01 §Screens (global search scopes include problems)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Searching for a phrase that appears only in a problem's root cause finds that problem.
  2. Searching "PRB-12" opens PRB-12.
  3. A user without problem access gets no problem results.

#### REQ-PRB-063 — Bulk actions on problems

Bulk assign, pick up, transition, link incidents, edit fields, delete to trash and export work
on problems as on incidents (REQ-INC-119 to REQ-INC-121), with the problem closure rules
applied to each record.

- **Decision:** SAME.
- **Source:** sdp-area-04 §Screens (list toolbar: delete, pick up, assign, export)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Bulk delete of 10 problems moves all 10 to trash and lists them there.
  2. A bulk transition skips problems where it is not allowed and lists them with the reason.

#### REQ-PRB-064 — The problem record page

The problem page shows a header with ID, title, type badge, status, priority, known error
marker and target date, and a fixed set of tabs in a fixed order: details, analysis, solution,
tasks, linked records, approvals, worklogs, conversation and notes, history (REQ-WI-011).
A side panel shows owner, template, life cycle, task progress, approval status, attachments and
counts of linked incidents, changes and releases. Previous and next move through the current
list (REQ-INC-125).

- **Decision:** BETTER. ServiceDesk Plus hides tabs in an overflow menu that reshuffles each
  time it is used.
- **Source:** sdp-area-04 §Screens (detail page header, tabs, overflow, right panel), §Weak spots
  (overflow reshuffles)
- **SDP weak spot fixed:** clicking the same overflow position twice opens different tabs.
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. The tab order is the same on every problem, whatever tab was used last.
  2. The linked incident count in the side panel changes live when an incident is linked
     elsewhere.
  3. On a narrow screen, tabs that do not fit go into a menu that keeps them in the same order.

#### REQ-PRB-065 — Print a problem

A problem can be printed or saved as PDF with its details, analysis, solution, linked records,
tasks and, if chosen, its review and history, in the user's language and text direction.

- **Decision:** SAME.
- **Source:** sdp-area-04 §Actions (print); REQ-INC-126
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. The PDF of a problem includes its root cause, workaround and list of linked incidents.
  2. Private notes are left out unless the user chooses to include them and may see them.
  3. An Arabic PDF prints right-to-left.

---

## 12. Proactive problem detection and AI

All AI on problems runs through the AI gateway (architecture §12), on every deployment, with
the user's permissions, and records whether each suggestion was accepted, edited or rejected
(as section 20 of file 01). Administration is in file 10. Model access follows D-049, pending a
pricing decision.

#### REQ-PRB-066 — Incident cluster analysis

AI groups similar recent incidents into clusters by their text, category, services and
configuration items. Each cluster shows its size, its trend, the common terms and items that
explain why the incidents were grouped, and whether they are already linked to a problem. From
a cluster a technician can create a problem from its incidents (REQ-PRB-012), link them to an
existing problem or known error, or dismiss the cluster with a reason. Dismissed clusters are
not suggested again unless they grow by a set amount.

- **Decision:** BETTER. ServiceDesk Plus offers cluster analysis in its cloud edition only and
  does not explain why incidents were grouped.
- **Source:** sdp-area-10 §Screens (cluster analysis, problem suggestion), §Configuration
  options; sdp-area-01 §Screens (problem prediction: run, view predictions); architecture §2.3
  (problem prediction by clustering), §2.10; product-plan §5, §7.2 (problem clustering)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Twenty test incidents about the same VPN error, spread over five days, form one cluster
     that lists the shared terms and CI.
  2. Creating a problem from the cluster links every incident in it.
  3. A dismissed cluster is not shown again unless it grows by the set amount (Appendix A).
  4. The feature passes the same tests with the on-prem local model profile.

#### REQ-PRB-067 — Admin-defined cluster analyses

Admins define named cluster analyses: which incidents to include (conditions), which fields to
analyse, how often to run and what to do with a finding (notify a group, create a draft problem
for review, or both). Each run is logged with what it found. The master switch for AI-based
analysis is in AI administration (file 10).

- **Decision:** SAME.
- **Source:** sdp-area-10 §Fields (new cluster analysis form), §Automation (actions on a
  finding), §Configuration options (master switch and per-analysis switch)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. An analysis limited to the network category never includes incidents from other
     categories.
  2. A finding with action "notify network group" notifies that group once per new cluster.
  3. Each run's log shows the time, the number of incidents analysed and the clusters found.

#### REQ-PRB-068 — Repeat incident rules without AI

Admins set simple repeat rules that work without any AI model: for example "5 or more incidents
on the same configuration item in 7 days" or "10 or more incidents in the same category and
site in 24 hours". When a rule matches, the group is notified with the incidents listed and can
create a problem from them in one step.

- **Decision:** NEW. ServiceDesk Plus relies only on AI for proactive detection.
- **Source:** product-plan §5 (incident clustering on all deployments); D-049
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. With the default rule (Appendix A), a fifth incident on the same CI within 7 days notifies
     the CI's support group.
  2. The rule fires once per set of incidents, not once per new incident, until the set is
     handled.
  3. The rule works with every AI feature switched off.

#### REQ-PRB-069 — AI help on a problem

AI helps the problem owner:

- suggest the owner and group, from past problems (as the vendor's problem technician
  prediction);
- summarise the symptoms of the linked incidents;
- draft a root cause hypothesis from the linked incidents, the evidence panel (REQ-PRB-032) and
  the CMDB, citing each source it used;
- suggest a workaround from the linked incidents' resolutions and knowledge articles;
- draft the problem review (REQ-PRB-053).

Every draft is shown as a suggestion that a person edits and saves.

- **Decision:** BETTER. ServiceDesk Plus offers only technician prediction for problems.
- **Source:** sdp-area-10 §Screens (predictive features: problem technician prediction);
  architecture §2.3 (technician prediction, AI root-cause draft), §2.10 (root-cause drafts);
  product-plan §5, §7.2 (RCA generation), §7.3 (PIR and RCA writer)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A root cause draft lists the incidents, changes and CIs it was based on, each as a link.
  2. A draft is never saved into the root cause field without a person accepting it, and the
     acceptance is recorded with source "AI".
  3. The owner suggestion shows a confidence and can be rejected.

---

## 13. Permissions

#### REQ-PRB-070 — Problem permissions

Roles control problems by action and scope (REQ-WI-015): view, add, edit, delete, and finer
permissions for:

- adding and changing tasks, and deleting tasks;
- adding and changing approvals, and deleting approvals;
- changing analysis, and changing the solution;
- marking and unmarking known errors;
- publishing workarounds to technicians and to the portal;
- closing, reopening, canceling and editing closed problems;
- editing and deleting other people's notes, and worklog actions.

Scopes are all, site, group and assigned to me, as for incidents. A new tenant gets a problem
manager role with all problem permissions (Appendix A).

- **Decision:** SAME.
- **Source:** sdp-area-11 §Fields (role permission matrix, advanced permissions for problems,
  granular scope); architecture §11.2
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A technician with "group" scope sees only problems of their groups, and the API refuses
     others with 404.
  2. A technician without "publish to portal" sees that action disabled with a reason.
  3. The problem manager role exists in a new tenant and can be copied and changed.

#### REQ-PRB-071 — Incident technicians see what they need of a problem

A technician working a linked incident can see the linked problem's title, status, known error
marker, workaround and target date, even without access to the problems module. They cannot see
the rest of the problem unless their role allows it.

- **Decision:** NEW. In ServiceDesk Plus an incident technician without problem access cannot
  see the workaround that would help them.
- **Source:** sdp-area-11 §Fields (module permissions); architecture §11.2 (field-level
  visibility); REQ-WI-016
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A technician without problem access sees the workaround of the problem linked to their
     incident.
  2. The same technician gets 403 when opening the problem record itself.
  3. The root cause is not shown to them unless the tenant allows it.

---

## 14. Notifications, reports and the requester's side

#### REQ-PRB-072 — Problem notifications with sensible defaults

These problem events notify the right people, through the notification engine (file 03):

- created and assigned: to the group and the new owner;
- left unassigned for a set time: to the group;
- a public note: to the owner, investigators and followers;
- status changes, known error marked or removed;
- incident linked (with a daily digest option, to avoid one message per incident);
- target date near and missed;
- a linked change completed: to the owner;
- resolved and closed: to the owner, investigators and, through follow-up actions, the linked
  incidents' technicians and requesters (REQ-PRB-055);
- approval needed, task assignment and mentions.

Each event can be switched on or off per tenant with chosen recipients and channels. Defaults
are in Appendix A. Templates ship in English and Arabic, and Urdu at V1 (D-048).

- **Decision:** BETTER. Same event coverage as the vendor's problem notification rules, with
  defaults that work without set-up and a digest for busy problems.
- **Source:** sdp-area-12 (12b) §Screens (notification rules: problem tab); sdp-area-04
  §Automation (problem-level notifications); REQ-INC-130; D-048
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. In a new tenant, assigning a problem notifies the new owner with no admin set-up.
  2. With the digest on, linking 30 incidents in a day sends the owner one digest, not 30
     messages.
  3. Nobody is notified about a change they made themselves, unless they opted in.

#### REQ-PRB-073 — Problem reports and metrics

Every problem field is reportable (file 09). Standard problem reports cover counts by category,
status, priority, impact, urgency, technician, root cause category and closure code; open and
closed problems over time; linked incident counts; cost and time spent; approver and approval
status. Problem metrics include:

- time to find the root cause, time to known error and time to resolve;
- age of open problems and of accepted known errors;
- incidents linked per problem, and incidents per week before and after the fix;
- share of incidents resolved with a known error workaround.

- **Decision:** BETTER. ServiceDesk Plus reports problem counts and cost but not how well
  problem management reduces incidents.
- **Source:** sdp-area-09 §Screens (problem reports, problem widgets, canned problem
  dashboard), §Weak spots (drill-down only for requests); architecture §2.3 (problem widgets on
  dashboards); product-plan §7.4
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. "Time to root cause" for a problem equals the time from creation to its first "root cause
     found" transition.
  2. The before-and-after report for a resolved problem shows linked incidents per week for
     the four weeks either side of resolution.
  3. A problem chart drills down to the list of problems behind each bar.

#### REQ-PRB-074 — Problem counters and dashboard widgets

The home summary shows personal problem counters (for example my open problems, unassigned
problems in my groups, target dates missed), and dashboards offer problem widgets and a
ready-made problem dashboard (file 09). Counters and widgets update live.

- **Decision:** SAME.
- **Source:** sdp-area-09 §Screens (my summary: problems pending, unassigned; canned problem
  dashboard); sdp-area-01 §Screens (problems counters, widget modules); REQ-INC-128
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Picking up an unassigned problem lowers the "unassigned problems" counter for every
     member of the group within one second.
  2. A new tenant has a problem dashboard with no set-up.

#### REQ-PRB-075 — What requesters see

Requesters never see problem records, analysis or internal notes. On their own incident in the
portal they see, in plain language:

- that the issue is known and being worked on, when the incident is linked to an open problem;
- the requester-facing workaround, when one is published (REQ-PRB-040);
- the outcome, when the problem's follow-up resolves their incident (REQ-PRB-055).

Requesters can follow a published known issue to be told when it is fixed.

- **Decision:** NEW. ServiceDesk Plus tells requesters only through manual notifications.
- **Source:** sdp-area-04 §Actions (notify incident requesters); sdp-area-08 §Limits (portal
  view inferred from publish settings); REQ-INC-147
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A requester's portal API response for an incident never contains the linked problem's ID,
     root cause or notes.
  2. Linking the requester's incident to a problem shows "known issue, being worked on" on the
     incident in the portal within one second.
  3. A requester who follows a known issue is notified once when the problem is resolved.

#### REQ-PRB-076 — Live updates on problem screens

Problem screens update live with no refresh (REQ-WI-005). Beyond the engine's behaviour, this
covers changes that start on other records:

- linked incident counts and the impact figures when incidents are linked, resolved or
  reopened;
- the status of linked changes and releases;
- the known error marker on linked incidents;
- the progress of follow-up actions (REQ-PRB-055);
- new clusters and repeat-rule matches on the problem detection screen.

- **Decision:** BETTER. ServiceDesk Plus problem lists and counters do not update on their own.
- **Source:** architecture §8; sdp-area-02a §Config (refresh frequency); REQ-WI-005
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Resolving a linked incident in one browser lowers the open linked incident count on the
     problem in another within one second.
  2. Marking a known error adds the marker to an open incident page that shows the link,
     without a refresh.
  3. Follow-up progress shows each incident's result as it is processed.

---

## 15. The monitoring boundary and other channels

#### REQ-PRB-077 — No alert correlation for problem detection

Proactive problem detection works only on incidents in SupportX (REQ-PRB-066, REQ-PRB-068). It
never reads raw monitoring alerts, polls devices or correlates events. MonetX problems arrive
as incidents (REQ-INC-030) and can then be clustered and linked like any other incident.

- **Decision:** SKIP. Alert correlation is MonetX's job (ADR-017, D-001). product-plan's
  correlation engine is out of scope; it is replaced by incident clustering and repeat rules.
- **Source:** ADR-017; D-001; REQ-INC-146; product-plan §5 (problem), §6
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. The cluster analysis input contains only incident records; an architecture test checks
     it has no dependency on any alert store.
  2. Twenty MonetX-sourced incidents are clustered by the same rules as any other incidents.

#### REQ-PRB-078 — Health and history of affected items from MonetX

A problem linked to configuration items that MonetX monitors shows their current health and
their recent MonetX problem history, read from the MonetX API (read-only, D-001), with a link
to open them in MonetX. This feeds the evidence panel (REQ-PRB-032).

- **Decision:** NEW.
- **Source:** D-001; ADR-017; REQ-INC-145; product-plan §5 (AI RCA using metrics)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A problem linked to a monitored CI shows its MonetX health and last 30 days of MonetX
     problems.
  2. If MonetX cannot be reached, the panel says so and the rest of the page works.
  3. SupportX makes no write call to MonetX and stores no performance data.

#### REQ-PRB-079 — Problem investigation agent

An agent from the agent library investigates a new problem: it gathers the evidence, drafts
symptoms and a root cause hypothesis, proposes a workaround and next tasks, and posts them as a
private note for the owner. It acts only in suggest mode on problems.

- **Decision:** NEW. ServiceDesk Plus agents are cloud-only and have no problem agent.
- **Source:** product-plan §7.3 (PIR and RCA writer); architecture §2.10 (agents)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. The agent's note cites every record it used.
  2. The agent changes no field on the problem; it only posts its note and suggestions.
  3. Every agent run is recorded with source "AI agent".

#### REQ-PRB-080 — Problems on the mobile app

Technicians handle problems in the mobile app: lists and views, the record, notes, analysis and
solution reading, transitions, assignment, worklogs, tasks and approvals, with push
notifications.

- **Decision:** SAME.
- **Source:** architecture §2.15 (mobile apps), §9.1; REQ-INC-149; D-065
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A push notification for a problem assignment opens the problem in the app.
  2. Transitions in the app follow the same rules and prompts as the console.

#### REQ-PRB-081 — Import problems

Admins import problems from a CSV or spreadsheet file, with field mapping, a dry run and a
per-row result. Imported problems keep their original dates and get new display IDs, with the
old ID kept in a field. The migration tool from ServiceDesk Plus (architecture §18) also
imports problems with their analysis, solution and links.

- **Decision:** SAME.
- **Source:** sdp-area-14 §Screens (data administration: import data includes problems);
  architecture §18
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A dry run of 500 rows reports errors per row and creates nothing.
  2. An imported problem keeps its original created date and records source "import".
  3. Importing the same file twice does not create duplicates when an external ID is mapped.

---

## Appendix A — Proposed defaults

These are the defaults a new tenant gets. They are seed data, not fixed behaviour: a tenant
admin can change every one of them (D-041). The requirements above refer to this appendix.

**Priority matrix** (REQ-PRB-004): a separate problem matrix that starts as a copy of the
incident matrix in file 01 Appendix A. The default priority when impact and urgency are both
unknown is P3, marked as defaulted.

**Target date policy** (REQ-PRB-008), in business days from creation: P1 5, P2 10, P3 20,
P4 40. Response and resolution SLAs are off for problems.

**Problem types** (REQ-PRB-005): reactive (from incidents) · proactive (found before
incidents occur).

**Root cause categories** (REQ-PRB-005): software defect · configuration error · hardware
failure · capacity or performance · third-party or supplier · process or procedure · human
error · security · unknown.

**Templates** (REQ-PRB-017): standard problem (default, standard life cycle); major problem
(analysis and solution sections on the create form, guided life cycle, review required).

**Statuses and categories** (REQ-PRB-023):

| Status | Category | Reason or fields needed to enter |
|---|---|---|
| new | open | no |
| assigned | open | no |
| investigating | open | no |
| root cause found | open | root cause |
| awaiting fix | open | no (usually a linked change) |
| on hold | paused | yes |
| resolved | resolved | resolution |
| closed | closed | closure code |
| canceled | canceled | yes (cancel reason) |
| merged (system only) | closed | set by merge |

**Allowed transitions:**

| From | To |
|---|---|
| new | assigned, investigating, canceled |
| assigned | new (unassign), investigating, on hold, canceled |
| investigating | root cause found, on hold, resolved, canceled |
| root cause found | awaiting fix, investigating (cause rejected), resolved, closed (accepted, no fix) |
| awaiting fix | resolved, investigating (fix failed), on hold |
| on hold | the status it was paused from |
| resolved | closed, investigating (reopen) |
| closed | investigating (reopen, permission and reason) |
| canceled | the previous status (undo cancel, permission) |

**Automatic moves:** new → assigned when an owner is set; investigating → awaiting fix
offered when a linked change is created; awaiting fix → resolved offered when all linked
changes are completed (REQ-PRB-044).

**Guided life cycle for major problems** (REQ-PRB-025): facts recorded → why-analysis →
cause confirmed (root cause required) → fix planned (linked change or accepted known error) →
fix verified → review → closed.

**Known errors** (REQ-PRB-036, REQ-PRB-042, REQ-PRB-050): marking needs a workaround or a root
cause; on resolution with a permanent fix, portal known issues are withdrawn and technician
workaround articles are flagged for review; accepting a known error without a fix needs
approval from the problem manager role and sets a review date 90 days ahead.

**Closure codes** (REQ-PRB-056): fixed permanently · resolved by workaround only · accepted,
no fix · could not reproduce · duplicate · not a problem · canceled.

**Closure rules** (REQ-PRB-054): resolving needs a resolution; closing needs a closure code and
a root cause (or the code "could not reproduce", "duplicate", "not a problem" or "canceled");
open tasks and checklists give a warning and need confirmation; pending approvals block;
linked changes not completed give a warning; a completed review is required for the major
problem template.

**Follow-up actions on linked incidents** (REQ-PRB-055): on resolving the problem, copy the
resolution into each open linked incident as its resolution, move it to resolved (so the
requester confirms), and notify its technician and requester. On closing a problem resolved by
workaround only, copy the workaround as a public note and leave the status unchanged.

**Evidence window** (REQ-PRB-032): changes and releases in the 72 hours before the first linked
incident.

**Cluster analysis** (REQ-PRB-066, REQ-PRB-067): off until AI is enabled for the tenant (file
10); when on, runs daily over the last 14 days of incidents, minimum cluster size 5; a
dismissed cluster is suggested again only if it grows by 50 percent.

**Repeat incident rules** (REQ-PRB-068), on by default: 5 or more incidents on the same
configuration item in 7 days; 10 or more incidents with the same category and site in 24
hours. Each notifies the support group of the item or category.

**Built-in views** (REQ-PRB-061): all open problems · my open problems · my groups' problems ·
unassigned · awaiting fix · on hold · known errors · accepted known errors due for review ·
resolved · closed · trash.

**Roles** (REQ-PRB-070): a problem manager role with every problem permission and "all" scope.

**Notifications on by default** (REQ-PRB-072): assigned to the new owner; unassigned for 4
business hours to the group; public note to the owner and investigators; incident linked to
the owner as a daily digest; target date missed to the owner and group head; linked change
completed to the owner; approval needed to the approver; resolved and closed follow-ups to the
linked incidents' technicians and requesters; mention to the person mentioned.

**Other defaults:**

- trash retention: 30 days (REQ-WI-020);
- copy limit: 20 (REQ-PRB-015);
- worklogs on closed problems: allowed (REQ-PRB-051);
- bulk incident link and create-from-many limit: 1,000 (REQ-PRB-012).

---

## Open questions for the product owner

1. **Default follow-up on linked incidents.** We propose moving linked incidents to resolved
   (the requester confirms) rather than closed, as ServiceDesk Plus does. Agree?
   (REQ-PRB-055)
2. **One problem per incident.** We propose that an incident is caused by at most one problem;
   further problems can only be "related". Agree? This also tightens REQ-INC-087 in file 01.
   (REQ-PRB-043)
3. **Target dates instead of SLAs.** Problems get target dates by priority, and response and
   resolution SLAs are off by default. Should a tenant be able to switch full SLAs on for
   problems? (REQ-PRB-008)
4. **Problem reviews.** Required by default only for the major problem template. Should they
   also be required for P1 and P2 problems? (REQ-PRB-053)
5. **Repeat incident rules without AI.** Problems are Professional, so the non-AI repeat rules
   are Professional too. Should Essentials tenants get the repeat-rule alerts (without
   problem records) as an upsell signal? (REQ-PRB-068)
6. **Cluster analysis on air-gapped installs.** Clustering needs embeddings from the local
   model. Is V1 on air-gapped acceptable, given D-049 is pending, or should air-gapped get it
   later? (REQ-PRB-066)
7. **Workaround visibility for incident technicians.** We propose that technicians without
   problem access see the workaround but not the root cause of a linked problem. Agree, or
   should the root cause be visible too? (REQ-PRB-071)
