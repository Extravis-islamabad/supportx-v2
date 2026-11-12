"""The asset record over HTTP, /api/v1/assets (WP-049a session 2). No business logic.

Registered after the catalogue routes (assets/api/routes.py), so `/assets/states` and friends
match first and `/assets/{asset_id}` only takes an ID. Reading needs `assets.view`, writing
`assets.manage`, each within its scope. Writes use If-Match; creates take an Idempotency-Key.
"""

import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.core.errors import NotFound, ProblemDetail
from app.modules import metadata
from app.modules.assets.domain.assets import IDENTIFIER_MAX, LOCATION_MAX, NAME_MAX
from app.modules.assets.domain.financials import (
    COST_CENTRE_MAX,
    GL_CODE_MAX,
    LIFE_MAX,
    DepreciationChoice,
)
from app.modules.assets.domain.views import AssetView
from app.modules.assets.infra.models import Asset, AssetAssignment, AssetDisposal, AssetProduct
from app.modules.assets.service import assets as service
from app.modules.assets.service import (
    bulk,
    disposals,
    linked,
    merge,
    moves,
    ownership,
    relationships,
    views,
)
from app.modules.assets.service.catalogue import TEXT_MAX
from app.modules.assets.service.refs import asset_refs, can_see
from app.modules.audit import RequestFacts, audited
from app.modules.audit import record as record_audit
from app.modules.identity_access import Subject, user_names
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.filters import FilterField
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.listing import ListQuery, Page, list_query, paginate
from app.shared.api.ratelimit import rate_limit
from app.shared.history import HistoryFilter, Source, history_page, source_of
from app.shared.search import ENGINE, SearchDocument

router = APIRouter(
    prefix="/assets",
    tags=["assets"],
    dependencies=[Depends(rate_limit("assets"))],
    responses={
        401: {"model": ProblemDetail, "description": "Not signed in."},
        403: {"model": ProblemDetail, "description": "Missing permission, feature or slot."},
    },
)
WRITE: dict[int | str, dict[str, object]] = {
    404: {"model": ProblemDetail, "description": "asset_not_found"},
    409: {"model": ProblemDetail, "description": "version_conflict"},
}

View = Annotated[Subject, Depends(require_permission(service.VIEW))]
Manage = Annotated[Subject, Depends(require_permission(service.MANAGE))]


async def _custom_filters(session: AsyncSession) -> dict[str, FilterField]:
    return await metadata.filter_fields(session, service.ENTITY, "assets")


AssetsQuery = Annotated[
    ListQuery,
    Depends(
        list_query(
            service.ASSET_FIELDS,
            # WP-049b s4a: the built-in view and the product type tree node (REQ-AST-047).
            extra_parameters=frozenset({"search", "view", "product_type"}),
            fields_for=_custom_filters,
        )
    ),
]
_COLUMNS = Asset.__table__.c
TEXT = SearchDocument(vector=_COLUMNS.search_vector, short_text=_COLUMNS.search_text)


class AssetOut(BaseModel):
    """An asset (REQ-AST-007)."""

    id: uuid.UUID
    name: str
    product_id: uuid.UUID
    product_type_id: uuid.UUID
    state_id: uuid.UUID
    tag: str | None
    serial_number: str | None
    discovered_serial: str | None = Field(description="Set by discovery; read-only here.")
    barcode: str | None
    vendor_id: uuid.UUID | None
    site_id: uuid.UUID | None
    owner_user_id: uuid.UUID | None = Field(default=None, description="Held by this person.")
    department_id: uuid.UUID | None = Field(default=None, description="Held by a department.")
    parent_asset_id: uuid.UUID | None = Field(default=None, description="Fitted to this asset.")
    location: str | None
    purchase_order_id: uuid.UUID | None
    purchase_price: Decimal | None = Field(description="Null without assets.view_financials.")
    purchase_tax: Decimal | None = Field(description="Null without assets.view_financials.")
    purchase_total: Decimal | None = Field(
        description="Price plus tax (D-141), worked out. Null without assets.view_financials."
    )
    currency: str | None
    acquired_on: date | None
    warranty_expires_on: date | None
    expires_on: date | None
    description: str | None
    loanable: bool = Field(default=False, description="May go out on a loan (REQ-AST-029).")
    cost_centre: str | None = Field(default=None, description="Free text (REQ-AST-038).")
    gl_code: str | None = Field(default=None, description="From the product unless typed.")
    custom: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    version: int

    @classmethod
    def of(cls, row: Asset, subject: Subject) -> "AssetOut":
        """From the row; the money (price, tax, total) null for those who may not see it."""
        money = service.sees_money(subject)
        return cls(
            id=row.id,
            name=row.name,
            product_id=row.product_id,
            product_type_id=row.product_type_id,
            state_id=row.state_id,
            tag=row.tag,
            serial_number=row.serial_number,
            discovered_serial=row.discovered_serial,
            barcode=row.barcode,
            vendor_id=row.vendor_id,
            site_id=row.site_id,
            owner_user_id=row.owner_user_id,
            department_id=row.department_id,
            parent_asset_id=row.parent_asset_id,
            location=row.location,
            purchase_order_id=row.purchase_order_id,
            purchase_price=row.purchase_price if money else None,
            purchase_tax=row.purchase_tax if money else None,
            purchase_total=service.purchase_total(row) if money else None,
            currency=row.currency,
            acquired_on=row.acquired_on,
            warranty_expires_on=row.warranty_expires_on,
            loanable=row.loanable,
            cost_centre=row.cost_centre,
            gl_code=row.gl_code,
            expires_on=row.expires_on,
            description=row.description,
            custom=dict(row.custom),
            created_at=row.created_at,
            updated_at=row.updated_at,
            version=row.version,
        )


