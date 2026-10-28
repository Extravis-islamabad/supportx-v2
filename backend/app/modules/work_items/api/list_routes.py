"""Saved views, list settings and bulk jobs over HTTP (WP-020d; REQ-INC-104, 106, 110, 119, 120).

Mounted before `/{record_id}`, like the other collection routes.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request, Response, status
from pydantic import BaseModel, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.modules import metadata
from app.modules.audit import audited
from app.modules.identity_access import Subject
from app.modules.work_items.domain.lists import (
    MAX_BULK,
    MAX_COLUMNS,
    BulkAction,
    BulkOutcome,
    BulkStatus,
    ViewVisibility,
)
from app.modules.work_items.domain.types import WorkItemType
from app.modules.work_items.infra.models import (
    WorkItemBulkJob,
    WorkItemListSetting,
    WorkItemView,
)
from app.modules.work_items.service import bulk as bulk_service
from app.modules.work_items.service import lists as service
from app.modules.work_items.service import work_items as items
from app.modules.work_items.service.access import FIELDS
from app.shared.api.concurrency import ExpectedVersion, etag_for, parse_etag, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.listing import ListQuery, list_query, request_zone
from app.shared.history import source_of

CONFLICT_409: dict[int | str, dict[str, object]] = {
    409: {"description": "The version is stale; the problem names what changed."}
}


class ListFieldNamingOut(BaseModel):
    """How the field's values are named (as in reports): a code prefix or a kind of record."""

    field: str
    kind: str
    label_prefix: str | None
    reference: str | None
    bucket: str | None = None


class ListFieldOut(BaseModel):
    """A field the list filters by, sorts by (`sortable`) or shows as a column."""

    name: str
    type: str
    values: list[str]
    multiple: bool
    sortable: bool
    dimension: ListFieldNamingOut | None


class ViewFilterOut(BaseModel):
    """A built-in view as a filter, for what takes a filter and not a view (the export)."""

    view: str
    expressible: bool = Field(description="False: the view needs more than the filter DSL.")
    filter: dict[str, Any] | None = Field(description="None with `expressible`: no condition.")


class ListColumn(BaseModel):
    """One column of the list: a field key (`custom.<key>` for custom fields) and its width."""

    key: str = Field(max_length=80)
    width: int | None = Field(default=None, description="Pixels; none for the default width.")


class SavedViewIn(BaseModel):
    """A view to save. `filter` and `sort` are the list API's own parameters, as sent."""

    name: str = Field(max_length=200)
    visibility: ViewVisibility = ViewVisibility.PRIVATE
    group_ids: list[uuid.UUID] = Field(
        default_factory=list, max_length=100, description="For visibility `groups`."
    )
    filter: dict[str, Any] | None = Field(
        default=None, description="FilterExpression (the list's `filter`), or none for all."
    )
    columns: list[ListColumn] = Field(default_factory=list, max_length=MAX_COLUMNS)
    sort: str | None = Field(default=None, max_length=200, description="e.g. -created_at")


class SavedViewPatch(BaseModel):
    """Fields to change; the ones left out keep their value."""

    name: str | None = Field(default=None, max_length=200)
    visibility: ViewVisibility | None = None
    group_ids: list[uuid.UUID] | None = Field(default=None, max_length=100)
    filter: dict[str, Any] | None = None
    columns: list[ListColumn] | None = Field(default=None, max_length=MAX_COLUMNS)
    sort: str | None = Field(default=None, max_length=200)


class SavedViewOut(BaseModel):
    """A saved view; `mine` says whether you may change it."""

    id: uuid.UUID
    name: str
    visibility: ViewVisibility
    group_ids: list[uuid.UUID]
    owner_id: uuid.UUID
    mine: bool
    filter: dict[str, Any] | None
    columns: list[ListColumn]
    sort: str | None
    version: int
    updated_at: datetime

    @classmethod
    def of(cls, row: WorkItemView, subject: Subject) -> "SavedViewOut":
        """From a row, for the subject."""
        return cls(
            id=row.id,
            name=row.name,
            visibility=ViewVisibility(row.visibility),
            group_ids=list(row.group_ids),
            owner_id=row.owner_id,
            mine=row.owner_id == subject.user_id,
            filter=row.filter,
            columns=[ListColumn(**c) for c in row.columns],
            sort=row.sort,
            version=row.version,
            updated_at=row.updated_at,
        )


class ListSettingIn(BaseModel):
    """Your columns, sort and page size for one view."""

    columns: list[ListColumn] = Field(default_factory=list, max_length=MAX_COLUMNS)
    sort: str | None = Field(default=None, max_length=200)
    page_size: int = Field(default=50, description="25, 50 or 100.")


