"""A person's cost per hour over HTTP (REQ-INC-068; service/cost_rates.py). No logic here.

`/users/{id}/cost-rates`: reading needs `users.view_cost_rates`; setting, changing and removing
need `users.manage_cost_rates` too. Creates take an Idempotency-Key, changes If-Match. Every
change is audited as `user.cost_rate_changed` with the rate and start before and after, and every
read as `user.cost_rate_viewed` (D-164).
Amounts are exact decimals (strings in JSON), in the currency each rate names.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.core.errors import ProblemDetail
from app.modules.audit import AuditNote, audited
from app.modules.identity_access.domain.cost_rates import RateState
from app.modules.identity_access.domain.policy import Subject
from app.modules.identity_access.service import cost_rates as service
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.ratelimit import rate_limit
from app.shared.history import source_of

router = APIRouter(
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(rate_limit("users"))],
    responses={
        401: {"model": ProblemDetail, "description": "Not signed in."},
        403: {"model": ProblemDetail, "description": "Missing permission."},
        404: {"model": ProblemDetail, "description": "user_not_found, cost_rate_not_found"},
        409: {"model": ProblemDetail, "description": "not_a_person (a service identity)."},
    },
)
View = Annotated[Subject, Depends(require_permission(service.VIEW))]
Manage = Annotated[Subject, Depends(require_permission(service.MANAGE))]
WRITE: dict[int | str, dict[str, Any]] = {
    409: {
        "model": ProblemDetail,
        "description": "version_conflict, cost_rate_date_taken, cost_rate_superseded, not_a_person",
    },
    428: {"model": ProblemDetail, "description": "If-Match missing."},
}
Rate = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]


class CostRateOut(BaseModel):
    """One rate: from `effective_from` until the next rate starts."""

    id: uuid.UUID
    user_id: uuid.UUID
    rate: Decimal = Field(description="Cost per hour.")
    currency: str = Field(description="The tenant's base currency when the rate was set.")
    effective_from: datetime
    state: RateState = Field(description="current, future (upcoming) or past (superseded).")
    created_at: datetime
    created_by: uuid.UUID | None
    updated_at: datetime
    version: int = Field(description="Send it back as If-Match to change or remove the rate.")

    @classmethod
    def of(cls, view: service.RateView) -> "CostRateOut":
        """From the service's view of a rate."""
        row = view.row
        return cls(
            id=row.id,
            user_id=row.user_id,
            rate=row.rate,
            currency=row.currency,
            effective_from=row.effective_from,
            state=view.state,
            created_at=row.created_at,
            created_by=row.created_by,
            updated_at=row.updated_at,
            version=row.version,
        )


class CostRatesOut(BaseModel):
    """A person's rates, newest start first, and the one in force now."""

    user_id: uuid.UUID
    currency: str = Field(description="The tenant's base currency: a new rate is set in it.")
    current: CostRateOut | None = Field(description="In force now; null when none has started.")
    items: list[CostRateOut]


class CostRateIn(BaseModel):
    """A new rate from a moment on (with its time zone)."""

    model_config = ConfigDict(extra="forbid")

    rate: Rate
    effective_from: AwareDatetime


class CostRatePatch(BaseModel):
    """What to change of the current or an upcoming rate (only the fields sent)."""

    model_config = ConfigDict(extra="forbid")

    rate: Rate | None = None
    effective_from: AwareDatetime | None = None


def _out(person: service.PersonRates) -> CostRatesOut:
    return CostRatesOut(
        user_id=person.user_id,
        currency=person.currency,
        current=CostRateOut.of(person.current) if person.current else None,
        items=[CostRateOut.of(v) for v in person.rates],
    )


async def _one(session: TenantSession, subject: Subject, change: service.RateChange) -> CostRateOut:
    """The changed rate as the list shows it now (its state among the person's rates)."""
    person = await service.list_rates(session, subject, change.rate.user_id)
    view = next((v for v in person.rates if v.row.id == change.rate.id), None)
    return CostRateOut.of(view or service.RateView(change.rate, RateState.PAST))


