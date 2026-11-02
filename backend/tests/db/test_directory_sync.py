"""Directory sync from Entra ID against a fake Graph (WP-040 session 2; REQ-INT-063, REQ-INT-064).

Same world as test_incidents_api.py. No real directory or account. Rule 5 cases: synced people
are made by the connector's own identity, leavers are disabled and never deleted (their sessions
end), the last administrator is never deactivated by a sync, fields the directory owns cannot be
changed on the people screens, a refused secret fails at once, and another tenant sees nothing.
"""

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import TextClause, text

from app.core.tenancy import TenantContext
from app.modules.integrations.domain.connector_health import RunCounts
from app.modules.integrations.service import connections, directories, directory_sync
from app.modules.integrations.tests.fake_directory import FakeDirectory, graph_id
from app.modules.integrations.tests.fake_providers import endpoint_settings
from app.shared.files.keyring import KeyRing
from tests.db.test_incidents_api import World, unit, world

__all__ = ["world"]  # fixture, re-used

pytestmark = [pytest.mark.db]

DIRECTORY = {
    "name": "Alpha Entra",
    "directory_tenant": "alpha.onmicrosoft.com",
    "client_id": "11111111-2222-3333-4444-555555555555",
    "credential_kind": "secret",
    "scope": "all_users",
}


@pytest.fixture
async def fake(world: World) -> AsyncIterator[FakeDirectory]:
    directory = FakeDirectory(client_id=DIRECTORY["client_id"], page_size=2)
    settings = world.app.state.settings
    world.app.state.settings = settings.model_copy(
        update={"files_keys": SecretStr(KeyRing.generate()), **endpoint_settings()}
    )
    connections.use_transport(directory.transport())
    yield directory
    connections.use_transport(None)


async def _create(world: World, fake: FakeDirectory, **values: Any) -> uuid.UUID:  # noqa: ANN401 - JSON
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant, world.a.admin)) as s:
        view = await directories.create_directory(
            s, world.app.state.settings, DIRECTORY | values, credential=fake.client_secret
        )
    return view.row.id


ENDED: list[tuple[uuid.UUID, uuid.UUID]] = []


async def _end(tenant: uuid.UUID, user: uuid.UUID) -> None:
    ENDED.append((tenant, user))


async def _sync(world: World, directory_id: uuid.UUID) -> RunCounts:
    async def no_wait(_seconds: float) -> None:
        return None

    settings = world.app.state.settings
    ring = connections.key_ring(settings)
    assert ring is not None
    counts = await directory_sync.sync_directory(
        world.app.state.db,
        settings,
        world.a.tenant,
        directory_id,
        ring=ring,
        end_sessions=_end,
        sleep=no_wait,
    )
    assert counts is not None
    return counts


async def _person(world: World, directory_id: uuid.UUID, external_id: str) -> dict[str, Any]:
    rows = await world.sql(
        "SELECT u.* FROM directory_people d JOIN users u ON u.tenant_id = d.tenant_id"
        " AND u.id = d.user_id WHERE d.connector_id = $1 AND d.external_id = $2",
        directory_id,
        external_id,
    )
    (row,) = rows
    return dict(row)


def _ada(**more: Any) -> dict[str, Any]:  # noqa: ANN401 - Graph attributes
    return {
        "displayName": "Ada Lovelace",
        "givenName": "Ada",
        "surname": "Lovelace",
        "mail": "ada@alpha.test",
        "userPrincipalName": "ada@alpha.onmicrosoft.com",
        "jobTitle": "Analyst",
        "employeeId": "E-100",
        "officeLocation": "London",
        **more,
    }


