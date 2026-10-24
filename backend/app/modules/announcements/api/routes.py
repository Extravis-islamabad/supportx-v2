"""Announcements HTTP API under /api/v1/announcements (WP-012). No business logic here.

Staff routes need `announcements.view` / `.manage` / `.publish` (scope-filtered in the service).
`GET /feed` and `GET /{id}` are for any signed-in user: they return only what is live for them.
Writes use If-Match (409 explains who changed what); create takes an Idempotency-Key.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission, require_signed_in
from app.core.database import TenantSession
from app.core.errors import ProblemDetail
from app.modules.announcements.domain.announcement import (
    BODY_MAX,
    REASON_MAX,
    TITLE_MAX,
    AnnouncementAction,
    AnnouncementAudience,
    AnnouncementSeverity,
    AnnouncementStatus,
    AnnouncementVisibility,
    Window,
    next_change,
    visibility,
)
from app.modules.announcements.infra.models import Announcement
from app.modules.announcements.service import announcements as service
from app.modules.identity_access import PolicyService, Subject, get_policy
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.listing import ListQuery, Page, PageResult, list_query
from app.shared.api.ratelimit import rate_limit
from app.shared.history import HistoryEntry, source_of

Responses = dict[int | str, dict[str, object]]
RESPONSES: Responses = {
    401: {"model": ProblemDetail, "description": "Not signed in."},
    403: {"model": ProblemDetail, "description": "Missing permission or licence feature."},
    404: {"model": ProblemDetail, "description": "No such announcement visible to you."},
}
CONFLICT: Responses = {
    409: {
        "model": ProblemDetail,
        "description": "Stale If-Match: version_conflict, who changed what.",
    }
}
TRANSITION_DOC: Responses = {
    409: {
        "model": ProblemDetail,
        "description": "invalid_transition, cannot_publish (with a reason) or version_conflict.",
    }
}

router = APIRouter(
    prefix="/announcements",
    tags=["announcements"],
    dependencies=[Depends(rate_limit("announcements"))],
    responses=RESPONSES,
)

View = Annotated[Subject, Depends(require_permission(service.VIEW))]
Manage = Annotated[Subject, Depends(require_permission(service.MANAGE))]
Publish = Annotated[Subject, Depends(require_permission(service.PUBLISH))]
SignedIn = Annotated[Subject, Depends(require_signed_in())]
SettingsAdmin = Annotated[Subject, Depends(require_permission("settings.manage"))]
Policy = Annotated[PolicyService, Depends(get_policy)]
AnnouncementsQuery = Annotated[ListQuery, Depends(list_query(service.ANNOUNCEMENT_FIELDS))]


# --- schemas --------------------------------------------------------------------------------------


class AnnouncementIn(BaseModel):
    """A new announcement (always saved as a draft)."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(max_length=TITLE_MAX)
    body: str = Field(max_length=BODY_MAX, description="Plain text; line breaks are kept.")
    severity: AnnouncementSeverity = AnnouncementSeverity.INFO
    audience: AnnouncementAudience = AnnouncementAudience.EVERYONE
    site_ids: list[uuid.UUID] = Field(default_factory=list, description="When audience = sites.")
    group_ids: list[uuid.UUID] = Field(default_factory=list, description="When audience = groups.")
    show_as_banner: bool = False
    publish_from: datetime | None = None
    publish_until: datetime | None = None
    owner_id: uuid.UUID | None = Field(default=None, description="Default: you.")


class AnnouncementPatch(BaseModel):
    """Fields to change (only those sent). The status changes through actions, not here."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=TITLE_MAX)
    body: str | None = Field(default=None, max_length=BODY_MAX)
    severity: AnnouncementSeverity | None = None
    audience: AnnouncementAudience | None = None
    site_ids: list[uuid.UUID] | None = None
    group_ids: list[uuid.UUID] | None = None
    show_as_banner: bool | None = None
    publish_from: datetime | None = None
    publish_until: datetime | None = None
    owner_id: uuid.UUID | None = None


class TransitionIn(BaseModel):
    """Optional reason (unpublish and archive), kept in the history."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=REASON_MAX)


class ActionStateOut(BaseModel):
    """A status action as you may use it now. Disabled ones carry a reason code (labelled)."""

    action: AnnouncementAction
    allowed: bool
    reason: str | None = None


