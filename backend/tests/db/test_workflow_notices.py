"""The notify node on a real incident (WP-048b S2; REQ-WF-022; lane A's design).

- The node writes one work_items event; the one notification engine sends it, never the step.
- Its audience is the node's: the record's people it names (the requester here) and named
  people, resolved at send time; the engine's own access check still applies, so a named person
  who cannot see the record gets nothing.
- The message is the node's own words, in the recipient's language.
"""

import uuid
from typing import Any

from tests.db.test_incidents_api import World, world
from tests.db.test_notifications_api import deliveries, run_engine
from tests.db.test_workflow_events import _node, _start, _status, _workflow

__all__ = ["world"]  # the fixture, re-used


def _notice(*named: uuid.UUID) -> dict[str, Any]:
    return {
        "format": 1,
        "nodes": [
            _node("s", "start"),
            _node(
                "tell",
                "notify",
                audience={"relatives": ["requester"], "user_ids": [str(p) for p in named]},
                subject={"en": "Your laptop is ready", "ar": "حاسوبك جاهز"},
                body={"en": "Collect it from the service desk."},
            ),
            _node("e", "end"),
        ],
        "links": [
            {"from": "s", "port": "next", "to": "tell"},
            {"from": "tell", "port": "next", "to": "e"},
        ],
        "variables": [],
    }


async def test_req_wf_022_the_engine_sends_the_node_s_words_to_its_audience(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin)
    outsider = a.requester2  # a requester who cannot see someone else's incident
    instance = await _start(world, await _workflow(world, _notice(a.tech_a, outsider)), item["id"])
    assert await _status(world, instance) == "finished"  # the step itself sends nothing

    await run_engine(world, a)
    rows = [
        r for r in await deliveries(world, a, item) if r["event_code"].endswith("workflow_notice")
    ]
    sent = {(r["user_id"], r["channel"]) for r in rows if r["state"] == "sent"}
    assert (a.requester, "in_app") in sent
    assert (a.tech_a, "in_app") in sent
    # The engine's access check at send time: logged, never sent (REQ-NTF-010).
    barred = {(r["state"], r["reason"]) for r in rows if r["user_id"] == outsider}
    assert barred == {("suppressed", "no_access")}
    texts = {r["text_body"] for r in rows if r["user_id"] == a.tech_a}
    assert any(t and "Collect it from the service desk." in t for t in texts)
