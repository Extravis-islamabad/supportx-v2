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
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import World, unit

__all__ = ["module_world", "shared_world"]  # fixture, re-used

pytestmark = [pytest.mark.db, MODULE_LOOP]

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
            s,
            world.app.state.settings,
            DIRECTORY | values,
            credential=fake.client_secret,
            by=await world.app.state.policy.subject(world.a.tenant, world.a.admin, s),
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


async def test_a_people_import_leaves_synced_people_alone(
    world: World, fake: FakeDirectory
) -> None:
    from app.modules.identity_access.service.people_import import (  # noqa: PLC0415 - one test
        RowProblem,
        apply_row,
    )

    fake.add_user(**_ada())
    directory_id = await _create(world, fake)
    await _sync(world, directory_id)
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant, world.a.admin)) as s:
        with pytest.raises(RowProblem) as refused:
            await apply_row(
                s, world.a.admin, {"email": "ada@alpha.test", "job_title": "Other"}, "email"
            )
    assert refused.value.code == "managed_by_directory"


async def test_a_returner_without_a_seat_is_counted_and_the_run_goes_on(
    world: World, fake: FakeDirectory
) -> None:
    from tests.db.test_auth_bff import set_technician_seats  # noqa: PLC0415 - one test

    ada = fake.add_user(**_ada())
    bob = fake.add_user(displayName="Bob", mail="bob@alpha.test")
    directory_id = await _create(world, fake)
    await _sync(world, directory_id)
    tech = (await _person(world, directory_id, ada))["id"]
    await world.sql("UPDATE users SET user_type = 'technician' WHERE id = $1", tech)
    fake.change_user(ada, accountEnabled=False)
    await _sync(world, directory_id)
    seats = await world.sql(
        "SELECT count(*) AS n FROM users WHERE tenant_id = $1 AND user_type = 'technician'"
        " AND status = 'active'",
        world.a.tenant,
    )
    await set_technician_seats(world.db, world.a.tenant, seats[0]["n"])  # every seat taken
    await world.app.state.entitlements.invalidate(world.a.tenant)  # the plan changed under it
    fake.change_user(ada, accountEnabled=True)
    fake.change_user(bob, jobTitle="Clerk")
    counts = await _sync(world, directory_id)
    assert counts.failed == 1
    assert (await _person(world, directory_id, ada))["status"] == "disabled"
    assert (await _person(world, directory_id, bob))["job_title"] == "Clerk"  # the run went on
    health = await world.sql(
        "SELECT failing FROM connector_health WHERE instance_id = $1", directory_id
    )
    assert health[0]["failing"] is False


async def test_an_erased_person_is_never_written_revived_or_adopted_again(
    world: World, fake: FakeDirectory
) -> None:
    """D-171: the directory's name and address never come back onto an erased row."""
    carol = fake.add_user(
        displayName="Carol Erased", givenName="Carol", surname="Erased", mail="carol@alpha.test"
    )
    directory_id = await _create(world, fake)
    await _sync(world, directory_id)
    person = await _person(world, directory_id, carol)
    # What the erasure job's steps 1 and 5 leave (ADR-052): disabled, anonymised, erased_at set.
    marker = {
        "display_name": "Erased person 4F2A",
        "first_name": "Erased person",
        "last_name": "4F2A",
        "email": f"erased-{person['id']}@invalid",
    }
    await world.sql(
        "UPDATE users SET display_name = $3, first_name = $4, last_name = $5, email = $6,"
        " status = 'disabled', can_sign_in = false, erased_at = now()"
        " WHERE tenant_id = $1 AND id = $2",
        world.a.tenant,
        person["id"],
        *marker.values(),
    )
    before = await _person(world, directory_id, carol)
    # The directory still has them, enabled, and renames them: nothing comes back.
    fake.change_user(carol, displayName="Carol Again", mail="carol@alpha.test", accountEnabled=True)
    counts = await _sync(world, directory_id)
    after = await _person(world, directory_id, carol)
    assert after == before
    assert {k: after[k] for k in marker} == marker
    assert (after["status"], after["can_sign_in"]) == ("disabled", False)
    assert counts.skipped >= 1
    # Removed in the directory: nothing either (no deactivation of an erased person).
    fake.delete_user(carol)
    await _sync(world, directory_id)
    assert await _person(world, directory_id, carol) == before
    # No other person ever took their address back either (never adopted, never duplicated).
    adopted = await world.sql(
        "SELECT count(*) AS n FROM users WHERE tenant_id = $1 AND lower(email) = $2",
        world.a.tenant,
        "carol@alpha.test",
    )
    assert adopted[0]["n"] == 0


async def test_a_person_frozen_by_a_running_erasure_stays_disabled(
    world: World, fake: FakeDirectory
) -> None:
    """Between step 1 (frozen) and step 5 (erased_at): no sync, no screen reactivates them."""
    dora = fake.add_user(displayName="Dora Frozen", mail="dora@alpha.test")
    directory_id = await _create(world, fake)
    await _sync(world, directory_id)
    person = await _person(world, directory_id, dora)
    # What step 1 leaves: disabled, no sign-in; the erasure approved and running, erased_at unset.
    await world.sql(
        "UPDATE users SET status = 'disabled', can_sign_in = false"
        " WHERE tenant_id = $1 AND id = $2",
        world.a.tenant,
        person["id"],
    )
    erasure_id = uuid.uuid4()
    await world.sql(
        "INSERT INTO person_erasures (id, tenant_id, person_id, state, step, reason_code,"
        " successor_id, keep_files, requested_by, requested_at, expires_at, approved_by,"
        " approved_at) VALUES ($1, $2, $3, 'running', 2, 'subject_request', $4, '{}', $5,"
        " now(), now() + interval '7 days', $6, now())",
        erasure_id,
        world.a.tenant,
        person["id"],
        world.a.tech_c,
        world.a.admin,
        world.a.lead,
    )
    before = await _person(world, directory_id, dora)
    fake.change_user(dora, displayName="Dora Again", accountEnabled=True)
    counts = await _sync(world, directory_id)
    after = await _person(world, directory_id, dora)
    assert after == before
    assert (after["status"], after["can_sign_in"]) == ("disabled", False)
    assert counts.skipped >= 1
    # The people screens cannot reactivate them either (the same refusal in the service).
    tried = await world.call(
        "POST",
        f"/users/{person['id']}/reactivate",
        world.a,
        world.a.admin,
        json={"keep_role_ids": [], "keep_group_ids": []},
        headers={"If-Match": f'"{after["version"]}"'},
    )
    assert (tried.status_code, tried.json()["code"]) == (409, "person_erasure_in_progress")
    assert (await _person(world, directory_id, dora))["status"] == "disabled"
