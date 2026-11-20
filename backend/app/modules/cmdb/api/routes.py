"""CMDB HTTP API under /api/v1/cmdb (WP-053 S1). No business logic here.

Reads need `cmdb.view` (scope-filtered in the service). CI writes need `cmdb.add`, `cmdb.edit` or
`cmdb.delete` (or `cmdb.manage`, which covers all three); the type tree, the states and the
settings need `cmdb.configure` (audited). Writes use If-Match (409 explains who changed what);
creates take an Idempotency-Key.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.core.errors import ProblemDetail
from app.modules.audit import audited
from app.modules.cmdb.domain import types as domain
from app.modules.cmdb.infra.models import Ci, CiState
from app.modules.cmdb.service import catalogue, cis, ref_names
from app.modules.identity_access import Subject, scope_filter
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.listing import ListQuery, Page, PageResult, list_query
from app.shared.api.ratelimit import rate_limit
from app.shared.history import HistoryEntry, source_of

Responses = dict[int | str, dict[str, object]]
RESPONSES: Responses = {
    401: {"model": ProblemDetail, "description": "Not signed in."},
    403: {"model": ProblemDetail, "description": "Missing permission or licence feature."},
    404: {"model": ProblemDetail, "description": "No such record visible to you."},
}
CONFLICT: Responses = {
    409: {"model": ProblemDetail, "description": "Stale If-Match (version_conflict), or in use."}
}

router = APIRouter(
    prefix="/cmdb",
    tags=["cmdb"],
    dependencies=[Depends(rate_limit("cmdb"))],
    responses=RESPONSES,
)

View = Annotated[Subject, Depends(require_permission(catalogue.VIEW))]
Add = Annotated[Subject, Depends(require_permission(catalogue.ADD, catalogue.MANAGE))]
Edit = Annotated[Subject, Depends(require_permission(catalogue.EDIT, catalogue.MANAGE))]
Delete = Annotated[Subject, Depends(require_permission(catalogue.DELETE, catalogue.MANAGE))]
Configure = Annotated[Subject, Depends(require_permission(catalogue.CONFIGURE))]
CisQuery = Annotated[ListQuery, Depends(list_query(cis.CI_FIELDS))]
# `type_tree` (this type and the types below it) is read by the list route itself.
CisTreeQuery = Annotated[
    ListQuery, Depends(list_query(cis.CI_FIELDS, extra_parameters=frozenset({"type_tree"})))
]

# Codes as named schemas (labelled `cmdb_state_category.<code>` and so on).
StateCategory = domain.CiStateCategory
ImpactCode = domain.CiImpact
SourceCode = domain.CiSource
Names = dict[str, str]


# --- schemas: types, states, settings -------------------------------------------------------------


class CiTypeIn(BaseModel):
    """A tenant's own CI type."""

    api_name: str
    names: Names
    parent_id: uuid.UUID | None = None
    icon: str | None = Field(default=None, max_length=40)


class CiTypePatch(BaseModel):
    """Fields to change (a built-in type keeps its code and its place in the tree)."""

    names: Names | None = None
    parent_id: uuid.UUID | None = None
    icon: str | None = Field(default=None, max_length=40)


class CiTypeOut(BaseModel):
    """One CI type. A built-in type is shown by its label (`cmdb_ci_type.<api_name>`)."""

    id: uuid.UUID
    parent_id: uuid.UUID | None
    api_name: str
    built_in: bool
    names: Names
    icon: str | None
    ci_count: int
    child_count: int
    version: int

    @classmethod
    def of(cls, view: catalogue.TypeView) -> "CiTypeOut":
        """From the service's view."""
        row = view.record
        return cls(
            id=row.id,
            parent_id=row.parent_id,
            api_name=row.api_name,
            built_in=row.built_in,
            names=row.names,
            icon=row.icon,
            ci_count=view.ci_count,
            child_count=view.child_count,
            version=row.version,
        )


class CiTypeList(BaseModel):
    """Every CI type (the tree is built from `parent_id`)."""

    items: list[CiTypeOut]


class CiStateIn(BaseModel):
    """A tenant's own CI state."""

    api_name: str
    names: Names
    category: StateCategory = domain.CiStateCategory.ACTIVE
    position: int = Field(default=100, ge=0, le=10000)


