"""Consumables, minimum stock and bookings over HTTP, /api/v1/assets (WP-049b s1). No logic.

Registered before the asset record's routes, so `/assets/consumables` never reads as an asset
ID. Reading needs `assets.view`; stock changes and staff bookings `assets.manage`; minimum-stock
rules `config.assets` (or `settings.manage`); the portal's booking routes only a signed-in
person, and only while the tenant allows booking there. Creates take an Idempotency-Key, edits
If-Match. Quantities are exact decimals, sent and returned as strings.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission, require_signed_in
from app.core.database import TenantSession
from app.core.errors import PermissionDenied, ProblemDetail
from app.modules.assets.api.routes import LoanOut, _loan_out
from app.modules.assets.domain.consumables import is_expired
from app.modules.assets.infra.models import (
    AssetBooking,
    AssetConsumableBatch,
    AssetConsumableMovement,
    AssetConsumableStock,
    AssetStockRule,
)
from app.modules.assets.service import bookings, consumables
from app.modules.assets.service.catalogue import CONFIGURE_ANY, MANAGE, VIEW
from app.modules.audit import audited
from app.modules.identity_access import Subject
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.ratelimit import rate_limit
from app.shared.clock import system_clock
from app.shared.history import source_of

router = APIRouter(
    prefix="/assets",
    tags=["assets"],
    dependencies=[Depends(rate_limit("assets"))],
    responses={
        401: {"model": ProblemDetail, "description": "Not signed in."},
        403: {"model": ProblemDetail, "description": "Missing permission or licence feature."},
    },
)
WRITE: dict[int | str, dict[str, Any]] = {
    404: {"model": ProblemDetail, "description": "No such item."},
    409: {"model": ProblemDetail, "description": "version_conflict, or the stock is short."},
}

View = Annotated[Subject, Depends(require_permission(VIEW))]
Manage = Annotated[Subject, Depends(require_permission(MANAGE))]
Configure = Annotated[Subject, Depends(require_permission(*CONFIGURE_ANY))]
SignedIn = Annotated[Subject, Depends(require_signed_in())]
Quantity = Annotated[Decimal, Field(description="Exact; up to three decimal places.")]
Comment = Annotated[str | None, Field(default=None, max_length=2000)]


# --- consumables (REQ-AST-033) ---------------------------------------------------------------


class AssetStockOut(BaseModel):
    """A site's stock of a consumable; `low`: at or below its minimum (alerted)."""

    id: uuid.UUID
    site_id: uuid.UUID | None
    location: str | None
    quantity: Decimal
    minimum: Decimal | None = Field(description="The minimum that applies here, if a rule does.")
    low: bool
    version: int


class AssetConsumableOut(BaseModel):
    """A consumable kept in stock, with its stock per site."""

    id: uuid.UUID
    product_id: uuid.UUID
    product_name: str
    product_type_id: uuid.UUID
    batch_tracked: bool = Field(description="Chosen when it was made; never switched.")
    barcode: str | None
    vendor_id: uuid.UUID | None
    unit_cost: Decimal | None = Field(description="In the base currency.")
    comment: str | None
    total: Decimal = Field(description="Every site's stock together.")
    stocks: list[AssetStockOut]
    version: int


class AssetBatchOut(BaseModel):
    """A lot at one site; `expired` once its expiry date has passed (033 AC2)."""

    id: uuid.UUID
    stock_id: uuid.UUID
    site_id: uuid.UUID | None
    lot_number: str
    reference: str | None
    manufactured_on: date | None
    expires_on: date | None
    quantity: Decimal
    expired: bool


class AssetConsumableDetailOut(AssetConsumableOut):
    """One consumable with its lots."""

    batches: list[AssetBatchOut]


class AssetConsumableIn(BaseModel):
    """A consumable product to keep in stock; batch tracking is chosen now, for good."""

    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID
    batch_tracked: bool
    barcode: str | None = Field(default=None, max_length=120)
    vendor_id: uuid.UUID | None = None
    unit_cost: Decimal | None = None
    comment: Comment


