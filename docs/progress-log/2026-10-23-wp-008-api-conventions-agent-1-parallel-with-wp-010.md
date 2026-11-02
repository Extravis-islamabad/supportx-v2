### 2026-10-23 — WP-008 API conventions (Agent 1, parallel with WP-010)
- Part A: D-023 (opentelemetry-exporter-prometheus + prometheus_client approved for WP-014),
  D-024 + CLAUDE.md §11 "Working rules" (no destructive git command without stash/commit first;
  same protection for data).
- `app/shared/api/`: `concurrency` (ETag from version, If-None-Match → 304, If-Match required:
  428 precondition_required / 409 version_conflict / 400 invalid_etag), `idempotency`
  (`idempotency_keys` table, claimed + stored in the request transaction, tenant+user scoped,
  24 h TTL, replay / 422 idempotency_key_reused / concurrent duplicates wait and replay),
  `filters` (JSON DSL with and/or groups, 13 operators + 10 relative-date operators, typed
  per-resource allowlist, limits, JSON-path errors, simple `?field=value` params, bound
  parameters only), `listing` (sort allowlist + id tie-breaker, keyset pagination with NULL
  handling, HMAC-signed cursors bound to endpoint/tenant/user/sort/filter, page envelope with
  capped `estimated_total`), `ratelimit` (Valkey fixed window per user + per tenant per route
  group, RateLimit-* headers, 429 + Retry-After, policy-provider hook for WP-009, fail open),
  `deprecation` (Deprecation/Sunset/Link, 12-month minimum), `openapi` (FilterExpression schema
  published; generated TS types). AppError now carries response headers; PreconditionRequired.
- Migration 0004: `idempotency_keys` (RLS), users.signature/time_zone, keyset indexes
  (tenant_id, field, id). Endpoints: GET /api/v1/users (filter/sort/cursor), GET /users/{id}
  (ETag/304), PATCH /users/{id} (own signature/time zone, If-Match, emits user.updated).
  Permissions: technicians list/read others; anyone reads self; only own preferences.
- `tooling/openapi_diff.py` + `make openapi-diff` + CI step against the target branch (recursive,
  additive-aware; also catches renamed schemas). Fixed WP-007 event checker: a class docstring
  edit was wrongly reported as breaking.
- Labels: 10 problem codes + 22 field-error codes (en/ar); label test now also checks
  `errors.field.*`. CI backend job gains a Valkey service; Valkey tests are required in CI.
- Tests: 500+ backend (unit: DSL grammar/limits/injection, cursors, sorting, ETags; HTTP + real
  PostgreSQL: users API, idempotency incl. 10 concurrent duplicates, rate limits on real Valkey).
  Filter compile 0.2 ms (30 conditions); 100k-row filtered list p50 5.7-7.5 ms over HTTP.
- Follow-ups: cleanup job for expired `idempotency_keys`; API-token subject for rate limits once
  API keys exist; entitlement-based rate-limit provider (WP-009); user time zone for relative
  dates; 409 "what changed" needs field history (§7.4); a permission policy layer (none exists
  yet; the users service checks user_type directly).
