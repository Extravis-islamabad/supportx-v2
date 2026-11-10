"""Migration 0125: every role's `<type>.assign_outside_group` grant is dropped (D-154a).

Haider, 2026-11-10: nobody assigns past a record's group any more, for all work-item types. The
grants go in every tenant (role_permissions forces RLS, so the step runs per tenant); the role's
other grants stay as they were.
"""

import asyncio
import uuid
from collections.abc import Iterator

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0124"  # 0125's down revision


@pytest.fixture
def before(db_config: db_testing.DbTestConfig) -> Iterator[db_testing.ThrowawayDatabase]:
    """A throwaway database migrated to just before 0125."""
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        yield database
    finally:
        db_testing.destroy(db_config, database)


async def _seed(url: str) -> list[uuid.UUID]:
    """Two tenants, each with a custom role holding the old grant on two types and others."""
    roles: list[uuid.UUID] = []
    conn = await asyncpg.connect(url)
    try:
        for n in range(2):
            tenant, role = uuid.uuid4(), uuid.uuid4()
            await conn.execute(
                "INSERT INTO tenants (id, name, slug) VALUES ($1, $2, $3)",
                tenant,
                f"Grants {n}",
                f"t-{tenant.hex[:12]}",
            )
            await conn.execute(
                "INSERT INTO roles (id, tenant_id, key, name) VALUES ($1, $2, 'lead', 'Lead')",
                role,
                tenant,
            )
            for permission in (
                "incidents.assign_outside_group",
                "problems.assign_outside_group",
                "incidents.assign",
                "incidents.view",
            ):
                await conn.execute(
                    "INSERT INTO role_permissions (tenant_id, role_id, permission, scope)"
                    " VALUES ($1, $2, $3, 'all')",
                    tenant,
                    role,
                    permission,
                )
            roles.append(role)
    finally:
        await conn.close()
    return roles


async def _held(url: str, role: uuid.UUID) -> set[str]:
    conn = await asyncpg.connect(url)
    try:
        rows = await conn.fetch("SELECT permission FROM role_permissions WHERE role_id = $1", role)
    finally:
        await conn.close()
    return {r["permission"] for r in rows}


def test_every_tenants_assign_outside_group_grants_go_and_nothing_else(
    before: db_testing.ThrowawayDatabase,
) -> None:
    roles = asyncio.run(_seed(before.admin_url))
    db_testing.migrate(before.migrator_url, "0125")
    for role in roles:  # both tenants: the step ran under each one's app.tenant_id
        assert asyncio.run(_held(before.admin_url, role)) == {"incidents.assign", "incidents.view"}
    # Schema-only downgrade: it runs, and the grants stay dropped (the docstring says why).
    db_testing.downgrade(before.migrator_url, BEFORE)
    assert asyncio.run(_held(before.admin_url, roles[0])) == {"incidents.assign", "incidents.view"}
