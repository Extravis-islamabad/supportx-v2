"""Migration 0072: stored layouts go back to "not chosen" once, in every tenant (D-136).

The product owner approved the one-time reset for the pre-pilot dev, QA and demo data. The
digits preference is added (D-135). The downgrade drops it and leaves the reset (NULL is valid).
"""

import asyncio
import uuid

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db


async def _users_in_two_tenants(url: str) -> list[uuid.UUID]:
    conn = await asyncpg.connect(url)
    try:
        users: list[uuid.UUID] = []
        for layout, density in (("top", "compact"), ("side_compact", None)):
            tenant = uuid.uuid4()
            await conn.execute(
                "INSERT INTO tenants (id, name, slug) VALUES ($1, 'Reset', $2)",
                tenant,
                f"t-{tenant.hex[:12]}",
            )
            user = uuid.uuid4()
            await conn.execute(
                "INSERT INTO users (id, tenant_id, email, display_name, first_name, user_type,"
                " nav_layout, form_density) VALUES ($1, $2, $3, 'Reset user', 'Reset',"
                " 'technician', $4, $5)",
                user,
                tenant,
                f"{user.hex[:10]}@reset.test",
                layout,
                density,
            )
            users.append(user)
        return users
    finally:
        await conn.close()


async def _rows(url: str, users: list[uuid.UUID]) -> list[tuple[object, ...]]:
    conn = await asyncpg.connect(url)
    try:
        rows = await conn.fetch(
            "SELECT nav_layout, form_density FROM users WHERE id = ANY($1::uuid[]) ORDER BY id",
            users,
        )
        has_digits = await conn.fetchval(
            "SELECT count(*) FROM information_schema.columns"
            " WHERE table_name = 'users' AND column_name = 'digits'"
        )
    finally:
        await conn.close()
    return [*(tuple(r) for r in rows), ("digits", has_digits)]


def test_0072_resets_stored_layouts_in_every_tenant_and_adds_digits(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to="0071")
    try:
        users = asyncio.run(_users_in_two_tenants(database.admin_url))
        before = asyncio.run(_rows(database.admin_url, users))
        assert before[-1] == ("digits", 0)
        assert sorted(before[:-1], key=str) == sorted(
            [("top", "compact"), ("side_compact", None)], key=str
        )
        db_testing.migrate(database.migrator_url, "0072")
        after = asyncio.run(_rows(database.admin_url, users))
        assert after == [(None, None), (None, None), ("digits", 1)]
        db_testing.downgrade(database.migrator_url, "0071")
        assert asyncio.run(_rows(database.admin_url, users)) == [
            (None, None),
            (None, None),
            ("digits", 0),
        ]
    finally:
        db_testing.destroy(db_config, database)
