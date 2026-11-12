"""A release's open work when it closes (WP-058b S4; REQ-REL-052).

- Its changes not closed yet and its open sub-releases are listed by name ("CHG-12 Subject"),
  through the shared open-work check (both kinds warn by default).
- Only open ones count; another type reports none of either.
"""

import uuid

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
