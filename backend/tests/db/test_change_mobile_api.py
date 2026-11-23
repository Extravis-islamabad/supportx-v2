"""Changes and their approvals from the mobile app (WP-045d S4b; REQ-CHG-110).

The app uses the same public API as the console (P2), so the same rules and prompts apply
(AC2). What the server tells apart is only where a decision was made: the mobile app is one
of our staff apps, so its decisions are recorded as made in the app, not in the portal.
"""

import pytest

from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_approvals_api import manager_of
from tests.db.test_changes_api import CHG, a_change, move
from tests.db.test_incidents_api import World

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

MOBILE = {"X-SupportX-Client": "mobile"}


@pytest.mark.parametrize(("client", "channel"), [("mobile", "app"), ("portal", "portal")])
async def test_req_chg_110_a_decision_from_the_mobile_app_is_recorded_as_the_app(
    world: World, client: str, channel: str
) -> None:
    a = world.a
    await manager_of(world, a.requester, a.tech_a)
    item = await a_change(world, a)
    assert (await move(world, a, item, "submission_awaiting_acceptance")).status_code == 200
    mine = await world.call(
        "GET", f"{CHG}/my-approvals", a, a.tech_a, headers={"X-SupportX-Client": client}
    )
    assert mine.status_code == 200, mine.text
    [entry] = [i for i in mine.json()["items"] if i["record_id"] == item["id"]]
    decided = await world.call(
        "POST",
        f"{CHG}/{item['id']}/approvals/{entry['approval_id']}/decision",
        a,
        a.tech_a,
        json={"decision": "approve"},
        headers={"If-Match": f'"{entry["approval_version"]}"', "X-SupportX-Client": client},
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["channel"] == channel


async def test_req_chg_110_ac2_a_move_from_the_app_follows_the_console_rules(
    world: World,
) -> None:
    """The same stage rules answer the app: a move the life cycle refuses is refused the same."""
    a = world.a
    item = await a_change(world, a)
    for headers in (MOBILE, {"X-SupportX-Client": "console"}):
        refused = await world.call(
            "POST",
            f"{CHG}/{item['id']}/moves",
            a,
            a.admin,
            json={"to_status": "implementation_in_progress"},
            headers={"If-Match": f'"{item["version"]}"', **headers},
        )
        assert refused.status_code == 409, refused.text
        assert refused.json()["code"] == "stage_move_not_allowed", refused.text