class CiStatePatch(BaseModel):
    """Fields to change (a built-in state's category is fixed)."""

    names: Names | None = None
    category: StateCategory | None = None
    position: int | None = Field(default=None, ge=0, le=10000)


class CiStateOut(BaseModel):
    """One CI state. A built-in state is shown by its label (`cmdb_ci_state.<api_name>`)."""

    id: uuid.UUID
    api_name: str
    built_in: bool
    names: Names
    category: StateCategory
    position: int
    version: int

    @classmethod
    def of(cls, row: CiState) -> "CiStateOut":
        """From the row."""
        return cls(
            id=row.id,
            api_name=row.api_name,
            built_in=row.built_in,
            names=row.names,
            category=domain.CiStateCategory(row.category),
            position=row.position,
            version=row.version,
        )


class CiStateList(BaseModel):
    """Every CI state, in order."""

    items: list[CiStateOut]


class CmdbSettingsIn(BaseModel):
    """The CMDB settings."""

    exclude_eol_from_pickers: bool


class CmdbSettingsOut(CmdbSettingsIn):
    """The CMDB settings, with their version."""

    version: int


# --- schemas: CIs ---------------------------------------------------------------------------------


class CiIn(BaseModel):
    """A new CI."""

    type_id: uuid.UUID
    name: str = Field(min_length=1, max_length=domain.NAME_MAX)
    description: str | None = Field(default=None, max_length=domain.DESCRIPTION_MAX)
    state_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    owner_user_id: uuid.UUID | None = None
    owner_group_id: uuid.UUID | None = None
    managed_by_group_id: uuid.UUID | None = None
    business_impact: ImpactCode | None = None
    criticality: ImpactCode | None = None
    custom: dict[str, Any] | None = Field(
        default=None,
        description="Custom field values by key: the fields of the CI's type and the types above.",
    )


class CiPatch(BaseModel):
    """Fields to change. The type changes through …/change-type."""

    name: str | None = Field(default=None, min_length=1, max_length=domain.NAME_MAX)
    description: str | None = Field(default=None, max_length=domain.DESCRIPTION_MAX)
    state_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    owner_user_id: uuid.UUID | None = None
    owner_group_id: uuid.UUID | None = None
    managed_by_group_id: uuid.UUID | None = None
    business_impact: ImpactCode | None = None
    criticality: ImpactCode | None = None
    custom: dict[str, Any] | None = Field(
        default=None,
        description="Custom values to change by key (null clears one); keys not sent are kept.",
    )


class RefNameOut(BaseModel):
    """How one referenced site, group, person or asset reads for you: its label, or why not."""

    label: str | None = Field(default=None, description="Its name; never an ID.")
    restricted: bool = Field(default=False, description="You may not see it now.")
    gone: bool = Field(default=False, description="It no longer exists.")

    @classmethod
    def of(cls, name: ref_names.RefName) -> "RefNameOut":
        """From the service's name."""
        return cls(label=name.label, restricted=name.restricted, gone=name.gone)


def names_out(names: dict[str, ref_names.RefName]) -> dict[str, RefNameOut]:
    """The service's names map as the API returns it."""
    return {key: RefNameOut.of(name) for key, name in sorted(names.items())}


class CiListItem(BaseModel):
    """One CI in a list."""

    id: uuid.UUID
    display_id: str
    name: str
    type_id: uuid.UUID
    state_id: uuid.UUID
    site_id: uuid.UUID | None
    owner_user_id: uuid.UUID | None
    owner_group_id: uuid.UUID | None
    managed_by_group_id: uuid.UUID | None
    business_impact: ImpactCode | None
    criticality: ImpactCode | None
    asset_id: uuid.UUID | None
    source: SourceCode
    updated_at: datetime
    version: int

    @classmethod
    def of(cls, row: Ci) -> "CiListItem":
        """From the row."""
        return cls.model_validate(row, from_attributes=True)


