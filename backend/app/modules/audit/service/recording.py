"""Writing audit entries (REQ-AUD-001 to 006; ADR-027).

Three ways in:

* `audited(action, object_type=..., object_param=...)`: a route dependency for privileged writes.
  On success it writes the entry in the request's own transaction (so the entry exists exactly
  when the change committed) and links the field history the request wrote (REQ-AUD-006). The
  route may add details through the `AuditNote` it receives. Refused and failed attempts are
  written by the error observer (`log_refusal`) in a separate transaction after the rollback.
* `audit_read(category)`: a route dependency for sensitive reads (REQ-AUD-004), at most one entry
  per person, category and object per read window (10 minutes by default).
* `record(...)`: for code without a route (sign-in, workers, the audit module itself).

Every entry goes into `audit_queue` and raises `audit.entry.recorded`, which wakes the sealer
(service/sealing.py). Personal values (IP address, user agent, free-text reasons) are stored
outside the hash in `audit_personal`, committed to by salted hashes (domain/integrity.py).
"""

import os
import uuid
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from fastapi import Depends, Request
from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY, Database, TenantSession
from app.core.logging import get_logger
from app.core.request_context import current_request_id
from app.core.tenancy import TenantContext
from app.modules.audit.domain.catalogue import (
    ALWAYS_LOGGED_READS,
    AuditActorType,
    AuditClient,
    AuditOutcome,
    ReadCategory,
    action,
    read_action,
)
from app.modules.audit.domain.integrity import SALT_SIZE, commitment, entry_hash, plain
from app.modules.audit.events import AuditAlertRaised, AuditEntryRecorded
from app.modules.audit.infra.models import AuditEntry, AuditPersonal, AuditQueueItem
from app.modules.audit.service.settings import load_settings
from app.shared.clock import Clock, system_clock
from app.shared.events import record_event
from app.shared.history import CLIENT_HEADER, recorded_change_ids
from app.shared.ids import new_id

log = get_logger(__name__)

AUDIT_ATTR = "__supportx_audit__"
READ_ATTR = "__supportx_audit_read__"
REASON_MAX = 500
USER_AGENT_MAX = 300
PROBING_ALERT_EVERY = timedelta(hours=1)
PROBING_ACTION = "audit.probing_detected"
_CLIENTS = {c.value for c in AuditClient}


@dataclass
class AuditNote:
    """What a route adds to its audit entry.

    Details hold codes, IDs and counts only (no names, no free text: those are personal data and
    go in `reason`).
    """

    object_type: str | None = None
    object_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None
    skip: bool = False  # nothing changed (an idempotent no-op): write no entry


@dataclass(frozen=True)
class RequestFacts:
    """Who and where, taken from the request."""

    client: AuditClient
    request_id: str | None
    ip: str | None
    user_agent: str | None

    @classmethod
    def of(cls, request: Request, client: str | None = None) -> "RequestFacts":
        """Facts of an HTTP request.

        The client header is informational, never a control; `client` overrides it where the
        server knows better (the session's app at sign-in).
        """
        claimed = (client or request.headers.get(CLIENT_HEADER, "")).strip().lower()
        client = AuditClient(claimed) if claimed in _CLIENTS else AuditClient.API
        agent = request.headers.get("user-agent")
        return cls(
            client=client,
            request_id=current_request_id(),
            ip=request.client.host if request.client else None,
            user_agent=agent[:USER_AGENT_MAX] if agent else None,
        )


WORKER = RequestFacts(AuditClient.WORKER, None, None, None)


def _actor(session: AsyncSession) -> tuple[AuditActorType, uuid.UUID | None]:
    context = session.info.get(SESSION_TENANT_KEY)
    if isinstance(context, TenantContext) and context.user_id is not None:
        return AuditActorType.PERSON, context.user_id
    return AuditActorType.SYSTEM, None