async def test_a_first_sync_creates_people_as_the_connector_with_reasons_for_the_rest(
    world: World, fake: FakeDirectory
) -> None:
    london = await unit(world, world.a, "sites", "London", [])
    ada = fake.add_user(**_ada())
    fake.add_user(displayName="Guest", mail="g@partner.test", userType="Guest")
    fake.add_user(displayName="No mail", mail=None, userPrincipalName="nobody")
    fake.add_user(displayName="Bob", mail="bob@alpha.test", officeLocation="Atlantis")
    directory_id = await _create(world, fake)
    counts = await _sync(world, directory_id)
    assert (counts.read, counts.created, counts.skipped, counts.failed) == (4, 2, 2, 0)
    person = await _person(world, directory_id, ada)
    assert (person["email"], person["first_name"], person["job_title"]) == (
        "ada@alpha.test",
        "Ada",
        "Analyst",
    )
    assert person["site_id"] == london
    assert person["directory_source"] == "entra"
    assert (person["user_type"], person["status"], person["can_sign_in"]) == (
        "requester",
        "active",
        True,
    )
    identity = await world.sql(
        "SELECT user_id FROM connector_identities WHERE kind = 'directory' AND instance_id = $1",
        directory_id,
    )
    assert person["created_by"] == identity[0]["user_id"]  # made in the connector's own name
    history = await world.sql(
        "SELECT DISTINCT source FROM field_changes WHERE record_type = 'user' AND record_id = $1",
        str(person["id"]),
    )
    assert [r["source"] for r in history] == ["integration"]
    connector = await world.sql(
        "SELECT last_skips, users_delta_link IS NOT NULL AS linked, last_synced_at"
        " FROM directory_connectors WHERE id = $1",
        directory_id,
    )
    assert connector[0]["linked"]
    assert connector[0]["last_synced_at"] is not None
    skips = json.loads(connector[0]["last_skips"])
    assert skips == {"guest": 1, "no_address": 1, "unknown_site": 1}


async def test_an_existing_person_with_the_address_is_adopted_never_duplicated(
    world: World, fake: FakeDirectory
) -> None:
    await world.sql("UPDATE users SET email = 'ada@alpha.test' WHERE id = $1", world.a.requester)
    ada = fake.add_user(**_ada())
    directory_id = await _create(world, fake)
    counts = await _sync(world, directory_id)
    assert (counts.created, counts.updated) == (0, 1)
    person = await _person(world, directory_id, ada)
    assert person["id"] == world.a.requester
    assert person["job_title"] == "Analyst"
    same = await world.sql(
        "SELECT count(*) AS n FROM users WHERE tenant_id = $1 AND lower(email) = 'ada@alpha.test'",
        world.a.tenant,
    )
    assert same[0]["n"] == 1


async def test_changes_come_by_delta_and_directory_fields_are_read_only_in_supportx(
    world: World, fake: FakeDirectory
) -> None:
    ada = fake.add_user(**_ada())
    directory_id = await _create(world, fake)
    await _sync(world, directory_id)
    fake.change_user(ada, jobTitle="Lead analyst")
    counts = await _sync(world, directory_id)
    assert (counts.read, counts.updated, counts.created) == (1, 1, 0)
    person = await _person(world, directory_id, ada)
    assert person["job_title"] == "Lead analyst"
    path = f"/users/{person['id']}/person"
    headers = {"If-Match": f'"{person["version"]}"'}
    refused = await world.call(
        "PATCH", path, world.a, world.a.admin, json={"job_title": "Boss"}, headers=headers
    )
    assert refused.status_code == 422, refused.text
    assert refused.json()["errors"][0]["code"] == "managed_by_directory"
    local = await world.call(
        "PATCH", path, world.a, world.a.admin, json={"vip": True}, headers=headers
    )
    assert local.status_code == 200, local.text  # what SupportX keeps stays editable


async def test_leavers_are_disabled_never_deleted_and_come_back_when_enabled(
    world: World, fake: FakeDirectory
) -> None:
    ada = fake.add_user(**_ada())
    bob = fake.add_user(displayName="Bob", mail="bob@alpha.test")
    directory_id = await _create(world, fake)
    await _sync(world, directory_id)
    ENDED.clear()
    fake.delete_user(ada)
    fake.change_user(bob, accountEnabled=False)
    await _sync(world, directory_id)
    for external in (ada, bob):
        person = await _person(world, directory_id, external)
        assert (person["status"], person["deleted_at"]) == ("disabled", None)
        assert (world.a.tenant, person["id"]) in ENDED  # their sessions end
    events = await world.sql(
        "SELECT envelope->'payload' AS p FROM outbox_events"
        " WHERE event_type = 'identity_access.user.status_changed' AND tenant_id = $1",
        world.a.tenant,
    )
    payloads = [e["p"] for e in events]
    directory = [p for p in map(json.loads, payloads) if p["reason"] == "directory"]
    assert [p["source"] for p in directory] == ["entra", "entra"]
    fake.change_user(bob, accountEnabled=True)
    await _sync(world, directory_id)
    assert (await _person(world, directory_id, bob))["status"] == "active"


