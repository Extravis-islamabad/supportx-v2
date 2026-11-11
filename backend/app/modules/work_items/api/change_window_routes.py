"""Freeze and maintenance windows, and a change's conflicts and freeze override (WP-045c; ADR-042).

`/api/v1/change-windows`: list (optionally only those with an occurrence in a range, for the
calendar), read, add (Idempotency-Key), change (If-Match) and remove. Reading needs
`changes.view` or the settings permission; changing needs `changes.manage_windows` (the change
manager) or the settings permission, and is audited.

On a change: `GET /api/v1/changes/{id}/conflicts` (each conflict and why) and
`POST /api/v1/changes/{id}/freeze-override` (a reason, If-Match; `changes.override_freeze` at
the change's scope; audited, refused attempts too).
"""

import uuid
from datetime import datetime, timedelta
from typing import Annotated, Self

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.modules.audit import AuditNote, audited
from app.modules.identity_access import Subject
from app.modules.work_items.api.settings_routes import CONFLICT
from app.modules.work_items.domain.change_windows import ConflictKind, WindowKind, WindowMode
from app.modules.work_items.domain.types import CHANGE, RELEASE
from app.modules.work_items.infra.models import ChangeWindow
from app.modules.work_items.service import change_windows as service
from app.modules.work_items.service.work_items import field_errors
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.ratelimit import rate_limit
from app.shared.history import source_of

router = APIRouter(
    prefix="/change-windows",
    tags=["changes"],
    dependencies=[Depends(rate_limit("work_items"))],
)
change_router = APIRouter(
    prefix="/changes",
    tags=["changes"],
    dependencies=[Depends(rate_limit("work_items"))],
)
LOCATION = "/api/v1/change-windows"
MAX_RANGE_DAYS = 400  # a calendar asks for a month, a week or a year at most
View = Annotated[Subject, Depends(require_permission(CHANGE.permission("view"), *service.MANAGE))]
Admin = Annotated[Subject, Depends(require_permission(*service.MANAGE))]
Note = Annotated[AuditNote, audited("change.window_changed", object_type="change_window")]


def _range_ok(start: datetime, end: datetime) -> bool:
    """A range that ends after it starts, and spans at most 400 days."""
    return start < end and end - start <= timedelta(days=MAX_RANGE_DAYS)


class WindowIn(BaseModel):
    """A new window: its kind, name and times; the mode follows the kind unless given."""

    model_config = ConfigDict(extra="forbid")

    kind: WindowKind
    mode: WindowMode | None = Field(
        default=None, description="Default: a freeze blocks, a maintenance window warns."
    )
    name: str = Field(max_length=service.NAME_MAX)
    labels: dict[str, str] | None = Field(default=None, description="{en, ar, ur}")
    description: str | None = Field(default=None, max_length=service.DESCRIPTION_MAX)
    starts_at: datetime
    ends_at: datetime
    repeat_weekly: bool = False
    repeat_until: datetime | None = None
    site_ids: list[uuid.UUID] = Field(default_factory=list, max_length=service.MAX_IDS)
    group_ids: list[uuid.UUID] = Field(default_factory=list, max_length=service.MAX_IDS)
    service_ids: list[uuid.UUID] = Field(default_factory=list, max_length=service.MAX_IDS)
    ci_ids: list[uuid.UUID] = Field(default_factory=list, max_length=service.MAX_IDS)


class WindowPatch(BaseModel):
    """A window's fields to change (send only those you change)."""

    model_config = ConfigDict(extra="forbid")

    kind: WindowKind | None = None
    mode: WindowMode | None = None
    name: str | None = Field(default=None, max_length=service.NAME_MAX)
    labels: dict[str, str] | None = None
    description: str | None = Field(default=None, max_length=service.DESCRIPTION_MAX)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    repeat_weekly: bool | None = None
    repeat_until: datetime | None = None
    site_ids: list[uuid.UUID] | None = Field(default=None, max_length=service.MAX_IDS)
    group_ids: list[uuid.UUID] | None = Field(default=None, max_length=service.MAX_IDS)
    service_ids: list[uuid.UUID] | None = Field(default=None, max_length=service.MAX_IDS)
    ci_ids: list[uuid.UUID] | None = Field(default=None, max_length=service.MAX_IDS)


class WindowOut(BaseModel):
    """A window as stored; scopes all empty: the whole tenant."""

    id: uuid.UUID
    kind: WindowKind
    mode: WindowMode
    name: str
    labels: dict[str, str] | None
    description: str | None
    starts_at: datetime
    ends_at: datetime
    repeat_weekly: bool
    repeat_until: datetime | None
    site_ids: list[uuid.UUID]
    group_ids: list[uuid.UUID]
    service_ids: list[uuid.UUID]
    ci_ids: list[uuid.UUID]
    version: int

    @classmethod
    def of(cls, row: ChangeWindow) -> Self:
        """From the stored window."""
        return cls(
            id=row.id,
            kind=WindowKind(row.kind),
            mode=WindowMode(row.mode),
            name=row.name,
            labels=row.labels,
            description=row.description,
            starts_at=row.starts_at,
            ends_at=row.ends_at,
            repeat_weekly=row.repeat_weekly,
            repeat_until=row.repeat_until,
            site_ids=list(row.site_ids or []),
            group_ids=list(row.group_ids or []),
            service_ids=list(row.service_ids or []),
            ci_ids=list(row.ci_ids or []),
            version=row.version,
        )