class ListSettingOut(BaseModel):
    """Saved settings, or the defaults (`version` null) when none were saved."""

    view_key: str
    columns: list[ListColumn]
    sort: str | None
    page_size: int
    version: int | None

    @classmethod
    def of(cls, view_key: str, row: WorkItemListSetting | None) -> "ListSettingOut":
        """From a row, or the defaults."""
        if row is None:
            return cls(view_key=view_key, columns=[], sort=None, page_size=50, version=None)
        return cls(
            view_key=view_key,
            columns=[ListColumn(**c) for c in row.columns],
            sort=row.sort,
            page_size=row.page_size,
            version=row.version,
        )


class BulkJobIn(BaseModel):
    """A bulk change: the picked rows, or every record of the list (`all_matching`).

    With `all_matching`, send the list's own query parameters (view, filter, tag, simple
    filters) with this request: the records are fixed now, at most 1,000.
    """

    action: BulkAction
    changes: dict[str, Any] = Field(
        default_factory=dict,
        description="Edit: only the changed fields. Assign: group_id, technician_id, "
        "confirm_lose_access. Resolve: resolution. Close: closure_code. Both: confirm_open_work.",
    )
    record_ids: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_BULK)
    all_matching: bool = False


class BulkResultOut(BaseModel):
    """What happened to one record; a skip carries the reason as a code (and field)."""

    id: uuid.UUID
    display_id: str | None
    outcome: BulkOutcome
    code: str | None = None
    field: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class BulkJobOut(BaseModel):
    """A bulk job with its progress and results."""

    id: uuid.UUID
    action: BulkAction
    status: BulkStatus
    total: int
    processed: int
    done_count: int
    skipped_count: int
    results: list[BulkResultOut]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    @classmethod
    def of(cls, row: WorkItemBulkJob, *, results: bool = True) -> "BulkJobOut":
        """From a row (the results only when asked for: up to 1,000 entries)."""
        return cls(
            id=row.id,
            action=BulkAction(row.action),
            status=BulkStatus(row.status),
            total=row.total,
            processed=row.processed,
            done_count=row.done_count,
            skipped_count=row.skipped_count,
            results=[BulkResultOut(**r) for r in row.results] if results else [],
            created_at=row.created_at,
            started_at=row.started_at,
            finished_at=row.finished_at,
        )


def list_dependency(wtype: WorkItemType) -> Any:  # noqa: ANN401 - a FastAPI dependency
    """The list's ListQuery dependency: built-in fields plus custom fields (WP-026)."""
    return list_query(
        FIELDS,
        extra_parameters=frozenset({"view", "tag"}),
        # Custom fields filter as `custom.<key>` (WP-026), typed per tenant.
        fields_for=lambda session: metadata.filter_fields(session, wtype.code.value, "work_items"),
    )


