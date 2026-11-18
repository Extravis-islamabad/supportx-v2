"""Converting incidents and service requests into each other over the API (WP-046b S2; 089).

- GET  /{type}/{id}/convert-preview   what carries and what stays (field keys only)
- POST /{type}/{id}/convert           create the other type's record (If-Match); audited with
                                      both IDs (`<type>.converted`)
- GET  /{type}/alias/{value}          where an old, converted number leads now (404 unless you
                                      may read that record)
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.modules.audit import AuditNote, audited
from app.modules.identity_access import PolicyService, Subject, get_policy
from app.modules.work_items.domain.types import WorkItemType, WorkItemTypeCode
from app.modules.work_items.service import record_convert as service
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.history import source_of


class ConvertPreviewOut(BaseModel):
    """What converting would carry and leave on the old record (keys only, never values)."""

    record_id: uuid.UUID
    to_type: WorkItemTypeCode
    carried_custom: list[str] = Field(description="Custom field keys that move to the new record.")
    not_carried: list[str] = Field(
        description=(
            "custom.<key> left on the old record: the new type lacks the field, its type"
            " differs, or a field-access rule covers it."
        )
    )
    pending_approvals: bool = Field(description="Open approvals, withdrawn by the conversion.")


class ConvertIn(BaseModel):
    """The new type's own inputs: a request's catalog item and answers, an incident's template."""

    catalog_item_id: uuid.UUID | None = None
    # Any: the item's answers are JSON of the item's own question types (the create path checks).
    answers: dict[str, Any] | None = Field(
        default=None, description="The catalog item's questions answered (service requests)."
    )
    template_id: uuid.UUID | None = None


class ConvertedOut(BaseModel):
    """The old record (now `converted`) and the new one."""

    old_id: uuid.UUID
    old_version: int
    new_id: uuid.UUID
    new_display_id: str
    new_type: WorkItemTypeCode
    not_carried: list[str]


class AliasOut(BaseModel):
    """Where an old number leads."""

    record_type: WorkItemTypeCode
    record_id: uuid.UUID
    display_id: str


def add_convert_routes(router: APIRouter, wtype: WorkItemType) -> None:
    """The three routes for one convertible type."""
    edit = Annotated[Subject, Depends(require_permission(wtype.permission("edit")))]
    view = Annotated[Subject, Depends(require_permission(wtype.permission("view")))]
    policy = Annotated[PolicyService, Depends(get_policy)]
    audit = wtype.code.value

    @router.get("/alias/{value}", summary="Where an old number leads")
    async def alias(value: str, session: TenantSession, subject: view) -> AliasOut:
        """A converted record's old number: the record it became, if you may read it."""
        found = await service.follow_alias(session, subject, value)
        return AliasOut(
            record_type=found.record_type, record_id=found.record_id, display_id=found.display_id
        )

    @router.get("/{record_id}/convert-preview", summary="Preview a conversion")
    async def convert_preview(
        record_id: uuid.UUID, session: TenantSession, subject: edit
    ) -> ConvertPreviewOut:
        """Nothing changes; the same checks as the conversion."""
        shown = await service.preview(session, subject, wtype, record_id)
        return ConvertPreviewOut(
            record_id=shown.record.id,
            to_type=shown.target.code,
            carried_custom=shown.carried_custom,
            not_carried=shown.not_carried,
            pending_approvals=shown.pending_approvals,
        )

    @router.post("/{record_id}/convert", summary="Convert to the other type")
    async def convert(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        body: ConvertIn,
        version: ExpectedVersion,
        session: TenantSession,
        subject: edit,
        holders: policy,
        request: Request,
        response: Response,
        note: Annotated[AuditNote, audited(f"{audit}.converted", object_type=audit)],
    ) -> ConvertedOut:
        """A new record of the other type; this one becomes `converted`. Needs If-Match."""
        done = await service.convert(
            session,
            subject,
            wtype,
            record_id,
            target_values=body.model_dump(exclude_none=True),
            expected_version=version,
            holders=holders,
            source=source_of(request),
        )
        note.object_id = str(done.old.id)
        note.details = {
            "to": str(done.new.record.id),
            "to_type": done.new.record.type,
            "not_carried": done.not_carried,
        }
        set_etag(response, done.old.version)
        return ConvertedOut(
            old_id=done.old.id,
            old_version=done.old.version,
            new_id=done.new.record.id,
            new_display_id=done.new.record.display_id,
            new_type=WorkItemTypeCode(done.new.record.type),
            not_carried=done.not_carried,
        )
