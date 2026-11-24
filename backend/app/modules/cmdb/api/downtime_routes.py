"""CI downtimes on the API (WP-053 S5b; REQ-CMDB-020). No logic: cmdb/service/downtimes.py.

A CI's downtimes read with the CI (404 for one the reader may not see). Only a downtime
recorded on the CI by hand is written here (`cmdb.record_downtime`): creates take an
Idempotency-Key, changes and removals If-Match on the downtime's own version. A downtime from a
change, release or incident is read-only here (409 `cmdb_downtime_synced`): it changes at its
record.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.core.errors import ProblemDetail
from app.modules.audit import audited
from app.modules.cmdb.domain import downtimes as domain
from app.modules.cmdb.infra.models import CiDowntime
from app.modules.cmdb.service import catalogue, downtimes
from app.modules.identity_access import Subject
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.ratelimit import rate_limit
from app.shared.history import source_of

Responses = dict[int | str, dict[str, Any]]
RESPONSES: Responses = {
    401: {"model": ProblemDetail, "description": "Not signed in."},
    403: {"model": ProblemDetail, "description": "Missing permission or licence feature."},
    404: {"model": ProblemDetail, "description": "No such CI or downtime visible to you."},
}
CONFLICT: Responses = {
    409: {
        "model": ProblemDetail,
        "description": "Stale If-Match (version_conflict), or a synced downtime "
        "(cmdb_downtime_synced): change it at its record.",
    }
}

router = APIRouter(
    prefix="/cmdb",
    tags=["cmdb"],
    dependencies=[Depends(rate_limit("cmdb"))],
    responses=RESPONSES,
)

View = Annotated[Subject, Depends(require_permission(catalogue.VIEW))]
Record = Annotated[Subject, Depends(require_permission(catalogue.RECORD_DOWNTIME))]

# Codes as named schemas (labelled `cmdb_downtime_state.<code>`, `cmdb_downtime_source.<code>`).
CiDowntimeState = domain.CiDowntimeState
CiDowntimeSource = domain.CiDowntimeSource
CiDowntimePhase = domain.CiDowntimePhase


class CiDowntimeOut(BaseModel):
    """One downtime of a CI. A synced one names its source record by ID (shown by its ref)."""

    id: uuid.UUID
    ci_id: uuid.UUID
    source: CiDowntimeSource
    source_work_item_id: uuid.UUID | None
    phase: CiDowntimePhase
    kind: str | None
    starts_at: datetime
    ends_at: datetime | None
    description: str | None = Field(description="Only on a downtime recorded by hand.")
    state: CiDowntimeState
    editable: bool = Field(description="True for a hand-recorded one (changed here).")
    version: int

    @classmethod
    def of(cls, row: CiDowntime) -> "CiDowntimeOut":
        """From the stored row."""
        return cls(
            id=row.id,
            ci_id=row.ci_id,
            source=CiDowntimeSource(row.source),
            source_work_item_id=row.source_work_item_id,
            phase=CiDowntimePhase(row.phase),
            kind=row.kind,
            starts_at=row.starts_at,
            ends_at=row.ends_at,
            description=row.description,
            state=CiDowntimeState(row.state),
            editable=row.source == CiDowntimeSource.MANUAL.value,
            version=row.version,
        )


class CiDowntimeCountsOut(BaseModel):
    """A CI's live downtimes by state."""

    scheduled: int
    active: int
    completed: int


class CiDowntimesOut(BaseModel):
    """A CI's downtimes, newest start first, and how many in each state."""

    items: list[CiDowntimeOut]
    counts: CiDowntimeCountsOut


class CiDowntimeIn(BaseModel):
    """A downtime recorded on the CI by hand."""

    model_config = ConfigDict(extra="forbid")

    starts_at: datetime
    ends_at: datetime | None = None
    kind: str | None = Field(default=None, max_length=40)
    description: str | None = Field(default=None, max_length=domain.DESCRIPTION_MAX)


class CiDowntimePatch(BaseModel):
    """Changes to a hand-recorded downtime (only the fields sent change)."""

    model_config = ConfigDict(extra="forbid")

    starts_at: datetime | None = None
    ends_at: datetime | None = None
    kind: str | None = Field(default=None, max_length=40)
    description: str | None = Field(default=None, max_length=domain.DESCRIPTION_MAX)


@router.get("/cis/{ci_id}/downtimes", summary="A CI's downtimes")
async def get_downtimes(ci_id: uuid.UUID, session: TenantSession, subject: View) -> CiDowntimesOut:
    """Scheduled, active and completed downtimes of the CI, with their counts."""
    rows = await downtimes.list_for_ci(session, subject, ci_id)
    counts = downtimes.counts_of(rows)
    return CiDowntimesOut(
        items=[CiDowntimeOut.of(r) for r in rows],
        counts=CiDowntimeCountsOut(
            scheduled=counts.scheduled, active=counts.active, completed=counts.completed
        ),
    )


@router.post(
    "/cis/{ci_id}/downtimes",
    summary="Record a downtime on a CI",
    status_code=status.HTTP_201_CREATED,
    response_model=CiDowntimeOut,
    dependencies=[audited("cmdb.downtime_recorded", object_type="cmdb_ci", object_param="ci_id")],
)
async def create_downtime(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    ci_id: uuid.UUID,
    body: CiDowntimeIn,
    session: TenantSession,
    subject: Record,
    idempotency: Idempotency,
    request: Request,
) -> Response:
    """By hand (`cmdb.record_downtime`). Send an Idempotency-Key: a retry returns the same 201."""

    async def run() -> Created:
        row = await downtimes.record_manual(
            session,
            subject,
            ci_id,
            starts_at=body.starts_at,
            ends_at=body.ends_at,
            kind=body.kind,
            description=body.description,
            source=source_of(request),
        )
        return Created(body=CiDowntimeOut.of(row), headers={"ETag": f'"{row.version}"'})

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.patch(
    "/cis/{ci_id}/downtimes/{downtime_id}",
    summary="Change a hand-recorded downtime",
    responses=CONFLICT,
    dependencies=[audited("cmdb.downtime_changed", object_type="cmdb_ci", object_param="ci_id")],
)
async def patch_downtime(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    ci_id: uuid.UUID,
    downtime_id: uuid.UUID,
    body: CiDowntimePatch,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Record,
    response: Response,
    request: Request,
) -> CiDowntimeOut:
    """If-Match on the downtime's version; a synced downtime answers 409."""
    row = await downtimes.update_manual(
        session,
        subject,
        ci_id,
        downtime_id,
        expected_version=version,
        values=body.model_dump(exclude_unset=True),
        source=source_of(request),
    )
    set_etag(response, row.version)
    return CiDowntimeOut.of(row)


@router.delete(
    "/cis/{ci_id}/downtimes/{downtime_id}",
    summary="Remove a hand-recorded downtime",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=CONFLICT,
    dependencies=[audited("cmdb.downtime_removed", object_type="cmdb_ci", object_param="ci_id")],
)
async def delete_downtime(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    ci_id: uuid.UUID,
    downtime_id: uuid.UUID,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Record,
    request: Request,
) -> Response:
    """If-Match on the downtime's version; a synced downtime answers 409."""
    await downtimes.remove_manual(
        session,
        subject,
        ci_id,
        downtime_id,
        expected_version=version,
        source=source_of(request),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
