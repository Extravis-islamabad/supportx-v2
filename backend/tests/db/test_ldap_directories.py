"""AD/LDAP directories: the guards, the stored settings and the Keycloak step (WP-040, D-118).

Real Postgres; Keycloak's side is a recording fake behind identity_access's public interface.
"""

import secrets as stdlib_secrets
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from pydantic import SecretStr

from app.core.errors import AppError, Conflict, ValidationFailed
from app.core.tenancy import TenantContext
from app.modules.identity_access import FederationFailed
from app.modules.integrations.service import directories, ldap_directories
from app.shared.files.keyring import KeyRing
from tests.app_state import set_state
from tests.db.test_files_api import audit_actions
from tests.db.test_incidents_api import World, world

__all__ = ["world"]  # fixture, re-used

pytestmark = [pytest.mark.db]

BIND_PASSWORD = stdlib_secrets.token_urlsafe(18)  # made at run time: never a literal secret
BODY: dict[str, Any] = {
    "name": "Corp AD",
    "host": "dc1.corp.example",
    "bind_dn": "CN=svc-supportx,OU=Service,DC=corp,DC=example",
    "users_dn": "OU=People,DC=corp,DC=example",
}


class FakeKeycloak:
    """What the worker asked Keycloak to do, and how Keycloak answers."""

    def __init__(self) -> None:
        self.components: dict[str, dict[str, Any]] = {}  # Any: Keycloak's JSON
        self.mappers: dict[str, list[dict[str, Any]]] = {}
        self.removed: list[str] = []
        self.fail: str | None = None

    async def put(
        self,
        settings: object,
        *,
        component: Callable[[str], dict[str, Any]],
        mappers: Callable[[str], list[dict[str, Any]]],
    ) -> str:
        del settings
        if self.fail:
            raise FederationFailed(self.fail)
        body = component("realm-1")
        found = next((k for k, v in self.components.items() if v["name"] == body["name"]), None)
        component_id = found or f"cmp-{len(self.components) + 1}"
        self.components[component_id] = body
        self.mappers[component_id] = mappers(component_id)
        return component_id

    async def remove(self, settings: object, component_id: str) -> None:
        del settings
        if self.fail:
            raise FederationFailed(self.fail)
        self.components.pop(component_id, None)
        self.removed.append(component_id)


@pytest.fixture
def keycloak(world: World, monkeypatch: pytest.MonkeyPatch) -> FakeKeycloak:
    fake = FakeKeycloak()
    settings = world.app.state.settings.model_copy(
        update={
            "files_keys": SecretStr(KeyRing.generate()),
            "keycloak_federation_client_secret": SecretStr(stdlib_secrets.token_urlsafe(24)),
        }
    )
    set_state(monkeypatch, world.app.state, "settings", settings)
    monkeypatch.setattr(ldap_directories, "put_ldap_federation", fake.put)
    monkeypatch.setattr(ldap_directories, "remove_ldap_federation", fake.remove)
    monkeypatch.setattr(ldap_directories, "get_settings", lambda: settings)
    return fake


