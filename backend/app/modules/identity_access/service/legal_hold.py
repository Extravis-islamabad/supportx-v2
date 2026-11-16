"""Legal hold on a person (H1, D-171; REQ-ADM-105).

A person under legal hold is never erased: `person_held` is the one check, used at the erasure's
request, approval and job start (ADR-052 §2). WP-064 S3 extends this same check with
record-level holds. Setting and lifting it needs `audit.manage_holds` (the route audits each with
the reason); both are ordinary person saves (If-Match, field history, `user.updated`).
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, FieldError, ParamValue, ValidationFailed
from app.modules.identity_access.domain import erasure as rules
from app.modules.identity_access.domain.people import clean_text
from app.modules.identity_access.infra.models import User
from app.modules.identity_access.service.people import get_person, save_marks


async def person_held(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """Whether the person is under legal hold (the session's tenant).

    Until WP-064 S3 adds record-level holds this person-level check is the whole hold, and it
    fails closed (ADR-052 §2): a person it cannot find counts as held, so nothing is erased on
    a doubt.
    """
    found = await session.execute(select(User.legal_hold_at).where(User.id == user_id))
    row = found.one_or_none()
    return row is None or row.legal_hold_at is not None


def _reason(reason: object) -> str:
    text = clean_text(reason)
    if text is None:
        code = "required"
    elif len(text) > rules.REASON_TEXT_MAX:
        code = "value_too_long"
    else:
        return text
    params: dict[str, ParamValue] = (
        {"max_length": rules.REASON_TEXT_MAX} if code == "value_too_long" else {}
    )
    message = "errors.field.value_too_long_max" if params else f"errors.field.{code}"
    raise ValidationFailed(
        errors=[FieldError(field="body.reason", code=code, message_key=message, params=params)]
    )


async def set_hold(  # noqa: PLR0913 - the person, its version, who, why and when, explicit
    session: AsyncSession,
    actor_id: uuid.UUID | None,
    user_id: uuid.UUID,
    reason: object,
    *,
    expected_version: int,
    now: datetime,
) -> User:
    """Put the person on hold, or change the reason of a hold already in place."""
    text = _reason(reason)
    person = await get_person(session, user_id)
    if person.erased_at is not None:
        raise Conflict(code=rules.ALREADY_ERASED)
    values: dict[str, object] = {"legal_hold_reason": text}
    if person.legal_hold_at is None:
        values.update(legal_hold_at=now, legal_hold_by=actor_id)
    return await save_marks(session, user_id, expected_version=expected_version, values=values)


async def lift_hold(session: AsyncSession, user_id: uuid.UUID, *, expected_version: int) -> User:
    """Lift the hold (409 `legal_hold_not_set` when there is none)."""
    person = await get_person(session, user_id)
    if person.legal_hold_at is None:
        raise Conflict(code=rules.HOLD_NOT_SET)
    return await save_marks(
        session,
        user_id,
        expected_version=expected_version,
        values={"legal_hold_at": None, "legal_hold_by": None, "legal_hold_reason": None},
    )
