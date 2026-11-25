"""CI health from MonetX (WP-053 S6; REQ-INT-042, REQ-CMDB-031), read-only and visible-only.

- **Visible only:** health answers for the CIs the reader may see (cmdb's `visible_ci_ids`). An
  unseen CI is absent from the answer, never `unknown` (ADR-053: nothing of it is revealed).
- **Licensed on the server:** without `monetx_integration`, every CI is `unmonitored` and MonetX
  is never asked.
- **One read per device per 15 s, for everyone:** a shared cache (Valkey, else this process),
  filled under a per-connection lock, so N viewers make one MonetX read (single flight).
- **A breaker per connection:** after repeated failures MonetX is left alone for a minute and
  health reads `unknown` with the reason `monitoring_unreachable`. Never an error page.
- **Live:** a read marks its CIs watched; every 15 s the refresh re-reads the watched devices,
  and a change of state emits `HealthChanged` (the state code only) for the CI's channel.
"""

import asyncio
import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import SESSION_TENANT_KEY, Database
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.core.valkey import client as valkey_client
from app.modules import cmdb, licensing
from app.modules.identity_access import Subject
from app.modules.monitoring_integrations.domain.monitoring import (
    CACHE_SECONDS,
    HEALTH_IDS_MAX,
    UNREACHABLE,
    Breaker,
    DeviceState,
    HealthState,
    health_of,
)
from app.modules.monitoring_integrations.events import HealthChanged
from app.modules.monitoring_integrations.infra.models import MonitoredDevice, MonitoringConnection
from app.modules.monitoring_integrations.infra.monetx_client import (
    DeviceHealth,
    MonitoringUnavailableError,
)
from app.modules.monitoring_integrations.service.connections import FEATURE, client_for
from app.shared.clock import system_clock
from app.shared.events import record_event

log = get_logger(__name__)
WATCH_SECONDS = 60  # a CI stays watched this long after someone last read its health


@dataclass(frozen=True)
class Health:
    """One CI's health as the API shows it (codes and a time, never MonetX's text)."""

    state: HealthState
    since: datetime | None = None
    problem_count: int = 0
    reason: str | None = None


class HealthCache(Protocol):
    """Where read health waits 15 s for the next reader, and which CIs are watched."""

    async def get(self, key: str) -> str | None:
        """A cached entry."""
        ...

    async def put(self, key: str, value: str, seconds: int) -> None:
        """Cache an entry for `seconds`."""
        ...

    async def watch(self, tenant: uuid.UUID, ci_ids: Sequence[uuid.UUID]) -> None:
        """Mark CIs watched for `WATCH_SECONDS`."""
        ...

    async def watched(self, tenant: uuid.UUID) -> list[uuid.UUID]:
        """The tenant's CIs watched now."""
        ...


class MemoryCache:
    """One process's cache (no Valkey configured, and tests)."""

    def __init__(self) -> None:
        self._items: dict[str, tuple[float, str]] = {}
        self._watched: dict[uuid.UUID, dict[uuid.UUID, float]] = {}

    def _now(self) -> float:
        return system_clock.now().timestamp()

    async def get(self, key: str) -> str | None:
        """A cached entry, if still fresh."""
        found = self._items.get(key)
        return found[1] if found is not None and found[0] > self._now() else None

    async def put(self, key: str, value: str, seconds: int) -> None:
        """Cache an entry."""
        self._items[key] = (self._now() + seconds, value)

    async def watch(self, tenant: uuid.UUID, ci_ids: Sequence[uuid.UUID]) -> None:
        """Mark CIs watched."""
        until = self._now() + WATCH_SECONDS
        self._watched.setdefault(tenant, {}).update(dict.fromkeys(ci_ids, until))

    async def watched(self, tenant: uuid.UUID) -> list[uuid.UUID]:
        """The CIs still watched."""
        now = self._now()
        return [c for c, until in self._watched.get(tenant, {}).items() if until > now]