class CiOut(CiListItem):
    """One CI with everything staff see."""

    description: str | None
    created_at: datetime
    created_by: uuid.UUID | None
    updated_by: uuid.UUID | None
    deleted_at: datetime | None
    history_count: int
    can_edit: bool
    can_delete: bool
    custom: dict[str, Any] = Field(
        description="Custom values you may read, by key (hidden and masked ones are left out)."
    )
    masked_fields: list[str] = Field(description="Fields shown as masked (`custom.<key>`).")
    read_only_fields: list[str] = Field(
        description="Fields your roles may only read (`custom.<key>`); a change is refused."
    )
    names: dict[str, RefNameOut] = Field(
        default_factory=dict,
        description="The site, owner, groups, asset and person custom values named for you, by "
        "the referenced ID.",
    )

    @classmethod
    def of_view(cls, view: cis.CiView) -> "CiOut":
        """From the service's view."""
        row = view.record
        base = CiListItem.of(row).model_dump()
        return cls(
            **base,
            description=row.description,
            created_at=row.created_at,
            created_by=row.created_by,
            updated_by=row.updated_by,
            deleted_at=row.deleted_at,
            history_count=view.history_count,
            can_edit=view.can_edit,
            can_delete=view.can_delete,
            custom=view.custom,
            masked_fields=list(view.masked_fields),
            read_only_fields=list(view.read_only_fields),
            names=names_out(view.names),
        )


class CiPage(Page[CiListItem]):
    """One page of CIs."""


class CiTypeChangeIn(BaseModel):
    """The type to move the CI to."""

    type_id: uuid.UUID
    confirm_dropped_fields: bool = Field(
        default=False,
        description="Drop the custom values the new type's fields do not include (see the "
        "preview); without it such a change is refused (409 cmdb_ci_type_change_drops_fields).",
    )


class CiDroppedFieldOut(BaseModel):
    """A custom field whose value the type change would drop."""

    key: str
    labels: Names


class CiTypeChangePreviewOut(BaseModel):
    """What moving the CI to a type would drop. Nothing is changed."""

    dropped: list[CiDroppedFieldOut]
    blocked: bool = Field(
        description="A dropped field is one your roles may only read: you may not change the type."
    )


class CiFromAssetsIn(BaseModel):
    """Assets to make CIs from (at most 100), all of one type."""

    asset_ids: list[uuid.UUID] = Field(min_length=1, max_length=cis.FROM_ASSETS_MAX)
    type_id: uuid.UUID
    state_id: uuid.UUID | None = None


class CiSkippedAsset(BaseModel):
    """An asset no CI was made for, and why."""

    asset_id: uuid.UUID
    reason: Literal["hidden", "gone", "has_ci"]


class CiFromAssetsOut(BaseModel):
    """The CIs made, and the assets skipped."""

    created: list[CiListItem]
    skipped: list[CiSkippedAsset]


class CiPickerOut(BaseModel):
    """CIs to choose from."""

    items: list[CiListItem]


class CiFieldChangeOut(BaseModel):
    """One field of one save. Values are codes, IDs or text; the UI labels them."""

    field: str
    old: Any = None
    new: Any = None


class CiHistoryEntryOut(BaseModel):
    """One save."""

    version: int
    kind: str
    occurred_at: datetime
    actor_type: Literal["user", "system"]
    actor_id: str | None
    actor_name: str | None
    source: str
    reason: str | None
    changes: list[CiFieldChangeOut]

    @classmethod
    def of(cls, entry: HistoryEntry, names: dict[str, str]) -> "CiHistoryEntryOut":
        """From a history entry plus resolved actor names."""
        return cls(
            version=entry.version,
            kind=entry.kind,
            occurred_at=entry.occurred_at,
            actor_type="user" if entry.actor_type == "user" else "system",
            actor_id=entry.actor_id,
            actor_name=names.get(entry.actor_id or ""),
            source=entry.source,
            reason=entry.reason,
            changes=[CiFieldChangeOut(field=c.field, old=c.old, new=c.new) for c in entry.changes],
        )


class CiHistoryOut(BaseModel):
    """Saves of one CI, newest first."""

    items: list[CiHistoryEntryOut]
    next_cursor: str | None


def _location(path: str) -> str:
    return f"/api/v1/cmdb/{path}"


def _page(page: PageResult[Ci]) -> CiPage:
    return CiPage(
        items=[CiListItem.of(row) for row in page.rows],
        next_cursor=page.next_cursor,
        has_more=page.has_more,
        estimated_total=page.estimated_total,
    )


# --- routes: types --------------------------------------------------------------------------------


@router.get("/ci-types", summary="CI types")
async def list_types(session: TenantSession, subject: View) -> CiTypeList:
    """Every CI type with its counts, counted within what the reader may see."""
    visible = scope_filter(subject, catalogue.VIEW, cis.CIS)
    return CiTypeList(
        items=[CiTypeOut.of(v) for v in await catalogue.list_types(session, visible=visible)]
    )


