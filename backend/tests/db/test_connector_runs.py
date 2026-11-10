"""Connector runs, health, errors and retention in a real database (WP-040, REQ-INT-004/005)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.core.tenancy import TenantContext
from app.modules.integrations.domain.connector_health import RunCounts
from app.modules.integrations.service import runs
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import World
from tests.db.test_mailboxes_api import add, with_key_ring

__all__ = ["module_world", "shared_world"]  # fixture, re-used

pytestmark = [pytest.mark.db, MODULE_LOOP]


async def _run(world: World, instance: uuid.UUID, error: str | None = None) -> None:
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        await runs.record_run(
            session,
            "mailbox",
            instance,
            started_at=datetime.now(UTC),
            counts=RunCounts(read=2, created=1, skipped=1) if error is None else RunCounts(),
            error_code=error,
            auth_failure=error == "imap_login_failed",
        )


async def _events(world: World, instance: uuid.UUID) -> list[str]:
    rows = await world.sql(
        "SELECT event_type FROM outbox_events WHERE tenant_id = $1 AND aggregate_id = $2"
        " AND event_type LIKE 'integrations.connector.%' ORDER BY id",
        world.a.tenant,
        str(instance),
    )
    return [r["event_type"].removeprefix("integrations.connector.") for r in rows]


async def test_fifty_failed_runs_tell_the_admins_once_and_the_recovery_once(world: World) -> None:
    instance = uuid.uuid4()
    for _ in range(50):
        await _run(world, instance, "imap_unreachable")
    await _run(world, instance)
    await _run(world, instance)
    assert await _events(world, instance) == ["failing", "recovered"]
    errors = await world.sql(
        "SELECT count(*) AS n FROM connector_errors WHERE instance_id = $1", instance
    )
    assert errors[0]["n"] == 50  # every failure is in the error list (REQ-INT-005 AC3)


async def test_the_catalogue_shows_the_last_day_and_the_last_error(world: World) -> None:
    with_key_ring(world)
    mailbox = uuid.UUID((await add(world)).json()["id"])
    await _run(world, mailbox, "imap_unreachable")
    await _run(world, mailbox)
    await _run(world, mailbox)
    await world.sql(  # a run from two days ago is outside the 24-hour counts
        "UPDATE connector_runs SET finished_at = now() - interval '2 days'"
        " WHERE id = (SELECT id FROM connector_runs WHERE instance_id = $1"
        " ORDER BY finished_at LIMIT 1)",
        mailbox,
    )
    response = await world.call("GET", "/integrations/catalogue", world.a, world.a.admin)
    (kind,) = [k for k in response.json() if k["code"] == "mailbox"]
    (instance,) = kind["instances"]
    assert instance["counts_24h"] == {
        "runs": 2,
        "failed_runs": 0,
        "read": 4,
        "created": 2,
        "updated": 0,
        "skipped": 2,
        "failed": 0,
    }
    assert instance["last_error_code"] == "imap_unreachable"
    assert instance["failing_since"] is None


async def test_runs_and_errors_past_their_retention_are_dropped(world: World) -> None:
    instance = uuid.uuid4()
    await _run(world, instance, "imap_unreachable")
    await _run(world, instance)
    later = datetime.now(UTC) + timedelta(days=8)
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        assert await runs.purge(session, later) == (2, 0)  # errors stay 90 days
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        assert await runs.purge(session, later + timedelta(days=90)) == (0, 1)


async def test_connector_tables_are_isolated_by_rls(world: World) -> None:
    instance = uuid.uuid4()
    await _run(world, instance, "imap_unreachable")
    tables = ("connector_runs", "connector_errors", "connector_health")
    async with world.app.state.db.tenant_session(TenantContext(world.b.tenant)) as session:
        for table in tables:
            rows = (await session.execute(text(f"SELECT tenant_id FROM {table}"))).all()  # noqa: S608 - fixed names
            assert rows == [], table
        changed = await session.execute(
            text("UPDATE connector_health SET failing = true WHERE instance_id = :id"),
            {"id": instance},
        )
        assert changed.rowcount == 0
        assert await runs.purge(session, datetime.now(UTC) + timedelta(days=365)) == (0, 0)
    rows = await world.sql(
        "SELECT count(*) AS n FROM connector_runs WHERE instance_id = $1", instance
    )
    assert rows[0]["n"] == 1
