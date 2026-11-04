"""Connector defaults per tenant in a real database (WP-040, D-041; migration 0057)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text

from app.core.tenancy import TenantContext
from app.modules.integrations.domain.connector_health import RunCounts
from app.modules.integrations.service import runs
from tests.db.test_directories_api import BODY as DIRECTORY
from tests.db.test_directories_api import _add as add_directory
from tests.db.test_directories_api import fake
from tests.db.test_files_api import audit_actions
from tests.db.test_incidents_api import World, world

__all__ = ["fake", "world"]  # fixtures, re-used

pytestmark = [pytest.mark.db]

API = "/integrations/connector-settings"


async def _put(world: World, version: int, **body: Any) -> Any:  # noqa: ANN401 - the response
    return await world.call(
        "PUT", API, world.a, world.a.admin, json=body, headers={"If-Match": f'"{version}"'}
    )


async def _run(world: World, instance: uuid.UUID, error: str | None = None) -> None:
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        await runs.record_run(
            session,
            "mailbox",
            instance,
            started_at=datetime.now(UTC),
            counts=RunCounts(),
            error_code=error,
            auth_failure=False,
        )


async def _failing(world: World, instance: uuid.UUID) -> bool:
    rows = await world.sql("SELECT failing FROM connector_health WHERE instance_id = $1", instance)
    return bool(rows[0]["failing"])


async def test_appendix_a_until_saved_then_the_tenants_own(world: World) -> None:
    first = await world.call("GET", API, world.a, world.a.admin)
    assert first.status_code == 200, first.text
    assert first.json() == {
        "failing_after_runs": 3,
        "error_retention_days": 90,
        "sync_minutes": 30,
        "version": 0,
    }
    saved = await _put(world, 0, failing_after_runs=1, sync_minutes=60)
    assert saved.status_code == 200, saved.text
    assert saved.json() == {
        "failing_after_runs": 1,
        "error_retention_days": 90,  # left out: kept
        "sync_minutes": 60,
        "version": 1,
    }
    stale = await _put(world, 0, error_retention_days=30)
    assert stale.status_code == 409, stale.text
    out = await _put(world, 1, failing_after_runs=0, error_retention_days=400)
    assert out.status_code == 422, out.text
    assert {(e["field"], e["code"]) for e in out.json()["errors"]} == {
        ("body.failing_after_runs", "out_of_range"),
        ("body.error_retention_days", "out_of_range"),
    }
    assert "connector_settings.changed" in await audit_actions(world, world.a)
    details = await world.sql(
        "SELECT details FROM audit_entries WHERE tenant_id = $1"
        " AND action = 'connector_settings.changed'",
        world.a.tenant,
    )
    assert '"from": 3' in details[0]["details"]  # each change, before and after
    events = await world.sql(
        "SELECT count(*) AS n FROM outbox_events WHERE tenant_id = $1"
        " AND event_type = 'integrations.connector_settings.changed'",
        world.a.tenant,
    )
    assert events[0]["n"] == 1  # through the outbox: every admin's card updates live
    other = await world.call("GET", API, world.b, world.b.admin)
    assert other.json()["failing_after_runs"] == 3  # tenant B keeps its own


async def test_the_failing_threshold_follows_the_setting(world: World) -> None:
    instance = uuid.uuid4()
    await _run(world, instance, "imap_unreachable")
    assert not await _failing(world, instance)  # the default: 3 in a row
    assert (await _put(world, 0, failing_after_runs=1)).status_code == 200
    other = uuid.uuid4()
    await _run(world, other, "imap_unreachable")
    assert await _failing(world, other)  # now at the first failure


async def test_errors_are_kept_as_long_as_the_setting_says(world: World) -> None:
    instance = uuid.uuid4()
    await _run(world, instance, "imap_unreachable")
    assert (await _put(world, 0, error_retention_days=7)).status_code == 200
    later = datetime.now(UTC) + timedelta(days=8)
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        assert (await runs.purge(session, later))[1] == 1  # 7 days, not 90


async def test_the_settings_are_isolated_by_rls(world: World) -> None:
    assert (await _put(world, 0, sync_minutes=45)).status_code == 200
    async with world.app.state.db.tenant_session(TenantContext(world.b.tenant)) as session:
        rows = (await session.execute(text("SELECT tenant_id FROM connector_settings"))).all()
        assert rows == []
        changed = await session.execute(text("UPDATE connector_settings SET sync_minutes = 15"))
        assert changed.rowcount == 0
    kept = await world.sql(
        "SELECT sync_minutes FROM connector_settings WHERE tenant_id = $1", world.a.tenant
    )
    assert kept[0]["sync_minutes"] == 45


@pytest.mark.usefixtures("fake")
async def test_a_new_directory_takes_the_tenants_interval(world: World) -> None:
    assert (await _put(world, 0, sync_minutes=60)).status_code == 200
    created = await add_directory(world)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["interval_minutes"] == 60  # left out: the tenant's default
    changed = await world.call(
        "PUT",
        f"/integrations/directories/{body['id']}",
        world.a,
        world.a.admin,
        json={k: v for k, v in DIRECTORY.items() if k != "credential"} | {"name": "Renamed"},
        headers={"If-Match": f'"{body["version"]}"'},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["interval_minutes"] == 60  # left out on a change: kept