class AssetConsumablePatch(BaseModel):
    """Details to change; `batch_tracked` may only be sent unchanged (AC3)."""

    model_config = ConfigDict(extra="forbid")

    batch_tracked: bool | None = None
    barcode: str | None = Field(default=None, max_length=120)
    vendor_id: uuid.UUID | None = None
    unit_cost: Decimal | None = None
    comment: Comment


async def _stocks(
    session: TenantSession, stocks: list[AssetConsumableStock], product_id: uuid.UUID
) -> list[AssetStockOut]:
    minimums = await consumables.minimums(session, stocks, product_id)
    return [
        AssetStockOut(
            id=s.id,
            site_id=s.site_id,
            location=s.location,
            quantity=s.quantity,
            minimum=minimums.get(s.id),
            low=s.low_alerted_at is not None,
            version=s.version,
        )
        for s in stocks
    ]


async def _out(session: TenantSession, view: consumables.ConsumableView) -> AssetConsumableOut:
    row = view.row
    return AssetConsumableOut(
        id=row.id,
        product_id=row.product_id,
        product_name=view.product_name,
        product_type_id=view.product_type_id,
        batch_tracked=row.batch_tracked,
        barcode=row.barcode,
        vendor_id=row.vendor_id,
        unit_cost=row.unit_cost,
        comment=row.comment,
        total=sum((s.quantity for s in view.stocks), Decimal(0)),
        stocks=await _stocks(session, view.stocks, row.product_id),
        version=row.version,
    )


def _batch_out(
    row: AssetConsumableBatch, sites: dict[uuid.UUID, uuid.UUID | None]
) -> AssetBatchOut:
    return AssetBatchOut(
        id=row.id,
        stock_id=row.stock_id,
        site_id=sites.get(row.stock_id),
        lot_number=row.lot_number,
        reference=row.reference,
        manufactured_on=row.manufactured_on,
        expires_on=row.expires_on,
        quantity=row.quantity,
        expired=is_expired(row.expires_on, system_clock.now().date()),
    )


async def _detail(
    session: TenantSession, subject: Subject, consumable_id: uuid.UUID
) -> AssetConsumableDetailOut:
    view = await consumables.consumable_view(session, subject, consumable_id)
    base = await _out(session, view)
    sites = {s.id: s.site_id for s in view.stocks}
    lots = await consumables.batches_of(session, subject, consumable_id)
    return AssetConsumableDetailOut(
        **base.model_dump(), batches=[_batch_out(b, sites) for b in lots]
    )


@router.get("/consumables", summary="Consumables kept in stock")
async def list_consumables(
    session: TenantSession,
    subject: View,
    search: Annotated[str | None, Query(max_length=200, description="Part of the name.")] = None,
    site_id: Annotated[uuid.UUID | None, Query(description="With stock at this site.")] = None,
) -> list[AssetConsumableOut]:
    """By product name, each with its stock per site and the minimum that applies there."""
    views = await consumables.list_consumables(session, subject, search=search, site_id=site_id)
    return [await _out(session, v) for v in views]


@router.post(
    "/consumables",
    summary="Keep a consumable product in stock",
    status_code=status.HTTP_201_CREATED,
    response_model=AssetConsumableDetailOut,
    responses={409: {"model": ProblemDetail, "description": "asset_consumable_exists"}},
    dependencies=[audited("asset_consumable.created", object_type="asset_consumable")],
)
async def create_consumable(
    body: AssetConsumableIn, session: TenantSession, subject: Manage, idempotency: Idempotency
) -> Response:
    """Idempotency-Key. The product's type must be a consumable one."""

    async def run() -> Created:
        row = await consumables.create_consumable(session, subject, body.model_dump())
        return Created(body=await _detail(session, subject, row.id))

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.get("/consumables/{consumable_id}", summary="One consumable, its stock and lots")
async def get_consumable(
    consumable_id: uuid.UUID, session: TenantSession, subject: View, response: Response
) -> AssetConsumableDetailOut:
    """With its ETag for If-Match."""
    found = await _detail(session, subject, consumable_id)
    set_etag(response, found.version)
    return found


