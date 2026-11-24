"""CIs on work items and the downtime event for the CMDB (WP-053 S5, lane A; REQ-CMDB-019, -020).

Real PostgreSQL with RLS on the incident world. Lane B's shapes (2026-11-24): `work_item_cis`
with `at_creation`; `work_items.ci_link.changed` and `work_items.downtime.changed`, IDs and
codes only; create with `ci_ids` even when the form shows no CI field (REQ-SR-019 AC1); an
incident records the actual downtime it caused (the coordinator's OK: the incident's edit right,
`can_link` per CI, history, refused once closed); the merge port moves links.
"""

import json
import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.tenancy import TenantContext
from app.modules.cmdb import Count
from app.modules.cmdb.service.links import ci_links_port
from app.modules.identity_access import subject_for
from app.modules.work_items.service.ci_links import COUNTS_PORT
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_changes_api import CHG, a_change
from tests.db.test_cmdb_api import _ci
from tests.db.test_incidents_api import CONSOLE, Org, World, problem, role
from tests.db.test_users_api import seed_users

pytestmark = [pytest.mark.db, MODULE_LOOP]
__all__ = ["module_world", "shared_world"]  # the fixtures, re-used

INC = "/incidents"


async def _a_ci(world: World, org: Org, name: str, **extra: Any) -> dict[str, Any]:  # noqa: ANN401
    made = await _ci(world, org, name, **extra)
    assert made.status_code == 201, made.text
    return dict(made.json())


async def _events(world: World, event_type: str, record_id: str) -> list[dict[str, Any]]:
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE event_type = $1 ORDER BY id", event_type
    )
    return [
        p for r in rows if (p := json.loads(r["envelope"])["payload"])["work_item_id"] == record_id
    ]


async def _link(world: World, org: Org, user: uuid.UUID, path: str, ci_ids: list[str]) -> Any:  # noqa: ANN401 - the response
    return await world.call(
        "POST",
        f"{path}/cis",
        org,
        user,
        json={"ci_ids": ci_ids},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )


async def test_link_list_and_unlink_a_ci_with_ids_only_events(world: World) -> None:
    a = world.a
    ci = await _a_ci(world, a, "Core switch")
    item = await world.create(a, a.admin)
    path = f"{INC}/{item['id']}"
    linked = await _link(world, a, a.admin, path, [ci["id"]])
    assert linked.status_code == 201, linked.text
    [row] = linked.json()["items"]
    assert (row["ci_id"], row["name"], row["hidden"], row["at_creation"]) == (
        ci["id"],
        "Core switch",
        False,
        False,
    )
    again = await _link(world, a, a.admin, path, [ci["id"]])
    assert len(again.json()["items"]) == 1  # already linked: left as it is
    gone = await world.call(
        "DELETE",
        f"{path}/cis/{row['id']}",
        a,
        a.admin,
        headers={"If-Match": f'"{row["version"]}"', **CONSOLE},
    )
    assert gone.status_code == 204, gone.text
    assert (await world.call("GET", f"{path}/cis", a, a.admin)).json()["items"] == []
    changes = await _events(world, "work_items.ci_link.changed", item["id"])
    assert [(c["change"], c["type"], c["ci_id"]) for c in changes] == [
        ("added", "incident", ci["id"]),
        ("removed", "incident", ci["id"]),
    ]
    assert all("Core switch" not in json.dumps(c) for c in changes)  # IDs only
    stored = await world.sql(
        "SELECT new_value, old_value FROM field_changes WHERE tenant_id = $1 AND record_id = $2"
        " AND field = 'ci'",
        a.tenant,
        uuid.UUID(item["id"]),
    )
    assert all("Core switch" not in json.dumps(dict(r)) for r in stored)  # never the name


