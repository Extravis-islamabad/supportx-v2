"""Consumable stock, allocations and minimum stock (WP-049b s1; REQ-AST-033, 034, 035).

- **A consumable (033)** is a product whose type is of kind `consumable` (D-141), kept in stock
  with its barcode, vendor, unit cost (base currency) and comments. Whether it is tracked in
  batches is chosen when it is made; switching later is refused with the reason (AC3).
- **Stock** is a quantity per consumable and site (one row each, "no site" included). Receiving
  adds to that site's row only (AC1); a batch-tracked consumable receives into a lot with its
  manufacture and expiry dates, and an expired lot is flagged (AC2).
- **Allocations (034)** go to a person, a department or an asset, with a quantity and date, and
  optionally the request they were made from (an ID only, rule e). Stock falls with one
  `UPDATE ... SET quantity = quantity - n WHERE quantity >= n RETURNING`: of two people taking
  the last unit at the same moment, exactly one row update succeeds; the other is told stock ran
  out (AC3). Asking for more than there is is refused with the amount available (AC1). A CHECK
  keeps every row at zero or more as well.
- **The ledger** lists every receipt, allocation, adjustment and return, with who, when and why.
  It is append-only (the application role may not change or remove a line).
- **Minimum stock (035)** per product type or product, and per site or all sites; the most
  specific rule decides. When stock falls to or below it the rule's people hear of it once (the
  row's `low_alerted_at`, claimed by one conditional UPDATE); only after stock rises above it is
  the alert re-armed (AC1). The draft purchase request (AC2) is a port procurement fills in with
  WP-054; until then none is made.

Reading needs `assets.view`; stock changes need `assets.manage`; the rules are set-up
(`config.assets` or `settings.manage`). Every change writes its event to the outbox in the same
transaction.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy import ColumnElement, Select, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, PermissionDenied
from app.core.logging import get_logger
from app.modules.assets.domain.catalogue import AssetTypeKind, Problem, amount_problems
from app.modules.assets.domain.consumables import (
    COMMENT_MAX,
    LOT_MAX,
    QUANTITY_MAX,
    QUANTITY_PLACES,
    RECIPIENT_KINDS,
    MovementKind,
    RuleCandidate,
    low_stock_step,
    pick_rule,
    quantity_problem,
)
from app.modules.assets.events import (
    ConsumableAction,
    ConsumableChanged,
    StockLow,
    StockMoved,
    StockRuleChanged,
)
from app.modules.assets.infra.models import (
    AssetConsumable,
    AssetConsumableBatch,
    AssetConsumableMovement,
    AssetConsumableStock,
    AssetProduct,
    AssetProductType,
    AssetStockRule,
)
from app.modules.assets.service.assets import (
    MANAGE,
    VIEW,
    _refuse,
    _require,
    _tenant,
    _visible,
)
from app.modules.assets.service.catalogue import require_configure
from app.modules.identity_access import Subject, active_user_ids
from app.modules.organization import existing_departments, existing_unit_ids
from app.modules.procurement import vendor_problem
from app.shared.clock import system_clock
from app.shared.events import record_event
from app.shared.history.conflicts import stale_version
from app.shared.ids import new_id

log = get_logger(__name__)

CONSUMABLES_MAX = 500
LEDGER_MAX = 200
NOTIFY_MAX = 50
BARCODE_MAX = 120
LOCATION_MAX = 200
RECORD_TYPE = "asset_consumable"
RULE_RECORD_TYPE = "asset_stock_rule"


# --- the draft purchase request port (REQ-AST-035 AC2) ------------------------------------------


class DraftPurchaseRequests(Protocol):
    """Makes a draft purchase request for a low stock (procurement, WP-054).

    Called in the alert's transaction; returns the request's ID, or None when procurement is not
    licensed. Procurement links the request to the rule and stock it names.
    """

    async def __call__(  # noqa: PLR0913 - what, where, how many, and the alert it answers
        self,
        session: AsyncSession,
        *,
        product_id: uuid.UUID,
        site_id: uuid.UUID | None,
        quantity: Decimal,
        rule_id: uuid.UUID,
        stock_id: uuid.UUID,
    ) -> uuid.UUID | None:
        """The draft request's ID, or None when procurement is not licensed."""
        ...


_DRAFT_REQUESTS: list[DraftPurchaseRequests] = []


def register_draft_purchase_requests(port: DraftPurchaseRequests) -> None:
    """Procurement registers its maker here (WP-054). Idempotent: the last one wins."""
    _DRAFT_REQUESTS[:] = [port]


def unregister_draft_purchase_requests() -> None:
    """Remove the maker (tests)."""
    _DRAFT_REQUESTS.clear()


# --- consumables ---------------------------------------------------------------------------------


async def _consumable_type(session: AsyncSession, product_id: uuid.UUID) -> AssetProduct | None:
    """The live product, if its type is a consumable one (D-141); None otherwise."""
    row = (
        await session.execute(
            select(AssetProduct, AssetProductType.kind)
            .join(AssetProductType, AssetProductType.id == AssetProduct.product_type_id)
            .where(AssetProduct.id == product_id, AssetProduct.deleted_at.is_(None))
        )
    ).first()
    if row is None or row.kind != AssetTypeKind.CONSUMABLE:
        return None
    product: AssetProduct = row[0]
    return product


