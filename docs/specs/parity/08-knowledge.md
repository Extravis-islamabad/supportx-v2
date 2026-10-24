# 08 — Knowledge base

Parity requirements for the knowledge base (architecture.md §2.15, `knowledge` module in §6.1):
articles, topics, authoring, versions, approval and publishing, review and expiry, visibility,
languages, search, AI answers, use on records, feedback, analytics and the knowledge part of the
requester portal. Rules, ID scheme and field meanings: [README.md](README.md).

**Status:** Draft v0.1, 2026-10-24. Written in Phase 2 against the decisions D-039 to D-050.
**Owner:** Haider (Product Owner).

## Scope of this file

- **REQ-KB-*** are knowledge requirements. Knowledge articles are **not** work items: they do
  not run on the work item engine and have no SLA, assignment or requester. They do reuse the
  platform services the engine uses: the rich-text editor and sanitiser (REQ-INC-064), safe
  attachments (REQ-INC-079), field history (REQ-WI-003), live updates (REQ-WI-005), safe
  concurrent editing (REQ-WI-007), server-decided actions (REQ-WI-010), fixed tabs
  (REQ-WI-011), labels and right-to-left (REQ-WI-013), one date formatter (REQ-WI-014), trash
  (REQ-WI-020) and accessibility (REQ-WI-023). This file does not restate them; it says only
  what knowledge adds.
- **Knowledge is in Essentials and in Stage 1** (product-plan §9, architecture §17). Core
  authoring, approval, publishing, search, suggestions and the portal knowledge base are MVP.
  Semantic search and AI answers depend on the AI gateway, which is Stage 2, so they are V1.
- **What this file owns, and what other files own:**
  - suggestions while logging an incident (REQ-INC-021), searching knowledge from the
    resolution (REQ-INC-090) and saving a resolution as an article (REQ-INC-091) are specified
    in file 01; the knowledge side of them is here (REQ-KB-016, REQ-KB-062 to REQ-KB-064);
  - workarounds, known errors and their publication are specified in file 04 (REQ-PRB-038 to
    REQ-PRB-042); this file says how workaround articles and portal known issues behave as
    knowledge content (REQ-KB-039 to REQ-KB-042);
  - the portal shell, home page and catalog (file 02); the notification engine and templates,
    business rules and workflows (file 03); reports and dashboards (file 09); AI gateway,
    model choice, the chatbot and agents (file 10); roles, requester groups, sites,
    departments and the import framework (file 11); connectors to Confluence and SharePoint
    (file 12).
- **Monitoring is out of scope** (ADR-017, D-001). Nothing in this file reads monitoring data.

## Words used in this file

| Word | Meaning |
|---|---|
| Article | A knowledge record: a title and a rich-text body with its fields, versions and translations. |
| Topic | A node in the knowledge hierarchy. Every article sits in one topic. |
| Article type | The kind of article (how-to, troubleshooting, FAQ, workaround ...). The type decides the template and some behaviour (REQ-KB-008). |
| Version | A saved, numbered state of an article's content. Readers see the published version (REQ-KB-020). |
| Translation | The same article in another language, with its own status and versions (REQ-KB-049). |
| Audience | Who may read an article: technician groups, and optionally requesters by group, site or department (REQ-KB-044, REQ-KB-045). |
| Published | Approved and visible to its audience. "Approved" and "published" are one step here (REQ-KB-026). |
| Owner | The person responsible for keeping an article correct; gets review tasks and feedback (REQ-KB-033). |
| Workaround article | An article created from a problem's workaround and linked to that problem (REQ-KB-039). |
| Known issue | A requester-facing article about a known error, shown in the portal (REQ-KB-041). |
| Deflection | A requester who found an answer in knowledge and did not raise a request (REQ-KB-074). |
| KCS | Knowledge-centred service: capturing and improving knowledge while resolving records (REQ-KB-066). |

## Requirement summary

<!-- summary:start -->
**Counts by decision and priority**

| Decision | MVP | V1 | LATER | Total |
|---|---|---|---|---|
| SAME | 12 | 15 | 0 | 27 |
| BETTER | 23 | 14 | 0 | 37 |
| NEW | 3 | 21 | 4 | 28 |
| SKIP | 0 | 0 | 1 | 1 |
| **Total** | **38** | **50** | **5** | **93** |

Edition (lowest edition that includes it): Essentials 85, Professional 8, Enterprise 0. By prefix: REQ-KB 93.