@router.patch(
    "/consumables/{consumable_id}",
    summary="Change a consumable",
    responses={
        **WRITE,
        409: {
            "model": ProblemDetail,
            "description": "version_conflict, asset_consumable_batch_tracking_fixed",
        },
    },
    dependencies=[
        audited(
            "asset_consumable.updated", object_type="asset_consumable", object_param="consumable_id"
        )
    ],
)
async def patch_consumable(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    consumable_id: uuid.UUID,
    body: AssetConsumablePatch,
    session: TenantSession,
    subject: Manage,
    version: ExpectedVersion,
    response: Response,
) -> AssetConsumableDetailOut:
    """If-Match. Switching batch tracking is refused with the reason (AC3)."""
    await consumables.update_consumable(
        session,
        subject,
        consumable_id,
        body.model_dump(include=body.model_fields_set),
        expected_version=version,
    )
    found = await _detail(session, subject, consumable_id)
    set_etag(response, found.version)
    return found


@router.delete(
    "/consumables/{consumable_id}",
    summary="Stop keeping a consumable",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WRITE,
    dependencies=[
        audited(
            "asset_consumable.deleted", object_type="asset_consumable", object_param="consumable_id"
        )
    ],
)
async def delete_consumable(
    consumable_id: uuid.UUID, session: TenantSession, subject: Manage, version: ExpectedVersion
) -> Response:
    """If-Match; refused while any site holds some (the ledger stays)."""
    await consumables.delete_consumable(session, subject, consumable_id, expected_version=version)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- stock movements (REQ-AST-033, 034) -------------------------------------------------------


class AssetMovementOut(BaseModel):
    """One ledger line: what moved, by how much, the balance after, to or from whom, why."""

    id: uuid.UUID
    consumable_id: uuid.UUID
    stock_id: uuid.UUID
    batch_id: uuid.UUID | None
    kind: Literal["receive", "allocate", "adjust", "return"]
    quantity: Decimal = Field(description="Signed: an allocation is negative.")
    balance_after: Decimal
    happened_on: date
    recipient_kind: Literal["user", "department", "asset"] | None
    recipient_id: uuid.UUID | None
    work_item_id: uuid.UUID | None = Field(description="The request it was allocated from.")
    unit_cost: Decimal | None
    comment: str | None
    created_at: datetime
    created_by: uuid.UUID | None


def _movement(row: AssetConsumableMovement) -> AssetMovementOut:
    return AssetMovementOut(
        id=row.id,
        consumable_id=row.consumable_id,
        stock_id=row.stock_id,
        batch_id=row.batch_id,
        kind=cast("Literal['receive', 'allocate', 'adjust', 'return']", row.kind),  # 0130's check
        quantity=row.quantity,
        balance_after=row.balance_after,
        happened_on=row.happened_on,
        recipient_kind=cast("Literal['user', 'department', 'asset'] | None", row.recipient_kind),
        recipient_id=row.recipient_id,
        work_item_id=row.work_item_id,
        unit_cost=row.unit_cost,
        comment=row.comment,
        created_at=row.created_at,
        created_by=row.created_by,
    )


class AssetBatchIn(BaseModel):
    """The lot a receipt goes into (batch-tracked consumables only)."""

    model_config = ConfigDict(extra="forbid")

    lot_number: str = Field(min_length=1, max_length=120)
    reference: str | None = Field(default=None, max_length=120)
    manufactured_on: date | None = None
    expires_on: date | None = None


class AssetReceiptIn(BaseModel):
    """Stock arrived at a site (no site: kept centrally)."""

    model_config = ConfigDict(extra="forbid")

    site_id: uuid.UUID | None = None
    quantity: Quantity
    batch: AssetBatchIn | None = None
    location: str | None = Field(default=None, max_length=200)
    unit_cost: Decimal | None = None
    happened_on: date | None = None
    comment: Comment


