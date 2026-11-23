"""The sign-in log (REQ-AUD-015; WP-057 S1a; table sign_in_events, migration 0151).

**Writers.** The BFF records what it decides (a sign-in, its own refusals, a sign-out) with
`record`; the Keycloak import (workers) records what Keycloak decides. Writing never fails a
sign-in: a log that cannot be written is logged as a warning and the person goes on.

**What is kept** (lane B's conditions 7 and 8): the person only when known (never the name typed
for an unknown one), the outcome and a reason code, the method, the app, the address and a short
device code (domain/sign_in.py), the identity provider's alias. `ip` and `device` are personal
data: the GDPR erasure nulls them (`forget_person`); every row goes after RETENTION (`purge`).

**Who reads it.** Admins with `audit.view_sign_ins` see the tenant's log (filters: outcome, time,
person, method; AC2); a person sees their own entries in My account.

**Method.** In S1a the BFF writes `mobile` or `unknown`; S1b adds the verified identity-provider
claim (a realm mapper, lane B's area) and with it `password` / `single_sign_on`. Keycloak's own
events name the provider, so imported rows carry the method already.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Select, and_, delete, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import Database
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.audit import SignInRow, register_sign_in_source
from app.modules.identity_access.domain.sign_in import (
    SignInApp,
    SignInMethod,
    SignInOutcome,
    Source,
    device,
)
from app.modules.identity_access.events import SignInRecorded
from app.modules.identity_access.infra.models import SignInEvent
from app.modules.identity_access.service import known_devices, security_notice_import
from app.shared.events import ConsumerSpec, EventEnvelope, record_event
from app.shared.ids import new_id

log = get_logger(__name__)

RETENTION = timedelta(days=90)
PAGE_MAX = 200


@dataclass(frozen=True)
class SignInFacts:
    """One event, as the BFF knows it."""

    outcome: SignInOutcome
    app: SignInApp
    method: SignInMethod = SignInMethod.UNKNOWN
    user_id: uuid.UUID | None = None
    reason: str | None = None
    ip: str | None = None
    user_agent: str | None = None
    identity_provider: str | None = None


async def record(
    database: Database | None,
    tenant_id: uuid.UUID,
    facts: SignInFacts,
    *,
    at: datetime | None = None,
) -> None:
    """Write one BFF event into the tenant's log; never raises (a sign-in must not fail on it)."""
    if database is None:
        return
    try:
        event_id = new_id()
        async with database.tenant_session(TenantContext(tenant_id)) as session:
            session.add(
                SignInEvent(
                    tenant_id=tenant_id,
                    id=event_id,
                    user_id=facts.user_id,
                    occurred_at=at or datetime.now(UTC),
                    outcome=facts.outcome.value,
                    reason=facts.reason,
                    method=facts.method.value,
                    app=facts.app.value,
                    ip=facts.ip,
                    device=device(facts.user_agent),
                    identity_provider=facts.identity_provider,
                    source=Source.BFF.value,
                )
            )
            # Open sign-in logs follow it live (rule 5c), in the same transaction (rule 5b).
            await record_event(
                session,
                SignInRecorded(outcome=facts.outcome.value),
                aggregate_id=event_id,
                aggregate_version=1,
            )
    except Exception:  # noqa: BLE001 - the log must never break a sign-in; it says so instead
        log.warning("sign_in_log_unwritten", tenant_id=str(tenant_id), outcome=facts.outcome)


@dataclass(frozen=True)
class LogFilter:
    """The admin list's filters (AC2: "failed" in the last 24 hours lists only those)."""

    outcomes: tuple[SignInOutcome, ...] = ()
    methods: tuple[SignInMethod, ...] = ()
    user_id: uuid.UUID | None = None
    since: datetime | None = None
    until: datetime | None = None
    before: tuple[datetime, uuid.UUID] | None = None  # the cursor: (occurred_at, id) of the last
    limit: int = 50


def _filtered(statement: Select[Any], found: LogFilter) -> Select[Any]:
    """The admin list's filters, shared by the list and its counts (WP-057 S4d)."""
    if found.outcomes:
        statement = statement.where(SignInEvent.outcome.in_([o.value for o in found.outcomes]))
    if found.methods:
        statement = statement.where(SignInEvent.method.in_([m.value for m in found.methods]))
    if found.user_id is not None:
        statement = statement.where(SignInEvent.user_id == found.user_id)
    if found.since is not None:
        statement = statement.where(SignInEvent.occurred_at >= found.since)
    if found.until is not None:
        statement = statement.where(SignInEvent.occurred_at < found.until)
    return statement


async def signed_in_through(
    database: Database, tenant_id: uuid.UUID, user_id: uuid.UUID, identity_provider: str
) -> bool:
    """Whether the person has signed in successfully through this provider before (D-177)."""
    async with database.tenant_session(TenantContext(tenant_id)) as session:
        found = await session.scalar(
            select(SignInEvent.id)
            .where(
                SignInEvent.user_id == user_id,
                SignInEvent.identity_provider == identity_provider,
                SignInEvent.outcome == SignInOutcome.SUCCESS.value,
            )
            .limit(1)
        )
    return found is not None


