"""Migration 0049: mailbox notice rules and set-up rights carry over to the connectors, and back.

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


async def _seed_role(admin_url: str, tenant: uuid.UUID) -> uuid.UUID:
    conn = await asyncpg.connect(admin_url)
    try:
        role = uuid.uuid4()
        await conn.execute(
            "INSERT INTO roles (id, tenant_id, key, name) VALUES ($1, $2, 'mail_team', 'Mail')",
            role,
            tenant,
        )
        await conn.execute(
            "INSERT INTO role_permissions (tenant_id, role_id, permission, scope)"
            " VALUES ($1, $2, 'mailboxes.manage', 'all')",
            tenant,
            role,
        )
        return role
    finally:
        await conn.close()


async def _grants(admin_url: str, role: uuid.UUID) -> set[tuple[str, str]]:
    conn = await asyncpg.connect(admin_url)
    try:
        rows = await conn.fetch(
            "SELECT permission, scope FROM role_permissions WHERE role_id = $1", role
        )
        return {(r["permission"], r["scope"]) for r in rows}
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


def test_mailbox_rules_and_rights_carry_over_and_the_downgrade_removes_only_the_copies(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to="0045")
    try:
        a = asyncio.run(create_tenant(database.migrator_url))
        b = asyncio.run(create_tenant(database.migrator_url))  # kept the default: no rule
        asyncio.run(_seed_rule(database.admin_url, a))
        role = asyncio.run(_seed_role(database.admin_url, a))
        before = asyncio.run(_rules(database.admin_url))
        db_testing.migrate(database.migrator_url, "0049")
        after = asyncio.run(_rules(database.admin_url))
        assert (a, "connector.failing", False, ["connector_admins"], ["email"]) in after
        assert not [r for r in after if r[0] == b]
        assert asyncio.run(_grants(database.admin_url, role)) == {
            ("mailboxes.manage", "all"),
            ("integrations.manage_email", "all"),  # same scope; the old key stays
        }
        db_testing.downgrade(database.migrator_url, "0045")
        assert asyncio.run(_rules(database.admin_url)) == before
        assert asyncio.run(_grants(database.admin_url, role)) == {("mailboxes.manage", "all")}
    finally:
        db_testing.destroy(db_config, database)