class AssetAllocationIn(BaseModel):
    """Give some to a person, a department or an asset, maybe for a request."""

    model_config = ConfigDict(extra="forbid")

    stock_id: uuid.UUID = Field(description="The site's stock it comes from.")
    quantity: Quantity
    recipient_kind: Literal["user", "department", "asset"]
    recipient_id: uuid.UUID
    work_item_id: uuid.UUID | None = Field(default=None, description="The request it is for.")
    batch_id: uuid.UUID | None = None
    happened_on: date | None = None
    comment: Comment


class AssetAdjustmentIn(BaseModel):
    """A count or a loss, with the reason: up or down (never below zero)."""

    model_config = ConfigDict(extra="forbid")

    stock_id: uuid.UUID
    change: Annotated[Decimal, Field(description="Signed; never zero.")]
    batch_id: uuid.UUID | None = None
    comment: str = Field(max_length=2000)


class AssetStockReturnIn(BaseModel):
    """Unused stock comes back, maybe from whom it was given to."""

    model_config = ConfigDict(extra="forbid")

    stock_id: uuid.UUID
    quantity: Quantity
    recipient_kind: Literal["user", "department", "asset"] | None = None
    recipient_id: uuid.UUID | None = None
    work_item_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    comment: Comment


def _recipient(kind: str | None, recipient_id: uuid.UUID | None) -> consumables.Recipient | None:
    if kind is None or recipient_id is None:
        return None
    return consumables.Recipient(kind, recipient_id)


SHORT: dict[int | str, dict[str, Any]] = {
    409: {"model": ProblemDetail, "description": "asset_stock_short, asset_stock_ran_out"}
}