class AnnouncementOut(BaseModel):
    """An announcement as staff see it."""

    kind: Literal["staff"] = "staff"
    id: uuid.UUID
    display_id: str
    title: str
    body: str
    severity: AnnouncementSeverity
    status: AnnouncementStatus
    audience: AnnouncementAudience
    site_ids: list[uuid.UUID]
    group_ids: list[uuid.UUID]
    owner_id: uuid.UUID
    show_as_banner: bool
    publish_from: datetime | None
    publish_until: datetime | None
    published_at: datetime | None
    published_by: uuid.UUID | None
    created_at: datetime
    created_by: uuid.UUID | None
    updated_at: datetime
    updated_by: uuid.UUID | None
    version: int = Field(description="Send it back as If-Match (the ETag) to change it.")
    visibility: AnnouncementVisibility
    next_change_in_seconds: float | None = Field(
        description="Seconds until its visibility changes by the clock (window start or end)."
    )
    actions: list[ActionStateOut]
    history_count: int
    can_manage: bool = Field(description="Whether you may edit or delete it (UI hint only).")

    @classmethod
    def of(cls, view: service.AnnouncementView) -> "AnnouncementOut":
        """From the service view."""
        r = view.record
        return cls(
            id=r.id,
            display_id=r.display_id,
            title=r.title,
            body=r.body,
            severity=AnnouncementSeverity(r.severity),
            status=AnnouncementStatus(r.status),
            audience=AnnouncementAudience(r.audience),
            site_ids=view.site_ids,
            group_ids=view.group_ids,
            owner_id=r.owner_id,
            show_as_banner=r.show_as_banner,
            publish_from=r.publish_from,
            publish_until=r.publish_until,
            published_at=r.published_at,
            published_by=r.published_by,
            created_at=r.created_at,
            created_by=r.created_by,
            updated_at=r.updated_at,
            updated_by=r.updated_by,
            version=r.version,
            visibility=AnnouncementVisibility(view.visibility),
            next_change_in_seconds=view.next_change_in_seconds,
            actions=[
                ActionStateOut(
                    action=AnnouncementAction(a.action), allowed=a.allowed, reason=a.reason
                )
                for a in view.actions
            ],
            history_count=view.history_count,
            can_manage=view.can_manage,
        )


class OwnerCandidateOut(BaseModel):
    """Someone who may own an announcement (holds announcements.manage)."""

    id: uuid.UUID
    display_name: str


class AnnouncementPublicOut(BaseModel):
    """An announcement as its audience sees it (nothing about owners or workflow)."""

    kind: Literal["public"] = "public"
    id: uuid.UUID
    display_id: str
    title: str
    body: str
    severity: AnnouncementSeverity
    show_as_banner: bool
    published_at: datetime | None
    publish_until: datetime | None
    visibility: AnnouncementVisibility
    next_change_in_seconds: float | None

    @classmethod
    def of(
        cls, record: Announcement, visibility: str, next_change_in_seconds: float | None
    ) -> "AnnouncementPublicOut":
        """From a live record."""
        return cls(
            id=record.id,
            display_id=record.display_id,
            title=record.title,
            body=record.body,
            severity=AnnouncementSeverity(record.severity),
            show_as_banner=record.show_as_banner,
            published_at=record.published_at,
            publish_until=record.publish_until,
            visibility=AnnouncementVisibility(visibility),
            next_change_in_seconds=next_change_in_seconds,
        )


class AnnouncementListItem(BaseModel):
    """One row of the staff list."""

    id: uuid.UUID
    display_id: str
    title: str
    severity: AnnouncementSeverity
    status: AnnouncementStatus
    audience: AnnouncementAudience
    owner_id: uuid.UUID
    show_as_banner: bool
    publish_from: datetime | None
    publish_until: datetime | None
    published_at: datetime | None
    updated_at: datetime
    deleted_at: datetime | None
    version: int
    visibility: AnnouncementVisibility


class AnnouncementPage(Page[AnnouncementListItem]):
    """One page of the staff list, and when the first row's visibility changes."""

    next_change_in_seconds: float | None = None


class FeedOut(BaseModel):
    """What is live for you now (banners and the portal), and when that changes."""

    items: list[AnnouncementPublicOut]
    next_change_in_seconds: float | None = Field(
        description="Refetch after this many seconds (a window starts or ends); null: no timer."
    )


