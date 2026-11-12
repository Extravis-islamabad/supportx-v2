"""A release's open work when it closes (WP-058b S4; REQ-REL-052).

- Its changes not closed yet and its open sub-releases are listed by name ("CHG-12 Subject"),
  through the shared open-work check (both kinds warn by default).
- Only open ones count; another type reports none of either.
"""

import uuid

import asyncpg

from app.core.tenancy import TenantContext
from app.modules.work_items.domain.closure import OPEN_WORK_DEFAULTS, OpenWorkKind, OpenWorkMode
from app.modules.work_items.infra.models import WorkItem
from app.modules.work_items.service import release_closing
from tests.db.test_changes_api import new_change
from tests.db.test_incidents_api import CONSOLE, World, world
from tests.db.test_release_links_api import set_parent
from tests.db.test_releases_api import REL, a_release

__all__ = ["world"]  # the fixture, re-used


async def _record(world: World, item_id: str) -> WorkItem:
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        found: WorkItem | None = await session.get(WorkItem, uuid.UUID(item_id))
        assert found is not None
        session.expunge(found)
        return found


async def _open(world: World, item_id: str) -> tuple[list[str], list[str]]:
    record = await _record(world, item_id)
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        changes = await release_closing.open_linked_changes(session, record)
        subs = await release_closing.open_sub_releases(session, record)
    return [i.title for i in changes], [i.title for i in subs]


def test_both_kinds_warn_by_default() -> None:
    assert OPEN_WORK_DEFAULTS[OpenWorkKind.LINKED_CHANGES] is OpenWorkMode.WARN
    assert OPEN_WORK_DEFAULTS[OpenWorkKind.CHILD_RELEASES] is OpenWorkMode.WARN


async def test_req_rel_052_a_release_lists_its_open_changes_and_sub_releases(
    world: World,
) -> None:
    a = world.a
    release = await a_release(world, a)
    made = await new_change(world, a, a.admin)
    assert made.status_code == 201, made.text
    change = made.json()
    added = await world.call(
        "POST",
        f"{REL}/{release['id']}/changes",
        a,
        a.admin,
        json={"change_id": change["id"]},
        headers=CONSOLE,
    )
    assert added.status_code in {200, 201, 204}, added.text
    sub = await a_release(world, a)
    parented = await set_parent(world, a, sub, uuid.UUID(release["id"]))
    assert parented.status_code in {200, 204}, parented.text

    changes, subs = await _open(world, release["id"])
    assert changes == [f"{change['display_id']} {change['subject']}"]
    assert subs == [f"{sub['display_id']} {sub['subject']}"]
    # The change itself has neither kind: only releases report them.
    assert await _open(world, change["id"]) == ([], [])


async def test_req_rel_053_ac3_the_failed_view_lists_failed_and_rolled_back_releases(
    world: World,
) -> None:
    a = world.a
    failed = await a_release(world, a)
    rolled = await a_release(world, a)
    running = await a_release(world, a)
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        for item, status in ((failed, "deployment_failed"), (rolled, "deployment_rolled_back")):
            await conn.execute(
                "UPDATE work_items SET status = $3, stage = 'deployment'"
                " WHERE tenant_id = $1 AND id = $2",
                a.tenant,
                uuid.UUID(item["id"]),
                status,
            )
    finally:
        await conn.close()
    listed = await world.call("GET", REL, a, a.admin, params={"view": "failed"})
    assert listed.status_code == 200, listed.text
    ids = {row["id"] for row in listed.json()["items"]}
    assert {failed["id"], rolled["id"]} <= ids
    assert running["id"] not in ids


async def _fail(world: World, item: dict[str, object]) -> None:
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        await conn.execute(
            "UPDATE work_items SET status = 'deployment_failed', stage = 'deployment'"
            " WHERE tenant_id = $1 AND id = $2",
            world.a.tenant,
            uuid.UUID(str(item["id"])),
        )
    finally:
        await conn.close()


async def test_req_rel_053_ac2_a_failed_release_makes_its_problem_and_follow_up(
    world: World,
) -> None:
    a = world.a
    release = await a_release(world, a)
    early = await world.call(
        "POST",
        f"{REL}/{release['id']}/follow-ups",
        a,
        a.admin,
        json={"kind": "problem", "subject": "Why did it fail?"},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert early.status_code == 409, early.text
    assert early.json()["code"] == "release_not_failed"

    await _fail(world, release)
    problem = await world.call(
        "POST",
        f"{REL}/{release['id']}/follow-ups",
        a,
        a.admin,
        json={"kind": "problem", "subject": "Why did it fail?"},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert problem.status_code == 201, problem.text
    assert (problem.json()["type"], problem.json()["relation"]) == ("problem", "caused_problem")
    again = await world.call(
        "POST",
        f"{REL}/{release['id']}/follow-ups",
        a,
        a.admin,
        json={"kind": "release", "subject": "Payroll 4.2.1"},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert again.status_code == 201, again.text
    assert again.json()["relation"] == "follow_up_release"

    listed = await world.call("GET", f"{REL}/{release['id']}/follow-ups", a, a.admin)
    assert [(f["display_id"], f["relation"]) for f in listed.json()] == [
        (problem.json()["display_id"], "caused_problem"),
        (again.json()["display_id"], "follow_up_release"),
    ]
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        kinds = {
            r["kind"]
            for r in await conn.fetch(
                "SELECT kind FROM work_item_links WHERE tenant_id = $1 AND target_id = $2",
                a.tenant,
                uuid.UUID(release["id"]),
            )
        }
    finally:
        await conn.close()
    assert {"caused_by_release", "follows"} <= kinds
    # Another tenant sees nothing of it.
    b = world.b
    theirs = await world.call("GET", f"{REL}/{release['id']}/follow-ups", b, b.admin)
    assert theirs.status_code == 404