def _note(note: AuditNote, change: service.RateChange) -> None:
    """The audit entry: which rate, and its amount and start before and after."""
    note.details = {
        "rate_id": str(change.rate.id),
        "change": change.action,
        "currency": change.rate.currency,
        "old_rate": None if change.old_rate is None else str(change.old_rate),
        "new_rate": None if change.new_rate is None else str(change.new_rate),
        "old_effective_from": (
            change.old_effective_from.isoformat() if change.old_effective_from else None
        ),
        "new_effective_from": (
            change.new_effective_from.isoformat() if change.new_effective_from else None
        ),
    }


Audited = Annotated[
    AuditNote, audited("user.cost_rate_changed", object_type="user", object_param="user_id")
]


# D-164 (Haider, 2026-11-12): every view of a person's rates is audited, one entry per person
# read: the person card's load and each of its live refetches. Which rates were shown, never
# their amounts. The worklog cost snapshot (`cost_rate`, the port) reads no route and is not a
# view.
Viewed = Annotated[
    AuditNote, audited("user.cost_rate_viewed", object_type="user", object_param="user_id")
]


@router.get("/{user_id}/cost-rates", summary="A person's cost per hour")
async def list_cost_rates(
    user_id: uuid.UUID, session: TenantSession, subject: View, note: Viewed
) -> CostRatesOut:
    """Every live rate, newest start first, and the one in force now (`users.view_cost_rates`).

    Audited as `user.cost_rate_viewed` (D-164).
    """
    person = await service.list_rates(session, subject, user_id)
    note.details = {
        "rate_ids": [str(v.row.id) for v in person.rates],
        "current_rate_id": str(person.current.row.id) if person.current else None,
    }
    return _out(person)


@router.post(
    "/{user_id}/cost-rates",
    summary="Set a new cost per hour",
    status_code=status.HTTP_201_CREATED,
    response_model=CostRateOut,
    responses={**WRITE, 201: {"model": CostRateOut, "description": "Created (or replayed)."}},
)
async def add_cost_rate(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    user_id: uuid.UUID,
    body: CostRateIn,
    session: TenantSession,
    subject: Manage,
    idempotency: Idempotency,
    request: Request,
    note: Audited,
) -> Response:
    """From `effective_from` on (past, now or later), in the base currency. Idempotency-Key."""
    note.skip = True  # a replay changes nothing

    async def run() -> Created:
        change = await service.set_rate(
            session,
            subject,
            user_id,
            rate=body.rate,
            effective_from=body.effective_from,
            source=source_of(request),
        )
        note.skip = False
        _note(note, change)
        out = await _one(session, subject, change)
        return Created(body=out, headers={"ETag": f'"{change.rate.version}"'})

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.patch(
    "/{user_id}/cost-rates/{rate_id}",
    summary="Change the current or an upcoming cost per hour",
    responses=WRITE,
)
async def patch_cost_rate(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    user_id: uuid.UUID,
    rate_id: uuid.UUID,
    body: CostRatePatch,
    session: TenantSession,
    subject: Manage,
    version: ExpectedVersion,
    response: Response,
    request: Request,
    note: Audited,
) -> CostRateOut:
    """Only the fields sent (If-Match). A superseded rate stays: set a new one instead."""
    change = await service.change_rate(
        session,
        subject,
        user_id,
        rate_id,
        expected_version=version,
        rate=body.rate,
        effective_from=body.effective_from,
        source=source_of(request),
    )
    _note(note, change)
    note.skip = change.old_rate == change.new_rate and (
        change.old_effective_from == change.new_effective_from
    )
    set_etag(response, change.rate.version)
    return await _one(session, subject, change)


@router.delete(
    "/{user_id}/cost-rates/{rate_id}",
    summary="Remove a cost per hour",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WRITE,
)
async def delete_cost_rate(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    user_id: uuid.UUID,
    rate_id: uuid.UUID,
    session: TenantSession,
    subject: Manage,
    version: ExpectedVersion,
    request: Request,
    note: Audited,
) -> None:
    """Removed (If-Match); costs already worked out keep the rate they used."""
    change = await service.remove_rate(
        session, subject, user_id, rate_id, expected_version=version, source=source_of(request)
    )
    _note(note, change)