def _text(name: str, raw: object, limit: int) -> tuple[str | None, list[Problem]]:
    value = " ".join(str(raw or "").split()) if name != "comment" else str(raw or "").strip()
    if len(value) > limit:
        return None, [Problem(name, "value_too_long", (("max", limit),))]
    return value or None, []


async def _clean(
    session: AsyncSession, values: Mapping[str, Any], current: AssetConsumable | None
) -> tuple[dict[str, Any], list[Problem]]:
    cleaned: dict[str, Any] = {}
    problems: list[Problem] = []
    for name, limit in (("barcode", BARCODE_MAX), ("comment", COMMENT_MAX)):
        if name in values:
            cleaned[name], found = _text(name, values[name], limit)
            problems += found
    if "unit_cost" in values:
        cost = None if values["unit_cost"] is None else Decimal(str(values["unit_cost"]))
        problems += amount_problems("unit_cost", cost)
        cleaned["unit_cost"] = cost
    if "vendor_id" in values:
        vendor = values["vendor_id"]
        if vendor is not None and (
            code := await vendor_problem(
                session, vendor, current=None if current is None else current.vendor_id
            )
        ):
            problems.append(Problem("vendor_id", code))
        cleaned["vendor_id"] = vendor
    return cleaned, problems


async def _changed(
    session: AsyncSession, row: AssetConsumable, action: ConsumableAction, fields: Sequence[str]
) -> None:
    await record_event(
        session,
        ConsumableChanged(consumable_id=row.id, action=action, changed_fields=sorted(fields)),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )


async def create_consumable(
    session: AsyncSession, subject: Subject, values: Mapping[str, Any]
) -> AssetConsumable:
    """Keep a consumable product in stock; `batch_tracked` is chosen now, for good (033)."""
    _require(subject, MANAGE)
    problems: list[Problem] = []
    product_id = values.get("product_id")
    if product_id is None:
        problems.append(Problem("product_id", "required"))
    elif await _consumable_type(session, product_id) is None:
        problems.append(Problem("product_id", "asset_product_not_consumable"))
    if not isinstance(values.get("batch_tracked"), bool):
        problems.append(Problem("batch_tracked", "required"))
    cleaned, found = await _clean(session, values, None)
    _refuse(problems + found)
    taken = await session.scalar(
        select(AssetConsumable.id).where(
            AssetConsumable.product_id == product_id, AssetConsumable.deleted_at.is_(None)
        )
    )
    if taken is not None:
        raise Conflict(code="asset_consumable_exists")
    row = AssetConsumable(
        id=new_id(),
        tenant_id=_tenant(session),
        created_by=subject.user_id,
        product_id=product_id,
        batch_tracked=values["batch_tracked"],
        **cleaned,
    )
    session.add(row)
    try:
        await session.flush()  # a racing create for the same product fails on the unique index
    except IntegrityError:
        raise Conflict(code="asset_consumable_exists") from None
    await _changed(session, row, "created", ["product_id", "batch_tracked", *cleaned])
    return row


async def _live(session: AsyncSession, consumable_id: uuid.UUID) -> AssetConsumable:
    row = await session.scalar(
        select(AssetConsumable).where(
            AssetConsumable.id == consumable_id, AssetConsumable.deleted_at.is_(None)
        )
    )
    if row is None:
        raise NotFound(code="asset_consumable_not_found")
    return row


async def get_consumable(
    session: AsyncSession, subject: Subject, consumable_id: uuid.UUID
) -> AssetConsumable:
    """One live consumable."""
    _require(subject, VIEW)
    return await _live(session, consumable_id)


async def update_consumable(
    session: AsyncSession,
    subject: Subject,
    consumable_id: uuid.UUID,
    values: Mapping[str, Any],
    *,
    expected_version: int,
) -> AssetConsumable:
    """Change its details (If-Match). Batch tracking stays as it was made (033 AC3)."""
    _require(subject, MANAGE)
    row = await _live(session, consumable_id)
    if row.version != expected_version:
        raise await stale_version(
            session, row, expected_version=expected_version, record_type=RECORD_TYPE,
            record_id=row.id,
        )  # fmt: skip
    if "batch_tracked" in values and values["batch_tracked"] != row.batch_tracked:
        raise Conflict(
            code="asset_consumable_batch_tracking_fixed",
            params={"batch_tracked": str(row.batch_tracked).lower()},
        )
    cleaned, problems = await _clean(session, values, row)
    _refuse(problems)
    changed = [k for k, v in cleaned.items() if getattr(row, k) != v]
    if not changed:
        return row
    for key in changed:
        setattr(row, key, cleaned[key])
    row.version += 1
    row.updated_by = subject.user_id
    await session.flush()
    await _changed(session, row, "updated", changed)
    return row


async def delete_consumable(
    session: AsyncSession, subject: Subject, consumable_id: uuid.UUID, *, expected_version: int
) -> None:
    """Stop keeping it; refused while any site still holds some. The ledger stays."""
    _require(subject, MANAGE)
    row = await _live(session, consumable_id)
    if row.version != expected_version:
        raise await stale_version(
            session, row, expected_version=expected_version, record_type=RECORD_TYPE,
            record_id=row.id,
        )  # fmt: skip
    held = await session.scalar(
        select(func.coalesce(func.sum(AssetConsumableStock.quantity), 0)).where(
            AssetConsumableStock.consumable_id == row.id
        )
    )
    if Decimal(held or 0) > 0:
        raise Conflict(code="asset_consumable_has_stock", params={"quantity": str(held)})
    row.deleted_at = system_clock.now()
    row.version += 1
    row.updated_by = subject.user_id
    await session.flush()
    await _changed(session, row, "deleted", ["deleted"])


