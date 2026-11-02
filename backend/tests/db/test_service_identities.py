"""Service identities (WP-040 session 2; REQ-INT-012): a connector acts in its own name.

Same world as test_mailboxes_api.py. Rule 5 cases: the identity can never sign in, never takes a
seat, never shows in people lists, search or permission holders, cannot be changed or made from
the people screens, and another tenant never sees it.
"""

import uuid

import asyncpg
import pytest
from sqlalchemy import text

from app.core.tenancy import TenantContext
from app.modules.identity_access import worker_policy
from app.modules.identity_access.service.users import count_technicians
from app.modules.integrations.service import fetching, identities
from app.modules.integrations.service.connections import key_ring
from tests.db.test_connector_catalogue import _role_with
from tests.db.test_incidents_api import World, world
from tests.db.test_mail_inbound import FakeReader
from tests.db.test_mailboxes_api import BASE, add, with_key_ring

__all__ = ["world"]  # fixture, re-used

pytestmark = [pytest.mark.db]


async def _identity(world: World, mailbox_id: str) -> dict[str, object]:
    rows = await world.sql(
        "SELECT u.id, u.user_type, u.status, u.email, u.external_subject, u.can_sign_in,"
        " u.display_name, u.invited_at FROM connector_identities c JOIN users u"
        " ON u.tenant_id = c.tenant_id AND u.id = c.user_id"
        " WHERE c.kind = 'mailbox' AND c.instance_id = $1",
        uuid.UUID(mailbox_id),
    )
    (row,) = rows
    return dict(row)


async def test_a_new_mailbox_acts_as_its_own_identity_that_cannot_sign_in(world: World) -> None:
    with_key_ring(world)
    created = (await add(world)).json()
    identity = await _identity(world, created["id"])
    assert identity["user_type"] == "service"
    assert identity["status"] == "active"
    assert identity["display_name"] == "it@alpha.test"
    assert (identity["email"], identity["external_subject"]) == (None, None)
    assert (identity["can_sign_in"], identity["invited_at"]) == (False, None)
    # Its own role and scope: none until given (it may do nothing).
    roles = await world.sql("SELECT role_id FROM user_roles WHERE user_id = $1", identity["id"])
    assert roles == []
    history = await world.sql(
        "SELECT source FROM field_changes WHERE record_type = 'user' AND record_id = $1",
        str(identity["id"]),
    )
    assert {r["source"] for r in history} == {"integration"}
    event = await world.sql(
        "SELECT envelope->'payload' AS payload FROM outbox_events"
        " WHERE event_type = 'identity_access.user.created' AND aggregate_id = $1",
        str(identity["id"]),
    )
    assert len(event) == 1


async def test_the_database_refuses_a_service_identity_with_a_way_to_sign_in(
    world: World,
) -> None:
    with_key_ring(world)
    identity = await _identity(world, (await add(world)).json()["id"])
    for change in (
        "email = 'svc@alpha.test'",
        "external_subject = 'kc-svc'",
        "can_sign_in = true",
    ):
        with pytest.raises(asyncpg.CheckViolationError):
            await world.sql(f"UPDATE users SET {change} WHERE id = $1", identity["id"])  # noqa: S608 - fixed text


async def test_it_takes_no_seat_and_is_never_in_people_lists_search_or_holders(
    world: World,
) -> None:
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        seats = await count_technicians(session)
    with_key_ring(world)
    identity = await _identity(world, (await add(world)).json()["id"])
    # Give it a role with a permission, so only the exclusion keeps it out of holders.
    await _role_with(world, uuid.UUID(str(identity["id"])), "integrations.manage_email")
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        assert await count_technicians(session) == seats
        holders = await worker_policy().holders(
            session, world.a.tenant, "integrations.manage_email", limit=200
        )
    assert identity["id"] not in {user_id for user_id, _ in holders}
    listed = await world.call("GET", "/users?limit=200", world.a, world.a.admin)
    assert listed.status_code == 200, listed.text
    assert str(identity["id"]) not in listed.text
    searched = await world.call("GET", "/users?q=alpha", world.a, world.a.admin)
    assert searched.status_code == 200, searched.text
    assert str(identity["id"]) not in searched.text


async def test_the_people_screens_cannot_change_or_make_one(world: World) -> None:
    with_key_ring(world)
    identity = await _identity(world, (await add(world)).json()["id"])
    user = f"/users/{identity['id']}"
    for method, path, body in (
        ("PATCH", f"{user}/person", {"job_title": "Bot"}),
        ("PUT", f"{user}/type", {"user_type": "technician"}),
        ("POST", f"{user}/deactivate", None),
    ):
        refused = await world.call(
            method, path, world.a, world.a.admin, json=body, headers={"If-Match": '"1"'}
        )
        assert refused.status_code == 409, (path, refused.text)
        assert refused.json()["code"] == "service_identity_managed"
    made = await world.call(
        "POST",
        "/users",
        world.a,
        world.a.admin,
        json={"first_name": "Bot", "user_type": "service", "can_sign_in": False},
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )
    assert made.status_code == 422, made.text


async def test_removing_the_mailbox_disables_its_identity_and_keeps_it(world: World) -> None:
    with_key_ring(world)
    created = (await add(world)).json()
    path = f"{BASE}/{created['id']}"
    gone = await world.call(
        "DELETE", path, world.a, world.a.admin, headers={"If-Match": f'"{created["version"]}"'}
    )
    assert gone.status_code == 204, gone.text
    identity = await _identity(world, created["id"])
    assert (identity["user_type"], identity["status"]) == ("service", "disabled")
    sources = await world.sql(
        "SELECT source FROM field_changes WHERE record_type = 'user' AND record_id = $1"
        " AND kind = 'status'",
        str(identity["id"]),
    )
    assert [r["source"] for r in sources] == ["integration"]


async def test_a_mailbox_from_before_gets_its_identity_at_its_next_run(world: World) -> None:
    with_key_ring(world)
    created = (await add(world)).json()
    mailbox_id = uuid.UUID(created["id"])
    # As before WP-040 session 2: no identity yet (the owner role removes the link).
    await world.sql("DELETE FROM connector_identities WHERE instance_id = $1", mailbox_id)
    ring = key_ring(world.app.state.settings)
    assert ring is not None

    async def run() -> None:
        await fetching.fetch_mailbox(
            world.app.state.db,
            world.app.state.settings,
            world.a.tenant,
            mailbox_id,
            ring=ring,
            reader=FakeReader([]),
        )

    await run()
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        first = await identities.identity_of(session, "mailbox", mailbox_id)
    assert first is not None
    await run()
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        assert await identities.identity_of(session, "mailbox", mailbox_id) == first  # once


async def test_another_tenant_never_sees_a_connectors_identity(world: World) -> None:
    with_key_ring(world)
    identity = await _identity(world, (await add(world)).json()["id"])
    async with world.app.state.db.tenant_session(TenantContext(world.b.tenant)) as session:
        rows = (await session.execute(text("SELECT user_id FROM connector_identities"))).all()
        assert rows == []
        found = await session.execute(
            text("SELECT id FROM users WHERE id = :id"), {"id": identity["id"]}
        )
        assert found.all() == []
    other = await world.call("GET", f"/users/{identity['id']}", world.b, world.b.admin)
    assert other.status_code == 404
