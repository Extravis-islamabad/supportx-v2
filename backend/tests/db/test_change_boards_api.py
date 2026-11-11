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
from tests.db.test_incidents_api import CONSOLE, Org, World, field_codes, problem, role, world

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
    # The board screen names its people, never an ID; groups are named by the group list.
    assert set(board["people"]) == {str(a.lead)}
    assert board["people"][str(a.lead)]["display_name"]
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


# --- boards on approval levels (WP-045b S3; REQ-CHG-041, -042) ---------------------------------


async def acceptance_by_board(world: World, org: Org, board: str = "mapped") -> None:
    """The submission stage's one level is a board (the mapped one by default)."""
    version = (await world.call("GET", "/changes/settings", org, org.admin)).json()["version"]
    response = await world.call(
        "PUT",
        "/changes/settings/stages/submission/approvals",
        org,
        org.admin,
        json={
            "approvals": {
                "raised_by": "submission_awaiting_acceptance",
                "approved": "submission_accepted",
                "rejected": "submission_rejected",
                "levels": [{"approvers": [{"board": board}]}],
            }
        },
        headers={"If-Match": f'"{version}"', **CONSOLE},
    )
    assert response.status_code == 200, response.text


async def raised(world: World, org: Org, **body: Any) -> list[dict[str, Any]]:  # noqa: ANN401 - JSON
    from tests.db.test_changes_api import move, new_change  # noqa: PLC0415 - shared helpers

    made = await new_change(world, org, org.admin, **body)
    assert made.status_code == 201, made.text
    moved = await move(world, org, made.json(), "submission_awaiting_acceptance")
    assert moved.status_code == 200, moved.text
    listed = await world.call("GET", f"/changes/{made.json()['id']}/approvals", org, org.admin)
    return list(listed.json()["items"])


async def test_req_chg_041_ac1_the_mapped_board_approves_by_its_rule(world: World) -> None:
    a = world.a
    await acceptance_by_board(world, a)
    board = await add(
        world,
        a,
        a.admin,
        rule="all",
        mapping={"change_types": ["normal"]},
        members=[{"user_id": str(a.lead)}, {"user_id": str(a.tech_b)}],
    )
    assert board.status_code == 201, board.text
    rows = await raised(world, a, change_type="normal")
    assert {(r["approver_id"], r["rule"], r["board_id"], r["board_reason"]) for r in rows} == {
        (str(a.lead), "all", board.json()["id"], "mapped"),
        (str(a.tech_b), "all", board.json()["id"], "mapped"),
    }


async def test_req_chg_041_ac2_the_default_board_without_members_routes_to_admins(
    world: World,
) -> None:
    a = world.a
    await acceptance_by_board(world, a)
    [row] = await raised(world, a)
    assert (row["approver_id"], row["route_reason"], row["board_reason"]) == (
        None,
        "board_has_no_members",
        "default",
    )


async def test_a_level_names_a_board_that_exists(world: World) -> None:
    a = world.a
    version = (await world.call("GET", "/changes/settings", a, a.admin)).json()["version"]
    refused = await world.call(
        "PUT",
        "/changes/settings/stages/submission/approvals",
        a,
        a.admin,
        json={
            "approvals": {
                "raised_by": "submission_awaiting_acceptance",
                "approved": "submission_accepted",
                "rejected": "submission_rejected",
                "levels": [{"approvers": [{"board": str(uuid.uuid4())}]}],
            }
        },
        headers={"If-Match": f'"{version}"', **CONSOLE},
    )
    assert field_codes(refused) == {"approvals.levels": "board_not_found"}


async def test_an_optional_members_vote_is_advisory_and_never_counts(world: World) -> None:
    """Haider: an optional member may record a reject; the level's outcome ignores it."""
    a = world.a
    await acceptance_by_board(world, a)
    made = await add(
        world,
        a,
        a.admin,
        rule="any",
        mapping={"change_types": ["normal"]},
        members=[{"user_id": str(a.lead)}, {"user_id": str(a.tech_b), "optional": True}],
    )
    assert made.status_code == 201, made.text
    rows = await raised(world, a, change_type="normal")
    by_person = {r["approver_id"]: r for r in rows}
    assert (by_person[str(a.lead)]["advisory"], by_person[str(a.tech_b)]["advisory"]) == (
        False,
        True,
    )
    [change] = (await world.call("GET", "/changes", a, a.admin)).json()["items"]  # the one made
    advisory = by_person[str(a.tech_b)]
    rejected = await world.call(
        "POST",
        f"/changes/{change['id']}/approvals/{advisory['id']}/decision",
        a,
        a.tech_b,
        json={"decision": "reject", "comment": "Weekend freeze"},
        headers={"If-Match": f'"{advisory["version"]}"', **CONSOLE},
    )
    assert rejected.status_code == 200, rejected.text
    still = (await world.call("GET", f"/changes/{change['id']}", a, a.admin)).json()
    assert still["status"] == "submission_awaiting_acceptance"  # the reject changed nothing
    counted = by_person[str(a.lead)]
    approved = await world.call(
        "POST",
        f"/changes/{change['id']}/approvals/{counted['id']}/decision",
        a,
        a.lead,
        json={"decision": "approve"},
        headers={"If-Match": f'"{counted["version"]}"', **CONSOLE},
    )
    assert approved.status_code == 200, approved.text
    done = (await world.call("GET", f"/changes/{change['id']}", a, a.admin)).json()
    assert done["stage"] == "planning"


async def test_boards_are_managed_by_the_change_manager_right_not_desk_config(
    world: World,
) -> None:
    """Haider (2026-11-10): the change manager and administrators run the boards, not every
    service desk configurer. Holding config.service_desk alone may read them, not change them."""
    a = world.a
    desk = await role(world, a, "Desk config", [("config.service_desk", "all")])
    boards = await role(world, a, "Board keeper", [("changes.manage_boards", "all")])
    for user, granted in ((a.tech_a, desk), (a.tech_b, boards)):
        given = await world.call("PUT", f"/users/{user}/roles/{granted}", a, a.admin)
        assert given.status_code == 204, given.text
    assert problem(await add(world, a, a.tech_a, name="Network board")) == (
        403,
        "permission_denied",
    )
    made = await add(world, a, a.tech_b, name="Network board")
    assert made.status_code == 201, made.text
