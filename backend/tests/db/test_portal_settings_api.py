"""The portal's own settings (WP-032 D8, D-143; REQ-PRT-031, -003). Real Postgres.

The defaults before any change (a GET never writes); a change needs the service desk
configuration right and If-Match, is audited with old and new value, is published for open
portals, and stays in its tenant (RLS).
"""

from sqlalchemy import text

from app.core.tenancy import TenantContext
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import World, field_codes, problem

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

SETTINGS = "/portal/settings"


async def test_defaults_then_an_audited_change_that_stays_in_its_tenant(world: World) -> None:
    a, b = world.a, world.b
    first = await world.call("GET", SETTINGS, a, a.requester)
    assert first.status_code == 200, first.text
    assert first.json() == {
        "search_sources": ["items", "articles", "announcements", "requests"],
        "profile_editing": True,
        "requester_reminders": True,
        "version": 1,
    }
    stored = await world.sql(
        "SELECT count(*) AS n FROM work_item_portal_settings WHERE tenant_id = $1", a.tenant
    )
    assert stored[0]["n"] == 0  # reading never writes
    refused = await world.call(
        "PATCH",
        SETTINGS,
        a,
        a.requester,
        json={"profile_editing": False},
        headers={"If-Match": '"1"'},
    )
    assert problem(refused)[0] == 403
    wrong = await world.call(
        "PATCH",
        SETTINGS,
        a,
        a.admin,
        json={"search_sources": ["requests", "requests"]},
        headers={"If-Match": '"1"'},
    )
    assert field_codes(wrong) == {"search_sources": "invalid_choice"}
    changed = await world.call(
        "PATCH",
        SETTINGS,
        a,
        a.admin,
        json={"search_sources": ["requests", "items"], "profile_editing": False},
        headers={"If-Match": '"1"'},
    )
    assert changed.status_code == 200, changed.text
    assert (changed.json()["search_sources"], changed.json()["version"]) == (
        ["requests", "items"],
        2,
    )
    stale = await world.call(
        "PATCH",
        SETTINGS,
        a,
        a.admin,
        json={"requester_reminders": False},
        headers={"If-Match": '"1"'},
    )
    assert problem(stale) == (409, "version_conflict")
    audit = await world.sql(
        "SELECT details FROM audit_entries WHERE tenant_id = $1"
        " AND action = 'portal.settings_changed' AND outcome = 'done'",
        a.tenant,
    )
    assert len(audit) == 1
    details = audit[0]["details"]
    assert '"profile_editing": true' in details
    assert '"profile_editing": false' in details
    events = await world.sql(
        "SELECT count(*) AS n FROM outbox_events"
        " WHERE envelope->>'event_type' = 'work_items.portal_settings.changed'"
        " AND envelope->>'tenant_id' = $1",
        str(a.tenant),
    )
    assert events[0]["n"] == 1
    # Tenant B keeps its own defaults, and cannot read or change A's row.
    assert (await world.call("GET", SETTINGS, b, b.admin)).json()["version"] == 1
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        rows = (
            await session.execute(text("SELECT tenant_id FROM work_item_portal_settings"))
        ).all()
        assert rows == []
        moved = await session.execute(
            text("UPDATE work_item_portal_settings SET profile_editing = true")
        )
        assert moved.rowcount == 0
