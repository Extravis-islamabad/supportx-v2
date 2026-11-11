"""A work item's save tells the audit sink which kind it is (WP-064; lane A's conditions).

Every work-item save writes history as `work_item`; work_items' resolver names the type from the
session's identity map, or with one read under RLS, and never fails a save.
"""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy import TenantContext
from app.modules.work_items.service.audit_subtype import work_item_subtype
from app.shared.history import SavedRecord, audit_sink, register_audit_sink
from tests.db.test_incidents_api import World, world
from tests.db.test_problems_api import new_problem

pytestmark = pytest.mark.db
__all__ = ["world"]  # the fixture, used by name


class Spy:
    """Records what each work-item save tells the sink, and writes nothing."""

    def __init__(self) -> None:
        self.seen: list[str | None] = []

    def handles(self, record_type: str, subtype: str | None) -> bool:
        if record_type == "work_item":
            self.seen.append(subtype)
        return False  # nothing is written

    async def saved(self, session: AsyncSession, record: SavedRecord) -> None:  # pragma: no cover
        del session, record


@pytest.fixture
def spy() -> Iterator[Spy]:
    previous = audit_sink()
    found = Spy()
    register_audit_sink(found)
    try:
        yield found
    finally:
        register_audit_sink(previous)


async def test_an_incident_and_a_problem_save_carry_their_own_subtype(
    world: World, spy: Spy
) -> None:
    a = world.a
    await world.create(a, a.admin)
    assert set(spy.seen) == {"incident"}
    spy.seen.clear()
    made = await new_problem(world, a, a.admin)
    assert made.status_code == 201, made.text
    assert set(spy.seen) == {"problem"}


async def test_the_fallback_reads_the_type_and_another_tenants_row_is_none(world: World) -> None:
    a, b = world.a, world.b
    item = await world.create(a, a.admin)
    record_id = uuid.UUID(item["id"])
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        session.expunge_all()  # not in the identity map: the one-column read
        assert await work_item_subtype(session, record_id) == "incident"
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        assert await work_item_subtype(session, record_id) is None  # RLS: not B's
        assert await work_item_subtype(session, uuid.uuid4()) is None
