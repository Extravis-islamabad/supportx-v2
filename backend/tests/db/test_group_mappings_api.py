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
from tests.db.test_incidents_api import Org, World, make_org, role

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
    current = (await world.call("GET", f"{BASE}/settings", org, org.admin)).json()
    saved = await world.call(
        "PUT", f"{BASE}/settings", org, org.admin, json={"privileged_allowed": allowed},
        headers={"If-Match": f'"{current["version"]}"'},
    )  # fmt: skip
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
    stale = await world.call(
        "DELETE", f"{BASE}/{mapping}", a, a.admin, headers={"If-Match": '"99"'}
    )
    assert stale.status_code == 409, stale.text  # If-Match (rule 5g)
    gone = await world.call("DELETE", f"{BASE}/{mapping}", a, a.admin, headers={"If-Match": '"1"'})
    assert gone.status_code == 204, gone.text
    after = await world.call("GET", f"{BASE}/{mapping}/holders", a, a.admin)
    assert after.status_code == 404  # a removed mapping has no holders to count
    assert await by_action(world, a, "idp_group_mapping.created")
    assert await by_action(world, a, "idp_group_mapping.removed")
    # Not identity.manage: no mappings at all.
    assert (await world.call("GET", f"{BASE}/settings", a, a.tech_a)).status_code == 403


async def test_an_sso_source_is_mapped_and_an_unknown_source_is_not_found(
    world: World,
) -> None:
    """S5c-1b: the release switch is gone; an SSO set-up of this tenant is a mapping's source."""
    a = world.a
    changer = await role(world, a, f"Change {uuid.uuid4().hex[:6]}", [("changes.view", "all")])
    provider = uuid.uuid4()
    await world.sql(
        "INSERT INTO sso_providers (id, tenant_id, alias, protocol, preset, display_name)"
        " VALUES ($1, $2, $3, 'oidc', 'entra', 'Acme')",
        provider, a.tenant, f"sx-m-{provider.hex[:6]}",
    )  # fmt: skip
    sso = await _create(
        world, a, source_kind="sso", source_id=str(provider),
        external_group_id="g-1", role_id=str(changer),
    )  # fmt: skip
    assert sso.status_code == 201, sso.text
    settings = await world.call("GET", f"{BASE}/settings", a, a.admin)
    assert settings.json()["sso_sources_ready"] is True
    elsewhere = await _create(
        world, a, source_kind="sso", source_id=str(uuid.uuid4()),
        external_group_id="g-1", role_id=str(changer),
    )  # fmt: skip
    assert (elsewhere.status_code, elsewhere.json()["code"]) == (404, "mapping_source_not_found")
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


async def test_a_stale_or_switched_off_directory_with_managed_access_is_flagged(
    world: World,
) -> None:
    """The coordinator's condition: visible on the security overview, never failing closed."""
    from datetime import UTC, datetime, timedelta  # noqa: PLC0415 - this test only

    from app.core.tenancy import TenantContext  # noqa: PLC0415 - this test only
    from app.modules.identity_access.domain.group_mappings import SourceKind  # noqa: PLC0415
    from app.modules.identity_access.service import group_mappings  # noqa: PLC0415

    org = await make_org(world, f"Stale {uuid.uuid4().hex[:6]}")
    source = await _directory(world, org)
    group = (await world.sql(
        "SELECT id FROM support_groups WHERE tenant_id = $1 LIMIT 1", org.tenant
    ))[0]["id"]  # fmt: skip
    made = await _create(
        world, org, source_kind="directory", source_id=str(source),
        external_group_id="sx-desk", group_id=str(group),
    )  # fmt: skip
    assert made.status_code == 201, made.text
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        await group_mappings.follow(
            session, source_kind=SourceKind.DIRECTORY, source_id=source,
            user_id=org.requester, group_ids=frozenset({"sx-desk"}),
        )  # fmt: skip

    async def flagged() -> int:
        async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
            return await group_mappings.stale_sources(session, datetime.now(UTC))

    long_ago = datetime.now(UTC) - timedelta(hours=30)
    await world.sql(
        "UPDATE directory_connectors SET last_synced_at = $2 WHERE id = $1", source, long_ago
    )
    assert await flagged() == 1  # over a day without a successful sync
    await world.sql("UPDATE directory_connectors SET last_synced_at = now() WHERE id = $1", source)
    assert await flagged() == 0  # fresh
    await world.sql("UPDATE directory_connectors SET enabled = false WHERE id = $1", source)
    assert await flagged() == 1  # switched off: no run will ever say so, the flag does
    overview = await world.call("GET", "/identity/security-overview", org, org.admin)
    assert overview.status_code == 200, overview.text
    assert "directory_access_stale" in overview.text


async def test_removing_the_mapping_that_holds_the_last_admin_is_refused_unless_kept(
    world: World,
) -> None:
    """Lane B's #620 review: "remove" never strands the only admin; "keep" still works."""
    from sqlalchemy import select  # noqa: PLC0415 - this test only

    from app.core.tenancy import TenantContext  # noqa: PLC0415 - this test only
    from app.modules.identity_access.domain.group_mappings import SourceKind  # noqa: PLC0415
    from app.modules.identity_access.infra.models import Role  # noqa: PLC0415
    from app.modules.identity_access.service import group_mappings  # noqa: PLC0415

    org = await make_org(world, f"Only admin {uuid.uuid4().hex[:6]}")
    source = await _directory(world, org)
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        admin_role = await session.scalar(select(Role.id).where(Role.key == "tenant_admin"))
    await _settings(world, org, allowed=True)
    made = await _create(
        world, org, source_kind="directory", source_id=str(source),
        external_group_id="sx-admins", role_id=str(admin_role),
    )  # fmt: skip
    assert made.status_code == 201, made.text
    mapping = made.json()["id"]
    # The only admin holds tenant admin through this mapping alone.
    for user in (org.lead, org.tech_a, org.tech_b, org.tech_c):
        await world.sql(
            "DELETE FROM user_roles WHERE tenant_id = $1 AND user_id = $2 AND role_id = $3",
            org.tenant, user, admin_role,
        )  # fmt: skip
    await world.sql(
        "UPDATE user_roles SET managed = true WHERE tenant_id = $1 AND user_id = $2",
        org.tenant, org.admin,
    )  # fmt: skip
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        await group_mappings.follow(
            session, source_kind=SourceKind.DIRECTORY, source_id=source,
            user_id=org.admin, group_ids=frozenset({"sx-admins"}),
        )  # fmt: skip

    match = {"If-Match": '"1"'}
    refused = await world.call(
        "DELETE", f"{BASE}/{mapping}?on_held=remove", org, org.admin, headers=match
    )
    assert (refused.status_code, refused.json()["code"]) == (409, "mapping_holds_last_admin")
    listed = await world.call(
        "GET", f"{BASE}?source_kind=directory&source_id={source}", org, org.admin
    )
    assert [m["id"] for m in listed.json()] == [mapping]  # nothing changed
    kept = await world.call(
        "DELETE", f"{BASE}/{mapping}?on_held=keep", org, org.admin, headers=match
    )
    assert kept.status_code == 204, kept.text
    still = await world.sql(
        "SELECT managed FROM user_roles WHERE tenant_id = $1 AND user_id = $2 AND role_id = $3",
        org.tenant, org.admin, admin_role,
    )  # fmt: skip
    assert [r["managed"] for r in still] == [False]  # the admin keeps it, now hand-made
