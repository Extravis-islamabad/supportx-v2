# ADR-047: Field access per role — hidden, masked or read-only fields, compiled with the subject

- **Status:** Accepted (WP-046a S7; coordinator 2026-11-14 after lanes B and C reviewed r2)
- **Deciders:** Haider (Product Owner), through the coordinator; lane B reviews (blocking, D-149);
  lane C reviews the UI and owns the analytics slice
- **Related:** REQ-WI-016, REQ-ADM-026, D-164 (cost rights), D-171 and ADR-052 (erasure and
  export), WP-057 S3b (SEC-040 field encryption, AUD-017 view log), ADR-046 (salts), §11.2

## Context (survey of main d430b2b71)

- `identity_access` has `FieldRule(permission, hide|mask)` + `visible()`, used only by USERS.
  Work items never call it.
- Work items have two hand-written gates: `HIDDEN_WITHOUT = {"root_cause": "view_root_cause"}`
  (record, history) and `MONEY_FIELDS` masked without `view_costs` (history).
- Everything else goes out unfiltered: `WorkItemOut.custom`, `WorkItemListItem.custom`, history
  old/new values, type detail endpoints, report fields (`WorkItemSource` = FIELDS + type +
  custom, checked by `<type>.view` only), and the filter/sort allowlist (`list_dependency` /
  `lists.allowed_fields` take no subject).
- Search is Postgres FTS over `search_vector` = subject + description + `custom_text` (all custom
  free text). So a hidden custom value is findable by its words today.
- Realtime and 409 bodies carry changed field *names* (never values), not filtered per viewer.
- Custom field definitions (`metadata.CustomField`) have no sensitive or personal-data flag.
- Writes: `update()` computes the `sent` field set; type PATCHes (change/release details, risk,
  plan) and `set_fields` / `automated_update` bypass it. All end in `_update()`, which has no
  subject.

## Decision

1. **Rules.** A tenant rule is (role, record type, field, mode). The modes are `hidden`, `masked` and
   `read_only`. `hidden` and `masked` imply read-only (you can't write what you can't see).
   - **Table:** `role_field_access` in `identity_access`, with tenant_id first, RLS plus the RLS
     test, a `version` (If-Match), and an audit entry with before and after on every change.
   - **Cap:** at most 2,000 rules per tenant (a 422 `limit_reached` over that).
   - **Field catalogue:** it comes from the owning module through a port, so identity_access never
     knows work-item fields. Each module registers the **rule-able** fields per type: custom
     fields, plus a fixed list of built-ins (costs, root cause, change financials/risk notes,
     release downtime, etc.).
   - **Not rule-able:** the core fields subject, description, status, priority, requester, group
     and assignee. Hiding those breaks lists, search, notifications and SLAs.
