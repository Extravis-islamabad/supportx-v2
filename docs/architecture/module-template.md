# Module template: building a business module the SupportX way

Copy this checklist when you start a module (WP-012, ADR-024, D-032). The **announcements**
module is the worked example: every step names the file to copy from. There is no generator on
purpose: read the example, copy what you need, keep the shape.

```
backend/app/modules/<module>/
  __init__.py        ModuleSpec: routers, events, permissions, feature, channels, realtime
  domain/            pure rules: statuses, actions, validation (no I/O)
  infra/models.py    tables (SQLAlchemy), matching the migration
  service/           use cases: permission + scope, rule, write, history, event (one transaction)
  service/realtime.py who may join which channel; which events reach which screens
  api/routes.py      HTTP only: schemas, dependencies, status codes (no business logic)
  events.py          event contracts (IDs and field names only)
  tests/             domain tests without I/O
backend/migrations/versions/NNNN_<module>.py
backend/tests/db/test_<module>_api.py          real PostgreSQL + Valkey
frontend/packages/api-client/src/<module>.ts   hooks on the generated schema
frontend/apps/console/src/pages/<module>/      list, record, form, history
frontend/e2e/tests/<module>.spec.ts            two browsers, who sees what, axe
```

## 1. Decide before you code

- [ ] The module is one of architecture.md §6.1, or an ADR adds it (ADR-024 added
  announcements). Name its licence feature (`incident` here) and its permissions
  (`<module>.view`, `.manage`, extra actions such as `.publish`), with the scopes each may be
  granted at and the built-in role defaults (`PermissionSpec(..., defaults=(("technician",
  "all"),))`). See `announcements/__init__.py`.
- [ ] Write the status flow as a table: status → {action → status}, plus the order the UI shows
  the actions in. Which actions take a reason?
- [ ] Who may see a record: owner columns (own), the site / group link (site, group), and what
  non-staff may see (here: only what is live for them, everything else is 404).

## 2. Database (migration)

Copy `migrations/versions/0009_announcements.py`.

- [ ] `TenantEntity` columns (UUIDv7 `id`, `tenant_id`, `created_*`, `updated_*`, `version`,
  `deleted_at`); a human `display_id` from `next_display_id(session, "ANN")`.
- [ ] Codes as short strings with CHECK constraints (`status IN (...)`), lengths checked in the
  database too, cross-field rules where cheap (`publish_until > publish_from`).
- [ ] Every foreign key to another tenant table is **same-tenant**: `(tenant_id, x_id)` →
  `(tenant_id, id)`.
- [ ] Indexes start with `tenant_id`; one per sortable list field `(tenant_id, field, id)`.
- [ ] `enable_tenant_rls(table)` and the narrowest `grant_app(...)` (link tables need no UPDATE;
  history is insert-only).
- [ ] Reversible `downgrade()`. `make db-guard` passes (the RLS guard lists every table).

## 3. Domain (pure Python)

Copy `domain/announcement.py` and its tests.

- [ ] Enums for every code (`StrEnum`); the class name becomes the OpenAPI schema name, so make
  it specific (`AnnouncementStatus`, not `Status`).
- [ ] `StatusMachine({...}, order=tuple(Action))` from `app/shared/domain`; never set a status by
  editing a field.
- [ ] Rules return **codes** (`["audience_empty"]`), not messages. Time-based state is computed
  from the clock (`visibility(status, window, now)`), with `next_change(...)` for live screens.

## 4. Service (one transaction per write)

Copy `service/announcements.py`. Each write does, in order:

1. permission and **scope** (`authorize_stored`, `scope_filter` from identity_access); a record
   the user may not see is 404;
2. validation → `ValidationFailed` with `FieldError(field="body.x", code="...")` written out
   literally (the label check scans for the codes);
3. the change through `Repository.update(..., expected_version=...)`; on `Conflict` raise
   `explain_conflict(...)` (who changed what);
4. the scope check **again** after the change (nobody moves a record out of their own reach);
5. `record_changes(...)` (field history, with `source_of(request)` and the optional reason);
6. `record_event(...)` with an event from `events.py`.

Also:
- [ ] A view object for the API with the **action states** (every action, allowed or the reason
  it is not) and `can_manage`, so the UI never guesses permissions.
- [ ] A no-op save returns the record unchanged: no new version, no event.
- [ ] Cross-module data only through the other module's package root (`existing_unit_ids`,
  `user_names`); import-linter enforces it.

## 5. API

Copy `api/routes.py`.

