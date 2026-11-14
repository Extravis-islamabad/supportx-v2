"""GDPR person erasure: request, approve, reject, expire (D-171, ADR-052 §1).

Two people: admin A requests (reason code and text, a successor for what the person owns, files
to keep with a reason each, the person's name typed), a different admin B approves (the name
typed again). Both need a recent confirmation (the routes' RecentAuth). Refused at request,
approval and job start: yourself, the last active tenant admin, a break-glass account, a person
under legal hold; and a second open erasure of the same person. An unapproved request expires
after 7 days (the job's schedule marks it). The routes audit every step; this writes the row and
its event in one transaction (rule b) and checks If-Match on changes (rule g).

**Approval needs the mentions report (D-171 a).** It is the approver's view of where the person
is named in other people's text, and ships with S1b, which fills `report`. Until then every
approval is refused with `erasure_report_unavailable`, and the job refuses to run an erasure
without a report too: no erasure can run before S1b.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict, FieldError, NotFound, ParamValue, ValidationFailed
from app.modules.identity_access.domain import erasure as rules
from app.modules.identity_access.domain.erasure import ErasureReason, ErasureState
from app.modules.identity_access.domain.identity import UserType
from app.modules.identity_access.domain.people import clean_text
from app.modules.identity_access.events import PersonErasureChanged
from app.modules.identity_access.infra.models import PersonErasure, User
from app.modules.identity_access.service.legal_hold import person_held
from app.modules.identity_access.service.people import get_person
from app.modules.identity_access.service.roles import guard_last_admin, holds_tenant_admin
from app.shared.events import record_event
from app.shared.files.infra.models import StoredFile
from app.shared.history import stale_version
from app.shared.ids import new_id

LIST_LIMIT = 200


@dataclass(frozen=True)
class ErasureRequest:
    """What admin A asks for (validated here, not in the route)."""

    reason_code: ErasureReason
    reason_text: str | None
    successor_id: uuid.UUID
    keep_files: Mapping[uuid.UUID, str]
    confirm_name: str


def _field(name: str, code: str, params: Mapping[str, ParamValue] | None = None) -> FieldError:
    key = "errors.field.value_too_long_max" if code == "value_too_long" else f"errors.field.{code}"
    return FieldError(field=f"body.{name}", code=code, message_key=key, params=dict(params or {}))


async def refusal(session: AsyncSession, person: User, *, actor_id: uuid.UUID | None) -> str | None:
    """Why this person may not be erased now, as a code; None when nothing stands in the way.

    The same checks at request, approval and job start (ADR-052 §1).
    """
    if actor_id is not None and person.id == actor_id:
        return rules.ERASE_SELF
    if person.break_glass:
        return rules.BREAK_GLASS
    if await person_held(session, person.id):
        return rules.HELD
    if person.status == "active" and await holds_tenant_admin(session, person.id):
        try:
            await guard_last_admin(session, person.id)
        except Conflict:
            return rules.LAST_ADMIN
    return None


async def _refuse_if_needed(session: AsyncSession, person: User, actor_id: uuid.UUID) -> None:
    if person.erased_at is not None:
        raise Conflict(code=rules.ALREADY_ERASED)
    code = await refusal(session, person, actor_id=actor_id)
    if code is not None:
        raise Conflict(code=code)


async def _successor_problem(
    session: AsyncSession, person_id: uuid.UUID, successor_id: uuid.UUID
) -> str | None:
    if successor_id == person_id:
        return "erasure_successor_is_person"
    found = await session.execute(
        select(User.status, User.user_type, User.deleted_at, User.erased_at).where(
            User.id == successor_id
        )
    )
    row = found.one_or_none()
    if (
        row is None
        or row.status != "active"
        or row.deleted_at is not None
        or row.erased_at is not None
        or row.user_type == UserType.SERVICE.value
    ):
        return "erasure_successor_not_active"
    return None


async def _keep_problems(
    session: AsyncSession, person_id: uuid.UUID, keep: Mapping[uuid.UUID, str]
) -> tuple[list[FieldError], dict[str, str]]:
    """Kept files must be live uploads of the person, each with its reason."""
    problems: list[FieldError] = []
    cleaned: dict[str, str] = {}
    if len(keep) > rules.KEEP_FILES_MAX:
        problems.append(
            _field("keep_files", "erasure_keep_files_too_many", {"max": rules.KEEP_FILES_MAX})
        )
        return problems, cleaned
    theirs = set(
        await session.scalars(
            select(StoredFile.id).where(
                StoredFile.id.in_(list(keep)),
                StoredFile.created_by == person_id,
                StoredFile.deleted_at.is_(None),
            )
        )
    )
    for file_id, reason in keep.items():
        name = f"keep_files.{file_id}"
        text = clean_text(reason)
        if file_id not in theirs:
            problems.append(_field(name, "erasure_keep_file_unknown"))
        elif text is None:
            problems.append(_field(name, "erasure_keep_reason_required"))
        elif len(text) > rules.KEEP_REASON_MAX:
            problems.append(_field(name, "value_too_long", {"max_length": rules.KEEP_REASON_MAX}))
        else:
            cleaned[str(file_id)] = text
    return problems, cleaned


async def _open_erasure(session: AsyncSession, person_id: uuid.UUID) -> uuid.UUID | None:
    return await session.scalar(
        select(PersonErasure.id).where(
            PersonErasure.person_id == person_id,
            PersonErasure.state.in_([state.value for state in rules.OPEN_STATES]),
        )
    )


async def _changed(session: AsyncSession, row: PersonErasure) -> None:
    await record_event(
        session,
        PersonErasureChanged(person_id=row.person_id, state=row.state, step=row.step),  # type: ignore[arg-type]  # a checked state code
        aggregate_id=row.id,
        aggregate_version=row.version,
    )


async def request_erasure(
    session: AsyncSession,
    actor_id: uuid.UUID,
    person_id: uuid.UUID,
    request: ErasureRequest,
    *,
    now: datetime,
) -> PersonErasure:
    """Admin A asks for the person's erasure; another admin must approve it within 7 days."""
    person = await get_person(session, person_id)  # 404; 409 for a service identity
    problems: list[FieldError] = []
    if not rules.same_name(request.confirm_name, person.display_name):
        problems.append(_field("confirm_name", "erasure_confirm_name_mismatch"))
    reason_text = clean_text(request.reason_text)
    if reason_text is not None and len(reason_text) > rules.REASON_TEXT_MAX:
        problems.append(
            _field("reason_text", "value_too_long", {"max_length": rules.REASON_TEXT_MAX})
        )
    successor = await _successor_problem(session, person_id, request.successor_id)
    if successor is not None:
        problems.append(_field("successor_id", successor))
    keep_problems, keep = await _keep_problems(session, person_id, request.keep_files)
    problems += keep_problems
    if problems:
        raise ValidationFailed(errors=problems)
    await _refuse_if_needed(session, person, actor_id)
    open_id = await _open_erasure(session, person_id)
    if open_id is not None:
        raise Conflict(code=rules.ALREADY_OPEN, params={"erasure_id": str(open_id)})
    context = session.info[SESSION_TENANT_KEY]
    row = PersonErasure(
        id=new_id(),
        tenant_id=context.tenant_id,
        person_id=person_id,
        state=ErasureState.REQUESTED.value,
        step=0,
        attempts=0,
        reason_code=request.reason_code.value,
        reason_text=reason_text,
        successor_id=request.successor_id,
        keep_files=keep,
        requested_by=actor_id,
        requested_at=now,
        expires_at=rules.expires_at(now),
        counts={},
        version=1,
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError as exc:  # a parallel request for the same person won
        raise Conflict(code=rules.ALREADY_OPEN) from exc
    await _changed(session, row)
    return row


async def _locked(
    session: AsyncSession, erasure_id: uuid.UUID, expected_version: int
) -> PersonErasure:
    row = await session.scalar(
        select(PersonErasure).where(PersonErasure.id == erasure_id).with_for_update()
    )
    if row is None:
        raise NotFound(code=rules.NOT_FOUND)
    if row.version != expected_version:
        raise await stale_version(session, row, expected_version=expected_version)
    return row


async def approve(  # noqa: PLR0913 - the erasure, its version, who and the typed name, explicit
    session: AsyncSession,
    actor_id: uuid.UUID,
    erasure_id: uuid.UUID,
    *,
    expected_version: int,
    confirm_name: str,
    now: datetime,
) -> PersonErasure:
    """Admin B approves; the job then runs. Refused until the mentions report exists (S1b)."""
    row = await _locked(session, erasure_id, expected_version)
    if not rules.can("approve", ErasureState(row.state)).allowed:
        raise Conflict(code=rules.NOT_PENDING, params={"state": row.state})
    if rules.is_expired(row.requested_at, now):
        raise Conflict(code=rules.EXPIRED)
    if row.requested_by == actor_id:
        raise Conflict(code=rules.SAME_APPROVER)
    person = await get_person(session, row.person_id)
    if not rules.same_name(confirm_name, person.display_name):
        raise ValidationFailed(errors=[_field("confirm_name", "erasure_confirm_name_mismatch")])
    await _refuse_if_needed(session, person, actor_id)
    if row.report is None:
        # D-171 (a): the approver must see where the person is named in other people's text.
        # S1b builds that report; until then nothing can be approved, so nothing can run.
        raise Conflict(code=rules.REPORT_UNAVAILABLE)
    row.state = ErasureState.APPROVED.value
    row.approved_by, row.approved_at = actor_id, now
    row.version += 1
    await session.flush()
    await _changed(session, row)
    return row


async def reject(
    session: AsyncSession,
    actor_id: uuid.UUID,
    erasure_id: uuid.UUID,
    *,
    expected_version: int,
    now: datetime,
) -> PersonErasure:
    """Any admin who may erase rejects (or the requester withdraws) before the job starts."""
    row = await _locked(session, erasure_id, expected_version)
    if not rules.can("reject", ErasureState(row.state)).allowed:
        raise Conflict(code=rules.NOT_PENDING, params={"state": row.state})
    row.state = ErasureState.REJECTED.value
    row.rejected_by, row.rejected_at = actor_id, now
    row.version += 1
    await session.flush()
    await _changed(session, row)
    return row


async def expire_due(session: AsyncSession, now: datetime) -> list[PersonErasure]:
    """Requests past their 7 days become expired (the caller audits each). The tenant's."""
    rows = list(
        await session.scalars(
            select(PersonErasure)
            .where(
                PersonErasure.state == ErasureState.REQUESTED.value,
                PersonErasure.expires_at <= now,
            )
            .with_for_update(skip_locked=True)
        )
    )
    for row in rows:
        row.state = ErasureState.EXPIRED.value
        row.version += 1
    await session.flush()
    for row in rows:
        await _changed(session, row)
    return rows


async def get_erasure(session: AsyncSession, erasure_id: uuid.UUID) -> PersonErasure:
    """One erasure (404 `erasure_not_found`)."""
    row = await session.get(PersonErasure, erasure_id)
    if row is None:
        raise NotFound(code=rules.NOT_FOUND)
    return row


async def list_erasures(
    session: AsyncSession,
    *,
    states: Sequence[ErasureState] = (),
    person_id: uuid.UUID | None = None,
) -> list[PersonErasure]:
    """The tenant's newest erasures (at most LIST_LIMIT), optionally by state or person."""
    query = select(PersonErasure).order_by(PersonErasure.created_at.desc(), PersonErasure.id.desc())
    if states:
        query = query.where(PersonErasure.state.in_([state.value for state in states]))
    if person_id is not None:
        query = query.where(PersonErasure.person_id == person_id)
    return list(await session.scalars(query.limit(LIST_LIMIT)))
