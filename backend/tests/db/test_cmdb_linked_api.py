"""A CI's linked work items: the Associations tab's API (WP-053 S5c; REQ-CMDB-019).

The counts come from work items' real OpenCountsPort (visible-only, D-158): a person who may see
the CI but no incidents is never told an incident is linked, not even as a number (the
coordinator's condition). The page goes through the `CiLinkedRecords` port that work items
register (lane A's adapter, with its own visible-only test); here a stand-in records the call,
so the route, the CI's read check and "not available" are pinned.
"""

import uuid
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from typing import Any

import pytest

from app.modules.cmdb.service.linked import (
    CiLinkedRecord,
    clear_ci_linked_records,
    linked_records_port,
    register_ci_linked_records,
)
from app.modules.identity_access import Subject
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_cmdb_relationships import _given
from tests.db.test_incidents_api import Org, World, problem
from tests.db.test_users_api import seed_users
from tests.db.test_work_item_cis_api import _a_ci

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the fixtures, used by name

CMDB = "/cmdb"


class _StandIn:
    """Records what the CMDB asks for; lane A's adapter answers for real."""

    def __init__(self) -> None:
        self.asked: list[tuple[uuid.UUID, str, str | None, int]] = []

    async def linked_page(
        self,
        session: Any,  # noqa: ANN401 - unused
        subject: Subject,
        ci_id: uuid.UUID,
        kind: str,
        *,
        cursor: str | None = None,
        limit: int = 25,
    ) -> tuple[Sequence[CiLinkedRecord], str | None]:
        del session, subject
        self.asked.append((ci_id, kind, cursor, limit))
        row = CiLinkedRecord(
            id=uuid.uuid4(), kind=kind, display_id="INC-1", subject="Disk full",
            status="open", open=True, updated_at=datetime.now(UTC),
        )  # fmt: skip
        return [row], "next-page"

    async def ci_ids_of(self, session: Any, work_item_id: uuid.UUID) -> list[uuid.UUID]:  # noqa: ANN401 - unused
        del session, work_item_id
        return []


@pytest.fixture
def stand_in() -> Iterator[_StandIn]:
    before = linked_records_port()
    port = _StandIn()
    register_ci_linked_records(port)
    try:
        yield port
    finally:
        clear_ci_linked_records()
        if before is not None:
            register_ci_linked_records(before)


async def _cmdb_viewer_without_incidents(world: World, org: Org) -> uuid.UUID:
    [person] = await seed_users(world.db, org.tenant, [{"user_type": "technician"}])
    await _given(world, org, person, f"CMDB only {uuid.uuid4().hex[:6]}", [("cmdb.view", "all")])
    return person


async def test_the_counts_are_visible_only_so_an_unseen_incident_is_never_counted(
    world: World, stand_in: _StandIn
) -> None:
    """The coordinator's S5c condition (D-158): no count reveals a record the reader can't see."""
    del stand_in
    a = world.a
    ci = await _a_ci(world, a, f"Linked host {uuid.uuid4().hex[:6]}")
    await world.create(a, a.admin, ci_ids=[ci["id"]])
    path = f"{CMDB}/cis/{ci['id']}/linked"
    seen = await world.call("GET", path, a, a.admin)
    assert seen.status_code == 200, seen.text
    kinds = {k["kind"]: k for k in seen.json()["kinds"]}
    assert (kinds["incident"]["open"], kinds["incident"]["total"]) == (1, 1)
    assert set(kinds) == {"incident", "service_request", "problem", "change", "release"}
    viewer = await _cmdb_viewer_without_incidents(world, a)
    blind = await world.call("GET", path, a, viewer)
    assert blind.status_code == 200, blind.text  # they may see the CI ...
    incident = next(k for k in blind.json()["kinds"] if k["kind"] == "incident")
    assert (incident["open"], incident["total"]) == (0, 0)  # ... but not that an incident exists


async def test_the_page_goes_through_the_port_after_the_cis_own_read_check(
    world: World, stand_in: _StandIn
) -> None:
    a = world.a
    ci = await _a_ci(world, a, f"Paged host {uuid.uuid4().hex[:6]}")
    page = await world.call(
        "GET", f"{CMDB}/cis/{ci['id']}/linked/incident", a, a.admin, params={"limit": 500}
    )
    assert page.status_code == 422, page.text  # above the cap: refused by the route
    page = await world.call(
        "GET", f"{CMDB}/cis/{ci['id']}/linked/incident", a, a.admin, params={"limit": 10}
    )
    assert page.status_code == 200, page.text
    assert page.json()["next_cursor"] == "next-page"
    assert [i["display_id"] for i in page.json()["items"]] == ["INC-1"]
    assert stand_in.asked[-1] == (uuid.UUID(ci["id"]), "incident", None, 10)
    bad = await world.call("GET", f"{CMDB}/cis/{ci['id']}/linked/not_a_type", a, a.admin)
    assert bad.status_code == 422, bad.text
    asked_before = len(stand_in.asked)
    unseen = await world.call("GET", f"{CMDB}/cis/{uuid.uuid4()}/linked/incident", a, a.admin)
    assert problem(unseen)[1] == "cmdb_ci_not_found"
    assert len(stand_in.asked) == asked_before  # an unseen CI never reaches the port
    other = await world.call("GET", f"{CMDB}/cis/{ci['id']}/linked", world.b, world.b.admin)
    assert problem(other)[1] == "cmdb_ci_not_found"  # tenant B never reads A's CI


async def test_without_work_items_port_both_say_not_available(world: World) -> None:
    a = world.a
    ci = await _a_ci(world, a, f"Portless host {uuid.uuid4().hex[:6]}")
    before = linked_records_port()
    clear_ci_linked_records()
    try:
        for path in (f"{CMDB}/cis/{ci['id']}/linked", f"{CMDB}/cis/{ci['id']}/linked/incident"):
            gone = await world.call("GET", path, a, a.admin)
            assert problem(gone)[1] == "linked_records_not_available", path
    finally:
        if before is not None:
            register_ci_linked_records(before)
