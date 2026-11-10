"""Assets linked to a record (REQ-AST-025): list, link and unlink.

    GET    /{record_id}/assets              the record's assets, as the reader may see them
    POST   /{record_id}/assets              link assets (Idempotency-Key)
    DELETE /{record_id}/assets/{link_id}    unlink one (If-Match on the link)

An asset that was removed, or that the reader may not see, is listed marked (`gone` / `hidden`)
without its tag or name (lane B's `assets.asset_refs`).
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.modules import assets
from app.modules.identity_access import Subject
from app.modules.work_items.domain.types import WorkItemType
from app.modules.work_items.infra.models import WorkItemAsset
from app.modules.work_items.service import asset_links as service
from app.shared.api.concurrency import ExpectedVersion
from app.shared.api.idempotency import Created, Idempotency
from app.shared.history import source_of

CONFLICT_409: dict[int | str, dict[str, object]] = {
    409: {"description": "Someone changed the link meanwhile (RFC 9457 problem)."}
}


class WorkItemAssetOut(BaseModel):
    """One linked asset; never more than the reader may see of it."""

    id: uuid.UUID = Field(description="The link (for unlinking).")
    asset_id: uuid.UUID
    tag: str | None = Field(description="AST-12; none when gone or hidden.")
    name: str | None = Field(description="None when gone or hidden.")
    gone: bool = Field(description="The asset was removed.")
    hidden: bool = Field(description="You may not see this asset.")
    mine: bool = Field(description="You hold it.")
    source: str = Field(description="How it was linked: ui, api, portal or email.")
    version: int
    created_at: datetime

    @classmethod
    def of(cls, row: WorkItemAsset, ref: assets.AssetRef) -> "WorkItemAssetOut":
        """The link with the asset as the reader may see it."""
        return cls(
            id=row.id,
            asset_id=row.asset_id,
            tag=ref.tag,
            name=ref.name,
            gone=ref.gone,
            hidden=ref.hidden,
            mine=ref.mine,
            source=row.source,
            version=row.version,
            created_at=row.created_at,
        )


class WorkItemAssetsOut(BaseModel):
    """A record's linked assets, in the order they were linked."""

    items: list[WorkItemAssetOut]


class WorkItemAssetsIn(BaseModel):
    """Assets to link; ones already linked are left as they are."""

    model_config = ConfigDict(extra="forbid")
    asset_ids: list[uuid.UUID] = Field(min_length=1, max_length=service.MAX_LINKS)


def add_asset_routes(router: APIRouter, wtype: WorkItemType) -> None:
    """The record's assets."""
    View = Annotated[Subject, Depends(require_permission(wtype.permission("view")))]  # noqa: N806 - type alias

    @router.get("/{record_id}/assets", summary="Assets linked to a record")
    async def list_assets(
        record_id: uuid.UUID, session: TenantSession, subject: View
    ) -> WorkItemAssetsOut:
        """In the order they were linked; removed or hidden assets marked, never named."""
        found = await service.linked(session, subject, wtype, record_id)
        return WorkItemAssetsOut(items=[WorkItemAssetOut.of(row, ref) for row, ref in found])

    @router.post(
        "/{record_id}/assets",
        summary="Link assets to a record",
        status_code=status.HTTP_201_CREATED,
        response_model=WorkItemAssetsOut,
    )
    async def link_assets(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        body: WorkItemAssetsIn,
        session: TenantSession,
        subject: View,
        idempotency: Idempotency,
        request: Request,
    ) -> Response:
        """Link assets: the record's edit right, the assets feature, at most 20 a record.

        Each asset must be one you may see, or one you hold.
        """

        async def run() -> Created:
            await service.link(
                session, subject, wtype, record_id, body.asset_ids, source=source_of(request)
            )
            found = await service.linked(session, subject, wtype, record_id)
            return Created(
                body=WorkItemAssetsOut(items=[WorkItemAssetOut.of(row, ref) for row, ref in found])
            )

        return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)

    @router.delete(
        "/{record_id}/assets/{link_id}",
        summary="Unlink an asset",
        status_code=status.HTTP_204_NO_CONTENT,
        responses=CONFLICT_409,
    )
    async def unlink_asset(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        link_id: uuid.UUID,
        version: ExpectedVersion,
        session: TenantSession,
        subject: View,
        request: Request,
    ) -> Response:
        """Needs If-Match on the link; history names the asset taken off."""
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
