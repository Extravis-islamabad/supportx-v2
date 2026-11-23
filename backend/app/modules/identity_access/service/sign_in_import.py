"""Keycloak's login events into the sign-in log (REQ-AUD-015; WP-057 S1b; lane B's conditions).

Every minute the consumers worker reads the realm's new error events as `supportx-events`
(view-events only: the chart gives its secret to that worker alone) and writes each into the one
tenant it belongs to (domain/sign_in_import.py says which, and what is read at all).

- **The token** is fetched per run (a new client each time) and never logged.
- **The cursor** (`sign_in_import_cursor`, one row per realm) moves on only after the tenants'
  rows are committed, so a failed run is read again; Keycloak's `dateFrom` is inclusive and the
  rows are unique on (tenant, Keycloak event ID), so re-reading writes nothing twice.
- **At most IMPORT_CAP events a run**; a backlog drains over the next runs. The cursor is a
  millisecond and an offset into it: when a whole run fell inside one millisecond (a burst), the
  next run reads on from the offset (`first`), so nothing in a burst is ever skipped (lane B).
  Otherwise it starts at the newest millisecond again with offset 0 and re-reads those few.
  Only events older than SETTLE_MS are read (`dateTo`), so the cursor never stands in a
  millisecond that can still grow and its offset always counts a finished set (lane B).
- **Unattributed** events (the shared address, no identity provider) are counted in
  `supportx_sign_in_import_unattributed`, never written to a guessed tenant.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from opentelemetry import metrics
from sqlalchemy import func, select, tuple_
from sqlalchemy.dialects.postgresql import insert

from app.core.config import Settings
from app.core.database import Database
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.identity_access.domain.security_notice_import import NOTICE_TYPES
from app.modules.identity_access.domain.sign_in import Source, keycloak_outcome, keycloak_reason
from app.modules.identity_access.domain.sign_in_import import (
    IMPORT_TYPES,
    KeycloakEvent,
    app_of,
    clean_ip,
    method_of,
    redirect_host,
    slug_of_alias,
    usable,
)
from app.modules.identity_access.events import SignInRecorded
from app.modules.identity_access.infra.keycloak_admin import (
    EventsReader,
    IdentityAdminRefused,
    IdentityAdminUnavailable,
    KeycloakAdmin,
)
from app.modules.identity_access.infra.models import (
    SignInEvent,
    SignInImportCursor,
    SsoProvider,
    User,
)
from app.modules.identity_access.service import security_notice_import as notices
from app.modules.organization import tenant_for_host, tenant_for_slug
from app.shared.events import record_event
from app.shared.ids import new_id

log = get_logger(__name__)

IMPORT_CAP = 5000
# One read, one cursor: the log's types and the person's notices' (REQ-SEC-033 part 2).
READ_TYPES = IMPORT_TYPES + NOTICE_TYPES
PAGE = 500
SETTLE_MS = 5000  # a millisecond this old takes no new events: offsets into it are stable
FIRST_RUN_LOOKBACK_MS = 24 * 3600 * 1000  # a new installation reads the last day, no more

_meter = metrics.get_meter("supportx.identity_access")
_unattributed = _meter.create_counter(
    "supportx_sign_in_import_unattributed",
    description="Keycloak login events no tenant could be named for (not imported)",
)
_imported = _meter.create_counter(
    "supportx_sign_in_import_imported", description="Keycloak login events imported"
)


@dataclass
class _Attribution:
    """Which tenant an event belongs to, with the run's lookups remembered."""

    database: Database
    base_domain: str | None
    by_alias: dict[str, uuid.UUID | None] = field(default_factory=dict)
    by_host: dict[str, uuid.UUID | None] = field(default_factory=dict)

    async def tenant(self, event: KeycloakEvent) -> uuid.UUID | None:
        if event.identity_provider:
            return await self._of_alias(event.identity_provider)
        host = redirect_host(event.redirect_uri)
        if host is None:
            return None
        if host not in self.by_host:
            found = await tenant_for_host(self.database, host, self.base_domain)
            self.by_host[host] = found.tenant_id if found is not None else None
        return self.by_host[host]

    async def _of_alias(self, alias: str) -> uuid.UUID | None:
        if alias in self.by_alias:
            return self.by_alias[alias]
        tenant: uuid.UUID | None = None
        slug = slug_of_alias(alias)
        found = await tenant_for_slug(self.database, slug) if slug else None
        if found is not None:
            # The alias is only a hint: the tenant must hold that provider itself (RLS).
            async with self.database.tenant_session(TenantContext(found.tenant_id)) as session:
                held = await session.scalar(
                    select(SsoProvider.id).where(SsoProvider.alias == alias).limit(1)
                )
            tenant = found.tenant_id if held is not None else None
        self.by_alias[alias] = tenant
        return tenant