@router.post(
    "/ci-types",
    summary="Create a CI type",
    status_code=status.HTTP_201_CREATED,
    response_model=CiTypeOut,
    dependencies=[audited("cmdb.ci_type_created", object_type="cmdb_ci_type")],
)
async def create_type(
    body: CiTypeIn, session: TenantSession, subject: Configure, idempotency: Idempotency
) -> Response:
    """A tenant's own type. Send an Idempotency-Key: a retried request returns the same 201."""

    async def run() -> Created:
        view = await catalogue.create_type(session, subject, body.model_dump(mode="python"))
        out = CiTypeOut.of(view)
        return Created(
            body=out,
            headers={"Location": _location(f"ci-types/{out.id}"), "ETag": f'"{out.version}"'},
        )

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.patch(
    "/ci-types/{type_id}",
    summary="Change a CI type",
    responses=CONFLICT,
    dependencies=[audited("cmdb.ci_type_changed", object_type="cmdb_ci_type")],
)
async def update_type(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    type_id: uuid.UUID,
    body: CiTypePatch,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Configure,
    response: Response,
) -> CiTypeOut:
    """Change the fields you send. Needs If-Match."""
    view = await catalogue.update_type(
        session,
        subject,
        type_id,
        expected_version=version,
        values=body.model_dump(include=body.model_fields_set, mode="python"),
    )
    set_etag(response, view.record.version)
    return CiTypeOut.of(view)


@router.delete(
    "/ci-types/{type_id}",
    summary="Remove a CI type",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=CONFLICT,
    dependencies=[audited("cmdb.ci_type_deleted", object_type="cmdb_ci_type")],
)
async def delete_type(
    type_id: uuid.UUID, version: ExpectedVersion, session: TenantSession, subject: Configure
) -> Response:
    """Refused (409 `cmdb_ci_type_in_use`, with counts) while CIs or types below use it."""
    await catalogue.delete_type(session, subject, type_id, expected_version=version)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- routes: states -------------------------------------------------------------------------------


@router.get("/ci-states", summary="CI states")
async def list_states(session: TenantSession, subject: View) -> CiStateList:
    """Every CI state, in order."""
    del subject
    return CiStateList(items=[CiStateOut.of(s) for s in await catalogue.list_states(session)])


@router.post(
    "/ci-states",
    summary="Create a CI state",
    status_code=status.HTTP_201_CREATED,
    response_model=CiStateOut,
    dependencies=[audited("cmdb.ci_state_created", object_type="cmdb_ci_state")],
)
async def create_state(
    body: CiStateIn, session: TenantSession, subject: Configure, idempotency: Idempotency
) -> Response:
    """A tenant's own state. Send an Idempotency-Key."""

    async def run() -> Created:
        out = CiStateOut.of(await catalogue.create_state(session, subject, body.model_dump()))
        return Created(
            body=out,
            headers={"Location": _location(f"ci-states/{out.id}"), "ETag": f'"{out.version}"'},
        )

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.patch(
    "/ci-states/{state_id}",
    summary="Change a CI state",
    responses=CONFLICT,
    dependencies=[audited("cmdb.ci_state_changed", object_type="cmdb_ci_state")],
)
async def update_state(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    state_id: uuid.UUID,
    body: CiStatePatch,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Configure,
    response: Response,
) -> CiStateOut:
    """Change the fields you send. Needs If-Match."""
    row = await catalogue.update_state(
        session,
        subject,
        state_id,
        expected_version=version,
        values=body.model_dump(include=body.model_fields_set),
    )
    set_etag(response, row.version)
    return CiStateOut.of(row)


@router.delete(
    "/ci-states/{state_id}",
    summary="Remove a CI state",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=CONFLICT,
    dependencies=[audited("cmdb.ci_state_deleted", object_type="cmdb_ci_state")],
)
async def delete_state(
    state_id: uuid.UUID, version: ExpectedVersion, session: TenantSession, subject: Configure
) -> Response:
    """Refused (409 `cmdb_ci_state_in_use`, with the count) while CIs hold it."""
    await catalogue.delete_state(session, subject, state_id, expected_version=version)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- routes: settings -----------------------------------------------------------------------------


