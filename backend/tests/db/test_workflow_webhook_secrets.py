"""A webhook step's header values are write-only (the coordinator, #406).

- Every read of a workflow (the draft, a save's answer, the export file) shows each header's
  value masked; the stored value is what the call sends.
- A save that sends the mask back keeps the stored value; a new value replaces it.
- A stored value never follows a changed address: the step needs its values typed again.
- A file imported here has no values: each masked header is a problem until entered again.
- The record's panel never shows step settings at all (#379, its own test).
"""

import copy
import json
import uuid
from typing import Any

from app.modules.automation.domain.workflows import SECRET_MASK
from tests.db.test_incidents_api import CONSOLE, World, world
from tests.db.test_workflow_events import _node, _workflow

__all__ = ["world"]  # the fixture, re-used

BASE = "/automation/workflows"
TOKEN = "Bearer s3cr3t-token-value"

FLOW: dict[str, Any] = {
    "format": 1,
    "nodes": [
        _node("s", "start"),
        _node(
            "call",
            "webhook",
            url="https://hooks.example.test/supportx",
            headers={"Authorization": TOKEN, "X-Team": "network"},
            fields=["subject"],
        ),
        _node("e", "end"),
    ],
    "links": [
        {"from": "s", "port": "next", "to": "call"},
        {"from": "call", "port": "next", "to": "e"},
    ],
    "variables": [],
}


def _headers(definition: dict[str, Any]) -> dict[str, str]:
    node = next(n for n in definition["nodes"] if n["id"] == "call")
    return dict(node["config"]["headers"])


async def _stored(world: World, flow: uuid.UUID) -> dict[str, str]:
    rows = await world.sql(
        "SELECT draft FROM workflows WHERE id = $1 AND tenant_id = $2", flow, world.a.tenant
    )
    draft = rows[0]["draft"]
    return _headers(draft if isinstance(draft, dict) else json.loads(draft))


async def test_header_values_are_masked_on_every_read_and_kept_on_a_masked_save(
    world: World,
) -> None:
    a = world.a
    flow = await _workflow(world, FLOW)
    got = await world.call("GET", f"{BASE}/{flow}", a, a.admin)
    assert got.status_code == 200, got.text
    assert _headers(got.json()["draft"]) == {"Authorization": SECRET_MASK, "X-Team": SECRET_MASK}
    assert TOKEN not in got.text
    # The designer saves what it was shown: the stored values stay; a typed one replaces.
    sent = copy.deepcopy(got.json()["draft"])
    next(n for n in sent["nodes"] if n["id"] == "call")["config"]["headers"]["X-Team"] = "ops"
    saved = await world.call(
        "PUT",
        f"{BASE}/{flow}/draft",
        a,
        a.admin,
        json={"definition": sent},
        headers={"If-Match": f'"{got.json()["version"]}"'},
    )
    assert saved.status_code == 200, saved.text
    assert TOKEN not in saved.text
    assert saved.json()["problems"] == []
    assert await _stored(world, flow) == {"Authorization": TOKEN, "X-Team": "ops"}


async def test_an_export_carries_no_header_value_and_its_import_asks_for_them(
    world: World,
) -> None:
    a = world.a
    flow = await _workflow(world, FLOW)
    exported = await world.call("GET", f"{BASE}/{flow}/export", a, a.admin)
    assert exported.status_code == 200, exported.text
    assert TOKEN not in exported.text
    imported = await world.call(
        "POST",
        f"{BASE}/import",
        a,
        a.admin,
        json=exported.json(),
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert imported.status_code == 201, imported.text
    problems = [(p["where"], p["code"]) for p in imported.json()["problems"]]
    assert ("node:call", "webhook_header_value_missing") in problems


async def test_a_stored_value_never_follows_a_changed_address(world: World) -> None:
    a = world.a
    flow = await _workflow(world, FLOW)
    got = await world.call("GET", f"{BASE}/{flow}", a, a.admin)
    sent = copy.deepcopy(got.json()["draft"])
    step = next(n for n in sent["nodes"] if n["id"] == "call")
    step["config"]["url"] = "https://elsewhere.example.test/collect"
    saved = await world.call(
        "PUT",
        f"{BASE}/{flow}/draft",
        a,
        a.admin,
        json={"definition": sent},
        headers={"If-Match": f'"{got.json()["version"]}"'},
    )
    assert saved.status_code == 200, saved.text
    problems = [(p["where"], p["code"]) for p in saved.json()["problems"]]
    assert ("node:call", "webhook_header_value_missing") in problems
    assert await _stored(world, flow) == {"Authorization": SECRET_MASK, "X-Team": SECRET_MASK}
    refused = await world.call(
        "POST",
        f"{BASE}/{flow}/publish",
        a,
        a.admin,
        headers={"If-Match": f'"{saved.json()["version"]}"', **CONSOLE},
    )
    assert refused.status_code == 422
    assert refused.json()["code"] == "workflow_has_problems"
