"""User directory endpoints: the reference list/detail/update endpoints for WP-008.

Every convention in docs/architecture/api-conventions.md is applied here: filter DSL, simple
query parameters, sorting, signed cursors, ETag / If-None-Match / If-Match, rate limiting.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.core.database import TenantSession
from app.core.errors import ProblemDetail
from app.modules.identity_access.domain.identity import UserType
from app.modules.identity_access.infra.models import User
from app.modules.identity_access.service import directory
from app.shared.api.concurrency import ExpectedVersion, not_modified, set_etag
from app.shared.api.listing import ListQuery, Page, list_query
from app.shared.api.ratelimit import rate_limit

router = APIRouter(
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(rate_limit("users"))],
    responses={
        401: {"model": ProblemDetail, "description": "Not signed in."},
        403: {"model": ProblemDetail, "description": "Not allowed."},
        422: {"model": ProblemDetail, "description": "Invalid filter, sort, page size or body."},
        429: {"model": ProblemDetail, "description": "Rate limit exceeded."},
    },
)

UsersQuery = Annotated[ListQuery, Depends(list_query(directory.USER_FIELDS))]


class UserDetail(BaseModel):
    """A user of the tenant. Codes (`user_type`, `status`, `locale`) render through labels."""

    id: uuid.UUID
    email: str
    display_name: str
    user_type: UserType
    status: Literal["active", "disabled"]
    locale: Literal["en", "ar", "ur"]
    time_zone: str | None
    signature: str | None
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime
    version: int = Field(description="Send it back as If-Match (the ETag) to update.")

    @classmethod
    def of(cls, user: User) -> "UserDetail":
        """From the ORM row (values validated against the codes above)."""
        return cls.model_validate(user, from_attributes=True)


class UserPage(Page[UserDetail]):
    """One page of users."""


class UserPreferencesPatch(BaseModel):
    """Fields SupportX owns. Identity fields come from Keycloak and cannot be set here."""

    model_config = ConfigDict(extra="forbid")

    signature: str | None = Field(default=None, max_length=2000, description="Reply signature.")
    time_zone: str | None = Field(default=None, max_length=64, description="IANA, e.g. Asia/Dubai.")


@router.get("", summary="List users")
async def list_users(session: TenantSession, query: UsersQuery) -> UserPage:
    """Users of the tenant (technicians only).

    Filter with the DSL (`filter=`) and/or simple parameters (`status=active`), sort with
    `sort=-last_login_at,display_name`, page with `limit` and `cursor`.
    """
    page = await directory.list_users(session, query)
    return UserPage(
        items=[UserDetail.of(u) for u in page.rows],
        next_cursor=page.next_cursor,
        has_more=page.has_more,
        estimated_total=page.estimated_total,
    )


@router.get(
    "/{user_id}",
    summary="Get a user",
    responses={304: {"description": "Not modified (If-None-Match)."}},
)
async def get_user(
    user_id: uuid.UUID, request: Request, response: Response, session: TenantSession
) -> UserDetail:
    """One user, with its ETag. Yourself always; others only for technicians."""
    user = await directory.get_user(session, user_id)
    cached = not_modified(request, user.version)
    if cached is not None:
        return cached  # type: ignore[return-value]  # 304 without a body
    set_etag(response, user.version)
    return UserDetail.of(user)


@router.patch(
    "/{user_id}",
    summary="Update your preferences",
    responses={
        409: {"model": ProblemDetail, "description": "Stale If-Match (version_conflict)."},
        428: {"model": ProblemDetail, "description": "If-Match missing."},
    },
)
async def update_user(
    user_id: uuid.UUID,
    body: UserPreferencesPatch,
    version: ExpectedVersion,
    response: Response,
    session: TenantSession,
) -> UserDetail:
    """Change your own signature or time zone. Needs `If-Match` with the ETag you read."""
    user = await directory.update_preferences(
        session,
        user_id,
        expected_version=version,
        changes=body.model_dump(include=body.model_fields_set),
    )
    set_etag(response, user.version)
    return UserDetail.of(user)