async def record(  # noqa: PLR0913 - every part of an entry, keyword-only
    session: AsyncSession,
    *,
    action_code: str,
    facts: RequestFacts,
    outcome: AuditOutcome = AuditOutcome.DONE,
    reason_code: str | None = None,
    object_type: str | None = None,
    object_id: str | uuid.UUID | None = None,
    details: Mapping[str, Any] | None = None,
    reason: str | None = None,
    change_id: uuid.UUID | None = None,
    actor: tuple[AuditActorType, uuid.UUID | None] | None = None,
    clock: Clock = system_clock,
) -> uuid.UUID:
    """Write one entry in the session's transaction and queue it for sealing. Returns its ID."""
    spec = action(action_code)
    context: TenantContext = session.info[SESSION_TENANT_KEY]
    actor_type, actor_id = actor or _actor(session)
    entry_id = new_id()
    occurred_at = clock.now()
    personal_data = {
        key: value
        for key, value in (
            ("ip", facts.ip),
            ("user_agent", facts.user_agent),
            ("reason", reason[:REASON_MAX] if reason else None),
        )
        if value
    }
    personal: list[AuditPersonal] = []
    commitments: dict[str, str] = {}
    if personal_data and actor_id is not None:
        salt = os.urandom(SALT_SIZE)
        commitments[str(actor_id)] = commitment(salt, personal_data)
        personal.append(
            AuditPersonal(
                tenant_id=context.tenant_id,
                entry_id=entry_id,
                subject_id=actor_id,
                salt=salt,
                data=personal_data,
                occurred_at=occurred_at,
            )
        )
    row: dict[str, Any] = {
        "id": entry_id,
        "tenant_id": context.tenant_id,
        "occurred_at": occurred_at,
        "action": spec.code,
        "category": spec.category.value,
        "module": spec.module,
        "outcome": outcome.value,
        "reason_code": reason_code,
        "actor_type": actor_type.value,
        "actor_id": actor_id,
        "on_behalf_id": None,
        "object_type": object_type,
        "object_id": str(object_id) if object_id is not None else None,
        "details": plain(dict(details or {})),
        "client": facts.client.value,
        "request_id": facts.request_id,
        "change_id": change_id,
        "personal_commitments": commitments,
    }
    session.add(AuditEntry(**row, entry_hash=entry_hash(row)))
    session.add_all(personal)
    session.add(
        AuditQueueItem(tenant_id=context.tenant_id, entry_id=entry_id, occurred_at=occurred_at)
    )
    await session.flush()
    await record_event(session, AuditEntryRecorded(entry_id=entry_id), aggregate_id=entry_id)
    return entry_id


async def record_alone(
    database: Database,
    context: TenantContext,
    *,
    action_code: str,
    facts: RequestFacts,
    **values: Any,  # noqa: ANN401 - record()'s keyword arguments
) -> uuid.UUID:
    """`record` in a transaction of its own (sign-in, refusals after a rollback, workers)."""
    async with database.tenant_session(context) as session:
        return await record(session, action_code=action_code, facts=facts, **values)


# --- route dependencies ------------------------------------------------------------------------


def audited(
    action_code: str,
    *,
    object_type: str | None = None,
    object_param: str | None = None,
    detail_params: tuple[str, ...] = (),
) -> Any:  # noqa: ANN401 - FastAPI's Depends marker
    """Route dependency for a privileged write.

    Use it as:

        note: Annotated[AuditNote, audited("role.updated", object_type="role")]
        @router.post(..., dependencies=[audited("site.member_added", ...)])

    `object_param` names the path parameter holding the object ID; `detail_params` are path
    parameters copied into the details (IDs only). Function scope: the entry is written after
    the endpoint and before the request's transaction commits.
    """
    action(action_code)  # unknown actions fail at import time, not at the first request

    async def dependency(request: Request, session: TenantSession) -> AsyncIterator[AuditNote]:
        note = AuditNote(
            object_type=object_type,
            object_id=request.path_params.get(object_param) if object_param else None,
            details={name: request.path_params.get(name) for name in detail_params},
        )
        yield note  # an exception here propagates: refusals are logged by the error observer
        if note.skip:
            return
        change_ids = recorded_change_ids(session)
        await record(
            session,
            action_code=action_code,
            facts=RequestFacts.of(request),
            object_type=note.object_type,
            object_id=note.object_id,
            details=note.details,
            reason=note.reason,
            change_id=change_ids[-1] if change_ids else None,
        )

    setattr(dependency, AUDIT_ATTR, AuditRouteSpec(action_code, object_type, object_param))
    return Depends(dependency, scope="function")


@dataclass(frozen=True)
class AuditRouteSpec:
    """What the error observer needs to log a refused attempt at an audited route."""

    action_code: str
    object_type: str | None
    object_param: str | None


