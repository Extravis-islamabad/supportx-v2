"""Migration 0091: custom roles' reserved `releases.manage` becomes the engine's actions, and back.

Lane B's condition for moving releases.* into work_items: a saved custom role keeps its access.
"""

import asyncio
import uuid
from collections.abc import Iterator

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db


@pytest.fixture
def at_0090(db_config: db_testing.DbTestConfig) -> Iterator[db_testing.ThrowawayDatabase]:
    """A throwaway database migrated to just before the release grants."""
    database = db_testing.create(db_config, migrate_to="0090")
    try:
        yield database
    finally:
        db_testing.destroy(db_config, database)


async def _seed(url: str) -> dict[str, uuid.UUID]:
    """A tenant with custom roles holding the old reserved grants (two scopes, and view only)."""
    tenant = uuid.uuid4()
    roles = {"wide": uuid.uuid4(), "group": uuid.uuid4(), "viewer": uuid.uuid4()}
    conn = await asyncpg.connect(url)
    try:
        await conn.execute(
            "INSERT INTO tenants (id, name, slug) VALUES ($1, 'Rel', $2)",
            tenant,
            f"t-{tenant.hex[:12]}",
        )
        for key, role in roles.items():
            await conn.execute(
                "INSERT INTO roles (id, tenant_id, key, name) VALUES ($1, $2, $3, $3)",
                role,
                tenant,
                f"rel_{key}",
            )
            scope = "all" if key == "wide" else "group"
            held = ("releases.view",) if key == "viewer" else ("releases.view", "releases.manage")
            for permission in held:
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


def test_releases_manage_becomes_the_engine_actions_and_never_delete(
    at_0090: db_testing.ThrowawayDatabase,
) -> None:
    roles = asyncio.run(_seed(at_0090.admin_url))
    db_testing.migrate(at_0090.migrator_url, "0091")
    assert asyncio.run(_grants(at_0090.admin_url, roles["group"])) == {
        ("releases.view", "group"),
        ("releases.create", "all"),  # create has only `all`
        ("releases.edit", "group"),
        ("releases.assign", "group"),
        ("releases.cancel", "group"),
        ("releases.reopen", "group"),
    }
    wide = asyncio.run(_grants(at_0090.admin_url, roles["wide"]))
    assert ("releases.edit", "all") in wide
    assert not {p for p, _ in wide} & {"releases.delete", "releases.manage"}
    assert asyncio.run(_grants(at_0090.admin_url, roles["viewer"])) == {("releases.view", "group")}

    db_testing.downgrade(at_0090.migrator_url, "0090")
    assert asyncio.run(_grants(at_0090.admin_url, roles["group"])) == {
        ("releases.view", "group"),
        ("releases.manage", "group"),
    }
