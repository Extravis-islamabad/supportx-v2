"""work_items.records_requested_by (ADR-052; lane C's ai erasure port): IDs only, batched."""

import uuid

from app.core.database import Database, create_engine
from app.core.tenancy import TenantContext
from app.modules.work_items import records_requested_by
from tests.db.test_incidents_api import World, world  # noqa: F401 - the fixture


async def test_requested_and_on_behalf_records_deleted_ones_included_paged(
    world: World,  # noqa: F811 - the fixture's name
) -> None:
    a = world.a
    asked = [await world.create(a, a.admin, requester_id=str(a.requester)) for _ in range(3)]
    for_them = await world.create(a, a.admin, on_behalf_of_id=str(a.requester))
    not_theirs = await world.create(a, a.admin, requester_id=str(a.tech_b))
    await world.sql(
        "UPDATE work_items SET deleted_at = now() WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(asked[0]["id"]),
    )
    database = Database(create_engine(world.db.app_url, application_name="test"))
    try:
        async with database.tenant_session(TenantContext(a.tenant)) as session:
            first, cursor = await records_requested_by(session, a.requester, limit=2)
            assert len(first) == 2
            assert cursor is not None
            rest, end = await records_requested_by(session, a.requester, cursor=cursor, limit=2)
            assert end is None
        async with database.tenant_session(TenantContext(world.b.tenant)) as other:
            assert await records_requested_by(other, a.requester) == ([], None)
    finally:
        await database.dispose()
    found = {str(i) for _, i in first + rest}
    assert found == {*(r["id"] for r in asked), for_them["id"]}
    assert not_theirs["id"] not in found
    assert {t for t, _ in first + rest} == {"incident"}
