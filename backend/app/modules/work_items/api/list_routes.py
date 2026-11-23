"""Saved views, list settings and bulk jobs over HTTP (WP-020d; REQ-INC-104, 106, 110, 119, 120).

Mounted before `/{record_id}`, like the other collection routes.
"""

import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.core.errors import FieldError, ValidationFailed
from app.core.tenancy import TenantContext
from app.modules import metadata
from app.modules.audit import AuditNote, audited
from app.modules.identity_access import Subject, get_policy
from app.modules.work_items.domain import field_access as field_rules
from app.modules.work_items.domain.lists import (
    MAX_BULK,
    MAX_COLUMNS,
    BoardGroupBy,
    BulkAction,
    BulkOutcome,
    BulkStatus,
    ListLayout,
    RowColourBy,
    ViewVisibility,
)
from app.modules.work_items.domain.types import WorkItemType
from app.modules.work_items.infra.models import (
    WorkItemBulkJob,
    WorkItemListSetting,
    WorkItemView,
)
from app.modules.work_items.service import bulk as bulk_service
from app.modules.work_items.service import catalogue, custom_values, view_audit, view_filters
from app.modules.work_items.service import lists as service
from app.modules.work_items.service import work_items as items
from app.modules.work_items.service.access import FIELDS, type_fields
from app.shared.api.concurrency import ExpectedVersion, etag_for, parse_etag, set_etag
from app.shared.api.filters import FilterField
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.listing import ListQuery, list_query, list_query_body, request_zone
from app.shared.api.ratelimit import rate_limit
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


class UnsharedViewOut(BaseModel):
    """A view the audit made private (D-176): whose, when, and the filter field that caused it."""

    id: uuid.UUID
    name: str
    owner_id: uuid.UUID
    unshared_at: datetime
    field: str = Field(description="The filter field's key; the console names it by its label.")


class ViewAuditOut(BaseModel):
    """The report: the views made private, newest first (at most 200)."""

    items: list[UnsharedViewOut]
    seal_pending: int = Field(
        default=0,
        description="Views still holding a sealed field's value in plain text; sealed on the "
        "next run once the tenant's keys are available.",
    )


class SavedViewOut(BaseModel):
    """A saved view; `mine` says whether you may change it."""

    id: uuid.UUID
    name: str
    visibility: ViewVisibility
    group_ids: list[uuid.UUID]
    owner_id: uuid.UUID
    mine: bool
    # Starred by you (REQ-INC-107 AC1); favourites come first in the list.
    favourite: bool = False
    filter: dict[str, Any] | None
    columns: list[ListColumn]
    sort: str | None
    version: int
    updated_at: datetime

    @classmethod
    def of(
        cls,
        row: WorkItemView,
        subject: Subject,
        *,
        favourite: bool = False,
        filter_shown: dict[str, Any] | None = None,
    ) -> "SavedViewOut":
        """From a row, for the subject."""
        return cls(
            favourite=favourite,
            id=row.id,
            name=row.name,
            visibility=ViewVisibility(row.visibility),
            group_ids=list(row.group_ids),
            owner_id=row.owner_id,
            mine=row.owner_id == subject.user_id,
            # The reader's form (sealed values opened or withheld); never the stored `sx2:` text.
            filter=filter_shown,
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
    row_colour_by: RowColourBy | None = Field(
        default=None, description="Your own row colouring for this view; null: the default."
    )
    layout: ListLayout | None = Field(
        default=None,
        description="Table, cards, board or calendar for this view (REQ-INC-111/112); null: table.",
    )
    group_by: BoardGroupBy | None = Field(
        default=None, description="The board's columns; null: status."
    )


class ListSettingOut(BaseModel):
    """Saved settings, or the defaults (`version` null) when none were saved."""

    view_key: str
    columns: list[ListColumn]
    sort: str | None
    page_size: int
    row_colour_by: RowColourBy | None = None
    layout: ListLayout | None = None
    group_by: BoardGroupBy | None = None
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
            row_colour_by=RowColourBy(row.row_colour_by) if row.row_colour_by else None,
            layout=ListLayout(row.layout) if row.layout else None,
            group_by=BoardGroupBy(row.group_by) if row.group_by else None,
            version=row.version,
        )


class ListDisplayIn(BaseModel):
    """The tenant's default row colouring (REQ-INC-115 AC1)."""

    model_config = ConfigDict(extra="forbid")

    row_colour_by: RowColourBy


class ListDisplayOut(BaseModel):
    """The default row colouring, with the type settings' version (the ETag)."""

    row_colour_by: RowColourBy
    settings_version: int


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