@dataclass(frozen=True, slots=True)
class ConsumableView:
    """A consumable with its product and stock, as the lists show it."""

    row: AssetConsumable
    product_name: str
    product_type_id: uuid.UUID
    stocks: list[AssetConsumableStock]


async def _views(
    session: AsyncSession, query: Select[AssetConsumable, str, uuid.UUID]
) -> list[ConsumableView]:
    rows = (await session.execute(query)).all()
    ids = [r[0].id for r in rows]
    stocks: dict[uuid.UUID, list[AssetConsumableStock]] = {i: [] for i in ids}
    if ids:
        for stock in await session.scalars(
            select(AssetConsumableStock)
            .where(AssetConsumableStock.consumable_id.in_(ids))
            .order_by(AssetConsumableStock.site_id.nulls_first(), AssetConsumableStock.id)
        ):
            stocks[stock.consumable_id].append(stock)
    return [ConsumableView(r[0], r.name, r.product_type_id, stocks[r[0].id]) for r in rows]


def _with_product() -> Select[AssetConsumable, str, uuid.UUID]:
    return (
        select(AssetConsumable, AssetProduct.name, AssetProduct.product_type_id)
        .join(AssetProduct, AssetProduct.id == AssetConsumable.product_id)
        .where(AssetConsumable.deleted_at.is_(None))
    )


async def list_consumables(
    session: AsyncSession,
    subject: Subject,
    *,
    search: str | None = None,
    site_id: uuid.UUID | None = None,
) -> list[ConsumableView]:
    """Every consumable kept, by product name; `site_id`: those with stock rows there."""
    _require(subject, VIEW)
    query = _with_product()
    if search:
        query = query.where(AssetProduct.name.ilike(f"%{search.strip()}%"))
    if site_id is not None:
        query = query.where(
            AssetConsumable.id.in_(
                select(AssetConsumableStock.consumable_id).where(
                    AssetConsumableStock.site_id == site_id
                )
            )
        )
    query = query.order_by(AssetProduct.name, AssetConsumable.id).limit(CONSUMABLES_MAX)
    return await _views(session, query)


async def consumable_view(
    session: AsyncSession, subject: Subject, consumable_id: uuid.UUID
) -> ConsumableView:
    """One consumable with its stock."""
    _require(subject, VIEW)
    found = await _views(session, _with_product().where(AssetConsumable.id == consumable_id))
    if not found:
        raise NotFound(code="asset_consumable_not_found")
    return found[0]


async def batches_of(
    session: AsyncSession, subject: Subject, consumable_id: uuid.UUID
) -> list[AssetConsumableBatch]:
    """Its lots, those expiring first first (an expired one is flagged by the API, 033 AC2)."""
    _require(subject, VIEW)
    return list(
        await session.scalars(
            select(AssetConsumableBatch)
            .where(
                AssetConsumableBatch.consumable_id == consumable_id,
                AssetConsumableBatch.deleted_at.is_(None),
            )
            .order_by(
                AssetConsumableBatch.expires_on.nulls_last(),
                AssetConsumableBatch.lot_number,
                AssetConsumableBatch.id,
            )
        )
    )


async def ledger(
    session: AsyncSession,
    subject: Subject,
    *,
    consumable_id: uuid.UUID | None = None,
    work_item_id: uuid.UUID | None = None,
    limit: int = LEDGER_MAX,
) -> list[AssetConsumableMovement]:
    """The ledger, newest first: one consumable's, or what was allocated from a request."""
    _require(subject, VIEW)
    query = select(AssetConsumableMovement)
    if consumable_id is not None:
        query = query.where(AssetConsumableMovement.consumable_id == consumable_id)
    if work_item_id is not None:
        query = query.where(AssetConsumableMovement.work_item_id == work_item_id)
    return list(
        await session.scalars(
            query.order_by(
                AssetConsumableMovement.created_at.desc(), AssetConsumableMovement.id.desc()
            ).limit(limit)
        )
    )


# --- stock movements -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BatchIn:
    """The lot a receipt goes into: found by its number at that site, else made."""

    lot_number: str
    reference: str | None = None
    manufactured_on: date | None = None
    expires_on: date | None = None


@dataclass(frozen=True, slots=True)
class Recipient:
    """Who an allocation goes to, or a return comes from."""

    kind: str
    id: uuid.UUID


async def _site_problems(session: AsyncSession, site_id: uuid.UUID | None) -> list[Problem]:
    if site_id is not None and site_id not in await existing_unit_ids(session, "site", [site_id]):
        return [Problem("site_id", "site_not_found")]
    return []


