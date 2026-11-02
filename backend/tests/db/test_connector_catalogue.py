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
