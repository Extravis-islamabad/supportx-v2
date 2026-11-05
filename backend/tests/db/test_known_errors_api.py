"""Known errors (WP-044b s3; REQ-PRB-034, -036, -037, -038, -042). Real Postgres.

The workaround needs problems.edit_solution. Marking needs problems.mark_known_error and a
workaround or root cause written; removing needs a reason. Resolving retires it. The database
searches subject, symptoms and workaround, never the root cause. Suggestions match an incident's
words to open known errors the technician may see.
"""

import uuid
from typing import Any

from tests.db.test_incidents_api import CONSOLE, Org, World, field_codes, problem, role, world
from tests.db.test_problems_api import PRB, new_problem

__all__ = ["world"]  # the fixture, re-used


async def fresh(world: World, org: Org, user: uuid.UUID, record: dict[str, Any]) -> dict[str, Any]:
    return dict((await world.call("GET", f"{PRB}/{record['id']}", org, user)).json())


async def post(
    world: World,
    org: Org,
    user: uuid.UUID,
    record: dict[str, Any],
    path: str,
    body: dict[str, Any],
) -> Any:  # noqa: ANN401 - an httpx response
    return await world.call(
        "POST",
        f"{PRB}/{record['id']}/{path}",
        org,
        user,
        json=body,
        headers={"If-Match": f'"{record["version"]}"', **CONSOLE},
    )


async def test_marking_needs_something_written_and_removing_needs_a_reason(world: World) -> None:
    a = world.a
    record = (await new_problem(world, a, a.tech_a, group_id=str(a.ga))).json()
    empty = await post(world, a, a.tech_a, record, "known-error", {})
    assert field_codes(empty) == {
        "workaround": "required_for_known_error",
        "root_cause": "required_for_known_error",
    }
    # Another group's technician may read it but not write the solution or mark it.
    patched = await world.call(
        "PATCH",
        f"{PRB}/{record['id']}",
        a,
        a.tech_b,
        json={"workaround": "<p>Restart the relay.</p>"},
        headers={"If-Match": f'"{record["version"]}"', **CONSOLE},
    )
    assert problem(patched)[0] == 403
    done = await world.call(
        "PATCH",
        f"{PRB}/{record['id']}",
        a,
        a.tech_a,
        json={"workaround": "<p>Restart the relay.</p>"},
        headers={"If-Match": f'"{record["version"]}"', **CONSOLE},
    )
    assert done.status_code == 200, done.text
    record = done.json()
    assert problem(await post(world, a, a.tech_b, record, "known-error", {}))[0] == 403
    marked = await post(world, a, a.tech_a, record, "known-error", {"comment": "Seen 3 times"})
    assert marked.status_code == 200, marked.text
    record = marked.json()
    assert record["known_error_at"] is not None
    assert problem(await post(world, a, a.tech_a, record, "known-error", {})) == (
        409,
        "already_known_error",
    )
    no_reason = await post(world, a, a.tech_a, record, "known-error/remove", {"reason": ""})
    assert problem(no_reason)[0] == 422
    removed = await post(
        world, a, a.tech_a, record, "known-error/remove", {"reason": "Not a known error"}
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["known_error_at"] is None
    history = await world.call("GET", f"{PRB}/{record['id']}/history", a, a.tech_a)
    reasons = {e["reason"] for e in history.json()["items"]}
    assert {"Seen 3 times", "Not a known error"} <= reasons


async def test_database_search_retire_on_resolve_and_suggestions(world: World) -> None:
    a, b = world.a, world.b
    record = (
        await new_problem(
            world,
            a,
            a.tech_a,
            group_id=str(a.ga),
            subject="Mail relay drops messages",
            symptoms="<p>Error 4.4.2 connection dropped</p>",
            workaround="<p>Restart the relay service.</p>",
            root_cause="<p>Secret cert expired</p>",
        )
    ).json()
    record = (await post(world, a, a.tech_a, record, "known-error", {})).json()

    async def search(q: str, user: uuid.UUID = a.tech_a, org: Org = a) -> list[dict[str, Any]]:
        found = await world.call("GET", f"{PRB}/known-errors?q={q}", org, user)
        assert found.status_code == 200, found.text
        return list(found.json())

    hits = await search("4.4.2")  # only in the symptoms (REQ-PRB-037 AC1)
    assert [h["display_id"] for h in hits] == [record["display_id"]]
    assert "root_cause" not in hits[0]
    assert await search("Secret") == []  # never searched in the root cause (D-140 Q7)
    assert await search("4.4.2", b.admin, b) == []  # another tenant

    incident = await world.create(
        a,
        a.admin,
        group_id=str(a.ga),
        subject="Mail keeps failing",
        description="<p>Users see Error 4.4.2 when sending</p>",
    )
    suggested = await world.call(
        "GET", f"{PRB}/known-errors/suggestions?incident_id={incident['id']}", a, a.tech_a
    )
    assert [s["display_id"] for s in suggested.json()] == [record["display_id"]]
    assert suggested.json()[0]["workaround"] == "<p>Restart the relay service.</p>"

    # Resolving it retires it; it stays in the database, marked, and leaves the suggestions.
    record = await fresh(world, a, a.tech_a, record)
    for action, body in (
        ("investigate", {}),
        ("confirm_root_cause", {}),
        ("resolve", {"resolution": "<p>New certificate.</p>"}),
    ):
        moved = await post(world, a, a.tech_a, record, f"actions/{action}", body)
        assert moved.status_code == 200, moved.text
        record = moved.json()
    assert record["known_error_retired_at"] is not None
    retired = await search("4.4.2")
    assert retired[0]["retired_at"] is not None
    live_only = await world.call(
        "GET", f"{PRB}/known-errors?q=4.4.2&include_retired=false", a, a.tech_a
    )
    assert live_only.json() == []
    gone = await world.call(
        "GET", f"{PRB}/known-errors/suggestions?incident_id={incident['id']}", a, a.tech_a
    )
    assert gone.json() == []
    history = await world.call("GET", f"{PRB}/{record['id']}/history", a, a.tech_a)
    fields = {c["field"] for e in history.json()["items"] for c in e["changes"]}
    assert "known_error_retired_at" in fields


async def test_a_role_without_the_rights_cannot_write_the_workaround(world: World) -> None:
    a = world.a
    viewer = await role(
        world, a, "Problem viewer", [("problems.view", "all"), ("problems.edit", "all")]
    )
    await world.call("PUT", f"/users/{a.requester2}/roles/{viewer}", a, a.admin)
    record = (await new_problem(world, a, a.admin)).json()
    refused = await world.call(
        "PATCH",
        f"{PRB}/{record['id']}",
        a,
        a.requester2,
        json={"workaround": "<p>x</p>"},
        headers={"If-Match": f'"{record["version"]}"', **CONSOLE},
    )
    assert problem(refused)[0] == 403
    ops = {
        o["action"]: o["allowed"]
        for o in (await fresh(world, a, a.requester2, record))["operations"]
    }
    assert (ops["edit_solution"], ops["mark_known_error"]) == (False, False)
