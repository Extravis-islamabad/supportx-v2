"""A plan change reaches every API's entitlement cache through the event bus (WP-009).

Full path on real PostgreSQL, NATS JetStream and Valkey: the subscription row and
`licensing.entitlement.changed` commit together (outbox), the relay publishes the event, the
licensing consumer bumps the tenant's cache generation, and the next read sees the new plan.
Keys use a random prefix and are deleted afterwards (CLAUDE.md rule h).
"""

import secrets
import uuid
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
import valkey.asyncio

from app.core.database import Database, create_engine
from app.core.tenancy import TenantContext
from app.modules.licensing import (
    Edition,
    EntitlementService,
    SubscriptionPlan,
    apply_subscription,
    current_subscription,
)
from app.modules.licensing.infra.cache import ValkeyEntitlementCache, generation_key
from app.modules.licensing.infra.providers import SubscriptionProvider
from app.modules.licensing.service.cache_consumer import CACHE_INVALIDATION, handler
from conftest import create_tenant, make_settings
from tests.db.test_rate_limit import valkey_url
from tests.events.conftest import RelayFactory, RunnerFactory, outbox_rows, run_until
from tests.events.test_consumers import publish_all
from tooling.db_testing import ThrowawayDatabase

pytestmark = [pytest.mark.db, pytest.mark.valkey]


@pytest_asyncio.fixture
async def valkey_prefixed() -> AsyncIterator[tuple[Any, str, str]]:
    """(client, url, prefix); deletes every key under the prefix afterwards."""
    url = valkey_url()
    if url is None:
        pytest.skip("Valkey is not configured")
    client: Any = valkey.asyncio.from_url(url)  # type: ignore[no-untyped-call]  # valkey-py ships no hints
    prefix = f"test-{secrets.token_hex(6)}:"
    try:
        await client.ping()
    except OSError:
        pytest.skip("Valkey is not reachable")
    yield client, url, prefix
    keys = [key async for key in client.scan_iter(match=f"{prefix}*")]
    if keys:
        await client.delete(*keys)
    await client.aclose()


async def change_plan(migrator_url: str, tenant: uuid.UUID, edition: Edition) -> list[str]:
    """What platform tooling does (make dev-subscription): row + event in one transaction."""
    database = Database(create_engine(migrator_url, application_name="tests", use_null_pool=True))
    try:
        async with database.tenant_session(TenantContext(tenant)) as session:
            current = await current_subscription(session)
            assert current is not None
            return await apply_subscription(session, replace(current, edition=edition))
    finally:
        await database.dispose()


async def test_plan_change_invalidates_the_cache_through_the_bus(
    migrated_db: ThrowawayDatabase,
    app_db: Database,
    make_relay: RelayFactory,
    make_runner: RunnerFactory,
    valkey_prefixed: tuple[Any, str, str],
) -> None:
    client, url, prefix = valkey_prefixed
    tenant = await create_tenant(migrated_db.migrator_url, "Upgrade", edition="professional")
    cache = ValkeyEntitlementCache(client, prefix=prefix, ttl_seconds=300)
    service = EntitlementService(SubscriptionProvider(app_db), cache=cache)
    assert (await service.entitlement(tenant)).edition is Edition.PROFESSIONAL

    assert await change_plan(migrated_db.migrator_url, tenant, Edition.ENTERPRISE) == ["edition"]
    (row,) = [r for r in await outbox_rows(migrated_db.admin_url) if r["tenant_id"] == tenant]
    assert row["event_type"] == "licensing.entitlement.changed"
    # Until the event arrives the cached plan is served: the cache is really in use.
    assert (await service.entitlement(tenant)).edition is Edition.PROFESSIONAL

    settings = make_settings(valkey_url=url, valkey_key_prefix=prefix)
    spec = replace(CACHE_INVALIDATION, handler=handler(lambda: settings))
    runner = make_runner(spec)
    await publish_all(make_relay)

    async def invalidated() -> bool:
        return await client.get(generation_key(prefix, tenant)) is not None

    await run_until([runner.run], invalidated)
    assert (await service.entitlement(tenant)).edition is Edition.ENTERPRISE


async def test_unchanged_plan_records_no_event(migrated_db: ThrowawayDatabase) -> None:
    tenant = await create_tenant(migrated_db.migrator_url, "Same", edition="professional")
    assert await change_plan(migrated_db.migrator_url, tenant, Edition.PROFESSIONAL) == []
    assert not [r for r in await outbox_rows(migrated_db.admin_url) if r["tenant_id"] == tenant]


async def test_new_subscription_records_every_field(migrated_db: ThrowawayDatabase) -> None:
    tenant = await create_tenant(migrated_db.migrator_url, "Fresh", edition=None)
    plan = SubscriptionPlan(
        edition=Edition.ESSENTIALS, starts_at=datetime.now(UTC) - timedelta(days=1)
    )
    database = Database(
        create_engine(migrated_db.migrator_url, application_name="tests", use_null_pool=True)
    )
    try:
        async with database.tenant_session(TenantContext(tenant)) as session:
            changed = await apply_subscription(session, plan)
        async with database.tenant_session(TenantContext(tenant)) as session:
            again = await apply_subscription(session, plan, only_if_absent=True)
    finally:
        await database.dispose()
    assert "edition" in changed
    assert again == []
    (row,) = [r for r in await outbox_rows(migrated_db.admin_url) if r["tenant_id"] == tenant]
    assert row["event_type"] == "licensing.entitlement.changed"