async def test_create_with_ci_ids_links_them_at_creation(world: World) -> None:
    """REQ-SR-019 AC1: the CI is attached though the incident form shows no CI field."""
    a = world.a
    ci = await _a_ci(world, a, "Mail server")
    item = await world.create(a, a.admin, ci_ids=[ci["id"]])
    [row] = (await world.call("GET", f"{INC}/{item['id']}/cis", a, a.admin)).json()["items"]
    assert (row["ci_id"], row["at_creation"]) == (ci["id"], True)
    [event] = await _events(world, "work_items.ci_link.changed", item["id"])
    assert event["at_creation"] is True


async def test_a_ci_one_may_not_see_is_refused_and_never_named(world: World) -> None:
    a = world.a
    ci = await _a_ci(world, a, "Payroll database")
    [narrow] = await seed_users(world.db, a.tenant, [{"user_type": "technician"}])
    inc_role = await role(
        world, a, "Incidents without CMDB", [("incidents.view", "all"), ("incidents.edit", "all")]
    )
    assert (
        await world.call("PUT", f"/users/{narrow}/roles/{inc_role}", a, a.admin)
    ).status_code == 204
    item = await world.create(a, a.admin)
    path = f"{INC}/{item['id']}"
    refused = await _link(world, a, narrow, path, [ci["id"]])
    assert problem(refused)[0] == 422
    assert (await _link(world, a, a.admin, path, [ci["id"]])).status_code == 201
    [seen] = (await world.call("GET", f"{path}/cis", a, narrow)).json()["items"]
    assert (seen["hidden"], seen["name"], seen["display_id"]) == (True, None, None)
    history = await world.call("GET", f"{path}/history", a, narrow)
    assert history.status_code == 200, history.text
    assert "Payroll database" not in history.text
    admin_history = await world.call("GET", f"{path}/history", a, a.admin)
    assert "Payroll database" in admin_history.text  # named for someone who may see it