class AssetIn(BaseModel):
    """A new asset: name and product; the tag comes from the pattern unless typed."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=NAME_MAX)
    product_id: uuid.UUID
    tag: str | None = Field(default=None, max_length=IDENTIFIER_MAX)
    serial_number: str | None = Field(default=None, max_length=IDENTIFIER_MAX)
    barcode: str | None = Field(default=None, max_length=IDENTIFIER_MAX)
    vendor_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    location: str | None = Field(default=None, max_length=LOCATION_MAX)
    purchase_order_id: uuid.UUID | None = None
    purchase_price: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    purchase_tax: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    acquired_on: date | None = None
    warranty_expires_on: date | None = None
    expires_on: date | None = None
    description: str | None = Field(default=None, max_length=TEXT_MAX)
    cost_centre: str | None = Field(default=None, max_length=COST_CENTRE_MAX)
    gl_code: str | None = Field(default=None, max_length=GL_CODE_MAX)
    depreciation_method: DepreciationChoice | None = Field(
        default=None, description="The asset's own (null: the product's). assets.view_financials."
    )
    useful_life_years: int | None = Field(default=None, ge=1, le=LIFE_MAX)
    salvage_value: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    custom: dict[str, Any] | None = Field(default=None, description="Custom field values by key.")


class AssetPatch(BaseModel):
    """Asset fields to change (only those sent; null clears an optional one)."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=NAME_MAX)
    product_id: uuid.UUID | None = None
    tag: str | None = Field(default=None, max_length=IDENTIFIER_MAX)
    serial_number: str | None = Field(default=None, max_length=IDENTIFIER_MAX)
    barcode: str | None = Field(default=None, max_length=IDENTIFIER_MAX)
    vendor_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    location: str | None = Field(default=None, max_length=LOCATION_MAX)
    purchase_order_id: uuid.UUID | None = None
    purchase_price: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    purchase_tax: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    acquired_on: date | None = None
    warranty_expires_on: date | None = None
    expires_on: date | None = None
    description: str | None = Field(default=None, max_length=TEXT_MAX)
    cost_centre: str | None = Field(default=None, max_length=COST_CENTRE_MAX)
    gl_code: str | None = Field(default=None, max_length=GL_CODE_MAX)
    depreciation_method: DepreciationChoice | None = Field(
        default=None, description="The asset's own (null: the product's). assets.view_financials."
    )
    useful_life_years: int | None = Field(default=None, ge=1, le=LIFE_MAX)
    salvage_value: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    custom: dict[str, Any] | None = Field(
        default=None, description="Custom values to change by key; null clears one."
    )
    reason: str | None = Field(
        default=None,
        max_length=1000,
        description="Why: required to change a disposed asset (assets.edit_disposed).",
    )


class AssetChangeOut(BaseModel):
    """One field's old and new value in an asset's history."""

    field: str
    old: Any = None
    new: Any = None
    hidden: bool = Field(
        default=False,
        description="Money without assets.view_financials (D-157): the line stays, values null.",
    )


class AssetChangeOriginOut(BaseModel):
    """An audit fix (its display ID and name) or the overdue-scan rule (WP-049b s3)."""

    kind: Literal["asset_audit", "asset_overdue_rule"]
    audit_id: uuid.UUID | None = None
    display_id: str | None = None
    name: str | None = None
    reason_code: Literal["overdue_scan_rule"] | None = Field(
        default=None, description="The change's reason as a code; labelled with its params."
    )
    reason_params: dict[str, int] = Field(default_factory=dict)


def _origin(ref: object) -> AssetChangeOriginOut | None:
    if not isinstance(ref, dict):
        return None
    if ref.get("kind") == "asset_audit":
        return AssetChangeOriginOut(
            kind="asset_audit",
            audit_id=uuid.UUID(str(ref["id"])),
            display_id=str(ref.get("display_id") or ""),
            name=str(ref.get("name") or ""),
        )
    if ref.get("kind") == "asset_overdue_rule":
        params = ref.get("params")
        return AssetChangeOriginOut(
            kind="asset_overdue_rule",
            reason_code="overdue_scan_rule" if ref.get("reason") == "overdue_scan_rule" else None,
            reason_params={k: v for k, v in (params or {}).items() if isinstance(v, int)}
            if isinstance(params, dict)
            else {},
        )
    return None


