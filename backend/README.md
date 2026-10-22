# backend

SupportX v2 Core API (FastAPI modular monolith) and workers. Python 3.12, managed with uv.
Layout and rules: architecture.md §6 and `CLAUDE.md`. The module contract and registry are in
`app/modules/README.md`.

```bash
make backend-env             # backend/.env from the dev stack's secrets (after make dev-init)
make backend-dev             # API with auto-reload on http://127.0.0.1:8000 (docs: /api/v1/docs)
make openapi                 # export the OpenAPI contract to frontend/packages/api-client
make db-migrate db-seed      # migrate the dev database, add the demo tenant (docs/dev-setup.md)
make db-guard                # tenant-isolation (RLS) check of every table
uv run pytest                # tests + coverage; -m db / -m integration select database tests
uv run ruff check . && uv run ruff format --check .
uv run mypy                  # strict
uv run lint-imports          # module boundary contracts
python -m app                # production-style entry point (uvicorn, no reload)
```

## Core pieces (WP-004)

| Where | What |
|---|---|
| `app/main.py` | `create_app()` factory and lifespan; discovers modules, never edited per module |
| `app/core/config.py` | `Settings` (pydantic-settings, `SUPPORTX_` env vars, profiles dev/test/production) |
| `app/core/errors.py` | RFC 9457 problem details, `AppError` hierarchy (`NotFound`, `Conflict`, ...) |
| `app/core/middleware.py` | request ID (X-Request-ID) + access log + 500 safety net; security headers |
| `app/core/logging.py` | structlog: JSON in production, console in dev, redaction of secrets/PII |
| `app/core/telemetry.py` | OpenTelemetry tracing; exporter off by default |
| `app/core/modules.py` | module registry (`ModuleSpec`) |
| `app/shared/ids.py`, `clock.py` | UUIDv7 IDs, `Clock` / `FrozenClock` |
| `app/modules/system` | `/api/v1/health` (liveness) and `/api/v1/ready` (PostgreSQL, Valkey, NATS) |
| `app/core/database.py` | engine (PgBouncer-safe), tenant/platform sessions, per-request unit of work |
| `app/core/tenancy.py` | `TenantContext`, tenant resolution (X-Tenant-ID in dev/test only) |
| `app/shared/db/` | `Base` + mixins, RLS SQL, generic `Repository`, display IDs |
| `migrations/` | Alembic (supportx_migrator, direct); `helpers.py` has `enable_tenant_rls` |
| `tooling/rls_guard.py` | tenant-isolation guard (`make db-guard`, CI) |

Tenant isolation is explained in `docs/architecture/tenancy.md`.
