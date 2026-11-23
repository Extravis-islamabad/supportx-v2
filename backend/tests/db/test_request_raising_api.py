"""Raising a service request (WP-047a S1; REQ-SR-014, -015, -016), through the API.

Real PostgreSQL with RLS, the incidents test world. Quantity is Professional (`catalog`,
D-133) and is refused on Essentials; needed-by, the expected delivery date and "request again"
are Essentials. The portal's answers are filtered on the server to the requester's questions
(the coordinator's condition 2), and a bulk job never touches a request its starter cannot see
(condition 1).
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from conftest import assign_system_role, create_tenant
from tests.db.test_approvals_api import approvals, decide, manager_of
from tests.db.test_catalog_api import add as add_item
from tests.db.test_catalog_delivery import policy
from tests.db.test_incidents_api import CONSOLE, Org, World, problem, world
from tests.db.test_service_requests_api import SR, an_item, raise_request
from tests.db.test_users_api import seed_users

__all__ = ["world"]  # the fixture, re-used

PORTAL = "/portal/service-requests"
THREE_DAYS = [{"kind": "resolution", "priority": None, "amount": 3, "unit": "business_days"}]


def field_codes(response: Any) -> dict[str, str]:  # noqa: ANN401 - httpx response
    assert response.status_code == 422, response.text
    return {e["field"].removeprefix("body."): e["code"] for e in response.json()["errors"]}


async def test_req_sr_014_quantity_up_to_the_items_maximum(world: World) -> None:
    """AC2: above the item's maximum is the same field error the form shows, with the max."""
    a = world.a
    item = await an_item(world, a, max_quantity=5)
    made = await raise_request(
        world, a, a.requester, catalog_item_id=item["id"], answers={"model": "air"}, quantity=3
    )
    assert made.status_code == 201, made.text
    assert made.json()["quantity"] == 3
    over = await raise_request(
        world, a, a.requester, catalog_item_id=item["id"], answers={"model": "air"}, quantity=6
    )
    assert field_codes(over) == {"quantity": "quantity_over_max"}
    assert over.json()["errors"][0]["params"] == {"max": 5}
    # An item that asks no quantity, and an incident, take none.
    plain = await an_item(world, a)
    none = await raise_request(
        world, a, a.requester, catalog_item_id=plain["id"], answers={"model": "air"}, quantity=2
    )
    assert field_codes(none) == {"quantity": "not_allowed"}
    incident = await world.call(
        "POST",
        "/incidents",
        a,
        a.admin,
        json={"subject": "Printer", "requester_id": str(a.requester), "quantity": 2},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert field_codes(incident) == {"quantity": "not_allowed"}


async def test_req_sr_015_the_expected_date_skips_the_weekend_and_flags_a_sooner_need(
    world: World,
) -> None:
    """AC1 on the SLA's own calendar (3 business days from a Thursday: the Tuesday); AC2."""
    from app.core.tenancy import TenantContext  # noqa: PLC0415
    from app.modules import sla  # noqa: PLC0415

    a = world.a
    rule = await policy(world, a, THREE_DAYS)
    thursday = datetime(2026, 11, 19, 10, 0, tzinfo=UTC)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant, a.admin)) as session:
        due = await sla.delivery_at(session, "service_request", rule["id"], "p2", thursday)
    assert due is not None
    assert due.weekday() == 1  # Tuesday: Friday, Monday and Tuesday, the weekend skipped
    assert timedelta(days=4) <= due - thursday < timedelta(days=6)

    item = await an_item(world, a, sla_policy_id=rule["id"], asks_needed_by=True)
    soon = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    made = await raise_request(
        world, a, a.requester, catalog_item_id=item["id"], answers={"model": "air"}, needed_by=soon
    )
    assert made.status_code == 201, made.text
    record = made.json()
    assert record["expected_delivery_at"] is not None
    assert record["needed_earlier"] is True
    mine = (await world.call("GET", f"{PORTAL}/{record['id']}", a, a.requester)).json()
    assert (mine["expected_delivery_at"] is not None, mine["needed_earlier"]) == (True, True)
    # An item that does not ask takes no needed-by date.
    plain = await an_item(world, a)
    refused = await raise_request(
        world, a, a.requester, catalog_item_id=plain["id"], answers={"model": "air"}, needed_by=soon
    )
    assert field_codes(refused) == {"needed_by": "not_allowed"}


