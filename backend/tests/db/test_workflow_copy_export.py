"""Copy, export, import and delete a workflow (WP-048b S3d; REQ-WF-027).

- A copy is an independent draft under the name the screen gives it (AC1).
- Exporting and importing in the same tenant gives an identical definition (AC2); a file from
  another tenant, of another shape, too large, or naming templates that are not here is refused.
- A workflow with live runs cannot be deleted; it can be disabled (AC3).
- The list shows each workflow's live runs.
"""

import uuid
from typing import Any

from tests.db.test_incidents_api import CONSOLE, World, world
from tests.db.test_workflow_events import WAIT_FOR_P1, _start, _workflow

__all__ = ["world"]  # the fixture, re-used

BASE = "/automation/workflows"


async def _post(world: World, path: str, body: dict[str, Any]) -> Any:  # noqa: ANN401 - response
    return await world.call(
        "POST",
        path,
        world.a,
        world.a.admin,
        json=body,
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )


async def _version(world: World, flow: uuid.UUID) -> int:
    got = await world.call("GET", f"{BASE}/{flow}", world.a, world.a.admin)
    return int(got.json()["version"])


async def test_req_wf_027_ac1_a_copy_is_an_independent_draft(world: World) -> None:
    a = world.a
    flow = await _workflow(world, WAIT_FOR_P1)
    copied = await _post(world, f"{BASE}/{flow}/copy", {"name": "Major incident (copy)"})
    assert copied.status_code == 201, copied.text
    body = copied.json()
    assert (body["name"], body["enabled"], body["published_version"]) == (
        "Major incident (copy)",
        False,
        None,
    )
    assert body["id"] != str(flow)
    assert body["draft"]["nodes"] == WAIT_FOR_P1["nodes"]
    again = await _post(world, f"{BASE}/{flow}/copy", {"name": "Major incident (copy)"})
    assert again.json()["name"] == "Major incident (copy) (2)"  # a taken name gets a number
    # Independent: the copy's draft changes, the original's does not.
    saved = await world.call(
        "PUT",
        f"{BASE}/{body['id']}/draft",
        a,
        a.admin,
        json={"definition": {**WAIT_FOR_P1, "variables": [{"name": "x", "type": "text"}]}},
        headers={"If-Match": f'"{body["version"]}"'},
    )
    assert saved.status_code == 200, saved.text
    original = await world.call("GET", f"{BASE}/{flow}", a, a.admin)
    assert original.json()["draft"]["variables"] == []


async def test_req_wf_027_ac2_export_and_import_here_give_an_identical_definition(
    world: World,
) -> None:
    a = world.a
    flow = await _workflow(world, WAIT_FOR_P1)
    exported = await world.call("GET", f"{BASE}/{flow}/export", a, a.admin)
    assert exported.status_code == 200, exported.text
    assert "attachment" in exported.headers["content-disposition"]
    file = exported.json()
    assert (file["format"], file["tenant_id"]) == ("supportx.workflow", str(a.tenant))
    imported = await _post(world, f"{BASE}/import", file)
    assert imported.status_code == 201, imported.text
    assert imported.json()["draft"] == file["definition"]
    assert imported.json()["enabled"] is False


async def test_an_import_refuses_another_tenant_s_file_and_other_shapes(world: World) -> None:
    a = world.a
    flow = await _workflow(world, WAIT_FOR_P1)
    file = (await world.call("GET", f"{BASE}/{flow}/export", a, a.admin)).json()
    theirs = await _post(world, f"{BASE}/import", {**file, "tenant_id": str(world.b.tenant)})
    assert theirs.status_code == 422
    assert theirs.json()["code"] == "workflow_file_other_tenant"
    other_shape = await _post(world, f"{BASE}/import", {**file, "format": "something.else"})
    assert other_shape.status_code == 422
    templates = await _post(
        world, f"{BASE}/import", {**file, "start_templates": [str(uuid.uuid4())]}
    )
    assert templates.status_code == 422
    assert templates.json()["code"] == "templates_not_found"
    huge = {
        **file,
        "description": None,
        "definition": {**file["definition"], "pad": "x" * 1_100_000},
    }
    too_big = await _post(world, f"{BASE}/import", huge)
    assert too_big.status_code == 422
    assert too_big.json()["code"] == "workflow_file_too_large"


async def test_req_wf_027_ac3_a_workflow_with_live_runs_is_not_deleted(world: World) -> None:
    a = world.a
    flow = await _workflow(world, WAIT_FOR_P1)
    item = await world.create(a, a.admin)
    await _start(world, flow, item["id"])
    listed = await world.call("GET", BASE, a, a.admin, params={"record_type": "incident"})
    assert next(w for w in listed.json() if w["id"] == str(flow))["running"] == 1
    refused = await world.call(
        "DELETE",
        f"{BASE}/{flow}",
        a,
        a.admin,
        headers={"If-Match": f'"{await _version(world, flow)}"'},
    )
    assert refused.status_code == 409
    assert refused.json()["code"] == "workflow_has_running_instances"
    made = await _post(world, BASE, {"record_type": "incident", "name": "Not used yet"})
    assert made.status_code == 201, made.text
    unused = uuid.UUID(made.json()["id"])
    gone = await world.call(
        "DELETE",
        f"{BASE}/{unused}",
        a,
        a.admin,
        headers={"If-Match": f'"{await _version(world, unused)}"'},
    )
    assert gone.status_code == 204, gone.text
    assert (await world.call("GET", f"{BASE}/{unused}", a, a.admin)).status_code == 404
