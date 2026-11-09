"""Designing, publishing and switching workflows (WP-048b S1; REQ-WF-010, -019, -021).

Real PostgreSQL and the real incident registration:
- a draft with problems saves with them, and cannot be published (REQ-WF-019 AC1);
- a clean draft publishes as version 1 and makes the run-as identity once;
- a second publish is version 2, and version 1 stays as it was (REQ-WF-021);
- enabling needs a published version; disabling deactivates the run-as identity (AC3).
"""

import copy
import uuid

import pytest

from app.core.errors import Conflict, ValidationFailed
from app.core.tenancy import TenantContext
from app.modules.automation.infra.models import Workflow, WorkflowVersion
from app.modules.automation.service import workflow_admin
from tests.db.test_incidents_api import World, world

__all__ = ["world"]  # the fixture, re-used


async def _create(world: World) -> uuid.UUID:
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        made = await workflow_admin.create_workflow(
            session,
            record_type="incident",
            name=f"Escalate {uuid.uuid4().hex[:6]}",
            description=None,
        )
        return made.id


async def _workflow(world: World, workflow_id: uuid.UUID) -> Workflow:
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        found = await session.get(Workflow, workflow_id)
        assert isinstance(found, Workflow)
        session.expunge(found)
        return found


async def test_req_wf_019_a_draft_with_problems_saves_but_does_not_publish(world: World) -> None:
    workflow_id = await _create(world)
    broken = copy.deepcopy(dict(workflow_admin.STARTER))
    broken["nodes"].append(
        {
            "id": "lost",
            "type": "note",
            "config": {"text": {"en": "x"}},
            "position": {"x": 0, "y": 0},
        }
    )
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        saved, problems = await workflow_admin.save_draft(
            session, workflow_id, expected_version=1, definition=broken
        )
        assert ("node:lost", "node_unreachable") in {(w, c) for w, c, _ in problems}
        assert saved.draft_problems == len(problems)
    with pytest.raises(ValidationFailed) as refused:
        async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
            await workflow_admin.publish(session, workflow_id, expected_version=2)
    assert refused.value.instance_code == "workflow_has_problems"


async def test_req_wf_021_publishing_makes_versions_and_the_run_as_identity_once(
    world: World,
) -> None:
    workflow_id = await _create(world)
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        first = await workflow_admin.publish(session, workflow_id, expected_version=1)
        assert first.number == 1
    identity = (await _workflow(world, workflow_id)).service_identity_id
    assert identity is not None
    names = await world.sql("SELECT display_name, user_type FROM users WHERE id = $1", identity)
    assert (names[0]["display_name"].startswith("Workflow: "), names[0]["user_type"]) == (
        True,
        "service",
    )
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        second = await workflow_admin.publish(session, workflow_id, expected_version=2)
        assert second.number == 2
    again = await _workflow(world, workflow_id)
    assert again.service_identity_id == identity  # made once
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        kept = await session.get(WorkflowVersion, (world.a.tenant, workflow_id, 1))
        assert kept is not None
        assert kept.definition == dict(workflow_admin.STARTER)


async def test_req_wf_010_ac3_enable_needs_a_version_and_disable_deactivates_the_identity(
    world: World,
) -> None:
    workflow_id = await _create(world)
    with pytest.raises(Conflict) as refused:
        async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
            await workflow_admin.set_enabled(session, workflow_id, expected_version=1, enabled=True)
    assert refused.value.instance_code == "workflow_not_published"
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        await workflow_admin.publish(session, workflow_id, expected_version=1)
        await workflow_admin.set_enabled(session, workflow_id, expected_version=2, enabled=True)
        await workflow_admin.set_enabled(session, workflow_id, expected_version=3, enabled=False)
    identity = (await _workflow(world, workflow_id)).service_identity_id
    status = await world.sql("SELECT status FROM users WHERE id = $1", identity)
    assert status[0]["status"] == "disabled"  # deactivated, never deleted