@router.get("", summary="Freeze and maintenance windows")
async def list_windows(
    session: TenantSession,
    subject: View,
    start: Annotated[datetime | None, Query(description="With `end`: only those then.")] = None,
    end: Annotated[datetime | None, Query()] = None,
) -> list[WindowOut]:
    """Every live window by start; with a range, only those with an occurrence in it.

    The range is at most 400 days; weekly windows are included by their occurrences.
    """
    if (start is None) != (end is None) or (
        start is not None and end is not None and not _range_ok(start, end)
    ):
        raise field_errors([("end", "out_of_range")])
    return [WindowOut.of(r) for r in await service.windows(session, subject, start=start, end=end)]


@router.get("/{window_id}", summary="A freeze or maintenance window")
async def get_window(
    window_id: uuid.UUID, session: TenantSession, subject: View, response: Response
) -> WindowOut:
    """One window; ETag is its version."""
    row = await service.window(session, subject, window_id)
    set_etag(response, row.version)
    return WindowOut.of(row)


@router.post(
    "",
    summary="Add a freeze or maintenance window",
    status_code=status.HTTP_201_CREATED,
    response_model=WindowOut,
)
async def add_window(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    body: WindowIn,
    session: TenantSession,
    subject: Admin,
    idempotency: Idempotency,
    request: Request,
    note: Note,
) -> Response:
    """Send an Idempotency-Key. A freeze blocks and a maintenance window warns by default."""

    async def run() -> Created:
        made = await service.create_window(
            session,
            subject,
            body.model_dump(exclude_unset=True, exclude={"mode"} if body.mode is None else set()),
            source=source_of(request),
        )
        note.details = {"window": str(made.id), "change": "added", "kind": made.kind}
        out = WindowOut.of(made)
        return Created(
            body=out,
            headers={"Location": f"{LOCATION}/{out.id}", "ETag": f'"{out.version}"'},
        )

    return await idempotency.run(body.model_dump(mode="json"), run)


@router.patch("/{window_id}", summary="Change a freeze or maintenance window", responses=CONFLICT)
async def patch_window(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    window_id: uuid.UUID,
    body: WindowPatch,
    session: TenantSession,
    subject: Admin,
    version: ExpectedVersion,
    response: Response,
    request: Request,
    note: Note,
) -> WindowOut:
    """Needs If-Match."""
    note.details = {"window": str(window_id), "changed_fields": sorted(body.model_fields_set)}
    changed = await service.update_window(
        session,
        subject,
        window_id,
        body.model_dump(exclude_unset=True),
        expected_version=version,
        source=source_of(request),
    )
    set_etag(response, changed.version)
    return WindowOut.of(changed)


@router.delete(
    "/{window_id}",
    summary="Remove a freeze or maintenance window",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=CONFLICT,
)
async def delete_window(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    window_id: uuid.UUID,
    session: TenantSession,
    subject: Admin,
    version: ExpectedVersion,
    request: Request,
    note: Note,
) -> None:
    """Needs If-Match; the window's history stays."""
    note.details = {"window": str(window_id), "change": "removed"}
    await service.delete_window(
        session, subject, window_id, expected_version=version, source=source_of(request)
    )


# --- on a change ----------------------------------------------------------------------------------


class ConflictOut(BaseModel):
    """One conflict of the change's planned time, and whether it blocks a save."""

    kind: ConflictKind
    starts_at: datetime
    ends_at: datetime
    blocks: bool = Field(description="A blocking freeze, unless the change's freezes were passed.")
    window_id: uuid.UUID | None = None
    window_name: str | None = None
    window_labels: dict[str, str] | None = None
    record_id: uuid.UUID | None = Field(
        default=None, description="The other change it overlaps (open it to see whether you may)."
    )


class ConflictsOut(BaseModel):
    """A change's conflicts now, and the blocking freezes someone passed for it."""

    items: list[ConflictOut]
    passed_window_ids: list[uuid.UUID] = Field(
        description="Freezes passed for this change; any other blocking freeze still blocks."
    )


