"""Sign-in settings and single sign-on over HTTP (WP-039 session 1; ADR-033; D-094).

Real PostgreSQL (throwaway database, RLS on); the session is faked by headers as in the other API
tests, Keycloak's admin API by `FakeAdmin` (the real one is proved in
tests/integration/test_keycloak_admin.py), and the provider's discovery document by a patched
fetch. Each test names the requirement or rule it proves.
"""

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import httpx
import pytest
import pytest_asyncio
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.tenancy import SESSION_RESOLVER_STATE, TenantContext
from app.main import create_app
from app.modules.identity_access.infra.fetch import FetchError
from app.modules.identity_access.infra.keycloak_admin import (
    IdentityAdminRefused,
    LoginEvent,
    Organization,
)
from app.modules.identity_access.service import sso as sso_service
from app.modules.identity_access.service.identity_settings import DEFAULTS
from app.modules.identity_access.service.users import provision_user
from conftest import make_settings
from tests.db.test_access_api import Org, fake_session, make_org
from tooling.db_testing import ThrowawayDatabase

pytestmark = pytest.mark.db

ISSUER = "https://login.example.test/acme/v2.0"


@dataclass
class FakeAdmin:
    """Keycloak's admin API in memory: organizations, providers, links, mappers, domains."""

    orgs: dict[str, Organization] = field(default_factory=dict)  # by tenant ID
    providers: dict[str, dict[str, Any]] = field(default_factory=dict)
    links: dict[str, set[str]] = field(default_factory=dict)
    mapper_sets: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    attributes: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    events: list[LoginEvent] = field(default_factory=list)
    logged_out: list[str] = field(default_factory=list)

    async def close(self) -> None:
        return None

    def add_org(self, tenant: uuid.UUID, slug: str, domains: tuple[str, ...] = ()) -> None:
        raw = {"id": f"org-{slug}", "alias": slug, "domains": [{"name": d} for d in domains]}
        self.orgs[str(tenant)] = Organization(f"org-{slug}", slug, slug, domains, raw)
        self.links[f"org-{slug}"] = set()

    async def organization(self, slug: str, tenant_id: str) -> Organization | None:
        found = self.orgs.get(tenant_id)
        return found if found is not None and found.alias == slug else None

    async def set_organization_domains(
        self, organization: Organization, domains: list[dict[str, Any]]
    ) -> None:
        names = [d["name"] for d in domains]
        for tenant, other in self.orgs.items():
            if other.id != organization.id and set(other.domains) & set(names):
                raise IdentityAdminRefused(409, "domain in use")
            if other.id == organization.id:
                raw = {**other.raw, "domains": domains}
                self.orgs[tenant] = replace(other, domains=tuple(names), raw=raw)

    async def provider(self, alias: str) -> dict[str, Any] | None:
        found = self.providers.get(alias)
        if found is None:
            return None
        masked = dict(found["config"])
        if "clientSecret" in masked:
            masked["clientSecret"] = "**********"
        return {**found, "config": masked}

    async def create_provider(self, representation: dict[str, Any]) -> None:
        if representation["alias"] in self.providers:
            raise IdentityAdminRefused(409, "exists")
        self.providers[representation["alias"]] = representation

    async def update_provider(self, alias: str, representation: dict[str, Any]) -> None:
        secret = self.providers[alias]["config"].get("clientSecret")
        config = dict(representation["config"])
        if config.get("clientSecret") in (None, "**********"):
            config["clientSecret"] = secret
        self.providers[alias] = {**representation, "config": config}

    async def delete_provider(self, alias: str) -> None:
        self.providers.pop(alias, None)
        for links in self.links.values():
            links.discard(alias)

    async def link_provider(self, organization_id: str, alias: str) -> None:
        self.links[organization_id].add(alias)

    async def linked_providers(self, organization_id: str) -> list[str]:
        return sorted(self.links[organization_id])

    async def replace_mappers(self, alias: str, mappers: list[dict[str, Any]]) -> None:
        self.mapper_sets[alias] = mappers

    async def parse_saml_metadata(self, metadata: str) -> dict[str, str]:
        if "<EntityDescriptor" not in metadata:
            raise IdentityAdminRefused(400, "unreadable")
        found: dict[str, str] = json.loads(metadata.split("<!--", 1)[1].split("-->", 1)[0])
        return found

    async def logout_user(self, user_id: str) -> None:
        self.logged_out.append(user_id)

    async def user_attributes(self, user_id: str) -> dict[str, list[str]]:
        return self.attributes.get(user_id, {})

    async def login_events(
        self, types: list[str], since_ms: int, user_id: str | None = None
    ) -> list[LoginEvent]:
        del user_id
        return [e for e in self.events if e.type in types and e.time_ms >= since_ms]