async def _recipient_problems(
    session: AsyncSession, subject: Subject, recipient: Recipient | None
) -> list[Problem]:
    if recipient is None:
        return []
    if recipient.kind not in RECIPIENT_KINDS:
        return [Problem("recipient_kind", "invalid_choice")]
    if recipient.kind == "user":
        found = await active_user_ids(session, [recipient.id])
    elif recipient.kind == "department":
        found = await existing_departments(session, [recipient.id])
    else:
        try:
            await _visible(session, subject, recipient.id)
        except (NotFound, PermissionDenied):  # the same answer either way: no such asset
            return [Problem("recipient_id", "asset_holder_not_found")]
        return []
    return [] if recipient.id in found else [Problem("recipient_id", "asset_holder_not_found")]


_PARAMS: dict[str, tuple[tuple[str, int | str], ...]] = {
    "out_of_range": (("min", 0), ("max", str(QUANTITY_MAX))),
    "too_many_decimals": (("max", QUANTITY_PLACES),),
}
# Field codes made from (field, code) pairs here, for the label check (tests/test_error_labels).
FIELD_PROBLEMS = frozenset(
    {
        "asset_quantity_positive",
        "asset_product_not_consumable",
        "asset_type_not_consumable",
        "asset_stock_rule_target",
        "asset_batch_required",
        "asset_not_batch_tracked",
        "asset_batch_expires_before_made",
    }
)


def _quantity(
    name: str, value: object, *, signed: bool = False, zero: bool = False
) -> list[Problem]:
    """`zero`: nought is a valid value here (a minimum of 0)."""
    code = quantity_problem(value, signed=signed)
    if zero and code == "asset_quantity_positive" and Decimal(str(value)) == 0:
        return []
    return [] if code is None else [Problem(name, code, _PARAMS.get(code, ()))]


def _comment(raw: str | None) -> tuple[str | None, list[Problem]]:
    return _text("comment", raw, COMMENT_MAX)


async def _locked_stock(
    session: AsyncSession, consumable: AssetConsumable, site_id: uuid.UUID | None
) -> AssetConsumableStock | None:
    return await session.scalar(
        select(AssetConsumableStock)
        .where(
            AssetConsumableStock.consumable_id == consumable.id,
            AssetConsumableStock.site_id.is_not_distinct_from(site_id),
        )
        .with_for_update()
    )


async def _stock_at(
    session: AsyncSession, subject: Subject, consumable: AssetConsumable, site_id: uuid.UUID | None
) -> AssetConsumableStock:
    """The site's stock row, locked; made at zero the first time (a racing receipt waits)."""
    found = await _locked_stock(session, consumable, site_id)
    if found is not None:
        return found
    row = AssetConsumableStock(
        id=new_id(), tenant_id=consumable.tenant_id, created_by=subject.user_id,
        consumable_id=consumable.id, site_id=site_id, quantity=Decimal(0),
    )  # fmt: skip
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:  # another receipt made it first: take that one
        found = await _locked_stock(session, consumable, site_id)
        if found is None:  # pragma: no cover - the unique index said it exists
            raise
        return found
    return row


async def _stock_of(
    session: AsyncSession, consumable: AssetConsumable, stock_id: uuid.UUID
) -> AssetConsumableStock:
    found = await session.scalar(
        select(AssetConsumableStock).where(
            AssetConsumableStock.id == stock_id,
            AssetConsumableStock.consumable_id == consumable.id,
        )
    )
    if found is None:
        raise NotFound(code="asset_stock_not_found")
    return found


def _short(available: Decimal) -> Conflict:
    """034 AC1 and AC3: how much is left, or that it ran out."""
    if available <= 0:
        return Conflict(code="asset_stock_ran_out")
    return Conflict(code="asset_stock_short", params={"available": _plain(available)})


def _plain(value: Decimal) -> str:
    """2.000 → "2", 2.500 → "2.5": a quantity as people write it."""
    text = format(value.normalize(), "f")
    return text if text != "-0" else "0"


async def _take(
    session: AsyncSession, subject: Subject, stock: AssetConsumableStock, amount: Decimal
) -> Decimal:
    """Add `amount` (negative: take it away), never below zero; the balance after.

    One conditional UPDATE: the row lock it takes orders racing callers, and the second sees
    the first's result, so the last unit is taken once (034 AC3).
    """
    balance = await session.scalar(
        update(AssetConsumableStock)
        .where(
            AssetConsumableStock.id == stock.id,
            AssetConsumableStock.quantity + amount >= 0,
        )
        .values(
            quantity=AssetConsumableStock.quantity + amount,
            version=AssetConsumableStock.version + 1,
            updated_by=subject.user_id,
        )
        .returning(AssetConsumableStock.quantity)
        .execution_options(synchronize_session=False)
    )
    if balance is None:
        available = await session.scalar(
            select(AssetConsumableStock.quantity).where(AssetConsumableStock.id == stock.id)
        )
        raise _short(Decimal(available or 0))
    await session.refresh(stock)
    return Decimal(balance)


async def _take_batch(
    session: AsyncSession, subject: Subject, batch: AssetConsumableBatch, amount: Decimal
) -> None:
    done = await session.scalar(
        update(AssetConsumableBatch)
        .where(
            AssetConsumableBatch.id == batch.id,
            AssetConsumableBatch.quantity + amount >= 0,
        )
        .values(
            quantity=AssetConsumableBatch.quantity + amount,
            version=AssetConsumableBatch.version + 1,
            updated_by=subject.user_id,
        )
        .returning(AssetConsumableBatch.id)
        .execution_options(synchronize_session=False)
    )
    if done is None:
        available = await session.scalar(
            select(AssetConsumableBatch.quantity).where(AssetConsumableBatch.id == batch.id)
        )
        raise _short(Decimal(available or 0))