async def test_an_incident_records_the_actual_downtime_it_caused(world: World) -> None:
    """REQ-CMDB-020 AC3 and the event's shape (lane B): one row, IDs and UTC times only."""
    a = world.a
    ci = await _a_ci(world, a, "Edge router")
    item = await world.create(a, a.admin)
    path = f"{INC}/{item['id']}/downtimes"
    planned = await world.call(
        "POST",
        path,
        a,
        a.admin,
        json={
            "phase": "planned",
            "starts_at": "2026-11-24T09:00:00Z",
            "ends_at": "2026-11-24T10:00:00Z",
        },
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert problem(planned)[0] == 422
    made = await world.call(
        "POST",
        path,
        a,
        a.admin,
        json={
            "starts_at": "2026-11-24T09:00:00Z",
            "ends_at": "2026-11-24T09:40:00Z",
            "kind": "full_outage",
            "description": "Fibre cut at the exchange",
            "ci_ids": [ci["id"]],
        },
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert made.status_code == 201, made.text
    assert made.json()["phase"] == "actual"
    [event] = await _events(world, "work_items.downtime.changed", item["id"])
    assert (event["phase"], event["kind"], event["ci_ids"], event["deleted"]) == (
        "actual",
        "full_outage",
        [ci["id"]],
        False,
    )
    assert event["source_work_item_id"] == item["id"]
    assert "Fibre" not in json.dumps(event)  # no free text
    await world.sql(
        "UPDATE work_items SET status_category = 'closed', status = 'closed'"
        " WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(item["id"]),
    )
    closed = await world.call(
        "POST",
        path,
        a,
        a.admin,
        json={"starts_at": "2026-11-24T11:00:00Z", "ends_at": "2026-11-24T11:10:00Z"},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert problem(closed) == (409, "record_closed")


async def test_a_changes_planned_downtime_and_its_removal_send_the_event(world: World) -> None:
    a = world.a
    change = await a_change(world, a)
    path = f"{CHG}/{change['id']}/downtimes"
    made = await world.call(
        "POST",
        path,
        a,
        a.admin,
        json={"starts_at": "2026-12-01T22:00:00Z", "ends_at": "2026-12-01T23:00:00Z"},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert made.status_code == 201, made.text
    row = made.json()
    removed = await world.call(
        "DELETE",
        f"{path}/{row['id']}",
        a,
        a.admin,
        headers={"If-Match": f'"{row["version"]}"', **CONSOLE},
    )
    assert removed.status_code == 204, removed.text
    events = await _events(world, "work_items.downtime.changed", change["id"])
    assert [(e["phase"], e["deleted"], e["source_work_item_id"]) for e in events] == [
        ("planned", False, None),
        ("planned", True, None),
    ]


async def test_a_cmdb_merge_moves_the_links_and_keeps_one(world: World) -> None:
    """cmdb/service/links.py contract, through the registered port."""
    a = world.a
    old, new = await _a_ci(world, a, "Old host"), await _a_ci(world, a, "New host")
    both = await world.create(a, a.admin, ci_ids=[old["id"], new["id"]])
    only_old = await world.create(a, a.admin, ci_ids=[old["id"]])
    port = ci_links_port()
    assert port is not None  # work_items registered it at import
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert await port(session, uuid.UUID(old["id"]), uuid.UUID(old["id"])) == 0
        touched = await port(session, uuid.UUID(old["id"]), uuid.UUID(new["id"]))
    assert touched == 2
    for item in (both, only_old):
        listed = (await world.call("GET", f"{INC}/{item['id']}/cis", a, a.admin)).json()
        assert [r["ci_id"] for r in listed["items"]] == [new["id"]]


async def test_ci_links_are_isolated_by_rls(world: World) -> None:
    a, b = world.a, world.b
    ci = await _a_ci(world, a, "Tenant A host")
    item = await world.create(a, a.admin, ci_ids=[ci["id"]])
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        seen = await session.scalar(
            text("SELECT count(*) FROM work_item_cis WHERE tenant_id = :a"), {"a": a.tenant}
        )
        assert seen == 0
    with pytest.raises(DBAPIError):
        async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
            await session.execute(
                text(
                    "INSERT INTO work_item_cis (id, tenant_id, work_item_id, ci_id)"
                    " VALUES (:i, :t, :w, :c)"
                ),
                {"i": uuid.uuid4(), "t": a.tenant, "w": item["id"], "c": ci["id"]},
            )


async def test_more_than_the_cap_is_refused(world: World) -> None:
    """At most 50 CIs on one create (the body's own limit, a labelled validation problem)."""
    a = world.a
    made = await world.call(
        "POST",
        INC,
        a,
        a.admin,
        json={
            "subject": "Too many",
            "requester_id": str(a.requester),
            "ci_ids": [str(uuid.uuid4()) for _ in range(51)],
        },
        headers=CONSOLE,
    )
    assert made.status_code == 422


async def test_the_counts_port_counts_open_and_total_per_type_through_each_view(
    world: World,
) -> None:
    """Lane B's widened OpenCountsPort (#605): {ci: {type: Count(open, total)}}, visible only."""
    a = world.a
    ci = await _a_ci(world, a, "Counted host")
    await world.create(a, a.admin, ci_ids=[ci["id"]])  # open
    closed_one = await world.create(a, a.admin, ci_ids=[ci["id"]])
    await world.sql(
        "UPDATE work_items SET status_category = 'closed', status = 'closed'"
        " WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(closed_one["id"]),
    )
    [narrow] = await seed_users(world.db, a.tenant, [{"user_type": "technician"}])
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        admin = await subject_for(session, a.tenant, a.admin)
        nobody = await subject_for(session, a.tenant, narrow)
        seen = await COUNTS_PORT.linked_counts(session, admin, [uuid.UUID(ci["id"])])
        hidden = await COUNTS_PORT.linked_counts(session, nobody, [uuid.UUID(ci["id"])])
    assert seen[uuid.UUID(ci["id"])]["incident"] == Count(open=1, total=2)
    assert "service_request" not in seen[uuid.UUID(ci["id"])]  # nothing linked: left out
    assert hidden == {}  # no incidents view: no count includes a record they may not see