- [ ] Router with `rate_limit("<module>")` and shared `responses` (ProblemDetail models).
- [ ] Every route declares access: `require_permission(...)` or `require_signed_in()`.
- [ ] List: `list_query(FIELDS)` (filter DSL, sort, cursor) and a named `Page` model; static
  paths (`/feed`, `/trash`, `/settings`) before `/{id}`.
- [ ] Create: `Idempotency` + `Created(body, headers={"Location", "ETag"})`, status 201.
- [ ] Update and actions: `ExpectedVersion` (If-Match, 428 without it) and `set_etag`.
- [ ] Pass `source_of(request)` to the service. Bodies use `extra="forbid"`.
- [ ] `make openapi` regenerates `openapi.json` and the TypeScript schema.

## 6. Events and realtime

Copy `events.py` and `service/realtime.py`.

- [ ] One event per kind of change; payload = IDs, status codes, changed field **names**.
- [ ] Channels: `LiveList("<module>", VIEW).spec()` for lists and a record `ChannelSpec` whose
  `authorize` uses the policy layer (presence for staff).
- [ ] Routes: record channel + list audiences (`LIST.publications(..., sites=, groups=,
  owners=)`). Audiences you cannot name (everyone a record is addressed to) get an **ID-free**
  tenant broadcast, sent only when something they could see changed.
- [ ] `make events-schemas` updates `docs/architecture/event-schemas.json`.

## 7. Labels (en, ar, ur)

All in `frontend/packages/labels/src/resources/{en,ar,ur}.ts`; the backend tests fail on any
missing key.

- [ ] `nav.<module>`, every enum value (`<prefix>.<code>`, prefixes in
  `tests/test_enum_labels.py`), `errors.<code>` and `errors.field.<code>`,
  `event_type.<type>`, `permission.<key>` + `.description`, `permission_module.<module>`,
  `action_reason.<code>` for every disabled-action or refusal reason, field names for history
  and conflicts (`<entity>.field.<name>`).
- [ ] Urdu for every new string (D-033). Check RTL wording does not use direction arrows.

## 8. Frontend

Copy `packages/api-client/src/announcements.ts` and `apps/console/src/pages/announcements/`.

- [ ] Hooks only on the generated types; query keys in `keys.ts`; writes send If-Match and keep
  the ETag; create sends one Idempotency-Key per form (a retry reuses it).
- [ ] List: `useListChannel` + `refreshList`/`refreshRecord`; `useRefetchAfter` when content
  changes by the clock.
- [ ] Record: `useRecordChannel` (presence + "changed by" notice while editing, silent refresh
  otherwise), actions in fixed order and disabled with a tooltip reason, History tab,
  `ConflictDialog error={...} fieldLabel={...}`.
- [ ] Forms: `FormField` + Zod (`schema` in a plain `.ts` file), `applyServerErrors`.
- [ ] Dates and times: always `DateTimeField` / `DateTimeRangeField` from `@supportx/ui` (D-035),
  never a native date input or a bare DatePicker. Form values stay ISO instants; the field shows
  and takes them in the user's profile time zone and says which zone.
- [ ] People pickers (owner, assignee): a searchable `Select` fed by a module endpoint that lists
  only users holding the needed permission (`PolicyService.holders`), with the current value
  passed as `include` so it is shown by name; the service refuses anyone else
  (`user_holds`, field error code `<field>_not_allowed`). Example: announcement owner.
- [ ] Nav item with `feature` and `permissions`; routes lazily loaded.
- [ ] Vitest: list labels and filter DSL, action order and reasons, 409 text.

## 9. Tests that prove the rules

Copy `tests/db/test_announcements_api.py` and `frontend/e2e/tests/announcements.spec.ts`.

- [ ] RLS: tenant B never reads or writes tenant A (API 404, list, feed, channel).
- [ ] Each scope (all, site, group, own) and the built-in roles; writes cannot leave the scope.
- [ ] ETag/428/409 with who changed what; idempotent create replay; validation codes.
- [ ] Every allowed and refused status move; reasons in the history; history paging.
- [ ] Licence: no plan → 403 `entitlement_required`; read-only plan → reads work, writes 403.
- [ ] Realtime routes: who gets which message, and that private changes send nothing wide.
- [ ] Performance: a filtered list on 10,000+ rows, p95 printed and asserted.
- [ ] e2e: two browsers live, the 409, every audience, no raw codes, axe in light, dark and RTL;
  suite records named "E2E …" and removed by `tooling/e2e_fixtures.py`.

## 10. Finish

- [ ] `make check` (it runs `CI=true pnpm install --frozen-lockfile` first) and the e2e suite.
- [ ] An import-linter `layers` contract for the module (`api > service > infra > domain`).
- [ ] ADR if you decided something architectural; PROGRESS.md session log.
