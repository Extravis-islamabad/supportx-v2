"""The connector catalogue over HTTP (WP-040 session 1; REQ-INT-001, REQ-INT-013, REQ-INT-003).

Same world as test_mailboxes_api.py: two tenants, an admin and technicians in each.
"""

import uuid
from typing import Any

import pytest

from tests.db.test_incidents_api import World, world
from tests.db.test_mailboxes_api import add, with_key_ring

__all__ = ["world"]  # fixture, re-used

pytestmark = [pytest.mark.db]

CATALOGUE = "/integrations/catalogue"


def _kind(body: list[dict[str, Any]], code: str) -> dict[str, Any]:
    (kind,) = [k for k in body if k["code"] == code]
    return kind


async def test_a_technician_sees_the_catalogue_read_only_with_the_reason(world: World) -> None:
    with_key_ring(world)
    assert (await add(world)).status_code == 201
    seen = await world.call("GET", CATALOGUE, world.a, world.a.tech_a)
    assert seen.status_code == 200, seen.text
    mailbox = _kind(seen.json(), "mailbox")
    assert (mailbox["category"], mailbox["available"]) == ("email", True)
    assert (mailbox["can_manage"], mailbox["manage_reason"]) == (False, "no_permission")
    assert [i["name"] for i in mailbox["instances"]] == ["it@alpha.test"]
    admin = _kind((await world.call("GET", CATALOGUE, world.a, world.a.admin)).json(), "mailbox")
    assert (admin["can_manage"], admin["manage_reason"]) == (True, None)


async def test_status_follows_the_mailbox_and_no_secret_is_returned(world: World) -> None:
    with_key_ring(world)
    created = (await add(world)).json()
    mailbox_id = uuid.UUID(created["id"])

    async def instance() -> dict[str, Any]:
        response = await world.call("GET", CATALOGUE, world.a, world.a.admin)
        assert "s3cret-imap" not in response.text  # REQ-INT-003 AC1
        instances: list[dict[str, Any]] = _kind(response.json(), "mailbox")["instances"]
        (only,) = instances
        return only

    assert ((await instance())["status"], (await instance())["reason"]) == ("not_set_up", None)
    await world.sql(
        "UPDATE mailboxes SET state = 'failing', state_reason = 'imap_login_failed' WHERE id = $1",
        mailbox_id,
    )
    failed = await instance()
    assert (failed["status"], failed["reason"]) == ("failed", "imap_login_failed")
    assert failed["last_success_at"] is None  # a failing fetch is not a success
    await world.sql(
        "UPDATE mailboxes SET state = 'working', state_reason = NULL, last_fetch_at = now()"
        " WHERE id = $1",
        mailbox_id,
    )
    working = await instance()
    assert working["status"] == "active"
    assert working["last_success_at"] is not None
    await world.sql("UPDATE mailboxes SET enabled = false WHERE id = $1", mailbox_id)
    paused = await instance()
    assert (paused["status"], paused["next_run_at"]) == ("paused", None)


async def test_another_tenants_connectors_never_show(world: World) -> None:
    with_key_ring(world)
    assert (await add(world)).status_code == 201
    other = await world.call("GET", CATALOGUE, world.b, world.b.admin)
    assert other.status_code == 200, other.text
    assert _kind(other.json(), "mailbox")["instances"] == []


async def test_requesters_never_see_the_catalogue(world: World) -> None:
    refused = await world.call("GET", CATALOGUE, world.a, world.a.requester)
    assert refused.status_code == 403


async def _role_with(world: World, user: uuid.UUID, permission: str) -> None:
    created = await world.call(
        "POST",
        "/roles",
        world.a,
        world.a.admin,
        json={
            "name": f"Mail {permission}",
            "permissions": [{"permission": permission, "scope": "all"}],
        },
    )
    assert created.status_code == 201, created.text
    assigned = await world.call(
        "PUT", f"/users/{user}/roles/{created.json()['id']}", world.a, world.a.admin
    )
    assert assigned.status_code in {200, 204}, assigned.text


@pytest.mark.parametrize("permission", ["integrations.manage_email", "mailboxes.manage"])
async def test_either_email_key_sets_mailboxes_up_during_the_move(
    world: World, permission: str
) -> None:
    """REQ-INT-013: the new per-category key works, and the old one until the contract step."""
    with_key_ring(world)
    assert (
        await world.call("GET", "/integrations/mailboxes", world.a, world.a.tech_b)
    ).status_code == 403
    await _role_with(world, world.a.tech_b, permission)
    assert (
        await world.call("GET", "/integrations/mailboxes", world.a, world.a.tech_b)
    ).status_code == 200
    seen = await world.call("GET", CATALOGUE, world.a, world.a.tech_b)
    assert _kind(seen.json(), "mailbox")["can_manage"] is True


async def test_another_categorys_key_does_not_set_mailboxes_up(world: World) -> None:
    """REQ-INT-013 AC2: one category's set-up rights (here identity) never reach another's."""
    await _role_with(world, world.a.tech_b, "integrations.manage_identity")
    seen = await world.call("GET", CATALOGUE, world.a, world.a.tech_b)
    mailbox = _kind(seen.json(), "mailbox")
    assert (mailbox["can_manage"], mailbox["manage_reason"]) == (False, "no_permission")
    assert (
        await world.call("GET", "/integrations/mailboxes", world.a, world.a.tech_b)
    ).status_code == 403
