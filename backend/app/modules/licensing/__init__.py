"""Licensing module: the entitlement interface (architecture.md §13; WP-009; CLAUDE.md rule f).

The ONLY place that knows where licence data comes from. Everything else asks through:

    has_feature(tenant_id, feature)          require_feature(tenant_id, feature)
    check_limit(session, limit, adding)      remaining(session, limit)
    reserve_capacity(session, limit, ...)    current_state(tenant_id)      summary(session)

and modules declare their feature in their ModuleSpec (`feature="change"`), which gates all
their routes automatically (app/core/entitlements.py). See docs/architecture/entitlements.md.

The provider is configuration (SUPPORTX_ENTITLEMENT_PROVIDER), resolved here and nowhere else.
"""

import uuid
from typing import TYPE_CHECKING

import valkey.asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import AUTHORIZER_STATE, Authorizer, PermissionSpec
from app.core.entitlements import ENTITLEMENT_GATE_STATE
from app.core.errors import ServiceUnavailable
from app.core.logging import get_logger
from app.core.modules import ModuleRegistry, ModuleSpec, UsageCounter
from app.core.tenancy import TenantContext
from app.modules.licensing.api.routes import router
from app.modules.licensing.domain.catalogue import Edition, Feature, LimitKey, unknown_features
from app.modules.licensing.domain.entitlement import (
    Entitlement,
    EntitlementState,
    LimitCheck,
    Status,
    Term,
)
from app.modules.licensing.domain.licence import LicenceRejectedError
from app.modules.licensing.events import EVENTS
from app.modules.licensing.infra.cache import EntitlementCache, NoCache, ValkeyEntitlementCache
from app.modules.licensing.infra.providers import (
    DevLicenceVerifier,
    LicenceFileProvider,
    NoInstallationCheck,
    StaticProvider,
    SubscriptionProvider,
)
from app.modules.licensing.service.cache_consumer import CACHE_INVALIDATION
from app.modules.licensing.service.entitlements import (
    EntitlementService,
    Summary,
    install,
    installed,
    uninstall,
)
from app.modules.licensing.service.gate import EntitlementRateLimits, RouteGate
from app.modules.licensing.service.ports import EntitlementProvider
from app.modules.licensing.service.realtime import ROUTES as REALTIME_ROUTES
from app.modules.licensing.service.subscriptions import (
    SubscriptionPlan,
    apply_subscription,
    current_subscription,
)
from app.shared.api.ratelimit import RATE_LIMITER_STATE, RateLimiter

if TYPE_CHECKING:
    from app.core.config import Settings
    from app.core.database import Database

log = get_logger(__name__)


class ModuleFeatureError(RuntimeError):
    """A module declares a feature or usage counter the catalogue does not know."""


def build_provider(settings: "Settings", database: "Database | None") -> EntitlementProvider | None:
    """The configured provider; None when it cannot run here (no database for subscriptions).

    Raises LicenceRejectedError for an unusable licence file: startup then fails (§13.6).
    """
    if settings.entitlement_provider == "licence_file":
        if settings.licence_file is None:  # pragma: no cover - rejected by Settings validation
            raise LicenceRejectedError(
                reason="licence_unreadable", detail="SUPPORTX_LICENCE_FILE is not set"
            )
        return LicenceFileProvider(
            settings.licence_file,
            # WP-013 hook: the licence-core verifier and installation check replace these two.
            verifier=DevLicenceVerifier(allow_unsigned=settings.profile in {"dev", "test"}),
            installation=NoInstallationCheck(),
        )
    return None if database is None else SubscriptionProvider(database)


def validate_registry(registry: ModuleRegistry) -> dict[LimitKey, UsageCounter]:
    """Check every module's feature and counters against the catalogue; collect the counters."""
    counters: dict[LimitKey, UsageCounter] = {}
    for spec in registry.modules:
        declared = {f for f in (spec.feature, *spec.router_features) if f is not None}
        if declared and unknown_features(declared):
            msg = f"module {spec.name!r} declares unknown features {sorted(declared)!r}"
            raise ModuleFeatureError(msg)
        for key, counter in spec.usage_counters.items():
            if key not in {limit.value for limit in LimitKey}:
                msg = f"module {spec.name!r} counts unknown limit {key!r}"
                raise ModuleFeatureError(msg)
            if LimitKey(key) in counters:
                msg = f"limit {key!r} is counted by more than one module"
                raise ModuleFeatureError(msg)
            counters[LimitKey(key)] = counter
    return counters


