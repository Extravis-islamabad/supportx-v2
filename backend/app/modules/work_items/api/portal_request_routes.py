"""The portal's service requests for requesters over HTTP (WP-030 D9; REQ-SR-051, -062).

    GET /api/v1/portal/service-requests             own (or a wider reach held), open first
    GET /api/v1/portal/service-requests/{id}        one: its item and answers, plain status
    GET /api/v1/portal/service-requests/{id}/steps  fulfilment progress, internal names hidden
    POST …/{id}/resolution/confirm | reject         received it, or not done (REQ-SR-059)
    GET  …/{id}/conversation                        public replies and notes (WP-047a S3a)
    POST …/{id}/replies                             the requester's public reply (Idempotency-Key)

The same reach and plain-status rules as the portal's incidents (service/portal.py, D-129).
Approvals (respecting "hide approvals from requesters") and withdrawal use the engine's own
routes, which apply the requester's rules (`/service-requests/{id}/approvals`, `/withdraw`).
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, Field

from app.core.authorization import require_signed_in
from app.core.database import TenantSession
from app.modules.identity_access import PolicyService, Subject, get_policy
from app.modules.work_items.api.portal_routes import (
    PortalConversationOut,
    PortalEntryOut,
    PortalRejectIn,
    PortalReplyIn,
)
from app.modules.work_items.domain import service_requests as sr_rules
from app.modules.work_items.domain.conversation import EntryKind
from app.modules.work_items.domain.portal import PortalReach, PortalStatus
from app.modules.work_items.domain.types import SERVICE_REQUEST
from app.modules.work_items.service import parts
from app.modules.work_items.service import portal as service
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.listing import ListQuery, list_query
from app.shared.api.ratelimit import rate_limit
from app.shared.history import source_of

router = APIRouter(
    prefix="/portal/service-requests",
    tags=["portal"],
    dependencies=[Depends(rate_limit("work_items"))],
)
SignedIn = Annotated[Subject, Depends(require_signed_in())]
Query_ = Annotated[
    ListQuery, Depends(list_query(service.FIELDS, extra_parameters=frozenset({"state"})))
]


class PortalRequestOut(BaseModel):
    """A service request as its requester's side sees it."""

    id: uuid.UUID
    display_id: str
    subject: str
    portal_status: PortalStatus
    reach: PortalReach
    requester_id: uuid.UUID
    on_behalf_of_id: uuid.UUID | None = None
    catalog_item_id: uuid.UUID | None = None
    answers: dict[str, Any] = Field(default_factory=dict)
    approval_status: str | None = None
    # WP-047a S1: how many (REQ-SR-014), when needed and when expected (REQ-SR-015).
    quantity: int | None = None
    needed_by: datetime | None = None
    expected_delivery_at: datetime | None = Field(
        default=None, description="From the item's SLA; updated when approval completes."
    )
    needed_earlier: bool = False
    created_at: datetime
    updated_at: datetime
    resolution: str | None = None
    resolution_due_at: datetime | None = Field(
        default=None,
        description="Expected delivery, when the tenant shows it to requesters (WP-028 D5).",
    )
    version: int


class PortalRequestPage(BaseModel):
    """One page of the requester's service requests."""

    items: list[PortalRequestOut]
    next_cursor: str | None
    has_more: bool


class PortalStepOut(BaseModel):
    """One fulfilment step: its name, unless it is internal (REQ-SR-051 AC2)."""

    position: int
    title: str | None = Field(description="None for an internal step: 'step n of m' only.")
    done: bool


class PortalStepsOut(BaseModel):
    """How far the request's fulfilment is."""

    items: list[PortalStepOut]
    done: int
    total: int


def _out(found: service.PortalRecord) -> PortalRequestOut:
    r = found.record
    return PortalRequestOut(
        id=r.id,
        display_id=r.display_id,
        subject=r.subject,
        portal_status=found.status,
        reach=found.reach,
        requester_id=r.requester_id,
        on_behalf_of_id=r.on_behalf_of_id,
        catalog_item_id=r.catalog_item_id,
        answers=dict(found.answers),  # filtered by the service: the requester's questions only
        approval_status=r.approval_status,
        quantity=r.quantity,
        needed_by=r.needed_by,
        expected_delivery_at=r.expected_delivery_at,
        needed_earlier=sr_rules.needed_earlier(r.needed_by, r.expected_delivery_at),
        created_at=r.created_at,
        updated_at=r.updated_at,
        resolution=r.resolution,
        resolution_due_at=r.resolution_due_at if "resolution_due_at" in found.fields else None,
        version=r.version,
    )


@router.get("", summary="Your service requests in the portal")
async def list_portal_requests(
    session: TenantSession,
    query: Query_,
    subject: SignedIn,
    state: Annotated[service.PortalState | None, Query(description="Open or closed.")] = None,
) -> PortalRequestPage:
    """Own requests, plus those of a wider reach the person holds (REQ-SR-062)."""
    rows, page = await service.list_records(
        session, subject, query, wtype=SERVICE_REQUEST, state=state
    )
    return PortalRequestPage(
        items=[_out(r) for r in rows], next_cursor=page.next_cursor, has_more=page.has_more
    )


