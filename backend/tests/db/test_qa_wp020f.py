"""WP-020f QA findings (~/Desktop/qa-wp020f/QA-REPORT.md): one test per bug, named after it.

Real PostgreSQL, the incidents test world.
"""

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY, Database
from app.core.tenancy import TenantContext
from app.modules.work_items.infra.models import WorkItem
from app.modules.work_items.service import closing
from app.modules.work_items.service.notifications import IncidentNotifications
from tests.db.test_closing_api import change_closure, fresh, settings
from tests.db.test_incidents_api import World, field_codes, incidents_world
from tooling.db_testing import ThrowawayDatabase

pytestmark = [pytest.mark.db, pytest.mark.valkey]


@pytest_asyncio.fixture
async def world(migrated_db: ThrowawayDatabase) -> AsyncIterator[World]:
    async with incidents_world(migrated_db) as built:
        yield built


@pytest.fixture
def email_reaches(world: World) -> Iterator[dict[uuid.UUID, str | None]]:
    """An "email" channel whose reach per tenant the test sets (None: reaches)."""
    reach: dict[uuid.UUID, str | None] = {}

    async def reaches(session: AsyncSession) -> str | None:
        context = session.info[SESSION_TENANT_KEY]
        assert isinstance(context, TenantContext)
        return reach.get(context.tenant_id, "mail_not_configured")

    del world  # registered after the app started
    closing.register_requester_channel("email", reaches)
    yield reach
    closing.unregister_requester_channel("email")


async def _resolved_at(app_db: Database, tenant: uuid.UUID, record_id: str) -> datetime:
    async with app_db.tenant_session(TenantContext(tenant)) as session:
        row = await session.get(WorkItem, uuid.UUID(record_id))
        assert row is not None
        assert row.resolved_at is not None
        return row.resolved_at


# --- BUG-02: nothing told the record that the requester was notified -----------------------------


async def test_bug_02_a_channel_reaches_each_tenant_on_its_own_and_says_why(
    world: World, email_reaches: dict[uuid.UUID, str | None]
) -> None:
    a, b = world.a, world.b
    email_reaches[a.tenant] = None  # tenant A's mail works; B's mail is failing
    email_reaches[b.tenant] = "mail_failing"
    assert (await change_closure(world, a, auto_close_days=3)).status_code == 200
    refused = await change_closure(world, b, auto_close_days=3)
    assert field_codes(refused) == {"auto_close_days": "auto_close_needs_notifications"}
    closure_a = (await settings(world, a))["closure"]
    closure_b = (await settings(world, b))["closure"]
    assert closure_a["requester_channels"] == ["email"]
    assert closure_b["requester_channels"] == []
    # The settings screen says why a channel does not reach this tenant's requesters.
    assert closure_b["requester_channel_states"] == [{"channel": "email", "reason": "mail_failing"}]


async def test_bug_02_only_the_current_resolution_starts_the_clock(
    world: World, app_db: Database
) -> None:
    org = world.a
    item = (await world.act(org, org.admin, await world.create(org, org.admin), "resolve")).json()
    first = await _resolved_at(app_db, org.tenant, item["id"])
    reopened = await world.act(
        org, org.admin, item, "reopen", reason_code="not_fixed", reason_text="Still jams"
    )
    again = (await world.act(org, org.admin, reopened.json(), "resolve")).json()
    async with app_db.tenant_session(TenantContext(org.tenant)) as session:
        # A late delivery of the first resolution's notice does not count for the second.
        assert not await closing.resolution_notified(
            session, uuid.UUID(again["id"]), event_at=first, at=datetime.now(UTC)
        )
    second = await _resolved_at(app_db, org.tenant, again["id"])
    told = datetime.now(UTC)
    async with app_db.tenant_session(TenantContext(org.tenant)) as session:
        assert await closing.resolution_notified(
            session, uuid.UUID(again["id"]), event_at=second, at=told
        )
    async with app_db.tenant_session(TenantContext(org.tenant)) as session:
        # Once per resolution: a second channel or a retry changes nothing.
        assert not await closing.resolution_notified(
            session, uuid.UUID(again["id"]), event_at=second, at=told + timedelta(hours=1)
        )
    assert (await fresh(world, org, again))["resolution_notified_at"] is not None


async def test_bug_02_a_delivered_resolution_notice_to_the_requester_starts_the_clock(
    world: World, app_db: Database
) -> None:
    org = world.a
    item = (await world.act(org, org.admin, await world.create(org, org.admin), "resolve")).json()
    resolved_at = await _resolved_at(app_db, org.tenant, item["id"])
    source = IncidentNotifications()
    record_id = uuid.UUID(item["id"])
    now = datetime.now(UTC)

    async def delivered(event_code: str, reasons: tuple[str, ...]) -> Any:  # noqa: ANN401
        async with app_db.tenant_session(TenantContext(org.tenant)) as session:
            await source.delivered(
                session,
                event_code=event_code,
                record_id=record_id,
                user_id=org.requester,
                reasons=reasons,
                event_at=resolved_at,
                at=now,
            )

    # Another notice, or the resolution notice to someone who is not the requester: no clock.
    await delivered("incident.assigned", ("requester",))
    await delivered("incident.resolved", ("assignee", "followers"))
    assert (await fresh(world, org, item))["resolution_notified_at"] is None
    await delivered("incident.resolved", ("requester",))
    assert (await fresh(world, org, item))["resolution_notified_at"] is not None


async def test_bug_02_auto_close_starts_once_a_channel_reaches_and_a_notice_is_delivered(
    world: World, app_db: Database, email_reaches: dict[uuid.UUID, str | None]
) -> None:
    from app.modules.work_items.domain.types import INCIDENT  # noqa: PLC0415 - test-only
    from app.modules.work_items.service import resolution  # noqa: PLC0415 - test-only

    org = world.a
    email_reaches[org.tenant] = None
    assert (await change_closure(world, org, auto_close_days=1)).status_code == 200
    item = (await world.act(org, org.admin, await world.create(org, org.admin), "resolve")).json()
    resolved_at = await _resolved_at(app_db, org.tenant, item["id"])
    async with app_db.tenant_session(TenantContext(org.tenant)) as session:
        await IncidentNotifications().delivered(
            session,
            event_code="incident.resolved",
            record_id=uuid.UUID(item["id"]),
            user_id=org.requester,
            reasons=("requester",),
            event_at=resolved_at,
            at=datetime.now(UTC) - timedelta(days=4),
        )
    # The tenant's mail stops working: auto-close waits, never closing on a channel that broke.
    email_reaches[org.tenant] = "mail_failing"
    async with app_db.tenant_session(TenantContext(org.tenant)) as session:
        assert await resolution.auto_close_due(session, INCIDENT, datetime.now(UTC)) == 0
    email_reaches[org.tenant] = None
    async with app_db.tenant_session(TenantContext(org.tenant)) as session:
        assert await resolution.auto_close_due(session, INCIDENT, datetime.now(UTC)) == 1
    assert (await fresh(world, org, item))["status_category"] == "closed"