# The codes an announcement's history can hold. Work items added more history kinds and sources
# (ADR-026); announcements never produce them, so their published contract stays as it was.
AnnouncementChangeKind = Literal["created", "updated", "status", "deleted", "restored"]
AnnouncementChangeSource = Literal["ui", "api", "rule", "workflow", "ai_agent", "system", "import"]


class FieldChangeOut(BaseModel):
    """One field of one save. Values are codes, IDs, text or ISO times; the UI labels them."""

    field: str
    old: Any = None
    new: Any = None


class HistoryEntryOut(BaseModel):
    """One save."""

    version: int
    kind: AnnouncementChangeKind
    occurred_at: datetime
    actor_type: Literal["user", "system"]
    actor_id: str | None
    actor_name: str | None
    source: AnnouncementChangeSource
    reason: str | None
    changes: list[FieldChangeOut]

    @classmethod
    def of(cls, entry: HistoryEntry, names: dict[str, str]) -> "HistoryEntryOut":
        """From a history entry plus resolved actor names."""
        return cls(
            version=entry.version,
            kind=entry.kind,  # type: ignore[arg-type]  # announcements write only these kinds
            occurred_at=entry.occurred_at,
            actor_type="user" if entry.actor_type == "user" else "system",
            actor_id=entry.actor_id,
            actor_name=names.get(entry.actor_id or ""),
            source=entry.source,  # type: ignore[arg-type]  # ... and only these sources
            reason=entry.reason,
            changes=[FieldChangeOut(field=c.field, old=c.old, new=c.new) for c in entry.changes],
        )


class HistoryOut(BaseModel):
    """Saves of one announcement, newest first."""

    items: list[HistoryEntryOut]
    next_cursor: str | None


class SettingsOut(BaseModel):
    """The module's tenant settings. `version` 0 = never changed."""

    require_second_publisher: bool = Field(
        description="Four-eyes: the owner or author of an announcement may not publish it."
    )
    version: int


class SettingsIn(BaseModel):
    """New settings."""

    model_config = ConfigDict(extra="forbid")

    require_second_publisher: bool


def _item(row: Announcement, now: datetime) -> AnnouncementListItem:
    return AnnouncementListItem(
        id=row.id,
        display_id=row.display_id,
        title=row.title,
        severity=AnnouncementSeverity(row.severity),
        status=AnnouncementStatus(row.status),
        audience=AnnouncementAudience(row.audience),
        owner_id=row.owner_id,
        show_as_banner=row.show_as_banner,
        publish_from=row.publish_from,
        publish_until=row.publish_until,
        published_at=row.published_at,
        updated_at=row.updated_at,
        deleted_at=row.deleted_at,
        version=row.version,
        visibility=AnnouncementVisibility(
            visibility(row.status, Window(row.publish_from, row.publish_until), now)
        ),
    )


def _location(announcement_id: uuid.UUID) -> str:
    return f"/api/v1/announcements/{announcement_id}"


# --- routes: lists and feeds (before /{id}) -------------------------------------------------


def _page(page: PageResult[Announcement], seconds: float | None) -> AnnouncementPage:
    now = datetime.now(UTC)
    return AnnouncementPage(
        items=[_item(row, now) for row in page.rows],
        next_cursor=page.next_cursor,
        has_more=page.has_more,
        estimated_total=page.estimated_total,
        next_change_in_seconds=seconds,
    )


@router.get("", summary="List announcements")
async def list_announcements(
    session: TenantSession, query: AnnouncementsQuery, subject: View
) -> AnnouncementPage:
    """Announcements you may see as staff (scope-filtered), drafts and archive included.

    Filter with the DSL (`filter=`) or simple parameters (`status=published`), sort with
    `sort=-updated_at`, page with `limit`/`cursor`.
    """
    return _page(*await service.list_announcements(session, subject, query))


@router.get("/trash", summary="Announcements in the trash")
async def list_trash(
    session: TenantSession, query: AnnouncementsQuery, subject: View
) -> AnnouncementPage:
    """Deleted announcements you may see, with the same filters; restore with POST …/restore."""
    return _page(*await service.list_announcements(session, subject, query, trash=True))