@router.get("/settings", summary="CMDB settings")
async def get_settings(
    session: TenantSession, subject: View, response: Response
) -> CmdbSettingsOut:
    """The tenant's CMDB settings."""
    del subject
    row = await catalogue.get_settings(session)
    set_etag(response, row.version)
    return CmdbSettingsOut(
        exclude_eol_from_pickers=row.exclude_eol_from_pickers, version=row.version
    )


@router.put(
    "/settings",
    summary="Change the CMDB settings",
    responses=CONFLICT,
    dependencies=[audited("cmdb.settings_changed", object_type="cmdb_settings")],
)
async def put_settings(
    body: CmdbSettingsIn,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Configure,
    response: Response,
) -> CmdbSettingsOut:
    """Change the settings. Needs If-Match."""
    row = await catalogue.update_settings(
        session,
        subject,
        expected_version=version,
        exclude_eol_from_pickers=body.exclude_eol_from_pickers,
    )
    set_etag(response, row.version)
    return CmdbSettingsOut(
        exclude_eol_from_pickers=row.exclude_eol_from_pickers, version=row.version
    )


# --- routes: CIs ----------------------------------------------------------------------------------


@router.get("/cis", summary="List CIs")
async def list_cis(
    session: TenantSession,
    query: CisTreeQuery,
    subject: View,
    type_tree: Annotated[
        uuid.UUID | None,
        Query(description="This type and the types below it (`type_id=` is that type only)."),
    ] = None,
) -> CiPage:
    """CIs you may see. Filter with the DSL (`filter=`) or simple parameters, sort, page."""
    return _page(await cis.list_cis(session, subject, query, type_id=type_tree))


@router.get("/cis/trash", summary="CIs in the trash")
async def list_trash(session: TenantSession, query: CisQuery, subject: View) -> CiPage:
    """Removed CIs you may see; restore with POST …/restore."""
    return _page(await cis.list_cis(session, subject, query, trash=True))


@router.get("/cis/picker", summary="CIs to choose from")
async def picker(
    session: TenantSession,
    subject: View,
    search: Annotated[str | None, Query(max_length=200)] = None,
    type_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=cis.PICKER_MAX)] = 20,
) -> CiPickerOut:
    """CIs you may see by name or ID; end-of-life ones left out when the settings say so."""
    rows = await cis.picker(session, subject, search=search, type_id=type_id, limit=limit)
    return CiPickerOut(items=[CiListItem.of(r) for r in rows])


@router.post(
    "/cis",
    summary="Create a CI",
    status_code=status.HTTP_201_CREATED,
    response_model=CiOut,
)
async def create_ci(
    body: CiIn, session: TenantSession, subject: Add, idempotency: Idempotency, request: Request
) -> Response:
    """A new CI. Send an Idempotency-Key: a retried request returns the same 201."""

    async def run() -> Created:
        view = await cis.create(session, subject, body.model_dump(), source_of(request))
        out = CiOut.of_view(view)
        return Created(
            body=out, headers={"Location": _location(f"cis/{out.id}"), "ETag": f'"{out.version}"'}
        )

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.post(
    "/cis/from-assets",
    summary="Create CIs from assets",
    status_code=status.HTTP_201_CREATED,
    response_model=CiFromAssetsOut,
)
async def from_assets(
    body: CiFromAssetsIn,
    session: TenantSession,
    subject: Add,
    idempotency: Idempotency,
    request: Request,
) -> Response:
    """One CI per asset you may see, named after it; assets that have a CI are skipped."""

    async def run() -> Created:
        result = await cis.from_assets(
            session,
            subject,
            body.asset_ids,
            type_id=body.type_id,
            state_id=body.state_id,
            source=source_of(request),
        )
        out = CiFromAssetsOut(
            created=[CiListItem.of(r) for r in result.created],
            skipped=[CiSkippedAsset(asset_id=a, reason=r) for a, r in result.skipped],  # type: ignore[arg-type]  # the service gives only these reasons
        )
        return Created(body=out, headers={})

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.get("/cis/{ci_id}", summary="Get a CI")
async def get_ci(
    ci_id: uuid.UUID, session: TenantSession, subject: View, response: Response
) -> CiOut:
    """One CI you may see (404 `cmdb_ci_not_found` otherwise)."""
    view = await cis.get_ci(session, subject, ci_id)
    set_etag(response, view.record.version)
    return CiOut.of_view(view)


