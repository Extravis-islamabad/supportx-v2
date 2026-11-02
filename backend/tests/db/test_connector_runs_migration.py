"""Migration 0049: a tenant's mailbox failure rule carries over to connector.failing, and back.

An admin who switched the mailbox notice off (or sent it to other people) keeps that choice when
the notice moves to the connector events. The downgrade removes only the copy (D-113).
"""

import asyncio
import uuid

import asyncpg
import pytest

from conftest import create_tenant
from tooling import db_testing

pytestmark = pytest.mark.db


async def _seed_rule(admin_url: str, tenant: uuid.UUID) -> None:
    conn = await asyncpg.connect(admin_url)
    try:
        await conn.execute(
            "INSERT INTO notification_rules (id, tenant_id, event_code, enabled, recipients,"
            " channels) VALUES ($1, $2, 'mailbox.failing', false, '{mail_admins}', '{email}')",
            uuid.uuid4(),
            tenant,
        )
    finally:
        await conn.close()


async def _rules(admin_url: str) -> list[tuple[object, ...]]:
    conn = await asyncpg.connect(admin_url)
    try:
        rows = await conn.fetch(
            "SELECT tenant_id, event_code, enabled, recipients, channels FROM notification_rules"
            " ORDER BY tenant_id, event_code"
        )
        return [tuple(r) for r in rows]
    finally:
        await conn.close()


def test_a_saved_mailbox_rule_carries_over_and_the_downgrade_removes_only_the_copy(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to="0045")
    try:
        a = asyncio.run(create_tenant(database.migrator_url))
        b = asyncio.run(create_tenant(database.migrator_url))  # kept the default: no rule
        asyncio.run(_seed_rule(database.admin_url, a))
        before = asyncio.run(_rules(database.admin_url))
        db_testing.migrate(database.migrator_url, "0049")
        after = asyncio.run(_rules(database.admin_url))
        assert (a, "connector.failing", False, ["connector_admins"], ["email"]) in after
        assert not [r for r in after if r[0] == b]
        db_testing.downgrade(database.migrator_url, "0045")
        assert asyncio.run(_rules(database.admin_url)) == before
    finally:
        db_testing.destroy(db_config, database)