@router.get("/{record_id}", summary="One of your service requests in the portal")
async def get_portal_request(
    record_id: uuid.UUID, session: TenantSession, subject: SignedIn
) -> PortalRequestOut:
    """Out of reach reads as not found (404), never forbidden."""
    return _out(await service.get_record(session, subject, record_id, SERVICE_REQUEST))


class PortalRequestAgainOut(BaseModel):
    """Request again (REQ-SR-016): the item's form with the earlier answers."""

    catalog_item_id: uuid.UUID
    available: bool = Field(description="False when the item can no longer be requested (AC3).")
    reason: str | None = Field(
        default=None,
        description="Why not, a label code (errors.<code>): catalog_item_retired, "
        "catalog_item_unavailable.",
    )
    answers: dict[str, Any] = Field(
        description="The earlier answers the form still asks; attachments never copied (AC1)."
    )
    dropped: list[str] = Field(
        description="Keys of earlier answers to questions the form no longer has (AC2)."
    )


@router.get("/{record_id}/request-again", summary="Request this again")
async def portal_request_again(
    record_id: uuid.UUID, session: TenantSession, subject: SignedIn
) -> PortalRequestAgainOut:
    """Your own past request's item, prefilled; nothing is created until you submit the form."""
    found = await service.request_again(session, subject, record_id)
    return PortalRequestAgainOut(
        catalog_item_id=found.item_id,
        available=found.available,
        reason=found.reason,
        answers=dict(found.answers),
        dropped=list(found.dropped),
    )


@router.get("/{record_id}/steps", summary="The fulfilment progress of your service request")
async def portal_request_steps(
    record_id: uuid.UUID, session: TenantSession, subject: SignedIn
) -> PortalStepsOut:
    """The plan's steps in order; an internal one shows no name (REQ-SR-051 AC2)."""
    await service.get_record(session, subject, record_id, SERVICE_REQUEST)  # 404 out of reach
    planned = [t for t in await parts.tasks_of(session, record_id) if t.from_plan]
    live = [t for t in planned if t.status != "canceled"]
    return PortalStepsOut(
        items=[
            PortalStepOut(
                position=i + 1, title=None if t.internal else t.title, done=t.status == "done"
            )
            for i, t in enumerate(live)
        ],
        done=sum(t.status == "done" for t in live),
        total=len(live),
    )


@router.post("/{record_id}/resolution/confirm", summary="Confirm you received it")
async def portal_request_confirm(
    record_id: uuid.UUID, session: TenantSession, subject: SignedIn, request: Request
) -> PortalRequestOut:
    """It is fulfilled for you (REQ-SR-059, as WP-020f); 409 `not_resolved` otherwise."""
    return _out(
        await service.answer_resolution(
            session,
            subject,
            record_id,
            confirmed=True,
            comment=None,
            source=source_of(request),
            wtype=SERVICE_REQUEST,
        )
    )


@router.post("/{record_id}/resolution/reject", summary="Say it is not done")
async def portal_request_reject(
    record_id: uuid.UUID,
    body: PortalRejectIn,
    session: TenantSession,
    subject: SignedIn,
    request: Request,
) -> PortalRequestOut:
    """It reopens; the comment is your public reply (REQ-SR-059)."""
    return _out(
        await service.answer_resolution(
            session,
            subject,
            record_id,
            confirmed=False,
            comment=body.comment,
            source=source_of(request),
            wtype=SERVICE_REQUEST,
        )
    )


# WP-047a S3a (REQ-SR-037 AC1): an approver's question to the requester is a public reply, so the
# portal shows the request's public conversation and takes the requester's answer, as it does
# for incidents and changes.
@router.get("/{record_id}/conversation", summary="The public conversation of your request")
async def portal_request_conversation(
    record_id: uuid.UUID, session: TenantSession, subject: SignedIn
) -> PortalConversationOut:
    """Public replies and notes only; private notes never."""
    entries = await service.conversation(session, subject, record_id, SERVICE_REQUEST)
    return PortalConversationOut(
        items=[
            PortalEntryOut(
                id=e.id,
                kind=EntryKind(e.kind),
                body=e.body,
                created_at=e.created_at,
                author_name=e.author_name,
                by_you=e.by_you,
            )
            for e in entries
        ]
    )


@router.post(
    "/{record_id}/replies",
    summary="Reply on your request",
    status_code=status.HTTP_201_CREATED,
    response_model=PortalRequestOut,
)
async def portal_request_reply(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    record_id: uuid.UUID,
    body: PortalReplyIn,
    session: TenantSession,
    subject: SignedIn,
    request: Request,
    policy: Annotated[PolicyService, Depends(get_policy)],
    idempotency: Idempotency,
) -> Response:
    """A public reply in your name, on your own request only (Idempotency-Key)."""

    async def run() -> Created:
        await service.reply(
            session,
            subject,
            record_id,
            body=body.body,
            source=source_of(request),
            holders=policy,
            wtype=SERVICE_REQUEST,
        )
        return Created(
            body=_out(await service.get_record(session, subject, record_id, SERVICE_REQUEST))
        )

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


__all__ = ["router"]
