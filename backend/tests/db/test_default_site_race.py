"""Two first reads of a tenant's sites at once share one default site (e2e, 2026-11-09).

`default_site` makes "Main site" on first need. Two requests doing so together both inserted
it; the second hit the unique name and answered 500 on a GET. Now the second waits for the
first and takes its row, in a transaction that stays usable.
"""

import asyncio

import pytest
from sqlalchemy import func, select

from app.core.database import Database, create_engine
from app.core.tenancy import TenantContext
from app.modules.organization.infra.models import Site
from app.modules.organization.service.structure import default_site, list_sites
from conftest import create_tenant
from tooling.db_testing import ThrowawayDatabase

pytestmark = pytest.mark.db


async def test_two_first_reads_at_once_share_one_default_site(
    migrated_db: ThrowawayDatabase,
) -> None:
    tenant = await create_tenant(migrated_db.migrator_url, "Race")
    engine = create_engine(migrated_db.app_url, application_name="test-default-site")
    db = Database(engine)
    context = TenantContext(tenant)
    try:
        started = asyncio.Event()

        async def second() -> Site:
            started.set()
            async with db.tenant_session(context) as session:
                site = await default_site(session)  # waits on the first one's insert
                assert [s.id for s in await list_sites(session)] == [site.id]  # still usable
                return site

        async with db.tenant_session(context) as session:
            first = await default_site(session)
            task = asyncio.create_task(second())
            await started.wait()
            await asyncio.sleep(0.5)  # the second is now blocked on the unique name
        other = await task
        assert other.id == first.id
        async with db.tenant_session(context) as session:
            assert await session.scalar(select(func.count()).select_from(Site)) == 1
    finally:
        await engine.dispose()