async def _read(
    reader: EventsReader, since_ms: int, offset: int, until_ms: int
) -> list[KeycloakEvent]:
    """Up to IMPORT_CAP events from `since_ms` to `until_ms`, after the `offset` read before."""
    events: list[KeycloakEvent] = []
    while len(events) < IMPORT_CAP:
        asked = min(PAGE, IMPORT_CAP - len(events))
        page = await reader.realm_events(
            READ_TYPES, since_ms, until_ms, first=offset + len(events), limit=asked
        )
        events.extend(page)
        if len(page) < asked:
            break
    return events


async def _write(database: Database, tenant_id: uuid.UUID, events: list[KeycloakEvent]) -> int:
    """The tenant's events, once each; how many were new."""
    written = 0
    async with database.tenant_session(TenantContext(tenant_id)) as session:
        subjects = {e.user_id for e in events if e.user_id}
        found = await session.execute(
            select(User.external_subject, User.id).where(
                User.external_subject.in_(subjects), User.deleted_at.is_(None)
            )
        )
        people = dict(found.all())  # rows, not the result: a Result has keys() (column names)
        for event in events:
            app = app_of(event)
            if app is None:  # filtered before; kept for the type checker
                continue
            outcome = keycloak_outcome(event.type, event.error)
            row_id = new_id()
            inserted = await session.scalar(
                insert(SignInEvent)
                .values(
                    tenant_id=tenant_id,
                    id=row_id,
                    # Only a person Keycloak resolved and this tenant knows; never the typed name.
                    user_id=people.get(event.user_id) if event.user_id else None,
                    occurred_at=datetime.fromtimestamp(event.time_ms / 1000, UTC),
                    outcome=outcome.value,
                    reason=keycloak_reason(event.error),
                    method=method_of(event).value,
                    app=app.value,
                    ip=clean_ip(event.ip),
                    device=None,  # Keycloak's events carry no User-Agent
                    identity_provider=(event.identity_provider or None),
                    source=Source.KEYCLOAK.value,
                    keycloak_event_id=event.id,
                )
                .on_conflict_do_nothing(
                    index_elements=[SignInEvent.tenant_id, SignInEvent.keycloak_event_id],
                    index_where=SignInEvent.keycloak_event_id.is_not(None),
                )
                .returning(SignInEvent.id)
            )
            if inserted is None:
                continue  # read before (the cursor is inclusive)
            written += 1
            await record_event(
                session,
                SignInRecorded(outcome=outcome.value),
                aggregate_id=row_id,
                aggregate_version=1,
            )
    return written


async def _advance(database: Database, realm: str, last_ms: int, offset: int) -> None:
    """Move the cursor forward to (last_ms, offset); never back (another run got further)."""
    async with database.platform_session() as session:
        statement = insert(SignInImportCursor).values(
            realm=realm, last_time_ms=last_ms, last_offset=offset
        )
        current = tuple_(SignInImportCursor.last_time_ms, SignInImportCursor.last_offset)
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[SignInImportCursor.realm],
                set_={
                    "last_time_ms": statement.excluded.last_time_ms,
                    "last_offset": statement.excluded.last_offset,
                    "updated_at": func.now(),
                },
                where=current
                < tuple_(statement.excluded.last_time_ms, statement.excluded.last_offset),
            )
        )


