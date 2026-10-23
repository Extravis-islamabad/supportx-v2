"""Entitlement service and cache without I/O: caching, invalidation races, rate-limit budgets."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import EntitlementRequired, LimitReached, ReadOnlyMode, ServiceUnavailable
from app.core.tenancy import TenantContext
from app.modules import licensing
from app.modules.licensing import (
    Edition,
    Entitlement,
    EntitlementService,
    EntitlementState,
    LimitKey,
    StaticProvider,
    Term,
)
from app.modules.licensing.infra.cache import NoCache, ValkeyEntitlementCache
from app.modules.licensing.service.entitlements import install, uninstall
from app.modules.licensing.service.gate import EntitlementRateLimits
from app.shared.api.ratelimit import SettingsPolicyProvider
from conftest import make_settings

NOW = datetime(2026, 10, 23, 12, tzinfo=UTC)
TENANT = uuid.uuid4()


class FakeValkey:
    """The four commands the cache uses, in memory."""

    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    async def mget(self, *keys: str) -> list[bytes | None]:
        return [self.data.get(key) for key in keys]

    async def set(self, key: str, value: str, ex: int) -> None:
        assert ex > 0
        self.data[key] = value.encode()

    async def incr(self, key: str) -> int:
        self.data[key] = str(int(self.data.get(key, b"0")) + 1).encode()
        return int(self.data[key])

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)


def plan(edition: Edition, **term: Any) -> Entitlement:  # noqa: ANN401
    return Entitlement.build(edition, term=Term(**{"starts_at": NOW - timedelta(days=1), **term}))


def service_with(provider: StaticProvider, client: FakeValkey) -> EntitlementService:
    cache = ValkeyEntitlementCache(client, prefix="t:", ttl_seconds=60)
    return EntitlementService(provider, cache=cache, clock=lambda: NOW)


async def test_feature_checks_and_errors() -> None:
    service = EntitlementService(StaticProvider({TENANT: plan(Edition.ESSENTIALS)}))
    assert await service.has_feature(TENANT, "incident")
    assert not await service.has_feature(TENANT, "change")
    await service.require_feature(TENANT, "incident")
    with pytest.raises(EntitlementRequired) as caught:
        await service.require_feature(TENANT, "change")
    assert caught.value.params == {"feature": "change"}


async def test_state_and_require_writable() -> None:
    expired = plan(Edition.ENTERPRISE, expires_at=NOW - timedelta(days=30), grace_days=14)
    service = EntitlementService(StaticProvider({TENANT: expired}), clock=lambda: NOW)
    assert (await service.current_state(TENANT)).state is EntitlementState.READ_ONLY
    with pytest.raises(ReadOnlyMode) as caught:
        await service.require_writable(TENANT)
    assert caught.value.params == {"reason": "expired"}


async def test_cache_serves_repeat_reads_and_invalidation_reloads() -> None:
    provider = StaticProvider({TENANT: plan(Edition.PROFESSIONAL)})
    service = service_with(provider, FakeValkey())
    for _ in range(3):
        assert (await service.entitlement(TENANT)).edition is Edition.PROFESSIONAL
    assert provider.loads == 1
    provider.entitlements[TENANT] = plan(Edition.ENTERPRISE)
    assert (await service.entitlement(TENANT)).edition is Edition.PROFESSIONAL  # still cached
    await service.invalidate(TENANT)
    assert (await service.entitlement(TENANT)).edition is Edition.ENTERPRISE
    assert provider.loads == 2


async def test_a_stale_write_after_invalidation_is_never_served() -> None:
    """Request A reads the old plan, the plan changes and the cache is invalidated, then A stores
    what it read: the stored entry carries the old generation and is ignored."""
    client = FakeValkey()
    cache = ValkeyEntitlementCache(client, prefix="t:", ttl_seconds=60)
    before = await cache.lookup(TENANT)
    old = plan(Edition.PROFESSIONAL)
    await cache.invalidate(TENANT)  # the plan changed meanwhile
    await cache.put(TENANT, old, before.generation)  # A's late write
    assert (await cache.lookup(TENANT)).entitlement is None
    fresh = await cache.lookup(TENANT)
    await cache.put(TENANT, plan(Edition.ENTERPRISE), fresh.generation)
    cached = (await cache.lookup(TENANT)).entitlement
    assert cached is not None
    assert cached.edition is Edition.ENTERPRISE


async def test_cache_is_per_tenant() -> None:
    other = uuid.uuid4()
    provider = StaticProvider({TENANT: plan(Edition.ENTERPRISE), other: plan(Edition.ESSENTIALS)})
    service = service_with(provider, FakeValkey())
    assert (await service.entitlement(TENANT)).edition is Edition.ENTERPRISE
    assert (await service.entitlement(other)).edition is Edition.ESSENTIALS
    await service.invalidate(other)
    assert provider.loads == 2
    await service.entitlement(TENANT)
    assert provider.loads == 2  # TENANT's entry survived other's invalidation


async def test_providers_that_hold_their_data_in_memory_skip_the_cache() -> None:
    provider = StaticProvider({TENANT: plan(Edition.ENTERPRISE)})
    provider.cacheable = False
    service = service_with(provider, FakeValkey())
    assert isinstance(service.cache, NoCache)


class BrokenValkey(FakeValkey):
    async def mget(self, *keys: str) -> list[bytes | None]:
        raise OSError(keys)

    async def set(self, key: str, value: str, ex: int) -> None:
        raise OSError(key, value, ex)


async def test_valkey_outage_falls_back_to_the_provider() -> None:
    provider = StaticProvider({TENANT: plan(Edition.ENTERPRISE)})
    service = service_with(provider, BrokenValkey())
    assert (await service.entitlement(TENANT)).edition is Edition.ENTERPRISE
    assert (await service.entitlement(TENANT)).edition is Edition.ENTERPRISE
    assert provider.loads == 2


@pytest.mark.parametrize(
    ("edition", "factor"),
    [(Edition.ESSENTIALS, 1), (Edition.PROFESSIONAL, 2), (Edition.ENTERPRISE, 4), (None, 1)],
)
async def test_rate_limit_budgets_scale_with_the_edition(
    edition: Edition | None, factor: int
) -> None:
    settings = make_settings(rate_limits={"default": {"user": 100, "tenant": 1000}})
    value = Entitlement.none() if edition is None else plan(edition)
    provider = EntitlementRateLimits(
        SettingsPolicyProvider(settings), EntitlementService(StaticProvider({TENANT: value}))
    )
    policy = await provider.policy_for("users", TENANT)
    assert (policy.user, policy.tenant) == (100 * factor, 1000 * factor)


class FakeSession:
    """Enough of AsyncSession for the limit functions: tenant context + a no-op execute."""

    def __init__(self, tenant: uuid.UUID, roles: frozenset[str] = frozenset()) -> None:
        self.info = {SESSION_TENANT_KEY: TenantContext(tenant, roles=roles)}
        self.statements = 0

    async def execute(self, statement: object) -> None:
        del statement
        self.statements += 1


async def test_module_functions_use_the_installed_service() -> None:
    entitled = plan(Edition.PROFESSIONAL)
    used = {"count": 1}

    async def count(session: Any) -> int:  # noqa: ANN401 - FakeSession stands in for AsyncSession
        del session
        return used["count"]

    service = EntitlementService(
        StaticProvider({TENANT: entitled}), counters={LimitKey.TECHNICIANS: count}
    )
    session: Any = FakeSession(TENANT, frozenset({"tenant_admin"}))
    install(service)
    try:
        assert await licensing.has_feature(TENANT, "change")
        await licensing.require_feature(TENANT, "change")
        assert (await licensing.current_state(TENANT)).state is EntitlementState.ACTIVE
        assert (await licensing.check_limit(session, LimitKey.TECHNICIANS)).allowed
        assert await licensing.remaining(session, LimitKey.TECHNICIANS) == 49  # 50 by default
        await licensing.hold_limit(session, LimitKey.TECHNICIANS)
        used["count"] = 50
        with pytest.raises(LimitReached) as caught:
            await licensing.reserve_capacity(session, LimitKey.TECHNICIANS)
        assert caught.value.instance_code == "limit_reached"
        assert caught.value.params == {"limit": "technicians", "max": 50}
        assert session.statements == 2  # two advisory locks: hold + reserve
        summary = await licensing.summary(session)
        assert summary.edition is Edition.PROFESSIONAL
        assert summary.admin_warning is False
    finally:
        uninstall(service)
    with pytest.raises(ServiceUnavailable) as missing:
        await licensing.has_feature(TENANT, "change")
    assert missing.value.instance_code == "entitlements_unavailable"


async def test_limit_functions_need_a_tenant_session() -> None:
    service = EntitlementService(StaticProvider())
    bare: Any = type("Bare", (), {"info": {}})()
    with pytest.raises(TypeError):
        await service.check_limit(bare, LimitKey.TECHNICIANS)
