"""Migration 0152 (shared life cycle versions; ADR-049) never loses data.

The data step makes a tenant's existing life cycle version 1, published, and every record and
transition run on it. Up, down and up again while everything is version 1; once a tenant has a
version 2, the downgrade is refused and the table stays (rule 5h). Rows are seeded by SQL, never
through the application (memory: downgrade tests vs lifecycle audit).
"""

import asyncio
import uuid

import asyncpg
import pytest

from conftest import create_tenant
from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0149"  # 0152's down revision while building (re-pointed at its queue turn)
AFTER = "0152"


async def _an_incident_on_no_version(url: str, tenant: uuid.UUID) -> uuid.UUID:
    """Two statuses, one move between them and a record with no version, as before 0152."""
    conn = await asyncpg.connect(url)
    try:
        user, desk, item = (uuid.uuid4() for _ in range(3))
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            await conn.execute(
                "INSERT INTO users (id, tenant_id, display_name, first_name, user_type)"
                " VALUES ($1, $2, 'Sara', 'Sara', 'requester')",
                user,
                tenant,
            )
            await conn.execute(
                "INSERT INTO desks (id, tenant_id, code, labels)"
                " VALUES ($1, $2, 'it', '{}'::jsonb)",
                desk,
                tenant,
            )
            for code, category, order in (("open", "open", 1), ("in_progress", "open", 2)):
                await conn.execute(
                    "INSERT INTO work_item_statuses (tenant_id, type, code, category, colour,"
                    " sort_order) VALUES ($1, 'incident', $2, $3, '#aaaaaa', $4)",
                    tenant,
                    code,
                    category,
                    order,
                )
            await conn.execute(
                "INSERT INTO work_item_transitions (tenant_id, type, lifecycle, from_status,"
                " action, to_status, reason_mode) VALUES ($1, 'incident', 'standard', 'open',"
                " 'start_work', 'in_progress', 'none')",
                tenant,
            )
            await conn.execute(
                "INSERT INTO work_items (id, tenant_id, type, display_id, display_number, subject,"
                " requester_id, channel, priority, priority_source, status, status_category,"
                " desk_id) VALUES ($1, $2, 'incident', 'INC-1', 1, 'Printer', $3, 'phone', 'p3',"
                " 'matrix', 'open', 'open', $4)",
                item,
                tenant,
                user,
                desk,
            )
        return item
    finally:
        await conn.close()


async def _state(url: str, tenant: uuid.UUID, item: uuid.UUID) -> dict[str, object]:
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            versions = [
                tuple(r)
                for r in await conn.fetch(
                    "SELECT type, lifecycle, number, state FROM work_item_lifecycle_versions"
                    " ORDER BY type, lifecycle, number"
                )
            ]
            return {
                "versions": versions,
                "transition": await conn.fetchval(
                    "SELECT lifecycle_version FROM work_item_transitions"
                ),
                "record": await conn.fetchval(
                    "SELECT lifecycle_version FROM work_items WHERE id = $1", item
                ),
            }
    finally:
        await conn.close()


async def _version_2(url: str, tenant: uuid.UUID) -> None:
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            await conn.execute(
                "INSERT INTO work_item_lifecycle_versions (tenant_id, type, lifecycle, number,"
                " state) VALUES ($1, 'incident', 'standard', 2, 'draft')",
                tenant,
            )
    finally:
        await conn.close()


def test_0152_makes_version_1_and_refuses_the_downgrade_once_a_version_2_exists(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        tenant = asyncio.run(create_tenant(database.migrator_url))
        item = asyncio.run(_an_incident_on_no_version(database.admin_url, tenant))
        db_testing.migrate(database.migrator_url, AFTER)
        assert asyncio.run(_state(database.admin_url, tenant, item)) == {
            "versions": [("incident", "standard", 1, "published")],
            "transition": 1,
            "record": 1,
        }
        # Everything on version 1: the downgrade goes, and up again rebuilds the same.
        db_testing.downgrade(database.migrator_url, BEFORE)
        db_testing.migrate(database.migrator_url, AFTER)
        assert asyncio.run(_state(database.admin_url, tenant, item))["versions"] == [
            ("incident", "standard", 1, "published")
        ]
        asyncio.run(_version_2(database.admin_url, tenant))
        with pytest.raises(Exception, match="downgrade refused"):
            db_testing.downgrade(database.migrator_url, BEFORE)
        kept = asyncio.run(_state(database.admin_url, tenant, item))["versions"]
        assert isinstance(kept, list)
        assert len(kept) == 2  # the table and the draft stayed
    finally:
        db_testing.destroy(db_config, database)
