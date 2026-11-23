"""Tenant addresses as the sign-in clients' callbacks (ADR-031, plan A part 1), on real Postgres.

The Keycloak side is a fake `ClientAddressAdmin`: the real adapter (its own service account,
allowed only these two clients) waits on the product owner's OK for fine-grained admin
permissions v2. Each delivery goes as the consumer worker makes it: a tenant transaction with the
consumer's idempotency claim.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from app.core.config import Settings
from app.core.database import Database, create_engine
from app.core.tenancy import TenantContext
from app.modules.identity_access.domain.client_addresses import (
    CALLBACK_PATH,
    Addresses,
    ClientBase,
)
from app.modules.identity_access.service import client_addresses
from app.shared.events import Actor, EventEnvelope, claim
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import Org, World

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the fixtures, used by name

BASE = "support.example.test"


class FakeAdmin:
    """The two clients' redirect URIs and web origins, in memory, with every change counted."""

    def __init__(self) -> None:
        self.held: dict[str, Addresses] = {}
        self.calls: list[tuple[str, str, Addresses]] = []

    async def current(self, client_id: str) -> Addresses:
        return self.held.get(client_id, Addresses())

    async def add(self, client_id: str, addresses: Addresses) -> None:
        self.calls.append(("add", client_id, addresses))
        now = self.held.get(client_id, Addresses())
        self.held[client_id] = Addresses(
            now.redirect_uris | addresses.redirect_uris, now.web_origins | addresses.web_origins
        )

    async def remove(self, client_id: str, addresses: Addresses) -> None:
        self.calls.append(("remove", client_id, addresses))
        now = self.held.get(client_id, Addresses())
        self.held[client_id] = Addresses(
            now.redirect_uris - addresses.redirect_uris, now.web_origins - addresses.web_origins
        )

    def uris(self, client_id: str) -> frozenset[str]:
        return self.held.get(client_id, Addresses()).redirect_uris


def _settings(world: World, *, base: str | None = BASE) -> Settings:
    settings: Settings = world.app.state.settings
    return settings.model_copy(
        update={"tenant_base_domain": base, "console_url": "https://support.example.test"}
    )


def _console(settings: Settings) -> ClientBase:
    return client_addresses.clients(settings)[0]


@pytest.fixture
def fake(world: World, monkeypatch: pytest.MonkeyPatch) -> FakeAdmin:
    admin = FakeAdmin()
    settings = _settings(world)
    monkeypatch.setattr(client_addresses, "admin_factory", lambda _s: admin)
    monkeypatch.setattr(client_addresses, "get_settings", lambda: settings)
    return admin


async def _domain(
    world: World, org: Org, host: str, status: str = "verified", *, removed: bool = False
) -> uuid.UUID:
    domain_id = uuid.uuid4()
    await world.sql(
        "INSERT INTO tenant_domains (id, tenant_id, host, status, verify_token, deleted_at)"
        " VALUES ($1, $2, $3, $4, 't', CASE WHEN $5 THEN now() END)",
        domain_id,
        org.tenant,
        host,
        status,
        removed,
    )
    return domain_id


def _event(org: Org, domain_id: uuid.UUID, change: str) -> EventEnvelope:
    return EventEnvelope(
        event_id=uuid.uuid4(),
        event_type="organization.domain.changed",
        schema_version=1,
        tenant_id=org.tenant,
        actor=Actor.system("tests"),
        occurred_at=datetime.now(UTC),
        aggregate_type="tenant_domain",
        aggregate_id=str(domain_id),
        payload={"domain_id": str(domain_id), "change": change},
    )


async def _deliver(world: World, envelope: EventEnvelope) -> bool:
    """One delivery as the consumer worker makes it (False: already processed)."""
    database = Database(
        create_engine(world.db.app_url, application_name="tests", use_null_pool=True)
    )
    try:
        async with database.tenant_session(TenantContext(envelope.tenant_id)) as session:
            if not await claim(session, client_addresses.CLIENT_ADDRESSES.name, envelope):
                return False
            await client_addresses.on_address_event(envelope, session)
        return True
    finally:
        await database.dispose()


async def _slug(world: World, org: Org) -> str:
    rows = await world.sql("SELECT slug FROM tenants WHERE id = $1", org.tenant)
    return str(rows[0]["slug"])


def _host() -> str:
    return f"help-{uuid.uuid4().hex[:8]}.example.test"


async def _audits(world: World, org: Org) -> list[dict[str, Any]]:
    rows = await world.sql(
        "SELECT details FROM audit_entries WHERE tenant_id = $1 AND action = $2",
        org.tenant,
        client_addresses.ACTION,
    )
    return [dict(r) for r in rows]


async def test_a_verified_domain_and_the_subdomain_are_added_and_audited(
    world: World, fake: FakeAdmin
) -> None:
    a = world.a
    host = _host()
    domain_id = await _domain(world, a, host)
    before = len(await _audits(world, a))
    assert await _deliver(world, _event(a, domain_id, "verified"))
    console = _console(_settings(world))
    assert console.callback(host) in fake.uris(console.client_id)
    assert console.callback(f"{await _slug(world, a)}.{BASE}") in fake.uris(console.client_id)
    assert f"https://{host}" in fake.held[console.client_id].web_origins
    assert len(await _audits(world, a)) == before + 1


