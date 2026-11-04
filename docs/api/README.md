# The SupportX API

Everything the SupportX screens do goes through this API (REQ-WI-018): there is no private
interface behind the console. It is a REST API under `/api/v1`, described by an OpenAPI 3.1
contract generated from the code.

- **Contract:** `GET /api/v1/openapi.json` on your installation, also published with each release.
  Each operation lists the scope an API key needs (`x-scopes`).
- **Authentication:** an API key (`Authorization: Bearer sxk_…`): see [keys.md](keys.md). The
  screens use a browser session instead.

## Versions

Changes within `/api/v1` only add: new operations, new optional fields, new values. Removing or
renaming anything needs a new major version (`/api/v2`), and a CI check refuses such a change on
`/api/v1`. An operation being retired answers with `Deprecation` and `Sunset` headers (and a
`Link` to its replacement) for at least 12 months before it goes. Until the first external release
(the pilot), changes that an approved decision requires are still listed in
`docs/architecture/openapi-accepted-breaks.json` (D-095).

## Safe writes

- **Creating:** send an `Idempotency-Key` header (any unique string, for example a UUID). A retry
  with the same key and the same body returns the first answer and creates nothing more; the same
  key with a different body is refused (422 `idempotency_key_reused`). Keys are kept 24 hours.
- **Changing:** read the record first and send its version back as `If-Match` (the `ETag`). If
  someone changed it since, the answer is 409 `version_conflict`, naming the fields that changed.

## Lists

- **Paging:** cursor-based. Each page answers `next_cursor` and `has_more`; send `cursor` for the
  next page. Records created while you page never make you see an existing record twice.
- **Page size:** `limit`, up to the list's maximum (usually 200). A larger value is reduced to the
  maximum and the answer says so in the header `X-Page-Size-Capped: <maximum>`.
- **Filters:** simple query parameters for common cases, and the shared JSON filter language in
  `filter`: a filter saved in the screens can be sent unchanged and returns the same rows.
- **Sorting:** `sort=field` or `sort=-field` (descending), up to three fields.

## Errors

Every error is an RFC 9457 problem: `status`, a stable machine `code`, `params` for the message,
and `errors` with one entry per invalid field (`field`, `code`). Codes never change meaning within
a major version; there is never a stack trace or an internal name in an answer.

```json
{
  "type": "urn:supportx:problem:validation_failed",
  "status": 422,
  "code": "validation_failed",
  "params": {},
  "errors": [{ "field": "body.subject", "code": "missing", "message_key": "errors.missing" }]
}
```

The list of codes with their English text: `make api-errors` writes it to
`docs/_build/api/errors.md` from the same labels the screens use.

## Rate limits

Calls are counted per user (or key) and per organisation. Every answer carries
`RateLimit-Limit`, `RateLimit-Remaining` and `RateLimit-Reset`; over the limit, 429 with
`Retry-After`.
