"""The shared list-settings store over HTTP (WP-049b s4a; app/shared/list_settings).

    GET    /api/v1/list-settings/{list_key}                        everything you keep for a list
    GET    /api/v1/list-settings/{list_key}/views/{view_key}       one view's settings
    PUT    /api/v1/list-settings/{list_key}/views/{view_key}       save them (If-Match after 1st)
    POST   /api/v1/list-settings/{list_key}/saved-views            save a view (Idempotency-Key)
    PATCH  /api/v1/list-settings/{list_key}/saved-views/{view_id}  change it (If-Match)
    DELETE /api/v1/list-settings/{list_key}/saved-views/{view_id}  remove it (If-Match)

Always the caller's own settings: a person's columns, saved views and stars, never anyone
else's. Reading the list itself needs the list's own permission and licence feature (its
`ListSpec`), checked here before anything is read or saved. Personal preferences, not
privileged writes: no audit entry (as work items' list settings).
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Response, status
from pydantic import BaseModel, Field

from app.core.authorization import require_signed_in
from app.core.database import TenantSession
from app.core.errors import EntitlementRequired, PermissionDenied, ProblemDetail
from app.modules.identity_access import Subject
from app.modules.licensing import has_feature
from app.shared import list_settings as store
from app.shared.api.concurrency import ExpectedVersion, etag_for, parse_etag, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.ratelimit import rate_limit
from app.shared.list_settings.domain import MAX_COLUMNS, NAME_MAX, SORT_MAX
from app.shared.list_settings.infra.models import ListSetting

router = APIRouter(
    prefix="/list-settings",
    tags=["list-settings"],
    dependencies=[Depends(rate_limit("list_settings"))],
    responses={
        401: {"model": ProblemDetail, "description": "Not signed in."},
        403: {"model": ProblemDetail, "description": "No access to the list, or its feature."},
        404: {"model": ProblemDetail, "description": "list_not_found, saved_view_not_found"},
    },
)
SignedIn = Annotated[Subject, Depends(require_signed_in())]
CONFLICT: dict[int | str, dict[str, object]] = {
    409: {"model": ProblemDetail, "description": "version_conflict"},
    428: {"model": ProblemDetail, "description": "If-Match is needed after the first save."},
}


async def _spec(list_key: str, subject: Subject) -> store.ListSpec:
    spec = store.list_spec(list_key)
    if spec.feature is not None and not await has_feature(subject.tenant_id, spec.feature):
        raise EntitlementRequired(params={"feature": spec.feature})
    if not subject.holds(spec.permission):
        raise PermissionDenied(params={"permission": spec.permission})
    return spec


class ListColumnIO(BaseModel):
    """One column: a field key (`custom.<key>` for custom fields) and its width in pixels."""

    key: str = Field(max_length=80)
    width: int | None = Field(default=None, description="Pixels (60-800); none: automatic.")


class ViewSettingOut(BaseModel):
    """Your settings of one view; `version` null: nothing saved yet (the screen's defaults).

    A saved view (`view_key` `custom:<id>`) also has its `name` and `filter`.
    """

    view_key: str
    saved_view_id: uuid.UUID | None = None
    name: str | None = None
    filter: dict[str, Any] | None = None
    columns: list[ListColumnIO]
    sort: str | None
    page_size: int
    favourite: bool
    version: int | None
    updated_at: datetime | None = None

    @classmethod
    def of(cls, view_key: str, row: ListSetting | None) -> "ViewSettingOut":
        """From a row, or the defaults."""
        if row is None:
            return cls(
                view_key=view_key, columns=[], sort=None, page_size=50, favourite=False,
                version=None,
            )  # fmt: skip
        return cls(
            view_key=row.view_key,
            saved_view_id=store.saved_view_id(row.view_key),
            name=row.name,
            filter=row.filter,
            columns=[ListColumnIO(**c) for c in row.columns],
            sort=row.sort,
            page_size=row.page_size,
            favourite=row.favourite,
            version=row.version,
            updated_at=row.updated_at,
        )


class ListSettingsOut(BaseModel):
    """Everything you keep for one list: saved views by name, then built-in views' settings."""

    list_key: str
    views: list[ViewSettingOut]


class ViewSettingIn(BaseModel):
    """Your columns, sort and page size for one view; `favourite` left out keeps the star."""

    columns: list[ListColumnIO] = Field(default_factory=list, max_length=MAX_COLUMNS)
    sort: str | None = Field(default=None, max_length=SORT_MAX)
    page_size: int = Field(default=50, description="25, 50 or 100.")
    favourite: bool | None = None


class SavedListViewIn(BaseModel):
    """A view to save: the list API's own `filter` and `sort`, as sent."""

    name: str = Field(max_length=NAME_MAX)
    filter: dict[str, Any] | None = Field(
        default=None, description="FilterExpression (the list's `filter`), or none for all."
    )
    columns: list[ListColumnIO] = Field(default_factory=list, max_length=MAX_COLUMNS)
    sort: str | None = Field(default=None, max_length=SORT_MAX)
    favourite: bool = False


class SavedListViewPatch(BaseModel):
    """Fields to change; those left out keep their value."""

    name: str | None = Field(default=None, max_length=NAME_MAX)
    filter: dict[str, Any] | None = None
    columns: list[ListColumnIO] | None = Field(default=None, max_length=MAX_COLUMNS)
    sort: str | None = Field(default=None, max_length=SORT_MAX)
    favourite: bool | None = None


@router.get("/{list_key}", summary="Your settings, saved views and favourites of a list")
async def list_settings(
    list_key: str, session: TenantSession, subject: SignedIn
) -> ListSettingsOut:
    """Saved views by name (yours only), then the settings you keep for built-in views."""
    spec = await _spec(list_key, subject)
    rows = await store.settings_of(session, subject.user_id, spec)
    return ListSettingsOut(
        list_key=spec.key, views=[ViewSettingOut.of(r.view_key, r) for r in rows]
    )


@router.get("/{list_key}/views/{view_key}", summary="Your settings of one view")
async def view_setting(
    list_key: str, view_key: str, session: TenantSession, subject: SignedIn, response: Response
) -> ViewSettingOut:
    """A built-in view code, `all`, or `custom:<saved view id>`."""
    spec = await _spec(list_key, subject)
    row = await store.view_setting(session, subject.user_id, spec, view_key)
    if row is not None:
        set_etag(response, row.version)
    return ViewSettingOut.of(view_key, row)


@router.put(
    "/{list_key}/views/{view_key}", summary="Save your settings of one view", responses=CONFLICT
)
async def save_view_setting(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    list_key: str,
    view_key: str,
    body: ViewSettingIn,
    session: TenantSession,
    subject: SignedIn,
    response: Response,
    if_match: Annotated[
        str | None,
        Header(alias="If-Match", description="The version read; none only for the first save."),
    ] = None,
) -> ViewSettingOut:
    """Columns (and widths), sort and page size of this view, for you only; star it or not."""
    spec = await _spec(list_key, subject)
    row = await store.save_view_setting(
        session,
        subject.user_id,
        spec,
        view_key,
        body.model_dump(mode="json"),
        expected_version=parse_etag(if_match) if if_match else None,
    )
    set_etag(response, row.version)
    return ViewSettingOut.of(view_key, row)


@router.post(
    "/{list_key}/saved-views",
    summary="Save a view of a list",
    status_code=status.HTTP_201_CREATED,
    response_model=ViewSettingOut,
)
async def create_saved_view(
    list_key: str,
    body: SavedListViewIn,
    session: TenantSession,
    subject: SignedIn,
    idempotency: Idempotency,
) -> Response:
    """The filter and sort are checked as the list checks them; names are unique per person."""
    spec = await _spec(list_key, subject)

    async def run() -> Created:
        row = await store.create_saved_view(
            session, subject.user_id, spec, body.model_dump(mode="json")
        )
        return Created(
            body=ViewSettingOut.of(row.view_key, row), headers={"ETag": etag_for(row.version)}
        )

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.patch(
    "/{list_key}/saved-views/{view_id}", summary="Change your saved view", responses=CONFLICT
)
async def update_saved_view(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    list_key: str,
    view_id: uuid.UUID,
    body: SavedListViewPatch,
    version: ExpectedVersion,
    session: TenantSession,
    subject: SignedIn,
    response: Response,
) -> ViewSettingOut:
    """Needs If-Match. Only the fields sent change."""
    spec = await _spec(list_key, subject)
    row = await store.update_saved_view(
        session,
        subject.user_id,
        spec,
        view_id,
        body.model_dump(mode="json", exclude_unset=True),
        expected_version=version,
    )
    set_etag(response, row.version)
    return ViewSettingOut.of(row.view_key, row)


@router.delete(
    "/{list_key}/saved-views/{view_id}",
    summary="Remove your saved view",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=CONFLICT,
)
async def delete_saved_view(
    list_key: str,
    view_id: uuid.UUID,
    version: ExpectedVersion,
    session: TenantSession,
    subject: SignedIn,
) -> Response:
    """Needs If-Match."""
    spec = await _spec(list_key, subject)
    await store.delete_saved_view(session, subject.user_id, spec, view_id, expected_version=version)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
