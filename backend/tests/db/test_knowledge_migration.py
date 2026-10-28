"""Migration 0036: custom roles' reserved `knowledge.manage` becomes the D-108 grants, and back."""

import asyncio
import uuid
from collections.abc import Iterator

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db


@pytest.fixture
def at_0035(db_config: db_testing.DbTestConfig) -> Iterator[db_testing.ThrowawayDatabase]:
    """A throwaway database migrated to just before knowledge."""
    database = db_testing.create(db_config, migrate_to="0035")
    try:
        yield database
    finally:
        db_testing.destroy(db_config, database)


async def _seed(url: str) -> dict[str, uuid.UUID]:
    """A tenant with two custom roles holding the old reserved grants (at both scopes)."""
    tenant = uuid.uuid4()
    roles = {"wide": uuid.uuid4(), "group": uuid.uuid4()}
    conn = await asyncpg.connect(url)
    try:
        await conn.execute(
            "INSERT INTO tenants (id, name, slug) VALUES ($1, 'Kb', $2)",
            tenant,
            f"t-{tenant.hex[:12]}",
        )
        for key, role in roles.items():
            await conn.execute(
                "INSERT INTO roles (id, tenant_id, key, name) VALUES ($1, $2, $3, $3)",
                role,
                tenant,
                f"kb_{key}",
            )
            scope = "all" if key == "wide" else "group"
            for permission in ("knowledge.view", "knowledge.manage"):
                await conn.execute(
                    "INSERT INTO role_permissions (tenant_id, role_id, permission, scope)"
                    " VALUES ($1, $2, $3, $4)",
                    tenant,
                    role,
                    permission,
                    scope,
                )
    finally:
        await conn.close()
    return roles


async def _grants(url: str, role: uuid.UUID) -> set[tuple[str, str]]:
    conn = await asyncpg.connect(url)
    try:
        rows = await conn.fetch(
            "SELECT permission, scope FROM role_permissions WHERE role_id = $1", role
        )
    finally:
        await conn.close()
    return {(r["permission"], r["scope"]) for r in rows}


def test_knowledge_manage_becomes_create_edit_own_and_submit(
    at_0035: db_testing.ThrowawayDatabase,
) -> None:
    roles = asyncio.run(_seed(at_0035.admin_url))
    db_testing.migrate(at_0035.migrator_url, "0036")
    # create keeps the scope; edit own and submit exist only at `own` (D-108 (7)).
    assert asyncio.run(_grants(at_0035.admin_url, roles["wide"])) == {
        ("knowledge.view", "all"),
        ("knowledge.create", "all"),
        ("knowledge.edit_own", "own"),
        ("knowledge.submit", "own"),
    }
    assert ("knowledge.create", "group") in asyncio.run(_grants(at_0035.admin_url, roles["group"]))

    db_testing.downgrade(at_0035.migrator_url, "0035")
    assert asyncio.run(_grants(at_0035.admin_url, roles["group"])) == {
        ("knowledge.view", "group"),
        ("knowledge.manage", "group"),
    }
