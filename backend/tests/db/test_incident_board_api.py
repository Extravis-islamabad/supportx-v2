"""The incident board's column counts (WP-046b S3b; REQ-INC-111; lane C's condition 1).

Real PostgreSQL, the incidents test world. A count is of the list's own query, so it only counts
records the reader may see, and columns keep a stable order, never by count.
"""

import uuid
from typing import Any

import pytest

from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import BASE, Org, World, field_codes

pytestmark = [pytest.mark.db, pytest.mark.valkey, MODULE_LOOP]
__all__ = ["module_world", "shared_world"]  # the fixtures, used by name


async def _board(w: World, org: Org, user: uuid.UUID, **body: Any) -> Any:  # noqa: ANN401 - JSON
    return await w.call("POST", f"{BASE}/board", org, user, json=body)


def _counts(response: Any) -> dict[str | None, int]:  # noqa: ANN401 - JSON
    assert response.status_code == 200, response.text
    return {c["key"]: c["count"] for c in response.json()}


async def test_counts_are_the_readers_own_and_columns_keep_their_order(world: World) -> None:
    a = world.a
    tag = uuid.uuid4().hex[:8]
    subject = {"field": "subject", "op": "contains", "value": f"Board {tag}"}
    for group in (a.ga, a.ga, a.gb):
        await world.create(a, a.admin, group_id=str(group), subject=f"Board {tag}")
    by_admin = await _board(world, a, a.admin, filter=subject)
    assert by_admin.headers["cache-control"] == "no-store"
    statuses = [c["key"] for c in by_admin.json()]
    # Every status in its workflow order, the empty ones too (lane C), whatever the counts.
    catalogue = (await world.call("GET", f"{BASE}/settings", a, a.admin)).json()
    enabled = [s["code"] for s in catalogue["statuses"] if not s.get("disabled")]
    assert statuses[: len(enabled)] == enabled
    assert sum(_counts(by_admin).values()) == 3
    # A technician of GA only counts what they see (the GB one is out of their scope).
    assert sum(_counts(await _board(world, a, a.tech_a, filter=subject)).values()) == 2
    # By group: IDs in a fixed order, the count under the reader's scope.
    groups = _counts(
        await _board(world, a, a.admin, filter=subject, params={"group_by": ["group"]})
    )
    assert groups == {str(a.ga): 2, str(a.gb): 1}


async def test_unassigned_is_its_own_column_last_and_bad_choices_are_refused(world: World) -> None:
    a = world.a
    tag = uuid.uuid4().hex[:8]
    subject = {"field": "subject", "op": "contains", "value": f"Unassigned {tag}"}
    await world.create(a, a.admin, group_id=str(a.ga), subject=f"Unassigned {tag}")
    shown = await _board(world, a, a.admin, filter=subject, params={"group_by": ["technician"]})
    assert shown.json()[-1] == {"key": None, "count": 1}
    refused = await _board(world, a, a.admin, params={"group_by": ["site"]})
    assert field_codes(refused) == {"params.group_by": "invalid_choice"}
    assert "site" not in refused.text
    # The list's own view narrows it too.
    viewed = await _board(world, a, a.admin, filter=subject, params={"view": ["unassigned"]})
    assert sum(_counts(viewed).values()) == 1
