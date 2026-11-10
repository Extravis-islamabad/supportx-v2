"""The tenant's approval settings: the chair of D-146 (WP-048b S2; migration 0106). Real Postgres.

No chair before any change (a GET never writes); setting one needs the service desk
configuration right and If-Match, refuses a deactivated person or a service identity, is
audited with the old and new chair, is published for open settings pages, can be cleared, and
stays in its tenant (RLS: tenant B can neither read nor change A's row).
"""

from sqlalchemy import text

from app.core.tenancy import TenantContext
from tests.db.test_incidents_api import World, field_codes, problem, world

__all__ = ["world"]  # the fixture, re-used

SETTINGS = "/approvals/settings"


async def test_d146_the_chair_is_set_audited_cleared_and_kept_in_its_tenant(world: World) -> None:
    a, b = world.a, world.b
    first = await world.call("GET", SETTINGS, a, a.tech_a)
    assert first.json() == {"chair_user_id": None, "version": 1}
    stored = await world.sql(
        "SELECT count(*) AS n FROM work_item_approval_settings WHERE tenant_id = $1", a.tenant
    )
    assert stored[0]["n"] == 0  # reading never writes
    refused = await world.call(
        "PATCH",
        SETTINGS,
        a,
        a.tech_a,
        json={"chair_user_id": str(a.tech_a)},
        headers={"If-Match": '"1"'},
    )
    assert problem(refused)[0] == 403
    await world.sql("UPDATE users SET status = 'disabled' WHERE id = $1", a.tech_b)
    inactive = await world.call(
        "PATCH",
        SETTINGS,
        a,
        a.admin,
        json={"chair_user_id": str(a.tech_b)},
        headers={"If-Match": '"1"'},
    )
    assert field_codes(inactive) == {"chair_user_id": "chair_inactive"}
    other_tenant = await world.call(
        "PATCH",
        SETTINGS,
        a,
        a.admin,
        json={"chair_user_id": str(b.admin)},
        headers={"If-Match": '"1"'},
    )
    assert field_codes(other_tenant) == {"chair_user_id": "chair_inactive"}  # not this tenant's
    chosen = await world.call(
        "PATCH",
        SETTINGS,
        a,
        a.admin,
        json={"chair_user_id": str(a.tech_a)},
        headers={"If-Match": '"1"'},
    )
    assert chosen.status_code == 200, chosen.text
    assert chosen.json() == {"chair_user_id": str(a.tech_a), "version": 2}
    stale = await world.call(
        "PATCH", SETTINGS, a, a.admin, json={"chair_user_id": None}, headers={"If-Match": '"1"'}
    )
    assert problem(stale) == (409, "version_conflict")
    cleared = await world.call(
        "PATCH", SETTINGS, a, a.admin, json={"chair_user_id": None}, headers={"If-Match": '"2"'}
    )
    assert cleared.json() == {"chair_user_id": None, "version": 3}
    audit = await world.sql(
        "SELECT details FROM audit_entries WHERE tenant_id = $1"
        " AND action = 'approvals.settings_changed' AND outcome = 'done' ORDER BY occurred_at",
        a.tenant,
    )
    assert len(audit) == 2
    assert str(a.tech_a) in audit[0]["details"]
    events = await world.sql(
        "SELECT count(*) AS n FROM outbox_events"
        " WHERE envelope->>'event_type' = 'work_items.approval_settings.changed'"
        " AND envelope->>'tenant_id' = $1",
        str(a.tenant),
    )
    assert events[0]["n"] == 2
    assert (await world.call("GET", SETTINGS, b, b.admin)).json()["version"] == 1
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        rows = (
            await session.execute(text("SELECT tenant_id FROM work_item_approval_settings"))
        ).all()
        assert rows == []
        moved = await session.execute(
            text("UPDATE work_item_approval_settings SET chair_user_id = NULL")
        )
        assert moved.rowcount == 0
