"""The portal's incidents for requesters over HTTP (WP-028; ~/Desktop/wp-028-plan.md D1).

    GET /api/v1/portal/incidents            "My requests": own, or one reach as a filter
    GET /api/v1/portal/incidents/{id}       one record in the viewer's reach
    GET /api/v1/portal/incidents/templates  the forms the portal offers (requester fields only)
    POST /api/v1/portal/incidents           report an issue (REQ-INC-028), Idempotency-Key
    GET  .../{id}/conversation              public replies and notes only
    POST .../{id}/replies                   the requester's reply (own records only)
    POST .../{id}/resolution/confirm|reject the requester's answer to a fix (WP-020f)

Only signed-in people; what they see is decided in `service/portal.py` (the one scope check).
Responses carry the allow-listed fields only: a field the record's template hides, and every
staff-only field, is absent, never null-with-a-value-elsewhere.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_signed_in
from app.core.database import TenantSession
from app.modules.identity_access import PolicyService, Subject, get_policy
from app.modules.work_items.api.routes import RESOLUTION_MAX, RESPONSES
from app.modules.work_items.domain.classification import Impact, Urgency
from app.modules.work_items.domain.conversation import EntryKind
from app.modules.work_items.domain.portal import PortalReach, PortalStatus, requester_fillable
from app.modules.work_items.domain.templates import (
    IMPACT_DETAILS_MAX,
    TemplateField,
    rules_from_json,
)
from app.modules.work_items.domain.types import DESCRIPTION_MAX, SUBJECT_MAX
from app.modules.work_items.infra.models import WorkItemTemplate
from app.modules.work_items.service import portal as service
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.listing import ListQuery, list_query
from app.shared.api.ratelimit import rate_limit
from app.shared.history import source_of

SignedIn = Annotated[Subject, Depends(require_signed_in())]
Query_ = Annotated[
    ListQuery,
    Depends(list_query(service.FIELDS, extra_parameters=frozenset({"reach", "state", "q"}))),
]


class PortalIncidentOut(BaseModel):
    """An incident as its requester's side sees it (fields the template hides are absent)."""

    id: uuid.UUID
    display_id: str
    subject: str
    portal_status: PortalStatus
    reach: PortalReach = Field(description="Why you see it: own, or a wider reach you hold.")
    requester_id: uuid.UUID
    on_behalf_of_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None
    closed_at: datetime | None = None
    resolution: str | None = None
    version: int
    description: str | None = None
    category_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    impact: str | None = None
    urgency: str | None = None
    impact_details: str | None = None


class PortalIncidentPage(BaseModel):
    """One page of "My requests"."""

    items: list[PortalIncidentOut]
    next_cursor: str | None
    has_more: bool
    estimated_total: int | None = None


class PortalFieldOut(BaseModel):
    """A field the requester fills in on this form."""

    name: TemplateField
    required: bool


class PortalTemplateOut(BaseModel):
    """A form the portal offers: its name and the requester's fields, nothing staff-side."""

    id: uuid.UUID
    code: str | None = Field(description="Seeded templates: labelled by the UI from this code.")
    labels: dict[str, str] | None
    description: str | None
    is_default: bool
    fields: list[PortalFieldOut]

    @classmethod
    def of(cls, row: WorkItemTemplate) -> "PortalTemplateOut":
        """The template as the portal shows it, fields in the form's order."""
        rules = rules_from_json(row.field_rules)
        fillable = requester_fillable(rules)
        return cls(
            id=row.id,
            code=row.code,
            labels=row.labels,
            description=row.description,
            is_default=row.is_default,
            fields=[
                PortalFieldOut(name=f, required=rules[f.value].required)
                for f in TemplateField
                if f.value in fillable
            ],
        )


class PortalIncidentIn(BaseModel):
    """What a requester sends; the template decides which of these they may fill in."""

    model_config = ConfigDict(extra="forbid")  # a staff field is refused, never ignored

    template_id: uuid.UUID | None = Field(default=None, description="Default: the first offered.")
    subject: str = Field(max_length=SUBJECT_MAX * 2)
    description: str | None = Field(
        default=None, max_length=DESCRIPTION_MAX * 2, description="Rich text (HTML), sanitised."
    )
    category_id: uuid.UUID | None = None
    impact: Impact | None = None
    urgency: Urgency | None = None
    impact_details: str | None = Field(default=None, max_length=IMPACT_DETAILS_MAX * 2)


class PortalEntryOut(BaseModel):
    """A public reply or note: who wrote it (name only) and what it says."""

    id: uuid.UUID
    kind: EntryKind
    body: str = Field(description="Sanitised HTML.")
    created_at: datetime
    author_name: str | None
    by_you: bool


class PortalConversationOut(BaseModel):
    """The public conversation, oldest first."""

    items: list[PortalEntryOut]


class PortalReplyIn(BaseModel):
    """The requester's reply."""

    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=DESCRIPTION_MAX * 2, description="Rich text.")


class PortalRejectIn(BaseModel):
    """Why it is not fixed: shown as the requester's public reply."""

    model_config = ConfigDict(extra="forbid")

    comment: str = Field(min_length=1, max_length=RESOLUTION_MAX)


