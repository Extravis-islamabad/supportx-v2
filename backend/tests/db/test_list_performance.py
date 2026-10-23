"""Filtered list query on 100,000 users in a throwaway database (WP-008 performance report).

The rows belong to a fresh tenant of the session's throwaway database, so they are invisible to
every other test (RLS) and dropped with the database. Timings are printed; set
SUPPORTX_PERF_REPORT=<file> to also write them as JSON. The assertion is a loose sanity bound.
"""

import json
import os
import statistics
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.tenancy import SESSION_RESOLVER_STATE
from app.main import create_app
from conftest import create_tenant, make_settings
from tests.db.test_users_api import fake_session
from tooling.db_testing import ThrowawayDatabase

if TYPE_CHECKING:
    from fastapi import FastAPI

pytestmark = pytest.mark.db
ROWS = 100_000
RUNS = 20

SEED = """
INSERT INTO users (id, tenant_id, external_subject, email, display_name, user_type, status,
                   locale, created_at, updated_at, last_login_at)
SELECT gen_random_uuid(), $1, 'sub-' || n, 'user' || n || '@perf.test',
       'User ' || lpad(n::text, 6, '0'),
       CASE WHEN n % 10 = 0 THEN 'technician' ELSE 'requester' END,
       CASE WHEN n % 50 = 0 THEN 'disabled' ELSE 'active' END,
       (ARRAY['en', 'ar', 'ur'])[1 + n % 3],
       now() - (n || ' minutes')::interval, now(),
       CASE WHEN n % 4 = 0 THEN NULL ELSE now() - ((n % 90) || ' days')::interval END
FROM generate_series(1, $2) AS n
"""

QUERIES = {
    "technicians_active_recent_login": {
        "filter": json.dumps(
            {
                "and": [
                    {"field": "user_type", "op": "eq", "value": "technician"},
                    {"field": "status", "op": "eq", "value": "active"},
                    {"field": "last_login_at", "op": "last_n_days", "value": 30},
                ]
            }
        ),
        "sort": "-last_login_at",
    },
    "name_contains_text": {
        "filter": json.dumps({"field": "display_name", "op": "contains", "value": "0042"}),
    },
    "simple_params_arabic_sorted_by_created": {"locale": "ar", "sort": "-created_at"},
    "or_group_with_in_list": {
        "filter": json.dumps(
            {
                "or": [
                    {"field": "email", "op": "starts_with", "value": "user9999"},
                    {"field": "locale", "op": "in", "value": ["ur"]},
                ]
            }
        ),
        "sort": "display_name",
    },
}


def write_report(results: dict[str, dict[str, float | int]]) -> None:
    if target := os.environ.get("SUPPORTX_PERF_REPORT"):
        path = Path(target)
        existing = json.loads(path.read_text()) if path.is_file() else {}
        existing["list_100k"] = results
        path.write_text(json.dumps(existing, indent=2))


async def test_filtered_list_on_100k_rows(
    migrated_db: ThrowawayDatabase, capsys: pytest.CaptureFixture[str]
) -> None:
    tenant = await create_tenant(migrated_db.migrator_url, "Perf")
    tech = uuid.uuid4()
    conn = await asyncpg.connect(migrated_db.admin_url)
    try:
        await conn.execute(SEED, tenant, ROWS)
        await conn.execute(
            "INSERT INTO users (id, tenant_id, external_subject, email, display_name, user_type)"
            " VALUES ($1, $2, 'sub-perf-tech', 'tech@perf.test', 'Perf Tech', 'technician')",
            tech,
            tenant,
        )
        await conn.execute("ANALYZE users")
    finally:
        await conn.close()

    app: FastAPI = create_app(make_settings(database_url=migrated_db.app_url))
    headers = {"X-Test-Tenant": str(tenant), "X-Test-User": str(tech)}
    results: dict[str, dict[str, float | int]] = {}
    async with app.router.lifespan_context(app):
        setattr(app.state, SESSION_RESOLVER_STATE, fake_session)
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            for name, params in QUERIES.items():
                timings, second_page = [], []
                for _ in range(RUNS):
                    started = time.perf_counter()
                    response = await client.get(
                        "/api/v1/users", params={**params, "limit": 50}, headers=headers
                    )
                    timings.append((time.perf_counter() - started) * 1000)
                    assert response.status_code == 200, response.text
                    body = response.json()
                    if body["next_cursor"]:
                        started = time.perf_counter()
                        page2 = await client.get(
                            "/api/v1/users",
                            params={**params, "limit": 50, "cursor": body["next_cursor"]},
                            headers=headers,
                        )
                        second_page.append((time.perf_counter() - started) * 1000)
                        assert page2.status_code == 200
                results[name] = {
                    "rows_in_tenant": ROWS + 1,
                    "page_items": len(body["items"]),
                    "p50_ms": round(statistics.median(timings), 1),
                    "max_ms": round(max(timings), 1),
                    "page2_p50_ms": round(statistics.median(second_page), 1) if second_page else 0,
                }
    with capsys.disabled():
        for name, values in results.items():
            print(f"\n[perf] list_100k {name}: " + ", ".join(f"{k}={v}" for k, v in values.items()))  # noqa: T201
    write_report(results)
    assert all(r["p50_ms"] < 1000 for r in results.values()), results
