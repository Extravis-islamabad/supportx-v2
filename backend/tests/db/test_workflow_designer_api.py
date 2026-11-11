"""The designer's palette and outputs (WP-048b S4; REQ-WF-009 AC3, REQ-WF-028).

- The palette lists the node types a record type offers, each in its group, and says why one
  cannot be used now (a function without a runner).
- The outputs of nodes being designed come from the same registry as validation: a switch's
  cases, a wait's timeout.
- Both are the admins' (workflows.manage).
"""

from tests.db.test_incidents_api import World, world

__all__ = ["world"]  # the fixture, re-used

BASE = "/automation/workflows"


async def test_req_wf_009_ac3_the_palette_is_the_record_type_s(world: World) -> None:
    a = world.a
    got = await world.call(
        "GET", f"{BASE}/node-types", a, a.admin, params={"record_type": "release"}
    )
    assert got.status_code == 200, got.text
    palette = {n["type"]: n for n in got.json()}
    assert {"start", "end", "if", "approval", "webhook"} <= set(palette)
    assert (palette["if"]["category"], palette["if"]["outputs"]) == ("logic", ["yes", "no"])
    assert palette["approval"]["available"] is True  # releases open approvals
    function = palette["function"]
    assert (function["available"], function["why_not"]) == (False, "function_not_offered")


async def test_the_outputs_of_nodes_being_designed(world: World) -> None:
    a = world.a
    got = await world.call(
        "POST",
        f"{BASE}/node-ports",
        a,
        a.admin,
        json={
            "nodes": [
                {"type": "switch", "config": {"cases": [{"port": "p1"}, {"port": "p2"}]}},
                {"type": "wait", "config": {"limit_seconds": 60}},
                {"type": "not_a_type", "config": {}},
            ]
        },
    )
    assert got.status_code == 200, got.text
    assert [n["outputs"] for n in got.json()] == [
        ["p1", "p2", "default"],
        ["next", "overtaken", "timeout"],
        [],
    ]


async def test_the_palette_is_the_admins(world: World) -> None:
    a = world.a
    refused = await world.call(
        "GET", f"{BASE}/node-types", a, a.tech_a, params={"record_type": "incident"}
    )
    assert refused.status_code == 403
    too_many = await world.call(
        "POST", f"{BASE}/node-ports", a, a.admin, json={"nodes": [{"type": "end"}] * 201}
    )
    assert too_many.status_code == 422
