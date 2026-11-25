"""The MonetX topology import (WP-053 S6; REQ-CMDB-031, REQ-INT-041): devices and links → CMDB.

- Hourly per connection, or at once after "run now" (a `running` run row waits for the next
  tick of the schedule). One import per connection at a time: its row is locked SKIP LOCKED.
- Writes go through cmdb's public `monitored_*` functions, as the sync identity: a new device is
  a new CI (`origin=monetx`), a known one is updated where `monetx` wins the CMDB's source
  precedence (S4), and fields a person set and that outrank it are kept.
- A device missing from one run is `stale`; missing from 3 in a row it's `ended` and its CI moves
  to its end-of-life state. **Never deleted.**
- Links the import made are remembered (`monitoring_links`); only those are ever removed. A link
  a person drew, even between the same two CIs, is never touched.
"""

import uuid
from collections import Counter
from datetime import timedelta
from typing import Final

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import SESSION_TENANT_KEY, Database
from app.core.errors import NotFound
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules import cmdb, licensing
from app.modules.monitoring_integrations.domain.monitoring import (
    DeviceState,
    RunState,
    after_run,
    ci_type_for,
    site_for,
)
from app.modules.monitoring_integrations.events import TopologyRunChanged
from app.modules.monitoring_integrations.infra.models import (
    MonitoredDevice,
    MonitoredLink,
    MonitoringConnection,
    TopologyRun,
)
from app.modules.monitoring_integrations.infra.monetx_client import (
    Device,
    Link,
    MonitoringUnavailableError,
)
from app.modules.monitoring_integrations.service.connections import FEATURE, client_for
from app.shared.clock import system_clock
from app.shared.events import record_event
from app.shared.history import Source

log = get_logger(__name__)
EVERY = timedelta(hours=1)
LINK_TYPE = "connected_to"
SOURCE: Final[Source] = "integration"


def _tenant(session: AsyncSession) -> uuid.UUID:
    tenant: uuid.UUID = session.info[SESSION_TENANT_KEY].tenant_id
    return tenant


async def request_run(session: AsyncSession, connection_id: uuid.UUID) -> TopologyRun:
    """Run now: a waiting run the schedule starts within a minute (one waiting at a time)."""
    await licensing.require_feature(_tenant(session), FEATURE)
    connection = await session.scalar(
        select(MonitoringConnection).where(
            MonitoringConnection.id == connection_id, MonitoringConnection.deleted_at.is_(None)
        )
    )
    if connection is None:
        raise NotFound(code="monitoring_connection_not_found")
    waiting = await session.scalar(
        select(TopologyRun).where(
            TopologyRun.connection_id == connection_id,
            TopologyRun.state == RunState.RUNNING.value,
        )
    )
    if waiting is not None:
        return waiting
    run = TopologyRun(
        tenant_id=connection.tenant_id,
        connection_id=connection_id,
        started_at=system_clock.now(),
        state=RunState.RUNNING.value,
        counts={},
    )
    session.add(run)
    await session.flush()
    await _event(session, run)
    return run


async def list_runs(
    session: AsyncSession, connection_id: uuid.UUID, *, limit: int = 20
) -> list[TopologyRun]:
    """The connection's latest runs, newest first."""
    rows = await session.scalars(
        select(TopologyRun)
        .where(TopologyRun.connection_id == connection_id)
        .order_by(TopologyRun.started_at.desc(), TopologyRun.id.desc())
        .limit(max(1, min(limit, 100)))
    )
    return list(rows)


async def _event(session: AsyncSession, run: TopologyRun) -> None:
    counts = run.counts or {}
    await record_event(
        session,
        TopologyRunChanged(
            connection_id=run.connection_id,
            run_id=run.id,
            state=run.state,
            created=int(counts.get("created", 0)),
            updated=int(counts.get("updated", 0)),
            stale=int(counts.get("stale", 0)),
            ended=int(counts.get("ended", 0)),
        ),
        aggregate_id=run.connection_id,
    )


async def _import_devices(
    session: AsyncSession, connection: MonitoringConnection, devices: list[Device]
) -> tuple[dict[str, uuid.UUID], Counter[str]]:
    """Devices to CIs; the external ID → CI of every device seen, and the counts."""
    counts: Counter[str] = Counter()
    now = system_clock.now()
    known = {
        d.external_id: d
        for d in await session.scalars(
            select(MonitoredDevice).where(MonitoredDevice.connection_id == connection.id)
        )
    }
    seen: dict[str, uuid.UUID] = {}
    for device in devices:
        site = site_for(connection.site_map or {}, device.group)
        values = {"name": device.name, "site_id": uuid.UUID(site) if site else None}
        row = known.get(device.id)
        if row is None:
            ci_id = await cmdb.monitored_ci_create(
                session, type_api_name=ci_type_for(device.kind), values=values, source=SOURCE
            )
            row = MonitoredDevice(
                tenant_id=connection.tenant_id,
                connection_id=connection.id,
                external_id=device.id,
                ci_id=ci_id,
            )
            session.add(row)
            known[device.id] = row
            counts["created"] += 1
        else:
            update = await cmdb.monitored_ci_update(session, row.ci_id, values, source=SOURCE)
            if update is not None and update.changed:
                counts["updated"] += 1
        after = after_run(seen=True, missed_runs=row.missed_runs or 0, state=DeviceState.SEEN)
        row.state, row.missed_runs, row.last_seen_at = after.state.value, after.missed_runs, now
        seen[device.id] = row.ci_id
    for external, row in known.items():
        if external in seen:
            continue
        after = after_run(
            seen=False, missed_runs=row.missed_runs or 0, state=DeviceState(row.state)
        )
        row.state, row.missed_runs = after.state.value, after.missed_runs
        counts[after.state.value] += 1
        if after.retire:
            await cmdb.monitored_retire(session, row.ci_id, source=SOURCE)
    await session.flush()
    return seen, counts


