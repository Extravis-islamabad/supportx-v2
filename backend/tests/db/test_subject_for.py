"""`identity_access.subject_for`: a user's scope for workers, the same as the API's (D-052).

Lane C's exports and scheduled reports run in the consumers worker, without the app's policy
service; they must decide exactly as the API would for the requesting user.
"""

import uuid
from collections.abc import AsyncIterator

import asyncpg
import pytest
import pytest_asyncio

from app.core.database import Database, create_engine
from app.core.modules import discover_modules
from app.core.tenancy import TenantContext
from app.main import create_app
from app.modules import licensing
from app.modules.identity_access import PolicyService, Subject, subject_for
from app.modules.licensing.service.entitlements import installed as licensing_installed
from conftest import make_settings
from tests.db.test_access_api import Org, make_org
from tooling.db_testing import ThrowawayDatabase

pytestmark = pytest.mark.db


@pytest_asyncio.fixture
async def api_policy(migrated_db: ThrowawayDatabase) -> AsyncIterator[PolicyService]:
    app = create_app(make_settings(database_url=migrated_db.app_url))
    async with app.router.lifespan_context(app):
        yield app.state.policy


async def _both(
    migrated_db: ThrowawayDatabase, policy: PolicyService, org: Org, user: uuid.UUID
) -> tuple[Subject, Subject]:
    database = Database(create_engine(migrated_db.app_url, application_name="test"))
    try:
        async with database.tenant_session(TenantContext(org.tenant, user)) as session:
            worker = await subject_for(session, org.tenant, user)
            api = await policy.compile(session, org.tenant, user)
    finally:
        await database.dispose()
    return worker, api


async def test_a_worker_gets_the_subject_the_api_compiles(
    migrated_db: ThrowawayDatabase, api_policy: PolicyService
) -> None:
    org = await make_org(migrated_db, "Subject For")
    for user in (org.admin, org.manager, org.tech, org.requester):
        worker, api = await _both(migrated_db, api_policy, org, user)
        assert worker == api
    worker, _ = await _both(migrated_db, api_policy, org, org.admin)
    assert worker.is_tenant_admin


async def test_a_deactivated_user_may_do_nothing(
    migrated_db: ThrowawayDatabase, api_policy: PolicyService
) -> None:
    """A scheduled report of someone who left returns nothing (lane C's request)."""
    org = await make_org(migrated_db, "Subject Gone")
    conn = await asyncpg.connect(migrated_db.admin_url)
    try:
        await conn.execute("UPDATE users SET status = 'disabled' WHERE id = $1", org.tech)
    finally:
        await conn.close()
    worker, api = await _both(migrated_db, api_policy, org, org.tech)
    assert worker == api
    assert not worker.grants
    unknown, _ = await _both(migrated_db, api_policy, org, uuid.uuid4())
    assert not unknown.grants


async def test_a_worker_without_the_app_compiles_with_the_plan_it_installed(
    migrated_db: ThrowawayDatabase,
) -> None:
    """The consumers worker has no app: it installs the entitlement service itself (lane C's
    e2e found every export failing with `entitlements_unavailable`)."""
    org = await make_org(migrated_db, "Subject Worker")
    settings = make_settings(database_url=migrated_db.app_url)
    database = Database(create_engine(migrated_db.app_url, application_name="test"))
    try:
        stop = await licensing.start_worker_service(settings, database, discover_modules())
        try:
            async with database.tenant_session(TenantContext(org.tenant, org.tech)) as session:
                worker = await subject_for(session, org.tenant, org.tech)
        finally:
            await stop()
        assert worker.holds("incidents.view")  # a feature-gated permission: the plan was read
        assert licensing_installed() is None
    finally:
        await database.dispose()
