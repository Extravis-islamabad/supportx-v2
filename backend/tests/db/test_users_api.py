"""GET/PATCH /api/v1/users over HTTP: every WP-008 convention on a real endpoint.

Real PostgreSQL (throwaway database, RLS on); the session is faked by a resolver that reads
X-Test-Tenant / X-Test-User, so each test can act as any user of any tenant.
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event

from app.core.tenancy import SESSION_RESOLVER_STATE, TenantContext
from app.main import create_app
from conftest import create_tenant, make_settings
from tooling.db_testing import ThrowawayDatabase

pytestmark = pytest.mark.db

BASE = datetime(2026, 1, 1, tzinfo=UTC)


async def fake_session(request: Request) -> TenantContext | None:
    tenant = request.headers.get("x-test-tenant")
    user = request.headers.get("x-test-user")
    if tenant is None:
        return None
    return TenantContext(uuid.UUID(tenant), uuid.UUID(user) if user else None)


@dataclass
class Directory:
    """A tenant with a technician, a requester and `count` more users."""

    client: AsyncClient
    db: ThrowawayDatabase
    tenant: uuid.UUID
    tech: uuid.UUID
    requester: uuid.UUID
    app: FastAPI

    def as_(self, user: uuid.UUID | None = None, tenant: uuid.UUID | None = None) -> dict[str, str]:
        headers = {"X-Test-Tenant": str(tenant or self.tenant)}
        if user is not None:
            headers["X-Test-User"] = str(user)
        return headers

    async def get(self, path: str, user: uuid.UUID | None = None, **kw: Any) -> httpx.Response:  # noqa: ANN401
        headers = {**self.as_(user or self.tech), **kw.pop("headers", {})}
        return await self.client.get(path, headers=headers, **kw)

    async def list(self, user: uuid.UUID | None = None, **params: Any) -> httpx.Response:  # noqa: ANN401
        return await self.get("/api/v1/users", user, params=params)


async def seed_users(
    db: ThrowawayDatabase, tenant: uuid.UUID, rows: list[dict[str, Any]]
) -> list[uuid.UUID]:
    conn = await asyncpg.connect(db.admin_url)
    try:
        ids = []
        for i, row in enumerate(rows):
            user_id = row.get("id", uuid.uuid4())
            await conn.execute(
                "INSERT INTO users (id, tenant_id, external_subject, email, display_name,"
                " user_type, status, locale, created_at, updated_at, last_login_at)"
                " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $9, $10)",
                user_id,
                tenant,
                f"sub-{user_id}",
                row.get("email", f"u{i}-{user_id.hex[:6]}@demo.test"),
                row.get("display_name", f"User {i:03d}"),
                row.get("user_type", "requester"),
                row.get("status", "active"),
                row.get("locale", "en"),
                row.get("created_at", BASE + timedelta(minutes=i)),
                row.get("last_login_at"),
            )
            ids.append(user_id)
        return ids
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def directory(migrated_db: ThrowawayDatabase) -> AsyncIterator[Directory]:
    tenant = await create_tenant(migrated_db.migrator_url, "Directory")
    tech, requester = await seed_users(
        migrated_db,
        tenant,
        [
            {"display_name": "Aisha Tech", "user_type": "technician", "email": "aisha@t.test"},
            {"display_name": "Bilal Requester", "email": "bilal@t.test"},
        ],
    )
    app: FastAPI = create_app(make_settings(database_url=migrated_db.app_url))
    async with app.router.lifespan_context(app):
        setattr(app.state, SESSION_RESOLVER_STATE, fake_session)
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield Directory(client, migrated_db, tenant, tech, requester, app)


def names(response: httpx.Response) -> list[str]:
    assert response.status_code == 200, response.text
    return [u["display_name"] for u in response.json()["items"]]


# --- list: filter, simple parameters, sort, envelope ----------------------------------------------


async def test_list_envelope_and_default_sort(directory: Directory) -> None:
    response = await directory.list()
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items", "next_cursor", "has_more", "estimated_total"}
    assert names(response) == ["Aisha Tech", "Bilal Requester"]  # default: display_name
    assert (body["has_more"], body["next_cursor"], body["estimated_total"]) == (False, None, None)
    assert (await directory.list(include_total="true")).json()["estimated_total"] == 2


async def test_dsl_filter_and_simple_parameters(directory: Directory) -> None:
    await seed_users(
        directory.db,
        directory.tenant,
        [
            {
                "display_name": "Carla Tech",
                "user_type": "technician",
                "last_login_at": datetime.now(UTC),
            },
            {"display_name": "Dina Disabled", "status": "disabled", "user_type": "technician"},
            {"display_name": "Emre Arabic", "locale": "ar"},
        ],
    )
    dsl = {
        "and": [
            {"field": "user_type", "op": "eq", "value": "technician"},
            {
                "or": [
                    {"field": "last_login_at", "op": "last_n_days", "value": 7},
                    {"field": "email", "op": "starts_with", "value": "aisha"},
                ]
            },
        ]
    }
    assert names(await directory.list(filter=json.dumps(dsl))) == ["Aisha Tech", "Carla Tech"]
    assert names(await directory.list(status="disabled")) == ["Dina Disabled"]
    assert names(await directory.list(locale="ar")) == ["Emre Arabic"]
    both = await directory.get(
        "/api/v1/users?user_type=technician&status=active&sort=-display_name"
    )
    assert names(both) == ["Carla Tech", "Aisha Tech"]
    multi = await directory.get("/api/v1/users?locale=ar&locale=en&user_type=requester")
    assert names(multi) == ["Bilal Requester", "Emre Arabic"]


async def test_cursor_pages_are_stable_under_concurrent_inserts(directory: Directory) -> None:
    await seed_users(directory.db, directory.tenant, [{} for _ in range(25)])
    seen: list[str] = []
    cursor = None
    pages = 0
    while True:
        params: dict[str, Any] = {"sort": "created_at", "limit": 10, "user_type": "requester"}
        if cursor:
            params["cursor"] = cursor
        body = (await directory.list(**params)).json()
        seen += [u["id"] for u in body["items"]]
        pages += 1
        if pages == 1:
            # New rows land before page 2 is read: older positions must not shift.
            await seed_users(
                directory.db,
                directory.tenant,
                [
                    {"created_at": BASE - timedelta(days=1)},
                    {"created_at": BASE + timedelta(days=1)},
                ],
            )
        cursor = body["next_cursor"]
        if not body["has_more"]:
            assert cursor is None
            break
    assert len(seen) == len(set(seen))  # no duplicates across pages
    assert len(seen) == 1 + 25 + 1  # Bilal, the 25, and the row inserted *after* the cursor


async def test_sort_by_nullable_column_pages_through_every_row(directory: Directory) -> None:
    logins = [datetime.now(UTC) - timedelta(hours=h) if h % 3 else None for h in range(12)]
    await seed_users(directory.db, directory.tenant, [{"last_login_at": t} for t in logins])
    for sort in ("-last_login_at,display_name", "last_login_at"):
        ids: list[str] = []
        cursor = None
        while True:
            params: dict[str, Any] = {"sort": sort, "limit": 5}
            if cursor:
                params["cursor"] = cursor
            body = (await directory.list(**params)).json()
            ids += [u["id"] for u in body["items"]]
            cursor = body["next_cursor"]
            if cursor is None:
                break
        assert len(ids) == len(set(ids)) == 14, sort


# --- cursor and page-size abuse ------------------------------------------------------------------


async def test_cursor_cannot_be_reused_elsewhere(
    directory: Directory, migrated_db: ThrowawayDatabase
) -> None:
    await seed_users(directory.db, directory.tenant, [{} for _ in range(5)])
    cursor = (await directory.list(limit=2)).json()["next_cursor"]
    assert cursor
    other_tenant = await create_tenant(migrated_db.migrator_url, "Other")
    (other_tech,) = await seed_users(migrated_db, other_tenant, [{"user_type": "technician"}])
    other_tech_here = (
        await seed_users(directory.db, directory.tenant, [{"user_type": "technician"}])
    )[0]
    attempts = {
        "other tenant": directory.client.get(
            "/api/v1/users",
            params={"limit": 2, "cursor": cursor},
            headers=directory.as_(other_tech, other_tenant),
        ),
        "other user": directory.list(other_tech_here, limit=2, cursor=cursor),
        "other filter": directory.list(limit=2, cursor=cursor, status="active"),
        "other sort": directory.list(limit=2, cursor=cursor, sort="-display_name"),
        "tampered": directory.list(limit=2, cursor=cursor[:-3] + "abc"),
        "garbage": directory.list(limit=2, cursor="' OR 1=1 --"),
    }
    for label, request in attempts.items():
        response = await request
        assert (response.status_code, response.json()["code"]) == (400, "invalid_cursor"), label


@pytest.mark.parametrize("limit", ["0", "201", "-5", "100000", "abc"])
async def test_page_size_abuse_is_refused(directory: Directory, limit: str) -> None:
    response = await directory.list(limit=limit)
    assert response.status_code == 422
    assert response.json()["code"] in {"invalid_page_size", "validation_failed"}


# --- filter attacks over HTTP: always a 422, never a 500 or a heavy query -------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "1=1",
        '{"field": "external_subject", "op": "eq", "value": "x"}',
        '{"field": "tenant_id", "op": "ne", "value": "00000000-0000-0000-0000-000000000000"}',
        '{"field": "email", "op": "gt", "value": "a"}',
        '{"field": "user_type", "op": "eq", "value": "admin"}',
        '{"field": "created_at", "op": "eq", "value": "now()"}',
        '{"or": [' + ",".join(['{"field": "email", "op": "eq", "value": "x"}'] * 40) + "]}",
        '{"and": [' * 50 + '{"field": "email", "op": "eq", "value": "x"}' + "]}" * 50,
        '{"field": "email", "op": "in", "value": ' + json.dumps(["x"] * 101) + "}",
    ],
)
async def test_filter_attacks_get_a_problem_not_data(directory: Directory, raw: str) -> None:
    response = await directory.list(filter=raw)
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "invalid_filter"
    assert body["errors"][0]["field"].startswith("filter")
    assert "Traceback" not in response.text


async def test_filter_values_with_sql_are_just_values(directory: Directory) -> None:
    raw = json.dumps(
        {"field": "display_name", "op": "contains", "value": "'; DROP TABLE users; --"}
    )
    assert names(await directory.list(filter=raw)) == []
    assert len(names(await directory.list())) == 2  # the table is still there


async def test_unknown_query_parameters_are_refused(directory: Directory) -> None:
    response = await directory.list(external_subject="sub-x")
    assert response.status_code == 422
    assert response.json()["errors"][0]["code"] == "unknown_parameter"


# --- permissions ---------------------------------------------------------------------------------


async def test_requesters_cannot_list_or_read_others(directory: Directory) -> None:
    refused = (await directory.list(directory.requester)).json()
    assert (refused["code"], refused["params"]) == (
        "permission_denied",
        {"permission": "users.view", "reason": "no_permission"},
    )
    other = await directory.get(f"/api/v1/users/{directory.tech}", directory.requester)
    assert other.json()["code"] == "permission_denied"
    me = await directory.get(f"/api/v1/users/{directory.requester}", directory.requester)
    assert me.status_code == 200


async def test_another_tenants_user_is_not_found(
    directory: Directory, migrated_db: ThrowawayDatabase
) -> None:
    other_tenant = await create_tenant(migrated_db.migrator_url, "Elsewhere")
    (stranger,) = await seed_users(migrated_db, other_tenant, [{}])
    response = await directory.get(f"/api/v1/users/{stranger}")
    assert response.status_code == 404


# --- detail and update: ETag, If-None-Match, If-Match ---------------------------------------------


async def outbox_updates(db: ThrowawayDatabase, user: uuid.UUID) -> list[dict[str, Any]]:
    conn = await asyncpg.connect(db.admin_url)
    try:
        rows = await conn.fetch(
            "SELECT envelope FROM outbox_events WHERE event_type = 'identity_access.user.updated'"
            " AND aggregate_id = $1 ORDER BY id",
            str(user),
        )
    finally:
        await conn.close()
    return [json.loads(r["envelope"]) for r in rows]


async def test_etag_and_conditional_get(directory: Directory) -> None:
    response = await directory.get(f"/api/v1/users/{directory.tech}")
    assert response.headers["etag"] == '"1"'
    assert response.json()["version"] == 1
    cached = await directory.get(
        f"/api/v1/users/{directory.tech}", headers={"If-None-Match": '"1"'}
    )
    assert cached.status_code == 304
    assert cached.content == b""


async def test_patch_needs_if_match_and_rejects_stale_versions(directory: Directory) -> None:
    path = f"/api/v1/users/{directory.tech}"
    headers = directory.as_(directory.tech)
    missing = await directory.client.patch(path, json={"signature": "Regards"}, headers=headers)
    assert (missing.status_code, missing.json()["code"]) == (428, "precondition_required")

    ok = await directory.client.patch(
        path,
        json={"signature": "Regards, Aisha", "time_zone": "Asia/Dubai"},
        headers={**headers, "If-Match": '"1"'},
    )
    assert ok.status_code == 200, ok.text
    assert ok.headers["etag"] == '"2"'
    assert (ok.json()["signature"], ok.json()["time_zone"]) == ("Regards, Aisha", "Asia/Dubai")

    stale = await directory.client.patch(
        path, json={"signature": "Lost update"}, headers={**headers, "If-Match": '"1"'}
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "version_conflict"
    params = stale.json()["params"]
    assert (params["expected_version"], params["current_version"]) == (1, 2)
    # Who changed what since version 1 (WP-012): Aisha herself, from another tab.
    assert params["changed_by"] == "Aisha Tech"
    assert params["changed_fields"].split(",") == ["signature", "time_zone"]
    assert params["changed_at"]

    bad = await directory.client.patch(path, json={}, headers={**headers, "If-Match": "*"})
    assert (bad.status_code, bad.json()["code"]) == (400, "invalid_etag")

    (event,) = await outbox_updates(directory.db, directory.tech)
    assert event["payload"] == {
        "user_id": str(directory.tech),
        "changed_fields": ["signature", "time_zone"],
    }
    assert event["aggregate_version"] == 2
    assert event["actor"] == {"type": "user", "id": str(directory.tech)}
    assert "Regards" not in json.dumps(event)  # values never go into events


async def test_patch_without_changes_keeps_the_version_and_emits_nothing(
    directory: Directory,
) -> None:
    path = f"/api/v1/users/{directory.tech}"
    same = await directory.client.patch(
        path, json={"signature": None}, headers={**directory.as_(directory.tech), "If-Match": '"1"'}
    )
    assert same.status_code == 200
    assert same.headers["etag"] == '"1"'
    assert await outbox_updates(directory.db, directory.tech) == []


async def test_identity_fields_and_other_users_cannot_be_patched(directory: Directory) -> None:
    headers = {**directory.as_(directory.tech), "If-Match": '"1"'}
    keycloak_owned = await directory.client.patch(
        f"/api/v1/users/{directory.tech}", json={"email": "evil@x.test"}, headers=headers
    )
    assert keycloak_owned.status_code == 422
    someone_else = await directory.client.patch(
        f"/api/v1/users/{directory.requester}", json={"signature": "x"}, headers=headers
    )
    assert (someone_else.status_code, someone_else.json()["code"]) == (403, "own_profile_only")
    bad_zone = await directory.client.patch(
        f"/api/v1/users/{directory.tech}", json={"time_zone": "Mars/Base"}, headers=headers
    )
    assert bad_zone.status_code == 422
    assert bad_zone.json()["errors"][0] == {
        "field": "body.time_zone",
        "code": "invalid_choice",
        "message_key": "errors.field.invalid_choice",
        "params": {},
    }


@contextmanager
def connection_peak(directory: Directory) -> Iterator[list[int]]:
    """Track the most DB connections checked out at once while the block runs."""
    engine = directory.app.state.db.engine.sync_engine
    state = [0, 0]  # peak, open

    def checkout(*_: object) -> None:
        state[1] += 1
        state[0] = max(state[0], state[1])

    def checkin(*_: object) -> None:
        state[1] -= 1

    event.listen(engine, "checkout", checkout)
    event.listen(engine, "checkin", checkin)
    try:
        yield state
    finally:
        event.remove(engine, "checkout", checkout)
        event.remove(engine, "checkin", checkin)


async def test_concurrent_patches_with_the_same_version_let_exactly_one_win(
    directory: Directory,
) -> None:
    path = f"/api/v1/users/{directory.tech}"
    headers = {**directory.as_(directory.tech), "If-Match": '"1"'}
    with connection_peak(directory) as peak:
        responses = await asyncio.gather(
            *(
                directory.client.patch(path, json={"signature": f"v{i}"}, headers=headers)
                for i in range(5)
            )
        )
    assert sorted(r.status_code for r in responses) == [200, 409, 409, 409, 409]
    # One connection per request: two each starved CI's 5-connection PgBouncer pool.
    assert peak[0] <= 5
    assert len(await outbox_updates(directory.db, directory.tech)) == 1


async def test_no_session_means_401(directory: Directory) -> None:
    response = await directory.client.get("/api/v1/users")
    assert response.status_code == 401
