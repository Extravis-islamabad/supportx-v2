"""Service request fulfilment (WP-047a S5; REQ-SR-047..050, -056).

Real PostgreSQL with RLS. A plan step's condition, owner kind, fields and `waits_for`; task-only
access for an owner outside the desk (the coordinator's condition 1, with a negative test per
exclusion); conditional re-planning that never cancels work (condition 3); and the asset
hand-over port on lane B's terms (its six cases).
"""

import uuid
from decimal import Decimal
from typing import Any

from conftest import assign_system_role, create_tenant
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_approvals_api import fresh, manager_of
from tests.db.test_assets_api import _add as add_asset
from tests.db.test_assets_api import _product
from tests.db.test_catalog_api import add as add_item
from tests.db.test_conversation_api import events_of
from tests.db.test_fulfilment_api import tasks
from tests.db.test_incidents_api import CONSOLE, Org, World, problem
from tests.db.test_service_requests_api import SR, an_item, raise_request
from tests.db.test_users_api import seed_users

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

TASKS = "/portal/tasks"
REMOTE = {
    "key": "remote",
    "label": {"en": "Remote?"},
    "kind": "choice",
    "required": True,
    "options": ["yes", "no"],
}


def step(title: str, **extra: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    return {"title": {"en": title}, **extra}


async def request_for(
    world: World,
    org: Org,
    plan: list[dict[str, Any]],
    answers: dict[str, Any],
    **item: Any,  # noqa: ANN401 - the item's JSON
) -> dict[str, Any]:
    made_item = await an_item(
        world, org, questions=[REMOTE], plan=plan, technician_id=str(org.tech_a), **item
    )
    made = await raise_request(
        world,
        org,
        org.admin,
        catalog_item_id=made_item["id"],
        answers=answers,
        on_behalf_of_id=str(org.requester),
        group_id=str(org.ga),
    )
    assert made.status_code == 201, made.text
    return dict(made.json())


async def patch_task(
    world: World,
    org: Org,
    user: uuid.UUID,
    record: dict[str, Any],
    task: dict[str, Any],
    body: dict[str, Any],
) -> Any:  # noqa: ANN401 - httpx response
    return await world.call(
        "PATCH",
        f"{SR}/{record['id']}/tasks/{task['id']}",
        org,
        user,
        json=body,
        headers={"If-Match": f'"{task["version"]}"', **CONSOLE},
    )


async def test_conditions_waits_and_fields_shape_the_tasks(world: World) -> None:
    """REQ-SR-048 AC1, -047 AC1, -049 AC1."""
    a = world.a
    plan = [
        step("Order", key="order"),
        step(
            "VPN",
            key="vpn",
            condition={"field": "remote", "op": "eq", "value": "yes"},
            waits_for=["order"],
        ),
        step(
            "Deliver",
            key="deliver",
            waits_for=["order"],
            fields=[{"key": "serial", "label": {"en": "Serial"}, "kind": "text", "required": True}],
        ),
    ]
    record = await request_for(world, a, plan, {"remote": "no"})
    made = await tasks(world, a, record)
    assert [t["plan_key"] for t in made] == ["order", "deliver"]  # the VPN step's condition failed
    order, deliver = made
    assert deliver["depends_on"] == [order["id"]]
    refused = await patch_task(world, a, a.admin, record, order, {"status": "done"})
    assert refused.status_code == 200, refused.text
    deliver = (await tasks(world, a, record))[1]
    empty = await patch_task(world, a, a.admin, record, deliver, {"status": "done"})
    assert empty.status_code == 422, empty.text
    assert "task_field_required" in empty.text
    filled = await patch_task(
        world, a, a.admin, record, deliver, {"status": "done", "field_values": {"serial": "X1"}}
    )
    assert filled.status_code == 200, filled.text
    assert filled.json()["field_values"] == {"serial": "X1"}
    stray = await patch_task(
        world, a, a.admin, record, filled.json(), {"field_values": {"other": "x"}}
    )
    assert stray.status_code == 422
    assert "unknown_field" in stray.text


async def test_a_task_for_the_manager_is_task_only_and_ends_on_close(world: World) -> None:
    """REQ-SR-050; condition 1: that task alone, each exclusion refused; closing ends it."""
    a = world.a
    await manager_of(world, a.requester, a.requester2)  # a manager outside the desk
    plan = [
        step("Internal prep", key="prep"),
        step(
            "Manager sign-off",
            key="sign",
            owner_kind="requested_for_manager",
            fields=[{"key": "ok", "label": {"en": "OK"}, "kind": "text"}],
        ),
    ]
    record = await request_for(world, a, plan, {"remote": "no"})
    prep, sign = await tasks(world, a, record)
    assert (sign["owner_id"], sign["task_only"]) == (str(a.requester2), True)
    mine = await world.call("GET", TASKS, a, a.requester2)
    assert mine.status_code == 200, mine.text
    [listed] = mine.json()["items"]
    assert listed["id"] == sign["id"]
    assert listed["request_ref"] == record["display_id"]
    assert "answers" not in listed
    assert "subject" not in listed
    # Each exclusion: the record, its answers, its conversation, another task.
    for path in (
        f"{SR}/{record['id']}",
        f"{SR}/{record['id']}/conversation",
        f"{TASKS}/{prep['id']}",
    ):
        hidden = await world.call("GET", path, a, a.requester2, headers=CONSOLE)
        assert hidden.status_code in {403, 404}, (path, hidden.text)
    other = await patch_task(world, a, a.requester2, record, prep, {"status": "done"})
    assert other.status_code in {403, 404}, other.text
    renamed = await patch_task(world, a, a.requester2, record, sign, {"title": "Mine now"})
    assert renamed.status_code == 403, renamed.text
    done = await world.call(
        "PATCH",
        f"{TASKS}/{sign['id']}",
        a,
        a.requester2,
        json={"status": "done", "field_values": {"ok": "yes"}},
        headers={"If-Match": f'"{sign["version"]}"'},
    )
    assert done.status_code == 200, done.text
    gone = await world.call("GET", f"{TASKS}/{sign['id']}", a, a.requester2)
    assert gone.status_code == 404, gone.text  # closing it ended the access
    assert (await world.call("GET", TASKS, a, a.requester2)).json()["items"] == []


async def test_reassigning_a_task_only_task_ends_the_old_owner_s_access(world: World) -> None:
    """Condition 1: another owner, and the first one sees nothing of it any more."""
    a = world.a
    await manager_of(world, a.requester, a.requester2)
    plan = [step("Manager sign-off", key="sign", owner_kind="requested_for_manager")]
    record = await request_for(world, a, plan, {"remote": "no"})
    [sign] = await tasks(world, a, record)
    moved = await patch_task(world, a, a.admin, record, sign, {"owner_id": str(a.tech_b)})
    assert moved.status_code == 200, moved.text
    gone = await world.call("GET", f"{TASKS}/{sign['id']}", a, a.requester2)
    assert gone.status_code == 404, gone.text


async def test_changed_answers_add_and_drop_but_never_cancel_work(world: World) -> None:
    """REQ-SR-048 AC2; condition 3: a dropped task with values is kept and flagged."""
    a = world.a
    plan = [
        step(
            "VPN",
            key="vpn",
            condition={"field": "remote", "op": "eq", "value": "yes"},
            fields=[{"key": "user", "label": {"en": "User"}, "kind": "text"}],
        ),
        step("Desk", key="desk", condition={"field": "remote", "op": "eq", "value": "no"}),
    ]
    record = await request_for(world, a, plan, {"remote": "yes"})
    [vpn] = await tasks(world, a, record)
    noted = await patch_task(world, a, a.admin, record, vpn, {"field_values": {"user": "sam"}})
    assert noted.status_code == 200, noted.text

    async def answer(value: str) -> None:
        current = await fresh(world, a, record)
        changed = await world.call(
            "PATCH",
            f"{SR}/{record['id']}/answers",
            a,
            a.admin,
            json={"answers": {"remote": value}},
            headers={"If-Match": f'"{current["version"]}"', **CONSOLE},
        )
        assert changed.status_code == 200, changed.text

    await answer("no")
    by_key = {t["plan_key"]: t for t in await tasks(world, a, record)}
    assert by_key["desk"]["status"] == "open"  # added
    assert (by_key["vpn"]["status"], by_key["vpn"]["needs_review"]) == ("open", True)  # kept
    await answer("yes")
    by_key = {t["plan_key"]: t for t in await tasks(world, a, record)}
    assert by_key["desk"]["status"] == "canceled"  # no work on it: dropped


async def _handover_world(
    world: World, org: Org
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    product = await _product(world, org, "laptop", f"Hand-over laptop {uuid.uuid4().hex[:6]}")
    made = await add_asset(
        world, org, {"name": f"HO {uuid.uuid4().hex[:6]}", "product_id": product}
    )
    assert made.status_code == 201, made.text
    plan = [step("Hand over", key="give", kind="asset_handover", owner_id=str(org.tech_a))]
    record = await request_for(world, org, plan, {"remote": "no"})
    [give] = await tasks(world, org, record)
    return dict(made.json()), record, give


async def _hand(
    world: World,
    org: Org,
    user: uuid.UUID,
    record: dict[str, Any],
    give: dict[str, Any],
    asset: dict[str, Any],
) -> Any:  # noqa: ANN401 - httpx response
    return await patch_task(
        world, org, user, record, give, {"status": "done", "asset_id": asset["id"]}
    )


async def test_handover_assigns_links_and_audits(world: World) -> None:
    """Lane B's term 6a: the happy path in one transaction."""
    a = world.a
    asset, record, give = await _handover_world(world, a)
    handed = await _hand(world, a, a.admin, record, give, asset)
    assert handed.status_code == 200, handed.text
    [row] = await world.sql(
        "SELECT owner_user_id, version FROM assets WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(asset["id"]),
    )
    assert row["owner_user_id"] == a.requester
    assert row["version"] == asset["version"] + 1
    links = await world.sql(
        "SELECT 1 FROM work_item_assets WHERE tenant_id = $1 AND work_item_id = $2"
        " AND asset_id = $3 AND deleted_at IS NULL",
        a.tenant,
        uuid.UUID(record["id"]),
        uuid.UUID(asset["id"]),
    )
    assert len(links) == 1
    audit = await world.sql(
        "SELECT actor_id FROM audit_entries WHERE tenant_id = $1 AND action = 'asset.handed_over'"
        " AND object_id = $2",
        a.tenant,
        asset["id"],
    )
    assert [r["actor_id"] for r in audit] == [a.admin]
    history = await world.sql(
        "SELECT source, reason FROM field_changes WHERE tenant_id = $1 AND record_id = $2"
        " AND field = 'owner_user_id'",
        a.tenant,
        uuid.UUID(asset["id"]),
    )
    assert [(r["source"], r["reason"]) for r in history] == [("workflow", record["display_id"])]
    holdings = await world.sql(  # lane B: the hand-over starts a holding (none was current)
        "SELECT holder_id, ended_at FROM asset_assignments WHERE tenant_id = $1 AND asset_id = $2",
        a.tenant,
        uuid.UUID(asset["id"]),
    )
    assert [(r["holder_id"], r["ended_at"]) for r in holdings] == [(a.requester, None)]
    changed = [
        e
        for e in await events_of(world, "asset")
        if e.event_type == "assets.holder.changed" and e.payload.get("asset_id") == asset["id"]
    ]
    assert [e.payload["people"] for e in changed] == [[str(a.requester)]]


async def test_handover_refused_out_of_scope_end_of_life_elsewhere_inactive(world: World) -> None:
    """Lane B's terms 6b-6e: each refused, labelled, and the task stays open."""
    a = world.a
    asset, record, give = await _handover_world(world, a)
    scoped = await _hand(world, a, a.requester2, record, give, asset)  # not the owner, no rights
    assert scoped.status_code in {403, 404}, scoped.text
    await world.sql(
        "UPDATE assets SET state_id = (SELECT id FROM asset_states WHERE tenant_id = $1"
        " AND category = 'retired' LIMIT 1) WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(asset["id"]),
    )
    retired = await _hand(world, a, a.admin, record, give, asset)
    assert retired.status_code == 409
    assert "asset_handover_end_of_life" in retired.text
    other, record2, give2 = await _handover_world(world, a)
    await world.sql(
        "UPDATE assets SET owner_user_id = $3 WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(other["id"]),
        a.tech_b,
    )
    fresh_other = (await world.call("GET", f"/assets/{other['id']}", a, a.admin)).json()
    elsewhere = await _hand(world, a, a.admin, record2, give2, fresh_other)
    assert elsewhere.status_code == 409
    assert "asset_assigned_elsewhere" in elsewhere.text
    third, record3, give3 = await _handover_world(world, a)
    await world.sql(
        "UPDATE users SET status = 'disabled' WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        a.requester,
    )
    try:
        inactive = await _hand(world, a, a.admin, record3, give3, third)
        assert inactive.status_code == 422
        assert "handover_person_not_active" in inactive.text
    finally:
        await world.sql(
            "UPDATE users SET status = 'active' WHERE tenant_id = $1 AND id = $2",
            a.tenant,
            a.requester,
        )
    for r in (record, record2, record3):
        assert all(t["status"] == "open" for t in await tasks(world, a, r))


async def test_handover_never_reaches_another_tenant_s_asset(world: World) -> None:
    """Lane B's term 6f: RLS; tenant B's asset is not found from tenant A."""
    a, b = world.a, world.b
    theirs, _, _ = await _handover_world(world, b)
    _, record, give = await _handover_world(world, a)
    crossed = await _hand(world, a, a.admin, record, give, theirs)
    assert crossed.status_code == 404, crossed.text
    [row] = await world.sql(
        "SELECT owner_user_id FROM assets WHERE tenant_id = $1 AND id = $2",
        b.tenant,
        uuid.UUID(theirs["id"]),
    )
    assert row["owner_user_id"] is None


async def test_the_actual_cost_adds_task_costs_for_the_cost_right_only(world: World) -> None:
    """REQ-SR-052 AC3: task costs plus worklog costs; hidden without view_costs."""
    a = world.a
    record = await request_for(world, a, [step("Order", key="order")], {"remote": "no"})
    [order] = await tasks(world, a, record)
    priced = await patch_task(world, a, a.admin, record, order, {"extra_cost": "120.00"})
    assert priced.status_code == 200, priced.text
    logged = await world.call(
        "POST",
        f"{SR}/{record['id']}/worklogs",
        a,
        a.admin,
        json={
            "worklog_type": "fix",
            "started_at": "2026-11-12T09:00:00+00:00",
            "minutes": 30,
            "costs": [{"amount": "5.50", "note": "Cable"}],
        },
    )
    assert logged.status_code == 201, logged.text
    full = await world.call("GET", f"{SR}/{record['id']}/worklogs", a, a.admin)
    assert full.status_code == 200, full.text
    body = full.json()
    assert (Decimal(body["task_cost"]), Decimal(body["actual_cost"])) == (
        Decimal("120.00"),
        Decimal("125.50"),
    )
    hidden = (await world.call("GET", f"{SR}/{record['id']}/worklogs", a, a.tech_a)).json()
    assert (hidden["task_cost"], hidden["actual_cost"]) == (None, None)


async def test_editions_conditions_on_essentials_the_rest_professional(world: World) -> None:
    """The plan's editions: REQ-SR-048 Essentials; -047, -049, -050, -053, -056 Professional."""
    tenant = await create_tenant(world.db.migrator_url, "Essentials plan", edition="essentials")
    (admin,) = await seed_users(world.db, tenant, [{"user_type": "technician"}])
    await assign_system_role(world.db.admin_url, tenant, admin, "tenant_admin")
    org = Org(tenant, admin, admin, admin, admin, admin, admin, admin)
    base: dict[str, Any] = {"questions": [REMOTE], "names": {"en": "Laptop"}}
    when = {"field": "remote", "op": "eq", "value": "yes"}
    professional = {
        "REQ-SR-047": [step("A", key="a"), step("B", key="b", waits_for=["a"])],
        "REQ-SR-049": [step("A", fields=[{"key": "x", "label": {"en": "X"}, "kind": "text"}])],
        "REQ-SR-050": [step("A", owner_kind="requested_for_manager")],
        "REQ-SR-056": [step("A", kind="asset_handover")],
    }
    for req, plan in professional.items():
        refused = await add_item(world, org, admin, **base, plan=plan)
        assert problem(refused) == (403, "entitlement_required"), req
    made = await add_item(world, org, admin, **base, plan=[step("A", key="a", condition=when)])
    assert made.status_code == 201, made.text  # REQ-SR-048: a condition stays Essentials
