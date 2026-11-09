"""Migration 0121: group-scoped service desk managers become team leads (D-152, D-153).

Two tenants, run per tenant under RLS FORCE. In the first, technicians see their groups (the
unanswered default), so every holder moves. In the second, technicians see everything, so only
the holder who leads a group moves. The downgrade moves them back, and refuses while anyone
holds another new role.
"""

import asyncio
import uuid
from collections.abc import Iterator

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0108"


@pytest.fixture
def before(db_config: db_testing.DbTestConfig) -> Iterator[db_testing.ThrowawayDatabase]:
    """A throwaway database migrated to just before 0121."""
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        yield database
    finally:
        db_testing.destroy(db_config, database)


async def _tenant(conn: asyncpg.Connection, name: str, scope: str | None) -> uuid.UUID:
    tenant = uuid.uuid4()
    await conn.execute(
        "INSERT INTO tenants (id, name, slug) VALUES ($1, $2, $3)",
        tenant,
        name,
        f"t-{tenant.hex[:12]}",
    )
    if scope is not None:
        await conn.execute(
            "INSERT INTO access_settings (tenant_id, technician_scope) VALUES ($1, $2)",
            tenant,
            scope,
        )
    return tenant


async def _user(conn: asyncpg.Connection, tenant: uuid.UUID, name: str) -> uuid.UUID:
    user = uuid.uuid4()
    await conn.execute(
        "INSERT INTO users (id, tenant_id, display_name, first_name, user_type)"
        " VALUES ($1, $2, $3, $3, 'technician')",
        user,
        tenant,
        name,
    )
    return user


async def _role(conn: asyncpg.Connection, tenant: uuid.UUID, key: str) -> uuid.UUID:
    role = uuid.uuid4()
    await conn.execute(
        "INSERT INTO roles (id, tenant_id, key, name, is_system, version)"
        " VALUES ($1, $2, $3, $3, true, 1)",
        role,
        tenant,
        key,
    )
    return role


async def _hold(
    conn: asyncpg.Connection, tenant: uuid.UUID, user: uuid.UUID, role: uuid.UUID
) -> None:
    await conn.execute(
        "INSERT INTO user_roles (tenant_id, user_id, role_id) VALUES ($1, $2, $3)",
        tenant,
        user,
        role,
    )


async def _seed(url: str) -> dict[str, uuid.UUID]:
    conn = await asyncpg.connect(url)
    try:
        grouped = await _tenant(conn, "Grouped", None)  # unanswered: technicians see groups
        wide = await _tenant(conn, "Wide", "all")
        seen: dict[str, uuid.UUID] = {"grouped": grouped, "wide": wide}
        for tenant, prefix in ((grouped, "g"), (wide, "w")):
            manager = await _role(conn, tenant, "service_desk_manager")
            for who in ("lead", "plain"):
                user = await _user(conn, tenant, f"{prefix}-{who}")
                await _hold(conn, tenant, user, manager)
                seen[f"{prefix}-{who}"] = user
            desk = await conn.fetchval(
                "INSERT INTO desks (id, tenant_id, code, labels) VALUES"
                " (gen_random_uuid(), $1, 'it', '{}'::jsonb) RETURNING id",
                tenant,
            )
            await conn.execute(
                "INSERT INTO support_groups (id, tenant_id, name, desk_id, lead_id)"
                " VALUES (gen_random_uuid(), $1, 'Desk', $2, $3)",
                tenant,
                desk,
                seen[f"{prefix}-lead"],
            )
    finally:
        await conn.close()
    return seen


async def _keys(url: str, user: uuid.UUID) -> set[str]:
    conn = await asyncpg.connect(url)  # the superuser: sees every tenant's rows (seeding only)
    try:
        rows = await conn.fetch(
            "SELECT r.key FROM user_roles ur JOIN roles r ON r.id = ur.role_id"
            " WHERE ur.user_id = $1",
            user,
        )
    finally:
        await conn.close()
    return {r["key"] for r in rows}


def test_holders_move_by_their_tenants_scope_and_back(
    before: db_testing.ThrowawayDatabase,
) -> None:
    seen = asyncio.run(_seed(before.admin_url))
    db_testing.migrate(before.migrator_url, "0121")
    url = before.admin_url
    # Technicians see their groups: both holders are team leads now.
    assert asyncio.run(_keys(url, seen["g-lead"])) == {"team_lead"}
    assert asyncio.run(_keys(url, seen["g-plain"])) == {"team_lead"}
    # Technicians see everything: only the group's lead moves.
    assert asyncio.run(_keys(url, seen["w-lead"])) == {"team_lead"}
    assert asyncio.run(_keys(url, seen["w-plain"])) == {"service_desk_manager"}
    db_testing.downgrade(before.migrator_url, BEFORE)
    for who in ("g-lead", "g-plain", "w-lead", "w-plain"):
        assert asyncio.run(_keys(url, seen[who])) == {"service_desk_manager"}, who


def test_the_downgrade_refuses_while_another_new_role_is_held(
    before: db_testing.ThrowawayDatabase,
) -> None:
    seen = asyncio.run(_seed(before.admin_url))
    db_testing.migrate(before.migrator_url, "0121")

    async def give_asset_manager() -> None:
        conn = await asyncpg.connect(before.admin_url)
        try:
            role = await _role(conn, seen["wide"], "asset_manager")
            await _hold(conn, seen["wide"], seen["w-plain"], role)
        finally:
            await conn.close()

    asyncio.run(give_asset_manager())
    with pytest.raises(Exception, match="downgrade refused"):
        db_testing.downgrade(before.migrator_url, BEFORE)
    assert asyncio.run(_keys(before.admin_url, seen["g-lead"])) == {"team_lead"}  # untouched