@router.post(
    "/consumables/{consumable_id}/receipts",
    summary="Add stock as it arrives",
    status_code=status.HTTP_201_CREATED,
    response_model=AssetMovementOut,
    dependencies=[
        audited(
            "asset_consumable.received", object_type="asset_consumable",
            object_param="consumable_id",
        )
    ],
)  # fmt: skip
async def receive(
    consumable_id: uuid.UUID,
    body: AssetReceiptIn,
    session: TenantSession,
    subject: Manage,
    idempotency: Idempotency,
) -> Response:
    """Idempotency-Key. Only that site's stock rises (033 AC1); a lot for batch-tracked ones."""

    async def run() -> Created:
        lot = None
        if body.batch is not None:
            lot = consumables.BatchIn(
                body.batch.lot_number, body.batch.reference, body.batch.manufactured_on,
                body.batch.expires_on,
            )  # fmt: skip
        line = await consumables.receive(
            session, subject, consumable_id, site_id=body.site_id, quantity=body.quantity,
            batch=lot, location=body.location, unit_cost=body.unit_cost,
            happened_on=body.happened_on, comment=body.comment,
        )  # fmt: skip
        return Created(body=_movement(line))

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.post(
    "/consumables/{consumable_id}/allocations",
    summary="Allocate stock to a person, a department or an asset",
    status_code=status.HTTP_201_CREATED,
    response_model=AssetMovementOut,
    responses=SHORT,
    dependencies=[
        audited(
            "asset_consumable.allocated", object_type="asset_consumable",
            object_param="consumable_id",
        )
    ],
)  # fmt: skip
async def allocate(
    consumable_id: uuid.UUID,
    body: AssetAllocationIn,
    session: TenantSession,
    subject: Manage,
    idempotency: Idempotency,
) -> Response:
    """Idempotency-Key. Never more than there is: 409 with the amount available (034)."""

    async def run() -> Created:
        line = await consumables.allocate(
            session, subject, consumable_id, stock_id=body.stock_id, quantity=body.quantity,
            recipient=consumables.Recipient(body.recipient_kind, body.recipient_id),
            work_item_id=body.work_item_id, batch_id=body.batch_id,
            happened_on=body.happened_on, comment=body.comment,
        )  # fmt: skip
        return Created(body=_movement(line))

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.post(
    "/consumables/{consumable_id}/adjustments",
    summary="Correct the stock, with the reason",
    status_code=status.HTTP_201_CREATED,
    response_model=AssetMovementOut,
    responses=SHORT,
    dependencies=[
        audited(
            "asset_consumable.adjusted", object_type="asset_consumable",
            object_param="consumable_id",
        )
    ],
)  # fmt: skip
async def adjust(
    consumable_id: uuid.UUID,
    body: AssetAdjustmentIn,
    session: TenantSession,
    subject: Manage,
    idempotency: Idempotency,
) -> Response:
    """Idempotency-Key. Never below zero."""

    async def run() -> Created:
        line = await consumables.adjust(
            session, subject, consumable_id, stock_id=body.stock_id, change=body.change,
            batch_id=body.batch_id, comment=body.comment,
        )  # fmt: skip
        return Created(body=_movement(line))

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.post(
    "/consumables/{consumable_id}/returns",
    summary="Take unused stock back",
    status_code=status.HTTP_201_CREATED,
    response_model=AssetMovementOut,
    dependencies=[
        audited(
            "asset_consumable.returned", object_type="asset_consumable",
            object_param="consumable_id",
        )
    ],
)  # fmt: skip
async def return_stock(
    consumable_id: uuid.UUID,
    body: AssetStockReturnIn,
    session: TenantSession,
    subject: Manage,
    idempotency: Idempotency,
) -> Response:
    """Idempotency-Key."""

    async def run() -> Created:
        line = await consumables.return_stock(
            session, subject, consumable_id, stock_id=body.stock_id, quantity=body.quantity,
            recipient=_recipient(body.recipient_kind, body.recipient_id),
            work_item_id=body.work_item_id, batch_id=body.batch_id, comment=body.comment,
        )  # fmt: skip
        return Created(body=_movement(line))

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.get("/consumables/{consumable_id}/ledger", summary="A consumable's stock ledger")
async def consumable_ledger(
    consumable_id: uuid.UUID, session: TenantSession, subject: View
) -> list[AssetMovementOut]:
    """Newest first, 200 at most."""
    await consumables.get_consumable(session, subject, consumable_id)
    rows = await consumables.ledger(session, subject, consumable_id=consumable_id)
    return [_movement(r) for r in rows]


@router.get("/consumable-allocations", summary="What was allocated from a request")
async def request_allocations(
    session: TenantSession,
    subject: View,
    work_item_id: Annotated[uuid.UUID, Query(description="The request.")],
) -> list[AssetMovementOut]:
    """The request's side of REQ-AST-034 AC2: its allocations (and returns), newest first."""
    rows = await consumables.ledger(session, subject, work_item_id=work_item_id)
    return [_movement(r) for r in rows]


# --- minimum stock (REQ-AST-035) ----------------------------------------------------------------


class AssetStockRuleOut(BaseModel):
    """A minimum for a product type or a product, at a site or every site."""

    id: uuid.UUID
    product_type_id: uuid.UUID | None
    product_id: uuid.UUID | None
    site_id: uuid.UUID | None = Field(description="None: every site.")
    min_quantity: Decimal
    notify_user_ids: list[uuid.UUID]
    create_purchase_request: bool = Field(
        description="A draft purchase request when it alerts (with procurement, WP-054)."
    )
    reorder_quantity: Decimal | None
    version: int


class AssetStockRuleIn(BaseModel):
    """A minimum-stock rule: exactly one of product type or product."""

    model_config = ConfigDict(extra="forbid")

    product_type_id: uuid.UUID | None = None
    product_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    min_quantity: Decimal
    notify_user_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    create_purchase_request: bool = False
    reorder_quantity: Decimal | None = None


