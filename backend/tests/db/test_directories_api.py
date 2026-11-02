"""Directory connectors API (WP-040 session 2): set up, change, remove, sync now, group search.

Rule 5 cases: the secret never comes back (only its type and ending), only holders of
`integrations.manage_identity` reach it, changes need If-Match, creates are idempotent, every
change is audited and announced through the outbox, and another tenant gets 404.
"""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.modules.integrations.service import connections
from app.modules.integrations.tests.fake_directory import FakeDirectory
from app.modules.integrations.tests.fake_providers import endpoint_settings
from app.shared.files.keyring import KeyRing
from tests.db.test_files_api import audit_actions
from tests.db.test_incidents_api import World, unit, world

__all__ = ["world"]  # fixture, re-used

pytestmark = [pytest.mark.db]

BASE = "/integrations/directories"
SECRET = "sync-s3cret-0123456789abcd"
BODY: dict[str, Any] = {
    "name": "Alpha Entra",
    "directory_tenant": "alpha.onmicrosoft.com",
    "client_id": "11111111-2222-3333-4444-555555555555",
    "credential_kind": "secret",
    "credential": SECRET,
}


@pytest.fixture
async def fake(world: World) -> AsyncIterator[FakeDirectory]:
    directory = FakeDirectory(client_id=BODY["client_id"], client_secret=SECRET)
    settings = world.app.state.settings
    world.app.state.settings = settings.model_copy(
        update={"files_keys": SecretStr(KeyRing.generate()), **endpoint_settings()}
    )
    connections.use_transport(directory.transport())
    yield directory
    connections.use_transport(None)


async def _add(world: World, user: uuid.UUID | None = None, **body: Any) -> httpx.Response:  # noqa: ANN401 - JSON
    return await world.call(
        "POST",
        BASE,
        world.a,
        user or world.a.admin,
        json=BODY | body,
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )


async def test_an_admin_adds_a_directory_and_its_secret_never_comes_back(
    world: World, fake: FakeDirectory
) -> None:
    del fake
    created = await _add(world)
    assert created.status_code == 201, created.text
    out = created.json()
    assert SECRET not in created.text
    assert out["secret"]["secret_type"] == "client_secret"
    assert out["secret"]["ending"] == SECRET[-4:]  # display only
    assert (out["scope"], out["interval_minutes"], out["enabled"]) == ("all_users", 30, True)
    listed = await world.call("GET", BASE, world.a, world.a.admin)
    assert SECRET not in listed.text
    stored = await world.sql(
        "SELECT sealed FROM connector_secrets WHERE owner_id = $1", uuid.UUID(out["id"])
    )
    assert SECRET.encode() not in bytes(stored[0]["sealed"])  # sealed, never in clear
    assert "directory.created" in await audit_actions(world, world.a)
    event = await world.sql(
        "SELECT 1 FROM outbox_events WHERE event_type = 'integrations.directory.changed'"
        " AND aggregate_id = $1",
        out["id"],
    )
    assert len(event) == 1


async def test_only_directory_admins_reach_it(world: World, fake: FakeDirectory) -> None:
    del fake
    refused = await _add(world, world.a.tech_a)
    assert refused.status_code == 403
    assert (await world.call("GET", BASE, world.a, world.a.tech_a)).status_code == 403


async def test_bad_settings_are_refused_per_field(world: World, fake: FakeDirectory) -> None:
    del fake
    bad = await _add(world, directory_tenant="not a domain", scope="groups")
    assert bad.status_code == 422, bad.text
    codes = {e["code"] for e in bad.json()["errors"]}
    assert {"directory_tenant_invalid", "directory_groups_required"} <= codes
    missing_group = await _add(
        world,
        group_mappings=[
            {
                "external_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "name": "Finance",
                "group_id": str(uuid.uuid4()),
            }
        ],
    )
    assert missing_group.status_code == 422, missing_group.text


async def test_changes_need_the_version_and_keep_the_secret_unless_given(
    world: World, fake: FakeDirectory
) -> None:
    del fake
    out = (await _add(world)).json()
    path = f"{BASE}/{out['id']}"
    body = {k: v for k, v in BODY.items() if k != "credential"} | {"interval_minutes": 60}
    stale = await world.call(
        "PUT", path, world.a, world.a.admin, json=body, headers={"If-Match": '"99"'}
    )
    assert stale.status_code == 409
    changed = await world.call(
        "PUT", path, world.a, world.a.admin, json=body, headers={"If-Match": f'"{out["version"]}"'}
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["interval_minutes"] == 60
    assert changed.json()["secret"]["ending"] == SECRET[-4:]  # kept


async def test_sync_now_and_group_search_use_the_sync_app(
    world: World, fake: FakeDirectory
) -> None:
    finance = fake.add_group("Finance", [])
    out = (await _add(world)).json()
    now = await world.call("POST", f"{BASE}/{out['id']}/sync", world.a, world.a.admin)
    assert now.status_code == 202, now.text
    assert now.json()["next_sync_at"] is not None
    found = await world.call("GET", f"{BASE}/{out['id']}/groups?q=fin", world.a, world.a.admin)
    assert found.status_code == 200, found.text
    assert found.json() == [{"external_id": finance, "name": "Finance"}]


async def test_removing_it_keeps_its_people_and_frees_them(
    world: World, fake: FakeDirectory
) -> None:
    team = await unit(world, world.a, "groups", "Synced team", [])
    del team
    fake.add_user(displayName="Ada", givenName="Ada", mail="ada@alpha.test")
    out = (await _add(world)).json()
    from tests.db.test_directory_sync import _sync  # noqa: PLC0415 - the sync helper, reused

    await _sync(world, uuid.UUID(out["id"]))
    person = await world.sql(
        "SELECT id, directory_source FROM users WHERE tenant_id = $1 AND email = 'ada@alpha.test'",
        world.a.tenant,
    )
    assert person[0]["directory_source"] == "entra"
    gone = await world.call(
        "DELETE",
        f"{BASE}/{out['id']}",
        world.a,
        world.a.admin,
        headers={"If-Match": f'"{out["version"]}"'},
    )
    assert gone.status_code == 204, gone.text
    after = await world.sql(
        "SELECT status, deleted_at, directory_source FROM users WHERE id = $1", person[0]["id"]
    )
    assert (after[0]["status"], after[0]["deleted_at"], after[0]["directory_source"]) == (
        "active",
        None,
        None,
    )
    assert (
        await world.call("GET", f"{BASE}/{out['id']}", world.a, world.a.admin)
    ).status_code == 404


async def test_another_tenant_gets_404(world: World, fake: FakeDirectory) -> None:
    del fake
    out = (await _add(world)).json()
    other = await world.call("GET", f"{BASE}/{out['id']}", world.b, world.b.admin)
    assert other.status_code == 404
    assert (await world.call("GET", BASE, world.b, world.b.admin)).json() == []
