"""A release's freeze override and conflict acks storage (WP-058b S2; REQ-REL-040, -041).

Real PostgreSQL with RLS, built to lane B's checklist for `releases.override_freeze`:
visible first (404), then the scope at override time (403 out_of_scope / no_permission);
a reason and live blocking freezes named by ID, stored per ID (a later freeze still holds);
SECURITY audit, refused attempts too, and a history line; a closed or canceled release refuses
(409 record_closed). The acks table is isolated by RLS.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.tenancy import TenantContext
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_change_windows_api import a_window
from tests.db.test_incidents_api import CONSOLE, Org, World, problem, role
from tests.db.test_releases_api import REL, new_release

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

LATER = datetime(2027, 6, 7, 0, 0, tzinfo=UTC)


async def _group_release(world: World, org: Org) -> dict[str, Any]:
    made = await new_release(world, org, org.admin, group_id=str(org.ga))
    assert made.status_code == 201, made.text
    return dict(made.json())


async def _freeze(world: World, org: Org, days: int) -> dict[str, Any]:
    return await a_window(
        world,
        org,
        name=f"Freeze {days}",
        starts_at=(LATER + timedelta(days=days)).isoformat(),
        ends_at=(LATER + timedelta(days=days + 2)).isoformat(),
    )


async def _override(
    world: World, org: Org, user: uuid.UUID, release: dict[str, Any], body: dict[str, Any]
) -> httpx.Response:
    current = (await world.call("GET", f"{REL}/{release['id']}", org, org.admin)).json()
    return await world.call(
        "POST",
        f"{REL}/{release['id']}/freeze-override",
        org,
        user,
        json=body,
        headers={"If-Match": f'"{current["version"]}"', **CONSOLE},
    )


async def test_req_rel_040_ac2_the_override_is_scoped_reasoned_audited_and_in_history(
    world: World,
) -> None:
    a = world.a
    freeze = await _freeze(world, a, 0)
    release = await _group_release(world, a)
    group_override = await role(
        world, a, "Group release freeze", [("releases.override_freeze", "group")]
    )
    viewer = await role(world, a, "Release viewer", [("releases.view", "all")])
    for tech in (a.tech_a, a.tech_b):
        for given_role in (group_override, viewer):
            given = await world.call("PUT", f"/users/{tech}/roles/{given_role}", a, a.admin)
            assert given.status_code == 204, given.text
    ask = {"reason": "Vendor only works then", "window_ids": [freeze["id"]]}
    # Tech B holds it for group B only: sees the release, refused at its scope.
    other_group = await _override(world, a, a.tech_b, release, ask)
    assert problem(other_group) == (403, "permission_denied"), other_group.text
    assert other_group.json()["params"]["reason"] == "out_of_scope"
    # A plain technician never holds it.
    plain = await _override(world, a, a.tech_c, release, ask)
    assert problem(plain)[0] in {403, 404}, plain.text
    if plain.status_code == 403:
        assert plain.json()["params"]["reason"] == "no_permission"
    blank = await _override(world, a, a.tech_a, release, {**ask, "reason": "   "})
    assert problem(blank)[0] == 422, blank.text
    none = await _override(world, a, a.tech_a, release, {**ask, "window_ids": []})
    assert problem(none)[0] == 422, none.text
    made_up = await _override(
        world, a, a.tech_a, release, {**ask, "window_ids": [str(uuid.uuid4())]}
    )
    assert problem(made_up)[0] == 422, made_up.text
    assert "window_ids" in made_up.text
    warn = await a_window(
        world,
        a,
        kind="maintenance",
        name="Not a freeze",
        starts_at=LATER.isoformat(),
        ends_at=(LATER + timedelta(days=1)).isoformat(),
    )
    not_freeze = await _override(world, a, a.tech_a, release, {**ask, "window_ids": [warn["id"]]})
    assert problem(not_freeze)[0] == 422, not_freeze.text
    passed = await _override(world, a, a.tech_a, release, ask)
    assert passed.status_code == 200, passed.text
    stored = await world.sql(
        "SELECT freeze_override_window_ids, freeze_override_by, freeze_override_reason"
        " FROM work_item_release_details WHERE tenant_id = $1 AND work_item_id = $2",
        a.tenant,
        uuid.UUID(release["id"]),
    )
    assert [str(w) for w in stored[0]["freeze_override_window_ids"]] == [freeze["id"]]
    assert stored[0]["freeze_override_by"] == a.tech_a
    # A second freeze is passed beside the first, never instead of it (per ID, no early return).
    later = await _freeze(world, a, 10)
    again = await _override(world, a, a.tech_a, release, {**ask, "window_ids": [later["id"]]})
    assert again.status_code == 200, again.text
    stored = await world.sql(
        "SELECT freeze_override_window_ids FROM work_item_release_details"
        " WHERE tenant_id = $1 AND work_item_id = $2",
        a.tenant,
        uuid.UUID(release["id"]),
    )
    assert sorted(str(w) for w in stored[0]["freeze_override_window_ids"]) == sorted(
        [freeze["id"], later["id"]]
    )
    history = await world.call("GET", f"{REL}/{release['id']}/history", a, a.admin)
    fields = {c["field"] for e in history.json()["items"] for c in e["changes"]}
    assert {"freeze_override", "freeze_override_windows"} <= fields
    audit = await world.sql(
        "SELECT outcome, category FROM audit_entries WHERE tenant_id = $1"
        " AND action = 'release.freeze_override' AND object_id = $2",
        a.tenant,
        release["id"],
    )
    assert {r["outcome"] for r in audit} >= {"done", "refused"}
    assert {r["category"] for r in audit} == {"security"}


async def test_an_override_needs_to_see_the_release_first(world: World) -> None:
    """Visible first: a holder who cannot see the release gets 404, never a scope answer."""
    a = world.a
    freeze = await _freeze(world, a, 20)
    release = await _group_release(world, a)
    blind = await role(world, a, "Override, no view", [("releases.override_freeze", "all")])
    await world.sql("DELETE FROM user_roles WHERE user_id = $1", a.tech_c)
    given = await world.call("PUT", f"/users/{a.tech_c}/roles/{blind}", a, a.admin)
    assert given.status_code == 204, given.text
    refused = await _override(
        world, a, a.tech_c, release, {"reason": "x", "window_ids": [freeze["id"]]}
    )
    assert refused.status_code in {403, 404}, refused.text
    if refused.status_code == 403:  # the route's view permission answers before the service
        assert refused.json()["params"]["permission"] == "releases.view"


async def test_a_canceled_release_refuses_an_override(world: World) -> None:
    a = world.a
    freeze = await _freeze(world, a, 30)
    release = await _group_release(world, a)
    await world.sql(
        "UPDATE work_items SET status_category = 'canceled', status = 'closure_canceled',"
        " stage = 'closure', version = version + 1 WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(release["id"]),
    )
    refused = await _override(
        world, a, a.admin, release, {"reason": "Late", "window_ids": [freeze["id"]]}
    )
    assert problem(refused) == (409, "record_closed"), refused.text


async def test_conflict_acks_are_isolated_by_rls(world: World) -> None:
    a, b = world.a, world.b
    release = await _group_release(world, a)
    ack = uuid.uuid4()
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        await session.execute(
            text(
                "INSERT INTO work_item_conflict_acks"
                " (id, tenant_id, work_item_id, conflict_key, reason, acked_by, acked_at)"
                " VALUES (:id, :t, :w, 'release:x:1:1', 'Known', :u, now())"
            ),
            {"id": ack, "t": a.tenant, "w": release["id"], "u": a.admin},
        )
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        seen = await session.execute(
            text("SELECT id FROM work_item_conflict_acks WHERE id = :id"), {"id": ack}
        )
        assert seen.all() == []  # tenant B never sees tenant A's ack
        written = await session.execute(
            text("UPDATE work_item_conflict_acks SET reason = 'x' WHERE id = :id"), {"id": ack}
        )
        assert written.rowcount == 0
    # Nor can tenant B write a row for tenant A (the policy's WITH CHECK).
    with pytest.raises(DBAPIError, match="row-level security"):
        async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
            await session.execute(
                text(
                    "INSERT INTO work_item_conflict_acks"
                    " (id, tenant_id, work_item_id, conflict_key, reason, acked_by, acked_at)"
                    " VALUES (:id, :t, :w, 'k', 'r', :u, now())"
                ),
                {"id": uuid.uuid4(), "t": a.tenant, "w": release["id"], "u": a.admin},
            )