class AssetHistoryEntryOut(BaseModel):
    """One save of an asset: who, when, how, what changed."""

    version: int
    kind: str
    actor_id: str | None
    actor_name: str | None
    source: str
    reason: str | None
    occurred_at: datetime
    changes: list[AssetChangeOut]
    origin: AssetChangeOriginOut | None = Field(
        default=None,
        description="What made the change on a person's behalf: an audit's fix, or a rule.",
    )


HistoryView = Literal["all", "state", "assignment"]
# REQ-AST-049 sub-views: the fields each shows. Assignment: who holds it (a person, a department
# or the asset it is fitted to); loans and their returns set and clear those too.
HISTORY_VIEWS: dict[str, tuple[str, ...]] = {
    "state": ("state_id",),
    "assignment": ("owner_user_id", "department_id", "parent_asset_id"),
}


class AssetHistoryOut(BaseModel):
    """A page of an asset's history, newest first."""

    items: list[AssetHistoryEntryOut]
    next_cursor: str | None


Search = Annotated[
    str | None,
    Query(max_length=200, description="Words or an identifier: name, tag, serials, barcode."),
]


ViewParam = Annotated[
    AssetView | None,
    Query(description="A built-in view (REQ-AST-047); none: all you may see."),
]
TypeParam = Annotated[
    uuid.UUID | None,
    Query(description="A product type: that type and every type below it (the tree)."),
]


class AssetListPage(Page[AssetOut]):
    """A page of assets with the names its columns show (REQ-AST-047's default columns).

    Holders by display name, parent assets by tag or name (one the caller may not see is left
    out), products by name. Departments and sites come from the organisation's own lists.
    """

    people: dict[str, str] = Field(default_factory=dict, description="Holder ID -> name.")
    parents: dict[str, str] = Field(default_factory=dict, description="Parent ID -> tag/name.")
    products: dict[str, str] = Field(default_factory=dict, description="Product ID -> name.")


