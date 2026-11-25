"""Approval delegations (WP-047a S3b; REQ-SR-035).

    GET  /approval-delegations              yours (as delegator or delegate); ?delegator_id=
                                            someone's, with requests.manage_delegations
    POST /approval-delegations              set one (Idempotency-Key); yours by default
    PATCH /approval-delegations/{id}        change its dates, delegate or reason (If-Match)
    POST /approval-delegations/{id}/end     end it now (If-Match); pending approvals move back

Signed in is enough for one's own; someone else's needs `requests.manage_delegations`.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_signed_in
from app.core.database import TenantSession
from app.modules.audit import AuditNote, RequestFacts, audited
from app.modules.identity_access import Subject
from app.modules.work_items.api.routes import RESPONSES
from app.modules.work_items.domain.delegations import REASON_MAX
from app.modules.work_items.infra.models import ApprovalDelegation
from app.modules.work_items.service import delegations as service
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.ratelimit import rate_limit

router = APIRouter(
    prefix="/approval-delegations",
    tags=["approvals"],
    dependencies=[Depends(rate_limit("work_items"))],
    responses=RESPONSES,
)
SignedIn = Annotated[Subject, Depends(require_signed_in())]
Created_ = Annotated[AuditNote, audited(service.AUDIT_CREATED, object_type="approval_delegation")]


class DelegationOut(BaseModel):
    """One delegation: who, to whom, when, and whether it is over."""

    id: uuid.UUID
    delegator_id: uuid.UUID
    delegate_id: uuid.UUID
    starts_at: datetime
    ends_at: datetime
    ended_at: datetime | None = Field(description="Set when it was ended early or expired.")
    reason: str | None
    version: int
    created_at: datetime

    @classmethod
    def of(cls, row: ApprovalDelegation) -> "DelegationOut":
        """From the row."""
        return cls(
            id=row.id,
            delegator_id=row.delegator_id,
            delegate_id=row.delegate_id,
            starts_at=row.starts_at,
            ends_at=row.ends_at,
            ended_at=row.ended_at,
            reason=row.reason,
            version=row.version,
            created_at=row.created_at,
        )


class DelegationsOut(BaseModel):
    """Delegations, newest start first."""

    items: list[DelegationOut]


class DelegationIn(BaseModel):
    """A delegation to set: yours unless `delegator_id` names someone else."""

    model_config = ConfigDict(extra="forbid")

    delegator_id: uuid.UUID | None = None
    delegate_id: uuid.UUID
    starts_at: datetime
    ends_at: datetime = Field(description="At most 90 days after the start.")
    reason: str | None = Field(default=None, max_length=REASON_MAX)


class DelegationPatch(BaseModel):
    """What changes; leave out what stays."""

    model_config = ConfigDict(extra="forbid")

    delegate_id: uuid.UUID | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    reason: str | None = Field(default=None, max_length=REASON_MAX)


@router.get("", summary="Approval delegations")
async def list_delegations(
    session: TenantSession,
    subject: SignedIn,
    delegator_id: Annotated[uuid.UUID | None, Query()] = None,
) -> DelegationsOut:
    """Yours by default; someone's with requests.manage_delegations."""
    rows = await service.list_for(session, subject, delegator_id)
    return DelegationsOut(items=[DelegationOut.of(r) for r in rows])


@router.post(
    "",
    summary="Set an approval delegation",
    status_code=status.HTTP_201_CREATED,
    response_model=DelegationOut,
)
async def create_delegation(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    body: DelegationIn,
    session: TenantSession,
    subject: SignedIn,
    idempotency: Idempotency,
    request: Request,
    note: Created_,
) -> Response:
    """New request approvals for the delegator go to the delegate while it is active (AC1).

    Audited here, refused attempts included (a manager naming themself someone's delegate).
    """
    # Named before the service runs (lane B's #612 nit, possible since #625): a refused attempt's
    # entry says whom it named, under `requested` (unverified IDs only), as a done one does.
    note.details = {
        "delegator_id": str(body.delegator_id or subject.user_id),
        "delegate_id": str(body.delegate_id),
    }

    async def run() -> Created:
        row = await service.create(
            session,
            subject,
            delegator_id=body.delegator_id,
            delegate_id=body.delegate_id,
            starts_at=body.starts_at,
            ends_at=body.ends_at,
            reason=body.reason,
            facts=RequestFacts.of(request),
        )
        note.object_id = str(row.id)
        return Created(body=DelegationOut.of(row), headers={"ETag": f'"{row.version}"'})

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.patch("/{delegation_id}", summary="Change an approval delegation")
async def change_delegation(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    delegation_id: uuid.UUID,
    body: DelegationPatch,
    version: ExpectedVersion,
    session: TenantSession,
    subject: SignedIn,
    request: Request,
    response: Response,
) -> DelegationOut:
    """Not once it has ended; a new delegate takes over, and the old one's pending go back."""
    row = await service.change(
        session,
        subject,
        delegation_id,
        body.model_dump(exclude_unset=True),
        expected_version=version,
        facts=RequestFacts.of(request),
    )
    set_etag(response, row.version)
    return DelegationOut.of(row)


@router.post("/{delegation_id}/end", summary="End an approval delegation now")
async def end_delegation(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    delegation_id: uuid.UUID,
    version: ExpectedVersion,
    session: TenantSession,
    subject: SignedIn,
    request: Request,
    response: Response,
) -> DelegationOut:
    """AC3: the approvals still pending move back to the delegator."""
    row = await service.end(
        session, subject, delegation_id, expected_version=version, facts=RequestFacts.of(request)
    )
    set_etag(response, row.version)
    return DelegationOut.of(row)


__all__ = ["router"]