@router.get("/feed", summary="Announcements live for you")
async def feed(session: TenantSession, subject: SignedIn) -> FeedOut:
    """Published, inside their window, addressed to you. Used by banners and the portal."""
    found = await service.feed(session, subject)
    now = datetime.now(UTC)
    items = []
    for row in found.items:
        window = Window(row.publish_from, row.publish_until)
        moment = next_change(row.status, window, now)
        items.append(
            AnnouncementPublicOut.of(
                row,
                visibility(row.status, window, now),
                None if moment is None else round((moment - now).total_seconds(), 3),
            )
        )
    return FeedOut(items=items, next_change_in_seconds=found.next_change_in_seconds)


@router.get("/owner-candidates", summary="People who may own an announcement")
async def owner_candidates(  # noqa: PLR0913, PLR0917 - FastAPI dependencies and query options
    session: TenantSession,
    subject: Manage,
    policy: Policy,
    search: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    include: Annotated[list[uuid.UUID] | None, Query(max_length=5)] = None,
) -> list[OwnerCandidateOut]:
    """Active users who may manage announcements, by name, for the owner picker.

    `search` matches name or email (contains, case-insensitive). Other people are refused as
    owner on create and edit (`owner_not_allowed`). `include` (e.g. the current owner) is listed
    first by name even when outside this page.
    """
    found = await service.owner_candidates(
        session,
        subject,
        policy,
        search=(search or "").strip() or None,
        limit=limit,
        include=include or [],
    )
    return [OwnerCandidateOut(id=user_id, display_name=name) for user_id, name in found]


@router.get("/settings", summary="Announcement settings")
async def get_settings(session: TenantSession, subject: View) -> SettingsOut:
    """The module's tenant settings (staff may read them: they explain disabled actions)."""
    del subject
    current = await service.get_settings(session)
    return SettingsOut(
        require_second_publisher=current.require_second_publisher, version=current.version
    )


@router.put("/settings", summary="Change announcement settings", responses=CONFLICT)
async def put_settings(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    body: SettingsIn,
    session: TenantSession,
    subject: SettingsAdmin,
    version: ExpectedVersion,
    response: Response,
    request: Request,
) -> SettingsOut:
    """Turn the four-eyes rule on or off. If-Match: the version you read ("0" if never set)."""
    changed = await service.update_settings(
        session,
        subject,
        expected_version=version,
        require_second_publisher=body.require_second_publisher,
        source=source_of(request),
    )
    set_etag(response, changed.version)
    return SettingsOut(
        require_second_publisher=changed.require_second_publisher, version=changed.version
    )


@router.post(
    "",
    summary="Create an announcement",
    status_code=status.HTTP_201_CREATED,
    response_model=AnnouncementOut,
)
async def create(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    body: AnnouncementIn,
    session: TenantSession,
    subject: Manage,
    idempotency: Idempotency,
    request: Request,
    policy: Policy,
) -> Response:
    """A new draft. Send an Idempotency-Key: a retried request returns the same 201."""

    async def run() -> Created:
        view = await service.create(
            session, subject, body.model_dump(exclude_unset=True), source_of(request), policy
        )
        out = AnnouncementOut.of(view)
        return Created(
            body=out, headers={"Location": _location(out.id), "ETag": f'"{out.version}"'}
        )

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


# --- routes: one announcement ---------------------------------------------------------------------


@router.get(
    "/{announcement_id}",
    summary="Get an announcement",
    responses={
        404: {"description": "Does not exist, or not visible to you (announcement_not_found)."}
    },
)
async def get_announcement(
    announcement_id: uuid.UUID, session: TenantSession, subject: SignedIn, response: Response
) -> AnnouncementOut | AnnouncementPublicOut:
    """One announcement, as much of it as you may see.

    Staff in scope: everything (`kind` = staff). Its audience while it is live: the public view
    (`kind` = public). Anyone else: 404 `announcement_not_found`, even for drafts that exist.
    """
    found = await service.get_announcement(session, subject, announcement_id)
    if isinstance(found, service.AnnouncementView):
        set_etag(response, found.record.version)
        return AnnouncementOut.of(found)
    return AnnouncementPublicOut.of(found.record, found.visibility, found.next_change_in_seconds)