class ValkeyCache:
    """The shared cache: every API process and the refresh see the same 15 s entries."""

    def __init__(self, client: Any, prefix: str) -> None:  # noqa: ANN401 - valkey-py's client
        self._client = client
        self._prefix = f"{prefix}monitoring:"

    async def get(self, key: str) -> str | None:
        """A cached entry."""
        found = await self._client.get(self._prefix + key)
        return found.decode() if isinstance(found, bytes) else found

    async def put(self, key: str, value: str, seconds: int) -> None:
        """Cache an entry."""
        await self._client.set(self._prefix + key, value, ex=seconds)

    async def watch(self, tenant: uuid.UUID, ci_ids: Sequence[uuid.UUID]) -> None:
        """Mark CIs watched (a sorted set scored by expiry)."""
        if not ci_ids:
            return
        until = system_clock.now().timestamp() + WATCH_SECONDS
        key = f"{self._prefix}watched:{tenant}"
        await self._client.zadd(key, {str(c): until for c in ci_ids})
        await self._client.expire(key, WATCH_SECONDS * 2)

    async def watched(self, tenant: uuid.UUID) -> list[uuid.UUID]:
        """The CIs still watched (expired ones dropped)."""
        key = f"{self._prefix}watched:{tenant}"
        now = system_clock.now().timestamp()
        await self._client.zremrangebyscore(key, "-inf", now)
        members = await self._client.zrange(key, 0, -1)
        out: list[uuid.UUID] = []
        for member in members:
            try:
                out.append(uuid.UUID(member.decode() if isinstance(member, bytes) else member))
            except ValueError:
                continue
        return out


_CACHE: list[HealthCache] = [MemoryCache()]
_LOCKS: dict[tuple[uuid.UUID, uuid.UUID], asyncio.Lock] = {}
_BREAKERS: dict[tuple[uuid.UUID, uuid.UUID], Breaker] = {}


def use_cache(cache: HealthCache | None) -> None:
    """Startup (Valkey) and tests: the cache to use; None goes back to this process's."""
    _CACHE[:] = [cache or MemoryCache()]
    _BREAKERS.clear()


def ensure_cache(settings: Settings) -> None:
    """Use the shared cache once Valkey is configured.

    API startup and the worker's schedule both call it, so the watched set the API fills is the
    one the refresh reads.
    """
    if settings.valkey_url is None or isinstance(_CACHE[0], ValkeyCache):
        return
    use_cache(ValkeyCache(valkey_client(settings), settings.valkey_key_prefix))


def _key(connection: uuid.UUID, external: str) -> str:
    return f"health:{connection}:{external}"


def _encode(found: DeviceHealth | None) -> str:
    if found is None:
        return json.dumps({"missing": True})
    return json.dumps(
        {
            "status": found.status,
            "since": found.since.isoformat() if found.since else None,
            "problem_count": found.problem_count,
        }
    )


def _decode(raw: str) -> Health:
    data = json.loads(raw)
    if data.get("missing"):
        return Health(HealthState.UNKNOWN)
    since = data.get("since")
    return Health(
        health_of(data.get("status")),
        datetime.fromisoformat(since) if isinstance(since, str) else None,
        int(data.get("problem_count") or 0),
    )


async def _read_connection(
    session: AsyncSession,
    settings: Settings,
    connection: MonitoringConnection,
    externals: Sequence[str],
    *,
    fresh: bool = False,
) -> dict[str, Health]:
    """Health of one connection's devices: cached, else one read under the connection's lock."""
    cache = _CACHE[0]
    found: dict[str, Health] = {}
    missing: list[str] = []
    for external in externals:
        raw = None if fresh else await cache.get(_key(connection.id, external))
        if raw is None:
            missing.append(external)
        else:
            found[external] = _decode(raw)
    if not missing:
        return found
    lock = _LOCKS.setdefault((connection.tenant_id, connection.id), asyncio.Lock())
    async with lock:
        # Single flight: whoever waited may find the first reader's answer cached now.
        still: list[str] = []
        for external in missing:
            raw = None if fresh else await cache.get(_key(connection.id, external))
            if raw is None:
                still.append(external)
            else:
                found[external] = _decode(raw)
        if not still:
            return found
        breaker = _BREAKERS.get((connection.tenant_id, connection.id), Breaker())
        now = system_clock.now()
        if breaker.is_open(now):
            return {
                **found,
                **dict.fromkeys(still, Health(HealthState.UNKNOWN, reason=UNREACHABLE)),
            }
        try:
            answer = await (await client_for(session, settings, connection)).health(still)
        except MonitoringUnavailableError as error:
            _BREAKERS[(connection.tenant_id, connection.id)] = breaker.failed(now)
            log.warning("monitoring_health_unavailable", code=error.code)
            return {
                **found,
                **dict.fromkeys(still, Health(HealthState.UNKNOWN, reason=UNREACHABLE)),
            }
        _BREAKERS[(connection.tenant_id, connection.id)] = breaker.succeeded()
        for external in still:
            raw = _encode(answer.get(external))
            await cache.put(_key(connection.id, external), raw, CACHE_SECONDS)
            found[external] = _decode(raw)
    return found