async def _startup(app: FastAPI) -> None:
    settings: Settings = app.state.settings
    app.state.entitlements = None
    setattr(app.state, ENTITLEMENT_GATE_STATE, None)
    counters = validate_registry(app.state.modules)
    try:
        provider = build_provider(settings, app.state.db)
    except LicenceRejectedError as exc:
        log.error("licence_rejected", reason=exc.reason)  # noqa: TRY400 - reason only, no trace
        raise
    if provider is None:
        log.warning("entitlements_unavailable", reason="no_database")
        return
    cache: EntitlementCache = NoCache()
    client = None
    if settings.valkey_url is not None and settings.entitlement_cache_ttl_seconds > 0:
        client = valkey.asyncio.from_url(settings.valkey_url.get_secret_value())  # type: ignore[no-untyped-call]  # valkey-py ships no annotation for from_url
        cache = ValkeyEntitlementCache(
            client,
            prefix=settings.valkey_key_prefix,
            ttl_seconds=settings.entitlement_cache_ttl_seconds,
        )
    service = EntitlementService(provider, cache=cache, counters=counters)
    start_service(app, service)
    app.state.entitlement_clients = client


def start_service(app: FastAPI, service: EntitlementService) -> None:
    """Install `service` for this app: route gate, rate-limit budgets, module functions.

    Tests call this after startup to swap in a StaticProvider-backed service.
    """

    async def is_admin(context: TenantContext) -> bool:
        authorizer: Authorizer | None = getattr(app.state, AUTHORIZER_STATE, None)
        return authorizer is not None and await authorizer.allows(context, "licence.manage")

    app.state.entitlements = service
    setattr(app.state, ENTITLEMENT_GATE_STATE, RouteGate(service, is_admin))
    limiter: RateLimiter | None = getattr(app.state, RATE_LIMITER_STATE, None)
    if limiter is not None:
        base = limiter.provider
        if isinstance(base, EntitlementRateLimits):
            base = base.base
        limiter.provider = EntitlementRateLimits(base, service)
    install(service)


async def _shutdown(app: FastAPI) -> None:
    service = getattr(app.state, "entitlements", None)
    if service is not None:
        uninstall(service)
    client = getattr(app.state, "entitlement_clients", None)
    if client is not None:
        await client.aclose()


# --- public interface for other modules ----------------------------------------------------------


def _service() -> EntitlementService:
    service = installed()
    if service is None:
        raise ServiceUnavailable(code="entitlements_unavailable")
    return service


async def has_feature(tenant_id: uuid.UUID, feature: Feature | str) -> bool:
    """Whether the tenant's plan includes `feature`."""
    return await _service().has_feature(tenant_id, feature)


async def require_feature(tenant_id: uuid.UUID, feature: Feature | str) -> None:
    """403 `entitlement_required` unless the plan includes `feature`."""
    await _service().require_feature(tenant_id, feature)


async def current_state(tenant_id: uuid.UUID) -> Status:
    """Licence state (active / grace / read_only / invalid) right now."""
    return await _service().current_state(tenant_id)


async def check_limit(session: AsyncSession, limit: LimitKey, adding: int = 1) -> LimitCheck:
    """Whether `adding` more fit (advisory only; use `reserve_capacity` before adding)."""
    return await _service().check_limit(session, limit, adding)


async def remaining(session: AsyncSession, limit: LimitKey) -> int | None:
    """How many more fit; None = unlimited."""
    return await _service().remaining(session, limit)


async def hold_limit(session: AsyncSession, limit: LimitKey) -> None:
    """Serialise additions to `limit` for the session's tenant until the transaction ends."""
    await _service().hold(session, limit)


async def reserve_capacity(
    session: AsyncSession, limit: LimitKey, adding: int = 1, *, code: str | None = None
) -> LimitCheck:
    """Race-safe check before adding counted records in this transaction (403 when full)."""
    return await _service().reserve(session, limit, adding, code=code)


async def summary(session: AsyncSession, *, show_usage: bool, is_admin: bool) -> Summary:
    """Edition, features, limits with usage, state and term."""
    return await _service().summary(session, show_usage=show_usage, is_admin=is_admin)


async def entitled_features(
    tenant_id: uuid.UUID, session: AsyncSession | None = None
) -> frozenset[str]:
    """Feature keys the tenant's plan includes (for compiling permissions, WP-016)."""
    entitlement = await _service().entitlement(tenant_id, session)
    return frozenset(str(f) for f in entitlement.features)


module = ModuleSpec(
    name="licensing",
    routers=[router],
    on_startup=[_startup],
    on_shutdown=[_shutdown],
    events=EVENTS,
    consumers=[CACHE_INVALIDATION],
    realtime=REALTIME_ROUTES,
    # Who sees licence warnings (and, later, imports licences).
    permissions=[PermissionSpec("licence.manage")],
)

__all__ = [
    "Edition",
    "Entitlement",
    "EntitlementService",
    "EntitlementState",
    "Feature",
    "LimitCheck",
    "LimitKey",
    "StaticProvider",
    "Status",
    "SubscriptionPlan",
    "Term",
    "apply_subscription",
    "check_limit",
    "current_state",
    "current_subscription",
    "entitled_features",
    "has_feature",
    "hold_limit",
    "module",
    "remaining",
    "require_feature",
    "reserve_capacity",
    "start_service",
    "summary",
]
