"""My access held elsewhere (WP-057 S5c-1b; D-188, lane B's Q3 conditions).

`GET /identity/my-access/elsewhere`: the access a sign-in group gives the signed-in person that
this session does not apply, with the provider it applies through. The profile says "Some of
your access comes from your sign-in group and only applies when you sign in with <provider>".

- The person is the session's own: no ID in the path or query, so it is self only by
  construction. Signed in, no permission; a vendor support session gets an empty list.
- Names only for the text (role, group, provider); a system role carries its key for its label.
- Nothing held elsewhere is an empty list, never a 404.
"""

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.core.authorization import require_signed_in
from app.core.database import TenantSession
from app.core.tenancy import resolve_tenant
from app.modules.identity_access.service import group_mappings
from app.shared.api.ratelimit import rate_limit

router = APIRouter(
    prefix="/identity/my-access",
    tags=["identity"],
    dependencies=[Depends(rate_limit("identity"))],
)
SignedIn = Annotated[Any, Depends(require_signed_in())]  # the module's Subject


class HeldElsewhereOut(BaseModel):
    """One role or support group that only applies through another sign-in."""

    kind: Literal["role", "group"]
    id: uuid.UUID
    name: str = Field(description="The role's or group's name (a system role: use its label).")
    role_key: str | None = Field(default=None, description="A role's key, for its label.")
    is_system: bool = False
    provider_name: str = Field(description="The sign-in it applies through.")


@router.get("/elsewhere", summary="My access that applies only through another sign-in")
async def my_access_elsewhere(
    request: Request, session: TenantSession, subject: SignedIn
) -> list[HeldElsewhereOut]:
    """Live with the session's permissions: the same filter the session's compile uses."""
    context = await resolve_tenant(request)
    if context.user_id is None or subject.support_grant_id is not None:
        return []  # vendor support holds a grant's access only, never a sign-in group's
    found = await group_mappings.held_elsewhere(session, context.user_id, context.access_source)
    return [
        HeldElsewhereOut(
            kind=h.kind,
            id=h.target_id,
            name=h.name,
            role_key=h.role_key,
            is_system=h.system,
            provider_name=h.provider_name,
        )
        for h in found
    ]
