### 2026-10-23 — WP-004 backend application core
- Housekeeping: PR #7 was already merged; Dependabot PR #3 (jsdom 27 → 30) rebased, all checks
  green, merged; D-019 (uvicorn, structlog, uuid-utils, OpenTelemetry) recorded via PR #8.
- Settings (`app/core/config.py`): pydantic-settings, `SUPPORTX_` env vars + `backend/.env`,
  profiles dev/test/production (production requires every backing-service URL), secrets as
  `SecretStr`. `make backend-env` writes `backend/.env` from the dev stack's secrets.
- App factory + lifespan (`app/main.py`), `python -m app` entry point, `make backend-dev`
  (uvicorn, reload, 127.0.0.1:8000). Module registry (`app/core/modules.py`, `ModuleSpec`):
  modules are discovered from `app/modules/`, so main.py never changes; documented in
  `app/modules/README.md`. Example `system` module (ADR-018) with `/api/v1/health` and
  `/api/v1/ready` (PostgreSQL via PgBouncer, Valkey, NATS; concurrent, 2 s timeout, reason codes).
- RFC 9457 problem details with `code`, `message_key`, `params`, field `errors`, `request_id`;
  `AppError` hierarchy; framework 404/405/422 mapped; unhandled exceptions → generic 500.
  Request-ID and security-header ASGI middleware. structlog JSON/console logging with request_id,
  tenant_id placeholder, trace/span IDs and redaction. OpenTelemetry FastAPI instrumentation,
  exporter `none` by default (`console` opt-in). UUIDv7 `new_id()` and `Clock`/`FrozenClock`.
- OpenAPI 3.1 export to `frontend/packages/api-client/openapi.json` (`make openapi`); drift check
  runs in `make backend-lint` and therefore in CI. Error codes have en/ar labels (CI test).
- Frontend: Vite proxies `/api` → 127.0.0.1:8000 in console and portal; console home shows a live
  API status tag (TanStack Query, 10 s poll) with labels in en/ar/ur. Verified in Chrome: green
  "API online", then red "API offline" without refresh after stopping the API.
- Tests: backend 97 (2 dev-stack integration tests skip automatically when the stack is down),
  coverage ≥ 96%; frontend 24. The integration test found that PgBouncer reports a bad password as
  a protocol violation; the probe now maps it to `auth_failed`.
- New runtime deps (D-019 + D-004): uvicorn, structlog, uuid-utils, opentelemetry-api/-sdk,
  opentelemetry-instrumentation-fastapi, pydantic-settings, asyncpg. Official client SDKs (named
  for veto): valkey (valkey-py, MIT), nats-py (Apache-2.0). Dev: asyncpg-stubs (BSD-3, D-012).
  Frontend: @tanstack/react-query (listed stack).
- Follow-ups: field-level error labels (`errors.field.*`) arrive with i18next in WP-010; the API
  client generation from openapi.json is WP-010; OTLP exporter when the observability stack lands.
