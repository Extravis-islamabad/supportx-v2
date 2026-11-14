# ADR-052: Person erasure and data-subject export — one resumable job per person, a port every module implements

- **Status:** Proposed (lane B, 2026-11-13; the plan approved as D-171 by Haider through the
  coordinator)
- **Deciders:** Haider (Product Owner), through the coordinator
- **Related:** D-171 (what is kept and what goes), REQ-ADM-100 (export), REQ-ADM-101 (erasure),
  REQ-ADM-105 (legal hold), ADR-046 (salted personal fields and `audit_erase_subject`), WP-064
  (lifecycle audit, record-level holds later), audit gap #12

## Context

Erasing a person (GDPR art. 17) and handing them their data (art. 15/20) touch every module:
identity, organisation, work items, assets, knowledge, analytics, notifications, mail, files,
audit. Before this ADR nothing emitted `user.status_changed` with reason `erasure`, so the
consumers that already react to it never ran, `audit.erase_subject` was never called, there was
no legal hold, and no per-person export. A one-shot transaction cannot do it: Keycloak and mail are
outside the database, the work is large, and a failure half-way must neither expose a
half-erased person nor be skipped.

## Decision

### 1. Who and when (D-171)

- Rights `people.erase`, `people.export`, `audit.manage_holds`: tenant administrators only (the
  built-in tenant_admin role; a custom role may hold them, with a warning in the role editor).
- **Two people.** Admin A **requests** (person, reason code + text, successor for shared objects,
  files to keep with a reason each); a **different** admin B **approves**. Both need RecentAuth
  and type the person's display name. A request expires after 7 days. Every step is audited:
  `person.erasure_requested / approved / rejected / expired / completed / failed`.
- **Refused** (a labelled 409/422 at request, approval and job start): yourself; the last active
  tenant admin; break-glass accounts; a person under legal hold; an erasure already open.
- **The mentions report (D-171 a)** is shown to the approver (S1b, §4a). Approval is refused
  with `erasure_report_unavailable` while the report is missing or incomplete, and with
  `erasure_report_not_reviewed` until the approving admin has reviewed it themselves.

### 2. Legal hold (H1)

`users.legal_hold_at / legal_hold_by / legal_hold_reason`, set and lifted under
`audit.manage_holds`, each audited. One check, `legal_hold.person_held(session, user_id)`, refuses
erasure at request, approval and job start. WP-064 S3 extends the same check with record-level
holds; ports then skip held records (see §4). Until then there are no record-level holds to
skip: the person-level check is the whole hold, and it fails closed.

### 3. The job

- Table `person_erasures` (tenant, RLS forced): `id, person_id, state, step, attempts,
  requested_by/at, approved_by/at, reason_code, reason_text, successor_id, keep_files (jsonb: file
  id → reason), last_error_code, report (jsonb, S1b), version`. States: `requested → approved →
  running → done`, or `rejected`, `expired`, `failed` (resumable). One open erasure per person
  (partial unique index).
- Runner: a schedule in the workers (every 30 s) that picks up approved and unfinished erasures,
  so a run a crashed worker left is resumed without a separate sweep; it also expires requests
  older than 7 days. Each
  **step** is idempotent, commits its own progress (`step`), and is retried with backoff; a run
  resumes at the recorded step. `last_error_code` holds a code, never a message with data.