@router.patch("/cis/{ci_id}", summary="Edit a CI", responses=CONFLICT)
async def edit_ci(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    ci_id: uuid.UUID,
    body: CiPatch,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Edit,
    response: Response,
    request: Request,
) -> CiOut:
    """Change the fields you send. Needs If-Match."""
    view = await cis.update(
        session,
        subject,
        ci_id,
        expected_version=version,
        values=body.model_dump(include=body.model_fields_set),
        source=source_of(request),
    )
    set_etag(response, view.record.version)
    return CiOut.of_view(view)


@router.post(
    "/cis/{ci_id}/copy",
    summary="Copy a CI",
    status_code=status.HTTP_201_CREATED,
    response_model=CiOut,
)
async def copy_ci(
    ci_id: uuid.UUID,
    session: TenantSession,
    subject: Add,
    idempotency: Idempotency,
    request: Request,
) -> Response:
    """A new CI with the same type, fields and values (never the asset link). Idempotency-Key."""

    async def run() -> Created:
        out = CiOut.of_view(await cis.copy(session, subject, ci_id, source_of(request)))
        return Created(
            body=out, headers={"Location": _location(f"cis/{out.id}"), "ETag": f'"{out.version}"'}
        )

    return await idempotency.run({"copy_of": str(ci_id)}, run, status_code=status.HTTP_201_CREATED)


@router.post("/cis/{ci_id}/change-type", summary="Change a CI's type", responses=CONFLICT)
async def change_type(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    ci_id: uuid.UUID,
    body: CiTypeChangeIn,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Edit,
    response: Response,
    request: Request,
) -> CiOut:
    """Move the CI to another type.

    Custom values outside the new type's fields are dropped only with `confirm_dropped_fields`
    (409 `cmdb_ci_type_change_drops_fields` otherwise); the history names those fields, never the
    values.
    """
    view = await cis.change_type(
        session,
        subject,
        ci_id,
        type_id=body.type_id,
        expected_version=version,
        source=source_of(request),
        confirm_dropped_fields=body.confirm_dropped_fields,
    )
    set_etag(response, view.record.version)
    return CiOut.of_view(view)


@router.get("/cis/{ci_id}/change-type-preview", summary="Preview a CI's type change")
async def change_type_preview(
    ci_id: uuid.UUID,
    type_id: Annotated[uuid.UUID, Query(description="The type the CI would move to.")],
    session: TenantSession,
    subject: Edit,
) -> CiTypeChangePreviewOut:
    """The custom values moving the CI to that type would drop, by field (nothing changes)."""
    preview = await cis.type_change_preview(session, subject, ci_id, type_id)
    return CiTypeChangePreviewOut(
        dropped=[CiDroppedFieldOut(key=d.key, labels=d.labels) for d in preview.dropped],
        blocked=preview.blocked,
    )


@router.delete(
    "/cis/{ci_id}",
    summary="Move a CI to the trash",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=CONFLICT,
)
async def delete_ci(
    ci_id: uuid.UUID,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Delete,
    request: Request,
) -> Response:
    """Soft delete: recoverable from the trash."""
    await cis.remove(session, subject, ci_id, expected_version=version, source=source_of(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/cis/{ci_id}/restore", summary="Restore a CI", responses=CONFLICT)
async def restore_ci(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    ci_id: uuid.UUID,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Delete,
    response: Response,
    request: Request,
) -> CiOut:
    """Take it out of the trash (409 `cmdb_asset_has_ci` if its asset has another CI now)."""
    view = await cis.restore(
        session, subject, ci_id, expected_version=version, source=source_of(request)
    )
    set_etag(response, view.record.version)
    return CiOut.of_view(view)


@router.get("/cis/{ci_id}/history", summary="History of a CI")
async def history(
    ci_id: uuid.UUID,
    session: TenantSession,
    subject: View,
    cursor: Annotated[str | None, Query(description="next_cursor of the previous page.")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> CiHistoryOut:
    """Every save, newest first: who, when, from where, what changed."""
    before = int(cursor) if cursor and cursor.isdigit() else None
    entries, next_version, names = await cis.history(
        session, subject, ci_id, before_version=before, limit=limit
    )
    return CiHistoryOut(
        items=[CiHistoryEntryOut.of(e, names) for e in entries],
        next_cursor=None if next_version is None else str(next_version),
    )
