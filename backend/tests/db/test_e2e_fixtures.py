"""tooling.e2e_fixtures creates and deletes only its own rows."""

import asyncio

import asyncpg
import pytest

from tooling import db_testing, e2e_fixtures, seed_dev

pytestmark = pytest.mark.db


async def _users(url: str) -> list[str]:
    conn = await asyncpg.connect(url)
    try:
        rows = await conn.fetch("SELECT email FROM users ORDER BY email")
    finally:
        await conn.close()
    return [r["email"] for r in rows]


def test_create_is_idempotent_and_delete_removes_only_fixtures(
    db_config: db_testing.DbTestConfig,
) -> None:
    # Own database: the fixtures go into the fixed Demo tenant, which other tests share.
    database = db_testing.create(db_config)
    try:
        asyncio.run(_scenario(database))
    finally:
        db_testing.destroy(db_config, database)


async def _scenario(database: db_testing.ThrowawayDatabase) -> None:
    await seed_dev.seed(database.migrator_url)
    conn = await asyncpg.connect(database.admin_url)
    await conn.execute(
        "INSERT INTO users (id, tenant_id, external_subject, email, display_name, user_type)"
        " VALUES (gen_random_uuid(), $1, 'keep', 'keep@demo.test', 'Keep', 'technician')",
        seed_dev.DEMO_TENANT_ID,
    )
    await conn.close()
    assert await e2e_fixtures.create(database.migrator_url) == e2e_fixtures.COUNT
    assert await e2e_fixtures.create(database.migrator_url) == 0
    assert len(await _users(database.admin_url)) == e2e_fixtures.COUNT + 1
    assert await e2e_fixtures.delete(database.migrator_url) == e2e_fixtures.COUNT
    assert await _users(database.admin_url) == ["keep@demo.test"]