async def _names(
    session: AsyncSession, subject: Subject, rows: list[Asset]
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    people = await user_names(
        session, sorted({str(r.owner_user_id) for r in rows if r.owner_user_id})
    )
    parent_ids = sorted({r.parent_asset_id for r in rows if r.parent_asset_id})
    refs = await asset_refs(session, subject, parent_ids)
    parents = {str(k): (v.tag or v.name or "") for k, v in refs.items() if v.name is not None}
    product_ids = sorted({r.product_id for r in rows})
    products = (
        {
            str(i): n
            for i, n in await session.execute(
                select(AssetProduct.id, AssetProduct.name).where(AssetProduct.id.in_(product_ids))
            )
        }
        if product_ids
        else {}
    )
    return people, parents, products


async def _page(  # noqa: PLR0913 - the list's parts, explicit
    session: AsyncSession,
    query: ListQuery,
    subject: Subject,
    search: str | None,
    *,
    trash: bool,
    view: AssetView | None = None,
    product_type: uuid.UUID | None = None,
) -> AssetListPage:
    statement = await views.rows(
        session, subject, view=view, product_type=product_type, trash=trash
    )
    search = (search or "").strip()
    if search:
        words = await ENGINE.match(session, TEXT, search)
        # REQ-AST-052 AC2: a merged asset's tag, serial or barcode finds its survivor.
        alias = Asset.id.in_(merge.alias_survivors(search))
        statement = statement.where(alias if words is None else or_(words.predicate, alias))
    page = await paginate(session, statement, query)
    people, parents, products = await _names(session, subject, list(page.rows))
    return AssetListPage(
        items=[AssetOut.of(row, subject) for row in page.rows],
        next_cursor=page.next_cursor,
        has_more=page.has_more,
        estimated_total=page.estimated_total,
        people=people,
        parents=parents,
        products=products,
    )


@router.get("", summary="Assets")
async def list_assets(  # noqa: PLR0913, PLR0917 - FastAPI dependencies and filters
    session: TenantSession,
    query: AssetsQuery,
    subject: View,
    search: Search = None,
    view: ViewParam = None,
    product_type: TypeParam = None,
) -> AssetListPage:
    """The assets you may see: filtered, searched and paged.

    Filters: the DSL, `custom.<key>` included. `search`: name, tag, serials, barcode and custom
    text. `view`: a built-in view; `product_type`: a tree node and its descendants. Newest change
    first unless sorted.
    """
    return await _page(
        session, query, subject, search, trash=False, view=view, product_type=product_type
    )


@router.get("/trash", summary="Assets in the trash")
async def list_trash(
    session: TenantSession, query: AssetsQuery, subject: Manage, search: Search = None
) -> Page[AssetOut]:
    """The trashed assets you may restore."""
    page = await _page(session, query, subject, search, trash=True)
    return Page[AssetOut](
        items=page.items,
        next_cursor=page.next_cursor,
        has_more=page.has_more,
        estimated_total=page.estimated_total,
    )


class AssetTypeCountOut(BaseModel):
    """Live assets of one product type (that type only: the screen sums a branch)."""

    product_type_id: uuid.UUID
    count: int


class AssetTypeCountsOut(BaseModel):
    """The tree's counts within a view, and the view's total."""

    view: AssetView
    total: int
    types: list[AssetTypeCountOut]


@router.get("/type-counts", summary="Assets per product type, for the tree")
async def type_counts(
    session: TenantSession, subject: View, view: ViewParam = None
) -> AssetTypeCountsOut:
    """Per product type, the live assets you may see in the view (REQ-AST-047 AC1)."""
    found = await views.type_counts(session, subject, view=view)
    return AssetTypeCountsOut(
        view=view or AssetView.ALL,
        total=sum(found.values()),
        types=[AssetTypeCountOut(product_type_id=k, count=v) for k, v in found.items()],
    )


@router.post(
    "",
    summary="Add an asset",
    status_code=status.HTTP_201_CREATED,
    response_model=AssetOut,
    dependencies=[audited("asset.created", object_type="asset")],
)
async def create_asset(
    body: AssetIn,
    session: TenantSession,
    subject: Manage,
    idempotency: Idempotency,
    request: Request,
) -> Response:
    """A new asset in the default in-stock state. Send an Idempotency-Key.

    An IT asset needs a free slot of the plan's asset limit (403 asset_limit_reached).
    """

    async def run() -> Created:
        row = await service.create_asset(
            session, subject, body.model_dump(exclude_none=True), source=source_of(request)
        )
        return Created(body=AssetOut.of(row, subject), headers={"ETag": f'"{row.version}"'})

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.get(
    "/{asset_id}",
    summary="Get an asset",
    responses={404: {"model": ProblemDetail, "description": "asset_not_found"}},
)
async def get_asset(
    asset_id: uuid.UUID, session: TenantSession, subject: View, response: Response
) -> AssetOut:
    """One asset you may see.

    A merged asset's ID answers 404 `asset_merged` naming the survivor (`survivor_id`) when you
    may see it, so the screen opens the survivor (REQ-AST-052 AC2).
    """
    try:
        row = await service.get_asset(session, subject, asset_id)
    except NotFound:
        survivor = await merge.survivor_of(session, asset_id)
        if survivor is not None and await can_see(session, subject, survivor):
            raise NotFound(code="asset_merged", params={"survivor_id": str(survivor)}) from None
        raise
    set_etag(response, row.version)
    return AssetOut.of(row, subject)


class AssetAccessOut(BaseModel):
    """What you may change on this asset (its page shows the matching actions)."""

    manage: bool = Field(description="assets.manage on it: everything your other rights allow.")
    through_ticket: bool = Field(
        description="D-157: linked to your own ticket and held by its requester or department:"
        " its state, location, notes and fitted components only."
    )


@router.get(
    "/{asset_id}/access",
    summary="What you may change on an asset",
    responses={404: {"model": ProblemDetail, "description": "asset_not_found"}},
)
async def asset_access(
    asset_id: uuid.UUID, session: TenantSession, subject: View
) -> AssetAccessOut:
    """Whether you manage it, or may change a few fields through your own ticket (D-157)."""
    manage, through_ticket = await service.edit_reach(session, subject, asset_id)
    return AssetAccessOut(manage=manage, through_ticket=through_ticket)


_REQUIRED = {"name", "product_id", "tag"}


@router.patch(
    "/{asset_id}",
    summary="Change an asset",
    responses=WRITE,
    dependencies=[audited("asset.updated", object_type="asset", object_param="asset_id")],
)
async def patch_asset(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    asset_id: uuid.UUID,
    body: AssetPatch,
    session: TenantSession,
    subject: View,  # assets.manage, or a technician's ticket (D-157): the service decides
    version: ExpectedVersion,
    response: Response,
    request: Request,
) -> AssetOut:
    """Change the fields sent (If-Match). The state moves through the life cycle, not here."""
    sent = body.model_dump(include=body.model_fields_set - {"reason"})
    values = {k: v for k, v in sent.items() if v is not None or k not in _REQUIRED}
    row = await service.update_asset(
        session,
        subject,
        asset_id,
        values,
        expected_version=version,
        source=source_of(request),
        reason=body.reason,
    )
    set_etag(response, row.version)
    return AssetOut.of(row, subject)


@router.delete(
    "/{asset_id}",
    summary="Move an asset to the trash",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WRITE,
    dependencies=[audited("asset.deleted", object_type="asset", object_param="asset_id")],
)
async def delete_asset(
    asset_id: uuid.UUID,
    session: TenantSession,
    subject: Manage,
    version: ExpectedVersion,
    request: Request,
) -> None:
    """To the trash (If-Match): it frees its slot; its tag and serial stay taken."""
    await service.delete_asset(
        session, subject, asset_id, expected_version=version, source=source_of(request)
    )


@router.post(
    "/{asset_id}/restore",
    summary="Restore an asset from the trash",
    responses={
        404: {"model": ProblemDetail, "description": "asset_not_found"},
        409: {"model": ProblemDetail, "description": "asset_restore_merged"},
    },
    dependencies=[audited("asset.restored", object_type="asset", object_param="asset_id")],
)
async def restore_asset(  # noqa: PLR0913 - FastAPI dependencies and the confirmation
    *,
    asset_id: uuid.UUID,
    session: TenantSession,
    subject: Manage,
    request: Request,
    response: Response,
    confirm_merged: Annotated[
        bool, Query(description="Restore an asset merged into another (after the warning).")
    ] = False,
) -> AssetOut:
    """Back from the trash; an IT asset needs a free slot again.

    An asset merged into another answers 409 `asset_restore_merged` (naming the survivor) until
    `confirm_merged` is sent: it then comes back on its own, and the merge stays as it was.
    """
    row = await service.restore_asset(
        session, subject, asset_id, source=source_of(request), confirm_merged=confirm_merged
    )
    set_etag(response, row.version)
    return AssetOut.of(row, subject)


def _change_out(field: str, old: Any, new: Any, *, money: bool) -> AssetChangeOut:  # noqa: ANN401 - history keeps JSON values
    """A history line; a money field's values masked for those who may not see money (D-157).

    Masked rather than dropped: the reader still sees that the price changed, and when and by
    whom, and the pages keep their size.
    """
    if not money and field in service.MONEY_FIELDS:
        return AssetChangeOut(field=field, hidden=True)
    return AssetChangeOut(field=field, old=old, new=new)


@router.get(
    "/{asset_id}/history",
    summary="An asset's history",
    responses={404: {"model": ProblemDetail, "description": "asset_not_found"}},
)
async def asset_history(  # noqa: PLR0913, PLR0917 - FastAPI dependencies and filters
    asset_id: uuid.UUID,
    session: TenantSession,
    subject: View,
    cursor: Annotated[int | None, Query(ge=1, description="next_cursor of the last page")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    view: Annotated[
        HistoryView,
        Query(description="state: state moves only; assignment: who holds it (and loans)."),
    ] = "all",
    field: Annotated[
        list[str] | None, Query(max_length=20, description="Only these fields.")
    ] = None,
    source: Annotated[
        list[Source] | None, Query(max_length=20, description="Only from these.")
    ] = None,
    actor_id: Annotated[uuid.UUID | None, Query(description="Only this person's changes.")] = None,
    since: Annotated[date | None, Query(description="From this day (inclusive, UTC).")] = None,
    until: Annotated[date | None, Query(description="To this day (inclusive, UTC).")] = None,
) -> AssetHistoryOut:
    """Every save, newest first, with who, when, how (UI, API, rule ...) and what changed.

    Filters (REQ-AST-049): a sub-view (state, assignment), fields, sources, a person and days.
    """
    await service.get_asset(session, subject, asset_id)
    fields = set(field or ()) | set(HISTORY_VIEWS.get(view, ()))
    where = HistoryFilter(
        fields=frozenset(fields),
        sources=frozenset(source or ()),
        actor_id=None if actor_id is None else str(actor_id),
        since=None if since is None else datetime.combine(since, time.min, UTC),
        until=None if until is None else datetime.combine(until + timedelta(days=1), time.min, UTC),
    )
    entries, next_version = await history_page(
        session, service.RECORD_TYPE, asset_id, before_version=cursor, limit=limit, where=where
    )
    names = await user_names(session, [e.actor_id for e in entries if e.actor_id])
    money = service.sees_money(subject)
    return AssetHistoryOut(
        items=[
            AssetHistoryEntryOut(
                version=e.version,
                kind=e.kind,
                actor_id=e.actor_id,
                actor_name=names.get(e.actor_id) if e.actor_id else None,
                source=e.source,
                reason=e.reason,
                occurred_at=e.occurred_at,
                changes=[_change_out(c.field, c.old, c.new, money=money) for c in e.changes],
                origin=_origin(e.automation_ref),
            )
            for e in entries
        ],
        next_cursor=None if next_version is None else str(next_version),
    )


class AssetMoveOptionOut(BaseModel):
    """A move the asset's life cycle lists from its state now."""

    to_state_id: uuid.UUID
    reason_required: bool
    required_fields: list[str] = Field(description="Asset fields (or custom.<key>) to fill first.")
    allowed: bool = Field(description="False: you lack the move's permission (show it disabled).")


class AssetMoveIn(BaseModel):
    """Move the asset to another state (REQ-AST-012)."""

    model_config = ConfigDict(extra="forbid")

    to_state_id: uuid.UUID
    reason: str | None = Field(default=None, max_length=moves.REASON_MAX)


@router.get(
    "/{asset_id}/moves",
    summary="The moves an asset may make",
    responses={404: {"model": ProblemDetail, "description": "asset_not_found"}},
)
async def asset_moves(
    asset_id: uuid.UUID, session: TenantSession, subject: View
) -> list[AssetMoveOptionOut]:
    """From its state now, along its type's life cycle, in the states' order."""
    options = await moves.move_options(session, subject, asset_id)
    return [
        AssetMoveOptionOut(
            to_state_id=o.to_state.id,
            reason_required=o.reason_required,
            required_fields=list(o.required_fields),
            allowed=o.allowed,
        )
        for o in options
    ]


@router.post(
    "/{asset_id}/move",
    summary="Move an asset to another state",
    responses={
        **WRITE,
        409: {"model": ProblemDetail, "description": "version_conflict, asset_move_not_allowed"},
    },
    dependencies=[audited("asset.moved", object_type="asset", object_param="asset_id")],
)
async def move_asset(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    asset_id: uuid.UUID,
    body: AssetMoveIn,
    session: TenantSession,
    subject: View,  # assets.manage, or a technician's ticket (D-157): the service decides
    version: ExpectedVersion,
    response: Response,
    request: Request,
) -> AssetOut:
    """Along the life cycle (If-Match), with a reason where the move or state asks for one."""
    row = await moves.move_asset(
        session,
        subject,
        asset_id,
        to_state_id=body.to_state_id,
        reason=body.reason,
        expected_version=version,
        source=source_of(request),
    )
    set_etag(response, row.version)
    return AssetOut.of(row, subject)


class AssetCopyIn(BaseModel):
    """How many copies (up to the tenant's copy limit, Appendix A: 50)."""

    model_config = ConfigDict(extra="forbid")

    count: int = Field(ge=1, le=500)


class AssetCopiesOut(BaseModel):
    """The new assets, in the order made."""

    items: list[AssetOut]


@router.post(
    "/{asset_id}/copy",
    summary="Copy an asset",
    status_code=status.HTTP_201_CREATED,
    response_model=AssetCopiesOut,
    responses={
        404: {"model": ProblemDetail, "description": "asset_not_found"},
        409: {"model": ProblemDetail, "description": "asset_copy_limit (params: max)"},
    },
    dependencies=[audited("asset.copied", object_type="asset", object_param="asset_id")],
)
async def copy_asset(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    asset_id: uuid.UUID,
    body: AssetCopyIn,
    session: TenantSession,
    subject: Manage,
    idempotency: Idempotency,
    request: Request,
) -> Response:
    """New assets like this one: new tags, no serial or barcode, in stock. Idempotency-Key."""

    async def run() -> Created:
        made = await bulk.copy_asset(
            session, subject, asset_id, count=body.count, source=source_of(request)
        )
        return Created(body=AssetCopiesOut(items=[AssetOut.of(row, subject) for row in made]))

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


class AssetBulkMoveItem(BaseModel):
    """One asset, at the version you saw."""

    model_config = ConfigDict(extra="forbid")

    asset_id: uuid.UUID
    version: int


class AssetBulkMoveIn(BaseModel):
    """Move these assets to one state, with one reason."""

    model_config = ConfigDict(extra="forbid")

    items: list[AssetBulkMoveItem] = Field(min_length=1, max_length=bulk.BULK_MAX)
    to_state_id: uuid.UUID
    reason: str | None = Field(default=None, max_length=moves.REASON_MAX)


class AssetBulkMoveResult(BaseModel):
    """One asset's outcome: moved (with its new version), or why not."""

    asset_id: uuid.UUID
    moved: bool
    code: str | None = None
    version: int | None = None


@router.post("/bulk-moves", summary="Move several assets to one state")
async def bulk_move(
    body: AssetBulkMoveIn, session: TenantSession, subject: Manage, request: Request
) -> list[AssetBulkMoveResult]:
    """Each one as a single move (life cycle, reason, permission, If-Match); per-asset results."""
    outcomes = await bulk.bulk_move(
        session,
        subject,
        [(i.asset_id, i.version) for i in body.items],
        to_state_id=body.to_state_id,
        reason=body.reason,
        source=source_of(request),
    )
    facts = RequestFacts.of(request)
    for outcome in outcomes:
        if outcome.moved:  # one audit entry per moved asset, as for a single move
            await record_audit(
                session,
                action_code="asset.moved",
                facts=facts,
                object_type="asset",
                object_id=outcome.asset_id,
                details={"bulk": True},
            )
    return [
        AssetBulkMoveResult(asset_id=o.asset_id, moved=o.moved, code=o.code, version=o.version)
        for o in outcomes
    ]


# --- disposal (REQ-AST-017) ------------------------------------------------------------------


class AssetDisposalIn(BaseModel):
    """Dispose of an asset: the record, and the move to the disposed state, in one step."""

    model_config = ConfigDict(extra="forbid")

    disposed_on: date
    method: Literal["resale", "recycling", "donation", "destruction", "returned_to_vendor", "other"]
    reason: str = Field(min_length=1, max_length=1000)
    cost: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    currency: str | None = Field(default=None, pattern="^[A-Z]{3}$")
    approved_by: uuid.UUID | None = Field(default=None, description="Who approved it (a person).")
    components: Literal["detach", "dispose"] | None = Field(
        default=None,
        description="Its fitted components: detach them, or dispose of them with the same record. "
        "Required when it has any (409 asset_has_components, params: count).",
    )


class AssetDisposalOut(BaseModel):
    """An asset's disposal record. The certificate is a file of owner `asset_disposal`."""

    id: uuid.UUID
    asset_id: uuid.UUID
    disposed_on: date
    method: str
    reason: str
    cost: Decimal | None
    currency: str | None
    approved_by: uuid.UUID | None
    recorded_by: uuid.UUID | None
    recorded_at: datetime
    version: int

    @classmethod
    def of(cls, row: AssetDisposal) -> "AssetDisposalOut":
        """The API shape of a disposal record."""
        return cls(
            id=row.id,
            asset_id=row.asset_id,
            disposed_on=row.disposed_on,
            method=row.method,
            reason=row.reason,
            cost=row.cost,
            currency=row.currency,
            approved_by=row.approved_by,
            recorded_by=row.created_by,
            recorded_at=row.created_at,
            version=row.version,
        )


@router.post(
    "/{asset_id}/dispose",
    summary="Dispose of an asset, with its record",
    responses={
        **WRITE,
        409: {
            "model": ProblemDetail,
            "description": "version_conflict, asset_move_not_allowed, asset_already_disposed, "
            "or what still holds the asset (an open loan)",
        },
    },
    dependencies=[audited("asset.disposed", object_type="asset", object_param="asset_id")],
)
async def dispose_asset(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    asset_id: uuid.UUID,
    body: AssetDisposalIn,
    session: TenantSession,
    subject: Manage,
    version: ExpectedVersion,
    response: Response,
    request: Request,
) -> AssetDisposalOut:
    """If-Match on the asset; it moves along its life cycle to the disposed state."""
    row, record = await disposals.dispose_asset(
        session,
        subject,
        asset_id,
        body.model_dump(),
        expected_version=version,
        source=source_of(request),
    )
    set_etag(response, row.version)
    return AssetDisposalOut.of(record)


@router.get(
    "/{asset_id}/disposal",
    summary="An asset's disposal record",
    responses={404: {"model": ProblemDetail, "description": "asset_disposal_not_found"}},
)
async def get_disposal(
    asset_id: uuid.UUID, session: TenantSession, subject: View
) -> AssetDisposalOut:
    """For whoever may see the asset."""
    return AssetDisposalOut.of(await disposals.get_disposal(session, subject, asset_id))


# --- holders and holdings (REQ-AST-018, 019, 020) ---------------------------------------------


class AssetHolderIn(BaseModel):
    """Who holds the asset now: a person, a department or the asset it is fitted to."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["user", "department", "asset"]
    id: uuid.UUID


class AssetHoldingOut(BaseModel):
    """One holding of an asset, from when to when (`ended_at` null: the current one)."""

    asset_id: uuid.UUID
    holder_kind: str
    holder_id: uuid.UUID
    started_at: datetime
    ended_at: datetime | None
    source: str
    assigned_by: uuid.UUID | None

    @classmethod
    def of(cls, row: AssetAssignment) -> "AssetHoldingOut":
        """The API shape of a holding."""
        return cls(
            asset_id=row.asset_id,
            holder_kind=row.holder_kind,
            holder_id=row.holder_id,
            started_at=row.started_at,
            ended_at=row.ended_at,
            source=row.source,
            assigned_by=row.created_by,
        )


class HeldAssetOut(BaseModel):
    """An asset a person or department holds or held, with that holding."""

    asset: AssetOut
    holding: AssetHoldingOut


@router.put(
    "/{asset_id}/holder",
    summary="Give an asset to a person, a department or another asset",
    responses=WRITE,
    dependencies=[audited("asset.assigned", object_type="asset", object_param="asset_id")],
)
async def set_holder(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    asset_id: uuid.UUID,
    body: AssetHolderIn,
    session: TenantSession,
    subject: View,  # assets.manage, or a technician's ticket (D-157): the service decides
    version: ExpectedVersion,
    response: Response,
    request: Request,
) -> AssetOut:
    """If-Match. Ends the current holding and starts this one; never itself or a child."""
    row = await ownership.set_holder(
        session,
        subject,
        asset_id,
        ownership.Holder(body.kind, body.id),
        expected_version=version,
        source=source_of(request),
    )
    set_etag(response, row.version)
    return AssetOut.of(row, subject)


@router.delete(
    "/{asset_id}/holder",
    summary="Take an asset back from its holder",
    responses=WRITE,
    dependencies=[audited("asset.unassigned", object_type="asset", object_param="asset_id")],
)
async def clear_holder(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    asset_id: uuid.UUID,
    session: TenantSession,
    subject: View,  # assets.manage, or a technician's ticket (D-157): the service decides
    version: ExpectedVersion,
    response: Response,
    request: Request,
) -> AssetOut:
    """If-Match. The current holding ends; its history stays."""
    row = await ownership.set_holder(
        session, subject, asset_id, None, expected_version=version, source=source_of(request)
    )
    set_etag(response, row.version)
    return AssetOut.of(row, subject)


@router.get("/{asset_id}/holdings", summary="Who held an asset, and when")
async def asset_holdings(
    asset_id: uuid.UUID, session: TenantSession, subject: View
) -> list[AssetHoldingOut]:
    """Newest first; the open one is the current holder (REQ-AST-019 AC1)."""
    return [AssetHoldingOut.of(r) for r in await ownership.holdings(session, subject, asset_id)]


# --- relationships (REQ-AST-027) -----------------------------------------------------------------


class AssetLinkIn(BaseModel):
    """Link this asset to another (stored once, shown from both ends)."""

    model_config = ConfigDict(extra="forbid")

    to_asset_id: uuid.UUID
    kind: Literal["connected_to", "depends_on", "runs_on", "backs_up"]


class AssetLinkOut(BaseModel):
    """A link as this asset sees it: `outgoing` false means the other asset points here."""

    id: uuid.UUID
    kind: str
    outgoing: bool
    other: AssetOut


@router.post(
    "/{asset_id}/links",
    summary="Link an asset to another",
    status_code=status.HTTP_201_CREATED,
    response_model=AssetLinkOut,
    responses={
        **WRITE,
        409: {"model": ProblemDetail, "description": "asset_link_exists"},
    },
    dependencies=[audited("asset.linked", object_type="asset", object_param="asset_id")],
)
async def add_link(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    asset_id: uuid.UUID,
    body: AssetLinkIn,
    session: TenantSession,
    subject: Manage,
    idempotency: Idempotency,
    request: Request,
) -> Response:
    """History on both assets (AC1). Idempotency-Key."""

    async def run() -> Created:
        link = await relationships.add_link(
            session, subject, asset_id, body.to_asset_id, body.kind, source=source_of(request)
        )
        other = await service.get_asset(session, subject, body.to_asset_id)
        out = AssetOut.of(other, subject)
        return Created(body=AssetLinkOut(id=link.id, kind=link.kind, outgoing=True, other=out))

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.get("/{asset_id}/links", summary="An asset's links, from both ends")
async def asset_links(
    asset_id: uuid.UUID, session: TenantSession, subject: View
) -> list[AssetLinkOut]:
    """Only links to assets you may see."""
    return [
        AssetLinkOut(
            id=link.relationship.id,
            kind=link.relationship.kind,
            outgoing=link.outgoing,
            other=AssetOut.of(link.other, subject),
        )
        for link in await relationships.links_of(session, subject, asset_id)
    ]


@router.delete(
    "/{asset_id}/links/{link_id}",
    summary="Remove a link between two assets",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"model": ProblemDetail, "description": "asset_link_not_found"}},
    dependencies=[audited("asset.unlinked", object_type="asset", object_param="asset_id")],
)
async def remove_link(
    asset_id: uuid.UUID,
    link_id: uuid.UUID,
    session: TenantSession,
    subject: Manage,
    request: Request,
) -> Response:
    """Kept, marked removed; history on both assets. 404 unless the link is this asset's."""
    await relationships.remove_link(session, subject, asset_id, link_id, source=source_of(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- linked records (WP-049b s4a, REQ-AST-044) ---------------------------------------------------


class AssetLinkedKindOut(BaseModel):
    """One kind's counters: still worked (open, paused, resolved and not closed) and total."""

    kind: str = Field(description="incident, service_request, problem, change or release")
    still_worked: int
    total: int


class AssetLinkedSummaryOut(BaseModel):
    """The panel's counters; `available` false while work items offer no links (panel hidden)."""

    available: bool
    kinds: list[AssetLinkedKindOut]


class AssetLinkedRecordOut(BaseModel):
    """A linked work item the caller may see."""

    id: uuid.UUID
    kind: str
    display_id: str
    subject: str
    status: str
    still_worked: bool
    updated_at: datetime


class AssetLinkedPageOut(BaseModel):
    """One page of one kind's linked records, newest first."""

    items: list[AssetLinkedRecordOut]
    next_cursor: str | None


@router.get("/{asset_id}/linked", summary="Counters of the work items linked to an asset")
async def linked_summary(
    asset_id: uuid.UUID, session: TenantSession, subject: View
) -> AssetLinkedSummaryOut:
    """Per kind, only the records you may see are counted (REQ-AST-044)."""
    found = await linked.linked_summary(session, subject, asset_id)
    return AssetLinkedSummaryOut(
        available=found.available,
        kinds=[
            AssetLinkedKindOut(kind=k.kind, still_worked=k.still_worked, total=k.total)
            for k in found.kinds
        ],
    )


@router.get(
    "/{asset_id}/linked/{kind}",
    summary="The work items of one kind linked to an asset",
    responses={404: {"model": ProblemDetail, "description": "linked_records_not_available"}},
)
async def linked_records(  # noqa: PLR0913, PLR0917 - FastAPI dependencies and paging
    asset_id: uuid.UUID,
    kind: str,
    session: TenantSession,
    subject: View,
    cursor: Annotated[str | None, Query(max_length=400)] = None,
    limit: Annotated[int, Query(ge=1, le=linked.PAGE_MAX)] = linked.PAGE_DEFAULT,
) -> AssetLinkedPageOut:
    """Newest first; only the records you may see."""
    rows, next_cursor = await linked.linked_page(
        session, subject, asset_id, kind, cursor=cursor, limit=limit
    )
    return AssetLinkedPageOut(
        items=[
            AssetLinkedRecordOut(
                id=r.id, kind=r.kind, display_id=r.display_id, subject=r.subject,
                status=r.status, still_worked=r.still_worked, updated_at=r.updated_at,
            )
            for r in rows
        ],
        next_cursor=next_cursor,
    )  # fmt: skip
