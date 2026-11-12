"""Field definitions are read once per transaction, and never outlive it (lane A, WP-046a).

One save reads an entity's definitions several times (clean, problem params, search text,
filters); each read was a query. They are now memoised in the session until its transaction
ends, and every write of the entity's fields drops the memo, so the transaction that writes a
field sees it at once and the next transaction always reads again.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.tenancy import TenantContext
from app.modules.metadata.service.custom_fields import create_field, definitions, list_fields
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import World

pytestmark = MODULE_LOOP
__all__ = ["module_world", "shared_world"]  # the fixture, re-used


@contextmanager
def field_reads(engine: AsyncEngine) -> Iterator[list[str]]:
    """The statements that read the custom_fields table while the block runs."""
    seen: list[str] = []

    def note(*args: Any) -> None:  # noqa: ANN401 - SQLAlchemy's cursor hook signature
        statement = str(args[2])
        if statement.lstrip().upper().startswith("SELECT") and "FROM custom_fields" in statement:
            seen.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", note)
    try:
        yield seen
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", note)


async def test_three_reads_in_one_transaction_are_one_query(world: World) -> None:
    db = world.app.state.db
    with field_reads(db.engine) as reads:
        async with db.tenant_session(TenantContext(world.a.tenant)) as session:
            first = await definitions(session, "incident")
            second = await definitions(session, "incident")
            third = await definitions(session, "incident")
            first.clear()  # each caller gets its own copy: the memo is untouched
            fourth = await definitions(session, "incident")
    assert len(reads) == 1
    assert second == third == fourth


async def test_a_write_is_seen_in_the_same_transaction(world: World) -> None:
    db = world.app.state.db
    async with db.tenant_session(TenantContext(world.a.tenant, world.a.admin)) as session:
        before = await definitions(session, "incident")
        rows_before = await list_fields(session, "incident")
        made = await create_field(
            session,
            "incident",
            {"field_type": "text", "labels": {"en": "Memo probe", "ar": "مسبار"}},
            source="api",
        )
        after = await definitions(session, "incident")
        assert made.key not in before
        assert made.key in after
        assert made.id in {r.id for r in await list_fields(session, "incident")}
        assert len(await list_fields(session, "incident")) == len(rows_before) + 1


async def test_a_new_transaction_reads_again(world: World) -> None:
    db = world.app.state.db
    with field_reads(db.engine) as reads:
        async with db.tenant_session(TenantContext(world.a.tenant)) as session:
            await definitions(session, "incident")
        async with db.tenant_session(TenantContext(world.a.tenant)) as session:
            await definitions(session, "incident")
    assert len(reads) == 2


async def test_a_rolled_back_savepoint_drops_what_it_saw(world: World) -> None:
    db = world.app.state.db
    async with db.tenant_session(TenantContext(world.a.tenant, world.a.admin)) as session:
        savepoint = await session.begin_nested()
        made = await create_field(
            session,
            "incident",
            {"field_type": "text", "labels": {"en": "Rolled back probe", "ar": "مسبار"}},
            source="api",
        )
        assert made.key in await definitions(session, "incident")
        await savepoint.rollback()
        assert made.key not in await definitions(session, "incident")