class AssetStockRulePatch(BaseModel):
    """What to change of a rule."""

    model_config = ConfigDict(extra="forbid")

    site_id: uuid.UUID | None = None
    min_quantity: Decimal | None = None
    notify_user_ids: list[uuid.UUID] | None = Field(default=None, max_length=50)
    create_purchase_request: bool | None = None
    reorder_quantity: Decimal | None = None


def _rule_out(row: AssetStockRule) -> AssetStockRuleOut:
    return AssetStockRuleOut(
        id=row.id,
        product_type_id=row.product_type_id,
        product_id=row.product_id,
        site_id=row.site_id,
        min_quantity=row.min_quantity,
        notify_user_ids=[uuid.UUID(str(p)) for p in row.notify_user_ids],
        create_purchase_request=row.create_purchase_request,
        reorder_quantity=row.reorder_quantity,
        version=row.version,
    )


@router.get("/stock-rules", summary="Minimum-stock rules")
async def list_stock_rules(session: TenantSession, subject: View) -> list[AssetStockRuleOut]:
    """Every rule, oldest first."""
    return [_rule_out(r) for r in await consumables.list_rules(session, subject)]


@router.post(
    "/stock-rules",
    summary="Add a minimum-stock rule",
    status_code=status.HTTP_201_CREATED,
    response_model=AssetStockRuleOut,
    responses={409: {"model": ProblemDetail, "description": "asset_stock_rule_exists"}},
    dependencies=[audited("asset_stock_rule.created", object_type="asset_stock_rule")],
)
async def create_stock_rule(
    body: AssetStockRuleIn, session: TenantSession, subject: Configure, idempotency: Idempotency
) -> Response:
    """Idempotency-Key. Stock already at or below it alerts at once (once)."""

    async def run() -> Created:
        row = await consumables.create_rule(session, subject, body.model_dump())
        return Created(body=_rule_out(row))

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.patch(
    "/stock-rules/{rule_id}",
    summary="Change a minimum-stock rule",
    responses=WRITE,
    dependencies=[
        audited("asset_stock_rule.updated", object_type="asset_stock_rule", object_param="rule_id")
    ],
)
async def patch_stock_rule(
    rule_id: uuid.UUID,
    body: AssetStockRulePatch,
    session: TenantSession,
    subject: Configure,
    version: ExpectedVersion,
) -> AssetStockRuleOut:
    """If-Match."""
    row = await consumables.update_rule(
        session,
        subject,
        rule_id,
        body.model_dump(include=body.model_fields_set),
        expected_version=version,
    )
    return _rule_out(row)


@router.delete(
    "/stock-rules/{rule_id}",
    summary="Remove a minimum-stock rule",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WRITE,
    dependencies=[
        audited("asset_stock_rule.deleted", object_type="asset_stock_rule", object_param="rule_id")
    ],
)
async def delete_stock_rule(
    rule_id: uuid.UUID, session: TenantSession, subject: Configure, version: ExpectedVersion
) -> Response:
    """If-Match."""
    await consumables.delete_rule(session, subject, rule_id, expected_version=version)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- bookings (REQ-AST-032) ---------------------------------------------------------------------


class AssetBookingOut(BaseModel):
    """One asset booked ahead for a person (and their department)."""

    id: uuid.UUID
    asset_id: uuid.UUID
    borrower_id: uuid.UUID
    department_id: uuid.UUID | None
    starts_at: datetime
    ends_at: datetime
    status: Literal["booked", "handed_over", "cancelled"]
    loan_id: uuid.UUID | None
    channel: Literal["console", "portal"]
    comment: str | None
    version: int


def _booking_out(row: AssetBooking) -> AssetBookingOut:
    return AssetBookingOut(
        id=row.id,
        asset_id=row.asset_id,
        borrower_id=row.borrower_id,
        department_id=row.department_id,
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        status=cast("Literal['booked', 'handed_over', 'cancelled']", row.status),  # 0130's check
        loan_id=row.loan_id,
        channel=cast("Literal['console', 'portal']", row.channel),  # 0130's check
        comment=row.comment,
        version=row.version,
    )


