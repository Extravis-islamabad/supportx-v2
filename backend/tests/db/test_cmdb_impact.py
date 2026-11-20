"""The impact service over HTTP and through `impact_of` (WP-053 S3b; REQ-CMDB-010, 011, 030).

- REQ-CMDB-010's acceptance: a database two applications depend on, each used by one service,
  lists both at depth 2 with their paths; depth 1 drops the services; a cycle lists each CI once.
- Each relationship type's flow (part of: the part breaks the whole), and a type that carries no
  impact is never followed.
- A path through a CI the reader can't see is still found, and that CI is a bare placeholder; a
  start they can't see is a 404 (the tab) or a placeholder never walked from (`impact_of`).
- Lane A's contract: `down|up`, at most 50 CIs, `missing`, affected users "not configured".

Real PostgreSQL and Valkey on the incident world: every organisation is new (rule 5h).
"""

import uuid
from typing import Any

import httpx
import pytest

from app.core.errors import ValidationFailed
from app.core.tenancy import TenantContext
from app.modules.cmdb import impact_of
from app.modules.cmdb.service.impact import NOT_CONFIGURED
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_cmdb_relationships import _given, _link, _made
from tests.db.test_incidents_api import World, field_codes, problem

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the fixture, re-used


async def _impact(
    world: World,
    ci: dict[str, Any],
    user: uuid.UUID | None = None,
    **params: Any,  # noqa: ANN401 - query values
) -> httpx.Response:
    a = world.a
    return await world.call(
        "GET", f"/cmdb/cis/{ci['id']}/impact", a, user or a.admin, params=params
    )


def _keys(body: dict[str, Any]) -> set[str]:
    return {c["key"] for c in body["cis"]}


async def _linked(
    world: World, ci: dict[str, Any], code: str, targets: list[dict[str, Any]]
) -> None:
    made = await _link(world, world.a, ci, code, targets)
    assert made.status_code == 201, made.text


async def test_dependents_of_a_database_two_apps_two_services(world: World) -> None:
    a = world.a
    tag = uuid.uuid4().hex[:6]
    db = await _made(world, a, f"Orders db {tag}", "database")
    app1 = await _made(world, a, f"Shop {tag}", "application")
    app2 = await _made(world, a, f"Billing {tag}", "application")
    svc1 = await _made(world, a, f"Online shop {tag}", "business_service")
    svc2 = await _made(world, a, f"Invoicing {tag}", "business_service")
    await _linked(world, app1, "depends_on", [db])
    await _linked(world, app2, "depends_on", [db])
    await _linked(world, svc1, "depends_on", [app1])
    await _linked(world, svc2, "depends_on", [app2])

    two = await _impact(world, db, depth=2)
    assert two.status_code == 200, two.text
    body = two.json()
    assert body["start"]["key"] == db["id"]
    assert _keys(body) == {app1["id"], app2["id"], svc1["id"], svc2["id"]}
    by_key = {c["key"]: c for c in body["cis"]}
    assert (by_key[svc1["id"]]["depth"], by_key[svc1["id"]]["via"]) == (2, app1["id"])
    assert (by_key[app2["id"]]["depth"], by_key[app2["id"]]["via"]) == (1, db["id"])
    assert {s["id"] for s in body["services"]} == {svc1["id"], svc2["id"]}
    assert body["affected_users"] is None
    assert body["affected_users_reason"] == NOT_CONFIGURED
    assert (body["restricted"], body["truncated"]) == (0, False)

    one = await _impact(world, db, depth=1)
    assert _keys(one.json()) == {app1["id"], app2["id"]}  # depth 1 drops the services
    assert one.json()["services"] == []

    up = await _impact(world, svc1, depth=3, direction="dependencies")
    assert _keys(up.json()) == {app1["id"], db["id"]}  # what the service relies on


async def test_a_cycle_lists_each_ci_once(world: World) -> None:
    a = world.a
    x = await _made(world, a, "Cycle x", "application")
    y = await _made(world, a, "Cycle y", "application")
    z = await _made(world, a, "Cycle z", "application")
    await _linked(world, x, "depends_on", [y])
    await _linked(world, y, "depends_on", [z])
    await _linked(world, z, "depends_on", [x])
    found = await _impact(world, x, depth=10)
    assert found.status_code == 200, found.text
    keys = [c["key"] for c in found.json()["cis"]]
    assert sorted(keys) == sorted([y["id"], z["id"]])  # once each; the start is not re-listed


