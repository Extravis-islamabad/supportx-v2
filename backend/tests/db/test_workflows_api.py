"""The workflow API over HTTP (WP-048b S1; REQ-WF-010, -019, -021, -023).

Real PostgreSQL, the real policy layer and the real incident services: a workflow is made,
its draft saved with a problem named by its node, publishing refused until fixed, published and
switched on, started on an incident (twice: the second refused), and its log read back.
"""

import uuid
from typing import Any

from tests.db.test_incidents_api import CONSOLE, World, problem, world

__all__ = ["world"]  # the fixture, re-used

BASE = "/automation/workflows"


def _new() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4()), **CONSOLE}


def _match(version: int) -> dict[str, str]:
    return {"If-Match": f'"{version}"', **CONSOLE}


def _node(node_id: str, kind: str, **config: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    return {"id": node_id, "type": kind, "config": config, "position": {"x": 0, "y": 0}}


NOTE_LINKS: list[dict[str, str]] = [
    {"from": "start", "port": "next", "to": "note"},
    {"from": "note", "port": "next", "to": "end"},
]
NOTE_THEN_END: dict[str, Any] = {
    "format": 1,
    "nodes": [
        _node("start", "start"),
        _node("note", "note", text={"en": "Escalated by the workflow"}, private=True),
        _node("end", "end"),
    ],
    "links": NOTE_LINKS,
    "variables": [],
}


async def test_a_workflow_is_designed_published_switched_on_and_run_on_an_incident(
    world: World,
) -> None:
    a = world.a
    made = await world.call(
        "POST",
        BASE,
        a,
        a.admin,
        json={"record_type": "incident", "name": "Escalate"},
        headers=_new(),
    )
    assert made.status_code == 201, made.text
    flow = made.json()
    assert (flow["enabled"], flow["published_version"], flow["problems"]) == (False, None, [])

    broken = {**NOTE_THEN_END, "links": [NOTE_LINKS[0]]}  # the note leads nowhere
    saved = await world.call(
        "PUT",
        f"{BASE}/{flow['id']}/draft",
        a,
        a.admin,
        json={"definition": broken},
        headers=_match(1),
    )
    assert saved.status_code == 200, saved.text
    assert {"where": "node:note", "code": "output_not_linked"}.items() <= {
        **next(p for p in saved.json()["problems"] if p["where"] == "node:note")
    }.items()
    refused = await world.call(
        "POST", f"{BASE}/{flow['id']}/publish", a, a.admin, headers=_match(2)
    )
    assert problem(refused) == (422, "workflow_has_problems")

    fixed = await world.call(
        "PUT",
        f"{BASE}/{flow['id']}/draft",
        a,
        a.admin,
        json={"definition": NOTE_THEN_END},
        headers=_match(2),
    )
    assert fixed.json()["problems"] == []
    published = await world.call(
        "POST", f"{BASE}/{flow['id']}/publish", a, a.admin, headers=_match(3)
    )
    assert published.status_code == 200, published.text
    assert published.json()["published_version"] == 1
    on = await world.call(
        "PUT", f"{BASE}/{flow['id']}/enabled", a, a.admin, json={"enabled": True}, headers=_match(4)
    )
    assert on.json()["enabled"] is True

    # The run-as identity holds nothing yet: its note is refused and the instance says why.
    item = await world.create(a, a.admin)
    started = await world.call(
        "POST",
        f"{BASE}/{flow['id']}/instances",
        a,
        a.admin,
        json={"record_id": item["id"]},
        headers=_new(),
    )
    assert started.status_code == 201, started.text
    instance = started.json()
    assert instance["status"] == "failed"
    again = await world.call(
        "POST",
        f"{BASE}/{flow['id']}/instances",
        a,
        a.admin,
        json={"record_id": item["id"]},
        headers=_new(),
    )
    assert problem(again) == (409, "workflow_already_running")  # REQ-WF-010 AC2

    log = await world.call("GET", f"{BASE}/instances/{instance['id']}/steps", a, a.admin)
    assert [s["node"] for s in log.json()][:2] == ["start", "note"]
    listed = await world.call("GET", f"{BASE}/{flow['id']}/instances", a, a.admin)
    assert [i["id"] for i in listed.json()] == [instance["id"]]


async def test_people_without_the_permissions_are_refused(world: World) -> None:
    a = world.a
    designer = await world.call("GET", f"{BASE}?record_type=incident", a, a.requester)
    assert designer.status_code == 403
