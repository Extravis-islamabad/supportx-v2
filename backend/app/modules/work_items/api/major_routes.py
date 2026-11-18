"""Major incidents over the API (WP-046b S4; REQ-INC-141, D-043 Essentials).

- POST /incidents/{id}/major            declare it major, with a reason (If-Match)
- POST /incidents/{id}/major/end        end the major status, with a reason (If-Match)
- GET  /incidents/majors                the open major incidents you may see
- GET  /incidents/settings/major        the major incident team and template
- PUT  /incidents/settings/major        set them (If-Match on the type's settings; audited)

Declaring and ending need `incidents.declare_major` (administrators and service desk managers by
default) and are audited by the service, the reason in the entry's personal part. No recent
sign-in (coordinator, 2026-11-17).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.modules.audit import AuditNote, RequestFacts, audited
from app.modules.identity_access import Subject
from app.modules.work_items.domain.types import WorkItemType
from app.modules.work_items.infra.models import WorkItem
from app.modules.work_items.service import catalogue
from app.modules.work_items.service import major_incidents as service
from app.modules.work_items.service.access import DECLARE_MAJOR
from app.modules.work_items.service.major_incidents import REASON_MAX
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.history import source_of


class IncidentMajorIn(BaseModel):
    """Why the incident is declared major, or why that ends."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(max_length=REASON_MAX)


class IncidentMajorOut(BaseModel):
    """The incident's major status after the change."""

    id: uuid.UUID
    major: bool
    version: int = Field(description="The new version (also the ETag).")
    template_id: uuid.UUID | None = Field(description="The template now (the major one, if set).")


class MajorIncidentOut(BaseModel):
    """One open major incident in the list."""

    id: uuid.UUID
    display_id: str
    subject: str
    status: str
    major_declared_at: str | None


class MajorSettingsIn(BaseModel):
    """The major incident team (a group and named people) and template (none: keep their own)."""

    model_config = ConfigDict(extra="forbid")

    group_id: uuid.UUID | None = None
    user_ids: list[uuid.UUID] = Field(default_factory=list, max_length=service.MAJOR_USERS_MAX)
    template_id: uuid.UUID | None = None


class MajorSettingsOut(BaseModel):
    """The major incident settings, with the type settings' version (the ETag)."""

    group_id: uuid.UUID | None
    user_ids: list[uuid.UUID]
    template_id: uuid.UUID | None
    settings_version: int


def add_major_routes(router: APIRouter, wtype: WorkItemType) -> None:
    """The routes for incidents (declare and end their own right; settings the admin's)."""
    declare_right = Annotated[Subject, Depends(require_permission(wtype.permission(DECLARE_MAJOR)))]
    view = Annotated[Subject, Depends(require_permission(wtype.permission("view")))]
    admin = Annotated[
        Subject, Depends(require_permission("config.service_desk", "settings.manage"))
    ]

    def answer(record: WorkItem, response: Response) -> IncidentMajorOut:
        set_etag(response, record.version)
        return IncidentMajorOut(
            id=record.id, major=record.major, version=record.version, template_id=record.template_id
        )

    @router.get("/majors", summary="Open major incidents")
    async def majors(session: TenantSession, subject: view) -> list[MajorIncidentOut]:
        """The open major incidents you may see, newest declaration first."""
        return [
            MajorIncidentOut(
                id=r.id,
                display_id=r.display_id,
                subject=r.subject,
                status=r.status,
                major_declared_at=r.major_declared_at.isoformat() if r.major_declared_at else None,
            )
            for r in await service.majors_open(session, subject)
        ]

    @router.post("/{record_id}/major", summary="Declare a major incident")
    async def declare(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        body: IncidentMajorIn,
        version: ExpectedVersion,
        session: TenantSession,
        subject: declare_right,
        request: Request,
        response: Response,
    ) -> IncidentMajorOut:
        """Open incidents you may edit; 409 `already_major`; the major template applies."""
        record = await service.declare(
            session,
            subject,
            record_id,
            expected_version=version,
            reason=body.reason,
            source=source_of(request),
            facts=RequestFacts.of(request),
        )
        return answer(record, response)

    @router.post("/{record_id}/major/end", summary="End a major incident's major status")
    async def end(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        body: IncidentMajorIn,
        version: ExpectedVersion,
        session: TenantSession,
        subject: declare_right,
        request: Request,
        response: Response,
    ) -> IncidentMajorOut:
        """409 `not_major` when it is not; the declaration stays in history."""
        record = await service.end(
            session,
            subject,
            record_id,
            expected_version=version,
            reason=body.reason,
            source=source_of(request),
            facts=RequestFacts.of(request),
        )
        return answer(record, response)

    @router.get("/settings/major", summary="Major incident settings")
    async def major_settings(
        session: TenantSession, subject: admin, response: Response
    ) -> MajorSettingsOut:
        """The team told when an incident is declared major, and the template it switches to."""
        del subject
        cat = await catalogue.load(session, wtype)
        set_etag(response, cat.settings_version)
        return MajorSettingsOut(
            group_id=cat.major.group_id,
            user_ids=list(cat.major.user_ids),
            template_id=cat.major.template_id,
            settings_version=cat.settings_version,
        )

    @router.put("/settings/major", summary="Set the major incident team and template")
    async def put_major_settings(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        body: MajorSettingsIn,
        session: TenantSession,
        subject: admin,
        version: ExpectedVersion,
        response: Response,
        request: Request,
        note: Annotated[
            AuditNote,
            audited("incident.major_settings_changed", object_type="incident_settings"),
        ],
    ) -> MajorSettingsOut:
        """A live group, active people (at most 50), a live incident template; IDs audited."""
        cat, before, after = await service.update_settings(
            session,
            group_id=body.group_id,
            user_ids=body.user_ids,
            template_id=body.template_id,
            expected_version=version,
            source=source_of(request),
            user_id=subject.user_id,
        )
        note.details = {"before": before, "after": after}
        set_etag(response, cat.settings_version)
        return MajorSettingsOut(
            group_id=cat.major.group_id,
            user_ids=list(cat.major.user_ids),
            template_id=cat.major.template_id,
            settings_version=cat.settings_version,
        )