def audit_read(
    category: ReadCategory, *, object_type: str | None = None, object_param: str | None = None
) -> Any:  # noqa: ANN401 - FastAPI's Depends marker
    """Route dependency for a sensitive read (REQ-AUD-004), coalesced per read window.

    Use it in `dependencies=[audit_read(ReadCategory.ACCESS_INFORMATION)]`.
    """
    spec = read_action(category)

    async def dependency(request: Request, session: TenantSession) -> AsyncIterator[None]:
        yield
        settings = await load_settings(session)
        if category not in ALWAYS_LOGGED_READS and category.value not in settings.read_categories:
            return
        actor_type, actor_id = _actor(session)
        object_id = request.path_params.get(object_param) if object_param else None
        since = system_clock.now() - timedelta(minutes=settings.read_window_minutes)
        if await _read_logged_since(session, spec.code, actor_id, object_id, since):
            return
        await record(
            session,
            action_code=spec.code,
            facts=RequestFacts.of(request),
            object_type=object_type,
            object_id=object_id,
            actor=(actor_type, actor_id),
        )

    setattr(dependency, READ_ATTR, category)
    return Depends(dependency, scope="function")


async def _read_logged_since(
    session: AsyncSession,
    action_code: str,
    actor_id: uuid.UUID | None,
    object_id: str | None,
    since: datetime,
) -> bool:
    query = select(
        exists().where(
            AuditEntry.actor_id == actor_id if actor_id else AuditEntry.actor_id.is_(None),
            AuditEntry.action == action_code,
            AuditEntry.occurred_at >= since,
            AuditEntry.object_id == object_id if object_id else AuditEntry.object_id.is_(None),
        )
    )
    return bool((await session.execute(query)).scalar())


# --- refused and failed attempts (REQ-AUD-005) ---------------------------------------------------

REFUSED_CODES = frozenset(
    {"permission_denied", "entitlement_required", "read_only_mode", "not_entitled", "not_found"}
)


def route_spec(request: Request) -> AuditRouteSpec | None:
    """The audit spec of the route that handled `request`, if it is audited."""
    route = request.scope.get("route")
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return None
    pending = list(dependant.dependencies)
    while pending:
        dependency = pending.pop()
        spec = getattr(dependency.call, AUDIT_ATTR, None)
        if isinstance(spec, AuditRouteSpec):
            return spec
        pending.extend(dependency.dependencies)
    return None


async def log_refusal(request: Request, status: int, code: str) -> None:
    """Error observer: write a refused/failed entry for an audited route, then check probing."""
    spec = route_spec(request)
    context = getattr(request.state, "tenant_context", None)
    database: Database | None = getattr(request.app.state, "db", None)
    if spec is None or not isinstance(context, TenantContext) or database is None:
        return  # not audited, or nobody signed in (401 happens before any tenant is known)
    outcome = AuditOutcome.REFUSED if code in REFUSED_CODES else AuditOutcome.FAILED
    facts = RequestFacts.of(request)
    async with database.tenant_session(context) as session:
        await record(
            session,
            action_code=spec.action_code,
            facts=facts,
            outcome=outcome,
            reason_code=code,
            object_type=spec.object_type,
            object_id=request.path_params.get(spec.object_param) if spec.object_param else None,
            details={"status": status},
        )
        if outcome is AuditOutcome.REFUSED and context.user_id is not None:
            await _check_probing(session, context.user_id, facts)


async def _check_probing(session: AsyncSession, actor_id: uuid.UUID, facts: RequestFacts) -> None:
    """N refusals by one person within the window raise one alert per hour (Appendix A)."""
    settings = await load_settings(session)
    now = system_clock.now()
    refusals = await session.scalar(
        select(func.count())
        .select_from(AuditEntry)
        .where(
            AuditEntry.actor_id == actor_id,
            AuditEntry.outcome == AuditOutcome.REFUSED.value,
            AuditEntry.occurred_at >= now - timedelta(minutes=settings.refusal_window_minutes),
        )
    )
    if (refusals or 0) < settings.refusal_threshold:
        return
    alerted = await session.scalar(
        select(
            exists().where(
                AuditEntry.action == PROBING_ACTION,
                AuditEntry.object_id == str(actor_id),
                AuditEntry.occurred_at >= now - PROBING_ALERT_EVERY,
            )
        )
    )
    if alerted:
        return
    entry_id = await record(
        session,
        action_code=PROBING_ACTION,
        facts=facts,
        object_type="user",
        object_id=actor_id,
        details={"refusals": int(refusals or 0), "window_minutes": settings.refusal_window_minutes},
        actor=(AuditActorType.SYSTEM, None),
    )
    await record_event(
        session,
        AuditAlertRaised(alert="probing", entry_id=entry_id, actor_id=actor_id),
        aggregate_id=entry_id,
    )
    log.warning("audit_probing_detected", actor_id=str(actor_id), refusals=refusals)
