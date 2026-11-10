"""Migration 0107 (workflow jobs, WP-048b S3) goes down and up, and refuses to drop jobs.

Seeded with SQL as the superuser (no lifecycle audit entries); it only goes down to 0106.
"""

import asyncio
import uuid
from collections.abc import Iterator

import asyncpg
import pytest

from conftest import create_tenant
from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0106"  # 0107's down revision


@pytest.fixture
def head(db_config: db_testing.DbTestConfig) -> Iterator[db_testing.ThrowawayDatabase]:
    database = db_testing.create(db_config, migrate_to="0107")
    try:
        yield database
    finally:
        db_testing.destroy(db_config, database)


async def _a_job(database: db_testing.ThrowawayDatabase) -> uuid.UUID:
    tenant = await create_tenant(database.migrator_url, "With a job")
    flow, job = uuid.uuid4(), uuid.uuid4()
    conn = await asyncpg.connect(database.admin_url)
    try:
        await conn.execute(
            "INSERT INTO workflows (id, tenant_id, record_type, name, draft)"
            " VALUES ($1, $2, 'incident', 'Flow', '{}')",
            flow,
            tenant,
        )
        await conn.execute(
            "INSERT INTO workflow_jobs (id, tenant_id, workflow_id, kind, instance_ids, status,"
            " total) VALUES ($1, $2, $3, 'retry', ARRAY[$4::uuid], 'done', 1)",
            job,
            tenant,
            flow,
            uuid.uuid4(),
        )
    finally:
        await conn.close()
    return job


async def _remove(database: db_testing.ThrowawayDatabase, job: uuid.UUID) -> None:
    conn = await asyncpg.connect(database.admin_url)
    try:
        await conn.execute("DELETE FROM workflow_jobs WHERE id = $1", job)
    finally:
        await conn.close()


def test_0107_upgrades_downgrades_and_upgrades_again(head: db_testing.ThrowawayDatabase) -> None:
    db_testing.downgrade(head.migrator_url, BEFORE)
    db_testing.migrate(head.migrator_url, "0107")


def test_the_downgrade_refuses_while_a_tenant_has_jobs(head: db_testing.ThrowawayDatabase) -> None:
    job = asyncio.run(_a_job(head))
    with pytest.raises(Exception, match="downgrade refused"):
        db_testing.downgrade(head.migrator_url, BEFORE)
    asyncio.run(_remove(head, job))  # this test's own row, in its throwaway database
    db_testing.downgrade(head.migrator_url, BEFORE)
