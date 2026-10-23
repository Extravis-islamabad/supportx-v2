"""The entitlement service: the one interface every module uses (architecture.md §13.1; WP-009).

    has_feature / require_feature   is a feature in the tenant's plan?
    check_limit / remaining         counted limits against live usage
    reserve                         race-safe "add one more" for counted limits
    current_state / require_writable  active, grace, read_only, invalid (§13.6)
    summary                         everything GET /api/v1/entitlements shows

Entitlements come from the configured provider through the per-tenant cache. The state is derived
from the term at call time (domain/entitlement.py), so it is never stale in the cache.

Usage numbers belong to the module that owns the records (identity_access counts technicians);
modules register a counter per limit in their ModuleSpec (`usage_counters`), and this service
runs it in the caller's session, so licensing never reads another module's tables.
"""

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import EntitlementRequired, LimitReached, ReadOnlyMode
from app.core.modules import UsageCounter
from app.core.tenancy import TenantContext
from app.modules.licensing.domain.catalogue import Edition, Feature, LimitKey
from app.modules.licensing.domain.entitlement import (
    Entitlement,
    EntitlementState,
    LimitCheck,
    StateReason,
    Status,
    Term,
    days_left,
)
from app.modules.licensing.infra.cache import EntitlementCache, NoCache
from app.modules.licensing.service.ports import EntitlementProvider

Clock = Callable[[], datetime]
ADMIN_ROLE = "tenant_admin"
# Roles that may see usage numbers (seat counts) in the summary.
STAFF_ROLES = frozenset({"tenant_admin", "technician"})


def _utcnow() -> datetime:
    return datetime.now(UTC)


def session_tenant(session: AsyncSession) -> TenantContext:
    """The tenant context of a tenant session (TypeError outside one)."""
    context = session.info.get(SESSION_TENANT_KEY)
    if not isinstance(context, TenantContext):
        msg = "entitlement limits need a tenant session (Database.tenant_session)"
        raise TypeError(msg)
    return context


@dataclass(frozen=True)
class LimitUsage:
    """One counted limit in the summary. `used` is None while no module counts it yet."""

    key: LimitKey
    limit: int | None
    used: int | None
    remaining: int | None


@dataclass(frozen=True)
class Summary:
    """The tenant's entitlement as GET /api/v1/entitlements returns it (no secrets)."""

    edition: Edition | None
    status: Status
    days_left: int | None
    admin_warning: bool
    features: list[Feature]
    limits: list[LimitUsage]
    term: Term | None