async def test_the_last_administrator_is_never_deactivated_by_a_sync(
    world: World, fake: FakeDirectory
) -> None:
    await world.sql("UPDATE users SET email = 'boss@alpha.test' WHERE id = $1", world.a.admin)
    boss = fake.add_user(displayName="Boss", mail="boss@alpha.test")
    directory_id = await _create(world, fake)
    await _sync(world, directory_id)
    fake.change_user(boss, accountEnabled=False)
    await _sync(world, directory_id)
    assert (await _person(world, directory_id, boss))["status"] == "active"
    skips = await world.sql(
        "SELECT last_skips FROM directory_connectors WHERE id = $1", directory_id
    )
    assert json.loads(skips[0]["last_skips"]) == {"last_admin_kept": 1}


async def test_scope_groups_and_mapped_groups_follow_the_directory(
    world: World, fake: FakeDirectory
) -> None:
    ada = fake.add_user(**_ada())
    bob = fake.add_user(displayName="Bob", mail="bob@alpha.test")
    fake.add_user(displayName="Cy", mail="cy@alpha.test")  # in no chosen group: not synced
    staff = fake.add_group("Staff", [ada, bob])
    finance = fake.add_group("Finance", [ada])
    team = await unit(world, world.a, "groups", "Finance team", [])
    directory_id = await _create(
        world,
        fake,
        scope="groups",
        scope_groups=[{"external_id": staff, "name": "Staff"}],
        group_mappings=[{"external_id": finance, "name": "Finance", "group_id": str(team)}],
    )
    counts = await _sync(world, directory_id)
    assert counts.created == 2
    synced = await world.sql(
        "SELECT external_id FROM directory_people WHERE connector_id = $1", directory_id
    )
    assert {r["external_id"] for r in synced} == {ada, bob}
    members = await world.sql("SELECT user_id FROM group_members WHERE group_id = $1", team)
    assert [m["user_id"] for m in members] == [(await _person(world, directory_id, ada))["id"]]
    fake.set_members(staff, [ada])  # Bob leaves the only scope group
    fake.set_members(finance, [])  # Ada leaves the mapped group
    await _sync(world, directory_id)
    assert (await _person(world, directory_id, bob))["status"] == "disabled"
    assert await world.sql("SELECT user_id FROM group_members WHERE group_id = $1", team) == []


async def test_managers_resolve_after_everyone_of_the_round_exists(
    world: World, fake: FakeDirectory
) -> None:
    boss_id = graph_id()
    # Sorted by ID in the fake, staff before boss: the manager comes later in the round.
    staff = fake.add_user(
        id="00000000-0000-4000-8000-000000000001", **_ada(manager={"id": boss_id})
    )
    fake.add_user(id=boss_id, displayName="Boss", mail="boss2@alpha.test")
    directory_id = await _create(world, fake)
    await _sync(world, directory_id)
    person = await _person(world, directory_id, staff)
    boss = await _person(world, directory_id, boss_id)
    assert person["manager_id"] == boss["id"]


async def test_a_refused_secret_fails_at_once_and_an_expired_link_starts_over(
    world: World, fake: FakeDirectory
) -> None:
    fake.add_user(**_ada())
    directory_id = await _create(world, fake)
    fake.client_secret = "rotated-elsewhere"
    counts = await _sync(world, directory_id)
    assert counts.created == 0
    health = await world.sql(
        "SELECT failing, last_error_code FROM connector_health WHERE instance_id = $1",
        directory_id,
    )
    assert (health[0]["failing"], health[0]["last_error_code"]) == (True, "oauth_client_rejected")
    fake.client_secret = "sync-s3cret"  # the stored one works again
    await _sync(world, directory_id)
    fake.expire_links = True
    await _sync(world, directory_id)
    links = await world.sql(
        "SELECT users_delta_link FROM directory_connectors WHERE id = $1", directory_id
    )
    assert links[0]["users_delta_link"] is None  # the next round reads everyone again


async def test_another_tenant_never_sees_a_directory_or_its_people(
    world: World, fake: FakeDirectory
) -> None:
    fake.add_user(**_ada())
    directory_id = await _create(world, fake)
    await _sync(world, directory_id)
    async with world.app.state.db.tenant_session(TenantContext(world.b.tenant)) as session:
        for table in ("directory_connectors", "directory_people", "directory_memberships"):
            rows = (await session.execute(_count(table))).scalar_one()
            assert rows == 0, table
        with pytest.raises(Exception, match="directory_not_found"):
            await directories.get_directory(session, directory_id)


def _count(table: str) -> TextClause:
    return text(f"SELECT count(*) FROM {table}")  # noqa: S608 - fixed table names
