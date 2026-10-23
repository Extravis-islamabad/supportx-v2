"""Entitlements against real PostgreSQL (WP-009): subscriptions, gating, the API, technician seats.

- tenant_subscriptions: tenant isolation and no write access for the application role;
- the subscription provider gates a sample module exactly like the test and licence-file
  providers do (tests/test_entitlement_enforcement.py);
- GET /api/v1/entitlements: shape, usage, no secrets;
- read-only mode on a real endpoint (PATCH /api/v1/users/{id});
- technician seats at JIT provisioning: a 20-way race never exceeds the limit, requesters are
  unlimited, existing technicians are never locked out.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
import pytest_asyncio
from fastapi import APIRouter, FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.database import Database
from app.core.errors import LimitReached
from app.core.modules import ModuleRegistry, ModuleSpec, discover_modules
from app.core.tenancy import SESSION_RESOLVER_STATE, TenantContext
from app.main import create_app
from app.modules.identity_access.domain.identity import Identity
from app.modules.identity_access.service.users import count_technicians, provision_user
from app.modules.licensing import EntitlementService, LimitKey
from app.modules.licensing.infra.providers import SubscriptionProvider
from app.modules.licensing.service.entitlements import install, installed, uninstall
from conftest import assign_system_role, create_tenant, make_settings
from tests.db.test_users_api import seed_users
from tooling.db_testing import ThrowawayDatabase

pytestmark = pytest.mark.db

NOW = datetime.now(UTC)

# --- tenant_subscriptions isolation (CLAUDE.md rule a) --------------------------------------------


async def test_app_role_reads_only_its_own_subscription(
    app_db: Database, tenant_pair: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, b = tenant_pair
    async with app_db.tenant_session(TenantContext(a)) as session:
        rows = (await session.execute(text("SELECT tenant_id FROM tenant_subscriptions"))).all()
        # Even naming B explicitly finds nothing.
        named_b = await session.scalar(
            text("SELECT count(*) FROM tenant_subscriptions WHERE tenant_id = :b"), {"b": b}
        )
    assert [r.tenant_id for r in rows] == [a]
    assert named_b == 0


async def test_without_tenant_context_no_subscription_is_visible(
    migrated_db: ThrowawayDatabase, tenant_pair: tuple[uuid.UUID, uuid.UUID]
) -> None:
    del tenant_pair
    conn = await asyncpg.connect(migrated_db.app_url)
    try:
        assert await conn.fetchval("SELECT count(*) FROM tenant_subscriptions") == 0
    finally:
        await conn.close()


@pytest.mark.parametrize(
    "statement",
    [
        (
            "INSERT INTO tenant_subscriptions (tenant_id, edition, starts_at)"
            " VALUES (:own, 'enterprise', now())"
        ),
        "UPDATE tenant_subscriptions SET edition = 'enterprise'",
        "UPDATE tenant_subscriptions SET limits = '{\"technicians\": 9999}'",
        "DELETE FROM tenant_subscriptions",
    ],
)
async def test_app_role_can_never_change_a_plan(
    migrated_db: ThrowawayDatabase, statement: str
) -> None:
    """Not even its own tenant's: entitlements are not something a request can grant itself."""
    tenant = await create_tenant(migrated_db.migrator_url, "Greedy", edition="essentials")
    conn = await asyncpg.connect(migrated_db.app_url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await conn.execute(statement.replace(":own", f"'{tenant}'"))
    finally:
        await conn.close()


# --- HTTP: the subscription provider gating a sample module ---------------------------------------

sample = APIRouter(prefix="/esm-sample")


@sample.get("/items")
async def _read() -> dict[str, str]:
    return {"ok": "read"}


@sample.post("/items")
async def _create() -> dict[str, str]:
    return {"ok": "write"}


SAMPLE = ModuleSpec(name="esm_sample", routers=[sample], feature="esm")


async def fake_session(request: Request) -> TenantContext | None:
    tenant = request.headers.get("x-test-tenant")
    if tenant is None:
        return None
    user = request.headers.get("x-test-user")
    roles = frozenset(filter(None, request.headers.get("x-test-roles", "").split(",")))
    return TenantContext(uuid.UUID(tenant), uuid.UUID(user) if user else None, roles=roles)


@pytest_asyncio.fixture
async def client(migrated_db: ThrowawayDatabase) -> AsyncIterator[AsyncClient]:
    registry = ModuleRegistry.from_specs([*discover_modules(), SAMPLE])
    app: FastAPI = create_app(make_settings(database_url=migrated_db.app_url), registry)
    async with app.router.lifespan_context(app):
        setattr(app.state, SESSION_RESOLVER_STATE, fake_session)
        assert isinstance(app.state.entitlements.provider, SubscriptionProvider)
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


def as_user(tenant: uuid.UUID, user: uuid.UUID | None = None, roles: str = "") -> dict[str, str]:
    headers = {"X-Test-Tenant": str(tenant), "X-Test-Roles": roles}
    if user is not None:
        headers["X-Test-User"] = str(user)
    return headers


async def test_subscription_provider_gates_the_module_by_edition(
    client: AsyncClient, migrated_db: ThrowawayDatabase
) -> None:
    enterprise = await create_tenant(migrated_db.migrator_url, "Ent", edition="enterprise")
    professional = await create_tenant(migrated_db.migrator_url, "Pro", edition="professional")
    none = await create_tenant(migrated_db.migrator_url, "None", edition=None)
    assert (await client.get("/api/v1/esm-sample/items", headers=as_user(enterprise))).json() == {
        "ok": "read"
    }
    for tenant in (professional, none):
        response = await client.post("/api/v1/esm-sample/items", headers=as_user(tenant))
        assert (response.status_code, response.json()["code"]) == (403, "entitlement_required")
        assert response.json()["params"] == {"feature": "esm"}


async def test_entitlements_endpoint(client: AsyncClient, migrated_db: ThrowawayDatabase) -> None:
    tenant = await create_tenant(
        migrated_db.migrator_url, "Shape", edition="professional", limits={"technicians": 3}
    )
    tech, requester, _second_tech = await seed_users(
        migrated_db,
        tenant,
        [
            {"user_type": "technician"},
            {"user_type": "requester"},
            {"user_type": "technician"},
        ],
    )
    staff = await client.get("/api/v1/entitlements", headers=as_user(tenant, tech, "technician"))
    assert staff.status_code == 200, staff.text
    body = staff.json()
    assert (body["edition"], body["state"], body["writable"]) == ("professional", "active", True)
    assert "change" in body["features"]
    assert "esm" not in body["features"]
    limits = {item["key"]: item for item in body["limits"]}
    assert limits["technicians"] == {"key": "technicians", "limit": 3, "used": 2, "remaining": 1}
    assert limits["assets"]["used"] is None  # no module counts assets yet
    assert body["admin_warning"] is False
    assert body["term"]["grace_days"] == 14
    secrets = {"signature", "customer", "licence_id", "installation_id", "fingerprint"}
    assert not secrets & (set(body) | set(body["term"]))

    # Requesters see the plan (to hide menus) but not seat usage.
    portal = await client.get("/api/v1/entitlements", headers=as_user(tenant, requester))
    assert {item["used"] for item in portal.json()["limits"]} == {None}


async def test_entitlements_endpoint_flags_problems_for_admins(
    client: AsyncClient, migrated_db: ThrowawayDatabase
) -> None:
    tenant = await create_tenant(migrated_db.migrator_url, "Grace", edition="enterprise")
    admin_id, tech_id = await seed_users(  # noqa: RUF059 - tech_id: the non-admin below
        migrated_db, tenant, [{"user_type": "technician"}, {"user_type": "technician"}]
    )
    await assign_system_role(migrated_db.admin_url, tenant, admin_id, "tenant_admin")
    await set_term(migrated_db, tenant, expires_at=NOW - timedelta(days=2), grace_days=14)
    admin = await client.get("/api/v1/entitlements", headers=as_user(tenant, admin_id))
    body = admin.json()
    assert (body["state"], body["state_reason"], body["writable"]) == ("grace", "expired", True)
    assert body["admin_warning"] is True
    assert body["days_left"] == 12
    technician = await client.get(
        "/api/v1/entitlements", headers=as_user(tenant, roles="technician")
    )
    assert technician.json()["admin_warning"] is False


async def test_read_only_tenant_keeps_reading_but_cannot_change_users(
    client: AsyncClient, migrated_db: ThrowawayDatabase
) -> None:
    tenant = await create_tenant(migrated_db.migrator_url, "Lapsed", edition="enterprise")
    (tech,) = await seed_users(migrated_db, tenant, [{"user_type": "technician"}])
    await set_term(migrated_db, tenant, expires_at=NOW - timedelta(days=60), grace_days=14)
    headers = as_user(tenant, tech, "technician")
    read = await client.get(f"/api/v1/users/{tech}", headers=headers)
    assert read.status_code == 200
    change = await client.patch(
        f"/api/v1/users/{tech}",
        json={"signature": "new"},
        headers={**headers, "If-Match": read.headers["ETag"]},
    )
    assert (change.status_code, change.json()["code"]) == (403, "read_only_mode")
    assert (await client.get("/api/v1/entitlements", headers=headers)).json()["writable"] is False


async def set_term(
    db: ThrowawayDatabase, tenant: uuid.UUID, *, expires_at: datetime, grace_days: int
) -> None:
    conn = await asyncpg.connect(db.migrator_url)
    try:
        await conn.execute(
            "UPDATE tenant_subscriptions SET starts_at = $2, expires_at = $3, grace_days = $4"
            " WHERE tenant_id = $1",
            tenant,
            expires_at - timedelta(days=365),
            expires_at,
            grace_days,
        )
    finally:
        await conn.close()


# --- technician seats at provisioning (§13.5, §13.6) ----------------------------------------------


@pytest_asyncio.fixture
async def seats(app_db: Database) -> AsyncIterator[EntitlementService]:
    """The real service on the subscription provider, installed for provision_user."""
    previous = installed()
    service = EntitlementService(
        SubscriptionProvider(app_db), counters={LimitKey.TECHNICIANS: count_technicians}
    )
    install(service)
    yield service
    uninstall(service)
    if previous is not None:
        install(previous)


def identity(email: str, roles: tuple[str, ...] = ("technician",)) -> Identity:
    return Identity(
        subject=f"sub-{email}",
        email=email,
        display_name=email.split("@", maxsplit=1)[0],
        locale="en",
        roles=roles,
        memberships=(),
        keycloak_session_id=None,
    )


async def login(db: Database, tenant: uuid.UUID, who: Identity) -> str:
    """Provision like a real login; 'ok' or the refusal code."""
    try:
        await provision_user(db, tenant, who, datetime.now(UTC), client="console", reason="login")
    except LimitReached as exc:
        return exc.instance_code
    return "ok"


async def technicians(db: Database, tenant: uuid.UUID) -> int:
    async with db.tenant_session(TenantContext(tenant)) as session:
        return await count_technicians(session)


async def set_seats(db: ThrowawayDatabase, tenant: uuid.UUID, seats: int) -> None:
    conn = await asyncpg.connect(db.migrator_url)
    try:
        await conn.execute(
            "UPDATE tenant_subscriptions SET limits = jsonb_build_object('technicians', $2::int)"
            " WHERE tenant_id = $1",
            tenant,
            seats,
        )
    finally:
        await conn.close()


async def test_twenty_simultaneous_first_logins_never_exceed_the_limit(
    seats: EntitlementService, app_db: Database, migrated_db: ThrowawayDatabase
) -> None:
    """app_db has no connection pool: each login runs in its own connection and transaction."""
    del seats
    tenant = await create_tenant(migrated_db.migrator_url, "Race", limits={"technicians": 5})
    results = await asyncio.gather(
        *(login(app_db, tenant, identity(f"tech{i}@race.test")) for i in range(20))
    )
    assert results.count("ok") == 5
    assert results.count("technician_limit_reached") == 15
    assert await technicians(app_db, tenant) == 5


async def test_same_new_user_logging_in_ten_times_at_once_takes_one_seat(
    seats: EntitlementService, app_db: Database, migrated_db: ThrowawayDatabase
) -> None:
    del seats
    tenant = await create_tenant(migrated_db.migrator_url, "Twice", limits={"technicians": 1})
    results = await asyncio.gather(
        *(login(app_db, tenant, identity("same@twice.test")) for _ in range(10))
    )
    assert results == ["ok"] * 10
    assert await technicians(app_db, tenant) == 1


async def test_requesters_are_unlimited(
    seats: EntitlementService, app_db: Database, migrated_db: ThrowawayDatabase
) -> None:
    del seats
    tenant = await create_tenant(migrated_db.migrator_url, "Portal", limits={"technicians": 0})
    for i in range(10):
        assert await login(app_db, tenant, identity(f"r{i}@p.test", ("requester",))) == "ok"
    assert await login(app_db, tenant, identity("t@p.test")) == "technician_limit_reached"


async def test_existing_technicians_are_never_locked_out(
    seats: EntitlementService, app_db: Database, migrated_db: ThrowawayDatabase
) -> None:
    del seats
    tenant = await create_tenant(migrated_db.migrator_url, "Shrink", limits={"technicians": 2})
    alice, bob, carol = (identity(f"{n}@shrink.test") for n in ("alice", "bob", "carol"))
    assert [await login(app_db, tenant, who) for who in (alice, bob)] == ["ok", "ok"]
    await set_seats(migrated_db, tenant, 1)  # plan downgraded below current use
    assert [await login(app_db, tenant, who) for who in (alice, bob)] == ["ok", "ok"]
    assert await login(app_db, tenant, carol) == "technician_limit_reached"


async def test_requester_promoted_to_technician_needs_a_seat(
    seats: EntitlementService, app_db: Database, migrated_db: ThrowawayDatabase
) -> None:
    del seats
    tenant = await create_tenant(migrated_db.migrator_url, "Promote", limits={"technicians": 1})
    assert await login(app_db, tenant, identity("t@promote.test")) == "ok"
    assert await login(app_db, tenant, identity("r@promote.test", ("requester",))) == "ok"
    promoted = identity("r@promote.test")  # same subject, Keycloak role changed
    assert await login(app_db, tenant, promoted) == "technician_limit_reached"
    await set_seats(migrated_db, tenant, 2)
    assert await login(app_db, tenant, promoted) == "ok"
    assert await technicians(app_db, tenant) == 2


async def test_check_limit_and_remaining(
    seats: EntitlementService, app_db: Database, migrated_db: ThrowawayDatabase
) -> None:
    tenant = await create_tenant(migrated_db.migrator_url, "Count", limits={"technicians": 4})
    await login(app_db, tenant, identity("one@count.test"))
    async with app_db.tenant_session(TenantContext(tenant)) as session:
        check = await seats.check_limit(session, LimitKey.TECHNICIANS, adding=3)
        remaining = await seats.remaining(session, LimitKey.TECHNICIANS)
        with pytest.raises(LookupError):
            await seats.check_limit(session, LimitKey.ASSETS)
    assert (check.used, check.limit, check.allowed, remaining) == (1, 4, True, 3)