def add_list_routes(router: APIRouter, wtype: WorkItemType) -> None:  # noqa: C901 - one route per operation
    """`/saved-views`, `/list-settings/{view_key}`, `/bulk` and `/bulk-jobs`."""
    perm = wtype.permission
    View = Annotated[Subject, Depends(require_permission(perm("view")))]  # noqa: N806 - type alias
    Query_ = Annotated[ListQuery, Depends(list_dependency(wtype))]  # noqa: N806 - type alias
    name = wtype.code.replace("_", " ")

    @router.get("/list-fields", summary="Fields of the list (filter, sort, columns)")
    async def list_fields(session: TenantSession, subject: View) -> list[ListFieldOut]:
        """Built-in and custom fields (`custom.<key>`), as the list's filter and sort take them."""
        return [
            ListFieldOut(
                name=f.name,
                type=f.type,
                values=f.values,
                multiple=f.multiple,
                sortable=f.sortable,
                dimension=None
                if f.dimension is None
                else ListFieldNamingOut(
                    field=f.name,
                    kind=f.dimension.kind.value,
                    label_prefix=f.dimension.label_prefix,
                    reference=f.dimension.reference,
                ),
            )
            for f in await service.list_fields(session, subject, wtype)
        ]

    @router.get("/view-filters", summary="Built-in views as filters")
    async def view_filters(session: TenantSession, subject: View) -> list[ViewFilterOut]:
        """Each built-in view and personal counter as the filter DSL, where the DSL can say it."""
        found = await items.view_filters(session, subject)
        return [
            ViewFilterOut(
                view=code,
                expressible=tree != items.NOT_EXPRESSIBLE,
                filter=tree if isinstance(tree, dict) else None,
            )
            for code, tree in found.items()
        ]

    # --- saved views ------------------------------------------------------------------------------

    @router.get("/saved-views", summary="Your saved views and the shared ones")
    async def saved_views(session: TenantSession, subject: View) -> list[SavedViewOut]:
        """By name. Shared views are listed for everyone; only their owner changes them."""
        return [SavedViewOut.of(r, subject) for r in await service.views(session, subject, wtype)]

    @router.post(
        "/saved-views",
        summary="Save a view",
        status_code=status.HTTP_201_CREATED,
        response_model=SavedViewOut,
    )
    async def create_saved_view(
        body: SavedViewIn,
        session: TenantSession,
        subject: View,
        idempotency: Idempotency,
        request: Request,
    ) -> Response:
        """The filter is checked like the list's; names are unique per owner (ignoring case)."""

        async def run() -> Created:
            row = await service.create_view(
                session, subject, wtype, body.model_dump(mode="json"), source=source_of(request)
            )
            return Created(
                body=SavedViewOut.of(row, subject), headers={"ETag": etag_for(row.version)}
            )

        return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)

    @router.patch("/saved-views/{view_id}", summary="Change your view", responses=CONFLICT_409)
    async def update_saved_view(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        view_id: uuid.UUID,
        body: SavedViewPatch,
        version: ExpectedVersion,
        session: TenantSession,
        subject: View,
        request: Request,
        response: Response,
    ) -> SavedViewOut:
        """Needs If-Match. Only the fields sent change."""
        row = await service.update_view(
            session,
            subject,
            wtype,
            view_id,
            body.model_dump(mode="json", exclude_unset=True),
            expected_version=version,
            source=source_of(request),
        )
        set_etag(response, row.version)
        return SavedViewOut.of(row, subject)

    @router.delete(
        "/saved-views/{view_id}",
        summary="Remove your view",
        status_code=status.HTTP_204_NO_CONTENT,
        responses=CONFLICT_409,
    )
    async def delete_saved_view(
        view_id: uuid.UUID,
        version: ExpectedVersion,
        session: TenantSession,
        subject: View,
        request: Request,
    ) -> Response:
        """Needs If-Match."""
        await service.delete_view(
            session, subject, wtype, view_id, expected_version=version, source=source_of(request)
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # --- list settings ----------------------------------------------------------------------------

    @router.get("/list-settings/{view_key}", summary="Your columns, sort and page size")
    async def list_setting(
        view_key: str, session: TenantSession, subject: View, response: Response
    ) -> ListSettingOut:
        """For one view: a built-in view code, `all`, or `custom:<saved view id>`."""
        row = await service.list_setting(session, subject, wtype, view_key)
        if row is not None:
            set_etag(response, row.version)
        return ListSettingOut.of(view_key, row)

    @router.put(
        "/list-settings/{view_key}", summary="Save your list settings", responses=CONFLICT_409
    )
    async def save_list_setting(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        view_key: str,
        body: ListSettingIn,
        session: TenantSession,
        subject: View,
        response: Response,
        if_match: Annotated[
            str | None,
            Header(
                alias="If-Match",
                description="The version read; leave out only for the first save.",
            ),
        ] = None,
    ) -> ListSettingOut:
        """Columns and sort of this view only, for you only (REQ-INC-104 AC1, AC3)."""
        row = await service.save_list_setting(
            session,
            subject,
            wtype,
            view_key,
            body.model_dump(mode="json"),
            expected_version=parse_etag(if_match) if if_match else None,
        )
        set_etag(response, row.version)
        return ListSettingOut.of(view_key, row)

    # --- bulk jobs --------------------------------------------------------------------------------

    @router.post(
        "/bulk",
        summary=f"Change many {wtype.path} at once",
        status_code=status.HTTP_202_ACCEPTED,
        response_model=BulkJobOut,
        dependencies=[audited(f"{name}.bulk_started", object_type=f"{name}_bulk_job")],
    )
    async def start_bulk(  # noqa: PLR0913, PLR0917 - FastAPI dependencies and query options
        body: BulkJobIn,
        session: TenantSession,
        subject: View,
        idempotency: Idempotency,
        request: Request,
        list_query: Query_,
        view: str | None = None,
        tag: str | None = None,
    ) -> Response:
        """Queue a background job (up to 1,000 records); progress arrives on your channel.

        Each record is changed as you, with its own permissions, transitions and closure rules;
        a record that refuses is skipped with the reason. Send an Idempotency-Key.
        """
        selected: ListQuery = list_query

        async def run() -> Created:
            ids = body.record_ids
            if body.all_matching:
                ids = await bulk_service.matching_ids(
                    session,
                    subject,
                    wtype,
                    selected,
                    view=view,
                    tag=tag,
                    zone=request_zone(request),
                )
            row = await bulk_service.start(
                session,
                subject,
                wtype,
                action=body.action,
                changes=body.changes,
                record_ids=ids,
                source=source_of(request),
            )
            return Created(body=BulkJobOut.of(row))

        return await idempotency.run(body, run, status_code=status.HTTP_202_ACCEPTED)

    @router.get("/bulk-jobs", summary="Your latest bulk jobs")
    async def bulk_jobs(session: TenantSession, subject: View) -> list[BulkJobOut]:
        """Newest first, without the per-record results."""
        rows = await bulk_service.jobs(session, subject, wtype)
        return [BulkJobOut.of(r, results=False) for r in rows]

    @router.get("/bulk-jobs/{job_id}", summary="One of your bulk jobs")
    async def bulk_job(job_id: uuid.UUID, session: TenantSession, subject: View) -> BulkJobOut:
        """Progress and a result per finished record."""
        return BulkJobOut.of(await bulk_service.job(session, subject, wtype, job_id))
