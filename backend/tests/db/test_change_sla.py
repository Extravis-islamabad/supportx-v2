"""Change SLAs (WP-045d S3, REQ-CHG-107 AC2): the shared SLA engine on changes.

Appendix A sets no change SLA, so a change has none until an admin gives a policy targets; then
its clocks, escalations, pauses, the trash rule (#368) and the safety net work as for incidents.
"""

import uuid
from datetime import timedelta
from typing import Any

import pytest

from app.core.tenancy import TenantContext
from app.modules import sla
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_changes_api import CHG, a_change
from tests.db.test_incidents_api import CONSOLE, Org, World

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

POLICIES = "/sla/record-types/change/policies"


async def _targets(world: World, item: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = await world.sql(
        "SELECT * FROM sla_targets WHERE record_id = $1 ORDER BY kind, round",
        uuid.UUID(item["id"]),
    )
    return {f"{r['kind']}:{r['round']}": dict(r) for r in rows}


async def _fire(world: World, org: Org, item: dict[str, Any], at: Any) -> list[str]:  # noqa: ANN401 - a datetime
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        result = await sla.fire(session, uuid.UUID(item["id"]), now=at)
    return [f"{f.what}:{f.kind}:{f.position or ''}" for f in result.fired]


async def _give_targets(world: World, org: Org) -> None:
    (fallback,) = (await world.call("GET", POLICIES, org, org.admin)).json()
    assert fallback["targets"] == []  # never seeded: no change SLA until an admin sets one
    saved = await world.call(
        "PATCH",
        f"/sla/policies/{fallback['id']}",
        org,
        org.admin,
        json={
            "targets": [
                {"kind": "resolution", "priority": None, "amount": 8, "unit": "hours"},
            ],
            "levels": [
                {"kind": "resolution", "offset_seconds": 0, "recipients": [{"kind": "assignee"}]}
            ],
        },
        headers={"If-Match": f'"{fallback["version"]}"', **CONSOLE},
    )
    assert saved.status_code == 200, saved.text


async def test_req_chg_107_ac2_a_change_sla_escalates_at_its_time_and_says_so(
    world: World,
) -> None:
    b = world.b  # its own tenant: no other test gives B's change policy targets
    before = await a_change(world, b)
    assert await _targets(world, before) == {}  # no targets anywhere: no clock
    await _give_targets(world, b)
    item = await a_change(world, b)
    target = (await _targets(world, item))["resolution:1"]
    due = target["due_at"]
    # Business hours: measured from the target's own moments, never a wall-clock guess.
    before_any = (target["warning_at"] or due) - timedelta(minutes=1)
    # The safety net finds a late change, as it does any other record.
    from app.modules.sla.service.timers import overdue_records  # noqa: PLC0415 - the net

    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        assert uuid.UUID(item["id"]) not in await overdue_records(session, before_any)
        assert uuid.UUID(item["id"]) in await overdue_records(session, due + timedelta(seconds=1))
    early = await _fire(world, b, item, before_any)
    assert not [f for f in early if f.startswith("escalated")]  # the warning only, at 75 %
    fired = await _fire(world, b, item, due + timedelta(seconds=5))
    assert "escalated:resolution:1" in fired
    history = (await world.call("GET", f"{CHG}/{item['id']}/history", b, b.admin)).json()["items"]
    escalated = [c for h in history for c in h["changes"] if c["field"] == "sla_escalation"]
    assert [c["new"] for c in escalated] == ["resolution:1"]
    shown = (await world.call("GET", f"{CHG}/{item['id']}", b, b.admin)).json()
    assert shown["resolution_due_at"] is not None  # the change shows its due time


async def test_req_chg_107_a_trashed_change_s_sla_waits(world: World) -> None:
    """The trash rule (#368): nothing fires while a change is in the trash."""
    b = world.b
    item = await a_change(world, b)
    targets = await _targets(world, item)
    if not targets:  # this test may run before the one that sets B's targets
        await _give_targets(world, b)
        item = await a_change(world, b)
        targets = await _targets(world, item)
    due = targets["resolution:1"]["due_at"]
    trashed = await world.call(
        "DELETE",
        f"{CHG}/{item['id']}",
        b,
        b.admin,
        headers={"If-Match": f'"{item["version"]}"', **CONSOLE},
    )
    assert trashed.status_code in {200, 204}, trashed.text
    assert await _fire(world, b, item, due + timedelta(minutes=1)) == []
