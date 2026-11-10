"""The workflow tables are isolated per tenant (WP-048b S1, migration 0105; CLAUDE.md rule a).

Real PostgreSQL as the application role: tenant A's workflow, version, instance and step are
invisible to tenant B, which can neither change them nor write rows for tenant A. A record runs
at most one live instance of a workflow (REQ-WF-010), and published versions and steps are
insert-only for the application role.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.tenancy import TenantContext
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import World

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

TABLES = (
    "workflows",
    "workflow_versions",
    "workflow_instances",
    "workflow_steps",
    "workflow_jobs",  # WP-048b S3, migration 0107
)


async def _seed(world: World) -> dict[str, uuid.UUID]:
    """One workflow, its version 1, a running instance on a record and one step, in tenant A."""
    ids = {"workflow": uuid.uuid4(), "instance": uuid.uuid4(), "record": uuid.uuid4()}
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        await session.execute(
            text(
                "INSERT INTO workflows (id, tenant_id, record_type, name, draft) "
                "VALUES (:w, :t, 'incident', 'Major incident', '{}')"
            ),
            {"w": ids["workflow"], "t": world.a.tenant},
        )
        await session.execute(
            text(
                "INSERT INTO workflow_versions (tenant_id, workflow_id, number, definition) "
                "VALUES (:t, :w, 1, '{}')"
            ),
            {"w": ids["workflow"], "t": world.a.tenant},
        )
        await session.execute(
            text(
                "INSERT INTO workflow_instances (id, tenant_id, workflow_id, version_number, "
                "record_type, record_id, status, state, started_how, started_at) "
                "VALUES (:i, :t, :w, 1, 'incident', :r, 'running', '{}', 'manual', now())"
            ),
            {"i": ids["instance"], "t": world.a.tenant, "w": ids["workflow"], "r": ids["record"]},
        )
        await session.execute(
            text(
                "INSERT INTO workflow_steps (tenant_id, instance_id, seq, token, node, "
                "node_type, result, at) VALUES (:t, :i, 1, 't1', 'start', 'start', 'next', now())"
            ),
            {"i": ids["instance"], "t": world.a.tenant},
        )
        await session.execute(
            text(
                "INSERT INTO workflow_jobs (id, tenant_id, workflow_id, kind, instance_ids, "
                "status, total) VALUES (:j, :t, :w, 'retry', ARRAY[CAST(:i AS uuid)], 'queued', 1)"
            ),
            {"j": uuid.uuid4(), "t": world.a.tenant, "w": ids["workflow"], "i": ids["instance"]},
        )
    return ids


@pytest.mark.parametrize("table", TABLES)
async def test_workflow_tables_are_isolated_by_rls(world: World, table: str) -> None:
    a, b = world.a, world.b
    await _seed(world)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one() > 0  # noqa: S608 - fixed table names
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        seen = await session.execute(
            text(f"SELECT count(*) FROM {table} WHERE tenant_id = :a"),  # noqa: S608 - fixed table names
            {"a": a.tenant},
        )
        assert seen.scalar_one() == 0
    if table in {"workflows", "workflow_instances", "workflow_jobs"}:  # the others: insert-only
        async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
            changed = await session.execute(
                text(f"UPDATE {table} SET tenant_id = tenant_id WHERE tenant_id = :a"),  # noqa: S608 - fixed table names
                {"a": a.tenant},
            )
            assert changed.rowcount == 0


async def test_tenant_b_cannot_write_a_workflow_for_tenant_a(world: World) -> None:
    with pytest.raises(DBAPIError):
        async with world.app.state.db.tenant_session(TenantContext(world.b.tenant)) as session:
            await session.execute(
                text(
                    "INSERT INTO workflows (id, tenant_id, record_type, name, draft) "
                    "VALUES (:w, :t, 'incident', 'Theirs', '{}')"
                ),
                {"w": uuid.uuid4(), "t": world.a.tenant},
            )


async def test_req_wf_010_one_live_instance_per_record_and_workflow(world: World) -> None:
    ids = await _seed(world)
    with pytest.raises(IntegrityError):
        async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
            await session.execute(
                text(
                    "INSERT INTO workflow_instances (id, tenant_id, workflow_id, version_number, "
                    "record_type, record_id, status, state, started_how, started_at) "
                    "VALUES (:i, :t, :w, 1, 'incident', :r, 'waiting', '{}', 'trigger', now())"
                ),
                {
                    "i": uuid.uuid4(),
                    "t": world.a.tenant,
                    "w": ids["workflow"],
                    "r": ids["record"],
                },
            )


@pytest.mark.parametrize("table", ["workflow_versions", "workflow_steps"])
async def test_versions_and_steps_are_insert_only_for_the_app(world: World, table: str) -> None:
    await _seed(world)
    with pytest.raises(DBAPIError):
        async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
            await session.execute(text(f"UPDATE {table} SET tenant_id = tenant_id"))  # noqa: S608 - fixed table names


async def test_tenant_b_cannot_queue_a_job_on_tenant_a_s_workflow(world: World) -> None:
    """A job names a workflow of its own tenant: RLS refuses another tenant's row."""
    ids = await _seed(world)
    with pytest.raises(DBAPIError):
        async with world.app.state.db.tenant_session(TenantContext(world.b.tenant)) as session:
            await session.execute(
                text(
                    "INSERT INTO workflow_jobs (id, tenant_id, workflow_id, kind, instance_ids, "
                    "status, total) VALUES (:j, :t, :w, 'cancel', ARRAY[CAST(:i AS uuid)], "
                    "'queued', 1)"
                ),
                {
                    "j": uuid.uuid4(),
                    "t": world.a.tenant,
                    "w": ids["workflow"],
                    "i": ids["instance"],
                },
            )
