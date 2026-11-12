"""A person's cost per hour over HTTP and through the read port (REQ-INC-068; migration 0148).

The access world (tests/db/test_access_api.py): per org an admin (tenant admin), a manager
(custom role with users.view and users.manage, so people admin without money), a technician
and a requester. Org B is there for isolation. Real PostgreSQL with RLS on; throwaway database.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import asyncpg
import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.database import Database, create_engine
from app.core.tenancy import TenantContext
from app.modules.identity_access import cost_rate
from tests.db import test_access_api
from tests.db.test_access_api import Org, World, problem

pytestmark = [pytest.mark.db, pytest.mark.valkey]
world = test_access_api.world  # the access world fixture, reused

DAY = timedelta(days=1)


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _path(user: uuid.UUID, rate_id: str | None = None) -> str:
    return f"/users/{user}/cost-rates" + (f"/{rate_id}" if rate_id else "")


async def _set(
    world: World,
    org: Org,
    person: uuid.UUID,
    rate: str,
    start: datetime,
    by: uuid.UUID | None = None,
    key: str | None = None,
) -> httpx.Response:
    return await world.call(
        "POST",
        _path(person),
        org,
        by or org.admin,
        json={"rate": rate, "effective_from": start.isoformat()},
        headers={"Idempotency-Key": key or str(uuid.uuid4())},
    )


async def _list(world: World, org: Org, person: uuid.UUID, by: uuid.UUID | None = None) -> Any:  # noqa: ANN401 - httpx response
    return await world.call("GET", _path(person), org, by or org.admin)


async def _sql(world: World, statement: str, *args: Any) -> list[asyncpg.Record]:  # noqa: ANN401 - asyncpg args
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        return list(await conn.fetch(statement, *args))
    finally:
        await conn.close()


async def _grant(world: World, org: Org, person: uuid.UUID, name: str, keys: list[str]) -> None:
    created = await world.create_role(
        org, org.admin, name, [{"permission": k, "scope": "all"} for k in keys]
    )
    assert created.status_code == 201, created.text
    given = await world.call("PUT", f"/users/{person}/roles/{created.json()['id']}", org, org.admin)
    assert given.status_code == 204, given.text


async def _service_identity(world: World, org: Org) -> uuid.UUID:
    user_id = uuid.uuid4()
    await _sql(
        world,
        "INSERT INTO users (id, tenant_id, display_name, first_name, user_type, can_sign_in)"
        " VALUES ($1, $2, 'Mail bot', 'Mail bot', 'service', false)",
        user_id,
        org.tenant,
    )
    return user_id


# --- tenant isolation (rule a) -------------------------------------------------------------------


async def test_a_tenant_never_reads_or_writes_another_tenants_rates(world: World) -> None:
    for org in (world.a, world.b):
        made = await _set(world, org, org.tech, "40.00", _now() - DAY)
        assert made.status_code == 201, made.text
    b_rate = (await _list(world, world.b, world.b.tech)).json()["items"][0]["id"]
    database = Database(
        create_engine(world.db.app_url, application_name="test", use_null_pool=True)
    )
    try:
        async with database.tenant_session(TenantContext(world.a.tenant)) as session:
            tenants = set(
                await session.scalars(text("SELECT DISTINCT tenant_id FROM user_cost_rates"))
            )
            assert tenants == {world.a.tenant}
            changed = await session.execute(
                text("UPDATE user_cost_rates SET rate = 0 WHERE tenant_id = :b"),
                {"b": world.b.tenant},
            )
            assert changed.rowcount == 0  # type: ignore[attr-defined]  # CursorResult at runtime
            # The port reads through RLS too: B's person has no rate seen from A.
            assert await cost_rate(session, world.b.tech, _now()) is None
        with pytest.raises(DBAPIError, match="row-level security"):
            async with database.tenant_session(TenantContext(world.a.tenant)) as session:
                await session.execute(
                    text(
                        "INSERT INTO user_cost_rates (tenant_id, id, user_id, rate, currency,"
                        " effective_from) VALUES (:b, :id, :u, 1, 'USD', now())"
                    ),
                    {"b": world.b.tenant, "id": uuid.uuid4(), "u": world.b.tech},
                )
    finally:
        await database.dispose()
    # Over the API, B's rate is not found from A.
    stray = await world.call(
        "PATCH",
        _path(world.a.tech, b_rate),
        world.a,
        world.a.admin,
        json={"rate": "1"},
        headers={"If-Match": '"1"'},
    )
    assert problem(stray) == (404, "cost_rate_not_found")
    assert problem(await _list(world, world.a, world.b.tech)) == (404, "user_not_found")


# --- the read port ------------------------------------------------------------------------------


async def test_the_port_gives_the_rate_in_force_at_a_moment(world: World) -> None:
    a, now = world.a, _now()
    assert (await _set(world, a, a.tech, "30.00", now - 30 * DAY)).status_code == 201
    assert (await _set(world, a, a.tech, "35.50", now - DAY)).status_code == 201
    assert (await _set(world, a, a.tech, "50.00", now + 10 * DAY)).status_code == 201
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert await cost_rate(session, a.tech, now) == Decimal("35.50")  # the latest started
        assert await cost_rate(session, a.tech, now - 10 * DAY) == Decimal("30.00")
        assert await cost_rate(session, a.tech, now + 11 * DAY) == Decimal("50.00")
        assert await cost_rate(session, a.tech, now - 31 * DAY) is None  # not yet in force
        assert await cost_rate(session, a.requester, now) is None  # never set
        with pytest.raises(ValueError, match="timezone-aware"):
            await cost_rate(session, a.tech, datetime(2026, 11, 12, 9, 0))  # noqa: DTZ001 - naive on purpose
    # A removed rate no longer counts.
    rates = (await _list(world, a, a.tech)).json()
    current = rates["current"]
    assert (current["rate"], current["state"], rates["currency"]) == ("35.50", "current", "USD")
    assert [r["state"] for r in rates["items"]] == ["future", "current", "past"]
    gone = await world.call(
        "DELETE",
        _path(a.tech, current["id"]),
        a,
        a.admin,
        headers={"If-Match": f'"{current["version"]}"'},
    )
    assert gone.status_code == 204, gone.text
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert await cost_rate(session, a.tech, now) == Decimal("30.00")


# --- rules ---------------------------------------------------------------------------------------


async def test_change_needs_the_version_and_a_superseded_rate_stays(world: World) -> None:
    a, now = world.a, _now()
    old = (await _set(world, a, a.tech, "20.00", now - 30 * DAY)).json()
    current = (await _set(world, a, a.tech, "25.00", now - DAY)).json()
    assert old["currency"] == "USD"
    stale = await world.call(
        "PATCH",
        _path(a.tech, current["id"]),
        a,
        a.admin,
        json={"rate": "26"},
        headers={"If-Match": f'"{current["version"] + 3}"'},
    )
    assert problem(stale) == (409, "version_conflict")
    missing = await world.call(
        "PATCH", _path(a.tech, current["id"]), a, a.admin, json={"rate": "1"}
    )
    assert missing.status_code == 428
    changed = await world.call(
        "PATCH",
        _path(a.tech, current["id"]),
        a,
        a.admin,
        json={"rate": "26.75"},
        headers={"If-Match": f'"{current["version"]}"'},
    )
    assert changed.status_code == 200, changed.text
    assert (changed.json()["rate"], changed.json()["version"]) == ("26.75", 2)
    assert changed.headers["ETag"] == '"2"'
    past = await world.call(
        "PATCH",
        _path(a.tech, old["id"]),
        a,
        a.admin,
        json={"rate": "21"},
        headers={"If-Match": f'"{old["version"]}"'},
    )
    assert problem(past) == (409, "cost_rate_superseded")
    # Moving the current rate before the old one would make it superseded too.
    moved = await world.call(
        "PATCH",
        _path(a.tech, current["id"]),
        a,
        a.admin,
        json={"effective_from": (now - 40 * DAY).isoformat()},
        headers={"If-Match": '"2"'},
    )
    assert problem(moved) == (409, "cost_rate_superseded")
    taken = await _set(world, a, a.tech, "99", now - 30 * DAY)
    assert problem(taken) == (409, "cost_rate_date_taken")
    negative = await _set(world, a, a.tech, "-1", now)
    assert negative.status_code == 422
    naive = await world.call(
        "POST",
        _path(a.tech),
        a,
        a.admin,
        json={"rate": "10", "effective_from": "2026-11-12T09:00:00"},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert naive.status_code == 422
    assert naive.json()["errors"][0]["code"] == "invalid_date"


async def test_the_same_idempotency_key_sets_one_rate(world: World) -> None:
    a, key, start = world.a, str(uuid.uuid4()), _now()
    first = await _set(world, a, a.tech, "33.00", start, key=key)
    again = await _set(world, a, a.tech, "33.00", start, key=key)
    assert first.status_code == again.status_code == 201
    assert first.json()["id"] == again.json()["id"]
    assert len((await _list(world, a, a.tech)).json()["items"]) == 1


async def test_a_service_identity_never_has_a_rate(world: World) -> None:
    a = world.a
    bot = await _service_identity(world, a)
    assert problem(await _set(world, a, bot, "10", _now())) == (409, "not_a_person")
    assert problem(await _list(world, a, bot)) == (409, "not_a_person")


# --- who may see and change them -----------------------------------------------------------------


async def test_rights_view_alone_reads_and_people_admin_without_them_sees_nothing(
    world: World,
) -> None:
    a = world.a
    made = await _set(world, a, a.tech, "45.00", _now() - DAY)
    assert made.status_code == 201, made.text
    rate = made.json()
    # The manager administers people (users.view + users.manage) but holds no cost-rate right.
    assert problem(await _list(world, a, a.tech, a.manager)) == (403, "permission_denied")
    assert problem(await _set(world, a, a.tech, "1", _now(), a.manager)) == (
        403,
        "permission_denied",
    )
    # Viewing alone: reads, never changes.
    await _grant(world, a, a.manager, "Cost viewer", ["users.view_cost_rates"])
    seen = await _list(world, a, a.tech, a.manager)
    assert seen.status_code == 200, seen.text
    assert seen.json()["current"]["rate"] == "45.00"
    assert problem(await _set(world, a, a.tech, "1", _now() + DAY, a.manager)) == (
        403,
        "permission_denied",
    )
    patched = await world.call(
        "PATCH",
        _path(a.tech, rate["id"]),
        a,
        a.manager,
        json={"rate": "1"},
        headers={"If-Match": '"1"'},
    )
    assert problem(patched) == (403, "permission_denied")
    removed = await world.call(
        "DELETE", _path(a.tech, rate["id"]), a, a.manager, headers={"If-Match": '"1"'}
    )
    assert problem(removed) == (403, "permission_denied")


async def test_a_technician_never_sees_rates(world: World) -> None:
    a = world.a
    assert (await _set(world, a, a.requester, "12.34", _now() - DAY)).status_code == 201
    assert (await _set(world, a, a.tech, "56.78", _now() - DAY)).status_code == 201
    for person in (a.tech, a.requester):
        assert problem(await _list(world, a, person, a.tech)) == (403, "permission_denied")
    assert problem(await _set(world, a, a.tech, "1", _now(), a.tech)) == (403, "permission_denied")


async def test_rates_never_appear_on_the_person_record_or_lists(world: World) -> None:
    a = world.a
    assert (await _set(world, a, a.tech, "87.65", _now() - DAY)).status_code == 201
    for by in (a.admin, a.manager, a.tech):
        detail = await world.call("GET", f"/users/{a.tech}", a, by)
        assert detail.status_code == 200, detail.text
        listed = await world.call("GET", "/users", a, by, params={"limit": 200})
        assert listed.status_code == 200, listed.text
        searched = await world.call("GET", "/users", a, by, params={"q": "Tech"})
        for response in (detail, listed, searched):
            assert "87.65" not in response.text
            assert "cost_rate" not in response.text
            assert "rate" not in json.dumps(response.json()).lower().replace("updated_at", "")


# --- audit, history and events -------------------------------------------------------------------


async def test_every_change_is_audited_with_old_new_and_the_date(world: World) -> None:
    a, start = world.a, _now() + 5 * DAY
    made = (await _set(world, a, a.tech, "40.00", start)).json()
    changed = await world.call(
        "PATCH",
        _path(a.tech, made["id"]),
        a,
        a.admin,
        json={"rate": "42.50"},
        headers={"If-Match": '"1"'},
    )
    assert changed.status_code == 200, changed.text
    gone = await world.call(
        "DELETE", _path(a.tech, made["id"]), a, a.admin, headers={"If-Match": '"2"'}
    )
    assert gone.status_code == 204, gone.text
    rows = await _sql(
        world,
        "SELECT object_type, object_id, actor_id, details FROM audit_entries"
        " WHERE tenant_id = $1 AND action = 'user.cost_rate_changed' ORDER BY occurred_at",
        a.tenant,
    )
    entries = [
        (r["object_type"], r["object_id"], r["actor_id"], json.loads(r["details"])) for r in rows
    ]
    assert [(t, o, actor) for t, o, actor, _ in entries] == [("user", str(a.tech), a.admin)] * 3
    details = [d for *_, d in entries]
    assert [d["change"] for d in details] == ["created", "updated", "deleted"]
    assert [(d["old_rate"], d["new_rate"]) for d in details] == [
        (None, "40.00"),
        ("40.00", "42.50"),
        ("42.50", None),
    ]
    assert datetime.fromisoformat(details[0]["new_effective_from"]) == start
    assert datetime.fromisoformat(details[1]["old_effective_from"]) == start
    assert {d["rate_id"] for d in details} == {made["id"]}
    assert {d["currency"] for d in details} == {"USD"}
    # A refused change is audited as refused (the error observer), and nothing changed.
    await _set(world, a, a.tech, "1", _now(), a.tech)
    refused = await _sql(
        world,
        "SELECT outcome FROM audit_entries WHERE tenant_id = $1"
        " AND action = 'user.cost_rate_changed' AND actor_id = $2",
        a.tenant,
        a.tech,
    )
    assert [r["outcome"] for r in refused] == ["refused"]
    # The person's history names the rate, never its amount; the event carries IDs only.
    history = await _sql(
        world,
        "SELECT kind, old_value, new_value FROM field_changes WHERE tenant_id = $1"
        " AND record_type = 'user' AND record_id = $2 AND field = 'cost_rate'"
        " ORDER BY occurred_at",
        a.tenant,
        str(a.tech),
    )
    assert [h["kind"] for h in history] == ["child_added", "child_changed", "child_removed"]
    assert all("40" not in str(h["old_value"]) + str(h["new_value"]) for h in history)
    events = await _sql(
        world,
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1"
        " AND event_type = 'identity_access.user_cost_rate.changed' ORDER BY created_at",
        a.tenant,
    )
    payloads = [json.loads(e["envelope"])["payload"] for e in events]
    assert payloads == [
        {"user_id": str(a.tech), "change": change} for change in ("created", "updated", "deleted")
    ]


async def test_a_rate_in_another_currency_than_today_s_base_is_no_rate(world: World) -> None:
    """After a change of base currency an old rate is never snapshotted as an amount in the new
    one: the port says no rate (lane A's #427 review)."""
    a, now = world.a, _now()
    person = a.manager  # no other test gives the manager a rate
    assert (await _set(world, a, person, "42.00", now - DAY)).status_code == 201
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert await cost_rate(session, person, now) == Decimal("42.00")
    # As if the base currency had changed since: the stored rate keeps its old currency.
    # Superuser connection: RLS does not apply, so the tenant is filtered explicitly.
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        await conn.execute(
            "UPDATE user_cost_rates SET currency = 'XTS' WHERE tenant_id = $1 AND user_id = $2",
            a.tenant,
            person,
        )
    finally:
        await conn.close()
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert await cost_rate(session, person, now) is None