async def _health_of_cis(
    session: AsyncSession, settings: Settings, ci_ids: Sequence[uuid.UUID], *, fresh: bool = False
) -> dict[uuid.UUID, Health]:
    """Health per CI (no visibility applied here: the callers do)."""
    rows = list(
        await session.execute(
            select(MonitoredDevice, MonitoringConnection)
            .join(MonitoringConnection, MonitoringConnection.id == MonitoredDevice.connection_id)
            .where(
                MonitoredDevice.ci_id.in_(ci_ids),
                MonitoringConnection.deleted_at.is_(None),
                MonitoringConnection.enabled.is_(True),
            )
        )
    )
    out: dict[uuid.UUID, Health] = dict.fromkeys(ci_ids, Health(HealthState.UNMONITORED))
    by_connection: dict[uuid.UUID, tuple[MonitoringConnection, list[MonitoredDevice]]] = {}
    for device, connection in rows:
        if device.state == DeviceState.ENDED.value:
            continue  # monitoring no longer reports it: unmonitored
        by_connection.setdefault(connection.id, (connection, []))[1].append(device)
    for connection, devices in by_connection.values():
        answer = await _read_connection(
            session, settings, connection, [d.external_id for d in devices], fresh=fresh
        )
        for device in devices:
            out[device.ci_id] = answer.get(device.external_id, Health(HealthState.UNKNOWN))
    return out


async def health_for(
    session: AsyncSession, subject: Subject, settings: Settings, ci_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, Health]:
    """Health of the CIs the reader may see (an unseen CI is absent); they're then watched."""
    unique = list(dict.fromkeys(ci_ids))[:HEALTH_IDS_MAX]
    visible = await cmdb.visible_ci_ids(session, subject, unique)
    shown = [c for c in unique if c in visible]
    if not shown:
        return {}
    tenant: uuid.UUID = session.info[SESSION_TENANT_KEY].tenant_id
    if not await licensing.has_feature(tenant, FEATURE):
        return dict.fromkeys(shown, Health(HealthState.UNMONITORED))
    found = await _health_of_cis(session, settings, shown)
    await _CACHE[0].watch(
        tenant, [c for c, h in found.items() if h.state is not HealthState.UNMONITORED]
    )
    return found


async def refresh_tenant(session: AsyncSession, settings: Settings) -> int:
    """Re-read the watched devices; each change of state emits `HealthChanged`. How many changed."""
    tenant: uuid.UUID = session.info[SESSION_TENANT_KEY].tenant_id
    watched = await _CACHE[0].watched(tenant)
    if not watched or not await licensing.has_feature(tenant, FEATURE):
        return 0
    found = await _health_of_cis(session, settings, watched, fresh=True)
    devices = {
        d.ci_id: d
        for d in await session.scalars(
            select(MonitoredDevice).where(MonitoredDevice.ci_id.in_(list(found)))
        )
    }
    changed = 0
    for ci_id, health in found.items():
        device = devices.get(ci_id)
        if device is None or health.reason is not None or device.health == health.state.value:
            continue  # unknown because MonetX is unreachable is not a change of the device
        device.health = health.state.value
        device.health_since = health.since or system_clock.now()
        changed += 1
        await record_event(
            session,
            HealthChanged(ci_id=ci_id, state=health.state.value),
            aggregate_id=ci_id,
        )
    await session.flush()
    return changed


async def refresh_schedule(database: Database, settings: Settings) -> None:
    """Every 15 s: each tenant's watched CIs (RLS: app.tenant_id set per tenant)."""
    ensure_cache(settings)
    async with database.platform_session() as session:
        tenants = list((await session.scalars(text("SELECT audit_tenant_ids()"))).all())
    for tenant in tenants:
        try:
            async with database.tenant_session(TenantContext(tenant)) as session:
                await refresh_tenant(session, settings)
        except Exception:  # pragma: no cover - one tenant's failure must not stop the others
            log.exception("monitoring_health_refresh_failed", tenant_id=str(tenant))


def states_of(found: Mapping[uuid.UUID, Health]) -> dict[str, str]:
    """`{ci_id: state}`: for tests and logs (codes only)."""
    return {str(c): h.state.value for c, h in found.items()}
