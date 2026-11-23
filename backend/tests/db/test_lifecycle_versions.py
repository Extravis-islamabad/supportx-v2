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
                " state) VALUES (:t, 'incident', 'standard', 2, 'draft')"
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
        await session.execute(
            text(
                "UPDATE work_item_lifecycle_versions SET state = 'published', published_at = now()"
                " WHERE type = 'incident' AND lifecycle = 'standard' AND number = 2"
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


async def _sql_as_app(world: World, statement: str) -> None:
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        await session.execute(text(statement))


@pytest.mark.parametrize(
    "statement",
    [
        # A published version's move cannot be removed, retargeted or given a new right.
        "DELETE FROM work_item_transitions WHERE type = 'incident' AND lifecycle_version = 1",
        (
            "UPDATE work_item_transitions SET to_status = 'closed'"
            " WHERE type = 'incident' AND lifecycle_version = 1 AND action = 'resolve'"
        ),
        (
            "UPDATE work_item_transitions SET permission = 'incidents.delete'"
            " WHERE type = 'incident' AND lifecycle_version = 1"
        ),
        # Nor can a move be added to it.
        (
            "INSERT INTO work_item_transitions (tenant_id, type, lifecycle, lifecycle_version,"
            " from_status, action, to_status, reason_mode)"
            " SELECT tenant_id, type, lifecycle, 1, 'closed', 'reopen', 'in_progress', 'none'"
            " FROM work_item_lifecycle_versions WHERE type = 'incident' AND number = 1"
            " ON CONFLICT DO NOTHING"
        ),
        # A version goes draft -> published -> retired only, and only a draft is removed.
        (
            "UPDATE work_item_lifecycle_versions SET state = 'draft'"
            " WHERE type = 'incident' AND number = 1"
        ),
        "DELETE FROM work_item_lifecycle_versions WHERE type = 'incident' AND number = 1",
    ],
)
async def test_lane_b_a_published_version_cannot_be_changed_by_the_app_role(
    world: World, statement: str
) -> None:
    """Enforced by the database, not only the service (lane B's #454 review)."""
    await world.create(world.a, world.a.admin)  # seeds tenant A's version 1, published
    with pytest.raises(DBAPIError, match=r"never change|draft"):
        await _sql_as_app(world, statement)


async def test_the_reason_prompt_stays_a_version_wide_setting(world: World) -> None:
    """Amendment 1: on a published version only the reason prompt may change."""
    await world.create(world.a, world.a.admin)
    await _sql_as_app(
        world,
        "UPDATE work_item_transitions SET reason_mode = 'optional'"
        " WHERE type = 'incident' AND lifecycle_version = 1 AND action = 'resolve'",
    )
