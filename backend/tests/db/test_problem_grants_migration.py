"""Migration 0077: saved roles keep their problem access (WP-044a; lane B's condition).

A custom role with the reserved `problems.manage` at a scope gets create (all), edit, assign
and close at that scope; `problems.view` stays; manage never becomes delete. And back.
"""

import asyncio
import uuid
from collections.abc import Iterator

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db


@pytest.fixture
def at_0076(db_config: db_testing.DbTestConfig) -> Iterator[db_testing.ThrowawayDatabase]:
    """A throwaway database migrated to just before the grants step."""
    database = db_testing.create(db_config, migrate_to="0076")
    try:
        yield database
    finally:
        db_testing.destroy(db_config, database)


async def _seed(url: str) -> dict[str, uuid.UUID]:
    """A tenant with two custom roles holding the old reserved grants (site and group)."""
    tenant = uuid.uuid4()
    roles = {"site": uuid.uuid4(), "group": uuid.uuid4()}
    conn = await asyncpg.connect(url)
    try:
        await conn.execute(
            "INSERT INTO tenants (id, name, slug) VALUES ($1, 'Prb', $2)",
            tenant,
            f"t-{tenant.hex[:12]}",
        )
        for scope, role in roles.items():
            await conn.execute(
                "INSERT INTO roles (id, tenant_id, key, name) VALUES ($1, $2, $3, $3)",
                role,
                tenant,
                f"prb_{scope}",
            )
            for permission, at in (("problems.view", "all"), ("problems.manage", scope)):
                await conn.execute(
                    "INSERT INTO role_permissions (tenant_id, role_id, permission, scope)"
                    " VALUES ($1, $2, $3, $4)",
                    tenant,
                    role,
                    permission,
                    at,
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


def test_manage_becomes_the_engine_actions_at_its_scope_and_back(
    at_0076: db_testing.ThrowawayDatabase,
) -> None:
    roles = asyncio.run(_seed(at_0076.admin_url))
    db_testing.migrate(at_0076.migrator_url, "0077")
    for scope, role in roles.items():
        assert asyncio.run(_grants(at_0076.admin_url, role)) == {
            ("problems.view", "all"),
            ("problems.create", "all"),  # create has no narrower scope
            ("problems.edit", scope),
            ("problems.assign", scope),
            ("problems.close", scope),
        }  # never problems.delete
    db_testing.downgrade(at_0076.migrator_url, "0076")
    for scope, role in roles.items():
        assert asyncio.run(_grants(at_0076.admin_url, role)) == {
            ("problems.view", "all"),
            ("problems.manage", scope),
        }


async def _change(url: str, statement: str, *args: object) -> None:
    conn = await asyncpg.connect(url)
    try:
        await conn.execute(statement, *args)
    finally:
        await conn.close()


@pytest.mark.parametrize("change", ["delete_granted", "trimmed_to_assign", "close_elsewhere"])
def test_the_downgrade_refuses_rather_than_lose_a_grant_made_after_the_upgrade(
    at_0076: db_testing.ThrowawayDatabase, change: str
) -> None:
    """Lane B's review (rule 5h): a grant problems.manage cannot hold stops the downgrade."""
    roles = asyncio.run(_seed(at_0076.admin_url))
    db_testing.migrate(at_0076.migrator_url, "0077")
    role = roles["group"]
    if change == "delete_granted":  # a key manage never covered
        asyncio.run(
            _change(
                at_0076.admin_url,
                "INSERT INTO role_permissions (tenant_id, role_id, permission, scope)"
                " SELECT tenant_id, id, 'problems.delete', 'all' FROM roles WHERE id = $1",
                role,
            )
        )
    elif change == "trimmed_to_assign":  # manage would widen it
        asyncio.run(
            _change(
                at_0076.admin_url,
                "DELETE FROM role_permissions WHERE role_id = $1 AND permission IN"
                " ('problems.create', 'problems.edit', 'problems.close')",
                role,
            )
        )
    else:  # close at another scope than edit
        asyncio.run(
            _change(
                at_0076.admin_url,
                "UPDATE role_permissions SET scope = 'all'"
                " WHERE role_id = $1 AND permission = 'problems.close'",
                role,
            )
        )
    before = {k: asyncio.run(_grants(at_0076.admin_url, r)) for k, r in roles.items()}
    with pytest.raises(Exception, match="below 0077"):
        db_testing.downgrade(at_0076.migrator_url, "0076")
    after = {k: asyncio.run(_grants(at_0076.admin_url, r)) for k, r in roles.items()}
    assert after == before  # nothing changed, nothing lost
