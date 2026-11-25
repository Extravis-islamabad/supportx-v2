"""CI baselines on the API (WP-053 S7b; REQ-CMDB-033). No logic: cmdb/service/baselines.py.

Reads need `cmdb.view` and the CI visible to you now (404 otherwise). Saving and deleting need
`cmdb.manage` on the CI, audited: a save takes an Idempotency-Key, a delete the baseline's
If-Match version. A compare is seen through your rights now: fields your rules hide are absent
from both sides, masked fields show only whether they changed.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.core.errors import ProblemDetail
from app.modules.audit import audited
from app.modules.cmdb.api.graph_routes import (
    CiAttributeChangeOut,
    CiVersionLinkOut,
    CiVersionOut,
    link_out,
    version_out,
)
from app.modules.cmdb.service import baselines, catalogue
from app.modules.identity_access import Subject
from app.shared.api.concurrency import ExpectedVersion
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.listing import ListQuery, list_query
from app.shared.api.ratelimit import rate_limit
from app.shared.history import source_of

Responses = dict[int | str, dict[str, Any]]
RESPONSES: Responses = {
    401: {"model": ProblemDetail, "description": "Not signed in."},
    403: {"model": ProblemDetail, "description": "Missing permission or licence feature."},
    404: {"model": ProblemDetail, "description": "No such CI or baseline visible to you."},
}
CONFLICT: Responses = {
    409: {"model": ProblemDetail, "description": "Stale If-Match (version_conflict)."}
}

router = APIRouter(
    prefix="/cmdb",
    tags=["cmdb"],
    dependencies=[Depends(rate_limit("cmdb"))],
    responses=RESPONSES,
)

View = Annotated[Subject, Depends(require_permission(catalogue.VIEW))]
Manage = Annotated[Subject, Depends(require_permission(catalogue.MANAGE))]
BaselinesQuery = Annotated[ListQuery, Depends(list_query(baselines.BASELINE_FIELDS))]


class BaselineIn(BaseModel):
    """A new baseline: the CI as it is now, under a name."""

    name: str = Field(min_length=1, max_length=baselines.NAME_MAX)


class BaselineOut(BaseModel):
    """One saved baseline (its copy is read through a compare)."""

    id: uuid.UUID
    ci_id: uuid.UUID
    name: str
    from_version: int = Field(description="The CI version it was taken at.")
    created_at: datetime
    created_by: uuid.UUID | None
    created_by_name: str | None
    version: int

    @classmethod
    def of(cls, item: baselines.BaselineItem) -> "BaselineOut":
        """From the service's item."""
        row = item.record
        return cls(
            id=row.id,
            ci_id=row.ci_id,
            name=row.name,
            from_version=row.from_version,
            created_at=row.created_at,
            created_by=row.created_by,
            created_by_name=item.created_by_name,
            version=row.version,
        )


class BaselinePage(BaseModel):
    """One page of a CI's baselines, newest first by default."""

    items: list[BaselineOut]
    next_cursor: str | None
    has_more: bool


class MaskedChangeOut(BaseModel):
    """A masked field: whether it changed, never its values."""

    field: str
    changed: bool


class BaselineComparisonOut(BaseModel):
    """The baseline (`from_version`) against another baseline or the CI now (`to_version`)."""

    from_version: CiVersionOut
    to_version: CiVersionOut
    attributes: list[CiAttributeChangeOut]
    masked: list[MaskedChangeOut] = Field(
        description="Masked fields either side holds: changed or unchanged only."
    )
    relationships_added: list[CiVersionLinkOut]
    relationships_removed: list[CiVersionLinkOut]


@router.get("/cis/{ci_id}/baselines", summary="Baselines of a CI")
async def list_baselines(
    ci_id: uuid.UUID, session: TenantSession, subject: View, query: BaselinesQuery
) -> BaselinePage:
    """The CI's baselines. Sort (`sort=name`), page with `cursor`."""
    items, page = await baselines.list_baselines(session, subject, ci_id, query)
    return BaselinePage(
        items=[BaselineOut.of(i) for i in items],
        next_cursor=page.next_cursor,
        has_more=page.has_more,
    )


@router.post(
    "/cis/{ci_id}/baselines",
    summary="Save a baseline",
    status_code=status.HTTP_201_CREATED,
    response_model=BaselineOut,
    dependencies=[audited("cmdb.baseline_saved", object_type="cmdb_ci", object_param="ci_id")],
)
async def save_baseline(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    ci_id: uuid.UUID,
    body: BaselineIn,
    session: TenantSession,
    subject: Manage,
    idempotency: Idempotency,
    request: Request,
) -> Response:
    """Save the CI's attributes and relationships as they are now. Send an Idempotency-Key."""

    async def run() -> Created:
        item = await baselines.save(
            session, subject, ci_id, body.model_dump(mode="python"), source_of(request)
        )
        out = BaselineOut.of(item)
        return Created(
            body=out,
            headers={
                "Location": f"/api/v1/cmdb/cis/{ci_id}/baselines/{out.id}",
                "ETag": f'"{out.version}"',
            },
        )

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.delete(
    "/cis/{ci_id}/baselines/{baseline_id}",
    summary="Delete a baseline",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=CONFLICT,
    dependencies=[audited("cmdb.baseline_deleted", object_type="cmdb_ci", object_param="ci_id")],
)
async def delete_baseline(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    ci_id: uuid.UUID,
    baseline_id: uuid.UUID,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Manage,
    request: Request,
) -> Response:
    """If-Match on the baseline's version."""
    await baselines.remove(
        session,
        subject,
        ci_id,
        baseline_id,
        expected_version=version,
        source=source_of(request),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/cis/{ci_id}/baselines/{baseline_id}/compare", summary="Compare a baseline")
async def compare_baseline(
    ci_id: uuid.UUID,
    baseline_id: uuid.UUID,
    session: TenantSession,
    subject: View,
    against: Annotated[
        uuid.UUID | None,
        Query(description="Another baseline of this CI; leave out to compare with the CI now."),
    ] = None,
) -> BaselineComparisonOut:
    """Attributes added, removed and changed; masked ones changed or not; relationships."""
    result = await baselines.compare(session, subject, ci_id, baseline_id, against=against)
    return BaselineComparisonOut(
        from_version=version_out(result.from_version),
        to_version=version_out(result.to_version),
        attributes=[
            CiAttributeChangeOut(field=a.field, kind=a.kind, old=a.old, new=a.new)  # type: ignore[arg-type]  # the domain gives only these kinds
            for a in result.attributes
        ],
        masked=[MaskedChangeOut(field=m.field, changed=m.changed) for m in result.masked],
        relationships_added=[link_out(link) for link in result.added],
        relationships_removed=[link_out(link) for link in result.removed],
    )