2. **Several roles: the clearest mode wins** (clear > read_only > masked > hidden), matching
   additive grants. A restriction holds only if *every* role the person has carries it.
   - **Effective access view:** the API and the editor show, per field, who sees it in clear,
     read-only, masked or hidden. This is computed from the same compile as the Subject, not a
     second implementation. A test asserts they agree.
   - **Docs:** the admin guide states the rule plainly ("one role without the rule shows the
     field").
3. **One compile, every subject kind.** `FieldAccess` is compiled into `Subject.field_access` =
   {type: {field: mode}}, for every subject kind: browser sessions, mobile sessions and API-key
   subjects (public API). A test covers an API key whose role hides a field.
   - A rule change emits `identity_access.field_access.changed`, which is added to the authz
     consumer's `TRIGGERS`. A test proves a rule change hides the field on the person's **next
     request**, with no sign-out (as for role changes).
   - The existing root_cause and view_costs gates become built-in rules in the same structure: no
     permission → hidden or masked. This makes one mechanism, named `FieldAccess` to avoid the
     clash with the template `FieldRule`.
4. **One read choke point.** `work_items.service.redact(view, access)` runs inside the service:
   `get`, `list_page`, search, lookup, trash, type details and history. Routers can't forget it.
   - **Typed schemas stay valid.** Hidden and masked values both come back as `null`. The record
     carries `hidden_fields: [...]` and `masked_fields: [...]`, and the UI shows "not shown to
     you" or "masked". No sentinel string ever goes into a number, date or choice field. The same
     applies to history entries: hidden entries are dropped, and masked ones have null old and
     new values plus `masked: true`.
   - This replaces the `MASK` string for work items.
5. **Filters, sorts, reports, exports, dashboards.** `fields_for(subject, type)` drops hidden and
   masked fields from the allowlist (AC2).
   - **Interactive reports, dashboards and exports** are compiled with the *viewer's* subject. A
     field that isn't allowed gives `measure_not_permitted` / `field_not_permitted`, never a
     silent blank. `list_dependency` and `lists.allowed_fields` take the subject.
   - **Scheduled reports mailed to recipients (lane C's analytics slice, shape agreed
     2026-11-13).** `run_schedule` already renders each recipient's file as that recipient
     (`requested_by=user_id`), so the recipient's field access applies through the compiler.
     - **Owner side:** at run start the definition is also checked against the *owner's* field
       access. If the owner may no longer see a field the report uses, the run stops and the
       schedule pauses with the outcome `field_not_permitted`, shown like `owner_not_allowed`.
     - **Recipient side:** a `field_not_permitted` from a recipient's compile means that recipient
       is *skipped*, not failed, and counted in the run's outcome. The owner gets one notice per
       run listing who was skipped and the field labels, with no values. The notice is not
       locked (lane B: it tells the owner about their own report and carries no security fact).
   - **Refusals on screen:** a dashboard widget whose query is refused shows "not available to
     you" in place of the chart, never a blank or zero. Exports refuse the same way.
   - **Caching:** analytics has no cross-viewer result cache today. Any future result cache must
     be keyed by the viewer's field-access fingerprint. Realtime dashboard events carry IDs only,
     so they are unchanged.
6. **Search fails closed.** A custom field that has any rule is kept out of `custom_text`.
   - Adding the first rule to a field, or removing its last one, sets a per-type
     `custom_text_rebuilding` flag. While the flag is on, search **ignores `custom_text` for that
     type for everyone**: fewer matches for a while, never a leak.
   - A per-tenant background job rebuilds `custom_text`, batched with progress, then clears the
     flag. The admin notice says "search on custom text for <type> is paused until the rebuild
     finishes".
7. **Live events and 409s.** Publications go to shared channels, so they can't vary per viewer.
   On the record channel and on **every list channel**, any rule-able field in `changed_fields`
   becomes the generic name `restricted`, and the client refetches (§8.3). A 409 body lists only
   the fields the caller may see.
8. **Writes.**
   - **Person writes:** `require_writable(subject, type, fields)` runs in `update()` (on `sent`),
     in `create`, in bulk (a per-item failure), and in every type-specific PATCH/PUT. A refused
     write is a 403 `field_read_only` with params {field}.
   - **System writes** under no person's subject (automation, escalations, workflow
     UPDATE_FIELDS under the workflow's own subject, approvals) stay allowed.
   - **Rule (not just UI):** a workflow, business rule, automation or template that *copies or
     references* a field is an admin-configured path. Saving one is refused (422
     `field_not_permitted`) when it references a field the saving admin can't see in clear. The
     check is server-side in the designer's save API.
9. **The audit and lifecycle viewer (lane B's).** `audit.view` holders see restricted old and new
   values in clear, as auditors must. Each view of an entry that carries a restricted field's
   value is itself recorded (who, which entry, when; no value).
   - The work-item history tab, which isn't the audit viewer, follows §4.
10. **AI.** AI sources take the person's `FieldAccess`. Today they send only subject, description
    and the timeline, none of which is rule-able, so nothing changes now.
    - The rule: a restricted field never goes into a shared summary cache or the embeddings.
    - A test proves that a restricted custom field never reaches the gateway.
11. **Notifications.** The template variable catalogue refuses rule-able fields. Rendering per
    recipient is out of scope, and no such variables exist today.
12. **Portal.** It is unchanged: the requester sees only what the template's `requester_can_see`
    allows (already an allowlist). Role rules are staff-side.
13. **Licensing.** This is Professional (`has_feature("field_access")`). Existing rules **always
    apply**: a lapse never exposes data.
    - When the feature is lapsed, the editor still lets an admin **view and remove** rules
    (audited, as the admin's informed choice). Adding or changing a rule needs the feature.
14. **Metadata flags (REQ-ADM-026 AC2).** A custom field gets two flags (metadata is lane A's;
    lane B blocks the flags). **Neither flag creates a field access rule.**
    - **`sensitive`:** its values are encrypted at rest (SEC-040). Turning it on or off for a
      field that already holds values starts a background re-seal or un-seal job with progress,
      never a silent switch, and the field reads through both paths until the job is done. See
      WP-057 S3b (lane C).
    - **`personal_data`:**
      - each view is logged (AUD-017, into the audit module's `personal_data_access`);
      - the field takes part in erasure and export (D-171, ADR-052): on records the person
        requested, its values are blanked with the requester's other personal text (D2a,
        through ADR-046's salts), and the export includes them;
      - on other people's records, the mentions report searches `personal_data` fields first.
    - **Masking stays here:** WP-057 S3b uses this ADR as its only masking mechanism. Its
      decryption (`open_custom`) and its view-log hook are called from §4's redaction point, so
      a hidden or masked value is never decrypted.

## Delivery (S7, one migration)

- **Migration:** `role_field_access`, the CustomField flags and the per-type
  `custom_text_rebuilding` flag.
- **Slice a:** the policy part (table, API, effective-access view, compile, cache trigger). The
  cache and trigger diff goes to lane B early.
- **Slice b:** redaction and the write checks in work_items, the designer save checks, search fail
  closed, and live renaming. Tests per AC:
  - API, list, history, search, reports, export, live events, AI and API key;
  - the next-request test;
  - a 10k-list timing check.
- **Lane C's analytics slice (§5):** owner check and schedule pause, recipients skipped with the
  owner notice, and the "not available to you" widget state. It comes after slice a ships
  `fields_for(subject, type)` and after lane C's S2b-2.
- **Slice c:** the role editor's "field access" tab plus the effective-access view. The PR plan
  goes to lane C first, then the UI for their review.
- **Lane B builds §9:** the audit viewer's clear-with-record, in a small PR after slice a ships
  the compiled FieldAccess and the rule-able field catalogue port.
- **Lane B blocks:** slice a in full, plus slice b's write checks and search fail-closed.

## Implementation note (slice a)

`Subject.extra` is not part of the subject's cache form (`to_dict`/`from_dict`), so field access
is a real `Subject.field_access` field, cached with the rest; a subject cached before it existed
reads as having none, which is safe because no rule exists before the first one bumps the
generation. Rule changes call `access_changed(session)` (stale right after commit in the process
that made them) and emit `identity_access.field_access.changed` (the authz consumer, every other
process; the realtime route tells the role's holders to refetch).

Slice a's catalogue offers each work item type's custom fields in use; built-in fields (root cause,
costs, change and release figures) join in slice b with their enforcement, so no field is offered
before the server protects it. Until slice b lands, rules are stored, compiled and cached but no
read path applies them yet; the editor UI (slice c) comes after slice b, so no admin meets a rule
that does nothing.