async def test_req_sr_015_ac3_the_date_is_worked_out_again_when_approval_completes(
    world: World,
) -> None:
    a = world.a
    await manager_of(world, a.requester, a.tech_a)
    rule = await policy(world, a, THREE_DAYS)
    item = await an_item(
        world,
        a,
        sla_policy_id=rule["id"],
        approval={"approvers": [{"kind": "requested_for_manager"}]},
    )
    record = (
        await raise_request(
            world, a, a.requester, catalog_item_id=item["id"], answers={"model": "air"}
        )
    ).json()
    before = record["expected_delivery_at"]
    assert before is not None
    [entry] = await approvals(world, a, a.tech_a, record)
    assert (await decide(world, a, a.tech_a, record, entry, "approve")).status_code == 200
    after = (await world.call("GET", f"{SR}/{record['id']}", a, a.admin)).json()
    assert after["expected_delivery_at"] >= before
    # Its change went through the usual update (history and the record's event: live).
    rows = await world.sql(
        "SELECT 1 FROM outbox_events WHERE tenant_id = $1 AND aggregate_id = $2"
        " AND envelope::text LIKE '%expected_delivery_at%'",
        a.tenant,
        record["id"],
    )
    assert rows or after["expected_delivery_at"] == before  # unchanged within the same second


async def test_condition_2_the_portal_never_returns_an_answer_meant_for_staff(
    world: World,
) -> None:
    """A technician-only answer never reaches the portal; the requester's own does (control)."""
    from app.modules.work_items.service.request_notifications import (  # noqa: PLC0415
        VARIABLES,
    )

    a = world.a
    item = await an_item(
        world,
        a,
        questions=[
            {
                "key": "model",
                "label": {"en": "Model"},
                "kind": "choice",
                "required": True,
                "options": ["air", "pro"],
            },
            {
                "key": "asset_tag",
                "label": {"en": "Asset tag"},
                "kind": "text",
                "shown_to": ["technician"],
            },
        ],
    )
    record = (
        await raise_request(
            world, a, a.requester, catalog_item_id=item["id"], answers={"model": "air"}
        )
    ).json()
    secret = f"TAG-{uuid.uuid4().hex[:8]}"
    # As a staff answer will be stored (WP-047a S4): straight onto the row.
    await world.sql(
        "UPDATE work_items SET answers = answers || jsonb_build_object('asset_tag', $3::text)"
        " WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        record["id"],
        secret,
    )
    one = (await world.call("GET", f"{PORTAL}/{record['id']}", a, a.requester)).json()
    listed = (await world.call("GET", PORTAL, a, a.requester)).json()["items"]
    assert one["answers"] == {"model": "air"}  # the control: their own answer is there
    assert secret not in json.dumps(one) + json.dumps(listed)
    staff = (await world.call("GET", f"{SR}/{record['id']}", a, a.admin)).json()
    assert staff["answers"]["asset_tag"] == secret  # staff still see it
    # Request again neither copies a staff answer nor names its question.
    again = (
        await world.call("GET", f"{PORTAL}/{record['id']}/request-again", a, a.requester)
    ).json()
    assert (again["answers"], again["dropped"]) == ({"model": "air"}, [])
    assert secret not in json.dumps(again)
    # Realtime payloads come from the record's events: they carry no answers at all.
    events = await world.sql(
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1 AND aggregate_id = $2",
        a.tenant,
        record["id"],
    )
    assert events
    assert all(secret not in str(e["envelope"]) for e in events)
    # The requester's mails: their source offers no answer among its variables.
    assert not any("answer" in v.name for v in VARIABLES)


async def test_req_sr_016_request_again_fills_the_form_and_lists_what_it_dropped(
    world: World,
) -> None:
    a = world.a
    item = await an_item(
        world,
        a,
        questions=[
            {
                "key": "model",
                "label": {"en": "Model"},
                "kind": "choice",
                "required": True,
                "options": ["air", "pro"],
            },
            {"key": "colour", "label": {"en": "Colour"}, "kind": "text"},
        ],
    )
    record = (
        await raise_request(
            world,
            a,
            a.requester,
            catalog_item_id=item["id"],
            answers={"model": "pro", "colour": "grey"},
        )
    ).json()
    again = await world.call("GET", f"{PORTAL}/{record['id']}/request-again", a, a.requester)
    assert again.status_code == 200, again.text
    assert again.json() == {
        "catalog_item_id": item["id"],
        "available": True,
        "reason": None,
        "answers": {"model": "pro", "colour": "grey"},
        "dropped": [],
    }
    # AC2: the item no longer asks the colour.
    current = (await world.call("GET", f"/catalog/items/{item['id']}", a, a.admin)).json()
    changed = await world.call(
        "PATCH",
        f"/catalog/items/{item['id']}",
        a,
        a.admin,
        json={"questions": [q for q in current["questions"] if q["key"] != "colour"]},
        headers={"If-Match": f'"{current["version"]}"', **CONSOLE},
    )
    assert changed.status_code == 200, changed.text
    later = (
        await world.call("GET", f"{PORTAL}/{record['id']}/request-again", a, a.requester)
    ).json()
    assert (later["answers"], later["dropped"]) == ({"model": "pro"}, ["colour"])
    # Someone else's request: not found, never a sign it exists.
    other = await world.call("GET", f"{PORTAL}/{record['id']}/request-again", a, a.requester2)
    assert problem(other)[0] == 404
    # AC3: a retired item cannot be requested again, with the reason.
    fresh = (await world.call("GET", f"/catalog/items/{item['id']}", a, a.admin)).json()
    retired = await world.call(
        "PATCH",
        f"/catalog/items/{item['id']}",
        a,
        a.admin,
        json={"status": "retired"},
        headers={"If-Match": f'"{fresh["version"]}"', **CONSOLE},
    )
    assert retired.status_code == 200, retired.text
    gone = (
        await world.call("GET", f"{PORTAL}/{record['id']}/request-again", a, a.requester)
    ).json()
    assert (gone["available"], gone["reason"], gone["answers"]) == (
        False,
        "catalog_item_retired",
        {},
    )


