"""Migration 0043's data step: replies saved before WP-024 now wait for mail, and back again.

`work_item_conversations` has FORCE ROW LEVEL SECURITY, so the step runs per tenant (lane C's
0034 finding). This test seeds a reply "not sent: email channel not configured" at 0042,
migrates, checks it waits, downgrades and checks it is as before (expand/contract, D-113).
"""

import asyncio
import uuid

import asyncpg
import pytest

from conftest import create_tenant
from tooling import db_testing

pytestmark = pytest.mark.db


async def _seed_reply(admin_url: str, tenant: uuid.UUID) -> uuid.UUID:
    conn = await asyncpg.connect(admin_url)
    try:
        user, desk, item, entry = (uuid.uuid4() for _ in range(4))
        await conn.execute(
            "INSERT INTO users (id, tenant_id, display_name, first_name, user_type)"
            " VALUES ($1, $2, 'Sara', 'Sara', 'requester')",
            user,
            tenant,
        )
        await conn.execute(
            "INSERT INTO desks (id, tenant_id, code, labels) VALUES ($1, $2, 'it', '{}'::jsonb)",
            desk,
            tenant,
        )
        await conn.execute(
            "INSERT INTO work_item_statuses (tenant_id, type, code, category, colour, sort_order)"
            " VALUES ($1, 'incident', 'new', 'open', '#aaaaaa', 1)",
            tenant,
        )
        await conn.execute(
            "INSERT INTO work_items (id, tenant_id, type, display_id, display_number, subject,"
            " requester_id, channel, priority, priority_source, status, status_category, desk_id)"
            " VALUES ($1, $2, 'incident', 'INC-1', 1, 'Printer', $3, 'email', 'p3', 'matrix',"
            " 'new', 'open', $4)",
            item,
            tenant,
            user,
            desk,
        )
        await conn.execute(
            "INSERT INTO work_item_conversations (id, tenant_id, work_item_id, kind, visibility,"
            " reply_mode, body, delivery_state, delivery_reason)"
            " VALUES ($1, $2, $3, 'reply', 'public', 'reply', '<p>Hi</p>', 'not_sent',"
            " 'email_channel_not_configured')",
            entry,
            tenant,
            item,
        )
        return entry
    finally:
        await conn.close()


async def _state(admin_url: str, entry: uuid.UUID) -> tuple[str, str]:
    conn = await asyncpg.connect(admin_url)
    try:
        row = await conn.fetchrow(
            "SELECT delivery_state, delivery_reason FROM work_item_conversations WHERE id = $1",
            entry,
        )
        assert row is not None
        return str(row["delivery_state"]), str(row["delivery_reason"])
    finally:
        await conn.close()


def test_replies_saved_before_wp024_wait_for_mail_and_the_downgrade_restores_them(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to="0042")
    try:
        tenant = asyncio.run(create_tenant(database.migrator_url))
        entry = asyncio.run(_seed_reply(database.admin_url, tenant))
        db_testing.migrate(database.migrator_url, "0043")
        assert asyncio.run(_state(database.admin_url, entry)) == (
            "waiting",
            "mail_not_configured",
        )
        db_testing.downgrade(database.migrator_url, "0042")
        assert asyncio.run(_state(database.admin_url, entry)) == (
            "not_sent",
            "email_channel_not_configured",
        )
    finally:
        db_testing.destroy(db_config, database)
