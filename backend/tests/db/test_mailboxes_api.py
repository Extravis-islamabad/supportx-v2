"""Mailboxes over HTTP (WP-024; REQ-INT-050, REQ-INT-051, REQ-ADM-066).

Same world as test_incidents_api.py, with an installation key ring so passwords can be sealed.
"""

import json
import uuid
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.shared.files.keyring import KeyRing
from tests.db.test_files_api import audit_actions
from tests.db.test_incidents_api import World, field_codes, problem, world

__all__ = ["world"]  # fixture, re-used

pytestmark = [pytest.mark.db]

BASE = "/integrations/mailboxes"
BOX: dict[str, Any] = {
    "address": "IT@alpha.test",
    "host": "imap.alpha.test",
    "username": "it@alpha.test",
    "password": "s3cret-imap",
    "allowed_domains": ["alpha.test"],
}


def with_key_ring(world: World) -> None:
    settings = world.app.state.settings
    world.app.state.settings = settings.model_copy(
        update={"files_keys": SecretStr(KeyRing.generate())}
    )


async def add(world: World, user: uuid.UUID | None = None, **body: Any) -> httpx.Response:  # noqa: ANN401 - JSON
    org = world.a
    return await world.call(
        "POST",
        BASE,
        org,
        user or org.admin,
        json=BOX | body,
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )


async def test_an_admin_adds_a_mailbox_and_its_password_never_comes_back(world: World) -> None:
    with_key_ring(world)
    created = await add(world)
    assert created.status_code == 201, created.text
    body = created.json()
    assert (body["address"], body["state"], body["has_password"]) == (
        "it@alpha.test",
        "not_set_up",
        True,
    )
    assert "password" not in body
    assert "s3cret-imap" not in created.text
    rows = await world.sql(
        "SELECT secret_sealed FROM mailboxes WHERE id = $1", uuid.UUID(body["id"])
    )
    assert b"s3cret-imap" not in bytes(rows[0]["secret_sealed"])
    listed = await world.call("GET", BASE, world.a, world.a.admin)
    assert [m["id"] for m in listed.json()] == [body["id"]]
    assert "mailbox.created" in await audit_actions(world, world.a)
    assert await changes(world, body["id"]) == ["added"]


async def changes(world: World, mailbox_id: str) -> list[str]:
    """The mailbox's events in the outbox: what the mail page refetches on (no address, no mail)."""
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE aggregate_id = $1 ORDER BY id", mailbox_id
    )
    envelopes = [json.loads(r["envelope"]) for r in rows]
    for envelope in envelopes:
        assert set(envelope["payload"]) == {"mailbox_id", "change"}
    return [e["payload"]["change"] for e in envelopes]


async def test_only_mailbox_managers_see_or_change_mailboxes(world: World) -> None:
    with_key_ring(world)
    assert (await add(world, world.a.tech_a)).status_code == 403
    assert (await world.call("GET", BASE, world.a, world.a.tech_a)).status_code == 403


async def test_mistakes_are_refused_at_the_form(world: World) -> None:
    with_key_ring(world)
    refused = await add(world, security="none", address="no-at-sign")
    assert field_codes(refused) == {
        "security": "plain_connection_refused",
        "address": "mailbox_address_invalid",
    }
    moved = await add(world, after_fetch="move")
    assert field_codes(moved) == {"move_to": "required"}
    assert (await add(world)).status_code == 201
    assert problem(await add(world, address="it@ALPHA.test")) == (409, "mailbox_address_taken")


async def test_without_a_key_ring_nothing_is_stored(world: World) -> None:
    assert problem(await add(world)) == (503, "mailbox_key_ring_missing")


async def test_changes_need_the_version_read_and_reset_the_state(world: World) -> None:
    with_key_ring(world)
    created = (await add(world)).json()
    path = f"{BASE}/{created['id']}"
    stale = await world.call(
        "PATCH", path, world.a, world.a.admin, json={"port": 143}, headers={"If-Match": '"9"'}
    )
    assert problem(stale) == (409, "version_conflict")
    await world.sql(
        "UPDATE mailboxes SET state = 'failing', state_reason = 'imap_login_failed' WHERE id = $1",
        uuid.UUID(created["id"]),
    )
    changed = await world.call(
        "PATCH",
        path,
        world.a,
        world.a.admin,
        json={"password": "new-one"},
        headers={"If-Match": f'"{created["version"]}"'},
    )
    assert changed.status_code == 200, changed.text
    assert (changed.json()["state"], changed.json()["state_reason"]) == ("not_set_up", None)
    assert changed.headers["etag"] == f'"{created["version"] + 1}"'
    gone = await world.call(
        "DELETE", path, world.a, world.a.admin, headers={"If-Match": changed.headers["etag"]}
    )
    assert gone.status_code == 204
    assert (await world.call("GET", BASE, world.a, world.a.admin)).json() == []
    assert await changes(world, created["id"]) == ["added", "changed", "removed"]
    assert problem(await world.call("POST", f"{path}/test", world.a, world.a.admin, json={})) == (
        404,
        "mailbox_not_found",
    )


async def test_a_mailbox_stays_in_its_tenant(world: World) -> None:
    with_key_ring(world)
    created = (await add(world)).json()
    b = world.b
    assert (await world.call("GET", BASE, b, b.admin)).json() == []
    other = await world.call(
        "PATCH",
        f"{BASE}/{created['id']}",
        b,
        b.admin,
        json={"port": 143},
        headers={"If-Match": '"1"'},
    )
    assert problem(other) == (404, "mailbox_not_found")


async def test_testing_an_unreachable_server_says_why(world: World) -> None:
    with_key_ring(world)
    created = (await add(world, host="127.0.0.1", port=1)).json()
    tested = await world.call(
        "POST", f"{BASE}/{created['id']}/test", world.a, world.a.admin, json={}
    )
    assert tested.status_code == 200, tested.text
    assert tested.json() == {"ok": False, "reason": "imap_unreachable"}
