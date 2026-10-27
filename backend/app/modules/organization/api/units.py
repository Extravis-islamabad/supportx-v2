"""Members of sites and support groups: add and remove (WP-016; the `site` / `group` scopes).

The sites and groups themselves (list, add, change, remove) are in structure.py (WP-021).
"""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Response, status

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.core.errors import ProblemDetail
from app.modules.audit import audited
from app.modules.organization.service import units
from app.shared.api.ratelimit import rate_limit

RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ProblemDetail, "description": "Not signed in."},
    403: {"model": ProblemDetail, "description": "Missing permission."},
    404: {"model": ProblemDetail, "description": "No such site, group or user."},
    409: {"model": ProblemDetail, "description": "Name taken or stale If-Match."},
}


def build_router(kind: Literal["site", "group"]) -> APIRouter:
    """The member endpoints for sites (/organization/sites) and groups (/organization/groups)."""
    plural = "sites" if kind == "site" else "groups"
    manage = Depends(require_permission(f"{plural}.manage"))
    router = APIRouter(
        prefix=f"/organization/{plural}",
        tags=["organization"],
        dependencies=[Depends(rate_limit("organization"))],
        responses=RESPONSES,
    )

    @router.put(
        "/{unit_id}/members/{user_id}",
        summary=f"Add a member to a {kind}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[
            manage,
            audited(
                f"{kind}.member_added",
                object_type=kind,
                object_param="unit_id",
                detail_params=("user_id",),
            ),
        ],
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
        dependencies=[
            manage,
            audited(
                f"{kind}.member_removed",
                object_type=kind,
                object_param="unit_id",
                detail_params=("user_id",),
            ),
        ],
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