async def _import_links(
    session: AsyncSession,
    connection: MonitoringConnection,
    links: list[Link],
    seen: dict[str, uuid.UUID],
) -> Counter[str]:
    """Links between seen devices; links the import made and MonetX dropped are removed."""
    counts: Counter[str] = Counter()
    made = {
        m.external_id: m
        for m in await session.scalars(
            select(MonitoredLink).where(MonitoredLink.connection_id == connection.id)
        )
    }
    current: set[str] = set()
    for link in links:
        a, b = seen.get(link.from_id), seen.get(link.to_id)
        if a is None or b is None or a == b:
            continue
        current.add(link.id)
        if link.id in made:
            continue
        relationship = await cmdb.monitored_link(session, a, b, type_code=LINK_TYPE, source=SOURCE)
        if relationship is None:
            continue  # already there (a person drew it): never ours, so never removed
        session.add(
            MonitoredLink(
                tenant_id=connection.tenant_id,
                connection_id=connection.id,
                external_id=link.id,
                relationship_id=relationship,
            )
        )
        counts["linked"] += 1
    for external, row in made.items():
        if external in current:
            continue
        await cmdb.monitored_unlink(session, row.relationship_id, source=SOURCE)
        await session.execute(delete(MonitoredLink).where(MonitoredLink.id == row.id))
        counts["unlinked"] += 1
    await session.flush()
    return counts


async def run_connection(
    session: AsyncSession, settings: Settings, connection: MonitoringConnection, run: TopologyRun
) -> TopologyRun:
    """One import; the run finishes `done` with counts, or `failed` with a labelled code."""
    try:
        client = await client_for(session, settings, connection)
        devices = await client.devices()
        links = await client.links()
    except MonitoringUnavailableError as error:
        run.state, run.error_code = RunState.FAILED.value, error.code
        connection.last_error_code = error.code
    else:
        seen, counts = await _import_devices(session, connection, devices)
        counts.update(await _import_links(session, connection, links, seen))
        run.state, run.counts, run.error_code = RunState.DONE.value, dict(counts), None
        connection.last_error_code = None
    now = system_clock.now()
    run.finished_at = now
    connection.last_run_at = now
    await session.flush()
    await _event(session, run)
    return run


async def _due(session: AsyncSession) -> list[tuple[MonitoringConnection, TopologyRun | None]]:
    """Connections whose hour is up or with a waiting run, each locked (SKIP LOCKED)."""
    cutoff = system_clock.now() - EVERY
    connections = list(
        await session.scalars(
            select(MonitoringConnection)
            .where(
                MonitoringConnection.deleted_at.is_(None),
                MonitoringConnection.enabled.is_(True),
                MonitoringConnection.secret_ref.is_not(None),
            )
            .with_for_update(skip_locked=True)
        )
    )
    out: list[tuple[MonitoringConnection, TopologyRun | None]] = []
    for connection in connections:
        waiting = await session.scalar(
            select(TopologyRun)
            .where(
                TopologyRun.connection_id == connection.id,
                TopologyRun.state == RunState.RUNNING.value,
            )
            .limit(1)
        )
        if waiting is not None or connection.last_run_at is None or connection.last_run_at < cutoff:
            out.append((connection, waiting))
    return out


async def run_tenant(session: AsyncSession, settings: Settings) -> int:
    """Every due connection of the tenant; how many ran. Nothing without the licence feature."""
    if not await licensing.has_feature(_tenant(session), FEATURE):
        return 0
    ran = 0
    for connection, waiting in await _due(session):
        run = waiting
        if run is None:
            run = TopologyRun(
                tenant_id=connection.tenant_id,
                connection_id=connection.id,
                started_at=system_clock.now(),
                state=RunState.RUNNING.value,
                counts={},
            )
            session.add(run)
            await session.flush()
        await run_connection(session, settings, connection, run)
        ran += 1
    return ran


async def topology_schedule(database: Database, settings: Settings) -> None:
    """Every minute: each tenant's due imports (RLS: app.tenant_id set per tenant)."""
    async with database.platform_session() as session:
        tenants = list((await session.scalars(text("SELECT audit_tenant_ids()"))).all())
    for tenant in tenants:
        try:
            async with database.tenant_session(TenantContext(tenant)) as session:
                await run_tenant(session, settings)
        except Exception:  # pragma: no cover - one tenant's failure must not stop the others
            log.exception("monitoring_topology_failed", tenant_id=str(tenant))
