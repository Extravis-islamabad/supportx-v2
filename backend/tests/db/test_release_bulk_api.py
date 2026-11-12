"""Bulk actions on releases (WP-058b S5a; REQ-REL-057; migration 0149).

- `assign_role` sets a release role's holders on every chosen release, each through the single
  assign (set_role): the acting person's own rights and the stage's access are checked per
  release, so one they may not edit is skipped with why, never forced (the coordinator's
  condition).
- Only a type with record roles has it; it needs a role and someone to hold it.
- The staged lists' cancel and trash work on releases too.
- Bulk jobs stay per tenant (RLS).
"""

import uuid
from typing import Any

from tests.db.test_incidents_api import CONSOLE, Org, World, world
from tests.db.test_release_guards_api import release_workers, set_access
from tests.db.test_releases_api import REL, a_release, moved

__all__ = ["world"]  # the fixture, re-used


async def _bulk(
    world: World,
    org: Org,
    action: str,
    records: list[dict[str, Any]],
    *,
    user: uuid.UUID | None = None,
    base: str = REL,
    **changes: Any,  # noqa: ANN401 - JSON
) -> dict[str, Any]:
    from app.modules.work_items.service.bulk import run_bulk_jobs  # noqa: PLC0415 - the runner

    started = await world.call(
        "POST",
        f"{base}/bulk",
        org,
        user or org.admin,
        json={"action": action, "changes": changes, "record_ids": [r["id"] for r in records]},
    )
    assert started.status_code == 202, started.text
    await run_bulk_jobs(world.app.state.db, world.app.state.settings)
    done = await world.call(
        "GET", f"{base}/bulk-jobs/{started.json()['id']}", org, user or org.admin
    )
    assert done.status_code == 200, done.text
    return dict(done.json())


async def _holders(world: World, org: Org, item: dict[str, Any], role: str) -> list[str]:
    roles = (await world.call("GET", f"{REL}/{item['id']}/roles", org, org.admin)).json()
    found = next(r for r in roles["roles"] if r["code"] == role)
    return list(found["user_ids"])


async def test_req_rel_057_assign_role_sets_the_engineer_and_skips_what_the_person_may_not_edit(
    world: World,
) -> None:
    a = world.a
    await release_workers(world, a)  # Tech A and Tech B may edit releases
    # Submission is editable by group GB only: Tech A (GA) may not edit a release there.
    saved = await set_access(world, a, "submission", edit={"group_ids": [str(a.gb)]})
    assert saved.status_code == 200, saved.text
    planning = await moved(world, a, await a_release(world, a), "submission_accepted")
    assert planning["stage"] == "planning"
    held = await a_release(world, a)  # still in submission

    done = await _bulk(
        world,
        a,
        "assign_role",
        [planning, held],
        user=a.tech_a,
        role="release_engineer",
        user_ids=[str(a.tech_b)],
    )
    assert (done["status"], done["done_count"], done["skipped_count"]) == ("done", 1, 1)
    [skip] = [r for r in done["results"] if r["outcome"] == "skipped"]
    assert skip["id"] == held["id"]
    # Refused by the stage's access, as a single assign by Tech A would be.
    assert skip["params"].get("reason") == "stage_access", skip
    assert await _holders(world, a, planning, "release_engineer") == [str(a.tech_b)]
    assert await _holders(world, a, held, "release_engineer") == []  # never forced
    # The same as a single assign: the change is in the release's history.
    history = (await world.call("GET", f"{REL}/{planning['id']}/history", a, a.admin)).json()
    entries = history["items"] if isinstance(history, dict) else history
    fields = {c["field"] for e in entries for c in e.get("changes", [])}
    assert "role.release_engineer" in fields


async def test_assign_role_needs_a_role_and_someone_and_a_type_with_roles(world: World) -> None:
    a = world.a
    item = await a_release(world, a)
    for changes in ({"user_ids": [str(a.tech_a)]}, {"role": "release_engineer"}):
        refused = await world.call(
            "POST",
            f"{REL}/bulk",
            a,
            a.admin,
            json={"action": "assign_role", "changes": changes, "record_ids": [item["id"]]},
        )
        assert refused.status_code == 422, refused.text
    incident = await world.call(
        "POST",
        "/incidents",
        a,
        a.admin,
        json={"subject": "No roles here", "requester_id": str(a.requester)},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert incident.status_code == 201, incident.text
    wrong = await world.call(
        "POST",
        "/incidents/bulk",
        a,
        a.admin,
        json={
            "action": "assign_role",
            "changes": {"role": "release_engineer", "user_ids": [str(a.tech_a)]},
            "record_ids": [incident.json()["id"]],
        },
    )
    assert wrong.status_code == 422, wrong.text


async def test_req_rel_057_cancel_and_trash_work_on_releases(world: World) -> None:
    a = world.a
    first, second = await a_release(world, a), await a_release(world, a)
    canceled = await _bulk(world, a, "cancel", [first], reason_text="Not needed any more")
    assert (canceled["done_count"], canceled["skipped_count"]) == (1, 0), canceled
    got = (await world.call("GET", f"{REL}/{first['id']}", a, a.admin)).json()
    assert got["status"] == "closure_canceled"
    trashed = await _bulk(world, a, "delete", [second])
    assert trashed["done_count"] == 1, trashed
    assert (await world.call("GET", f"{REL}/{second['id']}", a, a.admin)).status_code == 404
    # Another tenant sees none of these jobs.
    b = world.b
    theirs = await world.call("GET", f"{REL}/bulk-jobs/{canceled['id']}", b, b.admin)
    assert theirs.status_code == 404
