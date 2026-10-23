"""Sites and support groups: list with members, create, rename, add/remove members (WP-016).

Basic level: enough to give users the `site` and `group` scopes. Full admin screens later.
"""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.core.errors import ProblemDetail
from app.modules.organization.service import units
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.ratelimit import rate_limit

RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ProblemDetail, "description": "Not signed in."},
    403: {"model": ProblemDetail, "description": "Missing permission."},
    404: {"model": ProblemDetail, "description": "No such site, group or user."},
    409: {"model": ProblemDetail, "description": "Name taken or stale If-Match."},
}


class UnitOut(BaseModel):
    """A site or support group with the IDs of its members."""

    id: uuid.UUID
    name: str
    version: int = Field(description="Send back as If-Match to rename.")
    member_ids: list[uuid.UUID]


class UnitIn(BaseModel):
    """Name of a site or group."""

    name: str = Field(min_length=1, max_length=200)


def _out(view: units.UnitView) -> UnitOut:
    return UnitOut(id=view.id, name=view.name, version=view.version, member_ids=view.member_ids)


def build_router(kind: Literal["site", "group"]) -> APIRouter:
    """The same five endpoints for sites (/organization/sites) and groups (/organization/groups)."""
    plural = "sites" if kind == "site" else "groups"
    view = Depends(require_permission(f"{plural}.view"))
    manage = Depends(require_permission(f"{plural}.manage"))
    router = APIRouter(
        prefix=f"/organization/{plural}",
        tags=["organization"],
        dependencies=[Depends(rate_limit("organization"))],
        responses=RESPONSES,
    )

    @router.get("", summary=f"List {plural}", dependencies=[view])
    async def list_units(session: TenantSession) -> list[UnitOut]:
        """All of them, by name, with member IDs."""
        return [_out(v) for v in await units.list_units(session, kind)]

    @router.post(
        "", summary=f"Create a {kind}", status_code=status.HTTP_201_CREATED, dependencies=[manage]
    )
    async def create_unit(
        body: UnitIn, session: TenantSession, idempotency: Idempotency
    ) -> Response:
        """Create one (Idempotency-Key supported)."""

        async def operation() -> Created:
            created = _out(await units.create_unit(session, kind, body.name))
            return Created(created, {"ETag": f'"{created.version}"'})

        return await idempotency.run(body, operation)

    @router.patch("/{unit_id}", summary=f"Rename a {kind}", dependencies=[manage])
    async def rename_unit(
        unit_id: uuid.UUID,
        body: UnitIn,
        version: ExpectedVersion,
        response: Response,
        session: TenantSession,
    ) -> UnitOut:
        """Rename (If-Match with the version you read)."""
        renamed = await units.rename_unit(session, kind, unit_id, body.name, version)
        set_etag(response, renamed.version)
        return _out(renamed)

    @router.put(
        "/{unit_id}/members/{user_id}",
        summary=f"Add a member to a {kind}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[manage],
    )
    async def add_member(
        unit_id: uuid.UUID, user_id: uuid.UUID, session: TenantSession
    ) -> Response:
        """Idempotent: adding an existing member changes nothing."""
        await units.add_member(session, kind, unit_id, user_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.delete(
        "/{unit_id}/members/{user_id}",
        summary=f"Remove a member from a {kind}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[manage],
    )
    async def remove_member(
        unit_id: uuid.UUID, user_id: uuid.UUID, session: TenantSession
    ) -> Response:
        """Idempotent: removing a non-member changes nothing."""
        await units.remove_member(session, kind, unit_id, user_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router


sites_router = build_router("site")
groups_router = build_router("group")