class AssetBookingIn(BaseModel):
    """Book one loanable asset for a period."""

    model_config = ConfigDict(extra="forbid")

    asset_id: uuid.UUID
    borrower_id: uuid.UUID
    department_id: uuid.UUID | None = None
    starts_at: datetime
    ends_at: datetime
    comment: Comment


TAKEN: dict[int | str, dict[str, Any]] = {
    409: {
        "model": ProblemDetail,
        "description": "asset_booking_taken (params.next_free), asset_not_bookable",
    }
}


@router.get("/bookings", summary="Bookings ahead: by asset, or by product and site")
async def list_bookings(  # noqa: PLR0913 - the calendar's filters
    *,
    session: TenantSession,
    subject: View,
    asset_id: uuid.UUID | None = None,
    product_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    start: Annotated[datetime | None, Query(alias="from")] = None,
    end: Annotated[datetime | None, Query(alias="to")] = None,
    include_closed: bool = False,
) -> list[AssetBookingOut]:
    """Live bookings (or every one, `include_closed`), earliest first, 200 at most."""
    rows = await bookings.list_bookings(
        session, subject, asset_id=asset_id, product_id=product_id, site_id=site_id,
        start=start, end=end, include_closed=include_closed,
    )  # fmt: skip
    return [_booking_out(r) for r in rows]


@router.post(
    "/bookings",
    summary="Book an asset ahead",
    status_code=status.HTTP_201_CREATED,
    response_model=AssetBookingOut,
    responses=TAKEN,
    dependencies=[audited("asset_booking.created", object_type="asset_booking")],
)
async def create_booking(
    body: AssetBookingIn, session: TenantSession, subject: Manage, idempotency: Idempotency
) -> Response:
    """Idempotency-Key. A taken period is refused with the next free day (AC1)."""

    async def run() -> Created:
        row = await bookings.create_booking(
            session, subject, asset_id=body.asset_id, borrower_id=body.borrower_id,
            department_id=body.department_id, starts_at=body.starts_at, ends_at=body.ends_at,
            comment=body.comment,
        )  # fmt: skip
        return Created(body=_booking_out(row))

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.post(
    "/bookings/{booking_id}/cancel",
    summary="Cancel a booking",
    responses=WRITE,
    dependencies=[
        audited("asset_booking.cancelled", object_type="asset_booking", object_param="booking_id")
    ],
)
async def cancel_booking(
    booking_id: uuid.UUID, session: TenantSession, subject: Manage, version: ExpectedVersion
) -> AssetBookingOut:
    """If-Match; only one not yet handed over."""
    row = await bookings.cancel_booking(session, subject, booking_id, expected_version=version)
    return _booking_out(row)


class AssetHandoverOut(BaseModel):
    """The booking, handed over, and the loan it became."""

    booking: AssetBookingOut
    loan: LoanOut


@router.post(
    "/bookings/{booking_id}/handover",
    summary="Hand a booked asset over: the booking becomes a loan",
    responses=WRITE,
    dependencies=[
        audited("asset_booking.handed_over", object_type="asset_booking", object_param="booking_id")
    ],
)
async def hand_over(
    booking_id: uuid.UUID,
    session: TenantSession,
    subject: Manage,
    version: ExpectedVersion,
    request: Request,
) -> AssetHandoverOut:
    """If-Match. The loan has the booking's dates (AC2)."""
    row, loan = await bookings.hand_over(
        session, subject, booking_id, expected_version=version, source=source_of(request)
    )
    return AssetHandoverOut(booking=_booking_out(row), loan=await _loan_out(session, loan))


class AssetHeldOut(BaseModel):
    """A period an asset is already held: by a booking or its loan."""

    starts_at: datetime
    ends_at: datetime


class AssetAvailabilityOut(BaseModel):
    """A bookable asset and the periods it is already held (never by whom)."""

    id: uuid.UUID
    tag: str | None
    name: str
    product_id: uuid.UUID
    site_id: uuid.UUID | None
    held: list[AssetHeldOut]


