"""Changes' approval settings (WP-045b S3; REQ-CHG-039, -041).

Strict segregation of duties is the tenant's choice, audited with the type's settings: off, a
member of an implementing group still approves (Haider's default); on, every member is barred and
the administrators decide, saying why. Both settings are refused for other types.
"""

from typing import Any

from sqlalchemy import text

from app.core.tenancy import TenantContext
from tests.db.test_changes_api import CHG, a_change, move
from tests.db.test_incidents_api import CONSOLE, Org, World, world

__all__ = ["world"]  # the fixture, re-used


async def settings(world: World, org: Org, path: str = CHG, **body: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    current = (await world.call("GET", f"{path}/settings", org, org.admin)).json()
    changed = await world.call(
        "PATCH",
        f"{path}/settings",
        org,
        org.admin,
        json=body,
        headers={"If-Match": f'"{current["version"]}"', **CONSOLE},
    )
    return {"status": changed.status_code, "body": changed.json()}


async def group_implements(world: World, org: Org, item: dict[str, Any]) -> dict[str, Any]:
    fresh = (await world.call("GET", f"{CHG}/{item['id']}", org, org.admin)).json()
    set_ = await world.call(
        "PUT",
        f"{CHG}/{item['id']}/roles/implementer",
        org,
        org.admin,
        json={"group_ids": [str(org.ga)]},
        headers={"If-Match": f'"{fresh["version"]}"', **CONSOLE},
    )
    assert set_.status_code == 200, set_.text
    return dict((await world.call("GET", f"{CHG}/{item['id']}", org, org.admin)).json())


async def test_req_chg_039_strict_bars_every_member_of_an_implementing_group(
    world: World,
) -> None:
    from tests.db.test_approvals_api import manager_of  # noqa: PLC0415 - shared helper

    a = world.a
    await manager_of(world, a.requester, a.tech_a)  # tech_a: line manager and in GA
    shown = (await world.call("GET", f"{CHG}/settings", a, a.admin)).json()
    assert (shown["segregation_strict"], shown["cab_every_match"]) == (False, False)
    turned = await settings(world, a, segregation_strict=True)
    assert turned["status"] == 200, turned
    assert turned["body"]["segregation_strict"] is True
    item = await group_implements(world, a, await a_change(world, a))
    assert (await move(world, a, item, "submission_awaiting_acceptance")).status_code == 200
    rows = (await world.call("GET", f"{CHG}/{item['id']}/approvals", a, a.admin)).json()["items"]
    assert [(r["approver_id"], r["route_reason"]) for r in rows] == [
        (None, "segregation_of_duties")
    ]
    # Audited as a settings change, naming the field.
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        logged = await session.scalar(
            text(
                "SELECT count(*) FROM audit_entries WHERE action = 'change.settings_changed' "
                "AND details::text LIKE '%segregation_strict%'"
            )
        )
    assert logged == 1
    # The fallback is audited too, naming the level, the reason and who decides (REQ-CHG-039).
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        rerouted = (
            await session.execute(
                text(
                    "SELECT details FROM audit_entries WHERE action = 'change.approval_rerouted' "
                    "AND object_id = :r"
                ),
                {"r": item["id"]},
            )
        ).scalar_one()
    assert (rerouted["level"], rerouted["reason"], rerouted["to"]) == (
        1,
        "segregation_of_duties",
        "approval_administrators",
    )
    # Tenant B keeps the default.
    other = (await world.call("GET", f"{CHG}/settings", world.b, world.b.admin)).json()
    assert other["segregation_strict"] is False


async def test_change_settings_are_refused_for_other_types(world: World) -> None:
    a = world.a
    refused = await settings(world, a, "/incidents", segregation_strict=True, cab_every_match=True)
    assert refused["status"] == 422
    assert {e["field"].removeprefix("body."): e["code"] for e in refused["body"]["errors"]} == {
        "segregation_strict": "not_allowed",
        "cab_every_match": "not_allowed",
    }


async def test_req_chg_039_the_submit_warning_names_who_is_left_out(world: World) -> None:
    """Before acceptance opens: the implementer is left out and the administrators decide."""
    from tests.db.test_approvals_api import manager_of  # noqa: PLC0415 - shared helper

    a = world.a
    await manager_of(world, a.requester, a.tech_a)  # tech_a: the line manager
    item = await a_change(world, a)
    shown = await world.call(
        "GET", f"{CHG}/{item['id']}/approvals/preview", a, a.admin, params={"stage": "submission"}
    )
    assert shown.status_code == 200, shown.text
    assert shown.json() == {
        "stage": "submission",
        "approver_ids": [str(a.tech_a)],
        "barred": [],
        "fallback_reason": None,
    }
    fresh = (await world.call("GET", f"{CHG}/{item['id']}", a, a.admin)).json()
    set_ = await world.call(
        "PUT",
        f"{CHG}/{item['id']}/roles/implementer",
        a,
        a.admin,
        json={"user_ids": [str(a.tech_a)]},
        headers={"If-Match": f'"{fresh["version"]}"', **CONSOLE},
    )
    assert set_.status_code == 200, set_.text
    warned = await world.call(
        "GET", f"{CHG}/{item['id']}/approvals/preview", a, a.admin, params={"stage": "submission"}
    )
    assert warned.json()["barred"] == [
        {"user_id": str(a.tech_a), "reason": "segregation_of_duties"}
    ]
    assert warned.json()["fallback_reason"] == "segregation_of_duties"
    # Nothing was opened by looking.
    listed = await world.call("GET", f"{CHG}/{item['id']}/approvals", a, a.admin)
    assert listed.json()["items"] == []