@pytest.fixture
def licensed(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The add-on is on the tenant's licence (the refusal is tested with the real gate)."""
    asked: list[str] = []

    async def require(tenant_id: uuid.UUID, feature: object) -> None:
        del tenant_id
        asked.append(str(feature))

    monkeypatch.setattr(ldap_directories, "require_feature", require)
    return asked


def _context(world: World) -> TenantContext:
    return TenantContext(world.a.tenant, world.a.admin)


async def _create(world: World, *, multi_tenant: bool = False, **body: Any) -> Any:  # noqa: ANN401
    async with world.app.state.db.tenant_session(_context(world)) as session:
        return await ldap_directories.create_ldap_directory(
            session,
            world.app.state.settings,
            world.a.tenant,
            BODY | body,
            bind_password=BIND_PASSWORD,
            multi_tenant=multi_tenant,
        )


async def _apply(world: World, directory_id: uuid.UUID) -> str:
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        return await ldap_directories.apply_federation(
            session, world.app.state.settings, directory_id
        )


async def test_without_the_add_on_nothing_is_stored(world: World, keycloak: FakeKeycloak) -> None:
    del keycloak
    with pytest.raises(AppError) as refused:
        await _create(world)
    assert refused.value.instance_code == "entitlement_required"
    rows = await world.sql("SELECT count(*) AS n FROM directory_connectors WHERE source = 'ldap'")
    assert rows[0]["n"] == 0


@pytest.mark.usefixtures("licensed")
async def test_a_shared_realm_or_a_missing_federation_account_refuses_it(
    world: World, keycloak: FakeKeycloak, monkeypatch: pytest.MonkeyPatch
) -> None:
    del keycloak
    with pytest.raises(Conflict) as shared:
        await _create(world, multi_tenant=True)
    assert shared.value.instance_code == "ldap_single_tenant_only"
    no_account = world.app.state.settings.model_copy(
        update={"keycloak_federation_client_secret": None}
    )
    set_state(monkeypatch, world.app.state, "settings", no_account)
    with pytest.raises(AppError) as missing:
        await _create(world)
    assert missing.value.instance_code == "ldap_federation_not_installed"


@pytest.mark.usefixtures("licensed")
async def test_plain_ldap_needs_the_explicit_choice(world: World, keycloak: FakeKeycloak) -> None:
    del keycloak
    with pytest.raises(ValidationFailed) as refused:
        await _create(world, security="plain", port=389)
    assert [e.code for e in refused.value.errors] == ["plain_connection_refused"]
    view = await _create(world, name="Lab LDAP", security="plain", port=389, allow_plain=True)
    assert view.row.ldap["allow_plain"] is True


async def test_saved_pending_then_applied_in_keycloak_and_audited(
    world: World, keycloak: FakeKeycloak, licensed: list[str]
) -> None:
    view = await _create(world, groups_dn="OU=Groups,DC=corp,DC=example")
    assert licensed == ["directory_federation"]
    row = view.row
    assert (row.source, row.federation_state, row.ldap["security"]) == ("ldap", "pending", "ldaps")
    secret = await world.sql(
        "SELECT secret_type, sealed FROM connector_secrets WHERE id = $1", row.secret_ref
    )
    assert secret[0]["secret_type"] == "password"
    assert BIND_PASSWORD.encode() not in bytes(secret[0]["sealed"])  # sealed, never plain

    assert await _apply(world, row.id) == "applied"
    ((component_id, sent),) = keycloak.components.items()
    assert sent["name"] == f"supportx-{row.id}"  # a rename changes nothing in the realm
    assert sent["config"]["connectionUrl"] == ["ldaps://dc1.corp.example:636"]
    assert sent["config"]["editMode"] == ["READ_ONLY"]
    assert {m["name"] for m in keycloak.mappers[component_id]} >= {"email", "groups"}
    stored = await world.sql(
        "SELECT federation_state, keycloak_component_id FROM directory_connectors WHERE id = $1",
        row.id,
    )
    assert dict(stored[0]) == {"federation_state": "applied", "keycloak_component_id": component_id}
    assert await _apply(world, row.id) == "skipped"  # a repeated event changes nothing
    assert "directory.federation_applied" in await audit_actions(world, world.a)


@pytest.mark.usefixtures("licensed")
async def test_a_refusal_is_recorded_for_the_screen(world: World, keycloak: FakeKeycloak) -> None:
    view = await _create(world)
    keycloak.fail = "ldap_federation_refused"
    assert await _apply(world, view.row.id) == "failed"
    stored = await world.sql(
        "SELECT federation_state, federation_error FROM directory_connectors WHERE id = $1",
        view.row.id,
    )
    assert dict(stored[0]) == {
        "federation_state": "failed",
        "federation_error": "ldap_federation_refused",
    }
    assert "directory.federation_failed" in await audit_actions(world, world.a)


@pytest.mark.usefixtures("licensed")
async def test_removing_it_removes_the_component_and_entra_screens_never_list_it(
    world: World, keycloak: FakeKeycloak
) -> None:
    view = await _create(world)
    await _apply(world, view.row.id)
    async with world.app.state.db.tenant_session(_context(world)) as session:
        assert [v.row.id for v in await ldap_directories.list_ldap_directories(session)] == [
            view.row.id
        ]
        assert await directories.list_directories(session) == []  # the Entra list
        await ldap_directories.remove_ldap_directory(
            session, view.row.id, expected_version=view.row.version
        )
    assert await _apply(world, view.row.id) == "removed"
    assert keycloak.removed
    assert not keycloak.components
    assert "directory.federation_removed" in await audit_actions(world, world.a)


@pytest.mark.usefixtures("licensed")
async def test_another_tenant_never_sees_it(world: World, keycloak: FakeKeycloak) -> None:
    del keycloak
    view = await _create(world)
    async with world.app.state.db.tenant_session(TenantContext(world.b.tenant)) as session:
        assert await ldap_directories.list_ldap_directories(session) == []
        with pytest.raises(AppError) as hidden:
            await ldap_directories.get_ldap_directory(session, view.row.id)
    assert hidden.value.instance_code == "directory_not_found"