async def _batch_of(
    session: AsyncSession, stock: AssetConsumableStock, batch_id: uuid.UUID
) -> AssetConsumableBatch:
    found = await session.scalar(
        select(AssetConsumableBatch).where(
            AssetConsumableBatch.id == batch_id,
            AssetConsumableBatch.stock_id == stock.id,
            AssetConsumableBatch.deleted_at.is_(None),
        )
    )
    if found is None:
        raise NotFound(code="asset_batch_not_found")
    return found


def _batch_problems(consumable: AssetConsumable, *, given: bool, field: str) -> list[Problem]:
    if consumable.batch_tracked and not given:
        return [Problem(field, "asset_batch_required")]
    if not consumable.batch_tracked and given:
        return [Problem(field, "asset_not_batch_tracked")]
    return []


async def _receive_batch(
    session: AsyncSession, subject: Subject, stock: AssetConsumableStock, batch: BatchIn
) -> AssetConsumableBatch:
    """The lot at this site with that number (locked), made the first time."""
    found = await session.scalar(
        select(AssetConsumableBatch)
        .where(
            AssetConsumableBatch.stock_id == stock.id,
            func.lower(AssetConsumableBatch.lot_number) == batch.lot_number.lower(),
        )
        .with_for_update()
    )
    if found is not None:
        if found.expires_on is None and batch.expires_on is not None:
            found.expires_on = batch.expires_on
        return found
    row = AssetConsumableBatch(
        id=new_id(), tenant_id=stock.tenant_id, created_by=subject.user_id,
        consumable_id=stock.consumable_id, stock_id=stock.id, lot_number=batch.lot_number,
        reference=batch.reference, manufactured_on=batch.manufactured_on,
        expires_on=batch.expires_on, quantity=Decimal(0),
    )  # fmt: skip
    session.add(row)
    await session.flush()
    return row


def _lot_problems(batch: BatchIn | None) -> list[Problem]:
    if batch is None:
        return []
    problems: list[Problem] = []
    lot = " ".join(batch.lot_number.split())
    if not lot:
        problems.append(Problem("batch.lot_number", "required"))
    elif len(lot) > LOT_MAX:
        problems.append(Problem("batch.lot_number", "value_too_long", (("max", LOT_MAX),)))
    if (
        batch.manufactured_on is not None
        and batch.expires_on is not None
        and batch.expires_on < batch.manufactured_on
    ):
        problems.append(Problem("batch.expires_on", "asset_batch_expires_before_made"))
    return problems


async def _record(  # noqa: PLR0913 - one ledger line: what, where, how much, to whom, why
    session: AsyncSession,
    subject: Subject,
    consumable: AssetConsumable,
    stock: AssetConsumableStock,
    *,
    kind: MovementKind,
    amount: Decimal,
    balance: Decimal,
    happened_on: date | None,
    batch_id: uuid.UUID | None = None,
    recipient: Recipient | None = None,
    work_item_id: uuid.UUID | None = None,
    unit_cost: Decimal | None = None,
    comment: str | None = None,
) -> AssetConsumableMovement:
    """The ledger line, its event, and what the new balance means for the minimum (035)."""
    line = AssetConsumableMovement(
        id=new_id(), tenant_id=consumable.tenant_id, created_by=subject.user_id,
        consumable_id=consumable.id, stock_id=stock.id, batch_id=batch_id, kind=kind,
        quantity=amount, balance_after=balance,
        happened_on=happened_on or system_clock.now().date(),
        recipient_kind=None if recipient is None else recipient.kind,
        recipient_id=None if recipient is None else recipient.id,
        work_item_id=work_item_id, unit_cost=unit_cost, comment=comment,
    )  # fmt: skip
    session.add(line)
    await session.flush()
    await record_event(
        session,
        StockMoved(
            consumable_id=consumable.id, stock_id=stock.id, movement_id=line.id, kind=kind,
            site_id=stock.site_id, work_item_id=work_item_id,
        ),
        aggregate_id=consumable.id,
        aggregate_version=stock.version,
    )  # fmt: skip
    await check_minimum(session, consumable, stock, balance)
    return line


async def receive(  # noqa: PLR0913 - what arrived, where, how many, which lot, at what cost, why
    session: AsyncSession,
    subject: Subject,
    consumable_id: uuid.UUID,
    *,
    site_id: uuid.UUID | None,
    quantity: Decimal,
    batch: BatchIn | None = None,
    location: str | None = None,
    unit_cost: Decimal | None = None,
    happened_on: date | None = None,
    comment: str | None = None,
) -> AssetConsumableMovement:
    """Stock arrived at a site: that site's quantity rises, no other's (033 AC1)."""
    _require(subject, MANAGE)
    consumable = await _live(session, consumable_id)
    text_, problems = _comment(comment)
    place, found = _text("location", location, LOCATION_MAX)
    problems += found + _quantity("quantity", quantity)
    problems += _batch_problems(consumable, given=batch is not None, field="batch")
    problems += _lot_problems(batch) + await _site_problems(session, site_id)
    if unit_cost is not None:
        problems += amount_problems("unit_cost", unit_cost)
    _refuse(problems)
    stock = await _stock_at(session, subject, consumable, site_id)
    lot = None
    if batch is not None:
        lot = await _receive_batch(
            session, subject, stock,
            BatchIn(" ".join(batch.lot_number.split()), batch.reference, batch.manufactured_on,
                    batch.expires_on),
        )  # fmt: skip
    balance = await _take(session, subject, stock, quantity)
    if lot is not None:
        await _take_batch(session, subject, lot, quantity)
    if place is not None and place != stock.location:
        stock.location = place
        await session.flush()
    return await _record(
        session, subject, consumable, stock, kind="receive", amount=quantity, balance=balance,
        happened_on=happened_on, batch_id=None if lot is None else lot.id,
        unit_cost=unit_cost if unit_cost is not None else consumable.unit_cost, comment=text_,
    )  # fmt: skip