async def _own_and_custom(session: AsyncSession, wtype: WorkItemType) -> Mapping[str, FilterField]:
    custom = await metadata.filter_fields(session, wtype.code.value, "work_items")
    # A sealed field never sorts and never compares as stored text: its `eq` / `in` filters are
    # rewritten to its blind index before this allowlist is used (WP-057 S3b-2).
    sealed = await custom_values.not_plain_keys(session, wtype.code.value)
    custom = {n: f for n, f in custom.items() if n.removeprefix("custom.") not in sealed}
    return {**type_fields(wtype), **custom}


def _names(tree: Any, simple: Mapping[str, Sequence[str]]) -> list[str]:  # noqa: ANN401 - the DSL tree
    return [str(c["field"]) for c in view_filters.conditions(tree)] + list(simple)


def _hooks(wtype: WorkItemType) -> dict[str, Any]:
    """The list's hooks, the same for its GET and its POST form."""

    async def withheld(request: Request, tenant: TenantContext) -> frozenset[str]:
        subject = await get_policy(request).subject_for(request, tenant)
        return field_rules.unseen(subject.field_access, wtype.code.value).all

    async def sealed(
        session: AsyncSession,
        tree: Any,  # noqa: ANN401 - the filter DSL's parsed JSON tree
        simple: dict[str, list[str]],
        withheld: frozenset[str],
    ) -> tuple[Any, dict[str, list[str]], Mapping[str, FilterField]]:
        return await custom_values.rewrite_sealed_filters(
            session, wtype.code.value, tree, simple, withheld
        )

    return {
        # Custom fields filter as `custom.<key>` (WP-026), typed per tenant.
        # A type's own fields too (a change's risk, a problem's type): drill-down (REQ-CHG-116).
        "fields_for": lambda session: _own_and_custom(session, wtype),
        "exclude_for": withheld,
        "rewrite_for": sealed,
    }


def list_dependency(wtype: WorkItemType) -> Any:  # noqa: ANN401 - a FastAPI dependency
    """The list's ListQuery dependency (GET): built-in fields plus custom fields (WP-026).

    Minus the fields the caller's roles hide or mask (ADR-047 AC2): filtering or sorting on one
    is refused like any unknown field, so a filter never probes a value the list leaves out.
    A filter naming a sealed field is refused here (`sealed_filter_needs_post`): its value
    would travel in the URL, so it goes in `POST .../list`'s body (lane C).
    """

    async def refuse(
        session: AsyncSession,
        tree: Any,  # noqa: ANN401 - the filter DSL's parsed JSON tree
        simple: Mapping[str, Sequence[str]],
    ) -> None:
        found = await service.sealed_fields(session, wtype)
        named = next((n for n in _names(tree, simple) if n in found), None)
        if named is not None:
            # The field, never the value (lane C): the value is what must not travel.
            raise ValidationFailed(
                errors=[
                    FieldError(
                        field="query.filter",
                        code="sealed_filter_needs_post",
                        message_key="errors.field.sealed_filter_needs_post",
                        params={"field": named},
                    )
                ]
            )

    return list_query(
        FIELDS, extra_parameters=frozenset({"view", "tag"}), refuse_for=refuse, **_hooks(wtype)
    )


def list_body_dependency(wtype: WorkItemType) -> Any:  # noqa: ANN401 - a FastAPI dependency
    """The same list query from `POST .../list`'s body: a sealed filter may come this way."""
    return list_query_body(FIELDS, extra_parameters=frozenset({"view", "tag"}), **_hooks(wtype))