class EntitlementService:
    """Answers entitlement questions for any tenant."""

    def __init__(
        self,
        provider: EntitlementProvider,
        *,
        cache: EntitlementCache | None = None,
        counters: Mapping[LimitKey, UsageCounter] | None = None,
        clock: Clock = _utcnow,
    ) -> None:
        self.provider = provider
        self.cache: EntitlementCache = (
            cache if cache is not None and provider.cacheable else NoCache()
        )
        self.counters = dict(counters or {})
        self.clock = clock

    # --- entitlement and features -----------------------------------------------------------------

    async def entitlement(
        self, tenant_id: uuid.UUID, session: AsyncSession | None = None
    ) -> Entitlement:
        """The tenant's entitlement (cache, else provider, reading through `session` if given)."""
        found = await self.cache.lookup(tenant_id)
        if found.entitlement is not None:
            return found.entitlement
        entitlement = await self.provider.load(tenant_id, session)
        await self.cache.put(tenant_id, entitlement, found.generation)
        return entitlement

    async def invalidate(self, tenant_id: uuid.UUID) -> None:
        """Forget the cached entitlement (after a change, see the cache consumer)."""
        await self.cache.invalidate(tenant_id)

    async def has_feature(self, tenant_id: uuid.UUID, feature: Feature | str) -> bool:
        """Whether the tenant's plan includes `feature`."""
        return (await self.entitlement(tenant_id)).has_feature(feature)

    async def require_feature(self, tenant_id: uuid.UUID, feature: Feature | str) -> None:
        """403 `entitlement_required` (params: feature) unless the plan includes `feature`."""
        if not await self.has_feature(tenant_id, feature):
            raise EntitlementRequired(params={"feature": str(feature)})

    # --- state ------------------------------------------------------------------------------------

    async def current_state(self, tenant_id: uuid.UUID) -> Status:
        """State, reason and grace end at this moment."""
        return (await self.entitlement(tenant_id)).status(self.clock())

    async def require_writable(self, tenant_id: uuid.UUID) -> Status:
        """403 `read_only_mode` (params: reason) unless changes are allowed."""
        status = await self.current_state(tenant_id)
        if not status.allows_writes:
            raise ReadOnlyMode(params={"reason": _reason(status)})
        return status

    # --- counted limits ---------------------------------------------------------------------------

    async def usage(self, session: AsyncSession, key: LimitKey) -> int | None:
        """Live count from the owning module, or None if no module counts `key` yet."""
        counter = self.counters.get(key)
        return None if counter is None else await counter(session)

    async def check_limit(
        self, session: AsyncSession, key: LimitKey, adding: int = 1
    ) -> LimitCheck:
        """Whether `adding` more fit (no lock: use `reserve` before actually adding)."""
        tenant = session_tenant(session)
        used = await self.usage(session, key)
        if used is None:
            msg = f"no module registered a usage counter for limit {key!r}"
            raise LookupError(msg)
        entitlement = await self.entitlement(tenant.tenant_id, session)
        return entitlement.check(key, used=used, adding=adding)

    async def remaining(self, session: AsyncSession, key: LimitKey) -> int | None:
        """How many more fit; None = unlimited."""
        return (await self.check_limit(session, key, adding=0)).remaining

    async def hold(self, session: AsyncSession, key: LimitKey) -> None:
        """Serialise additions to `key` for this tenant until the transaction ends.

        `reserve` takes it too (advisory locks are re-entrant). Take it first when you must read
        your own state before deciding whether to reserve, e.g. "is this user already counted?".
        """
        tenant = session_tenant(session)
        lock_key = func.hashtextextended(f"licensing:{tenant.tenant_id}:{key.value}", 0)
        await session.execute(select(func.pg_advisory_xact_lock(lock_key)))

    async def reserve(
        self,
        session: AsyncSession,
        key: LimitKey,
        adding: int = 1,
        *,
        code: str | None = None,
    ) -> LimitCheck:
        """Check-and-hold capacity for `adding` more, inside the caller's transaction.

        Takes a transaction-level advisory lock per (tenant, limit) before counting, so concurrent
        callers queue up: each counts only after the previous one committed (READ COMMITTED gives
        every statement a fresh snapshot) or rolled back. The caller must insert its record in the
        same transaction. Raises 403 `limit_reached` (or `code`) with params limit/max.
        """
        await self.hold(session, key)
        check = await self.check_limit(session, key, adding)
        if not check.allowed:
            raise LimitReached(code=code, params={"limit": str(key), "max": check.limit})
        return check

    # --- summary ----------------------------------------------------------------------------------

    async def summary(self, session: AsyncSession) -> Summary:
        """The tenant's entitlement for display; usage only for staff roles."""
        context = session_tenant(session)
        entitlement = await self.entitlement(context.tenant_id, session)
        now = self.clock()
        status = entitlement.status(now)
        staff = bool(context.roles & STAFF_ROLES)
        limits = []
        for key in LimitKey:
            used = await self.usage(session, key) if staff else None
            limit = entitlement.limit(key)
            remaining = None
            if used is not None and limit is not None:
                remaining = max(0, limit - used)
            limits.append(LimitUsage(key=key, limit=limit, used=used, remaining=remaining))
        return Summary(
            edition=entitlement.edition,
            status=status,
            days_left=days_left(status, now),
            admin_warning=ADMIN_ROLE in context.roles
            and status.state is not EntitlementState.ACTIVE,
            features=sorted(entitlement.features),
            limits=limits,
            term=entitlement.term,
        )


def _reason(status: Status) -> str:
    return (status.reason or StateReason.NO_ENTITLEMENT).value


# --- the installed service (one per process) -----------------------------------------------------
# Other modules call the functions in app/modules/licensing/__init__.py, which use the service the
# licensing startup hook installed. Same pattern as the event registry (app/shared/events).

_installed: list[EntitlementService] = []


def install(service: EntitlementService) -> None:
    """Make `service` the process's entitlement service."""
    _installed[:] = [service]


def uninstall(service: EntitlementService) -> None:
    """Remove `service` if it is the installed one (app shutdown)."""
    if _installed and _installed[0] is service:
        _installed.clear()


def installed() -> EntitlementService | None:
    """The process's entitlement service, if the licensing module started."""
    return _installed[0] if _installed else None