async def test_an_unverified_domain_is_never_added(world: World, fake: FakeAdmin) -> None:
    a = world.a
    host = _host()
    domain_id = await _domain(world, a, host, status="pending")
    await _deliver(world, _event(a, domain_id, "verified"))  # even when an event says so
    console = _console(_settings(world))
    assert console.callback(host) not in fake.uris(console.client_id)


async def test_a_replayed_event_changes_nothing_the_second_time(
    world: World, fake: FakeAdmin
) -> None:
    a = world.a
    domain_id = await _domain(world, a, _host())
    event = _event(a, domain_id, "verified")
    assert await _deliver(world, event)
    calls = len(fake.calls)
    assert not await _deliver(world, event)  # the claim: already processed
    assert len(fake.calls) == calls


async def test_a_removed_or_failed_domain_is_taken_off(world: World, fake: FakeAdmin) -> None:
    a = world.a
    console = _console(_settings(world))
    for change in ("removed", "failed"):
        host = _host()
        domain_id = await _domain(world, a, host)
        await _deliver(world, _event(a, domain_id, "verified"))
        assert console.callback(host) in fake.uris(console.client_id)
        if change == "removed":
            await world.sql("UPDATE tenant_domains SET deleted_at = now() WHERE id = $1", domain_id)
        else:
            await world.sql("UPDATE tenant_domains SET status = 'failed' WHERE id = $1", domain_id)
        await _deliver(world, _event(a, domain_id, change))
        assert console.callback(host) not in fake.uris(console.client_id), change


async def test_one_tenants_event_never_takes_another_tenants_address(
    world: World, fake: FakeAdmin
) -> None:
    """Tenant B removes a host tenant A still verifies: A keeps its callback.

    The negative control (the same removal when no tenant holds the host) takes it off, so the
    check is what keeps it.
    """
    a, b = world.a, world.b
    console = _console(_settings(world))
    shared = _host()
    mine = await _domain(world, a, shared)
    await _deliver(world, _event(a, mine, "verified"))
    # B once added the same host (a host is unique among live rows, so B's is already removed).
    theirs = await _domain(world, b, shared, status="pending", removed=True)
    await _deliver(world, _event(b, theirs, "removed"))
    assert console.callback(shared) in fake.uris(console.client_id)
    # Control: once A no longer holds it, the same kind of removal takes it off.
    await world.sql("UPDATE tenant_domains SET deleted_at = now() WHERE id = $1", mine)
    await _deliver(world, _event(a, mine, "removed"))
    assert console.callback(shared) not in fake.uris(console.client_id)


async def test_the_reconcile_removes_a_managed_stray_and_keeps_an_operators_entry(
    world: World, fake: FakeAdmin
) -> None:
    a = world.a
    settings = _settings(world)
    console = _console(settings)
    kept_host = _host()
    await _domain(world, a, kept_host)
    stray = console.callback("gone.example.test")
    operators = {"https://support.example.test/*", "https://ops.example.test/hand-made"}
    fake.held[console.client_id] = Addresses(
        redirect_uris=frozenset({stray, *operators}), web_origins=frozenset()
    )
    await client_addresses.reconcile(world.app.state.db, settings, fake)
    held = fake.uris(console.client_id)
    assert stray not in held
    assert operators <= held
    assert console.callback(kept_host) in held


async def test_the_reconcile_removes_nothing_when_a_tenant_cant_be_read(
    world: World, fake: FakeAdmin, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed read must never empty the clients (negative control: a full read removes)."""
    settings = _settings(world)
    console = _console(settings)
    stray = console.callback("gone-again.example.test")
    real = client_addresses.tenant_addresses  # type: ignore[attr-defined]  # patched where it's used
    calls = 0

    async def flaky(session: Any) -> Any:  # noqa: ANN401 - the real function's types
        nonlocal calls
        calls += 1
        if calls == 1:
            msg = "unreadable"
            raise RuntimeError(msg)
        return await real(session)

    fake.held[console.client_id] = Addresses(redirect_uris=frozenset({stray}))
    monkeypatch.setattr(client_addresses, "tenant_addresses", flaky)
    await client_addresses.reconcile(world.app.state.db, settings, fake)
    assert stray in fake.uris(console.client_id)
    monkeypatch.setattr(client_addresses, "tenant_addresses", real)
    await client_addresses.reconcile(world.app.state.db, settings, fake)
    assert stray not in fake.uris(console.client_id)


async def test_with_no_admin_configured_nothing_happens(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = world.a
    monkeypatch.setattr(client_addresses, "admin_factory", lambda _s: None)
    domain_id = await _domain(world, a, _host())
    before = len(await _audits(world, a))
    assert await _deliver(world, _event(a, domain_id, "verified"))
    assert len(await _audits(world, a)) == before
    await client_addresses.reconcile_schedule(world.app.state.db, _settings(world))


async def test_the_callback_path_matches_the_sign_in() -> None:
    from app.modules.identity_access.service.auth import (  # noqa: PLC0415 - the one constant
        CALLBACK_PATH as SIGN_IN_CALLBACK,
    )

    assert CALLBACK_PATH == SIGN_IN_CALLBACK
