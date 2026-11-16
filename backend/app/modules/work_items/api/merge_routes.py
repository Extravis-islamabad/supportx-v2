"""Merging duplicate incidents over the API (WP-046b S2; REQ-INC-088, -150).

- GET  /incidents/{id}/merge-preview?into_id=  what a merge would do (counts and IDs only)
- POST /incidents/{id}/merge                    merge into `into_id` (If-Match; confirm a wider
                                                audience with `confirm_wider_audience`)
- POST /incidents/{id}/undo-merge               put it back exactly, or 409 (If-Match; needs
                                                incidents.undo_merge and a recent sign-in)

The merge itself shows in the audit log through the record's lifecycle (`incident.merged`); the
undo is audited here with both IDs (lane B).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.core.recent_auth import RecentAuth
from app.modules.audit import AuditNote, audited
from app.modules.identity_access import PolicyService, Subject, get_policy
from app.modules.work_items.domain.types import WorkItemType
from app.modules.work_items.service import incident_merge as service
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.history import source_of


class IncidentMergePreviewOut(BaseModel):
    """What merging would do. Counts and IDs only: never the names of people you cannot see."""

    duplicate_id: uuid.UUID
    into_id: uuid.UUID
    child_ids: list[uuid.UUID] = Field(description="The duplicate's children, which would move.")
    followers_added: list[uuid.UUID] = Field(
        description="The duplicate's requesters added as followers with portal access."
    )
    followers_not_added: list[uuid.UUID] = Field(
        description="Its requesters left out: the incidents are not in the same department."
    )
    staff_newly_seeing: int = Field(
        description="Staff who can see the survivor but not the duplicate today."
    )
    requesters_newly_seeing: int = Field(
        description="The survivor's requesters, who would see the duplicate's public entries."
    )
    followers_newly_seeing: int = Field(
        description=(
            "The duplicate's requesters added as followers, who see the survivor's public side."
        )
    )
    audience_complete: bool = Field(
        description="False: more staff than were checked, so the count is a lower bound."
    )
    needs_confirmation: bool = Field(description="Someone would newly see the duplicate.")


class IncidentMergeIn(BaseModel):
    """The incident to merge into, and the person's confirmation of a wider audience."""

    into_id: uuid.UUID
    confirm_wider_audience: bool = False


class IncidentMergeOut(BaseModel):
    """The duplicate's new state, and the children that moved."""

    id: uuid.UUID
    status: str = Field(description="`merged` after a merge; the earlier status after an undo.")
    version: int = Field(description="The new version (also the ETag).")
    moved_child_ids: list[uuid.UUID]


def add_incident_merge_routes(router: APIRouter, wtype: WorkItemType) -> None:
    """The three routes for incidents (both records need edit; undo its own right)."""
    edit = Annotated[Subject, Depends(require_permission(wtype.permission("edit")))]
    policy = Annotated[PolicyService, Depends(get_policy)]

    def answer(done: service.MergeOutcome, response: Response) -> IncidentMergeOut:
        set_etag(response, done.record.version)
        return IncidentMergeOut(
            id=done.record.id,
            status=done.record.status,
            version=done.record.version,
            moved_child_ids=done.moved,
        )

    @router.get("/{record_id}/merge-preview", summary="Preview a merge")
    async def merge_preview(
        record_id: uuid.UUID,
        into_id: Annotated[uuid.UUID, Query(description="The incident to merge into.")],
        session: TenantSession,
        subject: edit,
        holders: policy,
    ) -> IncidentMergePreviewOut:
        """Nothing changes; the same checks as the merge (both editable, both open)."""
        shown = await service.preview(session, subject, record_id, into_id, holders=holders)
        return IncidentMergePreviewOut(
            duplicate_id=shown.duplicate.id,
            into_id=shown.survivor.id,
            child_ids=shown.children,
            followers_added=shown.followers_added,
            followers_not_added=shown.followers_not_added,
            staff_newly_seeing=shown.staff_newly_seeing,
            requesters_newly_seeing=shown.requesters_newly_seeing,
            followers_newly_seeing=len(shown.followers_added),
            audience_complete=shown.audience_complete,
            needs_confirmation=shown.widens,
        )

    @router.post("/{record_id}/merge", summary="Merge into another incident")
    async def merge(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        body: IncidentMergeIn,
        version: ExpectedVersion,
        session: TenantSession,
        subject: edit,
        holders: policy,
        request: Request,
        response: Response,
    ) -> IncidentMergeOut:
        """Mark it `merged` under `into_id`; 409 `merge_widens_audience` until confirmed."""
        done = await service.merge(
            session,
            subject,
            record_id,
            body.into_id,
            expected_version=version,
            confirm_wider_audience=body.confirm_wider_audience,
            holders=holders,
            source=source_of(request),
        )
        return answer(done, response)

    @router.post(
        "/{record_id}/undo-merge",
        summary="Undo a merge",
        # Puts records back across two incidents: as sensitive as the closed-edit lock (lane B).
        dependencies=[RecentAuth],
    )
    async def undo_merge(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        version: ExpectedVersion,
        session: TenantSession,
        subject: edit,
        request: Request,
        response: Response,
        note: Annotated[AuditNote, audited("incident.merge_undone", object_type="incident")],
    ) -> IncidentMergeOut:
        """Exactly as before, or 409 `merge_undo_not_exact`. Needs incidents.undo_merge."""
        done = await service.undo_merge(
            session, subject, record_id, expected_version=version, source=source_of(request)
        )
        note.object_id = str(done.record.id)
        note.details = {"from": str(done.into_id), "children": [str(c) for c in done.moved]}
        return answer(done, response)