async def test_the_subject_comes_from_the_items_template_when_none_is_typed(
    world: World,
) -> None:
    a = world.a
    item = await an_item(world, a, subject_template="Laptop {model} for {person}")
    made = await world.call(
        "POST",
        SR,
        a,
        a.requester,
        json={
            "requester_id": str(a.requester),
            "catalog_item_id": item["id"],
            "answers": {"model": "air"},
        },
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert made.status_code == 201, made.text
    assert made.json()["subject"].startswith("Laptop air for ")
    typed = await raise_request(
        world, a, a.requester, catalog_item_id=item["id"], answers={"model": "air"}
    )
    assert typed.json()["subject"] == "New laptop for Sara"  # what the person typed stays


async def test_condition_1_a_bulk_job_never_touches_a_request_its_starter_cannot_see(
    world: World,
) -> None:
    from app.modules.work_items.service.bulk import run_bulk_jobs  # noqa: PLC0415

    a, b = world.a, world.b
    mine = (
        await raise_request(
            world,
            a,
            a.requester,
            catalog_item_id=(await an_item(world, a))["id"],
            answers={"model": "air"},
        )
    ).json()
    theirs = (
        await raise_request(
            world,
            b,
            b.requester,
            catalog_item_id=(await an_item(world, b))["id"],
            answers={"model": "air"},
        )
    ).json()
    started = await world.call(
        "POST",
        f"{SR}/bulk",
        a,
        a.admin,
        json={
            "action": "edit",
            "changes": {"impact": "team"},
            "record_ids": [mine["id"], theirs["id"]],
        },
    )
    assert started.status_code == 202, started.text
    await run_bulk_jobs(world.app.state.db, world.app.state.settings)
    done = (await world.call("GET", f"{SR}/bulk-jobs/{started.json()['id']}", a, a.admin)).json()
    outcomes = {r["id"]: (r["outcome"], r.get("code")) for r in done["results"]}
    assert outcomes[mine["id"]][0] == "done"
    assert outcomes[theirs["id"]] == ("skipped", "work_item_not_found")
    untouched = (await world.call("GET", f"{SR}/{theirs['id']}", b, b.admin)).json()
    assert untouched["impact"] != "team"


async def test_editions_essentials_may_request_again_and_see_delivery_but_not_quantity(
    world: World,
) -> None:
    """Condition 3, per REQ edition: 015 and 016 are Essentials, 014 is Professional."""
    tenant = await create_tenant(world.db.migrator_url, "Essentials SR", edition="essentials")
    (admin, requester) = await seed_users(
        world.db, tenant, [{"user_type": "technician"}, {"user_type": "requester"}]
    )
    await assign_system_role(world.db.admin_url, tenant, admin, "tenant_admin")
    await assign_system_role(world.db.admin_url, tenant, requester, "requester")
    org = Org(tenant, admin, admin, admin, admin, admin, requester, requester)
    questions = [
        {
            "key": "model",
            "label": {"en": "Model"},
            "kind": "choice",
            "required": True,
            "options": ["air", "pro"],
        },
    ]
    group = await world.call("POST", "/organization/groups", org, admin, json={"name": "Desk"})
    assert group.status_code == 201, group.text
    gid = group.json()["id"]
    refused = await add_item(
        world, org, admin, questions=questions, max_quantity=2, status="published", group_id=gid
    )
    assert problem(refused) == (403, "entitlement_required")
    made = await add_item(
        world,
        org,
        admin,
        questions=questions,
        asks_needed_by=True,
        status="published",
        group_id=gid,
    )
    assert made.status_code == 201, made.text
    item = made.json()
    record = await raise_request(
        world, org, requester, catalog_item_id=item["id"], answers={"model": "air"}
    )
    assert record.status_code == 201, record.text
    assert "expected_delivery_at" in record.json()  # the delivery date is theirs (no SLA: null)
    with_quantity = await raise_request(
        world, org, requester, catalog_item_id=item["id"], answers={"model": "air"}, quantity=1
    )
    assert problem(with_quantity) == (403, "entitlement_required")
    again = await world.call("GET", f"{PORTAL}/{record.json()['id']}/request-again", org, requester)
    assert again.status_code == 200, again.text
    assert again.json()["available"] is True