async def test_each_type_flows_its_own_way_and_backups_carry_none(world: World) -> None:
    a = world.a
    disk = await _made(world, a, "Disk")
    server = await _made(world, a, "Server whole")
    backup = await _made(world, a, "Backup box")
    await _linked(world, disk, "part_of", [server])
    await _linked(world, server, "backed_up_by", [backup])
    # The part breaks the whole: a failing disk reaches the server, not the other way.
    assert _keys((await _impact(world, disk)).json()) == {server["id"]}
    assert _keys((await _impact(world, server)).json()) == set()
    # backed_up_by carries no impact: the backup box is never reached, either way.
    both = await _impact(world, backup, direction="both")
    assert _keys(both.json()) == set()
    assert server["id"] not in both.text
    server_both = await _impact(world, server, direction="both")
    assert _keys(server_both.json()) == {disk["id"]}  # the part, by the reverse step; no backup


async def test_a_path_through_an_unseen_ci_is_found_and_redacted(world: World) -> None:
    """REQ-CMDB-030: the walk goes through a CI the reader can't see; that CI is a placeholder."""
    a = world.a
    # requester2 is a member of site S2 (the incident world), so S2 is the site they see.
    host = await _made(world, a, "Shared host", site_id=str(a.s2))
    hidden = await _made(world, a, "Secret middle db", "database", site_id=str(a.s1))
    front = await _made(world, a, "Front app", "application", site_id=str(a.s2))
    await _linked(world, hidden, "runs_on", [host])
    await _linked(world, front, "depends_on", [hidden])
    await _given(world, a, a.requester2, "Site two impact viewer", [("cmdb.view", "site")])

    found = await _impact(world, host, a.requester2, depth=3)
    assert found.status_code == 200, found.text
    body = found.json()
    placeholders = [c for c in body["cis"] if c["restricted"]]
    assert len(placeholders) == 1
    (placeholder,) = placeholders
    assert placeholder["key"].startswith("r")
    for name in ("id", "display_id", "name", "type_id", "type_label_key", "state_category"):
        assert placeholder[name] is None, name
    assert placeholder["type_names"] == {}
    assert hidden["id"] not in found.text
    assert "Secret" not in found.text
    seen = {c["key"]: c for c in body["cis"] if not c["restricted"]}
    assert seen[front["id"]]["via"] == placeholder["key"]  # the path goes through it
    assert seen[front["id"]]["depth"] == 2
    assert body["restricted"] == 1

    direct = await _impact(world, hidden, a.requester2)
    assert problem(direct) == (404, "cmdb_ci_not_found")


async def test_impact_of_keeps_lane_a_contract(world: World) -> None:
    a = world.a
    db = await _made(world, a, "Contract db", "database", site_id=str(a.s1))
    app = await _made(world, a, "Contract app", "application", site_id=str(a.s2))
    await _linked(world, app, "depends_on", [db])
    await _given(world, a, a.requester2, "Site two contract viewer", [("cmdb.view", "site")])
    admin = await world.app.state.policy.subject(a.tenant, a.admin)
    narrowed = await world.app.state.policy.subject(a.tenant, a.requester2)
    unknown = uuid.uuid4()
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        down = await impact_of(session, admin, [uuid.UUID(db["id"]), unknown], direction="down")
        assert [c.id for c in down.cis] == [uuid.UUID(app["id"])]
        assert down.missing == 1
        assert down.affected_users is None
        assert down.affected_users_reason == NOT_CONFIGURED
        up = await impact_of(session, admin, [uuid.UUID(app["id"])], direction="up")
        assert [c.id for c in up.cis] == [uuid.UUID(db["id"])]
        # A start the reader can't see: a placeholder, never walked from.
        hidden = await impact_of(session, narrowed, [uuid.UUID(db["id"])], direction="down")
        assert [s.restricted for s in hidden.starts] == [True]
        assert hidden.starts[0].id is None
        assert hidden.cis == []
        too_many = [uuid.uuid4() for _ in range(51)]
        with pytest.raises(ValidationFailed) as refused:
            await impact_of(session, admin, too_many)
        assert "too_many" in repr(refused.value.errors)


async def test_an_unknown_direction_is_a_field_problem(world: World) -> None:
    a = world.a
    ci = await _made(world, a, "Direction check", "application")
    bad = await _impact(world, ci, direction="sideways")
    assert "direction" in str(field_codes(bad))
