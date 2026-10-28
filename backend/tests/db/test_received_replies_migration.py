"""Migration 0040 turns requester replies stored as "not_sent" into "received" (BUG-01).

The data step runs per tenant (FORCE RLS, D-113): a test proves it reaches existing tenants,
both ways.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator

import asyncpg
import pytest
import pytest_asyncio

from app.core.tenancy import TenantContext
from app.modules.identity_access import subject_for
from app.modules.work_items.domain.types import INCIDENT
from app.modules.work_items.infra.models import WorkItem
from app.modules.work_items.service import conversations
from tests.db.test_incidents_api import World, incidents_world
from tooling import db_testing

pytestmark = [pytest.mark.db, pytest.mark.valkey]


@pytest.fixture
def own_db(db_config: db_testing.DbTestConfig) -> Iterator[db_testing.ThrowawayDatabase]:
    """A database of its own: this test migrates it down and up again."""
    database = db_testing.create(db_config, migrate_to="head")
    try:
        yield database
    finally:
        db_testing.destroy(db_config, database)


@pytest_asyncio.fixture
async def own_world(own_db: db_testing.ThrowawayDatabase) -> AsyncIterator[World]:
    async with incidents_world(own_db) as built:
        yield built


async def _states(admin_url: str, tenant: uuid.UUID) -> list[str]:
    conn = await asyncpg.connect(admin_url)
    try:
        rows = await conn.fetch(
            "SELECT delivery_state FROM work_item_conversations"
            " WHERE tenant_id = $1 AND kind = 'reply' ORDER BY created_at",
            tenant,
        )
    finally:
        await conn.close()
    return [r["delivery_state"] for r in rows]


async def test_bug_01_existing_requester_replies_become_received_and_back(own_world: World) -> None:
    world, org = own_world, own_world.a
    item = await world.create(org, org.admin)
    async with world.app.state.db.tenant_session(
        TenantContext(org.tenant, user_id=org.requester)
    ) as session:
        record = await session.get(WorkItem, uuid.UUID(item["id"]))
        assert record is not None
        await conversations.add_requester_reply(
            session,
            INCIDENT,
            record,
            body="<p>Still broken.</p>",
            source="email",
            automatic=False,
            subject=await subject_for(session, org.tenant, org.requester),
            holders=world.app.state.policy,
        )
    url = world.db.migrator_url
    admin = world.db.admin_url
    assert await _states(admin, org.tenant) == ["received"]
    await asyncio.to_thread(db_testing.downgrade, url, "0039")
    assert await _states(admin, org.tenant) == ["not_sent"]
    await asyncio.to_thread(db_testing.migrate, url)
    assert await _states(admin, org.tenant) == ["received"]