def add_list_routes(router: APIRouter, wtype: WorkItemType) -> None:  # noqa: C901, PLR0915 - one route per op
    """`/saved-views`, `/list-settings/{view_key}`, `/bulk` and `/bulk-jobs`."""
    perm = wtype.permission
    View = Annotated[Subject, Depends(require_permission(perm("view")))]  # noqa: N806 - type alias
    Query_ = Annotated[ListQuery, Depends(list_dependency(wtype))]  # noqa: N806 - type alias
    audit = wtype.code.value  # audit codes: "incident.deleted", "service_request.deleted"

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
        """Your starred views first, then by name. Only their owner changes shared views."""
        rows = await service.views(session, subject, wtype)
        starred = await service.favourite_ids(session, subject, wtype)
        shown = [
            SavedViewOut.of(
                r,
                subject,
                favourite=r.id in starred,
                filter_shown=await service.shown_filter(session, subject, wtype, r),
            )
            for r in rows
        ]
        return sorted(shown, key=lambda v: not v.favourite)  # stable: names stay in order

    @router.put(
        "/saved-views/{view_id}/favourite",
        summary="Star a view",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def star_saved_view(
        view_id: uuid.UUID, session: TenantSession, subject: View
    ) -> Response:
        """Yours only; nobody else sees it. Starring twice is the same as once."""
        await service.star_view(session, subject, wtype, view_id, starred=True)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.delete(
        "/saved-views/{view_id}/favourite",
        summary="Un-star a view",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def unstar_saved_view(
        view_id: uuid.UUID, session: TenantSession, subject: View
    ) -> Response:
        """Removing a star that is not there is fine."""
        await service.star_view(session, subject, wtype, view_id, starred=False)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

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
                body=SavedViewOut.of(
                    row,
                    subject,
                    filter_shown=await service.shown_filter(session, subject, wtype, row),
                ),
                headers={"ETag": etag_for(row.version)},
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
        return SavedViewOut.of(
            row, subject, filter_shown=await service.shown_filter(session, subject, wtype, row)
        )

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

    # --- row colours (REQ-INC-115 AC1) ------------------------------------------------------------

    SettingsAdmin = Annotated[  # noqa: N806 - type alias
        Subject, Depends(require_permission("config.service_desk", "settings.manage"))
    ]

    @router.get("/settings/list-display", summary="How list rows are coloured by default")
    async def list_display(
        session: TenantSession, subject: View, response: Response
    ) -> ListDisplayOut:
        """Everyone who sees the list reads it (their own choice per view overrides it)."""
        del subject
        cat = await catalogue.load(session, wtype)
        set_etag(response, cat.settings_version)
        return ListDisplayOut(
            row_colour_by=RowColourBy(cat.row_colour_by), settings_version=cat.settings_version
        )

    @router.put("/settings/list-display", summary="Set how list rows are coloured by default")
    async def put_list_display(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        body: ListDisplayIn,
        session: TenantSession,
        subject: SettingsAdmin,
        version: ExpectedVersion,
        response: Response,
        request: Request,
        note: Annotated[
            AuditNote,
            audited(f"{audit}.list_display_changed", object_type=f"{audit}_settings"),
        ],
    ) -> ListDisplayOut:
        """Needs If-Match on the type's settings; the change is audited."""
        cat, before, after = await service.set_row_colour_default(
            session,
            wtype,
            body.row_colour_by.value,
            expected_version=version,
            source=source_of(request),
            user_id=subject.user_id,
        )
        note.details = {"before": before, "after": after}
        set_etag(response, cat.settings_version)
        return ListDisplayOut(
            row_colour_by=RowColourBy(cat.row_colour_by), settings_version=cat.settings_version
        )

    # --- the shared-view audit (D-176) ------------------------------------------------------------

    Admin = Annotated[Subject, Depends(require_permission("roles.manage"))]  # noqa: N806 - alias

    def _report(rows: list[WorkItemView], pending: int = 0) -> ViewAuditOut:
        return ViewAuditOut(
            seal_pending=pending,
            items=[
                UnsharedViewOut(
                    id=r.id,
                    name=r.name,
                    owner_id=r.owner_id,
                    unshared_at=r.unshared_at,
                    field=r.unshared_field or "",
                )
                for r in rows
                if r.unshared_at is not None
            ],
        )

    @router.get(
        "/saved-views/audit",
        summary="Views made private because of their filter",
        dependencies=[Depends(rate_limit("identity"))],
    )
    async def view_audit_report(session: TenantSession, subject: Admin) -> ViewAuditOut:
        """Administrators: shared views the audit made private, with the field that caused it."""
        del subject
        return _report(
            await view_audit.unshared_views(session, wtype),
            len(await view_audit.seal_pending(session, wtype)),
        )

    @router.post(
        "/saved-views/audit",
        summary="Check the shared views again",
        response_model=ViewAuditOut,
        dependencies=[Depends(rate_limit("identity"))],
    )
    async def rerun_view_audit(
        session: TenantSession,
        subject: Admin,
        idempotency: Idempotency,
        note: Annotated[
            AuditNote,
            audited(f"{audit}.view_audit_run", object_type=f"{audit}_settings"),
        ],
    ) -> Response:
        """Runs the audit now (idempotent: views already private stay as they are); audited."""
        del subject, note  # the entry names who ran it; the views it changed carry their own

        async def run() -> ViewAuditOut:
            await view_audit.audit_type(session, wtype, datetime.now(UTC))
            return _report(
                await view_audit.unshared_views(session, wtype),
                len(await view_audit.seal_pending(session, wtype)),
            )

        return await idempotency.run(None, run, status_code=status.HTTP_200_OK)

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
        dependencies=[audited(f"{audit}.bulk_started", object_type=f"{audit}_bulk_job")],
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
