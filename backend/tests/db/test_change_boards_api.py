"""Change advisory boards over HTTP and under RLS (WP-045b S2; REQ-CHG-040, -041).

Real PostgreSQL as the application role. Each tenant starts with the two seeded boards and no
members; an admin's board needs a member; members are replaced, never all removed; the default
board stays; tenant B never sees or writes tenant A's boards or members (rule 5a).
"""

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.tenancy import TenantContext
from tests.db.test_incidents_api import CONSOLE, Org, World, field_codes, problem, world

__all__ = ["world"]  # the fixture, re-used

BOARDS = "/change-boards"


async def add(world: World, org: Org, user: uuid.UUID, **body: Any) -> httpx.Response:  # noqa: ANN401 - JSON
    return await world.call(
        "POST",
        BOARDS,
        org,
        user,
        json={"name": "Network CAB", "members": [{"user_id": str(org.lead)}], **body},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )


async def patch(world: World, org: Org, board: dict[str, Any], **body: Any) -> httpx.Response:  # noqa: ANN401 - JSON
    return await world.call(
        "PATCH",
        f"{BOARDS}/{board['id']}",
        org,
        org.admin,
        json=body,
        headers={"If-Match": f'"{board["version"]}"', **CONSOLE},
    )


async def test_req_chg_040_each_tenant_starts_with_two_boards_without_members(
    world: World,
) -> None:
    listed = await world.call("GET", BOARDS, world.a, world.a.admin)
    assert listed.status_code == 200, listed.text
    boards = {b["code"]: b for b in listed.json()}
    assert set(boards) == {"cab", "emergency_cab"}
    assert boards["cab"]["is_default"]
    assert boards["cab"]["members"] == []
    assert boards["emergency_cab"]["mapping"]["change_types"] == ["emergency"]
    again = await world.call("GET", BOARDS, world.a, world.a.admin)
    assert len(again.json()) == 2  # seeded once


async def test_req_chg_040_ac1_a_board_without_members_is_refused(world: World) -> None:
    a = world.a
    assert field_codes(await add(world, a, a.admin, members=[])) == {"members": "required"}
    made = await add(world, a, a.admin, members=[{"group_id": str(a.ga)}, {"user_id": str(a.lead)}])
    assert made.status_code == 201, made.text
    board = made.json()
    assert len(board["members"]) == 2
    assert field_codes(await patch(world, a, board, members=[])) == {"members": "required"}


async def test_members_are_replaced_and_checked(world: World) -> None:
    a, b = world.a, world.b
    board = (await add(world, a, a.admin)).json()
    swapped = await patch(world, a, board, members=[{"user_id": str(a.tech_a), "optional": True}])
    assert swapped.status_code == 200, swapped.text
    assert swapped.json()["members"] == [
        {"user_id": str(a.tech_a), "group_id": None, "optional": True}
    ]
    assert swapped.json()["version"] == board["version"] + 1
    # Tenant B's person is no one here.
    other = await patch(world, a, swapped.json(), members=[{"user_id": str(b.lead)}])
    assert field_codes(other) == {"members": "user_not_found"}
    # A stale version is a 409.
    assert problem(await patch(world, a, board, name="Old"))[0] == 409


async def test_a_mapping_names_known_types_levels_and_sites(world: World) -> None:
    a = world.a
    made = await add(
        world,
        a,
        a.admin,
        mapping={"risk_levels": ["high", "very_high"], "site_ids": [str(a.s1)]},
    )
    assert made.status_code == 201, made.text
    assert made.json()["mapping"]["risk_levels"] == ["high", "very_high"]
    wrong = await add(world, a, a.admin, name="Other", mapping={"change_types": ["nope"]})
    assert field_codes(wrong) == {"mapping.change_types": "invalid_choice"}
    no_site = await add(world, a, a.admin, name="Third", mapping={"site_ids": [str(uuid.uuid4())]})
    assert field_codes(no_site) == {"mapping.site_ids": "site_not_found"}


async def test_the_chair_rule_needs_a_chair_and_names_are_unique(world: World) -> None:
    a = world.a
    no_chair = await add(world, a, a.admin, rule="majority_with_chair")
    assert field_codes(no_chair) == {"chair_id": "required"}
    chaired = await add(world, a, a.admin, rule="majority_with_chair", chair_id=str(a.lead))
    assert chaired.status_code == 201, chaired.text
    again = await add(world, a, a.admin, name="network cab")
    assert field_codes(again) == {"name": "duplicate_name"}


async def test_req_chg_041_ac2_the_default_board_stays(world: World) -> None:
    a = world.a
    cab = next(b for b in (await world.call("GET", BOARDS, a, a.admin)).json() if b["is_default"])
    kept = await world.call(
        "DELETE",
        f"{BOARDS}/{cab['id']}",
        a,
        a.admin,
        headers={"If-Match": f'"{cab["version"]}"', **CONSOLE},
    )
    assert problem(kept) == (409, "default_board_kept")
    mine = (await add(world, a, a.admin)).json()
    gone = await world.call(
        "DELETE",
        f"{BOARDS}/{mine['id']}",
        a,
        a.admin,
        headers={"If-Match": f'"{mine["version"]}"', **CONSOLE},
    )
    assert gone.status_code == 204, gone.text
    assert mine["id"] not in {b["id"] for b in (await world.call("GET", BOARDS, a, a.admin)).json()}


async def test_only_admins_change_boards(world: World) -> None:
    a = world.a
    assert (await add(world, a, a.tech_a)).status_code == 403
    assert (await world.call("GET", BOARDS, a, a.requester)).status_code == 403


@pytest.mark.parametrize("table", ["change_boards", "change_board_members"])
async def test_boards_are_isolated_by_rls(world: World, table: str) -> None:
    a, b = world.a, world.b
    assert (await add(world, a, a.admin)).status_code == 201
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one() > 0  # noqa: S608 - fixed table names
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        seen = await session.execute(
            text(f"SELECT count(*) FROM {table} WHERE tenant_id = :a"),  # noqa: S608 - fixed table names
            {"a": a.tenant},
        )
        assert seen.scalar_one() == 0
        changed = await session.execute(
            text(f"UPDATE {table} SET tenant_id = tenant_id WHERE tenant_id = :a"),  # noqa: S608 - fixed table names
            {"a": a.tenant},
        )
        assert changed.rowcount == 0
    listed = await world.call("GET", BOARDS, b, b.admin)
    assert "Network CAB" not in {x["name"] for x in listed.json()}


async def test_tenant_b_cannot_write_a_board_for_tenant_a(world: World) -> None:
    with pytest.raises(DBAPIError):
        async with world.app.state.db.tenant_session(TenantContext(world.b.tenant)) as session:
            await session.execute(
                text("INSERT INTO change_boards (id, tenant_id, name) VALUES (:i, :t, 'Theirs')"),
                {"i": uuid.uuid4(), "t": world.a.tenant},
            )
