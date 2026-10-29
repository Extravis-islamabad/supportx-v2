"""User directory endpoints: the reference list/detail/update endpoints for WP-008.

Every convention in docs/architecture/api-conventions.md is applied here: filter DSL, simple
query parameters, sorting, signed cursors, ETag / If-None-Match / If-Match, rate limiting.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission, require_signed_in
from app.core.database import TenantSession
from app.core.errors import ProblemDetail
from app.modules.identity_access.domain.identity import FormDensity, NavLayout, UserType
from app.modules.identity_access.domain.policy import Subject
from app.modules.identity_access.infra.models import User
from app.modules.identity_access.service import directory
from app.modules.identity_access.service.policy import visible
from app.shared.api.concurrency import ExpectedVersion, not_modified, set_etag
from app.shared.api.listing import ListQuery, Page, list_query
from app.shared.api.ratelimit import rate_limit
from app.shared.history import source_of
from app.shared.labels import strip_isolates

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

UsersQuery = Annotated[
    ListQuery, Depends(list_query(directory.USER_FIELDS, extra_parameters=frozenset({"q"})))
]


class UserDetail(BaseModel):
    """A user of the tenant. Codes (`user_type`, `status`, `locale`) render through labels."""

    id: uuid.UUID
    email: str | None = Field(description="Null for a contact without an address (WP-021).")
    display_name: str
    first_name: str
    last_name: str | None
    name_custom: bool = Field(description="The display name was set by hand, not 'first last'.")
    employee_id: str | None
    job_title: str | None
    description: str | None = Field(default=None, description="Only for `users.manage`.")
    phone: str | None
    mobile: str | None
    vip: bool
    site_id: uuid.UUID | None
    department_id: uuid.UUID | None
    manager_id: uuid.UUID | None
    can_sign_in: bool = Field(description="False: a contact, who cannot sign in.")
    invited_at: datetime | None = Field(default=None, description="Only for `users.manage`.")
    signed_in_before: bool = Field(
        default=False, description="Linked to a sign-in account (has signed in at least once)."
    )
    request_visibility: Literal["site"] | None
    user_type: UserType
    status: Literal["active", "disabled"]
    locale: Literal["en", "ar", "ur"]
    time_zone: str | None
    signature: str | None
    nav_layout: NavLayout
    form_density: FormDensity
    ui_locale: Literal["en", "ar", "ur"] | None = Field(
        default=None, description="Language picked in the app; null: Keycloak's `locale`."
    )
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime
    version: int = Field(description="Send it back as If-Match (the ETag) to update.")

    @classmethod
    def of(cls, user: User, subject: Subject) -> "UserDetail":
        """From the ORM row, with the fields the subject may not see hidden (WP-016)."""
        data = cls.model_validate(user, from_attributes=True).model_dump()
        data["signed_in_before"] = user.external_subject is not None
        return cls.model_validate(visible(subject, directory.USERS, data))


class UserPage(Page[UserDetail]):
    """One page of users."""


class UserPreferencesPatch(BaseModel):
    """Fields SupportX owns. Identity fields come from Keycloak and cannot be set here."""

    model_config = ConfigDict(extra="forbid")

    signature: str | None = Field(default=None, max_length=2000, description="Reply signature.")
    time_zone: str | None = Field(default=None, max_length=64, description="IANA, e.g. Asia/Dubai.")
    nav_layout: NavLayout | None = Field(
        default=None, description="Navigation: top bar, side bar or compact side bar."
    )
    form_density: FormDensity | None = Field(
        default=None, description="Record forms: comfortable (one column) or compact (two)."
    )
    ui_locale: str | None = Field(
        default=None,
        max_length=8,
        description="UI language (en, ar, ur); null: follow the identity provider's locale.",
    )


ViewUsers = Annotated[Subject, Depends(require_permission("users.view"))]
SignedIn = Annotated[Subject, Depends(require_signed_in())]
EditProfile = Annotated[Subject, Depends(require_permission("profile.edit"))]


@router.get("", summary="List users")
async def list_users(
    session: TenantSession,
    query: UsersQuery,
    subject: ViewUsers,
    q: Annotated[
        str | None,
        Query(
            max_length=200,
            description="Search names and emails: word starts, Arabic and Urdu spellings, typos.",
        ),
    ] = None,
) -> UserPage:
    """Users the caller may see (`users.view`, filtered to its scope).

    Filter with the DSL (`filter=`) and/or simple parameters (`status=active`), search with `q`,
    sort with `sort=-last_login_at,display_name`, page with `limit` and `cursor`.
    """
    page = await directory.list_users(
        session, subject, query, text=strip_isolates(q or "").strip() or None
    )
    return UserPage(
        items=[UserDetail.of(u, subject) for u in page.rows],
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
    user_id: uuid.UUID,
    request: Request,
    response: Response,
    session: TenantSession,
    subject: SignedIn,
) -> UserDetail:
    """One user, with its ETag. Yourself always; others with `users.view` in scope."""
    user = await directory.get_user(session, subject, user_id)
    cached = not_modified(request, user.version)
    if cached is not None:
        return cached  # type: ignore[return-value]  # 304 without a body
    set_etag(response, user.version)
    return UserDetail.of(user, subject)


@router.patch(
    "/{user_id}",
    summary="Update your preferences",
    responses={
        409: {"model": ProblemDetail, "description": "Stale If-Match (says who changed what)."},
        428: {"model": ProblemDetail, "description": "If-Match missing."},
    },
)
async def update_user(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    user_id: uuid.UUID,
    body: UserPreferencesPatch,
    version: ExpectedVersion,
    response: Response,
    session: TenantSession,
    subject: EditProfile,
    request: Request,
) -> UserDetail:
    """Change your own signature or time zone. Needs `If-Match` with the ETag you read.

    A stale If-Match gets 409 with `changed_fields`, `changed_by` and `changed_at`.
    """
    user = await directory.update_preferences(
        session,
        subject,
        user_id,
        expected_version=version,
        changes=body.model_dump(include=body.model_fields_set),
        source=source_of(request),
    )
    set_etag(response, user.version)
    return UserDetail.of(user, subject)