| ID | Title | Decision | Priority | Edition |
|---|---|---|---|---|
| [REQ-KB-001](#req-kb-001--knowledge-article-record-and-core-fields) | Knowledge article record and core fields | SAME | MVP | Essentials |
| [REQ-KB-002](#req-kb-002--article-ids-with-a-prefix) | Article IDs with a prefix | SAME | MVP | Essentials |
| [REQ-KB-003](#req-kb-003--topic-tree) | Topic tree | BETTER | MVP | Essentials |
| [REQ-KB-004](#req-kb-004--managing-topics) | Managing topics | BETTER | MVP | Essentials |
| [REQ-KB-005](#req-kb-005--keywords-that-help-search) | Keywords that help search | BETTER | MVP | Essentials |
| [REQ-KB-006](#req-kb-006--rich-text-article-body) | Rich-text article body | BETTER | MVP | Essentials |
| [REQ-KB-007](#req-kb-007--attachments-and-images-on-articles) | Attachments and images on articles | SAME | MVP | Essentials |
| [REQ-KB-008](#req-kb-008--article-types) | Article types | NEW | MVP | Essentials |
| [REQ-KB-009](#req-kb-009--custom-fields-on-articles) | Custom fields on articles | SAME | V1 | Essentials |
| [REQ-KB-010](#req-kb-010--related-articles) | Related articles | SAME | V1 | Essentials |
| [REQ-KB-011](#req-kb-011--articles-about-services-and-configuration-items) | Articles about services and configuration items | NEW | V1 | Professional |
| [REQ-KB-012](#req-kb-012--create-and-edit-articles) | Create and edit articles | BETTER | MVP | Essentials |
| [REQ-KB-013](#req-kb-013--drafts-are-saved-automatically) | Drafts are saved automatically | NEW | MVP | Essentials |
| [REQ-KB-014](#req-kb-014--article-templates) | Article templates | SAME | V1 | Essentials |
| [REQ-KB-015](#req-kb-015--two-people-editing-the-same-article) | Two people editing the same article | BETTER | V1 | Essentials |
| [REQ-KB-016](#req-kb-016--article-from-a-resolved-record) | Article from a resolved record | SAME | V1 | Essentials |
| [REQ-KB-017](#req-kb-017--duplicate-article-warning) | Duplicate article warning | NEW | V1 | Essentials |
| [REQ-KB-018](#req-kb-018--quality-checks-before-review) | Quality checks before review | NEW | V1 | Essentials |
| [REQ-KB-019](#req-kb-019--ai-drafting-help-for-articles) | AI drafting help for articles | SAME | V1 | Essentials |
| [REQ-KB-020](#req-kb-020--every-published-change-is-a-version) | Every published change is a version | BETTER | MVP | Essentials |
| [REQ-KB-021](#req-kb-021--edit-a-published-article-without-taking-it-offline) | Edit a published article without taking it offline | BETTER | MVP | Essentials |
| [REQ-KB-022](#req-kb-022--compare-versions) | Compare versions | BETTER | V1 | Essentials |
| [REQ-KB-023](#req-kb-023--restore-an-earlier-version) | Restore an earlier version | SAME | V1 | Essentials |
| [REQ-KB-024](#req-kb-024--minor-edits) | Minor edits | NEW | V1 | Essentials |
| [REQ-KB-025](#req-kb-025--no-switch-to-turn-versioning-off) | No switch to turn versioning off | SKIP | LATER | Essentials |
| [REQ-KB-026](#req-kb-026--article-statuses-with-a-fixed-meaning) | Article statuses with a fixed meaning | BETTER | MVP | Essentials |
| [REQ-KB-027](#req-kb-027--submit-approve-and-reject) | Submit, approve and reject | BETTER | MVP | Essentials |
| [REQ-KB-028](#req-kb-028--approving-your-own-article) | Approving your own article | SAME | MVP | Essentials |
| [REQ-KB-029](#req-kb-029--multi-step-approval) | Multi-step approval | BETTER | V1 | Professional |
| [REQ-KB-030](#req-kb-030--scheduled-publishing) | Scheduled publishing | NEW | V1 | Essentials |
| [REQ-KB-031](#req-kb-031--withdraw-an-article) | Withdraw an article | SAME | MVP | Essentials |
| [REQ-KB-032](#req-kb-032--bulk-actions-on-articles) | Bulk actions on articles | SAME | V1 | Essentials |
| [REQ-KB-033](#req-kb-033--article-and-topic-owners) | Article and topic owners | BETTER | MVP | Essentials |
| [REQ-KB-034](#req-kb-034--review-dates-and-review-without-a-new-version) | Review dates and review without a new version | BETTER | MVP | Essentials |
| [REQ-KB-035](#req-kb-035--expiry) | Expiry | SAME | MVP | Essentials |
| [REQ-KB-036](#req-kb-036--review-and-expiry-reminders) | Review and expiry reminders | BETTER | V1 | Essentials |
| [REQ-KB-037](#req-kb-037--content-health-view) | Content health view | NEW | V1 | Essentials |
| [REQ-KB-038](#req-kb-038--broken-link-checks) | Broken link checks | NEW | V1 | Essentials |
| [REQ-KB-039](#req-kb-039--workaround-articles-follow-their-problem) | Workaround articles follow their problem | BETTER | V1 | Professional |
| [REQ-KB-040](#req-kb-040--review-flag-when-the-problem-changes) | Review flag when the problem changes | NEW | V1 | Professional |
| [REQ-KB-041](#req-kb-041--known-issues-in-the-portal) | Known issues in the portal | BETTER | V1 | Professional |
| [REQ-KB-042](#req-kb-042--known-errors-alongside-articles-in-suggestions) | Known errors alongside articles in suggestions | BETTER | V1 | Professional |
| [REQ-KB-043](#req-kb-043--knowledge-permissions) | Knowledge permissions | SAME | MVP | Essentials |
| [REQ-KB-044](#req-kb-044--technician-visibility-by-group-set-on-topics-and-articles) | Technician visibility by group, set on topics and articles | BETTER | MVP | Essentials |
| [REQ-KB-045](#req-kb-045--requester-audiences) | Requester audiences | BETTER | MVP | Essentials |
| [REQ-KB-046](#req-kb-046--technician-only-sections-in-a-requester-article) | Technician-only sections in a requester article | NEW | V1 | Essentials |
| [REQ-KB-047](#req-kb-047--preview-as-a-reader) | Preview as a reader | BETTER | V1 | Essentials |
| [REQ-KB-048](#req-kb-048--visibility-is-enforced-everywhere) | Visibility is enforced everywhere | BETTER | MVP | Essentials |
| [REQ-KB-049](#req-kb-049--translations-of-an-article) | Translations of an article | NEW | MVP | Essentials |
| [REQ-KB-050](#req-kb-050--translations-that-fall-behind-are-flagged) | Translations that fall behind are flagged | NEW | V1 | Essentials |
| [REQ-KB-051](#req-kb-051--ai-translation-drafts) | AI translation drafts | NEW | V1 | Essentials |
| [REQ-KB-052](#req-kb-052--right-to-left-and-arabic-text-in-articles-and-search) | Right-to-left and Arabic text in articles and search | BETTER | MVP | Essentials |
| [REQ-KB-053](#req-kb-053--full-text-knowledge-search) | Full-text knowledge search | BETTER | MVP | Essentials |
| [REQ-KB-054](#req-kb-054--synonyms) | Synonyms | NEW | V1 | Essentials |
| [REQ-KB-055](#req-kb-055--search-inside-attachments) | Search inside attachments | NEW | V1 | Essentials |
| [REQ-KB-056](#req-kb-056--ranking-and-promoted-results) | Ranking and promoted results | NEW | V1 | Essentials |
| [REQ-KB-057](#req-kb-057--semantic-search) | Semantic search | BETTER | V1 | Essentials |
| [REQ-KB-058](#req-kb-058--ai-answers-with-citations) | AI answers with citations | BETTER | V1 | Essentials |
| [REQ-KB-059](#req-kb-059--knowledge-summary-for-technicians-on-a-record) | Knowledge summary for technicians on a record | SAME | V1 | Essentials |
| [REQ-KB-060](#req-kb-060--search-analytics) | Search analytics | NEW | V1 | Essentials |
| [REQ-KB-061](#req-kb-061--external-knowledge-sources) | External knowledge sources | NEW | LATER | Professional |
| [REQ-KB-062](#req-kb-062--one-suggestion-service-for-every-entry-point) | One suggestion service for every entry point | BETTER | MVP | Essentials |
| [REQ-KB-063](#req-kb-063--search-and-insert-from-the-editors) | Search and insert from the editors | BETTER | MVP | Essentials |
| [REQ-KB-064](#req-kb-064--link-articles-to-records) | Link articles to records | SAME | MVP | Essentials |
| [REQ-KB-065](#req-kb-065--reuse-that-is-counted) | Reuse that is counted | NEW | V1 | Essentials |
| [REQ-KB-066](#req-kb-066--work-in-progress-knowledge-for-technicians) | Work-in-progress knowledge for technicians | BETTER | V1 | Essentials |
| [REQ-KB-067](#req-kb-067--forward-and-share-an-article) | Forward and share an article | SAME | V1 | Essentials |
| [REQ-KB-068](#req-kb-068--print-and-pdf) | Print and PDF | SAME | V1 | Essentials |
| [REQ-KB-069](#req-kb-069--did-this-help) | "Did this help?" | BETTER | MVP | Essentials |
| [REQ-KB-070](#req-kb-070--feedback-reaches-the-owner) | Feedback reaches the owner | NEW | V1 | Essentials |
| [REQ-KB-071](#req-kb-071--comments-on-articles) | Comments on articles | SAME | V1 | Essentials |
| [REQ-KB-072](#req-kb-072--usage-figures-on-every-article) | Usage figures on every article | BETTER | V1 | Essentials |
| [REQ-KB-073](#req-kb-073--knowledge-reports-and-dashboard-widgets) | Knowledge reports and dashboard widgets | SAME | V1 | Essentials |
| [REQ-KB-074](#req-kb-074--self-service-deflection) | Self-service deflection | NEW | V1 | Essentials |
| [REQ-KB-075](#req-kb-075--knowledge-gaps) | Knowledge gaps | NEW | V1 | Essentials |
| [REQ-KB-076](#req-kb-076--knowledge-author-agent) | Knowledge author agent | NEW | LATER | Professional |
| [REQ-KB-077](#req-kb-077--knowledge-list-with-topic-tree-and-views) | Knowledge list with topic tree and views | SAME | MVP | Essentials |
| [REQ-KB-078](#req-kb-078--article-page) | Article page | BETTER | MVP | Essentials |
| [REQ-KB-079](#req-kb-079--trash-and-restore) | Trash and restore | SAME | MVP | Essentials |
| [REQ-KB-080](#req-kb-080--history-and-audit) | History and audit | BETTER | MVP | Essentials |
| [REQ-KB-081](#req-kb-081--knowledge-in-the-portal) | Knowledge in the portal | SAME | MVP | Essentials |
| [REQ-KB-082](#req-kb-082--knowledge-in-portal-search) | Knowledge in portal search | SAME | MVP | Essentials |
| [REQ-KB-083](#req-kb-083--from-an-article-to-a-request) | From an article to a request | BETTER | V1 | Essentials |
| [REQ-KB-084](#req-kb-084--follow-an-article) | Follow an article | NEW | V1 | Essentials |
| [REQ-KB-085](#req-kb-085--public-knowledge-base-without-sign-in) | Public knowledge base without sign-in | NEW | LATER | Essentials |
| [REQ-KB-086](#req-kb-086--knowledge-notifications-with-sensible-defaults) | Knowledge notifications with sensible defaults | BETTER | MVP | Essentials |
| [REQ-KB-087](#req-kb-087--announce-a-new-article) | Announce a new article | SAME | V1 | Essentials |
| [REQ-KB-088](#req-kb-088--import-articles) | Import articles | BETTER | V1 | Essentials |
| [REQ-KB-089](#req-kb-089--export-articles) | Export articles | NEW | V1 | Essentials |
| [REQ-KB-090](#req-kb-090--knowledge-settings-on-one-page) | Knowledge settings on one page | BETTER | MVP | Essentials |
| [REQ-KB-091](#req-kb-091--automation-on-knowledge-events) | Automation on knowledge events | SAME | V1 | Essentials |
| [REQ-KB-092](#req-kb-092--knowledge-on-the-mobile-app) | Knowledge on the mobile app | SAME | V1 | Essentials |
| [REQ-KB-093](#req-kb-093--knowledge-from-servicedesk-plus) | Knowledge from ServiceDesk Plus | NEW | LATER | Essentials |
<!-- summary:end -->

---

## 1. Articles and topics

#### REQ-KB-001 — Knowledge article record and core fields

A knowledge article has:

- title and body (rich text), both required;
- topic (required), article type, keywords and language;
- status (REQ-KB-026), owner (REQ-KB-033), audience (REQ-KB-044, REQ-KB-045);
- review date and expiry date (REQ-KB-034, REQ-KB-035);
- attachments, related articles and links to records;
- an internal note for authors and approvers, never shown to readers;
- created by, created at, last updated by, last updated at, published at, version number and
  view count.

- **Decision:** SAME.
- **Source:** sdp-area-08 §Fields, §Screens (solution detail page, right panel); architecture §2.15 (knowledge base)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Creating an article without a title, body or topic is refused, and the message names each
     missing field.
  2. The internal note is never returned by the API to a user without edit rights on the
     article, and never appears in the portal.
  3. The article page shows created, updated and published times in the reader's time zone.

#### REQ-KB-002 — Article IDs with a prefix

Every article gets a human ID from a per-tenant counter with a prefix, for example KB-42. An
admin can change the prefix and the starting number before the first article exists, and the
prefix at any time. Searching for the ID opens the article.

- **Decision:** SAME.
- **Source:** sdp-area-08 §Config (ID prefix and starting ID); architecture §7.1; D-045
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. The first article in a new tenant is KB-1 under the default settings (Appendix A).
  2. After a prefix change, new articles use the new prefix and old IDs still open their
     articles.
  3. An ID is never reused, even after the article is deleted.
  4. Translations of an article share its ID (REQ-KB-049).

#### REQ-KB-003 — Topic tree

Topics form a tree up to six levels deep. A topic can be created at the top or under any topic
directly from one dialog with a parent field. An icon is optional: a topic without one gets a
neutral default. Each topic has a name per language, an optional description, and an order
among its siblings.

- **Decision:** BETTER. The parent can be chosen when creating, and the icon is optional.
- **Source:** sdp-area-08 §Screens (topic management, new topic dialog), §Weak spots (icon forced)
- **SDP weak spot fixed:** the new topic dialog has no parent field, so subtopics need a context
  menu, and an icon is mandatory, which slows down building many topics.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A topic can be created under an existing topic from the new topic dialog, without opening
     a context menu.
  2. A topic saved without an icon shows the default icon.
  3. A seventh level is refused with a message giving the limit.
  4. Topic names show in the reader's language, falling back to the default language.

#### REQ-KB-004 — Managing topics

People with the topic permission can rename, reorder (drag and drop), move a topic with its
subtopics, merge two topics, and delete a topic. Deleting a topic that holds articles asks
where to move them; nothing is deleted silently. Deleted topics go to the trash with their
place in the tree and can be restored. Each topic can have a topic owner (REQ-KB-033).

- **Decision:** BETTER. Adds merge and makes deleting a topic with content explicit.
- **Source:** sdp-area-08 §Screens (topic context menu: new, edit, share, topic owner, delete; trashed topics)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Moving a topic moves its subtopics and articles, and every article's history records the
     new topic path.
  2. Deleting a topic with 12 articles asks for a target topic and moves all 12 there before
     the topic goes to the trash.
  3. A restored topic returns under its old parent, or at the top level if the parent is gone.
  4. Reordering in one browser shows the new order in another browser without a refresh.

#### REQ-KB-005 — Keywords that help search

Articles take keywords as separate tags (typed, pasted as a comma list, or picked from keywords
already used). Keywords are optional; the form never marks them as required. They raise the
rank of an article in search and suggestions, and can be suggested by AI (REQ-KB-019).

- **Decision:** BETTER. Keywords are honestly optional and are reused as tags.
- **Source:** sdp-area-08 §Fields (keywords), §Weak spots (required marker on an optional field), §Behaviour (suggestions match keywords)
- **SDP weak spot fixed:** keywords show a required marker but are optional.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. An article saves without keywords, and the form shows no required marker on them.
  2. Pasting "vpn, remote access, token" creates three keyword tags.
  3. For a query that matches one article's keyword and another article's body only, the
     keyword match ranks higher.

#### REQ-KB-006 — Rich-text article body

The body uses the shared rich-text editor (REQ-INC-064, Tiptap, D-036, D-040) with what
articles need on top: headings with an automatic table of contents, numbered steps, tables,
code blocks, callouts (note, tip, warning), links to other articles and records, inline
images and image alt text. The server sanitises every stored value with the shared allow-list
(architecture §11.4). The text is registered as typed; there is no lost-input error on save.

- **Decision:** BETTER. One safe editor for articles and records, with article structure.
- **Source:** D-036; D-040; architecture §11.4 (sanitised HTML in KB articles); sdp-area-08 §Fields (content), §Weak spots (false content error)
- **SDP weak spot fixed:** the first save can fail with a false "content required" error until
  one more key is pressed.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A script tag, event handler or `javascript:` link in an article body is removed before
     storage, on every path (editor, API, import).
  2. Saving immediately after typing (without leaving the field) keeps the full text.
  3. An article with three headings shows a table of contents that jumps to each heading.
  4. An image without alt text is flagged by the quality check (REQ-KB-018).

#### REQ-KB-007 — Attachments and images on articles

Files and images can be attached to an article and placed inline, with the same scanning,
encryption, size and type limits as record attachments (REQ-INC-079). A reader can open an
attachment only if they can read the article. Attachments belong to a version, so an older
version keeps its own files.

- **Decision:** SAME.
- **Source:** sdp-area-08 §Fields (attachments); architecture §6.8 (files)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A requester outside the article's audience gets 404 for its attachment link, even with
     the file ID.
  2. A file still being scanned shows its scan state and cannot be opened.
  3. Replacing an attachment in a new version leaves the old file on the old version.

#### REQ-KB-008 — Article types

Every article has a type. The type picks the default template (REQ-KB-014), the default review
interval (REQ-KB-034) and some behaviour: workaround and known issue types link to a problem
(REQ-KB-039, REQ-KB-041). Admins can add, rename, translate and retire types; built-in types
keep their behaviour. Defaults are in Appendix A.

- **Decision:** NEW. ServiceDesk Plus has templates but no article types, so reports and
  search cannot tell a how-to from a troubleshooting note.
- **Source:** sdp-area-08 §Screens (new solution form: template picker); architecture §2.15 (knowledge base: templates); product-plan §5 (KCS workflow)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A new tenant has the article types in Appendix A.
  2. Search and the knowledge list can be filtered by type.
  3. A retired type cannot be chosen for new articles; existing articles keep it.
  4. Workaround and known issue types are available only where problems are licensed
     (REQ-WI-025).

#### REQ-KB-009 — Custom fields on articles

Admins can add custom fields to articles (text, number, date, choice, lookup, user), with
labels in each language, and choose which article types show them and whether readers see
them.

- **Decision:** SAME.
- **Source:** sdp-area-13 §Additional Fields (module dropdown includes solutions); architecture §6.6
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A custom field added for the troubleshooting type shows on troubleshooting articles only.
  2. A field marked "authors only" never reaches the portal or a technician without edit rights.
  3. Custom fields can be used as filters in the knowledge list and in search.

#### REQ-KB-010 — Related articles

An author can link articles to each other as related. Both articles list the link, and readers
see related articles they are allowed to read at the end of the article.

- **Decision:** SAME.
- **Source:** sdp-area-08 §Screens (right panel: linked solutions)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Linking KB-3 to KB-7 lists each on the other, with a history entry on both.
  2. A reader who cannot read KB-7 does not see it in KB-3's related list.

#### REQ-KB-011 — Articles about services and configuration items

An article can be linked to business services and configuration items. When an incident or
request names a service or CI, articles linked to it rank higher in suggestions, and the CI
and service pages list their articles.

- **Decision:** NEW. ServiceDesk Plus links solutions to records but not to services or CIs.
- **Source:** architecture §2.12 (CMDB), §2.15 (linking to tickets)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. An incident with CI "mail-gw-01" shows articles linked to that CI first in its suggestions.
  2. The CI page lists the articles linked to it that the user may read.
  3. Linking writes history on the article and the CI (REQ-WI-003).

---

## 2. Authoring and templates

#### REQ-KB-012 — Create and edit articles

People with the create permission write articles in the console, from the knowledge area, a
record (REQ-KB-016) or the command palette (REQ-WI-022). The editor always offers the same
actions in the same places: save draft, submit for review, and publish (only for those
allowed to publish, REQ-KB-028). An action that does not apply is shown disabled with the
reason, for example "publishing to requesters needs approval". A shortcut opens a new
article.

- **Decision:** BETTER. Buttons never vanish; each action says why it is unavailable.
- **Source:** sdp-area-08 §Actions (create and edit buttons), §Weak spots (add button vanishes); sdp-area-01 §Screens (quick actions: new solution shortcut); REQ-WI-010
- **SDP weak spot fixed:** ticking "publish in portal" removes the plain add button with no
  explanation.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Changing the audience to include requesters leaves every button in place; publish shows
     disabled with a reason for an author who may not publish to requesters.
  2. A technician without the create permission sees no create entry, and the API refuses
     creation with 403.
  3. The new-article shortcut opens the editor with the current topic pre-selected when used
     from a topic.

#### REQ-KB-013 — Drafts are saved automatically

While an article is written, the draft is saved automatically every few seconds and on leaving
the field. Leaving the page with unsaved changes asks first. An author's drafts are listed in
"my drafts" and can be continued from any device. Drafts are visible only to the author and to
people with edit rights on the topic.

- **Decision:** NEW. ServiceDesk Plus has "save as draft" only on edit, with no autosave.
- **Source:** sdp-area-08 §Actions (save as draft on edit only)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Closing the browser 10 seconds after typing and reopening "my drafts" shows the text.
  2. A requester or a technician without edit rights cannot see another author's draft.
  3. Navigating away with unsaved changes asks for confirmation.

#### REQ-KB-014 — Article templates

Admins keep article templates. A template pre-fills the body structure (for example
"symptoms, cause, resolution" for troubleshooting), the topic, keywords, audience and custom
fields. Each article type has a default template. Switching template on a draft keeps what was
typed and adds the new structure below, never overwriting text. Templates have names and
content per language, and usage is reported (REQ-KB-073).

- **Decision:** SAME. ServiceDesk Plus ships sample solution templates.
- **Source:** sdp-area-08 §Screens (new solution form: template picker), §Fields (template); sdp-area-09 §Screens (report "solution templates in use"); architecture §2.15
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Choosing the troubleshooting template fills the three headings into an empty body.
  2. Switching template on a draft with text keeps all existing text.
  3. An Arabic-speaking author gets the Arabic version of the template if one exists.

#### REQ-KB-015 — Two people editing the same article

When two people open the same draft or article for editing, each sees that the other is there
(REQ-WI-006). Saves use the version read (REQ-WI-007): a second save over a newer version is
refused, and the editor shows what changed and lets the person merge their text in, never
losing it.

- **Decision:** BETTER. ServiceDesk Plus gives no warning when two people edit one solution.
- **Source:** architecture §6.5 (optimistic concurrency); REQ-WI-006; REQ-WI-007
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. With two editors open, each sees the other's presence within one second.
  2. The second of two conflicting saves is refused with 409, and the person's unsaved text
     is still in their editor.
  3. The conflict view shows the other person's changes highlighted.

#### REQ-KB-016 — Article from a resolved record

From the resolution of an incident, service request or problem, a technician saves an article
draft (REQ-INC-091, REQ-PRB-041). The draft is pre-filled from the record (subject as title,
the resolution as the body, category mapped to a topic, record type mapped to an article
type) and linked to the record. Before saving, the author sees a warning if the text holds
personal data such as email addresses, phone numbers or what looks like a password, and can
edit it. The record shows the article it produced.

- **Decision:** SAME. Adds the personal-data warning.
- **Source:** sdp-area-08 §Behaviour (request to solution: save and add to solutions), §Actions (resolution tab); sdp-area-02c §Screens (resolution tab); REQ-INC-091; REQ-PRB-041
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. "Save as knowledge" on INC-12 creates an unpublished draft linked to INC-12, with INC-12's
     subject as its title.
  2. A resolution containing an email address shows a personal-data warning in the draft.
  3. INC-12 lists the draft under its linked articles, and the draft lists INC-12 as its
     source.

#### REQ-KB-017 — Duplicate article warning

While a title and body are typed, existing articles that look similar are shown beside the
editor, without moving it (REQ-WI-012). The author can open one, link to it, or switch to
improving it instead of writing a new one.

- **Decision:** NEW. Duplicate articles are the main cause of a messy knowledge base.
- **Source:** product-plan §5 (KCS workflow); architecture §2.15
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Typing a title close to an existing article's title lists that article within one second.
  2. "Improve this one instead" opens an edit draft of the existing article and keeps the new
     text for copying.
  3. Only articles the author may read are shown.

#### REQ-KB-018 — Quality checks before review

When an article is submitted for review, it is checked and the author sees the results:

- required fields and custom fields filled;
- broken links to articles or records (REQ-KB-038);
- images without alt text;
- possible personal data (email addresses, phone numbers, secrets);
- a missing translation where the topic requires one (REQ-KB-049).

Admins choose which checks block and which only warn.

- **Decision:** NEW.
- **Source:** architecture §11.3 (PII); REQ-WI-023 (accessibility); product-plan §5 (KCS workflow)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Submitting an article that links to a deleted article shows the broken link and blocks
     submission under the default settings (Appendix A).
  2. An image without alt text gives a warning but does not block by default.
  3. Each check result names the place in the article it refers to.

#### REQ-KB-019 — AI drafting help for articles

In the article editor, the author can ask AI to:

- draft a title, body or keywords from a short prompt or from a source record;
- change the length, the tone or the structure of the selected text;
- suggest a topic and keywords for the draft.

The author reviews every result before it is inserted; nothing is published by AI. Model
access follows D-049 and file 10.

- **Decision:** SAME. The same generator works on every deployment, including the local model.
- **Source:** sdp-area-10 §Fields (solution generator dialog), §Behaviour (solution generator); architecture §2.10 (solution generator); product-plan §7.2
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A generated draft is shown for review and inserted only when the author accepts it.
  2. Accepted AI text is recorded in history with source "AI", accepted by the author.
  3. Personal data is masked before an external model is called.
  4. The feature passes its tests with the on-prem local model profile.

---

## 3. Versions

#### REQ-KB-020 — Every published change is a version

Each time an article is published, its content becomes a new numbered version with who, when
and an optional change note. Versions are always on; there is no setting to turn them off. The
list of versions shows status, author, approver and note.

- **Decision:** BETTER. ServiceDesk Plus versioning is a tenant switch that is off by default.
- **Source:** sdp-area-08 §Config (enable solution versioning: off); architecture §2.15 (versions); product-plan §5 (versions are Cloud only)
- **SDP weak spot fixed:** versioning is off by default and Cloud only, so edits overwrite the
  published text with no way back.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Publishing an article twice gives versions 1 and 2, both listed with author and time.
  2. Version content cannot be changed or deleted through any API.
  3. The version number shows on the article page for technicians.

#### REQ-KB-021 — Edit a published article without taking it offline

Editing a published article creates a new draft version. Readers keep seeing the published
version until the new one is approved and published; then it replaces the old one in one step.
The article page shows technicians that a newer draft is in progress, and by whom.

- **Decision:** BETTER. In ServiceDesk Plus editing an approved solution changes what readers
  see, or forces it back through approval while readers lose it.
- **Source:** sdp-area-08 §Actions (edit buttons: save, save and approve, save as draft)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. While version 3 is in review, a requester still reads version 2.
  2. Publishing version 3 changes the portal page live, without a refresh.
  3. Rejecting version 3 leaves version 2 published and unchanged.

#### REQ-KB-022 — Compare versions

Any two versions of an article can be compared side by side or inline, with added, removed and
changed text highlighted, including changes to title, topic, keywords, audience and dates.
Approvers see the comparison with the published version by default when they review.

- **Decision:** BETTER. ServiceDesk Plus has no comparison of solution versions.
- **Source:** architecture §2.15 (versions); sdp-area-08 §Config (versioning)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Comparing versions 1 and 2 highlights a changed sentence and a changed audience.
  2. An approver opening a review sees the changes against the published version first.
  3. Comparison works for Arabic text laid out right to left.

#### REQ-KB-023 — Restore an earlier version

A person with edit rights can restore an earlier version. Restoring creates a new draft from
it; it does not publish by itself and does not delete later versions.

- **Decision:** SAME.
- **Source:** architecture §2.15 (versions)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Restoring version 1 of an article at version 3 creates draft version 4 with version 1's
     content.
  2. Versions 2 and 3 remain in the list.

#### REQ-KB-024 — Minor edits

A person with the minor-edit permission can publish a small correction (for example a typo)
without a new approval, marked as minor. A minor edit still creates a version, keeps the
review date and the feedback, and is shown in history. Changes to audience, topic or type are
never minor.

- **Decision:** NEW. Fixing a typo should not reset approval or ratings.
- **Source:** sdp-area-08 §Actions (save and approve asks to reset likes and dislikes)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A minor edit by a permitted user is published at once as a new version marked minor.
  2. Changing the audience in the same edit removes the minor option and needs approval.
  3. A user without the permission does not get the minor option.

#### REQ-KB-025 — No switch to turn versioning off

SupportX has no tenant setting to switch article versioning off. Versions are always kept.

- **Decision:** SKIP. A switch that throws away history adds risk and no value; audit and
  compare need versions (REQ-KB-020, REQ-KB-080).
- **Source:** sdp-area-08 §Config (enable solution versioning)
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. No admin screen or API offers a setting to disable versions.
  2. The migration tool imports ServiceDesk Plus solutions as version 1 whatever that switch
     was (REQ-KB-093).

---

## 4. Approval and publishing

#### REQ-KB-026 — Article statuses with a fixed meaning

Every article version has one status: draft, in review, published, withdrawn or archived.
Expired and "needs review" are flags on a published article, not separate statuses. Approval
and publishing are one step: an approved version is published to its audience. Actions offered
on an article follow its status and the user's rights (REQ-WI-010); an action that is already
done is never offered again.

- **Decision:** BETTER. One clear set of states instead of separate approval and publish
  states.
- **Source:** sdp-area-08 §Screens (views: approved, approval pending, unapproved), §Actions (detail actions menu), §Weak spots (publish listed on a published solution); architecture §2.15 (approvals)
- **SDP weak spot fixed:** "approved" and "published" are separate, and the menu offers
  "publish" on a solution that is already published.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. The action menu of a published article has no publish action, and keeps the same number
     of entries in the same order (REQ-WI-010).
  2. An expired article keeps the status published with an expired flag.
  3. Statuses and flags display through labels in English and Arabic.

#### REQ-KB-027 — Submit, approve and reject

An author submits a draft for review with an optional note. The approvers for the article's
topic (topic owner, then people with the approve permission) get an in-app task and a
notification (REQ-KB-086). An approver sees the article, the changes (REQ-KB-022) and the
quality check results, and then approves or rejects. Rejecting needs a reason and returns the
draft to the author. Review works with no mail server: in-app notifications are enough.

- **Decision:** BETTER. Works without email and always shows why a draft was rejected.
- **Source:** sdp-area-08 §Actions (approve dialog), §Automation (manual approval), §Behaviour (submit for approval failed without mail), §Weak spots (approval depends on mail)
- **SDP weak spot fixed:** submitting for approval fails outright when no mail server is set.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. With no mail server configured, submitting a draft creates an in-app review task for the
     topic's approvers.
  2. Rejecting without a reason is refused; the author sees the reason on the draft.
  3. Approving publishes the version to its audience, and the portal shows it within one
     second.
  4. An approver cannot approve a version they cannot read.

#### REQ-KB-028 — Approving your own article

A tenant setting decides whether a person with the approve permission may publish their own
article without a second person. When it is off, the author's own submissions go to another
approver, and the API refuses self-approval.

- **Decision:** SAME.
- **Source:** sdp-area-08 §Config (allow approver to approve their own solutions: on), §Automation; sdp-area-11 §Fields (allow technician to approve solutions)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. With the setting on (default, Appendix A), an approver can publish their own article in
     one step.
  2. With the setting off, the same action is disabled with a reason, and the API returns 403.
  3. The history of a self-approved version records that the author approved it.

#### REQ-KB-029 — Multi-step approval

Admins can require more than one approval step for chosen topics or types, for example the
topic owner and then a compliance reviewer, using the shared approval engine (REQ-INC-083) or
a workflow (file 03). Each step records who decided, when and why.

- **Decision:** BETTER. ServiceDesk Plus has a single approve step.
- **Source:** sdp-area-08 §Automation (manual approval only); architecture §2.15 (approvals); product-plan §5 (KB with approvals)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. An article in a topic with two steps is published only after both steps approve.
  2. A rejection at step two returns the draft to the author with the step and the reason.
  3. Each step's decision is in the article history.

#### REQ-KB-030 — Scheduled publishing

An approver can approve a version to go live at a chosen date and time. Until then readers see
the earlier version (or nothing for a new article). Publishing happens on time even if nobody
is signed in.

- **Decision:** NEW.
- **Source:** architecture §2.15 (approvals, publish to portal)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A version approved for 09:00 tomorrow is not visible to readers before then, and is
     visible within one minute after.
  2. The article shows "scheduled" with the time to technicians.
  3. Cancelling the schedule returns the version to approved-not-published, recorded in
     history.

#### REQ-KB-031 — Withdraw an article

A person with permission withdraws a published article with a reason. It disappears from the
portal, search and suggestions for readers, live. Links to it from records stay, and show
"withdrawn" to technicians and "no longer available" to requesters. A withdrawn article can be
republished through approval.

- **Decision:** SAME.
- **Source:** sdp-area-08 §Actions (reject, delete); architecture §2.15 (publish to portal)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Withdrawing removes the article from the portal topic page in another browser within one
     second.
  2. A requester following a saved link sees "no longer available", not an error page.
  3. Withdrawing without a reason is refused.

#### REQ-KB-032 — Bulk actions on articles

From the knowledge list, a person can select articles across pages and, as permissions allow:

- approve or reject;
- move to another topic;
- change the audience, the owner, or the review or expiry date;
- withdraw, archive or delete.

Each action shows a preview of what will change, runs in the background for large selections
with progress, and reports results per article.

- **Decision:** SAME. Adds the preview and results per article.
- **Source:** sdp-area-08 §Screens (list toolbar: share, approve actions, move, delete), §Actions (list toolbar share)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Moving 300 selected articles shows a preview count, runs with live progress and reports
     any article that failed and why.
  2. Articles the user may not change are listed as skipped with the reason.
  3. Changing the audience in bulk writes one history entry per article.

---

## 5. Ownership, review and expiry

#### REQ-KB-033 — Article and topic owners

Every article has an owner, by default its author. Every topic can have a topic owner, who is
the first approver and the fallback owner for its articles. When an owner is deactivated, their
articles move to the topic owner, and the topic owner is told. Owners see their articles in
"my articles" with review and feedback counts.

- **Decision:** BETTER. ServiceDesk Plus has topic owners but no article owner, so review dates
  reach nobody.
- **Source:** sdp-area-08 §Screens (topic owner); architecture §2.15 (expiry and review dates)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A new article's owner is its author.
  2. Deactivating a user moves their 5 articles to the topic owner, with a history entry on
     each.
  3. Changing an owner needs edit rights on the topic and is recorded in history.

#### REQ-KB-034 — Review dates and review without a new version

Each article has a review date, set by default from its type's review interval (Appendix A).
Any future date, including today, can be chosen. On or after the date the article gets a
"review due" task for its owner. The owner can confirm the article is still correct, which
records the review and sets the next review date without creating a new version, or edit it.

- **Decision:** BETTER. Adds review intervals by type and a "still correct" confirmation.
- **Source:** sdp-area-08 §Fields (review date), §Screens (views: due for periodic review today, in 15 days), §Weak spots (today rejected); architecture §2.15
- **SDP weak spot fixed:** a review date of today is rejected, and reviewing means editing.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A new how-to article gets a review date 12 months ahead under the default settings.
  2. A review date of today is accepted.
  3. "Still correct" records the review in history and moves the review date by the interval,
     with no new version.
  4. Articles due for review appear in the "due for review" views live.

#### REQ-KB-035 — Expiry

An article can have an expiry date. When it passes, the article is flagged expired: it leaves
the portal, requester search and suggestions, and stays visible to technicians with an
expired marker. Publishing a new version with a later or no expiry date ends the expiry.

- **Decision:** SAME.
- **Source:** sdp-area-08 §Fields (expiry date), §Screens (views: expired solutions); architecture §2.15
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. One minute after its expiry time, an article is no longer found by a requester's search.
  2. A technician still finds it, labelled expired.
  3. The expiry date must be after the review date, or the form says why it is refused.

#### REQ-KB-036 — Review and expiry reminders

Owners get a reminder before an article's review date and before its expiry date, and a
reminder when the review is overdue. Owners with many articles get them as a daily digest. The
reminders use the notification engine (file 03) and their timing is set by the admin.

- **Decision:** BETTER. ServiceDesk Plus shows review views but no reminders were found.
- **Source:** sdp-area-08 §Automation (review and expiry drive views only); sdp-area-12 §Screens (notification rules: solution tab)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. An owner gets an in-app reminder 14 days before the review date (default, Appendix A).
  2. An owner with 20 articles due the same week gets one digest, not 20 messages.
  3. The reminder links to the article and the "still correct" action.

#### REQ-KB-037 — Content health view

A content health view lists articles that may be stale, with the reason for each:

- not viewed for a set period;
- helpfulness below a threshold with enough votes;
- review overdue;
- linked to a retired known error or a withdrawn article;
- broken links (REQ-KB-038);
- a translation behind its source (REQ-KB-050).

Owners and topic owners can act from the view: confirm, edit, withdraw or archive.

- **Decision:** NEW.
- **Source:** sdp-area-08 §Weak spots (no reporting on versioning and ratings); product-plan §5 (KCS workflow)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. An article with 12 votes and 25 percent helpful appears with the reason "low helpfulness"
     under the default threshold (Appendix A).
  2. Confirming an article as correct from the view removes it until a reason applies again.
  3. The view can be filtered by topic, owner and reason.

#### REQ-KB-038 — Broken link checks

Links inside articles are checked:

- links to other articles and to records are checked at once when the target is withdrawn,
  archived or deleted;
- links to outside web pages are checked on a schedule, only when the admin has turned the
  check on.

Broken links are flagged on the article for its owner, listed in content health
(REQ-KB-037), and shown in the quality check (REQ-KB-018).

- **Decision:** NEW.
- **Source:** architecture §2.15 (knowledge base); product-plan §5 (KCS workflow)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Deleting KB-9 flags every article that links to KB-9 within one minute.
  2. With the outside link check off, the server makes no outbound requests for it.
  3. An outside link returning "not found" twice in a row is flagged as broken.

---

## 6. Workaround articles and known issues

#### REQ-KB-039 — Workaround articles follow their problem

A workaround article is created from a problem's workaround (REQ-PRB-039) as a technician-only
draft of the workaround type, linked to the problem. It shows the problem's ID, title, status
and known error marker live at the top, and links back to it. Its owner is the person who
published it. It goes through the normal approval flow (REQ-KB-027).

- **Decision:** BETTER. The workaround and the article stay connected instead of drifting
  apart as two copies.
- **Source:** REQ-PRB-039; sdp-area-08 §Behaviour (problem to solution); sdp-area-04 §Screens (solution tab: workaround and resolution)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Publishing a workaround from PRB-4 creates a draft of the workaround type linked to PRB-4,
     with requesters excluded from the audience.
  2. Moving PRB-4 to "awaiting fix" changes the status shown on the article in another browser
     within one second.
  3. A reader without access to problems sees the problem's ID, title and status on the
     article, but cannot open the problem (REQ-PRB-071).

#### REQ-KB-040 — Review flag when the problem changes

A workaround article or known issue gets a "needs review" flag, and its owner gets a review
task, when its problem changes in a way that may make it wrong:

- the workaround text on the problem is edited;
- a root cause is recorded or changed;
- the problem is resolved, closed or its known error retired (REQ-PRB-042);
- the problem is merged into another problem.

The flag shows to technicians on the article, in the knowledge list and in content health. It
clears when the owner confirms or publishes a new version.

- **Decision:** NEW. ServiceDesk Plus never connects a problem's later changes to the
  solutions copied from it.
- **Source:** REQ-PRB-039 (AC2); REQ-PRB-042; sdp-area-04 §Behaviour (known error flag kept after the fix)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Editing the workaround on PRB-4 flags its article and creates a review task for the owner.
  2. Resolving PRB-4 with a permanent fix flags its technician article for review; it stays
     published until reviewed (REQ-PRB-042 AC3).
  3. "Still correct" clears the flag, with the reason recorded in history.

#### REQ-KB-041 — Known issues in the portal

A known issue is a requester-facing article of the known issue type, created from a known error
(REQ-PRB-040). Its text is written for requesters and is separate from the internal
workaround. After approval it shows:

- in the portal's known issues list and in portal knowledge search, for its audience only;
- on the portal page of every incident linked to the problem;
- first among suggestions when a requester reports an issue that matches it.

When the known error is retired, the known issue is withdrawn or flagged for review as the
tenant chooses (REQ-PRB-042, file 04 Appendix A). A withdrawn known issue stays readable from
linked incidents with a "resolved" banner.

- **Decision:** BETTER. ServiceDesk Plus can only publish a copied solution; there is no known
  issues list and no separate requester text.
- **Source:** REQ-PRB-040; REQ-PRB-042; sdp-area-08 §Fields (publish in self-service portal, user groups); architecture §2.3 (known error database)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. An approved known issue for the "Riyadh site" audience is in the portal list for Riyadh
     requesters only.
  2. The known issue's text never includes the internal workaround or root cause unless the
     author copied it in.
  3. Under the default setting, resolving the problem withdraws the known issue, and it leaves
     the portal list live; linked incidents show it with a "resolved" banner.

#### REQ-KB-042 — Known errors alongside articles in suggestions

Where knowledge suggestions are shown to technicians (REQ-KB-062), matching known errors
(REQ-PRB-038) are listed in the same panel, labelled as known errors, ahead of ordinary
articles of equal match. One click applies the workaround as REQ-PRB-038 describes.

- **Decision:** BETTER. One panel for both kinds of help instead of two places to look.
- **Source:** REQ-PRB-038; sdp-area-08 §Behaviour (suggested solutions panel)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A known error and an article matching equally appear with the known error first, each
     with its label.
  2. Tenants without problems licensed see articles only, with no empty known error section.

---

## 7. Visibility and permissions

#### REQ-KB-043 — Knowledge permissions

Roles control knowledge by action and scope (REQ-WI-015):

- view, create, edit own, edit any, delete;
- submit, approve, approve own (REQ-KB-028), minor edit (REQ-KB-024);
- publish to requesters, withdraw, archive;
- manage topics, manage templates and types, manage settings;
- moderate comments and feedback.

Scope can be limited to chosen topics. A new tenant gets a knowledge manager role with every
knowledge permission (Appendix A).

- **Decision:** SAME. Finer than view, add, edit and delete plus one approve switch.
- **Source:** sdp-area-11 §Fields (role permission matrix: solutions; general: allow technician to approve solutions); architecture §11.2
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A technician with "edit own" cannot edit another author's article; the API returns 403.
  2. A technician limited to the "Network" topic cannot create articles in other topics.
  3. The knowledge manager role exists in a new tenant and can be copied and changed.

#### REQ-KB-044 — Technician visibility by group, set on topics and articles

Each topic has a technician audience: all technicians or chosen groups. Articles inherit their
topic's audience and may narrow it. Changing a topic's audience shows how many articles inherit
it and how many have their own, and applies only to the inheriting ones unless the person
chooses otherwise.

- **Decision:** BETTER. ServiceDesk Plus warns that sharing a topic may overwrite sharing on
  its solutions, without saying which.
- **Source:** sdp-area-08 §Screens (share topic dialog), §Actions (share dialog), §Behaviour (sharing); sdp-area-11 §Fields (granular scope)
- **SDP weak spot fixed:** sharing a topic may silently overwrite the sharing set on each
  solution.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. An article in a topic shared with "Network" only is not visible to a technician outside
     that group in lists, search or suggestions.
  2. Changing a topic's audience shows "38 articles inherit, 4 have their own" before saving.
  3. An article cannot be given a wider technician audience than its topic.

#### REQ-KB-045 — Requester audiences

An article is visible to requesters only when its audience includes them. The requester
audience can be all requesters or any mix of requester groups, sites and departments (and,
later, customers in multi-customer setups, file 12). An article's audience is shown in
plain words on the article, for example "technicians: all; requesters: Riyadh site, Finance
department".

- **Decision:** BETTER. ServiceDesk Plus offers only requester groups.
- **Source:** sdp-area-08 §Fields (publish in self-service portal, user groups), §Behaviour (no per-site visibility); architecture §2.15 (portal layouts per audience)
- **SDP weak spot fixed:** requester visibility is by user group only; there is no site or
  department audience.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. An article for "Finance department" is found by a Finance requester and not by an IT
     requester.
  2. An article for "Riyadh site or Finance department" is visible to a requester in either.
  3. A requester moving from Finance to IT loses access to Finance-only articles at once.

#### REQ-KB-046 — Technician-only sections in a requester article

An author can mark parts of a requester-visible article as technician only, for example admin
steps or internal contacts. Requesters never receive those parts, from any path: portal, API,
search snippets, AI answers, print or email forward.

- **Decision:** NEW. Without it, teams keep two copies of the same article.
- **Source:** sdp-area-08 §Fields (comment: show to requester); architecture §11.2 (field-level visibility)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. The portal API response for the article contains no text from a technician-only section.
  2. A search for a word that appears only in a technician-only section finds nothing for a
     requester.
  3. Technicians see the section with a clear "technicians only" marker.

#### REQ-KB-047 — Preview as a reader

An author or admin can preview an article, a topic page or the portal knowledge home as a chosen
audience (for example "a requester in the Riyadh site") or as a chosen person, without signing
in as them. The preview applies that audience's real visibility, including technician-only
sections and translations.

- **Decision:** BETTER. ServiceDesk Plus has no way to see what a requester sees.
- **Source:** sdp-area-08 §Weak spots (no requester-side preview), §Limits; sdp-area-03 §Weak spots (portal preview is not a requester view)
- **SDP weak spot fixed:** there is no requester preview; the portal preview renders as the
  technician.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Previewing as a Riyadh requester hides an article whose audience is Jeddah only.
  2. The preview hides technician-only sections.
  3. Preview opens no session as the other person and is recorded in the audit log.

#### REQ-KB-048 — Visibility is enforced everywhere

Article visibility is decided by the one policy layer (architecture §11.2) and applies to every
path: lists, topic pages, search results and counts, suggestions, AI answers and citations,
related articles, links on records, attachments, print, export, notifications and live
updates. Where a record links to an article the user cannot read, they see that a link exists,
not its title.

- **Decision:** BETTER. One rule for every path, tested on each.
- **Source:** architecture §6.8 (search indexing: permission filters at query time), §11.2, §12 (retrieval applies permissions before ranking); REQ-PRB-035
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A search's result count never includes articles the user cannot read.
  2. An incident linking to a restricted article shows "1 restricted article" to a user who
     cannot read it.
  3. A live update about a restricted article is not delivered to a user outside its audience.
  4. An AI answer never cites an article the asking user cannot open.

---

## 8. Languages

#### REQ-KB-049 — Translations of an article

An article can exist in several languages: English and Arabic at MVP, Urdu from V1 (D-006,
D-048). Translations share the article's ID, topic, audience and links. Each translation has
its own title, body, keywords, status, versions and approval. Readers get the article in their
language; if there is no published translation, they get the default language with a note
that it is not available in theirs. Admins can require chosen languages for chosen topics.

- **Decision:** NEW. ServiceDesk Plus has no linked translations of a solution.
- **Source:** architecture §2.15 (administration: multi-language with Arabic and Urdu, RTL); product-plan §5 (Arabic and Urdu with RTL from day one); D-006; D-048
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. An Arabic-speaking requester opening KB-5 gets its published Arabic translation.
  2. With no Arabic translation, they get English with a note in Arabic saying so.
  3. Publishing the English version does not publish an Arabic draft.
  4. Feedback and view counts are kept per translation and summed on the article.

#### REQ-KB-050 — Translations that fall behind are flagged

When the source language version of an article is published with changes, its translations are
flagged "behind the source" for their owners, with a link to the changes (REQ-KB-022). A
minor edit (REQ-KB-024) can be marked as not needing translation.

- **Decision:** NEW.
- **Source:** product-plan §5 (Arabic and Urdu from day one); architecture §2.15
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Publishing version 3 in English flags the Arabic translation as behind.
  2. The translation owner sees the English changes since the version the translation was
     based on.
  3. A minor edit marked "no translation needed" does not flag translations.

#### REQ-KB-051 — AI translation drafts

An author can ask AI to draft a translation of an article into another supported language. The
draft keeps the structure, images and links, and goes through the normal approval; it is never
published by AI. Model access follows D-049 and file 10.

- **Decision:** NEW. ServiceDesk Plus offers a language change in its generator, not
  translations of an article.
- **Source:** architecture §2.10 (solution generator and translation); sdp-area-10 §Fields (solution generator: language)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A translation draft into Arabic keeps headings, lists, images and links of the source.
  2. The draft is created as a draft translation recorded with source "AI".
  3. The feature passes its tests with the on-prem local model profile.

#### REQ-KB-052 — Right-to-left and Arabic text in articles and search

Arabic and Urdu articles are written, shown, printed and compared right to left, with mixed
Arabic and English text kept in the right order. Search handles Arabic properly: it ignores
diacritics, treats variant letter forms as the same, and handles common prefixes, so that
words are found in their usual written forms.

- **Decision:** BETTER. Arabic search quality is a tender point in our markets.
- **Source:** CLAUDE.md §5d; D-006; architecture §2.15 (RTL), §5 (OpenSearch)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. An Arabic article with an English product name in a sentence renders in the right order.
  2. Searching an Arabic word without diacritics finds an article where it is written with
     them, and the reverse.
  3. Searching a word written with a different alef form finds the article.

---

## 9. Search and AI answers

#### REQ-KB-053 — Full-text knowledge search

Knowledge search uses the search service (OpenSearch, architecture §6.8) over title, body,
keywords, topic names and custom fields. It tolerates typos, matches word forms, and shows
highlighted snippets. Results can be filtered by topic, type, status, language, owner, audience
and dates. It is permission-filtered (REQ-KB-048). A published change is searchable within
five seconds. Knowledge is a scope of the global search (REQ-INC-109).

- **Decision:** BETTER. Topic names count, typos are tolerated, and freshness is defined.
- **Source:** sdp-area-08 §Behaviour (suggestions do not match topic names; filters topic and status); sdp-area-01 §Screens (global search scope: solutions); architecture §6.8 (search indexing)
- **SDP weak spot fixed:** an article in topic "Printers" is not found by the word "printer"
  unless it is in the title, body or keywords.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. "printr spooler" finds an article titled "Printer spooler keeps stopping".
  2. "printer" finds an article in topic "Printers" whose text does not contain the word.
  3. An article published now is found by search within five seconds.
  4. Results show highlighted snippets and can be narrowed by topic and type.

#### REQ-KB-054 — Synonyms

Admins keep synonym lists per language (for example "VPN, remote access" or "laptop,
notebook"), used by knowledge search and suggestions. Changes apply without re-indexing by
hand.

- **Decision:** NEW. ServiceDesk Plus has no synonym support.
- **Source:** architecture §6.8 (search indexing)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. With "laptop, notebook" as synonyms, searching "notebook" finds an article that says
     "laptop" only.
  2. A synonym added in the settings is used by search within five minutes.
  3. Synonym lists are kept separately for English and Arabic.

#### REQ-KB-055 — Search inside attachments

Text in common document attachments (PDF, Word, text) on articles is extracted after the
malware scan and indexed with the article. A match inside an attachment shows the file name in
the result.

- **Decision:** NEW.
- **Source:** architecture §6.8 (search indexing, files)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A word that appears only in an attached PDF finds the article, and the result names the
     PDF.
  2. A file that failed the malware scan is never indexed.

#### REQ-KB-056 — Ranking and promoted results

Search ranks by match quality and also by helpfulness, use on records, freshness and the
reader's language. Admins can promote chosen articles for chosen queries, so they show first.
Expired and withdrawn articles never rank for requesters.

- **Decision:** NEW.
- **Source:** product-plan §5 (AI-first portal, article deflection); architecture §6.8
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Of two articles with the same match, the one with higher helpfulness ranks first.
  2. An article promoted for "password reset" is the first result for that query.
  3. A promoted article the reader cannot read is not shown to them.

#### REQ-KB-057 — Semantic search

Knowledge search also finds articles by meaning, not only by words: articles are embedded and
stored in the vector index (architecture §5, §12), and results combine word and meaning
matches. It works with the local model on every deployment.

- **Decision:** BETTER. ServiceDesk Plus search is word matching only.
- **Source:** architecture §12 (retrieval), §7.3 (vector data); sdp-area-08 §Behaviour (suggestions match words only)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. "I can't get into my email from home" finds an article titled "Configure webmail access
     outside the office".
  2. Meaning matches respect visibility before ranking (REQ-KB-048).
  3. The feature passes its tests with the on-prem local model profile.

#### REQ-KB-058 — AI answers with citations

In the portal search, in the console search and in the chat assistant (file 10), a question
can get a short AI answer built only from published articles the user may read. Each answer
cites the articles it used, with links. If the articles do not answer the question, it says so
and offers the next step (in the portal: raise a request). Users rate answers, and the rating
is kept with the answer's sources. Unapproved and expired articles are never used.

- **Decision:** BETTER. Same capability as ServiceDesk Plus, on every deployment, with an
  honest "no answer".
- **Source:** sdp-area-10 §Behaviour (chat answer grounded on an approved solution with citation); product-plan §7.1 (grounded and cited), §7.2 (RAG answers in the portal); architecture §12
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. An answer about printer spoolers cites the article it used, and the link opens it.
  2. A question no article covers gets "no answer found" and a "raise a request" action in the
     portal.
  3. An unapproved article that matches is never used or cited.
  4. On an evaluation set, answers contain no step absent from the cited articles.

#### REQ-KB-059 — Knowledge summary for technicians on a record

On an incident or request, a technician can ask for a summary built from the most relevant
articles (and known errors, REQ-KB-042), with citations, to insert into a reply or resolution
after review.

- **Decision:** SAME. ServiceDesk Plus builds a curated summary from articles.
- **Source:** sdp-area-10 §Screens (predictive features: solution assist), §Fields (resolution assist); architecture §2.10 (resolution assist)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. The summary lists the articles it used, and each opens.
  2. The summary is inserted only when the technician accepts it.
  3. It uses only articles the technician may read.

#### REQ-KB-060 — Search analytics

Knowledge search records queries (without personal data), result counts, clicks and whether
the search ended in a request. Owners and knowledge managers see top queries, queries with no
results, queries with results nobody opened, and the articles found most.

- **Decision:** NEW.
- **Source:** product-plan §5 (article deflection analytics); architecture §2.8
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A query that returned no results appears in "no results" with its count within 15 minutes.
  2. The report never shows who searched.
  3. A "no results" query can be turned into a new article draft from the report.

#### REQ-KB-061 — External knowledge sources

Articles from connected outside sources (for example Confluence or SharePoint, connectors in
file 12) can be included in technician search, suggestions and AI answers, labelled with their
source. The outside source's permissions are applied for the user, or the source is limited
to chosen groups.

- **Decision:** NEW. ServiceDesk Plus has an unexplained "search from external sources" switch
  in its chatbot.
- **Source:** architecture §2.14 (Confluence and SharePoint knowledge sources); sdp-area-10 §Fields (chatbot customisation: external sources), §Weak spots
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A Confluence page the user may read appears in search with a "Confluence" label.
  2. A page the user may not read in Confluence is not shown.
  3. An AI answer citing an outside page links to it at its source.

---

## 10. Knowledge on records

#### REQ-KB-062 — One suggestion service for every entry point

One suggestion service gives matching articles to every place that needs them:

- the technician create form (REQ-INC-021);
- the portal report form (REQ-INC-028) and service request forms (file 02);
- the record page's knowledge panel;
- the chat assistant (file 10).

It matches on title, body, keywords, topic and, where given, category, service and CI
(REQ-KB-011). By default only published articles are suggested; a tenant setting can also
show in-progress articles to technicians, marked as such (REQ-KB-066). Suggestions never move
the form (REQ-WI-012).

- **Decision:** BETTER. Approved only by default, topic and category aware, the same results
  everywhere.
- **Source:** sdp-area-08 §Behaviour (suggested solutions panel), §Config (approved only in suggestions: off; hide suggestions on new request: off); sdp-area-02b §Screens; sdp-area-02c §Behaviour (banner shifts the form)
- **SDP weak spot fixed:** unapproved solutions are suggested by default, and the banner
  shifts the form so the first click misses.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. The same subject typed on the technician form and the portal form gives the same top
     three articles, filtered by each user's visibility.
  2. A draft article is never suggested to requesters, whatever the setting.
  3. With the tenant setting "no suggestions on the technician form", the panel is not shown
     there and still works in the portal.
  4. Suggestions appear within one second of the person pausing typing.

#### REQ-KB-063 — Search and insert from the editors

From the reply, note and resolution editors on any record, a technician searches knowledge with
the record's subject pre-filled, filters by topic and status, previews an article and then:

- inserts the content, keeping its formatting and images; or
- inserts a link that opens the article for the record's requester, if they may read it.

Inserting records the article as used on the record (REQ-KB-064).

- **Decision:** BETTER. Keeps formatting, and can send a link the requester can open.
- **Source:** sdp-area-08 §Behaviour (request to solution: copy to resolution pastes plain title and description), §Actions (resolution tab); REQ-INC-090; sdp-area-04 §Behaviour (problem search not pre-filled)
- **SDP weak spot fixed:** "copy to resolution" pastes plain "title / description" text, and
  the search from a problem starts empty.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Inserting an article with a numbered list and an image keeps both in the resolution.
  2. Inserting a link for a requester outside the article's audience warns the technician
     before sending.
  3. The search opens with the record's subject as its query.

#### REQ-KB-064 — Link articles to records

Articles can be linked to incidents, service requests, problems, changes and releases, by hand
or by inserting them. The record lists its articles; the article lists the records that
referred to it, counted by type. Both sides record the link in history (REQ-WI-003).

- **Decision:** SAME.
- **Source:** sdp-area-08 §Screens (associations tab; referred in problems, referred in requests), §Behaviour (referred solutions); REQ-PRB-035; architecture §2.15 (linking to tickets)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Linking KB-4 to INC-20 shows INC-20 under KB-4's referring records, live.
  2. The article's counters show referring records by type.
  3. A user who cannot see INC-20 sees the count but not the incident.

#### REQ-KB-065 — Reuse that is counted

When a record is resolved with an article linked or inserted, the article is counted as having
helped resolve it. Each article shows how many records it helped resolve. Knowledge managers
see the share of resolved records that used knowledge, per group and technician (REQ-KB-073).

- **Decision:** NEW. Measures whether knowledge is used, the core KCS measure.
- **Source:** product-plan §5 (KCS workflow), §7.4 (measure by outcomes)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Resolving INC-20 with KB-4 inserted increases KB-4's "helped resolve" count by one.
  2. Reopening INC-20 and resolving it again does not count twice.
  3. The share of resolved incidents with an article is reported per group.

#### REQ-KB-066 — Work-in-progress knowledge for technicians

Following KCS, a tenant can let technicians find and use articles that are still in review,
clearly marked "not yet approved", so new knowledge helps at once. Requesters never see them.
Using one on a record notifies its owner, as a signal to finish the review.

- **Decision:** BETTER. ServiceDesk Plus shows unapproved content in suggestions by default and
  without a marker; here it is opt-in and marked.
- **Source:** sdp-area-08 §Config (show only approved solutions: off), §Behaviour (unapproved solution suggested); architecture §6.1 (KCS workflow); product-plan §5 (KCS workflow)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. With the setting off (default), an article in review is not found by technicians outside
     its authors and approvers.
  2. With it on, the article is found with a "not yet approved" marker.
  3. A requester never sees it, with the setting on or off.

#### REQ-KB-067 — Forward and share an article

A technician can send an article by email to people they choose, with a short message, or copy
a link to it. The email holds the readable content for requesters (without technician-only
sections, REQ-KB-046). The person is warned before sending to someone outside the article's
audience. Sending is recorded on the article.

- **Decision:** SAME.
- **Source:** sdp-area-08 §Screens (detail toolbar: forward), §Limits (forward not used)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Forwarding to a requester sends the requester-visible content only.
  2. Forwarding to an address outside the audience shows a warning that must be confirmed.
  3. The article history lists the forward with sender and recipients.

#### REQ-KB-068 — Print and PDF

An article prints, and saves as PDF, with title, ID, version, published date and content, in
the reader's language and direction, without technician-only sections for requesters.

- **Decision:** SAME.
- **Source:** sdp-area-08 §Screens (detail toolbar: print)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. An Arabic article prints right to left.
  2. The PDF shows the version number and published date.

---

## 11. Feedback, comments and analytics

#### REQ-KB-069 — "Did this help?"

Every article asks readers whether it helped (yes or no). A "no" offers a short list of reasons
and an optional comment. Each person has one vote per article version and can change it.
Technicians see the helpful share and the vote counts; requesters see neither by default.
Votes from a version stay with that version; the article shows the current version's score
and the all-time score.

- **Decision:** BETTER. Votes per version replace one like and dislike count that an approver
  may reset on each approval.
- **Source:** sdp-area-08 §Screens (like and dislike buttons with counts), §Actions (reset likes and dislikes on approval), §Automation; architecture §2.15 (ratings)
- **SDP weak spot fixed:** likes and dislikes are reset by a checkbox ticked by default on
  every approval, losing the history.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A requester votes "no" with the reason "steps did not work"; the owner sees the vote and
     the reason.
  2. Voting twice on the same version changes the vote; it does not add a second one.
  3. Publishing a new version starts its score at zero and keeps the old version's score
     visible in its history.
  4. Counts update live on the article for technicians.

#### REQ-KB-070 — Feedback reaches the owner

A "no" vote with a comment, or a technician's "flag as wrong" from a record or the article,
creates a feedback item for the article's owner. The owner can reply (the reader is notified if
they asked), fix the article, or dismiss the item with a reason. Open feedback counts show in
"my articles" and content health (REQ-KB-037).

- **Decision:** NEW. ServiceDesk Plus collects likes but nothing reaches the author.
- **Source:** sdp-area-08 §Weak spots (no reporting on ratings); product-plan §5 (KCS workflow)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. "Flag as wrong" on KB-4 from INC-30 creates a feedback item for KB-4's owner that links to
     INC-30.
  2. Dismissing feedback needs a reason, recorded in history.
  3. A requester who asked for a reply gets one in the portal when the owner answers.

#### REQ-KB-071 — Comments on articles

Technicians can comment on an article; comments are internal by default and can be made
visible to requesters one by one. Requesters can comment if the tenant allows it. Comments
support mentions and are moderated: people with the moderate permission can hide or delete
them, with a reason. Comments are separate from the article's internal author note
(REQ-KB-001).

- **Decision:** SAME.
- **Source:** sdp-area-08 §Fields (internal comments; comment shown to requester), §Behaviour (internal comment with lock), §Config (do not allow requesters to add or edit comments); architecture §2.15 (comments)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. An internal comment is never returned to a requester by any API.
  2. With requester comments off, the portal shows no comment box and the API refuses them.
  3. A hidden comment shows "hidden by a moderator" to technicians, with the reason in history.

#### REQ-KB-072 — Usage figures on every article

Each article shows, for technicians:

- views, unique readers, and the split between technicians and requesters;
- helpful share (REQ-KB-069) and open feedback (REQ-KB-070);
- records it was linked to and helped resolve (REQ-KB-065);
- searches that led to it and deflections (REQ-KB-074).

Figures cover a chosen period, per translation and in total. A view is counted once per
reader per day.

- **Decision:** BETTER. ServiceDesk Plus shows a raw view counter that rises on every open.
- **Source:** sdp-area-08 §Screens (right panel: views), §Behaviour (views climbed with each open)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Opening an article five times in one day counts one view for that reader.
  2. The figures can be shown for the last 30 days and all time.
  3. View counts update live.

#### REQ-KB-073 — Knowledge reports and dashboard widgets

The report and dashboard builders (file 09) include knowledge data. Built-in reports cover:

- articles by status, type, topic, language and owner;
- due for review, expired and flagged articles;
- most viewed, most helpful and least helpful articles;
- articles created and published per author and per period;
- template use, search analytics (REQ-KB-060), reuse (REQ-KB-065) and deflection
  (REQ-KB-074);
- knowledge gaps (REQ-KB-075).

- **Decision:** SAME. ServiceDesk Plus has knowledge widgets and one report.
- **Source:** sdp-area-09 §Screens (widget modules: solutions; reports: solutions); sdp-area-08 §Weak spots (no reporting); product-plan §5 (deflection analytics)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A dashboard widget "articles due for review by owner" updates live when a review is done.
  2. Each built-in report can be filtered by topic and period.
  3. Report data respects article visibility for the viewer.

#### REQ-KB-074 — Self-service deflection

When a requester starting a request or incident in the portal opens a suggested article or an
AI answer, they are asked whether it solved their issue. "Yes" ends the form without a record
and counts as a deflection for the article. Leaving the form after reading an article without
submitting, within a set time, counts as a likely deflection.

- **Decision:** NEW. Deflection is the main value measure of self-service.
- **Source:** product-plan §5 (article deflection analytics), §7.4 (ticket deflection rate)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Answering "yes, solved" after reading KB-4 counts one deflection for KB-4 and creates no
     record.
  2. Confirmed and likely deflections are reported separately.
  3. The deflection rate per period is available as a report and a widget.

#### REQ-KB-075 — Knowledge gaps

A knowledge gap view lists where knowledge is missing:

- groups of resolved incidents and requests with similar subjects and no linked article;
- frequent searches with no results or no clicks (REQ-KB-060);
- categories with many records and few articles.

Each gap can be turned into an article draft or assigned to a person as a task.

- **Decision:** NEW.
- **Source:** product-plan §7.3 (knowledge author: flags knowledge gaps from repeated issues); product-plan §5 (KCS workflow)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Ten resolved incidents in one category with no article in 30 days appear as a gap.
  2. "Create draft" from a gap opens a draft pre-filled from the most typical resolution.
  3. A gap with a new linked article leaves the list.

#### REQ-KB-076 — Knowledge author agent

An AI agent (file 10) reviews resolved records on a schedule, drafts articles for repeated
issues without knowledge, proposes updates to articles that resolutions contradict, and
flags gaps. Every draft goes through the normal approval; the agent never publishes.

- **Decision:** NEW.
- **Source:** product-plan §7.3 (knowledge author agent); architecture §2.10, §12 (agents)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. Agent drafts are created as drafts with source "AI agent" and the source records linked.
  2. The agent cannot run the publish action; the API refuses it.
  3. Each run lists what it drafted and why, for the knowledge manager.

---

## 12. Lists, the article page and history

#### REQ-KB-077 — Knowledge list with topic tree and views

The knowledge area shows the topic tree beside the article list. The list has chosen columns,
sorting, a list or card layout, and built-in views:

- all published, my articles, my drafts, in review, awaiting my approval;
- due for review today, due within 15 days, review overdue, needs review (flagged);
- expired, withdrawn, archived, trash.

Custom views, sharing and favourites work as for records (REQ-INC-106, REQ-INC-107). Counts
and rows update live (REQ-WI-005).

- **Decision:** SAME.
- **Source:** sdp-area-08 §Screens (solutions list: topic tree, views, list/detail toggle, column chooser); sdp-area-01 §Screens (rail entry)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Selecting a topic shows its articles and those of its subtopics, with a switch to show
     only the topic's own.
  2. Approving an article moves it from "in review" to "all published" in another browser
     within one second.
  3. The views list can be searched by name.

#### REQ-KB-078 — Article page

The article page shows the ID, title, status and flags, topic path, type and language switch
in the header; the content; the "did this help" control; and fixed tabs (REQ-WI-011):
comments, links, versions, feedback, history. A side panel shows owner, dates, audience in
plain words, translations, views and referring record counts. Actions keep their place
(REQ-WI-010).

- **Decision:** BETTER. Tabs are fixed and the audience is written in plain words.
- **Source:** sdp-area-08 §Screens (solution detail page); REQ-WI-010; REQ-WI-011
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. All five tabs show on every article, empty or not, in the same order.
  2. The audience panel reads, for example, "technicians: Network group; requesters: none".
  3. A new comment by another user appears on the open page without a refresh.

#### REQ-KB-079 — Trash and restore

Deleting an article moves it, with its versions, translations, attachments and links, to the
trash for the retention period (REQ-WI-020). A restored article returns as withdrawn, so it
is not published again by accident. Only people with the delete permission can empty the
trash.

- **Decision:** SAME.
- **Source:** sdp-area-08 §Screens (views: trashed solutions; trashed topics); REQ-WI-020
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A deleted article no longer appears in search or suggestions and is listed in the trash.
  2. A restored article is withdrawn, with its versions and links intact.
  3. After the retention period, the article is purged and its ID is not reused.

#### REQ-KB-080 — History and audit

Every change to an article, its translations, its topic and its settings is in the article's
history with who, when, old and new values, source and reason (REQ-WI-003): content versions,
status changes, approvals and rejections, audience changes, owner changes, links, feedback
actions and views of restricted previews. Approving, publishing to requesters, audience
changes, deletion and settings changes are also written to the audit log (REQ-WI-021).

- **Decision:** BETTER. ServiceDesk Plus has a history tab; here audience and approval
  decisions are audited.
- **Source:** sdp-area-08 §Screens (history tab); architecture §7.4; REQ-WI-003; REQ-WI-021
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Changing an article's audience from technicians to all requesters writes a history entry
     and an audit log entry naming the person.
  2. History entries cannot be edited or deleted through any API.
  3. History can be filtered to approvals only.

---

## 13. Knowledge in the portal

#### REQ-KB-081 — Knowledge in the portal

The portal (shell in file 02) has a knowledge area where requesters:

- browse topics they have articles in (empty topics are hidden);
- search (REQ-KB-082) and read articles in their language, right to left where needed;
- see popular, recently updated and featured articles, and known issues (REQ-KB-041);
- vote on helpfulness (REQ-KB-069) and comment where allowed (REQ-KB-071).

The portal home has an entry to knowledge. A tenant can switch the knowledge area off for
requesters entirely. Everything updates live.

- **Decision:** SAME.
- **Source:** sdp-area-03 §Screens (portal: solutions in the left navigation, home "looking for solutions" card); sdp-area-08 §Config (do not show the solutions module to requesters), §Limits (requester view inferred); sdp-area-13 §Navigation & Footer Settings (requester view: solutions); architecture §2.15 (self-service portal: knowledge)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A requester sees only topics that hold at least one article they may read.
  2. With knowledge switched off for requesters, the portal shows no knowledge entry and the
     portal API refuses knowledge calls.
  3. An article published to the requester's site appears in the portal's "recently updated"
     list without a refresh.
  4. The knowledge area passes the accessibility checks (REQ-WI-023) in English and Arabic.

#### REQ-KB-082 — Knowledge in portal search

The portal's search covers knowledge together with the catalog, announcements and the
requester's own requests (file 02). Admins can switch knowledge results on or off and set
their order among the result groups. Known issues show first when they match.

- **Decision:** SAME.
- **Source:** sdp-area-03 §Config (portal search scope: announcements, solutions, request templates, requests, orderable); sdp-area-13 §Requester Portal (portal search)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A portal search for "vpn" shows matching articles in their own group, with the order the
     admin set.
  2. With knowledge results switched off, the portal search returns none.
  3. A matching known issue shows above other knowledge results.

#### REQ-KB-083 — From an article to a request

At the end of each portal article, "still need help?" starts a request or incident. The new
record is pre-filled with what the requester searched for and links to the articles they read,
so the technician knows what was tried.

- **Decision:** BETTER. Turns a failed self-help attempt into useful context for the
  technician.
- **Source:** sdp-area-03 §Screens (portal home cards); product-plan §5 (AI-first portal)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A request raised from KB-4's page shows KB-4 under "articles the requester read".
  2. The requester's last search text is in the new record's description, editable before
     submitting.

#### REQ-KB-084 — Follow an article

Requesters and technicians can follow an article or a known issue and get notified when a new
version is published, when it is withdrawn, or when a known issue is resolved. They can stop
following from the notification.

- **Decision:** NEW. ServiceDesk Plus has follow for announcements, not for solutions.
- **Source:** sdp-area-03 §Screens (announcements with a follow button)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A requester following a known issue is notified when it is marked resolved.
  2. A minor edit (REQ-KB-024) does not notify followers.
  3. A follower who loses access to the article gets no further notifications.

#### REQ-KB-085 — Public knowledge base without sign-in

A tenant can publish chosen articles to a public knowledge page that needs no sign-in, under
its portal domain, and choose whether search engines may index it. Only articles with the
"public" audience appear; attachments and links follow the same rule.

- **Decision:** NEW. A public help centre is common in tenders; ServiceDesk Plus did not show
  one in this area.
- **Source:** architecture §2.15 (branded portal, custom domain)
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. An anonymous visitor sees public articles only, and gets 404 for any other article ID.
  2. With indexing off, public pages tell search engines not to index them.
  3. Making an article public needs the publish-to-requesters permission and is audited.

---

## 14. Notifications, import, export and settings

#### REQ-KB-086 — Knowledge notifications with sensible defaults

Knowledge events notify the right people through the notification engine (file 03), in-app
and by email, in each recipient's language:

- submitted for review: the approvers;
- approved, rejected or published: the author;
- review due, review overdue, expiring: the owner (REQ-KB-036);
- flagged for review (REQ-KB-040), feedback and comments: the owner;
- mentions in comments: the person mentioned;
- followed article changed: the followers (REQ-KB-084).

Which are on by default is in Appendix A.

- **Decision:** BETTER. ServiceDesk Plus has a knowledge tab in notification rules, but review
  failed without mail.
- **Source:** sdp-area-12 §Screens (notification rules: solution tab); sdp-area-08 §Behaviour (submit for approval failed without mail)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. In a new tenant, submitting a draft notifies the topic's approvers in-app with no admin
     set-up.
  2. An Arabic-speaking author gets the rejection notice in Arabic.
  3. A notification never includes article text the recipient may not read.

#### REQ-KB-087 — Announce a new article

When publishing, an author with the announcement permission can also create an announcement
about the article for chosen audiences, linking to it. The announcement cannot reach people
outside the article's audience.

- **Decision:** SAME. ServiceDesk Plus has a "new knowledge entry" announcement type.
- **Source:** sdp-area-13 §Announcement and Maintenance (announcement types: new knowledge base entry); REQ-INC-129
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. "Announce" on publishing creates an announcement linked to the article.
  2. Choosing an announcement audience wider than the article's is refused with a reason.

#### REQ-KB-088 — Import articles

Articles can be imported in bulk from:

- CSV or Excel (one row per article, with topic path, keywords, audience and language);
- a package of HTML or Markdown files with their images.

Import runs as a background job with live progress (architecture §6.8). It starts with a field
mapping and a dry run that shows what will be created, updated or refused. Imported content is
sanitised (REQ-KB-006), and imported articles start as drafts unless the importer may publish
and chooses to.

- **Decision:** BETTER. Adds document packages, a dry run and sanitising.
- **Source:** sdp-area-14 §Screens (import wizard: solutions module, CSV/XLS/XLSX, modes, 3,000 record limit, sample file, import history); architecture §6.8 (imports)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A dry run of a 500-row file reports creates, updates and errors per row without saving
     anything.
  2. A script tag in an imported HTML file is removed before storage.
  3. Missing topics in the topic path are created, and listed in the import result.
  4. Import history keeps each job's file, who ran it and its results.

#### REQ-KB-089 — Export articles

Chosen articles, a topic, or the whole knowledge base can be exported as a package (HTML or
Markdown with attachments, plus a data file with fields, versions and translations), as a
background job. Export respects the exporter's visibility and needs the export permission.

- **Decision:** NEW. ServiceDesk Plus has no knowledge export in this area.
- **Source:** architecture §6.8 (exports), §2.15 (compliance: secure export)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Exporting a topic of 40 articles gives a package that re-imports into a new tenant with
     the same content and topic paths (REQ-KB-088).
  2. Articles the exporter cannot read are not in the package.
  3. The export is recorded in the audit log.

#### REQ-KB-090 — Knowledge settings on one page

All knowledge settings are on one admin page, each with a short explanation:

- ID prefix and starting number (REQ-KB-002);
- self-approval (REQ-KB-028) and work-in-progress knowledge (REQ-KB-066);
- suggestions on the technician form and in the portal (REQ-KB-062);
- requester comments (REQ-KB-071) and the portal knowledge area (REQ-KB-081);
- review intervals by type, reminder timing, content health thresholds and outside link checks
  (REQ-KB-034 to REQ-KB-038);
- quality checks that block or warn (REQ-KB-018);
- what happens to known issues when a known error is retired (REQ-KB-041).

- **Decision:** BETTER. ServiceDesk Plus spreads knowledge behaviour over the knowledge
  configuration, portal settings and per-article choices.
- **Source:** sdp-area-08 §Config; sdp-area-03 §Weak spots (portal settings split across three places)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Every setting named above is on the knowledge settings page, with its explanation.
  2. A changed setting takes effect without a restart and is recorded in the audit log.
  3. Each setting shows its default and can be reset to it.

#### REQ-KB-091 — Automation on knowledge events

Knowledge events (article submitted, published, withdrawn, expired, flagged, feedback
received) are available to business rules, workflows and webhooks (file 03, REQ-RUL-008,
REQ-WF-031), so tenants can, for example, open a task when an article gets three "no" votes in
a week.

- **Decision:** SAME. ServiceDesk Plus has no rule or workflow acting on solutions; this goes
  further.
- **Source:** sdp-area-08 §Automation (no business rule or workflow acts on solutions); architecture §6.5 (events)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A rule on "article published" in topic "Security" can notify a chosen group.
  2. A webhook subscribed to "article withdrawn" receives the article ID and version, and no
     content the subscriber is not allowed.

#### REQ-KB-092 — Knowledge on the mobile app

In the technician app, technicians search and read articles, see suggestions on a record, and
insert an article or its link into a reply or resolution. Approvers can approve or reject
articles from the app.

- **Decision:** SAME.
- **Source:** architecture §2.15 (mobile apps); REQ-INC-149
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Searching in the app returns the same results as the console for the same user.
  2. An approver can approve an article from a push notification, with the change view.

#### REQ-KB-093 — Knowledge from ServiceDesk Plus

The ServiceDesk Plus migration tool (architecture §18) brings over solutions as articles:
topics with their tree, titles, content (sanitised), keywords, attachments, review and expiry
dates, approval state, technician sharing and requester publishing mapped to audiences, likes
and dislikes as historic votes, comments and links to migrated records.

- **Decision:** NEW. Supports replacing ServiceDesk Plus.
- **Source:** architecture §18.2 (knowledge articles migrate automatically); product-plan §8 (migration path)
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. A migrated published solution shared with one technician group and two user groups arrives
     as a published article with the matching audiences.
  2. Links between migrated solutions and migrated requests are kept on both sides.
  3. The migration report lists every solution that could not be migrated, with the reason.

---

## Appendix A — Proposed defaults

These are the defaults a new tenant gets. They are seed data, not fixed behaviour: a tenant
admin can change every one of them (D-041). The requirements above refer to this appendix.

**Article IDs** (REQ-KB-002): prefix KB, first number 1.

**Article types, default templates and review intervals** (REQ-KB-008, REQ-KB-014,
REQ-KB-034):

| Type | Template sections | Review interval |
|---|---|---|
| how-to | purpose · before you start · steps · result | 12 months |
| troubleshooting | symptoms · cause · resolution · if it still fails | 12 months |
| FAQ | question · answer | 12 months |
| reference | overview · details | 24 months |
| policy | purpose · scope · policy · contacts | 12 months |
| workaround (Professional) | symptoms · workaround · linked problem (automatic) | 3 months |
| known issue (Professional) | what is affected · what you can do · status (automatic) | 1 month |

**Statuses** (REQ-KB-026): draft · in review · published · withdrawn · archived. Flags on a
published article: expired · needs review · scheduled · behind the source (translation).

**Approval** (REQ-KB-027, REQ-KB-028): one step; approvers are the topic owner and people
with the approve permission; self-approval allowed for people with the approve permission;
rejection needs a reason.

**Knowledge manager role** (REQ-KB-043): every knowledge permission, all topics. Technicians
get view, create, edit own and submit. Requesters get view of articles in their audience.

**Visibility** (REQ-KB-044, REQ-KB-045): a new topic is visible to all technicians and to no
requesters; a new article inherits its topic's audience.

**Suggestions and work in progress** (REQ-KB-062, REQ-KB-066): suggestions on in the
technician form and the portal; published articles only; work-in-progress knowledge for
technicians off.

**Review, expiry and reminders** (REQ-KB-034 to REQ-KB-036): reminder 14 days before review
and 14 days before expiry; overdue reminder 7 days after the review date, then weekly; owners
with more than 5 reminders in a day get one daily digest.

**Content health thresholds** (REQ-KB-037): not viewed for 180 days; helpful share under 40
percent with at least 10 votes; review overdue by more than 30 days.

**Link checks** (REQ-KB-038): links to articles and records checked on every change; outside
links not checked (the admin can turn on a weekly check).

**Quality checks** (REQ-KB-018): broken links and missing required fields block; missing alt
text, possible personal data and missing required translations warn.

**Workaround articles and known issues** (REQ-KB-040, REQ-KB-041): as file 04 Appendix A —
when a known error is retired, its portal known issue is withdrawn and its technician
workaround article is flagged for review.

**Feedback** (REQ-KB-069, REQ-KB-070): "did this help" on for technicians and requesters;
scores visible to technicians only; reasons for "no": outdated · incorrect · unclear · steps
did not work · not what I was looking for · other.

**Comments** (REQ-KB-071): technician comments on and internal by default; requester comments
off.

**Deflection** (REQ-KB-074): leaving the portal form within 30 minutes of reading a suggested
article, without submitting, counts as a likely deflection.

**Notifications on by default** (REQ-KB-086), in-app and email: submitted for review to the
approvers; approved, rejected and published to the author; review due, overdue and expiring to
the owner; flagged for review to the owner; negative feedback with a comment to the owner;
mention to the person mentioned. Off by default: comments to the owner, followed article
changes by email (in-app stays on).

**Other defaults:**

- topic tree depth: 6 levels (REQ-KB-003);
- attachment size: 25 MB per file, as file 01 (REQ-KB-007);
- trash retention: 30 days, as file 01 (REQ-KB-079);
- import limit: 10,000 rows per job (REQ-KB-088);
- languages required per topic: none (REQ-KB-049).

---

## Open questions for the product owner

1. **AI answers in the portal at MVP?** product-plan §7.2 puts RAG answers in the portal in
   Phase 1, but architecture §17 puts the AI gateway in Stage 2. Following architecture, we
   made AI answers and semantic search V1 (REQ-KB-057, REQ-KB-058). Should a limited version
   (cited answers from the local model) be MVP instead?
2. **Work-in-progress knowledge for technicians.** We propose that articles in review are
   hidden from other technicians by default, with an opt-in KCS setting (REQ-KB-066). Agree?
3. **Requester comments.** We propose requester comments off by default, with "did this help"
   and feedback as the requester's channel (REQ-KB-071). Agree?
4. **Feedback across versions.** We propose that votes belong to a version and a new version
   starts at zero, instead of an optional reset on approval (REQ-KB-069). Agree, or should
   scores carry over unless reset?
5. **Public knowledge base.** We put an unauthenticated public knowledge page at LATER and in
   Essentials (REQ-KB-085). Is that the right priority and edition?
6. **Multi-step knowledge approval edition.** Multi-step approval is Professional, because it
   uses the approval workflows sold there (REQ-KB-029). Should Essentials get two fixed steps
   without workflows?
7. **Outside link checks on-prem.** Checking outside links means outbound requests from the
   server. We propose it off by default everywhere, and turned on by the admin (REQ-KB-038).
   Agree?
8. **Article ID prefix.** We propose "KB" rather than the "SOL" style of ServiceDesk Plus
   (REQ-KB-002). Agree?
