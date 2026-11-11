"""Roles the record's own fields hold (QA-2026-11-11 F-02).

A change's requester and owner are its requester and technician. The roles tab, approval levels
and stage rules naming those roles read the record, never a role-holder row: the tab once said
"Nobody yet" beside a header naming the requester. Setting them through the roles endpoint is
refused (they change in the details panel). Releases keep their roles in the holder table only.
"""

import uuid
from typing import Any

import pytest

from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_changes_api import CHG, a_change, move
from tests.db.test_incidents_api import CONSOLE, Org, World, field_codes
from tests.db.test_release_approvals_api import approvals, planning_levels, to_waiting
from tests.db.test_releases_api import REL, a_release

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the fixture, re-used


async def _roles(world: World, org: Org, path: str, item: dict[str, Any]) -> dict[str, Any]:
    got = await world.call("GET", f"{path}/{item['id']}/roles", org, org.admin)
    assert got.status_code == 200, got.text
    return {r["code"]: r for r in got.json()["roles"]}


async def _fresh(world: World, org: Org, item: dict[str, Any]) -> dict[str, Any]:
    return dict((await world.call("GET", f"{CHG}/{item['id']}", org, org.admin)).json())


async def _own(world: World, org: Org, item: dict[str, Any], tech: uuid.UUID) -> dict[str, Any]:
    fresh = await _fresh(world, org, item)
    owned = await world.call(
        "POST",
        f"{CHG}/{item['id']}/assign",
        org,
        org.admin,
        json={"technician_id": str(tech)},
        headers={"If-Match": f'"{fresh["version"]}"', **CONSOLE},
    )
    assert owned.status_code == 200, owned.text
    return await _fresh(world, org, item)


async def _stale_holder(world: World, org: Org, item: dict[str, Any], role: str) -> None:
    """A holder row as an older build could write one (the superuser connection: tenant named)."""
    await world.sql(
        "INSERT INTO work_item_role_holders"
        " (id, tenant_id, work_item_id, type, role, user_id, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, now(), now())",
        uuid.uuid4(),
        org.tenant,
        uuid.UUID(item["id"]),
        item["type"],
        role,
        org.tech_b,
    )


async def test_f02_the_roles_tab_shows_the_change_s_own_requester_and_owner(
    world: World,
) -> None:
    a = world.a
    item = await a_change(world, a)
    shown = await _roles(world, a, CHG, item)
    assert shown["requester"]["user_ids"] == [str(a.requester)]
    assert shown["requester"]["from_record"] is True
    # No owner yet: nobody, even with a stale holder row naming someone else.
    await _stale_holder(world, a, item, "change_owner")
    assert shown["change_owner"]["user_ids"] == []
    assert (await _roles(world, a, CHG, item))["change_owner"]["user_ids"] == []
    owned = await _own(world, a, item, a.tech_a)
    after = await _roles(world, a, CHG, owned)
    assert after["change_owner"]["user_ids"] == [str(a.tech_a)]
    assert after["implementer"]["from_record"] is False
    refused = await world.call(
        "PUT",
        f"{CHG}/{item['id']}/roles/requester",
        a,
        a.admin,
        json={"user_ids": [str(a.tech_b)], "group_ids": []},
        headers={"If-Match": f'"{owned["version"]}"', **CONSOLE},
    )
    assert field_codes(refused).get("role") == "role_held_by_record"


async def test_f02_a_level_naming_the_owner_reaches_the_owner_who_is_then_barred(
    world: World,
) -> None:
    """The level resolves to the change's technician (no longer "nobody holds it"); the owner
    may not approve (REQ-CHG-039), so the administrators decide, and the owner cannot."""
    a = world.a
    version = (await world.call("GET", "/changes/settings", a, a.admin)).json()["version"]
    put = await world.call(
        "PUT",
        "/changes/settings/stages/submission/approvals",
        a,
        a.admin,
        json={
            "approvals": {
                "raised_by": "submission_awaiting_acceptance",
                "approved": "submission_accepted",
                "rejected": "submission_rejected",
                "levels": [{"approvers": [{"role": "change_owner"}]}],
            }
        },
        headers={"If-Match": f'"{version}"', **CONSOLE},
    )
    assert put.status_code == 200, put.text
    item = await _own(world, a, await a_change(world, a), a.tech_a)
    await _stale_holder(world, a, item, "change_owner")  # never the one asked
    assert (await move(world, a, item, "submission_awaiting_acceptance")).status_code == 200
    rows = (await world.call("GET", f"{CHG}/{item['id']}/approvals", a, a.admin)).json()["items"]
    assert [(r["approver_id"], r["route_reason"]) for r in rows] == [
        (None, "segregation_of_duties")
    ]
    for outsider in (a.tech_a, a.tech_b):
        tried = await world.call(
            "POST",
            f"{CHG}/{item['id']}/approvals/{rows[0]['id']}/decision",
            a,
            outsider,
            json={"decision": "approve"},
            headers={"If-Match": f'"{rows[0]["version"]}"', **CONSOLE},
        )
        assert tried.status_code in {403, 404}, tried.text


async def test_f02_releases_keep_their_roles_in_the_holder_table(world: World) -> None:
    """Lane C's check: a release's requester role is not its requester field."""
    a = world.a
    release = await a_release(world, a)
    shown = await _roles(world, a, REL, release)
    assert shown["requester"]["user_ids"] == []
    assert shown["requester"]["from_record"] is False
    await planning_levels(world, a, [{"approvers": [{"role": "requester"}]}])
    rows = await approvals(world, a, await to_waiting(world, a, release))
    assert [(r["approver_id"], r["route_reason"]) for r in rows] == [(None, "no_holder")]