async def list_events(session: AsyncSession, found: LogFilter) -> list[SignInEvent]:
    """The tenant's events, newest first (RLS keeps them to the tenant)."""
    statement = _filtered(select(SignInEvent), found)
    if found.before is not None:
        at, last = found.before
        older = SignInEvent.occurred_at < at
        same_time_older = (SignInEvent.occurred_at == at) & (SignInEvent.id < last)
        statement = statement.where(older | same_time_older)
    statement = statement.order_by(SignInEvent.occurred_at.desc(), SignInEvent.id.desc()).limit(
        min(max(found.limit, 1), PAGE_MAX)
    )
    return list(await session.scalars(statement))


async def count_events(session: AsyncSession, found: LogFilter) -> int:
    """How many events the list would show with these filters (paging aside), for the overview."""
    statement = _filtered(select(func.count()).select_from(SignInEvent), found)
    return int(await session.scalar(statement) or 0)


async def sign_ins_after(
    session: AsyncSession,
    after: tuple[datetime, uuid.UUID] | None,
    limit: int,
) -> list[SignInRow]:
    """The tenant's sign-ins after `after` (time, then ID), oldest first, at most `limit`.

    For the SIEM stream (WP-057 S5a, audit's port): what happened and when, to whom by ID; never
    the IP address, the device, a name or an e-mail address (lane A's S5a condition).
    """
    query = select(SignInEvent)
    if after is not None:
        at, last = after
        query = query.where(
            or_(
                SignInEvent.occurred_at > at,
                and_(SignInEvent.occurred_at == at, SignInEvent.id > last),
            )
        )
    rows = await session.scalars(
        query.order_by(SignInEvent.occurred_at, SignInEvent.id).limit(limit)
    )
    return [
        SignInRow(r.id, r.occurred_at, r.user_id, r.outcome, r.reason, r.method, r.app)
        for r in rows
    ]


async def latest_sign_in(session: AsyncSession) -> tuple[datetime, uuid.UUID] | None:
    """The tenant's newest sign-in's position (a new stream starts after it: no history)."""
    row = (
        await session.execute(
            select(SignInEvent.occurred_at, SignInEvent.id)
            .order_by(SignInEvent.occurred_at.desc(), SignInEvent.id.desc())
            .limit(1)
        )
    ).first()
    return None if row is None else (row[0], row[1])


async def forget_person(session: AsyncSession, user_id: uuid.UUID) -> int:
    """GDPR erasure: null the address and device of the person's entries (lane B's condition 8)."""
    result = await session.execute(
        update(SignInEvent)
        .where(SignInEvent.user_id == user_id)
        .values(ip=None, device=None)
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]  # a CursorResult for an UPDATE


async def purge(session: AsyncSession, now: datetime) -> int:
    """Delete the tenant's entries older than RETENTION; how many went."""
    result = await session.execute(
        delete(SignInEvent)
        .where(SignInEvent.occurred_at < now - RETENTION)
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]  # a CursorResult for a DELETE


async def on_person_erased(envelope: EventEnvelope, session: AsyncSession | None) -> None:
    """Consumer: a person was erased (GDPR); their sign-in traces go.

    Their entries lose address and device, and their known devices (WP-057 S2b-1) and security
    notice marks (S2b-2) are deleted, in the same transaction.
    """
    assert session is not None  # noqa: S101 - transactional consumer
    if envelope.payload.get("reason") != "erasure":
        return
    person = uuid.UUID(str(envelope.payload["user_id"]))
    forgotten = await forget_person(session, person)
    devices = await known_devices.forget(session, person)
    marks = await security_notice_import.forget(session, person)
    if forgotten or devices or marks:
        log.info("sign_in_log_erased", entries=forgotten, known_devices=devices, notice_marks=marks)


PERSON_ERASED = ConsumerSpec(
    name="identity_access__sign_ins_erased",
    event_types=("identity_access.user.status_changed",),
    handler=on_person_erased,
)


async def purge_schedule(database: Database, settings: Settings) -> None:
    """Daily, in every tenant (each in its own session, RLS): entries past RETENTION go.

    Also the security notice marks past their 30 days (REQ-SEC-033 part 2, lane B).
    """
    del settings
    async with database.platform_session() as platform:
        tenants = list((await platform.scalars(text("SELECT audit_tenant_ids()"))).all())
    now = datetime.now(UTC)
    for tenant in tenants:
        async with database.tenant_session(TenantContext(tenant)) as session:
            gone = await purge(session, now)
            marks = await security_notice_import.purge(session, now)
        if gone or marks:
            log.info("sign_in_log_purged", tenant_id=str(tenant), entries=gone, notice_marks=marks)


def register_siem_source() -> None:
    """Hand sign-ins to the audit module's SIEM stream (at import, like the other ports)."""
    register_sign_in_source(sign_ins_after, latest_sign_in)