async def allocate(  # noqa: PLR0913 - from where, how many, to whom, for which request, why
    session: AsyncSession,
    subject: Subject,
    consumable_id: uuid.UUID,
    *,
    stock_id: uuid.UUID,
    quantity: Decimal,
    recipient: Recipient,
    work_item_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    happened_on: date | None = None,
    comment: str | None = None,
) -> AssetConsumableMovement:
    """Give some to a person, a department or an asset; never more than there is (034)."""
    _require(subject, MANAGE)
    consumable = await _live(session, consumable_id)
    text_, problems = _comment(comment)
    problems += _quantity("quantity", quantity)
    problems += _batch_problems(consumable, given=batch_id is not None, field="batch_id")
    problems += await _recipient_problems(session, subject, recipient)
    _refuse(problems)
    stock = await _stock_of(session, consumable, stock_id)
    batch = None if batch_id is None else await _batch_of(session, stock, batch_id)
    balance = await _take(session, subject, stock, -quantity)  # the stock row first, always
    if batch is not None:
        await _take_batch(session, subject, batch, -quantity)
    return await _record(
        session, subject, consumable, stock, kind="allocate", amount=-quantity, balance=balance,
        happened_on=happened_on, batch_id=batch_id, recipient=recipient,
        work_item_id=work_item_id, unit_cost=consumable.unit_cost, comment=text_,
    )  # fmt: skip


async def adjust(  # noqa: PLR0913 - which row, by how much, which lot, why
    session: AsyncSession,
    subject: Subject,
    consumable_id: uuid.UUID,
    *,
    stock_id: uuid.UUID,
    change: Decimal,
    batch_id: uuid.UUID | None = None,
    comment: str | None = None,
) -> AssetConsumableMovement:
    """A count or a loss: up or down by `change`, with the reason; never below zero."""
    _require(subject, MANAGE)
    consumable = await _live(session, consumable_id)
    text_, problems = _comment(comment)
    if text_ is None:
        problems.append(Problem("comment", "required"))
    problems += _quantity("change", change, signed=True)
    problems += _batch_problems(consumable, given=batch_id is not None, field="batch_id")
    _refuse(problems)
    stock = await _stock_of(session, consumable, stock_id)
    batch = None if batch_id is None else await _batch_of(session, stock, batch_id)
    balance = await _take(session, subject, stock, change)
    if batch is not None:
        await _take_batch(session, subject, batch, change)
    return await _record(
        session, subject, consumable, stock, kind="adjust", amount=change, balance=balance,
        happened_on=None, batch_id=batch_id, comment=text_,
    )  # fmt: skip


async def return_stock(  # noqa: PLR0913 - which row, how many, from whom, which lot, why
    session: AsyncSession,
    subject: Subject,
    consumable_id: uuid.UUID,
    *,
    stock_id: uuid.UUID,
    quantity: Decimal,
    recipient: Recipient | None = None,
    work_item_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    comment: str | None = None,
) -> AssetConsumableMovement:
    """Unused stock comes back (from whoever it was given to)."""
    _require(subject, MANAGE)
    consumable = await _live(session, consumable_id)
    text_, problems = _comment(comment)
    problems += _quantity("quantity", quantity)
    problems += _batch_problems(consumable, given=batch_id is not None, field="batch_id")
    problems += await _recipient_problems(session, subject, recipient)
    _refuse(problems)
    stock = await _stock_of(session, consumable, stock_id)
    batch = None if batch_id is None else await _batch_of(session, stock, batch_id)
    balance = await _take(session, subject, stock, quantity)
    if batch is not None:
        await _take_batch(session, subject, batch, quantity)
    return await _record(
        session, subject, consumable, stock, kind="return", amount=quantity, balance=balance,
        happened_on=None, batch_id=batch_id, recipient=recipient, work_item_id=work_item_id,
        comment=text_,
    )  # fmt: skip


# --- minimum stock (REQ-AST-035) -----------------------------------------------------------------


async def _type_chain(session: AsyncSession, type_id: uuid.UUID) -> list[uuid.UUID]:
    """The type and its parents, nearest first."""
    chain: list[uuid.UUID] = []
    node: uuid.UUID | None = type_id
    while node is not None and node not in chain:
        chain.append(node)
        node = await session.scalar(
            select(AssetProductType.parent_id).where(AssetProductType.id == node)
        )
    return chain