class FreezeOverrideIn(BaseModel):
    """Why the change goes ahead in a freeze (required)."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(max_length=service.REASON_MAX)
    window_ids: list[uuid.UUID] = Field(
        min_length=1,
        max_length=50,
        description="The blocking freezes to pass (as the 409 named them); only these.",
    )


ViewChange = Annotated[Subject, Depends(require_permission(CHANGE.permission("view")))]


@change_router.get("/{record_id}/conflicts", summary="The change's conflicts with windows")
async def change_conflicts(
    record_id: uuid.UUID, session: TenantSession, subject: ViewChange
) -> ConflictsOut:
    """Freezes, being outside a maintenance window, and overlapping changes, each with why."""
    _, found, named, passed = await service.change_conflicts_of(session, subject, record_id)
    return ConflictsOut(
        items=[
            ConflictOut(
                kind=c.kind,
                starts_at=c.starts_at,
                ends_at=c.ends_at,
                blocks=c.blocks and c.window_id not in passed,
                window_id=c.window_id,
                window_name=named[c.window_id].name if c.window_id in named else None,
                window_labels=named[c.window_id].labels if c.window_id in named else None,
                record_id=c.record_id,
            )
            for c in found
        ],
        passed_window_ids=sorted(passed),
    )


@change_router.post(
    "/{record_id}/freeze-override",
    summary="Go ahead in a freeze, with a reason",
    responses=CONFLICT,
)
async def freeze_override(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    record_id: uuid.UUID,
    body: FreezeOverrideIn,
    version: ExpectedVersion,
    session: TenantSession,
    subject: ViewChange,
    request: Request,
    response: Response,
    note: Annotated[
        AuditNote,
        # The dependency also logs a refused attempt (lane B, as for D-144's override).
        audited("change.freeze_override", object_type="change", object_param="record_id"),
    ],
) -> dict[str, int]:
    """Needs `changes.override_freeze` at the change's scope, a reason and If-Match.

    Only the freezes named are passed for this change; the record's history keeps which, who
    and why, and the audit log keeps it with the reason.
    """
    note.reason = body.reason
    note.details = {"window_ids": sorted(str(w) for w in body.window_ids)}
    updated = await service.override_freeze(
        session,
        subject,
        record_id,
        reason=body.reason,
        window_ids=body.window_ids,
        expected_version=version,
        source=source_of(request),
    )
    set_etag(response, updated.version)
    return {"version": updated.version}


# --- the change calendar (WP-045c S3) -------------------------------------------------------------

# Its own prefix: `/changes/calendar` would meet the changes' `/{record_id}` route first.
calendar_router = APIRouter(
    prefix="/change-calendar",
    tags=["changes"],
    dependencies=[Depends(rate_limit("work_items"))],
)


class CalendarEntryOut(BaseModel):
    """A change's planned time: its implementation window or a planned downtime."""

    record_id: uuid.UUID
    display_id: str
    subject: str
    stage: str | None
    status: str
    stage_path: str | None
    group_id: uuid.UUID | None
    site_id: uuid.UUID | None
    technician_id: uuid.UUID | None
    kind: str = Field(
        description="`window` (implementation, or a release's deployment) or `downtime` (planned)."
    )
    starts_at: datetime
    ends_at: datetime
    part_id: uuid.UUID | None = Field(default=None, description="The downtime, for a downtime.")
    version: int = Field(description="The window's or downtime's own version, for If-Match.")


def _entries(entries: list[service.CalendarEntry]) -> list[CalendarEntryOut]:
    return [
        CalendarEntryOut(
            record_id=e.record.id,
            display_id=e.record.display_id,
            subject=e.record.subject,
            stage=e.record.stage,
            status=e.record.status,
            stage_path=e.record.stage_path,
            group_id=e.record.group_id,
            site_id=e.record.site_id,
            technician_id=e.record.technician_id,
            kind=e.kind,
            starts_at=e.starts_at,
            ends_at=e.ends_at,
            part_id=e.part_id,
            version=e.version,
        )
        for e in entries
    ]


@calendar_router.get("", summary="Changes planned in a range")
async def change_calendar(
    session: TenantSession,
    subject: ViewChange,
    start: Annotated[datetime, Query()],
    end: Annotated[datetime, Query()],
    mine: Annotated[bool, Query(description="Only the changes you hold.")] = False,  # noqa: FBT002 - a query flag
) -> list[CalendarEntryOut]:
    """The changes you may see, planned in [start, end) (at most 400 days), by start."""
    if not _range_ok(start, end):
        raise field_errors([("end", "out_of_range")])
    return _entries(await service.calendar(session, subject, start=start, end=end, mine=mine))


# --- the release calendar (WP-058b S1; REQ-REL-038) --------------------------------------------

release_calendar_router = APIRouter(
    prefix="/release-calendar",
    tags=["releases"],
    dependencies=[Depends(rate_limit("work_items"))],
)
ViewRelease = Annotated[Subject, Depends(require_permission(RELEASE.permission("view")))]


@release_calendar_router.get("", summary="Releases planned in a range")
async def release_calendar(
    session: TenantSession,
    subject: ViewRelease,
    start: Annotated[datetime, Query()],
    end: Annotated[datetime, Query()],
    mine: Annotated[bool, Query(description="Only the releases you hold.")] = False,  # noqa: FBT002 - a query flag
) -> list[CalendarEntryOut]:
    """The releases you may see, planned in [start, end) (at most 400 days), by start.

    Each one's deployment window and its planned downtimes.
    """
    if not _range_ok(start, end):
        raise field_errors([("end", "out_of_range")])
    entries = await service.calendar(
        session, subject, start=start, end=end, mine=mine, wtype=RELEASE
    )
    return _entries(entries)
