"""Configuration items linked to a record (WP-053 S5; REQ-CMDB-019): list, link and unlink.

    GET    /{record_id}/cis              the record's CIs, as the reader may see them
    POST   /{record_id}/cis              link CIs (Idempotency-Key)
    DELETE /{record_id}/cis/{link_id}    unlink one (If-Match on the link)

For incidents, service requests, problems, changes and releases. A CI that was removed, or that
the reader may not see, is listed marked (`gone` / `hidden`) without its ID label or name (lane
B's `cmdb.ci_refs`).
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.modules import cmdb
from app.modules.identity_access import Subject
from app.modules.work_items.domain.types import WorkItemType
from app.modules.work_items.infra.models import WorkItemCi
from app.modules.work_items.service import ci_links as service
from app.shared.api.concurrency import ExpectedVersion
from app.shared.api.idempotency import Created, Idempotency
from app.shared.history import source_of

CONFLICT_409: dict[int | str, dict[str, object]] = {
    409: {"description": "Someone changed the link meanwhile (RFC 9457 problem)."}
}


class WorkItemCiOut(BaseModel):
    """One linked CI; never more than the reader may see of it."""

    id: uuid.UUID = Field(description="The link (for unlinking).")
    ci_id: uuid.UUID
    display_id: str | None = Field(description="CI-12; none when gone or hidden.")
    name: str | None = Field(description="None when gone or hidden.")
    type_label_key: str | None = Field(description="A built-in type's label key.")
    type_names: dict[str, str] = Field(description="A tenant's own type, its name per language.")
    state_category: str | None = Field(description="The state's category code.")
    gone: bool = Field(description="The CI was removed.")
    hidden: bool = Field(description="You may not see this CI.")
    at_creation: bool = Field(description="Linked as the record was raised.")
    source: str = Field(description="How it was linked: ui, api, portal, system.")
    version: int
    created_at: datetime

    @classmethod
    def of(cls, row: WorkItemCi, ref: cmdb.CiRef) -> "WorkItemCiOut":
        """The link with the CI as the reader may see it."""
        return cls(
            id=row.id,
            ci_id=row.ci_id,
            display_id=ref.display_id,
            name=ref.name,
            type_label_key=ref.type_label_key,
            type_names=dict(ref.type_names),
            state_category=ref.state_category,
            gone=ref.gone,
            hidden=ref.hidden,
            at_creation=row.at_creation,
            source=row.source,
            version=row.version,
            created_at=row.created_at,
        )


class WorkItemCisOut(BaseModel):
    """A record's linked CIs, in the order they were linked."""

    items: list[WorkItemCiOut]


class WorkItemCisIn(BaseModel):
    """CIs to link; ones already linked are left as they are."""

    model_config = ConfigDict(extra="forbid")
    ci_ids: list[uuid.UUID] = Field(min_length=1, max_length=service.MAX_LINKS)


def add_ci_routes(router: APIRouter, wtype: WorkItemType) -> None:
    """The record's CIs."""
    View = Annotated[Subject, Depends(require_permission(wtype.permission("view")))]  # noqa: N806 - type alias

    @router.get("/{record_id}/cis", summary="CIs linked to a record")
    async def list_cis(
        record_id: uuid.UUID, session: TenantSession, subject: View
    ) -> WorkItemCisOut:
        """In the order they were linked; removed or hidden CIs marked, never named."""
        found = await service.linked(session, subject, wtype, record_id)
        return WorkItemCisOut(items=[WorkItemCiOut.of(row, ref) for row, ref in found])

    @router.post(
        "/{record_id}/cis",
        summary="Link CIs to a record",
        status_code=status.HTTP_201_CREATED,
        response_model=WorkItemCisOut,
    )
    async def link_cis(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        body: WorkItemCisIn,
        session: TenantSession,
        subject: View,
        idempotency: Idempotency,
        request: Request,
    ) -> Response:
        """Link CIs: the record's edit right, the cmdb feature, each one you may link."""

        async def run() -> Created:
            await service.link(
                session, subject, wtype, record_id, body.ci_ids, source=source_of(request)
            )
            found = await service.linked(session, subject, wtype, record_id)
            return Created(
                body=WorkItemCisOut(items=[WorkItemCiOut.of(row, ref) for row, ref in found])
            )

        return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)

    @router.delete(
        "/{record_id}/cis/{link_id}",
        summary="Unlink a CI",
        status_code=status.HTTP_204_NO_CONTENT,
        responses=CONFLICT_409,
    )
    async def unlink_ci(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        link_id: uuid.UUID,
        version: ExpectedVersion,
        session: TenantSession,
        subject: View,
        request: Request,
    ) -> Response:
        """Needs If-Match on the link."""
        await service.unlink(
            session,
            subject,
            wtype,
            record_id,
            link_id,
            expected_version=version,
            source=source_of(request),
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["add_ci_routes"]
