"""Life cycle versions (ADR-049; WP-046a S4, REQ-INC-049).

Real PostgreSQL as the application role:
- `work_item_lifecycle_versions` is isolated per tenant (rule 5a): tenant B never reads, changes or
  writes tenant A's versions.
- A record runs on the version it was made on (REQ-INC-049 AC3): once version 2 is published, an
  incident made before keeps version 1's moves and a new one gets version 2's.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.tenancy import TenantContext
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import World, states

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixture, re-used


async def _publish_version_2_without_start_work(world: World) -> None:
    """Tenant A's incidents get version 2: version 1's moves, but "start work" from new gone."""
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        await session.execute(
            text(
                "INSERT INTO work_item_lifecycle_versions (tenant_id, type, lifecycle, number,"
                " state, published_at) VALUES (:t, 'incident', 'standard', 2, 'published', now())"
            ),
            {"t": world.a.tenant},
        )
        await session.execute(
            text(
                "INSERT INTO work_item_transitions (tenant_id, type, lifecycle, lifecycle_version,"
                " from_status, action, to_status, reason_mode, reason_list)"
                " SELECT tenant_id, type, lifecycle, 2, from_status, action, to_status,"
                " reason_mode, reason_list FROM work_item_transitions"
                " WHERE type = 'incident' AND lifecycle = 'standard' AND lifecycle_version = 1"
                " AND NOT (from_status = 'new' AND action = 'start_work')"
            )
        )


async def test_versions_are_isolated_by_rls(world: World) -> None:
    a, b = world.a, world.b
    await world.create(a, a.admin)  # seeds tenant A's incident life cycle, version 1
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        mine = await session.execute(text("SELECT count(*) FROM work_item_lifecycle_versions"))
        assert mine.scalar_one() > 0
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        seen = await session.execute(
            text("SELECT count(*) FROM work_item_lifecycle_versions WHERE tenant_id = :a"),
            {"a": a.tenant},
        )
        assert seen.scalar_one() == 0
        changed = await session.execute(
            text("UPDATE work_item_lifecycle_versions SET state = 'retired' WHERE tenant_id = :a"),
            {"a": a.tenant},
        )
        assert changed.rowcount == 0


async def test_tenant_b_cannot_write_a_version_for_tenant_a(world: World) -> None:
    with pytest.raises(DBAPIError):
        async with world.app.state.db.tenant_session(TenantContext(world.b.tenant)) as session:
            await session.execute(
                text(
                    "INSERT INTO work_item_lifecycle_versions (tenant_id, type, lifecycle,"
                    " number, state) VALUES (:t, 'incident', 'theirs', 1, 'draft')"
                ),
                {"t": world.a.tenant},
            )


async def test_req_inc_049_ac3_a_record_keeps_its_version_after_a_newer_one_publishes(
    world: World,
) -> None:
    a = world.a
    before = await world.create(a, a.admin, subject=f"Before v2 {uuid.uuid4().hex[:6]}")
    assert states(await world.fresh(a, before))["start_work"] is None
    await _publish_version_2_without_start_work(world)

    after = await world.create(a, a.admin, subject=f"After v2 {uuid.uuid4().hex[:6]}")
    # The new record runs on version 2: no "start work" from new.
    assert states(await world.fresh(a, after))["start_work"] is not None
    moved = await world.act(a, a.admin, after, "start_work")
    assert moved.status_code == 409, moved.text
    # The one made before still runs on version 1, and its move still works.
    assert states(await world.fresh(a, before))["start_work"] is None
    started = await world.act(a, a.admin, before, "start_work")
    assert started.status_code == 200, started.text
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        kept = await session.execute(
            text("SELECT id::text, lifecycle_version FROM work_items WHERE id IN (:x, :y)"),
            {"x": uuid.UUID(before["id"]), "y": uuid.UUID(after["id"])},
        )
        assert dict(kept.tuples().all()) == {before["id"]: 1, after["id"]: 2}
