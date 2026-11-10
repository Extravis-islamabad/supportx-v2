"""Search words between hyphens and brackets (QA10-P1-01): a draft finds its twin problem."""

import uuid

from tests.db.test_incidents_api import CONSOLE, World, world

__all__ = ["world"]  # the fixture, re-used

SUBJECT = "QA-2026-11-10 VPN drops every few minutes (flow 2 problem)"


async def test_qa10_p1_01_a_subject_with_hyphens_and_brackets_finds_its_twin(world: World) -> None:
    a = world.a
    made = await world.call(
        "POST",
        "/problems",
        a,
        a.admin,
        json={"subject": SUBJECT, "requester_id": str(a.requester)},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert made.status_code == 201, made.text
    for typed in (SUBJECT, "QA-2026-11-10 VPN", "VPN drops (flow 2", "minutes (flow 2 problem)"):
        found = await world.call("GET", "/problems/similar", a, a.admin, params={"q": typed})
        assert found.status_code == 200, found.text
        assert [p["id"] for p in found.json()] == [made.json()["id"]], typed