async def rule_for(
    session: AsyncSession, product_id: uuid.UUID, site_id: uuid.UUID | None
) -> AssetStockRule | None:
    """The most specific live rule for a product at a site (035)."""
    type_id = await session.scalar(
        select(AssetProduct.product_type_id).where(AssetProduct.id == product_id)
    )
    chain = [] if type_id is None else await _type_chain(session, type_id)
    site: ColumnElement[bool] = AssetStockRule.site_id.is_(None)
    if site_id is not None:
        site = site | (AssetStockRule.site_id == site_id)
    rules = list(
        await session.scalars(
            select(AssetStockRule).where(
                AssetStockRule.deleted_at.is_(None),
                (AssetStockRule.product_id == product_id)
                | AssetStockRule.product_type_id.in_(chain),
                site,
            )
        )
    )
    by_id = {str(r.id): r for r in rules}
    picked = pick_rule(
        [
            RuleCandidate(
                id=str(r.id),
                product_rule=r.product_id is not None,
                site_rule=r.site_id is not None,
                type_depth=None if r.product_type_id is None else chain.index(r.product_type_id),
                minimum=r.min_quantity,
            )
            for r in rules
        ]
    )
    return None if picked is None else by_id[picked.id]


async def check_minimum(
    session: AsyncSession,
    consumable: AssetConsumable,
    stock: AssetConsumableStock,
    balance: Decimal,
) -> bool:
    """Alert once at or below the minimum, re-arm above it (035 AC1); whether it alerted.

    The alert is claimed by one UPDATE ... WHERE low_alerted_at IS NULL, so two changes at once
    never both announce it.
    """
    rule = await rule_for(session, consumable.product_id, stock.site_id)
    step = low_stock_step(
        balance,
        None if rule is None else rule.min_quantity,
        alerted=stock.low_alerted_at is not None,
    )
    if step == "rearm":
        await session.execute(
            update(AssetConsumableStock)
            .where(AssetConsumableStock.id == stock.id)
            .values(low_alerted_at=None)
            .execution_options(synchronize_session=False)
        )
        await session.refresh(stock)
        return False
    if step != "alert" or rule is None:
        return False
    claimed = await session.scalar(
        update(AssetConsumableStock)
        .where(AssetConsumableStock.id == stock.id, AssetConsumableStock.low_alerted_at.is_(None))
        .values(low_alerted_at=system_clock.now())
        .returning(AssetConsumableStock.id)
        .execution_options(synchronize_session=False)
    )
    if claimed is None:
        return False
    await session.refresh(stock)
    await record_event(
        session,
        StockLow(
            consumable_id=consumable.id, stock_id=stock.id, rule_id=rule.id, site_id=stock.site_id
        ),
        aggregate_id=consumable.id,
        aggregate_version=stock.version,
    )
    if rule.create_purchase_request and rule.reorder_quantity is not None:
        await _draft_request(session, consumable, stock, rule)
    return True


async def _draft_request(
    session: AsyncSession,
    consumable: AssetConsumable,
    stock: AssetConsumableStock,
    rule: AssetStockRule,
) -> None:
    """The draft purchase request of a rule that asks for one (REQ-AST-035 AC2).

    TODO(WP-054): procurement registers `DraftPurchaseRequests` and links the draft request it
    makes. Until it does, a rule asking for one makes none: logged, never faked.
    """
    if not _DRAFT_REQUESTS:
        log.info("asset_stock_draft_request_waiting_for_procurement", rule_id=str(rule.id))
        return
    assert rule.reorder_quantity is not None  # noqa: S101 - the caller checked
    await _DRAFT_REQUESTS[0](
        session,
        product_id=consumable.product_id,
        site_id=stock.site_id,
        quantity=rule.reorder_quantity,
        rule_id=rule.id,
        stock_id=stock.id,
    )


async def _recheck_all(session: AsyncSession) -> None:
    """After a rule changed: every stock row against its rule now (a tenant keeps few)."""
    rows = (
        await session.execute(
            select(AssetConsumable, AssetConsumableStock)
            .join(AssetConsumableStock, AssetConsumableStock.consumable_id == AssetConsumable.id)
            .where(AssetConsumable.deleted_at.is_(None))
            .with_for_update(of=AssetConsumableStock)
        )
    ).all()
    for consumable, stock in rows:
        await check_minimum(session, consumable, stock, stock.quantity)


async def list_rules(session: AsyncSession, subject: Subject) -> list[AssetStockRule]:
    """Every live rule."""
    _require(subject, VIEW)
    return list(
        await session.scalars(
            select(AssetStockRule)
            .where(AssetStockRule.deleted_at.is_(None))
            .order_by(AssetStockRule.created_at, AssetStockRule.id)
        )
    )


