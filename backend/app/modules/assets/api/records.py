"""The asset record over HTTP, /api/v1/assets (WP-049a session 2). No business logic.

Registered after the catalogue routes (assets/api/routes.py), so `/assets/states` and friends
match first and `/assets/{asset_id}` only takes an ID. Reading needs `assets.view`, writing
`assets.manage`, each within its scope. Writes use If-Match; creates take an Idempotency-Key.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.core.errors import ProblemDetail
from app.modules import metadata
from app.modules.assets.domain.assets import IDENTIFIER_MAX, LOCATION_MAX, NAME_MAX
from app.modules.assets.infra.models import Asset, AssetAssignment, AssetDisposal
from app.modules.assets.service import assets as service
from app.modules.assets.service import bulk, disposals, moves, ownership, relationships
from app.modules.assets.service.catalogue import TEXT_MAX
from app.modules.audit import RequestFacts, audited
from app.modules.audit import record as record_audit
from app.modules.identity_access import Subject, user_names
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.filters import FilterField
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.listing import ListQuery, Page, list_query, paginate
from app.shared.api.ratelimit import rate_limit
from app.shared.history import history_page, source_of
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
            service.ASSET_FIELDS, extra_parameters=frozenset({"search"}), fields_for=_custom_filters
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
    purchase_price: Decimal | None
    purchase_tax: Decimal | None
    purchase_total: Decimal | None = Field(description="Price plus tax (D-141), worked out.")
    currency: str | None
    acquired_on: date | None
    warranty_expires_on: date | None
    expires_on: date | None
    description: str | None
    custom: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    version: int

    @classmethod
    def of(cls, row: Asset) -> "AssetOut":
        """From the row."""
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
            purchase_price=row.purchase_price,
            purchase_tax=row.purchase_tax,
            purchase_total=service.purchase_total(row),
            currency=row.currency,
            acquired_on=row.acquired_on,
            warranty_expires_on=row.warranty_expires_on,
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


class AssetHistoryOut(BaseModel):
    """A page of an asset's history, newest first."""

    items: list[AssetHistoryEntryOut]
    next_cursor: str | None


Search = Annotated[
    str | None,
    Query(max_length=200, description="Words or an identifier: name, tag, serials, barcode."),
]


async def _page(
    session: AsyncSession, query: ListQuery, subject: Subject, search: str | None, *, trash: bool
) -> Page[AssetOut]:
    statement = service.staff_rows(subject, trash=trash)
    search = (search or "").strip()
    if search:
        words = await ENGINE.match(session, TEXT, search)
        if words is None:
            return Page[AssetOut](items=[], next_cursor=None, has_more=False, estimated_total=0)
        statement = statement.where(words.predicate)
    page = await paginate(session, statement, query)
    return Page[AssetOut](
        items=[AssetOut.of(row) for row in page.rows],
        next_cursor=page.next_cursor,
        has_more=page.has_more,
        estimated_total=page.estimated_total,
    )


@router.get("", summary="Assets")
async def list_assets(
    session: TenantSession, query: AssetsQuery, subject: View, search: Search = None
) -> Page[AssetOut]:
    """The assets you may see: filtered, searched and paged.

    Filters: the DSL, `custom.<key>` included. `search`: name, tag, serials, barcode and custom
    text. Newest change first unless sorted.
    """
    return await _page(session, query, subject, search, trash=False)


@router.get("/trash", summary="Assets in the trash")
async def list_trash(
    session: TenantSession, query: AssetsQuery, subject: Manage, search: Search = None
) -> Page[AssetOut]:
    """The trashed assets you may restore."""
    return await _page(session, query, subject, search, trash=True)


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
        return Created(body=AssetOut.of(row), headers={"ETag": f'"{row.version}"'})

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.get(
    "/{asset_id}",
    summary="Get an asset",
    responses={404: {"model": ProblemDetail, "description": "asset_not_found"}},
)
async def get_asset(
    asset_id: uuid.UUID, session: TenantSession, subject: View, response: Response
) -> AssetOut:
    """One asset you may see."""
    row = await service.get_asset(session, subject, asset_id)
    set_etag(response, row.version)
    return AssetOut.of(row)


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
    subject: Manage,
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
    return AssetOut.of(row)


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
    responses={404: {"model": ProblemDetail, "description": "asset_not_found"}},
    dependencies=[audited("asset.restored", object_type="asset", object_param="asset_id")],
)
async def restore_asset(
    asset_id: uuid.UUID,
    session: TenantSession,
    subject: Manage,
    request: Request,
    response: Response,
) -> AssetOut:
    """Back from the trash; an IT asset needs a free slot again."""
    row = await service.restore_asset(session, subject, asset_id, source=source_of(request))
    set_etag(response, row.version)
    return AssetOut.of(row)


@router.get(
    "/{asset_id}/history",
    summary="An asset's history",
    responses={404: {"model": ProblemDetail, "description": "asset_not_found"}},
)
async def asset_history(
    asset_id: uuid.UUID,
    session: TenantSession,
    subject: View,
    cursor: Annotated[int | None, Query(ge=1, description="next_cursor of the last page")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> AssetHistoryOut:
    """Every save, newest first, with who, when, how (UI, API, rule ...) and what changed."""
    await service.get_asset(session, subject, asset_id)
    entries, next_version = await history_page(
        session, service.RECORD_TYPE, asset_id, before_version=cursor, limit=limit
    )
    names = await user_names(session, [e.actor_id for e in entries if e.actor_id])
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
                changes=[AssetChangeOut(field=c.field, old=c.old, new=c.new) for c in e.changes],
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
    subject: Manage,
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
    return AssetOut.of(row)


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
        return Created(body=AssetCopiesOut(items=[AssetOut.of(row) for row in made]))

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
    subject: Manage,
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
    return AssetOut.of(row)


@router.delete(
    "/{asset_id}/holder",
    summary="Take an asset back from its holder",
    responses=WRITE,
    dependencies=[audited("asset.unassigned", object_type="asset", object_param="asset_id")],
)
async def clear_holder(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    asset_id: uuid.UUID,
    session: TenantSession,
    subject: Manage,
    version: ExpectedVersion,
    response: Response,
    request: Request,
) -> AssetOut:
    """If-Match. The current holding ends; its history stays."""
    row = await ownership.set_holder(
        session, subject, asset_id, None, expected_version=version, source=source_of(request)
    )
    set_etag(response, row.version)
    return AssetOut.of(row)


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
        return Created(
            body=AssetLinkOut(id=link.id, kind=link.kind, outgoing=True, other=AssetOut.of(other))
        )

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
            other=AssetOut.of(link.other),
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
