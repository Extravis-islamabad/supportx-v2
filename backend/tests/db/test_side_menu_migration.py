"""Migration 0051: every tenant's users on the top bar move to the side bar once, and back.

The product owner approved the one-time move for the pre-pilot dev, QA and demo data (D-124).
A user on the compact side bar keeps it; the downgrade returns the moved users to the top bar.
"""

import asyncio
import uuid

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db


async def _tenant_with_users(url: str) -> tuple[uuid.UUID, uuid.UUID]:
    """A tenant with one user on the top bar and one on the compact side bar."""
    conn = await asyncpg.connect(url)
    try:
        tenant = uuid.uuid4()
        await conn.execute(
            "INSERT INTO tenants (id, name, slug) VALUES ($1, 'Menu', $2)",
            tenant,
            f"t-{tenant.hex[:12]}",
        )
        top, compact = uuid.uuid4(), uuid.uuid4()
        for user, layout in ((top, "top"), (compact, "side_compact")):
            await conn.execute(
                "INSERT INTO users (id, tenant_id, email, display_name, first_name, user_type,"
                " nav_layout) VALUES ($1, $2, $3, 'Menu user', 'Menu', 'technician', $4)",
                user,
                tenant,
                f"{user.hex[:10]}@menu.test",
                layout,
            )
        return top, compact
    finally:
        await conn.close()


async def _layouts(url: str, users: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    conn = await asyncpg.connect(url)
    try:
        rows = await conn.fetch(
            "SELECT id, nav_layout FROM users WHERE id = ANY($1::uuid[])", users
        )
    finally:
        await conn.close()
    return {r["id"]: r["nav_layout"] for r in rows}


async def _default(url: str) -> str:
    conn = await asyncpg.connect(url)
    try:
        found: str = await conn.fetchval(
            "SELECT column_default FROM information_schema.columns"
            " WHERE table_name = 'users' AND column_name = 'nav_layout'"
        )
    finally:
        await conn.close()
    return found


def test_0051_moves_top_to_side_in_every_tenant_and_reverses(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to="0038")
    try:
        first = asyncio.run(_tenant_with_users(database.admin_url))
        second = asyncio.run(_tenant_with_users(database.admin_url))
        users = [*first, *second]

        db_testing.migrate(database.migrator_url, "0051")
        after = asyncio.run(_layouts(database.admin_url, users))
        assert [after[first[0]], after[second[0]]] == ["side", "side"]
        assert [after[first[1]], after[second[1]]] == ["side_compact", "side_compact"]
        assert "side" in asyncio.run(_default(database.admin_url))

        db_testing.downgrade(database.migrator_url, "0038")
        back = asyncio.run(_layouts(database.admin_url, users))
        assert [back[first[0]], back[second[0]]] == ["top", "top"]
        assert [back[first[1]], back[second[1]]] == ["side_compact", "side_compact"]
        assert "top" in asyncio.run(_default(database.admin_url))
    finally:
        db_testing.destroy(db_config, database)
