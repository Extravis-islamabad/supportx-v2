"""Keycloak user events into notices to the person (REQ-SEC-033 part 2; WP-057 S2b-2; lane B).

The sign-in log's events import (service/sign_in_import.py) reads these types in the same run and
cursor, and hands each tenant its share here. Per event, in the tenant's transaction:

- the person is the tenant's user with that Keycloak subject; none, or an event of no kind
  (domain/security_notice_import.py), and nothing happens;
- a mark (`security_notice_marks`, once per Keycloak event ID) is written first; a re-read
  writes nothing, so nobody is told twice;
- a lock-out says when the account opens at the earliest (a lower bound: our marks can only
  undercount) and at most one lock-out notice goes to a person an hour; the rest are marked
  quiet (lane B: anyone who knows a name can lock it every 15 minutes);
- a person's first password (no password mark in MARK_RETENTION, made within it) is marked
  quiet as `password_set`: never "your password changed" on day one (lane B);
- otherwise `AccountSecurityChanged` goes to the outbox, which the locked security notice tells.

Which tenant, when Keycloak names none (no identity provider, no SupportX address): the one
tenant the subject is a person in (`sole_tenants`, each tenant asked under RLS); two or more and
nothing is guessed (counted unattributed by the caller). Marks older than MARK_RETENTION are
purged by the daily sign-in log purge; erasure deletes a person's marks (`forget`).
"""

import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import Database
from app.core.tenancy import TenantContext
from app.modules.identity_access.domain.place import place_of
from app.modules.identity_access.domain.security_notice_import import (
    LOCKOUT,
    MARK_RETENTION,
    NoticeKind,
    kind_of,
    lockout_quiet,
)
from app.modules.identity_access.domain.sign_in_import import KeycloakEvent, clean_ip
from app.modules.identity_access.events import AccountSecurityChanged
from app.modules.identity_access.infra.geoip import GeoIp
from app.modules.identity_access.infra.models import SecurityNoticeMark, User
from app.modules.identity_access.service import site_networks
from app.shared.events import record_event
from app.shared.ids import new_id

PASSWORD_KINDS = (NoticeKind.PASSWORD_CHANGED.value, NoticeKind.PASSWORD_SET.value)
Locate = Callable[[uuid.UUID, str | None], Any]  # (tenant, address) -> awaitable stored place


def locator(database: Database, settings: Settings) -> Locate:
    """The approximate place of an address in a tenant: its site map, then GeoIP (D-170).

    The consumers worker may have no GeoIP database (the chart mounts it on the API): then a
    mapped site or the internal network only, else no place. Never the address itself.
    """
    geo = GeoIp(settings.geoip_db)

    async def locate(tenant_id: uuid.UUID, ip: str | None) -> dict[str, Any] | None:
        if ip is None:
            return None
        networks = await site_networks.tenant_site_networks(database, tenant_id)
        found = place_of(ip, networks, geo.lookup)
        return None if found is None else found.to_dict()

    return locate


async def sole_tenants(database: Database, subjects: set[str]) -> dict[str, uuid.UUID]:
    """For each Keycloak subject, the one active tenant it is a person in; none or several: absent.

    Each tenant is asked in its own session (RLS), all of a run's subjects at once, and only for
    the events Keycloak named no tenant for. No cross-tenant function or grant (#476).
    """
    if not subjects:
        return {}
    async with database.platform_session() as platform:
        tenants = list((await platform.scalars(text("SELECT audit_tenant_ids()"))).all())
    held: dict[str, list[uuid.UUID]] = {}
    for tenant in tenants:
        async with database.tenant_session(TenantContext(tenant)) as session:
            found = await session.scalars(
                select(User.external_subject).where(
                    User.external_subject.in_(subjects), User.deleted_at.is_(None)
                )
            )
            for subject in found:
                if subject is not None:
                    held.setdefault(subject, []).append(tenant)
    return {subject: ids[0] for subject, ids in held.items() if len(ids) == 1}


async def _first_password(session: AsyncSession, person: User, at: datetime) -> bool:
    """Whether this is the person's first password: no password mark lately, a recent account."""
    if person.created_at < at - MARK_RETENTION:
        return False
    earlier = await session.scalar(
        select(func.count())
        .select_from(SecurityNoticeMark)
        .where(
            SecurityNoticeMark.user_id == person.id,
            SecurityNoticeMark.kind.in_(PASSWORD_KINDS),
            SecurityNoticeMark.occurred_at < at,
        )
    )
    return not earlier