@dataclass
class _Grouped:
    """The run's events by tenant: for the sign-in log, and for notices to the person."""

    log: dict[uuid.UUID, list[KeycloakEvent]] = field(default_factory=dict)
    notices: dict[uuid.UUID, list[KeycloakEvent]] = field(default_factory=dict)
    unattributed: int = 0


async def _group(attribution: _Attribution, events: list[KeycloakEvent]) -> _Grouped:
    """Which tenant each event goes to, and how many named none."""
    grouped = _Grouped()
    hintless: list[KeycloakEvent] = []
    for event in events:
        if not usable(event):
            continue
        if event.type in NOTICE_TYPES:
            # Lane B: no userId (an unknown name) is never anyone's notice, nor counted.
            if not event.user_id:
                continue
            tenant = await attribution.tenant(event)
            if tenant is None:
                hintless.append(event)
                continue
            grouped.notices.setdefault(tenant, []).append(event)
        elif app_of(event) is not None:
            tenant = await attribution.tenant(event)
            if tenant is None:
                grouped.unattributed += 1
                continue
            grouped.log.setdefault(tenant, []).append(event)
    # No tenant named: the one tenant the person is in, else not guessed (lane B).
    sole = await notices.sole_tenants(attribution.database, {e.user_id or "" for e in hintless})
    for event in hintless:
        tenant = sole.get(event.user_id or "")
        if tenant is None:
            grouped.unattributed += 1
            continue
        grouped.notices.setdefault(tenant, []).append(event)
    return grouped


async def _deliver(
    database: Database, grouped: _Grouped, locate: notices.Locate | None
) -> tuple[int, int]:
    """Each tenant's log rows and notices; (log rows new, people told)."""
    written = told = 0
    for tenant, items in grouped.log.items():
        written += await _write(database, tenant, items)
    for tenant, items in grouped.notices.items():
        told += await notices.write(database, tenant, items, locate)
    return written, told


async def import_once(
    database: Database,
    reader: EventsReader,
    *,
    base_domain: str | None,
    now_ms: int,
    locate: notices.Locate | None = None,
) -> int:
    """One run: read, write per tenant, then move the cursor; how many rows were new."""
    async with database.platform_session() as session:
        cursor = await session.get(SignInImportCursor, reader.realm)
    if cursor is None:
        since, offset = now_ms - FIRST_RUN_LOOKBACK_MS, 0
    else:
        since, offset = cursor.last_time_ms, cursor.last_offset
    until = now_ms - SETTLE_MS
    if until < since:
        return 0  # nothing has settled since the cursor yet
    events = await _read(reader, since, offset, until)
    if not events:
        if cursor is None:
            await _advance(database, reader.realm, since, 0)
        return 0
    grouped = await _group(_Attribution(database, base_domain), events)
    unattributed = grouped.unattributed
    written, told = await _deliver(database, grouped, locate)
    newest = max(e.time_ms for e in events)
    if newest == since:
        # Still inside the cursor's millisecond: read on from here next time, skip nothing.
        await _advance(database, reader.realm, since, offset + len(events))
    else:
        # Past it: the newest millisecond is read again from its start (rows are unique).
        await _advance(database, reader.realm, newest, 0)
    if unattributed:
        _unattributed.add(unattributed)
    if written:
        _imported.add(written)
    if written or told:
        log.info("sign_in_import", imported=written, told=told, unattributed=unattributed)
    return written


async def import_schedule(database: Database, settings: Settings) -> None:
    """Every minute (consumers worker): the run, with a reader made for it alone."""
    reader = KeycloakAdmin.events_from_settings(settings)
    if reader is None:
        return  # not set up: the BFF's own entries are still written
    try:
        now_ms = int(datetime.now(UTC).timestamp() * 1000)
        await import_once(
            database,
            reader,
            base_domain=settings.tenant_base_domain,
            now_ms=now_ms,
            locate=notices.locator(database, settings),
        )
    except (IdentityAdminUnavailable, IdentityAdminRefused):
        log.warning("sign_in_import_keycloak_unavailable")  # the next run tries again
    finally:
        await reader.close()