async def _rule_problems(
    session: AsyncSession, values: Mapping[str, Any], current: AssetStockRule | None
) -> tuple[dict[str, Any], list[Problem]]:
    merged = {
        **(
            {}
            if current is None
            else {
                "product_type_id": current.product_type_id,
                "product_id": current.product_id,
                "site_id": current.site_id,
                "min_quantity": current.min_quantity,
                "notify_user_ids": current.notify_user_ids,
                "create_purchase_request": current.create_purchase_request,
                "reorder_quantity": current.reorder_quantity,
            }
        ),
        **values,
    }
    problems: list[Problem] = []
    type_id, product_id = merged.get("product_type_id"), merged.get("product_id")
    if (type_id is None) == (product_id is None):
        problems.append(Problem("product_id", "asset_stock_rule_target"))
    elif product_id is not None and await _consumable_type(session, product_id) is None:
        problems.append(Problem("product_id", "asset_product_not_consumable"))
    elif type_id is not None:
        kind = await session.scalar(
            select(AssetProductType.kind).where(
                AssetProductType.id == type_id, AssetProductType.deleted_at.is_(None)
            )
        )
        if kind != AssetTypeKind.CONSUMABLE:
            problems.append(Problem("product_type_id", "asset_type_not_consumable"))
    minimum = merged.get("min_quantity")
    if minimum is None:
        problems.append(Problem("min_quantity", "required"))
    else:
        problems += _quantity("min_quantity", minimum, zero=True)
    problems += await _site_problems(session, merged.get("site_id"))
    people = [uuid.UUID(str(p)) for p in merged.get("notify_user_ids") or []]
    if len(people) > NOTIFY_MAX:
        problems.append(Problem("notify_user_ids", "too_many", (("max", NOTIFY_MAX),)))
    elif set(people) - set(await active_user_ids(session, people)):
        problems.append(Problem("notify_user_ids", "asset_holder_not_found"))
    reorder = merged.get("reorder_quantity")
    if merged.get("create_purchase_request") and reorder is None:
        problems.append(Problem("reorder_quantity", "required"))
    elif reorder is not None:
        problems += _quantity("reorder_quantity", reorder)
    merged["notify_user_ids"] = [str(p) for p in dict.fromkeys(people)]
    merged["create_purchase_request"] = bool(merged.get("create_purchase_request"))
    return merged, problems


async def _rule_event(session: AsyncSession, row: AssetStockRule, action: ConsumableAction) -> None:
    await record_event(
        session,
        StockRuleChanged(rule_id=row.id, action=action),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )


_RULE_FIELDS = (
    "product_type_id",
    "product_id",
    "site_id",
    "min_quantity",
    "notify_user_ids",
    "create_purchase_request",
    "reorder_quantity",
)


async def create_rule(
    session: AsyncSession, subject: Subject, values: Mapping[str, Any]
) -> AssetStockRule:
    """A minimum for a product type or a product, at a site or all sites."""
    require_configure(subject)
    merged, problems = await _rule_problems(session, values, None)
    _refuse(problems)
    row = AssetStockRule(
        id=new_id(),
        tenant_id=_tenant(session),
        created_by=subject.user_id,
        **{k: merged.get(k) for k in _RULE_FIELDS if k in merged},
    )
    session.add(row)
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError:
        raise Conflict(code="asset_stock_rule_exists") from None
    await session.refresh(row)  # the stored quantities (NUMERIC(14, 3))
    await _rule_event(session, row, "created")
    await _recheck_all(session)
    return row


async def _live_rule(session: AsyncSession, rule_id: uuid.UUID) -> AssetStockRule:
    row = await session.scalar(
        select(AssetStockRule)
        .where(AssetStockRule.id == rule_id, AssetStockRule.deleted_at.is_(None))
        .with_for_update()
    )
    if row is None:
        raise NotFound(code="asset_stock_rule_not_found")
    return row


async def update_rule(
    session: AsyncSession,
    subject: Subject,
    rule_id: uuid.UUID,
    values: Mapping[str, Any],
    *,
    expected_version: int,
) -> AssetStockRule:
    """Change a rule (If-Match); stock is checked against it again at once."""
    require_configure(subject)
    row = await _live_rule(session, rule_id)
    if row.version != expected_version:
        raise await stale_version(
            session, row, expected_version=expected_version, record_type=RULE_RECORD_TYPE,
            record_id=row.id,
        )  # fmt: skip
    merged, problems = await _rule_problems(session, values, row)
    _refuse(problems)
    for key in _RULE_FIELDS:
        if key in merged:
            setattr(row, key, merged[key])
    row.version += 1
    row.updated_by = subject.user_id
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError:
        raise Conflict(code="asset_stock_rule_exists") from None
    await session.refresh(row)  # the stored quantities (NUMERIC(14, 3))
    await _rule_event(session, row, "updated")
    await _recheck_all(session)
    return row


async def delete_rule(
    session: AsyncSession, subject: Subject, rule_id: uuid.UUID, *, expected_version: int
) -> None:
    """Remove a rule (If-Match); another rule may then apply."""
    require_configure(subject)
    row = await _live_rule(session, rule_id)
    if row.version != expected_version:
        raise await stale_version(
            session, row, expected_version=expected_version, record_type=RULE_RECORD_TYPE,
            record_id=row.id,
        )  # fmt: skip
    row.deleted_at = system_clock.now()
    row.version += 1
    row.updated_by = subject.user_id
    await session.flush()
    await _rule_event(session, row, "deleted")
    await _recheck_all(session)


async def minimums(
    session: AsyncSession, stocks: Sequence[AssetConsumableStock], product_id: uuid.UUID
) -> dict[uuid.UUID, Decimal]:
    """Each stock row's minimum, where a rule applies."""
    found: dict[uuid.UUID, Decimal] = {}
    for stock in stocks:
        rule = await rule_for(session, product_id, stock.site_id)
        if rule is not None:
            found[stock.id] = rule.min_quantity
    return found
