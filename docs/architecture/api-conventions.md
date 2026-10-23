# API conventions

WP-008. Rules: architecture.md §6.5 and §10, CLAUDE.md rules g (optimistic concurrency) and d
(labels), ADR-020. Code: `backend/app/shared/api/`. Reference endpoints that use every
convention: `GET /api/v1/users`, `GET /api/v1/users/{id}`, `PATCH /api/v1/users/{id}`
(`backend/app/modules/identity_access/api/routes.py`).

| Convention | Header / parameter | Error code | Code |
|---|---|---|---|
| Optimistic concurrency | `ETag` on single records; `If-Match` on PATCH/PUT/DELETE; `If-None-Match` on GET | 428 `precondition_required`, 409 `version_conflict`, 400 `invalid_etag` | `concurrency.py` |
| Idempotent creates | `Idempotency-Key` on POST; replay sets `Idempotent-Replayed: true` | 422 `idempotency_key_reused`, 400 `invalid_idempotency_key` | `idempotency.py` |
| Cursor pagination | `limit`, `cursor`, `include_total`; body `items`, `next_cursor`, `has_more`, `estimated_total` | 400 `invalid_cursor`, 422 `invalid_page_size` | `listing.py` |
| Filtering | `filter=<JSON>` (the DSL) and simple `?field=value` | 422 `invalid_filter` (field error says where) | `filters.py` |
| Sorting | `sort=-created_at,display_name` | 422 `invalid_sort` | `listing.py` |
| Rate limiting | `RateLimit-Limit`, `-Remaining`, `-Reset`, `-Policy`; `Retry-After` on 429 | 429 `rate_limited` | `ratelimit.py` |
| Deprecation | `Deprecation`, `Sunset`, `Link: rel="deprecation"` | — | `deprecation.py` |
| Contract stability | OpenAPI export + breaking-change check against the target branch | CI fails | `tooling/openapi_diff.py` |

Every error is RFC 9457 problem details with a stable `code`; the UI shows
`errors.<code>` (and `errors.field.<code>` for field errors) through the labels package.

## 1. Optimistic concurrency (ETag / If-Match)

Every editable record has an integer `version`. Its ETag is that version: `"7"`.

```http
GET /api/v1/users/0191...            → 200   ETag: "7"
GET /api/v1/users/0191...            If-None-Match: "7"   → 304 (no body)
PATCH /api/v1/users/0191...          If-Match: "7"   {"signature": "Regards"}   → 200   ETag: "8"
PATCH /api/v1/users/0191...          (no If-Match)   → 428 precondition_required
PATCH /api/v1/users/0191...          If-Match: "7"   (someone saved first)   → 409 version_conflict
```

The 409 body carries `params: {"expected_version": 7, "current_version": 8}`; the client reloads
and shows what changed. `If-Match: *` is refused: it would mean "overwrite whatever is there".

Records with field history (WP-012, `app/shared/history`) explain the 409 from it: `params` also
has `changed_fields` (comma-separated field codes, labelled by the UI), `changed_by` (display
names) and `changed_at` (ISO time of the last save). Services call
`explain_conflict(session, error, record_type=..., record_id=..., names=...)` on a version
conflict; `<ConflictDialog error={...} fieldLabel={...}>` shows it.