async def _lockouts(
    session: AsyncSession, user_id: uuid.UUID, at: datetime
) -> list[tuple[datetime, bool]]:
    """The person's earlier lock-outs (when, whether told) inside the realm's window.

    The window (12 hours) is longer than the notice limit's hour, so it serves both.
    """
    since = at - timedelta(seconds=LOCKOUT.max_delta_seconds)
    rows = await session.execute(
        select(SecurityNoticeMark.occurred_at, SecurityNoticeMark.told).where(
            SecurityNoticeMark.user_id == user_id,
            SecurityNoticeMark.kind == NoticeKind.LOCKED_OUT.value,
            SecurityNoticeMark.occurred_at >= since,
            SecurityNoticeMark.occurred_at < at,
        )
    )
    return [(when, told) for when, told in rows.all()]


async def _notice(  # noqa: PLR0913 - the event, its person and kind, and the tenant
    session: AsyncSession,
    person: User,
    event: KeycloakEvent,
    kind: NoticeKind,
    *,
    locate: Locate | None,
    tenant_id: uuid.UUID,
) -> bool:
    """Mark one event and, unless kept quiet, tell the person; whether they were told."""
    at = datetime.fromtimestamp(event.time_ms / 1000, UTC)
    told = True
    opens_at = None
    if kind is NoticeKind.LOCKED_OUT:
        earlier = await _lockouts(session, person.id, at)
        opens_at = LOCKOUT.opens_at(at, [when for when, _ in earlier])
        last_told = max((when for when, was in earlier if was), default=None)
        told = not lockout_quiet(at, last_told)
    elif kind is NoticeKind.PASSWORD_CHANGED and await _first_password(session, person, at):
        kind, told = NoticeKind.PASSWORD_SET, False
    marked = await session.scalar(
        insert(SecurityNoticeMark)
        .values(
            tenant_id=tenant_id,
            id=new_id(),
            keycloak_event_id=event.id,
            user_id=person.id,
            kind=kind.value,
            occurred_at=at,
            told=told,
        )
        .on_conflict_do_nothing(constraint="uq_security_notice_marks_once")
        .returning(SecurityNoticeMark.id)
    )
    if marked is None or not told:
        return False  # read before (the cursor is inclusive), or kept quiet
    place = await locate(tenant_id, clean_ip(event.ip)) if locate is not None else None
    await record_event(
        session,
        AccountSecurityChanged(
            user_id=person.id,
            kind=kind.value,  # type: ignore[arg-type]  # PASSWORD_SET never reaches here
            occurred_at=at,
            opens_at=opens_at,
            place={k: str(v) for k, v in place.items()} if place else None,
        ),
        aggregate_id=person.id,
    )
    return True


async def write(
    database: Database,
    tenant_id: uuid.UUID,
    events: Sequence[KeycloakEvent],
    locate: Locate | None = None,
) -> int:
    """The tenant's notice events, oldest first, once each; how many people were told."""
    told = 0
    async with database.tenant_session(TenantContext(tenant_id)) as session:
        subjects = {e.user_id for e in events if e.user_id}
        found = await session.scalars(
            select(User).where(User.external_subject.in_(subjects), User.deleted_at.is_(None))
        )
        people = {person.external_subject: person for person in found}
        for event in sorted(events, key=lambda e: (e.time_ms, e.id)):
            kind = kind_of(event.type, event.credential_type)
            person = people.get(event.user_id) if event.user_id else None
            if kind is None or person is None:
                continue
            told += await _notice(session, person, event, kind, locate=locate, tenant_id=tenant_id)
    return told


async def purge(session: AsyncSession, now: datetime) -> int:
    """Marks past MARK_RETENTION go (lane B); the tenant's session, from the daily purge."""
    result = await session.execute(
        delete(SecurityNoticeMark).where(SecurityNoticeMark.occurred_at < now - MARK_RETENTION)
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def forget(session: AsyncSession, user_id: uuid.UUID) -> int:
    """Erasure (GDPR): the person's marks go."""
    result = await session.execute(
        delete(SecurityNoticeMark).where(SecurityNoticeMark.user_id == user_id)
    )
    return int(getattr(result, "rowcount", 0) or 0)