def _availability(found: list[bookings.Availability]) -> list[AssetAvailabilityOut]:
    return [
        AssetAvailabilityOut(
            id=a.asset.id,
            tag=a.asset.tag,
            name=a.asset.name,
            product_id=a.asset.product_id,
            site_id=a.asset.site_id,
            held=[AssetHeldOut(starts_at=p.starts_at, ends_at=p.due_at) for p in a.held],
        )
        for a in found
    ]


@router.get("/availability", summary="Bookable assets by product and site, and when they're held")
async def availability(
    session: TenantSession,
    subject: View,
    product_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> list[AssetAvailabilityOut]:
    """Loanable assets not retired or disposed, 50 at most (the booking calendar)."""
    del subject
    found = await bookings.availability(session, product_id=product_id, site_id=site_id, text_=q)
    return _availability(found)


# --- the portal's bookings (REQ-AST-032 AC3) ------------------------------------------------------


class MyAssetBookingsOut(BaseModel):
    """Whether I may book here, and my live bookings."""

    enabled: bool = Field(description="The organisation allows booking from the portal.")
    bookings: list[AssetBookingOut]
    assets: dict[str, str] = Field(description="Each booked asset's tag or name, by ID.")


class MyAssetBookingIn(BaseModel):
    """Book one loanable asset for myself."""

    model_config = ConfigDict(extra="forbid")

    asset_id: uuid.UUID
    starts_at: datetime
    ends_at: datetime
    comment: Comment


@router.get("/my-bookings", summary="My bookings ahead (the portal)")
async def my_bookings(session: TenantSession, subject: SignedIn) -> MyAssetBookingsOut:
    """Live, earliest first; `enabled` false when the organisation has not allowed it."""
    enabled = await bookings.portal_booking_on(session)
    rows = await bookings.my_bookings(session, subject)
    names = await bookings.asset_names(session, [r.asset_id for r in rows])
    return MyAssetBookingsOut(
        enabled=enabled,
        bookings=[_booking_out(r) for r in rows],
        assets={str(k): v for k, v in names.items()},
    )


async def _portal_on(session: TenantSession) -> None:
    if not await bookings.portal_booking_on(session):
        raise PermissionDenied(code="asset_portal_booking_off")


@router.get("/bookable", summary="Assets I may book (the portal)")
async def bookable(
    session: TenantSession,
    subject: SignedIn,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> list[AssetAvailabilityOut]:
    """Only while the organisation allows booking from the portal (403 otherwise)."""
    del subject
    await _portal_on(session)
    found = await bookings.availability(session, product_id=None, site_id=None, text_=q)
    return _availability(found)


@router.post(
    "/my-bookings",
    summary="Book an asset for myself (the portal)",
    status_code=status.HTTP_201_CREATED,
    response_model=AssetBookingOut,
    responses=TAKEN,
)
async def book_for_me(
    body: MyAssetBookingIn, session: TenantSession, subject: SignedIn, idempotency: Idempotency
) -> Response:
    """Idempotency-Key. Only while the organisation allows it; a taken period is refused."""

    async def run() -> Created:
        row = await bookings.create_booking(
            session, subject, asset_id=body.asset_id, borrower_id=subject.user_id,
            starts_at=body.starts_at, ends_at=body.ends_at, comment=body.comment,
            channel="portal",
        )  # fmt: skip
        return Created(body=_booking_out(row))

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.post(
    "/my-bookings/{booking_id}/cancel", summary="Cancel my booking (the portal)", responses=WRITE
)
async def cancel_my_booking(
    booking_id: uuid.UUID, session: TenantSession, subject: SignedIn, version: ExpectedVersion
) -> AssetBookingOut:
    """If-Match; my own only."""
    row = await bookings.cancel_booking(
        session, subject, booking_id, expected_version=version, own_only=True
    )
    return _booking_out(row)
