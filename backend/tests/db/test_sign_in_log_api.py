"""The sign-in log list (REQ-AUD-015; WP-057 S1a; lane B's conditions 8 and 11).

AC2: "failed" in the last 24 hours lists only failures in that range. Only holders of
`identity.view_sign_ins` read it; another tenant's entries never show (RLS); pages follow a
signed cursor bound to the filters.
"""

import uuid
from datetime import UTC, datetime, timedelta

import asyncpg
import httpx

from tests.db.test_access_api import Org
from tests.db.test_identity_api import World, world

__all__ = ["world"]  # the fixture, re-used

PATH = "/identity/sign-ins"


async def _event(
    world: World, org: Org, *, outcome: str, ago: timedelta, reason: str | None = None
) -> uuid.UUID:
    event_id = uuid.uuid4()
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        await conn.execute(
            "INSERT INTO sign_in_events (tenant_id, id, user_id, occurred_at, outcome, reason,"
            " method, app, ip, device, source) VALUES ($1, $2, $3, $4, $5, $6, 'unknown',"
            " 'console', '192.0.2.10', 'chrome:windows', 'bff')",
            org.tenant,
            event_id,
            org.admin,
            datetime.now(UTC) - ago,
            outcome,
            reason,
        )
    finally:
        await conn.close()
    return event_id


async def test_req_aud_015_ac2_failed_in_the_last_day_lists_only_those(world: World) -> None:
    recent = await _event(
        world, world.a, outcome="failed", ago=timedelta(hours=2), reason="ip_not_allowed"
    )
    await _event(world, world.a, outcome="failed", ago=timedelta(days=2))
    await _event(world, world.a, outcome="success", ago=timedelta(hours=1))
    await _event(world, world.b, outcome="failed", ago=timedelta(hours=1))  # another tenant
    since = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
    query = httpx.QueryParams({"outcome": "failed", "since": since})
    listed = await world.call("GET", f"{PATH}?{query}", world.a)
    assert listed.status_code == 200, listed.text
    page = listed.json()
    assert [item["id"] for item in page["items"]] == [str(recent)]
    (item,) = page["items"]
    assert (item["reason"], item["ip"], item["device"]) == (
        "ip_not_allowed",
        "192.0.2.10",
        "chrome:windows",
    )
    assert str(world.a.admin) in page["people"]


async def test_the_log_pages_newest_first_with_a_cursor_bound_to_its_filters(world: World) -> None:
    ids = [
        await _event(world, world.a, outcome="success", ago=timedelta(minutes=m)) for m in (3, 2, 1)
    ]
    first = (await world.call("GET", f"{PATH}?limit=2", world.a)).json()
    assert [i["id"] for i in first["items"]] == [str(ids[2]), str(ids[1])]
    assert first["next_cursor"]
    second = await world.call(
        "GET", f"{PATH}?{httpx.QueryParams({'limit': 2, 'cursor': first['next_cursor']})}", world.a
    )
    assert [i["id"] for i in second.json()["items"]] == [str(ids[0])]
    assert second.json()["next_cursor"] is None
    # The same cursor with other filters is another list's: refused.
    cursor = first["next_cursor"]
    other = await world.call(
        "GET",
        f"{PATH}?{httpx.QueryParams({'limit': 2, 'outcome': 'failed', 'cursor': cursor})}",
        world.a,
    )
    assert (other.status_code, other.json()["code"]) == (400, "invalid_cursor")


async def test_only_holders_of_the_right_read_the_log(world: World) -> None:
    assert (await world.call("GET", PATH, world.a, world.a.tech)).status_code == 403


async def test_erasure_clears_address_and_device_and_old_entries_go(world: World) -> None:
    """Lane B's condition 8: ip and device are personal data; entries go after 90 days."""
    from app.core.tenancy import TenantContext  # noqa: PLC0415 - this test only
    from app.modules.identity_access.service import sign_in_log  # noqa: PLC0415 - this test only

    kept = await _event(world, world.a, outcome="success", ago=timedelta(days=89))
    await _event(world, world.a, outcome="success", ago=timedelta(days=91))
    theirs = await _event(world, world.b, outcome="success", ago=timedelta(days=91))
    database = world.app.state.db
    async with database.tenant_session(TenantContext(world.a.tenant)) as session:
        assert await sign_in_log.purge(session, datetime.now(UTC)) == 1  # only the old one here
        assert await sign_in_log.forget_person(session, world.a.admin) == 1
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        rows = await conn.fetch("SELECT id, ip, device FROM sign_in_events")
    finally:
        await conn.close()
    found = {r["id"]: (r["ip"], r["device"]) for r in rows}
    assert found[kept] == (None, None)  # erased: no address, no device
    assert theirs in found  # the other tenant's old entry is its own purge's business (RLS)