DISCOVERY = {
    "issuer": ISSUER,
    "authorization_endpoint": f"{ISSUER}/authorize",
    "token_endpoint": f"{ISSUER}/token",
    "jwks_uri": f"{ISSUER}/keys",
}


@dataclass
class World:
    client: AsyncClient
    db: ThrowawayDatabase
    a: Org
    b: Org
    app: FastAPI
    admin: FakeAdmin
    accepted_secrets: set[str]

    async def call(
        self,
        method: str,
        path: str,
        org: Org,
        user: uuid.UUID | None = None,
        **kw: Any,  # noqa: ANN401 - httpx request options
    ) -> httpx.Response:
        headers = {
            "X-Test-Tenant": str(org.tenant),
            "X-Test-User": str(user or org.admin),
            **kw.pop("headers", {}),
        }
        return await self.client.request(method, f"/api/v1{path}", headers=headers, **kw)

    async def add_oidc(self, org: Org, **body: Any) -> httpx.Response:  # noqa: ANN401
        values = {
            "preset": "entra",
            "display_name": "Acme Entra ID",
            "domains": ["acme.test"],
            "issuer": ISSUER,
            "client_id": "supportx",
            "client_secret": "right-secret",
            **body,
        }
        return await self.call(
            "POST",
            "/identity/sso",
            org,
            json=values,
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )


@pytest_asyncio.fixture
async def world(
    migrated_db: ThrowawayDatabase, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[World]:
    accepted = {"right-secret"}

    async def fetch(url: str, *, allow_loopback: bool = False) -> str:
        del allow_loopback
        if url == f"{ISSUER}/.well-known/openid-configuration":
            return json.dumps(DISCOVERY)
        missing = "unreachable"
        raise FetchError(missing)

    async def client_check(
        token_url: str, client_id: str, secret: str, *, allow_loopback: bool = False
    ) -> bool:
        del token_url, client_id, allow_loopback
        return secret in accepted

    monkeypatch.setattr(sso_service, "fetch_document", fetch)
    monkeypatch.setattr(sso_service, "client_accepted", client_check)
    app: FastAPI = create_app(make_settings(database_url=migrated_db.app_url))
    async with app.router.lifespan_context(app):
        setattr(app.state, SESSION_RESOLVER_STATE, fake_session)
        admin = FakeAdmin()
        app.state.identity_admin = admin
        a = await make_org(migrated_db, "Alpha")
        b = await make_org(migrated_db, "Beta")
        for org in (a, b):
            slug = await _slug(migrated_db, org.tenant)
            admin.add_org(org.tenant, slug, (f"{slug}.test",))
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield World(client, migrated_db, a, b, app, admin, accepted)


async def _slug(db: ThrowawayDatabase, tenant: uuid.UUID) -> str:
    conn = await asyncpg.connect(db.admin_url)
    try:
        return str(await conn.fetchval("SELECT slug FROM tenants WHERE id = $1", tenant))
    finally:
        await conn.close()


async def _admin_rows(db: ThrowawayDatabase, sql: str, *args: Any) -> list[asyncpg.Record]:  # noqa: ANN401
    conn = await asyncpg.connect(db.admin_url)
    try:
        return await conn.fetch(sql, *args)
    finally:
        await conn.close()


# --- tenant isolation (CLAUDE.md rule a) ------------------------------------------------------


async def test_new_tables_are_tenant_isolated(world: World) -> None:
    for org in (world.a, world.b):
        saved = await world.call(
            "PUT",
            "/identity/settings",
            org,
            json={**_settings_body(), "create_people_on_sign_in": False},
            headers={"If-Match": '"0"'},
        )
        assert saved.status_code == 200, saved.text
        slug = world.admin.orgs[str(org.tenant)].alias
        added = await world.add_oidc(org, domains=[f"sso.{slug}.test"])
        assert added.status_code == 201, added.text
    intruders = {
        "identity_settings": ("INSERT INTO identity_settings (tenant_id) VALUES ($1)", ()),
        "sso_providers": (
            (
                "INSERT INTO sso_providers (id, tenant_id, alias, protocol, preset, display_name)"
                " VALUES ($2, $1, 'sx-x', 'oidc', 'oidc', 'X')"
            ),
            (uuid.uuid4(),),
        ),
    }
    conn = await asyncpg.connect(world.db.app_direct_url)
    try:
        for table, (insert, extra) in intruders.items():
            async with conn.transaction():
                await conn.execute(f"SET LOCAL app.tenant_id = '{world.a.tenant}'")
                rows = await conn.fetch(f"SELECT tenant_id FROM {table}")  # noqa: S608 - fixed names
                assert {r["tenant_id"] for r in rows} == {world.a.tenant}, table
            # Tenant A cannot write a row for tenant B (the policy's WITH CHECK).
            async with conn.transaction():
                await conn.execute(f"SET LOCAL app.tenant_id = '{world.a.tenant}'")
                with pytest.raises(asyncpg.InsufficientPrivilegeError):
                    await conn.execute(insert, world.b.tenant, *extra)
    finally:
        await conn.close()


# --- settings (REQ-SEC-013, REQ-SEC-017, REQ-SEC-029) ---------------------------------------------


def _settings_body(**changes: Any) -> dict[str, Any]:  # noqa: ANN401
    body = {name: getattr(DEFAULTS, name) for name in DEFAULTS.__dataclass_fields__}
    body.pop("version")
    return body | changes


async def test_settings_start_at_the_appendix_a_defaults_and_save_with_if_match(
    world: World,
) -> None:
    found = await world.call("GET", "/identity/settings", world.a)
    assert found.status_code == 200
    assert found.json() == {**_settings_body(), "version": 0}
    assert found.json()["console_idle_seconds"] == 3600  # 60 minutes (Appendix A)
    saved = await world.call(
        "PUT",
        "/identity/settings",
        world.a,
        json=_settings_body(portal_idle_seconds=900),
        headers={"If-Match": '"0"'},
    )
    assert saved.status_code == 200, saved.text
    assert (saved.json()["portal_idle_seconds"], saved.json()["version"]) == (900, 1)
    assert saved.headers["ETag"] == '"1"'
    stale = await world.call(
        "PUT",
        "/identity/settings",
        world.a,
        json=_settings_body(portal_idle_seconds=600),
        headers={"If-Match": '"0"'},
    )
    assert stale.status_code == 409
    # Audited with before and after (D-089 D7), and an event through the outbox (rule b).
    entries = await _admin_rows(
        world.db,
        "SELECT details FROM audit_entries WHERE tenant_id = $1 AND action = $2",
        world.a.tenant,
        "identity.settings_changed",
    )
    details = json.loads(entries[0]["details"])
    assert details["changed_fields"] == ["portal_idle_seconds"]
    assert (details["portal_idle_seconds.before"], details["portal_idle_seconds.after"]) == (
        1800,
        900,
    )
    events = await _admin_rows(
        world.db,
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1 AND event_type = $2",
        world.a.tenant,
        "identity_access.identity_settings.changed",
    )
    assert len(events) == 1


async def test_out_of_range_timeouts_are_refused_at_the_field_with_the_limit(world: World) -> None:
    refused = await world.call(
        "PUT",
        "/identity/settings",
        world.a,
        json=_settings_body(console_idle_seconds=60, portal_absolute_seconds=40 * 86400),
        headers={"If-Match": '"0"'},
    )
    assert refused.status_code == 422
    errors = {e["field"]: e for e in refused.json()["errors"]}
    assert errors["console_idle_seconds"]["code"] == "session_idle_out_of_range"
    assert errors["console_idle_seconds"]["params"] == {"min": 5, "max": 1440}
    assert errors["portal_absolute_seconds"]["params"] == {"max": 720}  # 30 days, in hours


async def test_only_identity_managers_see_or_change_sign_in_settings(world: World) -> None:
    for method, path in (("GET", "/identity/settings"), ("GET", "/identity/sso")):
        assert (await world.call(method, path, world.a, world.a.tech)).status_code == 403
    put = await world.call(
        "PUT",
        "/identity/settings",
        world.a,
        world.a.tech,
        json=_settings_body(),
        headers={"If-Match": '"0"'},
    )
    assert put.status_code == 403


async def test_people_creation_off_refuses_unknown_people_but_lets_known_ones_in(
    world: World,
) -> None:
    """REQ-SEC-013 AC3: with automatic creation off, only people the tenant knows sign in."""
    saved = await world.call(
        "PUT",
        "/identity/settings",
        world.a,
        json=_settings_body(create_people_on_sign_in=False),
        headers={"If-Match": '"0"'},
    )
    assert saved.status_code == 200
    from app.core.database import Database, create_engine  # noqa: PLC0415 - this test only
    from app.core.errors import PermissionDenied  # noqa: PLC0415
    from app.modules.identity_access.domain.identity import Identity  # noqa: PLC0415

    database = Database(create_engine(world.db.app_url, application_name="test"))
    stranger = Identity(
        subject="sub-stranger",
        email="stranger@acme.test",
        display_name="Stranger",
        locale="en",
        roles=(),
        memberships=(),
        keycloak_session_id=None,
    )
    with pytest.raises(PermissionDenied) as refused:
        await provision_user(
            database, world.a.tenant, stranger, datetime.now(UTC), client="console", reason="login"
        )
    assert refused.value.instance_code == "sign_in_unknown_person"
    # Beta still creates people (its own setting), with Beta's portal limits.
    created = await provision_user(
        database, world.b.tenant, stranger, datetime.now(UTC), client="portal", reason="login"
    )
    assert (created.session_idle_seconds, created.session_absolute_seconds) == (1800, 43200)


async def test_department_and_site_from_sso_are_applied_on_first_sign_in(world: World) -> None:
    """REQ-SEC-007 AC3 (D-089 D6): matched by name or code, never created."""
    department = await world.call(
        "POST", "/organization/departments", world.a, json={"name": "Finance", "code": "fin"}
    )
    assert department.status_code == 201, department.text
    site = await world.call("POST", "/organization/sites", world.a, json={"name": "Karachi"})
    assert site.status_code == 201, site.text
    from app.core.database import Database, create_engine  # noqa: PLC0415 - this test only
    from app.modules.identity_access.domain.identity import Identity  # noqa: PLC0415

    async def directory(subject: str) -> dict[str, str | None]:
        return {"department": "FIN", "site": "karachi"} if subject == "sub-new" else {}

    database = Database(create_engine(world.db.app_url, application_name="test"))
    person = Identity("sub-new", "new@acme.test", "New Person", "en", (), (), None)
    created = await provision_user(
        database,
        world.a.tenant,
        person,
        datetime.now(UTC),
        client="console",
        reason="login",
        directory=directory,
    )
    rows = await _admin_rows(
        world.db, "SELECT department_id, site_id FROM users WHERE id = $1", created.user_id
    )
    assert str(rows[0]["department_id"]) == department.json()["id"]
    assert str(rows[0]["site_id"]) == site.json()["id"]


# --- single sign-on (REQ-SEC-007, REQ-SEC-008) ------------------------------------------------


async def test_an_oidc_set_up_is_saved_hidden_linked_and_without_its_secret(world: World) -> None:
    added = await world.add_oidc(world.a, mapping=None)
    assert added.status_code == 201, added.text
    body = added.json()
    assert (body["state"], body["protocol"], body["domains"]) == ("draft", "oidc", ["acme.test"])
    assert "right-secret" not in added.text
    alias = next(iter(world.admin.providers))
    provider = world.admin.providers[alias]
    slug = world.admin.orgs[str(world.a.tenant)].alias
    assert alias.startswith(f"sx-{slug}-")
    assert (provider["enabled"], provider["hideOnLogin"]) == (True, True)  # only the test uses it
    assert provider["config"]["clientSecret"] == "right-secret"  # Keycloak keeps it
    assert provider["config"]["authorizationUrl"] == DISCOVERY["authorization_endpoint"]
    org = world.admin.orgs[str(world.a.tenant)]
    routed = {d["name"]: d for d in org.raw["domains"]}["acme.test"]
    # Routed to the set-up, nobody sent there yet (draft).
    assert (routed["identityProviderAlias"], routed["autoRedirect"]) == (alias, False)
    assert alias in world.admin.links[org.id]
    assert set(org.domains) == {f"{slug}.test", "acme.test"}
    rows = await _admin_rows(world.db, "SELECT settings::text AS s FROM sso_providers")
    assert "right-secret" not in rows[0]["s"]
    assert body["redirect_uri"].endswith(f"/broker/{alias}/endpoint")


async def test_a_wrong_secret_or_issuer_is_refused_with_a_plain_reason(world: World) -> None:
    """REQ-SEC-007 AC1 / 008: the reason at the field; nothing left behind in Keycloak."""
    wrong = await world.add_oidc(world.a, client_secret="wrong-secret")
    assert wrong.status_code == 422
    assert wrong.json()["errors"][0] == {
        "field": "client_secret",
        "code": "sso_client_rejected",
        "message_key": "errors.field.sso_client_rejected",
        "params": {},
    }
    unknown = await world.add_oidc(world.a, issuer="https://nowhere.example.test")
    assert unknown.json()["errors"][0]["code"] == "sso_discovery_unreachable"
    assert world.admin.providers == {}


async def test_public_and_other_tenants_domains_cannot_be_claimed(world: World) -> None:
    public = await world.add_oidc(world.a, domains=["gmail.com"])
    assert public.json()["errors"][0]["code"] == "sso_domain_public"
    beta = world.admin.orgs[str(world.b.tenant)].alias
    taken = await world.add_oidc(world.a, domains=[f"{beta}.test"])  # Beta's own domain
    assert taken.status_code == 422
    assert taken.json()["errors"][0]["code"] == "sso_domain_taken"
    assert world.admin.providers == {}  # undone


async def test_switch_on_needs_a_passed_test_and_a_connection_change_needs_a_new_one(
    world: World,
) -> None:
    added = (await world.add_oidc(world.a)).json()
    path = f"/identity/sso/{added['id']}"
    refused = await world.call(
        "POST", f"{path}/switch-on", world.a, headers={"If-Match": f'"{added["version"]}"'}
    )
    assert (refused.status_code, refused.json()["code"]) == (409, "sso_not_tested")
    await _mark_tested(world, world.a, uuid.UUID(added["id"]))
    current = (await world.call("GET", path, world.a)).json()
    assert current["state"] == "tested"
    on = await world.call(
        "POST", f"{path}/switch-on", world.a, headers={"If-Match": f'"{current["version"]}"'}
    )
    assert on.status_code == 200, on.text
    alias = next(iter(world.admin.providers))
    assert world.admin.providers[alias]["hideOnLogin"] is False
    # An "on" set-up is switched off before its connection changes (no locked-out tenant).
    body = {
        "preset": "entra",
        "display_name": "Acme Entra ID",
        "domains": ["acme.test"],
        "issuer": ISSUER,
        "client_id": "another-client",
    }
    busy = await world.call(
        "PUT", path, world.a, json=body, headers={"If-Match": f'"{on.json()["version"]}"'}
    )
    assert (busy.status_code, busy.json()["code"]) == (409, "sso_switch_off_first")
    off = await world.call(
        "POST", f"{path}/switch-off", world.a, headers={"If-Match": f'"{on.json()["version"]}"'}
    )
    assert world.admin.providers[alias]["enabled"] is False
    changed = await world.call(
        "PUT", path, world.a, json=body, headers={"If-Match": f'"{off.json()["version"]}"'}
    )
    assert changed.status_code == 200, changed.text
    assert (changed.json()["state"], changed.json()["tested_at"]) == ("draft", None)
    assert world.admin.providers[alias]["config"]["clientSecret"] == "right-secret"  # kept


async def _mark_tested(world: World, org: Org, provider: uuid.UUID) -> None:
    from app.core.database import Database, create_engine  # noqa: PLC0415 - helper

    database = Database(create_engine(world.db.app_url, application_name="test"))
    async with database.tenant_session(TenantContext(org.tenant, org.admin)) as session:
        await sso_service.mark_tested(session, provider, org.admin)


async def test_removing_gives_back_only_the_domains_it_claimed(world: World) -> None:
    own = f"{world.admin.orgs[str(world.a.tenant)].alias}.test"
    added = (await world.add_oidc(world.a, domains=["acme.test", own])).json()
    removed = await world.call(
        "DELETE",
        f"/identity/sso/{added['id']}",
        world.a,
        headers={"If-Match": f'"{added["version"]}"'},
    )
    assert removed.status_code == 204
    assert world.admin.providers == {}
    # The tenant's own domain was the organization's before; acme.test only the set-up's.
    assert world.admin.orgs[str(world.a.tenant)].domains == (own,)
    assert (await world.call("GET", "/identity/sso", world.a)).json()["items"] == []
    audit = await _admin_rows(
        world.db,
        "SELECT action FROM audit_entries WHERE tenant_id = $1 AND action LIKE 'sso.%'"
        " ORDER BY occurred_at",
        world.a.tenant,
    )
    assert [r["action"] for r in audit] == ["sso.added", "sso.removed"]


async def test_saml_metadata_is_read_by_keycloak_and_its_certificate_checked(world: World) -> None:
    expired = _certificate(days=-1)
    valid = _certificate(days=365)
    for certificate, expected in ((expired, 422), (valid, 201)):
        metadata = (
            "<EntityDescriptor><!--"
            + json.dumps(
                {
                    "singleSignOnServiceUrl": "https://idp.acme.test/saml",
                    "signingCertificate": certificate,
                    "idpEntityId": "https://idp.acme.test",
                }
            )
            + "--></EntityDescriptor>"
        )
        added = await world.call(
            "POST",
            "/identity/sso",
            world.a,
            json={
                "preset": "saml",
                "display_name": "Acme SAML",
                "domains": ["acme.test"],
                "metadata": metadata,
            },
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        assert added.status_code == expected, added.text
    assert added.json()["last_check"]["certificate_not_after"] is not None
    assert added.json()["service_provider_metadata_url"].endswith("/endpoint/descriptor")
    provider = next(iter(world.admin.providers.values()))
    assert provider["config"]["validateSignature"] == "true"


def _certificate(*, days: int) -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "idp.acme.test")])
    now = datetime.now(UTC)
    start = now - timedelta(days=400) if days < 0 else now - timedelta(days=1)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(start)
        .not_valid_after(now + timedelta(days=days))
        .sign(key, hashes.SHA256())
    )
    pem = certificate.public_bytes(serialization.Encoding.PEM).decode()
    return "".join(pem.splitlines()[1:-1])