def _out(found: service.PortalRecord) -> PortalIncidentOut:
    return PortalIncidentOut.model_validate(found.values())


router = APIRouter(
    prefix="/portal/incidents",
    tags=["portal"],
    dependencies=[Depends(rate_limit("work_items"))],
    responses=RESPONSES,
)


@router.get(
    "",
    summary="Your incidents in the portal",
    response_model_exclude_unset=True,
)
async def list_portal_incidents(  # noqa: PLR0913, PLR0917 - FastAPI dependencies and query options
    session: TenantSession,
    query: Query_,
    subject: SignedIn,
    reach: Annotated[
        PortalReach | None, Query(description="Only one reach (e.g. reports).")
    ] = None,
    state: Annotated[service.PortalState | None, Query(description="Open or closed.")] = None,
    q: Annotated[str | None, Query(max_length=service.SEARCH_MAX)] = None,
) -> PortalIncidentPage:
    """Own incidents, plus those of a wider reach the person holds (REQ-PRT-007)."""
    rows, page = await service.list_records(
        session, subject, query, only=reach, state=state, search=q
    )
    return PortalIncidentPage(
        items=[_out(r) for r in rows],
        next_cursor=page.next_cursor,
        has_more=page.has_more,
        estimated_total=page.estimated_total,
    )


@router.get("/templates", summary="The forms the portal offers")
async def list_portal_templates(
    session: TenantSession, subject: SignedIn
) -> list[PortalTemplateOut]:
    """Templates marked for requesters (else the default), with the requester's fields only."""
    del subject
    return [PortalTemplateOut.of(t) for t in await service.portal_templates(session)]


@router.post("", summary="Report an issue in the portal", status_code=status.HTTP_201_CREATED)
async def create_portal_incident(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    body: PortalIncidentIn,
    session: TenantSession,
    subject: SignedIn,
    idempotency: Idempotency,
    request: Request,
    policy: Annotated[PolicyService, Depends(get_policy)],
) -> Response:
    """A new incident in your name; the new ID comes back at once (REQ-INC-028 AC1)."""

    async def run() -> Created:
        values = body.model_dump(exclude_unset=True, exclude={"template_id"})
        found = await service.create_record(
            session,
            subject,
            values,
            template_id=body.template_id,
            source=source_of(request),
            holders=policy,
        )
        out = _out(found)
        return Created(
            body=out.model_dump(mode="json", exclude_unset=True),
            headers={"Location": f"/api/v1/portal/incidents/{out.id}"},
        )

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.get(
    "/{record_id}",
    summary="One of your incidents in the portal",
    response_model_exclude_unset=True,
)
async def get_portal_incident(
    session: TenantSession, subject: SignedIn, record_id: uuid.UUID
) -> PortalIncidentOut:
    """The record as the requester's side sees it; 404 when out of reach."""
    return _out(await service.get_record(session, subject, record_id))


@router.get("/{record_id}/conversation", summary="The public conversation of your incident")
async def portal_conversation(
    session: TenantSession, subject: SignedIn, record_id: uuid.UUID
) -> PortalConversationOut:
    """Public replies and notes only; private notes never (REQ-INC-147 AC2)."""
    entries = await service.conversation(session, subject, record_id)
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
    summary="Reply on your incident",
    status_code=status.HTTP_201_CREATED,
    response_model_exclude_unset=True,
)
async def portal_reply(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    record_id: uuid.UUID,
    body: PortalReplyIn,
    session: TenantSession,
    subject: SignedIn,
    request: Request,
    policy: Annotated[PolicyService, Depends(get_policy)],
) -> PortalIncidentOut:
    """A public reply in your name; waiting on you resumes, a late one may reopen (WP-020f)."""
    replied = await service.reply(
        session, subject, record_id, body=body.body, source=source_of(request), holders=policy
    )
    target = replied.follow_up.id if replied.follow_up is not None else record_id
    return _out(await service.get_record(session, subject, target))


@router.post(
    "/{record_id}/resolution/confirm",
    summary="Confirm the fix",
    response_model_exclude_unset=True,
)
async def portal_confirm(
    record_id: uuid.UUID, session: TenantSession, subject: SignedIn, request: Request
) -> PortalIncidentOut:
    """It is fixed (REQ-INC-096 AC1); 409 `not_resolved` when there is nothing to confirm."""
    return _out(
        await service.answer_resolution(
            session, subject, record_id, confirmed=True, comment=None, source=source_of(request)
        )
    )


@router.post(
    "/{record_id}/resolution/reject",
    summary="Say it is not fixed",
    response_model_exclude_unset=True,
)
async def portal_reject(
    record_id: uuid.UUID,
    body: PortalRejectIn,
    session: TenantSession,
    subject: SignedIn,
    request: Request,
) -> PortalIncidentOut:
    """It reopens; the comment is your public reply (REQ-INC-096 AC2)."""
    return _out(
        await service.answer_resolution(
            session,
            subject,
            record_id,
            confirmed=False,
            comment=body.comment,
            source=source_of(request),
        )
    )


__all__ = ["router"]
