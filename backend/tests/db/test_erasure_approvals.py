"""An erasure never grants an approval (the coordinator's decision, 2026-11-14; ADR-052).

The erased approver's pending approval goes to the approval administrators with the reason
"approver erased" and stays pending: the record waits for a person's decision, never moves on
because someone was erased.
"""

from datetime import UTC, datetime

from app.core.tenancy import TenantContext
from app.modules.work_items.service.person_data import REFERENCES
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_approvals_api import approvals, manager_of, waiting
from tests.db.test_incidents_api import World

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixture, re-used


async def test_an_erased_approver_s_approval_goes_to_the_administrators_still_pending(
    world: World,
) -> None:
    a = world.a
    await manager_of(world, a.requester, a.tech_a)
    record = await waiting(world, a)
    cursor: str | None = None
    for _ in range(20):
        async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
            batch = await REFERENCES.erase_person(
                session,
                a.tech_a,
                successor_id=a.admin,
                keep_files={},
                now=datetime.now(UTC),
                cursor=cursor,
            )
        cursor = batch.cursor
        if cursor is None:
            break
    [entry] = await approvals(world, a, a.admin, record)
    assert (entry["origin"], entry["route_reason"]) == ("administrators", "approver_erased")
    assert entry["state"] == "pending"  # never granted by the erasure
    (row,) = await world.sql(
        "SELECT approval_status FROM work_items WHERE tenant_id = $1 AND id = $2::uuid",
        a.tenant,
        record["id"],
    )
    assert row["approval_status"] != "approved"