- **Steps, in order** (the order is the contract; the person is never half-visible):
  0. **Re-check**: hold, last admin, approval still valid.
  1. **Freeze**: status disabled, `can_sign_in` false, all sessions ended (store + realtime +
     Keycloak logout through ADR-051's path), API keys revoked, invite and action links cleared.
  2. **Mail**: `app.shared.mail.forget_recipient(email)` while the address still exists.
  3. **Keycloak** (D5): `remove_member` from the tenant's organisation; `delete_user` only when
     `member_tenants` is then empty. Unreachable → retry, never skip.
  4. **Module ports** (§4), in registry order.
  5. **The person row**: names → "Erased person <code>" (D6b, a stable 4-character code from the
     ID, not reversible to anything personal), email → `erased-<id>@invalid`, `external_subject`
     null, phone, mobile, job title, employee ID, description, signature, manager cleared,
     preferences reset, `erased_at / erased_by` set. The row stays: IDs everywhere point at it.
  6. **Audit**: `audit.erase_subject(person)` (ADR-046: personal values blanked, salt destroyed →
     "erased on request"), then `audit_erase_profile_history(person)` (0164, a migrator-owned
     definer function): values and reasons of their own profile history (record type `user`)
     blanked, only once step 5 set `users.erased_at`, so it can never blank a live person's.
  7. **Event**: `user.status_changed {status: disabled, reason: erasure}` for the consumers that
     already react to it, then `person.erasure_completed`.

### 4. The port contract (every module that holds person data)

```python
class PersonData(Protocol):
    module: ClassVar[str]          # registry key: "work_items", or "work_items.references"
    order: ClassVar[int]           # within a band (below)
    kinds: ClassVar[frozenset[str]]  # the count kinds it returns, each labelled

    async def erase_person(
        self, session: AsyncSession, person_id: UUID, *, successor_id: UUID,
        keep_files: Mapping[UUID, str], now: datetime, cursor: str | None,
    ) -> ErasureBatch: ...         # one bounded batch; see "Batches" below

@dataclass(frozen=True)
class ErasureBatch:
    counts: Mapping[str, int]      # by kind, never data
    cursor: str | None             # None: this module is done; else call again with it

    async def export_person(
        self, session: AsyncSession, person_id: UUID, out: ExportWriter,
    ) -> Mapping[str, int]: ...    # streams; counts by kind

class ExportWriter(Protocol):      # lane C's review: never a whole section in memory
    def record(self, kind: str, data: Mapping[str, object]) -> None: ...  # one JSON line
    def file(self, file_id: UUID) -> None: ...  # an upload to include (copied once, deduped)

register_person_data(impl)         # identity_access's registry, at module import
```

**Order bands** (lane C): `100–199` references (lists, recipients, memberships), `500–599` owned
objects and personal rows, `900–999` derived data (AI summaries and embeddings), so derived data is
removed after the text it came from is blanked. A module picks a number inside its band.

**Keys, kinds and errors** (lane A): a module with work in two bands registers one port per band
under `<module>.<part>` (e.g. `work_items.references` in 100s, `work_items.owned` in 500s);
`REQUIRED_PORTS` lists keys. A port declares the count kinds it returns; each has a label
`erasure_count.<kind>` in en/ar/ur (tested), and the job refuses an undeclared kind
(`erasure_port_kind_undeclared`). A port raises `ErasureStepFailed(code)` for a failure it can
name: retried, and only the code is recorded.

**Batches** (lane A): a person with tens of thousands of records cannot be erased in one
transaction. Each call does at most `ERASE_BATCH` rows (500) and returns a cursor; the runner
commits, stores the cursor in the erasure's progress, and calls again in a fresh transaction
until the cursor is None, then moves to the next port. Every batch is idempotent on its own, so a
resumed run repeats at most one batch harmlessly.

**Export records** use stable keys (codes, never labels) and each section carries a
`schema_version`, so `index.html` labels them in en/ar/ur and a later export stays comparable.

Rules every implementation follows (each owner proves them with a DB test: erase, a second call is
a no-op, other people untouched, another tenant untouched, held records untouched once WP-064 S3
lands):

- **Tenant session, RLS.** Called in the job's tenant session; never cross-tenant.
- **Idempotent.** A second call changes nothing and returns zero counts.
- **Private data deleted**: the person's views, list settings, reminders, timers, drafts,
  favourites, preferences, follows, votes, private templates.
- **References removed** (band 100–199): the person in followers, watchers, approver and
  recipient lists, rule recipients, schedule recipients, and their address in
  `work_items.notify_emails` (people kept informed).
- **Shared objects they own → `successor_id`** (D4): reports, dashboards, workflows, boards,
  shared templates, KB topics, asset ownership. Never deleted, never left orphaned. The successor
  is required at request; if they are no longer active at job start, the approving admin is the
  successor instead, named in the erasure's record (lane C's review).
