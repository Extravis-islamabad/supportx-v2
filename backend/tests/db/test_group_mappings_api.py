"""The group mappings API (WP-057 S5c-1a, REQ-SEC-014; lane B's conditions).

- A directory mapping onto a role is created, listed, counted and removed.
- An SSO source waits for S5c-1b (422, labelled); an unknown source is 404.
- Tenant admin, or a support group carrying it, needs the tenant opt-in (409, then allowed). The
  opt-in is audited, and it guards adding tenant admin to a group a mapping targets too.

Real PostgreSQL and Valkey on the incident world: every organisation is new (rule 5h).
"""

import uuid
from typing import Any

import pytest

from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_audit_api import by_action
from tests.db.test_incidents_api import Org, World, role

pytestmark = [pytest.mark.db, MODULE_LOOP]
__all__ = ["module_world", "shared_world"]  # the fixtures, re-used

BASE = "/identity/group-mappings"


async def _directory(world: World, org: Org) -> uuid.UUID:
    made = uuid.uuid4()
    await world.sql(
        "INSERT INTO directory_connectors (id, tenant_id, name, directory_tenant, client_id,"
        " credential_kind) VALUES ($1, $2, $3, 'contoso.example', 'app-1', 'secret')",
        made, org.tenant, f"Directory {made.hex[:6]}",
    )  # fmt: skip
    return made


async def _create(world: World, org: Org, **body: Any) -> Any:  # noqa: ANN401 - JSON and httpx
    return await world.call(
        "POST", BASE, org, org.admin, json=body, headers={"Idempotency-Key": str(uuid.uuid4())}
    )


async def _settings(world: World, org: Org, *, allowed: bool) -> None:
    saved = await world.call(
        "PUT", f"{BASE}/settings", org, org.admin, json={"privileged_allowed": allowed}
    )
    assert saved.status_code == 200, saved.text


async def test_a_directory_mapping_onto_a_role_is_made_listed_counted_and_removed(
    world: World,
) -> None:
    a = world.a
    source = await _directory(world, a)
    changer = await role(world, a, f"Change {uuid.uuid4().hex[:6]}", [("changes.view", "all")])
    made = await _create(
        world, a, source_kind="directory", source_id=str(source),
        external_group_id="7c1e0d2a-1111-4c1d-9d1e-5b2c3d4e5f60", role_id=str(changer),
    )  # fmt: skip
    assert made.status_code == 201, made.text
    mapping = made.json()["id"]
    listed = await world.call("GET", f"{BASE}?source_kind=directory&source_id={source}", a, a.admin)
    assert [m["id"] for m in listed.json()] == [mapping]
    counted = await world.call("GET", f"{BASE}/{mapping}/holders", a, a.admin)
    assert counted.json() == {"holders": 0}
    gone = await world.call("DELETE", f"{BASE}/{mapping}", a, a.admin)
    assert gone.status_code == 204, gone.text
    assert await by_action(world, a, "idp_group_mapping.created")
    assert await by_action(world, a, "idp_group_mapping.removed")
    # Not identity.manage: no mappings at all.
    assert (await world.call("GET", f"{BASE}/settings", a, a.tech_a)).status_code == 403


async def test_sso_sources_wait_for_s5c_1b_and_an_unknown_source_is_not_found(
    world: World,
) -> None:
    a = world.a
    changer = await role(world, a, f"Change {uuid.uuid4().hex[:6]}", [("changes.view", "all")])
    sso = await _create(
        world, a, source_kind="sso", source_id=str(uuid.uuid4()),
        external_group_id="g-1", role_id=str(changer),
    )  # fmt: skip
    assert sso.status_code == 422, sso.text
    assert sso.json()["errors"][0]["code"] == "idp_group_mappings_coming_soon"
    settings = await world.call("GET", f"{BASE}/settings", a, a.admin)
    assert settings.json()["sso_sources_ready"] is False
    unknown = await _create(
        world, a, source_kind="directory", source_id=str(uuid.uuid4()),
        external_group_id="g-1", role_id=str(changer),
    )  # fmt: skip
    assert (unknown.status_code, unknown.json()["code"]) == (404, "mapping_source_not_found")


async def test_privileged_access_needs_the_tenant_opt_in(world: World) -> None:
    a = world.a
    source = await _directory(world, a)
    roles = (await world.call("GET", "/roles", a, a.admin)).json()
    admin_role = next(r["id"] for r in roles if r["key"] == "tenant_admin")
    body: dict[str, Any] = {
        "source_kind": "directory", "source_id": str(source),
        "external_group_id": "sx-admins", "role_id": admin_role,
    }  # fmt: skip
    refused = await _create(world, a, **body)
    assert (refused.status_code, refused.json()["code"]) == (
        409,
        "mapping_grants_privileged_access",
    )
    await _settings(world, a, allowed=True)
    try:
        assert (await world.call("GET", f"{BASE}/settings", a, a.admin)).json()[
            "privileged_allowed"
        ] is True
        allowed = await _create(world, a, **body)
        assert allowed.status_code == 201, allowed.text
        assert await by_action(world, a, "idp_group_mapping.privileged_opt_in_changed")
    finally:
        await _settings(world, a, allowed=False)
    # Tenant admin onto a group a mapping targets: the same opt-in (the back door).
    group_mapping = await _create(
        world, a, source_kind="directory", source_id=str(source),
        external_group_id="sx-network", group_id=str(a.gb),
    )  # fmt: skip
    assert group_mapping.status_code == 201, group_mapping.text
    onto = await world.call("PUT", f"/roles/{admin_role}/groups/{a.gb}", a, a.admin)
    assert (onto.status_code, onto.json()["code"]) == (409, "mapping_grants_privileged_access")
