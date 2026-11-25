"""A CI's linked work items on the API (WP-053 S5c; REQ-CMDB-019). No logic: service/linked.py.

Read with the CI (404 for one the reader may not see). Only the work items the reader may see
are counted or listed (D-158): nothing of an unseen one, not even that it exists. Without work
items' port registered, both answer 404 `linked_records_not_available` and the tab hides.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.core.errors import ProblemDetail
from app.modules.cmdb.service import catalogue, linked
from app.modules.identity_access import Subject
from app.shared.api.ratelimit import rate_limit

Responses = dict[int | str, dict[str, Any]]
RESPONSES: Responses = {
    401: {"model": ProblemDetail, "description": "Not signed in."},
    403: {"model": ProblemDetail, "description": "Missing permission or licence feature."},
    404: {
        "model": ProblemDetail,
        "description": "No such CI visible to you (cmdb_ci_not_found), or no work items yet "
        "(linked_records_not_available).",
    },
}

router = APIRouter(
    prefix="/cmdb",
    tags=["cmdb"],
    dependencies=[Depends(rate_limit("cmdb"))],
    responses=RESPONSES,
)

View = Annotated[Subject, Depends(require_permission(catalogue.VIEW))]


class CiLinkedKindOut(BaseModel):
    """One work-item type's linked records you may see."""

    kind: str
    open: int
    total: int


class CiLinkedKindsOut(BaseModel):
    """Per type: open, and all of them (only what you may see)."""

    kinds: list[CiLinkedKindOut]


class CiLinkedRecordOut(BaseModel):
    """A linked work item, as the Associations tab lists it."""

    id: uuid.UUID
    kind: str
    display_id: str
    subject: str
    status: str
    open: bool
    updated_at: datetime


class CiLinkedPageOut(BaseModel):
    """One page, newest first."""

    items: list[CiLinkedRecordOut]
    next_cursor: str | None = None


@router.get("/cis/{ci_id}/linked", summary="Work items linked to a CI, per type")
async def linked_kinds(ci_id: uuid.UUID, session: TenantSession, subject: View) -> CiLinkedKindsOut:
    """Open and total per type: only the records you may see."""
    found = await linked.linked_kinds(session, subject, ci_id)
    return CiLinkedKindsOut(
        kinds=[CiLinkedKindOut(kind=k.kind, open=k.open, total=k.total) for k in found]
    )


@router.get("/cis/{ci_id}/linked/{kind}", summary="One type's work items linked to a CI")
async def linked_page(  # noqa: PLR0913, PLR0917 - FastAPI dependencies and paging
    ci_id: uuid.UUID,
    kind: str,
    session: TenantSession,
    subject: View,
    cursor: Annotated[str | None, Query(max_length=400)] = None,
    limit: Annotated[int, Query(ge=1, le=linked.PAGE_MAX)] = linked.PAGE_DEFAULT,
) -> CiLinkedPageOut:
    """Newest first; only the records you may see."""
    rows, next_cursor = await linked.linked_page(
        session, subject, ci_id, kind, cursor=cursor, limit=limit
    )
    return CiLinkedPageOut(
        items=[
            CiLinkedRecordOut(
                id=r.id, kind=r.kind, display_id=r.display_id, subject=r.subject,
                status=r.status, open=r.open, updated_at=r.updated_at,
            )
            for r in rows
        ],
        next_cursor=next_cursor,
    )  # fmt: skip