- **A transferred thing that acts with its owner's rights** (a scheduled report, a workflow, a
  connector or rule that **runs as** the person, WP-055) is **paused** on transfer (outcome `owner_changed`); the successor resumes it after looking,
  since its permissions are now theirs (ADR-047 §5's owner check).
- **Derived data** (AI summaries and embeddings of records they requested, their prompts) is
  deleted in the derived band, after the text it came from is blanked.
- **Text they wrote on organisation records stays** (D1a), shown with the erased name.
- **Open records assigned to them** (lane A): go back to their group's unassigned queue
  (technician cleared, history source "erasure"), not to the successor, since an assignee must
  be in the record's group (D-154). Closed records keep the erased name.
- **Records they requested** (D2a): the requester's personal free text (subject, description,
  custom text, `personal_data` custom fields, answers) is replaced by the reserved marker
  `erased_on_request` (shown through labels as "Removed at the person's request"; a required
  field keeps a valid value; search and AI skip it), with a version bump so open editors get a
  409. Technicians' replies stay. The record's **field history** of those values is blanked by
  step 6 (`audit.erase_subject`, ADR-046: the requester is the history's data subject), so ports
  never rewrite history themselves.
- **Files they uploaded are deleted** (D-171 b) unless their ID is in `keep_files` (kept with the
  admin's reason, audited per file by the job). Shared files service: `files.forget_uploader`.
- **Costs** (D3a): rates deleted, worklog amounts kept.
- **Mail block rules** naming their address as sender **stay unchanged**: the tenant's own
  security control (legitimate interest); an erasure never lifts a block (the coordinator,
  2026-11-14).
- **No data in counts, logs or errors.** Counts by kind only; failures raise a coded error.
- **No events that name the person**; ordinary change events (IDs, changed fields) as for any
  change, so screens follow live.

Owners (S2): identity_access, organization, audit, files, mail, assets, action links, list
settings: lane B. work_items, notifications (#492 done), integrations, automation, sla: lane A.
knowledge, analytics, announcements, ai (consumer done): lane C. The registry refuses to start
the job while a module listed in `REQUIRED_PORTS` has not registered (a missing port is a
release defect, never a silent skip).

### 4a. The mentions report and redaction (S1b, D-171 a)

- **Port contract.** A module whose text other people write may name the person implements
  `PersonMentions` (person_data.py) under its registry key, beside or on its erasure port:
  `find_mentions(session, person_id, *, terms, cursor) -> MentionBatch` (at most
  `MENTION_BATCH` = 500 rows per call; mentions are `(record_type, record_id, field,
  match_kind name|email|phone, occurrences)`, **never a snippet or any text**);
  `redact_mention(session, mention, *, terms, marker, now) -> bool` (only the matched
  occurrences of that kind in that one field become the reserved code `erased_on_request`, the
  record's version goes up, history names the field only with old/new null and reason
  `erasure_redaction`, the record's ordinary change event); `passage(session, subject, mention)
  -> str | None` (the field's current text when the caller's own rights let them read the
  record). Terms (`MentionTerms`: display name and first + last, the e-mail, phone and mobile as
  digits) are rebuilt from the person's row when needed and never stored.
- **Required ports.** `REQUIRED_MENTION_PORTS` (one place) names identity_access, files and assets
  (built in S1b) and S2's work_items.references, work_items.owned, integrations, knowledge and
  announcements. A report is `complete` only when every required key ran, so until S2 no report
  is complete and approval stays refused in practice.
- **Build.** While an erasure is requested, the 30 s erasure schedule runs every registered
  mentions port in key order, one batch per transaction, progress (port and cursor) in
  `report.building`. Rows go to `person_erasure_mentions` (migration 0164; one per place and
  kind; states found, redacted, left). The finished `report` is `{complete, by_module: {key:
  {kind: count}}, ports_done, ports_missing, attachment_content_searched: false, building:
  null}`. A port registered later runs on the next tick, and the review then lapses.
- **Review.** `POST /erasures/{id}/report/reviewed` (`people.erase`, RecentAuth, If-Match,
  audited `person.erasure_report_reviewed`) sets `report_reviewed_at/by`; approval needs the
  approver's own review (a review by anyone else does not count), and
  approval leaves the mentions still found as `left`. The job's step 0 still refuses an
  incomplete report.
- **Reading.** `GET /erasures/{id}/mentions` lists places and counts (cursor pages, never
  text); `GET /erasures/{id}/mentions/{mention_id}/passage` returns the current text through
  the owning port (404 when the caller may not read the record), each view audited
  `person.erasure_mention_viewed` with IDs only.
- **Redaction** needs the same read rights as the passage: a mention of a record the admin may
  not read refuses the whole request (404). `POST /erasures/{id}/mentions/redact` (`people.erase`, RecentAuth, If-Match on
  the erasure, at most 200 mention IDs; requested or approved, never once the job runs): each
  through its port, the row marked redacted, an audit entry `person.erasure_mention_redacted`
  per mention (IDs only). A mention of another erasure refuses the whole request (404).
- **Attachment contents are not searched,** only file names and details: the report and the
  mentions list carry `attachment_content_searched: false`, shown with the label
  `people_erasure.attachment_content_not_searched`.
- **History of a redacted field** (0164, `history_redact_field(mention)`, a migrator-owned
  definer function; the app role has no UPDATE on `field_changes`): it takes only a mention ID
  and blanks old/new values of the record and field that *redacted* mention row names, in the
  caller's tenant, so no caller can point it at another field. Rows a fingerprinted audit entry
  commits to (ADR-046: work items, assets) are **kept**, since blanking them would read as
  tampering; the mention's `history_kept` counts them and the screen says so
  (`people_erasure.history_kept_fingerprinted`). Blanking those needs the pre-blank field
  digests kept and a `redacted_on_request` verifier status: a follow-up before the work-item
  mention ports register (lane C agreed, 2026-11-14). D-171 keeps no redacted original, so
  until then an erasure with a kept row is **refused** at approval and at job start
  (`erasure_signed_history_kept`; the coordinator, 2026-11-14).

### 5. Export (REQ-ADM-100)

`people.export`, RecentAuth, audited; the existing export-job pattern (queued job, file in object
storage, single-use download link, 7 days). A ZIP: `person.json`, one JSON per module from
`export_person`, `index.html` (a readable summary, en/ar/ur), and the files they uploaded. Offered
as "export first" before an erasure is requested.

### 6. Requests from the person

A starter catalog item "Personal data request (export or erasure)" (lane A) creates an ordinary
request for admins; there is no self-service erase (D7).

### 7. Export and field access (ADR-047)

Erasure is a system job and ignores field-access rules. The export gives the person their **own**
data in full, `personal_data` custom fields included, even where a role rule hides a field from
staff. **Open, for Haider:** whether other people's *private notes about* the person are exported
(a legal call); until decided they are not.

## Consequences

- One place decides the order and resumes after failures; modules only implement their slice.
- A module that adds person data must add it to its port, or its DB test fails (each port's test
  seeds its tables).
- Erasure is not undoable: the job writes nothing that could restore the person, and the audit
  shows "erased on request".
- Mentions in other people's text (D-171 a) are handled by the report and redaction (S1b, §4a),
  not by the erasure ports; until S2's mentions ports land, approval is refused.
- Keycloak accounts shared with other tenants survive (D5); only this tenant's membership goes.
