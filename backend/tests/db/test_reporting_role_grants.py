"""Every reportable entity can be read by the reporting role (lane C found #310's 500).

Reports run as supportx_report (SET LOCAL ROLE, ADR-033), which reads only the tables a
migration grants it. A module that registers a reporting source but forgets the grant answers
500 on every report of it. This guard runs each registered source's own list query in a report
session, as an admin (the widest query), so a missing grant on any table it reads fails here.
The source itself is built in the app's session, as analytics builds it; only its rows run as
the reporting role.
"""

import pytest
from sqlalchemy import func, select

from app.core.tenancy import TenantContext
from app.modules.identity_access import subject_for
from app.shared.reporting import provider_for, registered_entities
from tests.db.test_assets_api import _add, _product
from tests.db.test_incidents_api import World, world

pytestmark = pytest.mark.db
__all__ = ["world"]  # the fixture, used by name


async def test_every_reportable_entity_is_readable_by_the_reporting_role(world: World) -> None:
    a = world.a
    entities = registered_entities()
    assert "asset" in entities  # the source that lacked its grant
    database = world.app.state.db
    for entity in entities:
        provider = provider_for(entity)
        # As analytics does: the source in the app's session, its rows as the reporting role.
        async with database.tenant_session(TenantContext(a.tenant, a.admin)) as session:
            subject = await subject_for(session, a.tenant, a.admin)
            source = await provider.source(session, subject)
        async with database.reporting_session(
            TenantContext(a.tenant, a.admin), timeout_seconds=30
        ) as report:
            counted = await report.scalar(select(func.count()).select_from(source.rows.subquery()))
        assert counted is not None, entity


async def test_an_asset_report_counts_assets_as_the_reporting_role(world: World) -> None:
    a = world.a
    laptop = await _product(world, a, "laptop", "Reported laptop")
    assert (await _add(world, a, {"name": "Reported", "product_id": laptop})).status_code == 201
    database = world.app.state.db
    async with database.tenant_session(TenantContext(a.tenant, a.admin)) as session:
        subject = await subject_for(session, a.tenant, a.admin)
        source = await provider_for("asset").source(session, subject)
    async with database.reporting_session(
        TenantContext(a.tenant, a.admin), timeout_seconds=30
    ) as report:
        counted = await report.scalar(select(func.count()).select_from(source.rows.subquery()))
    assert counted is not None
    assert counted >= 1