async def test_another_tenant_never_sees_or_changes_a_set_up(world: World) -> None:
    added = (await world.add_oidc(world.a)).json()
    path = f"/identity/sso/{added['id']}"
    assert (await world.call("GET", path, world.b)).status_code == 404
    assert (await world.call("GET", "/identity/sso", world.b)).json()["items"] == []
    gone = await world.call("DELETE", path, world.b, headers={"If-Match": '"1"'})
    assert gone.status_code == 404
    assert len(world.admin.providers) == 1


async def test_two_set_ups_never_share_a_domain(world: World) -> None:
    assert (await world.add_oidc(world.a)).status_code == 201
    again = await world.add_oidc(world.a, display_name="Second")
    assert again.status_code == 422
    assert again.json()["errors"][0]["code"] == "sso_domain_in_use"
    assert again.json()["errors"][0]["params"] == {"domain": "acme.test"}


async def test_people_are_sent_to_the_provider_only_while_it_is_on_and_when_chosen(
    world: World,
) -> None:
    added = (await world.add_oidc(world.a, email_redirect=True)).json()

    def routed() -> dict[str, Any]:
        org = world.admin.orgs[str(world.a.tenant)]
        found: dict[str, Any] = {d["name"]: d for d in org.raw["domains"]}["acme.test"]
        return found

    assert routed()["autoRedirect"] is False  # draft: nobody sent there yet
    await _mark_tested(world, world.a, uuid.UUID(added["id"]))
    current = (await world.call("GET", f"/identity/sso/{added['id']}", world.a)).json()
    on = await world.call(
        "POST",
        f"/identity/sso/{added['id']}/switch-on",
        world.a,
        headers={"If-Match": f'"{current["version"]}"'},
    )
    assert on.status_code == 200
    assert routed()["autoRedirect"] is True
    off = await world.call(
        "POST",
        f"/identity/sso/{added['id']}/switch-off",
        world.a,
        headers={"If-Match": f'"{on.json()["version"]}"'},
    )
    assert off.status_code == 200
    assert routed()["autoRedirect"] is False


async def test_multi_tenant_installations_route_only_proved_domains(world: World) -> None:
    """D-098: in a realm tenants share, an unproved domain is never routed (refused, clearly)."""
    world.app.state.settings = world.app.state.settings.model_copy(update={"multi_tenant": True})
    refused = await world.add_oidc(world.a)
    assert refused.status_code == 422
    assert refused.json()["errors"][0] == {
        "field": "domains",
        "code": "sso_domain_unverified",
        "message_key": "errors.field.sso_domain_unverified",
        "params": {"domain": "acme.test"},
    }
    assert world.admin.providers == {}
    # Once the organization's domain is proved (WP-014d marks it verified), it can be routed.
    org = world.admin.orgs[str(world.a.tenant)]
    proved = [*org.raw["domains"], {"name": "acme.test", "verified": True}]
    world.admin.orgs[str(world.a.tenant)] = replace(
        org, domains=(*org.domains, "acme.test"), raw={**org.raw, "domains": proved}
    )
    assert (await world.add_oidc(world.a)).status_code == 201