@router.patch("/{announcement_id}", summary="Edit an announcement", responses=CONFLICT)
async def edit(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    announcement_id: uuid.UUID,
    body: AnnouncementPatch,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Manage,
    response: Response,
    request: Request,
    policy: Policy,
) -> AnnouncementOut:
    """Change the fields you send. Needs If-Match; the status changes through actions."""
    view = await service.update(
        session,
        subject,
        announcement_id,
        expected_version=version,
        values=body.model_dump(include=body.model_fields_set),
        source=source_of(request),
        holders=policy,
    )
    set_etag(response, view.record.version)
    return AnnouncementOut.of(view)


async def _transition(  # noqa: PLR0913, PLR0917 - shared by the four action routes
    action: AnnouncementAction,
    announcement_id: uuid.UUID,
    body: TransitionIn | None,
    version: int,
    session: Any,  # noqa: ANN401 - TenantSession, typed by the route
    subject: Subject,
    response: Response,
    request: Request,
) -> AnnouncementOut:
    view = await service.transition(
        session,
        subject,
        announcement_id,
        action,
        expected_version=version,
        reason=body.reason if body else None,
        source=source_of(request),
    )
    set_etag(response, view.record.version)
    return AnnouncementOut.of(view)


@router.post("/{announcement_id}/publish", summary="Publish", responses=TRANSITION_DOC)
async def publish(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    announcement_id: uuid.UUID,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Publish,
    response: Response,
    request: Request,
) -> AnnouncementOut:
    """Draft → published. Needs announcements.publish (and, with four-eyes on, not your own)."""
    return await _transition(
        AnnouncementAction.PUBLISH,
        announcement_id,
        None,
        version,
        session,
        subject,
        response,
        request,
    )


@router.post("/{announcement_id}/unpublish", summary="Unpublish", responses=TRANSITION_DOC)
async def unpublish(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    announcement_id: uuid.UUID,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Manage,
    response: Response,
    request: Request,
    body: TransitionIn | None = None,
) -> AnnouncementOut:
    """Published → draft, with an optional reason."""
    return await _transition(
        AnnouncementAction.UNPUBLISH,
        announcement_id,
        body,
        version,
        session,
        subject,
        response,
        request,
    )


@router.post("/{announcement_id}/archive", summary="Archive", responses=TRANSITION_DOC)
async def archive(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    announcement_id: uuid.UUID,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Manage,
    response: Response,
    request: Request,
    body: TransitionIn | None = None,
) -> AnnouncementOut:
    """Draft or published → archived, with an optional reason."""
    return await _transition(
        AnnouncementAction.ARCHIVE,
        announcement_id,
        body,
        version,
        session,
        subject,
        response,
        request,
    )


@router.post("/{announcement_id}/reopen", summary="Reopen", responses=TRANSITION_DOC)
async def reopen(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    announcement_id: uuid.UUID,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Manage,
    response: Response,
    request: Request,
) -> AnnouncementOut:
    """Archived → draft."""
    return await _transition(
        AnnouncementAction.REOPEN,
        announcement_id,
        None,
        version,
        session,
        subject,
        response,
        request,
    )


@router.delete(
    "/{announcement_id}",
    summary="Move an announcement to the trash",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=CONFLICT,
)
async def delete(
    announcement_id: uuid.UUID,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Manage,
    request: Request,
) -> Response:
    """Soft delete: recoverable from the trash with POST …/restore."""
    await service.remove(
        session, subject, announcement_id, expected_version=version, source=source_of(request)
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{announcement_id}/restore", summary="Restore from the trash", responses=CONFLICT)
async def restore(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    announcement_id: uuid.UUID,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Manage,
    response: Response,
    request: Request,
) -> AnnouncementOut:
    """Take it out of the trash, as it was."""
    view = await service.restore(
        session, subject, announcement_id, expected_version=version, source=source_of(request)
    )
    set_etag(response, view.record.version)
    return AnnouncementOut.of(view)


@router.get("/{announcement_id}/history", summary="History of an announcement")
async def history(
    announcement_id: uuid.UUID,
    session: TenantSession,
    subject: View,
    cursor: Annotated[str | None, Query(description="next_cursor of the previous page.")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> HistoryOut:
    """Every save, newest first: who, when, from where, what changed from what to what, why."""
    before = int(cursor) if cursor and cursor.isdigit() else None
    entries, next_version, names = await service.history(
        session, subject, announcement_id, before_version=before, limit=limit
    )
    return HistoryOut(
        items=[HistoryEntryOut.of(entry, names) for entry in entries],
        next_cursor=None if next_version is None else str(next_version),
    )