**Client headers.** The console and portal send `X-SupportX-Client: console|portal` (history
records the source `ui`; anything else is `api`) and `X-Time-Zone` (the user's profile zone, else
the browser's): calendar filters such as `today` and `this_week` use the user's days (an unknown
zone falls back to UTC).

## 2. Idempotency-Key on POST

Clients send a random key (a UUID) per *intended* create and reuse it when retrying.

```http
POST /api/v1/things   Idempotency-Key: 4f0c…   {"title": "Printer jam"}   → 201 (created)
POST /api/v1/things   Idempotency-Key: 4f0c…   {"title": "Printer jam"}   → 201, same body, Idempotent-Replayed: true
POST /api/v1/things   Idempotency-Key: 4f0c…   {"title": "Other"}         → 422 idempotency_key_reused
```

- Keys belong to (tenant, user): another user's identical key is a different key.
- They live 24 hours (`SUPPORTX_IDEMPOTENCY_TTL_HOURS`).
- The key and the created record are saved in **one database transaction**. A crash rolls back
  both, so a retry simply runs again. Ten identical requests at once create one record: the
  others wait for the first and get its response.
- A failed request (4xx/5xx raised by the operation) stores nothing, so it can be retried.

## 3. Cursor pagination

```http
GET /api/v1/users?limit=25
→ {"items": [...25], "next_cursor": "eyJ2Ijox….Qk3x…", "has_more": true, "estimated_total": null}
GET /api/v1/users?limit=25&cursor=eyJ2Ijox….Qk3x…
```

- `limit`: default 50, maximum 200 (`SUPPORTX_PAGE_SIZE_DEFAULT`, `_MAX`). Outside 1..200 → 422.
- Pages are "rows after the last one I saw" (keyset), not OFFSET: new rows never shift later pages,
  and page 1,000 costs the same as page 1.
- Cursors are opaque and signed. They only work for the same endpoint, tenant, user, sort and
  filter. An edited, forged or borrowed cursor → 400 `invalid_cursor`.
- `include_total=true` adds `estimated_total`: matches counted up to 10,000 (10,000 means "at
  least"). Leave it off for fast lists.

## 4. Filter DSL

One JSON grammar, reused later by list views, reports, business rules and SLAs. A node is a
condition or a group:

```json
{"field": "status", "op": "eq", "value": "active"}
{"and": [ <node>, <node>, ... ]}
{"or":  [ <node>, <node>, ... ]}
```

| Field type | Operators |
|---|---|
| string | eq, ne, in, not_in, contains, starts_with, is_null, is_not_null |
| enum, uuid | eq, ne, in, not_in, is_null, is_not_null |
| datetime | eq, ne, in, not_in, gt, gte, lt, lte, between, is_null, is_not_null, today, yesterday, this_week, last_week, this_month, last_month, last_n_days (value: days), next_n_days, before_now, after_now |
| integer | eq, ne, in, not_in, gt, gte, lt, lte, between, is_null, is_not_null |
| boolean | eq, ne, is_null, is_not_null |

- `in`/`not_in` take a list, `between` takes `[low, high]`, null checks and relative dates take no
  value (`last_n_days`/`next_n_days` take a number of days). Relative dates are UTC; weeks start
  on Monday.
- `ne` and `not_in` also match rows where the field is empty ("not X" includes "nothing").
- `contains`/`starts_with` are case-insensitive; `%` and `_` in the value are literal characters.
- Only fields in the endpoint's allowlist can be used, each with its type. Unknown fields,
  operators that don't fit the type, wrong value types and unknown keys are refused.
- Limits: 8,000 characters, 5 levels of nesting, 30 conditions, 100 values per list, 200
  characters per string.
- Errors point at the problem:
  `422 invalid_filter`, `errors: [{"field": "filter.and[1].or[0].op", "code": "operator_not_allowed", ...}]`.
- The JSON is compiled to SQLAlchemy expressions with bound parameters only. User input never
  becomes SQL text.
- The schema is published in OpenAPI as `FilterExpression` (types in `packages/api-client`).

**Simple parameters** cover common cases without JSON: `?status=active` is `eq`, and
`?locale=ar&locale=en` is `in`. They are combined with `filter` using AND. Date fields are DSL-only.
Unknown parameters are refused (422 `unknown_parameter`), so typos never silently return everything.

Examples (from the tests, on `GET /api/v1/users`):

```text
filter={"and":[{"field":"user_type","op":"eq","value":"technician"},
               {"or":[{"field":"last_login_at","op":"last_n_days","value":7},
                      {"field":"email","op":"starts_with","value":"aisha"}]}]}
  → technicians who signed in this week, or whose email starts with "aisha"

?user_type=technician&status=active&sort=-display_name
  → active technicians, Z→A

filter={"field":"display_name","op":"contains","value":"'; DROP TABLE users; --"}
  → 200 with no items: the text is a value, nothing else
```

## 5. Sorting

`sort=-last_login_at,display_name`: up to three fields from the endpoint's sortable list, `-` for
descending. The record ID is always added as the last key, so the order is total and cursors are
exact. Empty values sort as the largest (last ascending, first descending).

## 6. Rate limiting

Each route group has a budget per user (or API token, once those exist) and per tenant, per
window (default 60 s). Settings: `SUPPORTX_RATE_LIMITS='{"default":{"user":600,"tenant":6000},
"users":{"user":300}}'`, `SUPPORTX_RATE_LIMIT_WINDOW_SECONDS`. Responses carry the tighter budget:

```http
RateLimit-Limit: 300   RateLimit-Remaining: 297   RateLimit-Reset: 41   RateLimit-Policy: 300;w=60
429 rate_limited   Retry-After: 41
```

Budgets come from a policy provider. Higher limits per licence tier will plug in through the
entitlement interface (WP-009) without changing endpoints. If Valkey is down, requests are
allowed and a warning is logged.

## 7. Deprecation

```python
OLD = Deprecation(since=date(2026, 11, 1), sunset=date(2027, 11, 1), link="https://…/migration")
@router.get("/old", deprecated=True, dependencies=[OLD.dependency])
```

This sends `Deprecation: @<unix time>`, `Sunset: <HTTP date>` and `Link: <…>; rel="deprecation"`.
A sunset less than 12 months after deprecation is refused (§10).

## 8. Contract stability

`make openapi` exports `openapi.json` and regenerates the TypeScript types. CI fails if the file
is stale (`openapi-check`). It also fails when `openapi.json` breaks the target branch's copy
(`make openapi-diff base=…`). Breaking means:
- an operation or parameter removed;
- a new required parameter or body field;
- a type changed;
- a response field removed or made optional;
- a named schema removed or renamed.

Breaking changes go to `/api/v2`.

## Checklist: building a new list / detail / update endpoint

**Resource definition (service layer)**
- [ ] Declare `ResourceFields` with only the fields users may filter/sort on, each with its type
  (enum fields list their codes). Never expose internal columns (`tenant_id`, secrets, subjects).
- [ ] Every sortable field has an index `(tenant_id, field, id)` in the migration.

**List endpoint**
- [ ] `query: Annotated[ListQuery, Depends(list_query(MY_FIELDS))]`, then
  `await paginate(session, select(Model).where(Model.deleted_at.is_(None)), query)` in the service.
- [ ] Return a named page model: `class ThingPage(Page[ThingDetail])`.

**Detail endpoint**
- [ ] `set_etag(response, entity.version)`; return `not_modified(request, entity.version)` when it
  is not None.

**Update / delete**
- [ ] Take `version: ExpectedVersion`.
- [ ] Update through `Repository.update(..., expected_version=version)`.
- [ ] Set the new ETag on the response.
- [ ] Reject fields the caller may not change (`extra="forbid"` on the body model).

**Create**
- [ ] Take `idempotency: Idempotency` and return `await idempotency.run(body, operation)`.
- [ ] Keep `response_model=` on the route.
- [ ] Return `Created(body, headers={"Location": ...})`.

**Every endpoint**
- [ ] Permissions are checked in the service, never in the router.
- [ ] Each state change records its event in the same transaction (`record_event`).
- [ ] Router-level `dependencies=[Depends(rate_limit("<group>"))]`.

**Labels and contract**
- [ ] New error codes have `errors.<code>` labels (en, ar); new field-error codes have
  `errors.field.<code>`. `tests/test_error_labels.py` enforces both.
- [ ] Run `make openapi` and commit `openapi.json` + `schema.ts`.

**Tests**
- [ ] Filter/sort/cursor/ETag/If-Match/permission tests over HTTP against real PostgreSQL. Use
  `tests/db/test_users_api.py` as the template.
