import asyncio
import uuid

import asyncpg
import pytest
from sqlalchemy import text

from app.core.database import Database, create_engine, pgbouncer_safe_connect_args
from app.core.tenancy import TenantContext
from tooling import seed_dev
from tooling.db_testing import ThrowawayDatabase

pytestmark = pytest.mark.db


async def demo_tenant(url: str) -> asyncpg.Record | None:
    conn = await asyncpg.connect(url)
    try:
        return await conn.fetchrow("SELECT id, name, slug FROM tenants WHERE slug = 'demo'")
    finally:
        await conn.close()


async def test_seed_creates_the_demo_tenant_once_and_never_overwrites(
    migrated_db: ThrowawayDatabase,
) -> None:
    first = await seed_dev.seed(migrated_db.migrator_url)
    conn = await asyncpg.connect(migrated_db.migrator_url)
    try:
        await conn.execute("UPDATE tenants SET name = 'Renamed by user' WHERE slug = 'demo'")
    finally:
        await conn.close()
    second = await seed_dev.seed(migrated_db.migrator_url)
    row = await demo_tenant(migrated_db.migrator_url)
    assert (first, second) == (True, False)
    assert row is not None
    assert row["id"] == seed_dev.DEMO_TENANT_ID
    assert row["name"] == "Renamed by user"  # the seed left the user's change alone


async def test_many_concurrent_transactions_through_pgbouncer(
    migrated_db: ThrowawayDatabase, tenant_pair: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """Transaction pooling + asyncpg: no 'prepared statement does not exist/already exists',
    and every transaction sees exactly its own tenant even when server connections are reused."""
    a, b = tenant_pair
    database = Database(
        create_engine(migrated_db.app_url, application_name="tests", pool_size=5, max_overflow=0)
    )
    try:

        async def work(i: int) -> uuid.UUID:
            tenant = a if i % 2 else b
            async with database.tenant_session(TenantContext(tenant)) as session:
                seen = await session.scalar(text("SELECT id FROM tenants"))
                await session.scalar(
                    text("SELECT count(*) FROM display_id_sequences WHERE prefix = :p"),
                    {"p": "INC"},
                )
                assert seen == tenant
                return tenant

        results = await asyncio.gather(*(work(i) for i in range(200)))
    finally:
        await database.dispose()
    assert results.count(a) == 100
    assert results.count(b) == 100


def test_engine_is_configured_for_transaction_pooling() -> None:
    args = pgbouncer_safe_connect_args("supportx-api")
    assert args["statement_cache_size"] == 0
    assert args["prepared_statement_cache_size"] == 0
    first, second = args["prepared_statement_name_func"](), args["prepared_statement_name_func"]()
    assert first != second
    assert first.startswith("__supportx_")
