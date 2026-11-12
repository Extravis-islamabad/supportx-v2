"""The asset record (WP-049a session 2; parity 07 §3: REQ-AST-001, 002, 004, 007, 008).

- **Who:** `assets.view` reads (scoped: all, or the assets at your sites); `assets.manage` adds,
  changes and moves assets to the trash, within its scope. A technician without it may change
  the location of an asset its own ticket links while the ticket's requester or department
  holds it (D-157, `ticket_access`; also its state and fitted parts, in moves and ownership).
- **Money (D-157):** price, tax, total and depreciation settings are read and written only with
  `assets.view_financials`; the API shows others nulls and masks those history lines.
- **Licence (REQ-AST-002, D-141):** an IT asset (an IT type of kind asset) that is not disposed
  uses a slot of the plan's asset limit. Adding one, or turning an asset into one (a product
  change, a restore), reserves the slot race-safely; the limit is only read through the
  licensing interface.
- **Tags (REQ-AST-008):** a new asset gets the next tag of its type's pattern (the nearest type
  up the tree with one), else the tenant's. The counter never goes back. A person with
  `assets.manage` may type a tag instead. Tag and serial are unique per tenant, ignoring case,
  trash included, and a refusal names the asset that holds the value (AC1).
- **Other modules:** vendor (procurement), site (organization) and custom fields (metadata) are
  checked through their public interfaces.
- Every save keeps field history and writes its event to the outbox in the same transaction;
  changes need the version read (If-Match). The state is not changed here: moves between states
  follow the life cycle (session 3).
"""

import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict, FieldError, NotFound, PermissionDenied, ValidationFailed
from app.modules import metadata
from app.modules.assets.domain.assets import (
    IDENTIFIER_MAX,
    LOCATION_MAX,
    NAME_MAX,
    clean_identifier,
    counts_toward_limit,
    format_tag,
    identifier_problem,
    tag_counter_key,
)
from app.modules.assets.domain.catalogue import AssetStateCategory, Problem, amount_problems
from app.modules.assets.domain.financials import (
    COST_CENTRE_MAX,
    GL_CODE_MAX,
    DepreciationChoice,
    terms_problems,
)
from app.modules.assets.events import AssetAction, AssetChanged
from app.modules.assets.infra.models import (
    Asset,
    AssetMerge,
    AssetProduct,
    AssetProductType,
    AssetSettings,
    AssetState,
)
from app.modules.assets.service import catalogue as catalogue_money
from app.modules.assets.service import ticket_access, valuations
from app.modules.assets.service.catalogue import TEXT_MAX, ensure_defaults
from app.modules.assets.service.memo import memo
from app.modules.assets.service.valuations import VALUED_FIELDS
from app.modules.identity_access import (
    ResourceType,
    Subject,
    authorize_stored,
    scope_filter,
    unrestricted,
)
from app.modules.licensing import LimitKey, reserve_capacity
from app.modules.organization import existing_unit_ids
from app.modules.procurement import vendor_problem
from app.shared.api.filters import FieldType, FilterField, ResourceFields
from app.shared.db.display_ids import next_display_number
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes
from app.shared.history.conflicts import stale_version
from app.shared.ids import new_id

VIEW = "assets.view"
MANAGE = "assets.manage"
EDIT_DISPOSED = "assets.edit_disposed"  # REQ-AST-017 AC3: changes a disposed asset (with a reason)
# WP-049b s2: costs, depreciation and book value (REQ-AST-036, 037). The asset's own depreciation
# settings are set only by those who may see its money (and manage it).
VIEW_FINANCIALS = catalogue_money.VIEW_FINANCIALS  # one name for the right (catalogue)
DEPRECIATION_FIELDS = ("depreciation_method", "useful_life_years", "salvage_value")
# D-157: the purchase price and tax are money too; with the depreciation settings, nobody
# without `assets.view_financials` reads (API, list, history) or writes them.
MONEY_FIELDS = ("purchase_price", "purchase_tax", "purchase_total", *DEPRECIATION_FIELDS)
RECORD_TYPE = "asset"
ENTITY = "asset"  # metadata.CustomFieldEntity.ASSET
LIMIT_CODE = "asset_limit_reached"

ASSET_FIELDS = ResourceFields(
    name="assets",
    fields={
        "name": FilterField(Asset.name, FieldType.STRING, sortable=True),
        "tag": FilterField(Asset.tag, FieldType.STRING, sortable=True),
        "serial_number": FilterField(Asset.serial_number, FieldType.STRING, sortable=True),
        "barcode": FilterField(Asset.barcode, FieldType.STRING),
        "product_id": FilterField(Asset.product_id, FieldType.UUID),
        "product_type_id": FilterField(Asset.product_type_id, FieldType.UUID),
        "state_id": FilterField(Asset.state_id, FieldType.UUID),
        "vendor_id": FilterField(Asset.vendor_id, FieldType.UUID),
        "site_id": FilterField(Asset.site_id, FieldType.UUID),
        # Its holder (0111): what a person or department holds, an asset's components.
        "owner_user_id": FilterField(Asset.owner_user_id, FieldType.UUID),
        "department_id": FilterField(Asset.department_id, FieldType.UUID),
        "parent_asset_id": FilterField(Asset.parent_asset_id, FieldType.UUID),
        "acquired_on": FilterField(Asset.acquired_on, FieldType.DATE, sortable=True),
        "warranty_expires_on": FilterField(
            Asset.warranty_expires_on, FieldType.DATE, sortable=True
        ),
        "created_at": FilterField(Asset.created_at, FieldType.DATETIME, sortable=True),
        "updated_at": FilterField(Asset.updated_at, FieldType.DATETIME, sortable=True),
        # 0131 (REQ-AST-038): free text, as typed; reports group by it.
        "cost_centre": FilterField(Asset.cost_centre, FieldType.STRING, sortable=True),
        "gl_code": FilterField(Asset.gl_code, FieldType.STRING, sortable=True),
    },
    id_column=Asset.id,
    default_sort=("-updated_at",),
)


def _at_sites(site_ids: frozenset[uuid.UUID]) -> ColumnElement[bool]:
    return Asset.site_id.in_(site_ids)


def _group_reach(subject: Subject) -> ColumnElement[bool] | None:
    # Assets have no managing group yet (ownership, session 4, names people and departments):
    # until they do, `group` scope reaches the assets at the member's sites and those at none,
    # so a technician can keep the assets they add without a site.
    unsited = Asset.site_id.is_(None)
    return or_(Asset.site_id.in_(subject.site_ids), unsited) if subject.site_ids else unsited


ASSETS = ResourceType(
    name="assets",
    fields=ASSET_FIELDS,
    site_scope=_at_sites,
    group_scope_extra=_group_reach,
)

# The fields a person sets (state: through the life cycle; discovered serial: by discovery).
_TEXT_FIELDS = {
    "name": NAME_MAX,
    "location": LOCATION_MAX,
    "description": TEXT_MAX,
    "cost_centre": COST_CENTRE_MAX,
    "gl_code": GL_CODE_MAX,
}
_IDENTIFIERS = ("tag", "serial_number", "barcode")
_AMOUNTS = ("purchase_price", "purchase_tax")
_DATES = ("acquired_on", "warranty_expires_on", "expires_on")
_IDS = ("product_id", "vendor_id", "site_id", "purchase_order_id")


# The asset as it is saved is one the person may manage (their scope: site, or group's sites and
# unsited assets). `assets.manage` in some scope is not enough: a site-scoped manager never
# creates an asset at, nor moves one to, a site outside it (lane B, 2026-11-12).
SITE_NOT_MANAGED = "asset_site_not_managed"


async def _within_scope(session: AsyncSession, subject: Subject, row: Asset) -> None:
    """Refuse (the transaction rolls back) when the saved asset falls outside the scope."""
    await session.flush()
    if unrestricted(subject, MANAGE):
        return  # scope "all", no condition: the query could only say yes (an import, per row)
    if not await authorize_stored(session, subject, MANAGE, ASSETS, Asset.id, row.id):
        raise PermissionDenied(code=SITE_NOT_MANAGED, params={"permission": MANAGE})


async def _site_change_within_scope(
    session: AsyncSession, subject: Subject, row: Asset, changes: list[Change]
) -> None:
    """A change of site never moves the asset out of the person's reach."""
    if any(c.field == "site_id" for c in changes):
        await _within_scope(session, subject, row)


def _require(subject: Subject, permission: str) -> None:
    if not subject.holds(permission):
        raise PermissionDenied(params={"permission": permission})


def _require_financials_for(subject: Subject, values: Mapping[str, Any]) -> None:
    """Price, tax and depreciation settings are money (REQ-AST-037, D-157): `view_financials`."""
    if any(name in values for name in MONEY_FIELDS):
        _require(subject, VIEW_FINANCIALS)


def sees_money(subject: Subject) -> bool:
    """Whether the subject may read an asset's money (price, tax, total, depreciation)."""
    return subject.holds(VIEW_FINANCIALS)


def _tenant(session: AsyncSession) -> uuid.UUID:
    tenant: uuid.UUID = session.info[SESSION_TENANT_KEY].tenant_id
    return tenant


def _json(value: object) -> Any:  # noqa: ANN401 - history stores JSON values
    if isinstance(value, Decimal | uuid.UUID | date):
        return str(value)
    return value


def _clean_text(name: str, raw: object, limit: int) -> tuple[str | None, Problem | None]:
    value = "" if raw is None else str(raw)
    text = value.strip() if name == "description" else " ".join(value.split())
    if name == "name" and not text:
        return None, Problem(name, "required")
    if len(text) > limit:
        return None, Problem(name, "value_too_long", (("max", limit),))
    return text or None, None


def _clean_identifier(name: str, raw: object) -> tuple[str | None, Problem | None]:
    value = clean_identifier(raw)
    if code := identifier_problem(value):
        params = (("max", IDENTIFIER_MAX),) if code == "value_too_long" else ()
        return None, Problem(name, code, params)
    return value, None


def _clean(values: Mapping[str, Any]) -> tuple[dict[str, Any], list[Problem]]:
    """The person-set fields sent, trimmed, and what is wrong with their shape."""
    cleaned: dict[str, Any] = {}
    problems: list[Problem] = []
    for name, limit in _TEXT_FIELDS.items():
        if name in values:
            text, problem = _clean_text(name, values[name], limit)
            if problem is None:
                cleaned[name] = text
            else:
                problems.append(problem)
    for name in _IDENTIFIERS:
        if name in values:
            value, problem = _clean_identifier(name, values[name])
            if problem is None:
                cleaned[name] = value
            else:
                problems.append(problem)
    for name in _AMOUNTS:
        if name in values:
            amount = None if values[name] is None else Decimal(str(values[name]))
            problems += amount_problems(name, amount)
            cleaned[name] = amount
    cleaned.update({k: values[k] for k in ("currency", *_DATES, *_IDS) if k in values})
    problems += _depreciation(values, cleaned)
    return cleaned, problems


def _depreciation(values: Mapping[str, Any], cleaned: dict[str, Any]) -> list[Problem]:
    """The asset's own depreciation settings sent (REQ-AST-037), into `cleaned`; their problems.

    The salvage value is checked against the cost by `_salvage_problems` once the cost is known.
    """
    problems: list[Problem] = []
    if "depreciation_method" in values:
        method = values["depreciation_method"]
        if method is not None and method not in set(DepreciationChoice):
            problems.append(Problem("depreciation_method", "invalid_choice"))
        else:
            cleaned["depreciation_method"] = None if method is None else str(method)
    life = values.get("useful_life_years")
    salvage = values.get("salvage_value")
    salvage = None if salvage is None else Decimal(str(salvage))
    found = terms_problems(life, salvage, None)
    problems += found
    if not found:
        cleaned.update(
            {
                k: v
                for k, v in (("useful_life_years", life), ("salvage_value", salvage))
                if k in values
            }
        )
    return problems


def _salvage_problems(cleaned: Mapping[str, Any], current: Asset | None) -> list[Problem]:
    """A salvage value above the asset's cost (as it will be after this save) is refused."""

    def after(name: str) -> Any:  # noqa: ANN401 - a column's value
        return cleaned[name] if name in cleaned else getattr(current, name, None)

    salvage = after("salvage_value")
    if salvage is None:
        return []
    cost = (after("purchase_price") or Decimal(0)) + (after("purchase_tax") or Decimal(0))
    if after("purchase_price") is None and after("purchase_tax") is None:
        return []
    return terms_problems(None, salvage, cost)


def _refuse(problems: Sequence[Problem]) -> None:
    if problems:
        raise ValidationFailed(
            errors=[
                FieldError(
                    field=f"body.{p.field}",
                    code=p.code,
                    message_key=f"errors.field.{p.code}",
                    params=dict(p.params),
                )
                for p in problems
            ]
        )


async def _holder(
    session: AsyncSession,
    column: InstrumentedAttribute[str | None],
    value: str,
    other_than: uuid.UUID | None,
) -> str | None:
    """The tag (or name) of the asset already holding `value`, trash included."""
    statement = select(Asset.tag, Asset.name).where(func.lower(column) == value.lower())
    if other_than is not None:
        statement = statement.where(Asset.id != other_than)
    row = (await session.execute(statement.limit(1))).first()
    return None if row is None else (row.tag or row.name)


async def _unique_problems(
    session: AsyncSession, cleaned: Mapping[str, Any], other_than: uuid.UUID | None
) -> list[Problem]:
    problems: list[Problem] = []
    for name, column in (("tag", Asset.tag), ("serial_number", Asset.serial_number)):
        value = cleaned.get(name)
        if value is not None and (held := await _holder(session, column, value, other_than)):
            problems.append(Problem(name, f"asset_{name}_taken", (("asset", held),)))
    return problems


async def _link_problems(
    session: AsyncSession, cleaned: Mapping[str, Any], current: Asset | None
) -> list[Problem]:
    """The vendor and site the asset names (other modules' records), checked."""
    problems: list[Problem] = []
    vendor = cleaned.get("vendor_id")
    if vendor is not None:
        code = await vendor_problem(
            session, vendor, current=None if current is None else current.vendor_id
        )
        if code is not None:
            problems.append(Problem("vendor_id", code))
    site = cleaned.get("site_id")
    if site is not None and site not in await existing_unit_ids(session, "site", [site]):
        problems.append(Problem("site_id", "site_not_found"))
    return problems


async def _product(session: AsyncSession, product_id: uuid.UUID) -> AssetProduct | None:
    """A live product, kept for the (sub)transaction like the types.

    An import names the same few products on thousands of rows (WP-049b). Within one batch a
    product retired by someone else is still seen as live until the batch ends, about two
    seconds, as a row already checked would have been.
    """
    products: dict[uuid.UUID, AssetProduct | None] = memo(session).setdefault("products", {})
    if product_id not in products:
        products[product_id] = await session.scalar(
            select(AssetProduct).where(
                AssetProduct.id == product_id, AssetProduct.deleted_at.is_(None)
            )
        )
    return products[product_id]


async def _type(session: AsyncSession, type_id: uuid.UUID) -> AssetProductType:
    found = await _held_type(session, type_id)
    if found is None:  # a foreign key holds it
        msg = f"asset product type {type_id} is missing"
        raise RuntimeError(msg)
    return found


async def _held_type(session: AsyncSession, type_id: uuid.UUID) -> AssetProductType | None:
    """A product type, kept for the transaction (the identity map alone forgets it: S4c)."""
    types: dict[uuid.UUID, AssetProductType | None] = memo(session).setdefault("types", {})
    if type_id not in types:
        types[type_id] = await session.get(AssetProductType, type_id)
    return types[type_id]


async def _default_state(session: AsyncSession) -> AssetState:
    known = memo(session)
    if "default_state" in known:
        state: AssetState = known["default_state"]
        return state
    found = await session.scalar(
        select(AssetState).where(
            AssetState.category == AssetStateCategory.IN_STOCK,
            AssetState.is_default_for_category,
            AssetState.deleted_at.is_(None),
        )
    )
    if found is None:  # ensure_defaults made one; an admin cannot remove a default
        msg = "no default in-stock state"
        raise RuntimeError(msg)
    known["default_state"] = found
    return found


async def _counts(session: AsyncSession, type_id: uuid.UUID, state_id: uuid.UUID) -> bool:
    kind = await _type(session, type_id)
    state = await session.get(AssetState, state_id)
    return state is not None and counts_toward_limit(kind.category, kind.kind, state.category)


async def _reserve(session: AsyncSession) -> None:
    """Take one managed-asset slot, or refuse (403 asset_limit_reached), race-safely.

    `reserve_capacity` takes the limit's lock itself before it counts (a second `hold_limit`
    first was one more round trip per asset, S4c).
    """
    await reserve_capacity(session, LimitKey.ASSETS, code=LIMIT_CODE)
    known = memo(session)
    if "slots" in known:  # memo.keep_slot_count: one more slot taken in this savepoint
        known["slots"] += 1


async def _next_tag(session: AsyncSession, product_type: AssetProductType) -> str:
    """The next tag of the nearest pattern up the type tree, else the tenant's (REQ-AST-008)."""
    node: AssetProductType | None = product_type
    while node is not None:
        if node.tag_pattern:
            number = await next_display_number(session, tag_counter_key(str(node.id)))
            return format_tag(node.tag_pattern, number)
        node = None if node.parent_id is None else await _held_type(session, node.parent_id)
    known = memo(session)
    if "settings" not in known:
        known["settings"] = await session.get(AssetSettings, _tenant(session))
    settings: AssetSettings | None = known["settings"]
    pattern = settings.tag_pattern if settings is not None else "AST-{n}"
    return format_tag(pattern, await next_display_number(session, tag_counter_key(None)))


async def _custom(
    session: AsyncSession, sent: Mapping[str, Any] | None, current: Asset | None
) -> tuple[dict[str, Any] | None, list[Problem]]:
    """The asset's custom values after this save (None: untouched), checked by metadata."""
    creating = current is None
    if sent is None and not creating:
        return None, []
    before = {} if current is None else dict(current.custom)
    cleaned, found = await metadata.clean(
        session, ENTITY, sent or {}, current=before, creating=creating, defaults=creating
    )
    params = await metadata.problem_params(session, ENTITY, found) if found else {}
    problems = [Problem(path, code, tuple(params.get(path, {}).items())) for path, code in found]
    merged = {**before, **cleaned}
    return {k: v for k, v in merged.items() if v is not None}, problems


async def _saved(  # noqa: PLR0913 - one save: what, who, the changes, how, where from
    session: AsyncSession,
    subject: Subject | None,
    row: Asset,
    changes: list[Change],
    *,
    action: AssetAction,
    source: Source,
    reason: str | None = None,
) -> None:
    """One save: version, history, event. `subject` None: the system (a site that followed)."""
    if action != "created":
        row.version += 1
    row.updated_by = None if subject is None else subject.user_id
    await session.flush()
    if action != "created":  # a new asset's INSERT returned them (eager_defaults on Asset)
        await session.refresh(row)  # the database's timestamps
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=row.id,
        version=row.version,
        kind="created"
        if action == "created"
        else ("deleted" if action == "deleted" else "updated"),
        changes=changes,
        source=source,
        reason=reason,
    )
    await record_event(
        session,
        AssetChanged(
            asset_id=row.id,
            action=action,
            changed_fields=sorted({c.field for c in changes}),
            site_id=row.site_id,
        ),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )
    if action == "created" or VALUED_FIELDS & {c.field for c in changes}:
        # Reports see the new figures at once. A new asset has no cost lines or disposal yet.
        await valuations.refresh(session, row, new=action == "created")


def staff_rows(subject: Subject, *, trash: bool = False) -> Select[Asset]:
    """The assets the subject may see (or, `trash`, those in the trash)."""
    _require(subject, VIEW)
    deleted = Asset.deleted_at.is_not(None) if trash else Asset.deleted_at.is_(None)
    return select(Asset).where(deleted, scope_filter(subject, VIEW, ASSETS))


async def _visible(
    session: AsyncSession, subject: Subject, asset_id: uuid.UUID, *, permission: str = VIEW
) -> Asset:
    row = await session.scalar(
        select(Asset)
        .where(Asset.id == asset_id, Asset.deleted_at.is_(None))
        .with_for_update(of=Asset)
    ) if permission == MANAGE else await session.scalar(
        select(Asset).where(Asset.id == asset_id, Asset.deleted_at.is_(None))
    )  # fmt: skip
    if row is None or not await authorize_stored(
        session, subject, permission, ASSETS, Asset.id, asset_id
    ):
        if (
            row is not None
            and permission == MANAGE
            and await authorize_stored(session, subject, VIEW, ASSETS, Asset.id, asset_id)
        ):
            raise PermissionDenied(params={"permission": MANAGE})
        raise NotFound(code="asset_not_found")
    return row


async def writable(
    session: AsyncSession, subject: Subject, asset_id: uuid.UUID
) -> tuple[Asset, bool]:
    """The asset to change, locked, and whether only the narrower D-157 path allows it.

    `assets.manage` on the asset: the full write (False). Otherwise a person who sees it may
    still change a few fields when it is linked to their own ticket and held by that ticket's
    requester or department (True, `ticket_access`). Otherwise 403 (seen) or 404.
    """
    if subject.holds(MANAGE):
        try:
            return await _visible(session, subject, asset_id, permission=MANAGE), False
        except PermissionDenied:
            pass  # sees it without managing it (another site): perhaps through a ticket
    if not subject.holds(VIEW):
        raise PermissionDenied(params={"permission": MANAGE})
    row = await _visible(session, subject, asset_id)
    if not await ticket_access.ticket_grants(session, subject, row):
        raise PermissionDenied(params={"permission": MANAGE})
    await session.refresh(row, with_for_update=True)  # as the full write locks it
    return row, True


async def _writable_with(
    session: AsyncSession, subject: Subject, asset_id: uuid.UUID, values: Mapping[str, Any]
) -> Asset:
    """The asset for a save of `values`: the D-157 path changes the location only; money asks."""
    row, limited = await writable(session, subject, asset_id)
    if limited and (refused := sorted(set(values) - ticket_access.LIMITED_FIELDS)):
        raise ticket_access.refuse_field(refused[0])
    _require_financials_for(subject, values)
    return row


async def get_asset(session: AsyncSession, subject: Subject, asset_id: uuid.UUID) -> Asset:
    """One live asset the subject may see (404 otherwise: never a hint that it exists)."""
    _require(subject, VIEW)
    return await _visible(session, subject, asset_id)


async def edit_reach(
    session: AsyncSession, subject: Subject, asset_id: uuid.UUID
) -> tuple[bool, bool]:
    """(manages it, may change a few fields through its own ticket: D-157) for the record page."""
    row = await get_asset(session, subject, asset_id)
    if subject.holds(MANAGE) and await authorize_stored(
        session, subject, MANAGE, ASSETS, Asset.id, asset_id
    ):
        return True, False
    return False, await ticket_access.ticket_grants(session, subject, row)


async def create_asset(
    session: AsyncSession, subject: Subject, values: Mapping[str, Any], *, source: Source
) -> Asset:
    """A new asset of a product, in the default in-stock state, with its tag."""
    _require(subject, MANAGE)
    _require_financials_for(subject, values)
    await ensure_defaults(session)
    cleaned, problems = _clean(values)
    problems += _salvage_problems(cleaned, None)
    if "name" not in cleaned and not any(p.field == "name" for p in problems):
        problems.append(Problem("name", "required"))
    product = None
    if cleaned.get("product_id") is None:
        problems.append(Problem("product_id", "required"))
    elif (product := await _product(session, cleaned["product_id"])) is None:
        problems.append(Problem("product_id", "asset_product_not_found"))
    problems += await _link_problems(session, cleaned, None)
    custom, custom_problems = await _custom(session, values.get("custom"), None)
    problems += custom_problems
    problems += await _unique_problems(session, cleaned, None)
    _refuse(problems)
    assert product is not None  # noqa: S101 - refused above otherwise
    product_type = await _type(session, product.product_type_id)
    state = await _default_state(session)
    if counts_toward_limit(product_type.category, product_type.kind, state.category):
        await _reserve(session)
    if cleaned.get("tag") is None:
        cleaned["tag"] = await _next_tag(session, product_type)
    if "gl_code" not in values and product.gl_code:
        cleaned["gl_code"] = product.gl_code  # REQ-AST-038: from the product unless typed
    row = Asset(
        id=new_id(),
        tenant_id=_tenant(session),
        created_by=subject.user_id,
        updated_by=subject.user_id,  # as `_saved` sets it: no second UPDATE of the new row (S4c)
        product_type_id=product_type.id,
        state_id=state.id,
        custom=custom or {},
        # No custom values, no search text (S4c: skips reading the definitions for nothing).
        custom_text=await metadata.text_for_search(session, ENTITY, custom) if custom else None,
        **cleaned,
    )
    session.add(row)
    await _within_scope(session, subject, row)  # flushes
    if custom:
        await metadata.mark_used(session, ENTITY, list(custom))
    changes = [
        Change(k, None, _json(v))
        for k, v in {**cleaned, "product_type_id": product_type.id, "state_id": state.id}.items()
        if v is not None
    ]
    changes += [Change(f"custom.{k}", None, v) for k, v in (custom or {}).items()]
    await _saved(session, subject, row, changes, action="created", source=source)
    return row


async def _product_change(session: AsyncSession, cleaned: dict[str, Any]) -> list[Problem]:
    """A new product, checked; its type then goes with it (into `cleaned`)."""
    if "product_id" not in cleaned:
        return []
    if cleaned["product_id"] is None:
        return [Problem("product_id", "required")]
    product = await _product(session, cleaned["product_id"])
    if product is None:
        return [Problem("product_id", "asset_product_not_found")]
    cleaned["product_type_id"] = product.product_type_id
    return []


async def _apply_custom(session: AsyncSession, row: Asset, custom: dict[str, Any]) -> list[Change]:
    changes = [
        Change(f"custom.{key}", row.custom.get(key), custom.get(key))
        for key in sorted(set(custom) | set(row.custom))
        if custom.get(key) != row.custom.get(key)
    ]
    row.custom = custom
    row.custom_text = await metadata.text_for_search(session, ENTITY, custom)
    await metadata.mark_used(session, ENTITY, list(custom))
    return changes


async def update_asset(  # noqa: PLR0913 - the If-Match and the source
    session: AsyncSession,
    subject: Subject,
    asset_id: uuid.UUID,
    values: Mapping[str, Any],
    *,
    expected_version: int,
    source: Source,
    reason: str | None = None,
) -> Asset:
    """Change the fields sent. A product change moves the asset to that product's type.

    A disposed asset is read-only (REQ-AST-017 AC3): only `assets.edit_disposed` changes it,
    and each such change asks for a reason, kept in its history.
    """
    row = await _writable_with(session, subject, asset_id, values)
    if row.version != expected_version:
        raise await stale_version(
            session, row, expected_version=expected_version, record_type=RECORD_TYPE,
            record_id=row.id,
        )  # fmt: skip
    state = await session.get(AssetState, row.state_id)
    disposed = state is not None and state.category == AssetStateCategory.DISPOSED
    if disposed and not subject.holds(EDIT_DISPOSED):
        raise PermissionDenied(
            code="asset_disposed_read_only", params={"permission": EDIT_DISPOSED}
        )
    cleaned, problems = _clean(values)
    text = (reason or "").strip() or None
    if disposed and text is None:
        problems.append(Problem("reason", "required"))
    problems += await _product_change(session, cleaned)
    problems += _salvage_problems(cleaned, row)
    if "tag" in cleaned and cleaned["tag"] is None:
        problems.append(Problem("tag", "required"))  # a tag, once given, stays (AST-008)
    problems += await _link_problems(session, cleaned, row)
    custom, custom_problems = await _custom(session, values.get("custom"), row)
    problems += custom_problems
    problems += await _unique_problems(session, cleaned, row.id)
    _refuse(problems)
    counted = await _counts(session, row.product_type_id, row.state_id)
    changes: list[Change] = []
    for field, value in cleaned.items():
        if getattr(row, field) != value:
            changes.append(Change(field, _json(getattr(row, field)), _json(value)))
            setattr(row, field, value)
    if custom is not None and custom != row.custom:
        changes += await _apply_custom(session, row, custom)
    if not changes:
        return row
    await _site_change_within_scope(session, subject, row, changes)
    if not counted and await _counts(session, row.product_type_id, row.state_id):
        await _reserve(session)  # e.g. a non-IT asset's product became an IT one
    await _saved(session, subject, row, changes, action="updated", source=source, reason=text)
    return row


async def delete_asset(
    session: AsyncSession,
    subject: Subject,
    asset_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> None:
    """To the trash; it frees its slot, and its tag and serial stay taken (restore is safe)."""
    _require(subject, MANAGE)
    row = await _visible(session, subject, asset_id, permission=MANAGE)
    if row.version != expected_version:
        raise await stale_version(
            session, row, expected_version=expected_version, record_type=RECORD_TYPE,
            record_id=row.id,
        )  # fmt: skip
    row.deleted_at = datetime.now(UTC)
    deleted = Change("deleted", old=False, new=True)
    await _saved(session, subject, row, [deleted], action="deleted", source=source)


async def restore_asset(
    session: AsyncSession,
    subject: Subject,
    asset_id: uuid.UUID,
    *,
    source: Source,
    confirm_merged: bool = False,
) -> Asset:
    """Back from the trash, taking a slot again if it counts (403 asset_limit_reached).

    An asset merged into another (REQ-AST-052) comes back only once the person has seen the
    warning (409 `asset_restore_merged`, naming the survivor; then `confirm_merged`). It comes
    back on its own: the alias ends, and what moved to the survivor stays there.
    """
    _require(subject, MANAGE)
    in_trash = select(Asset).where(
        Asset.id == asset_id,
        Asset.deleted_at.is_not(None),
        scope_filter(subject, MANAGE, ASSETS),
    )
    row = await session.scalar(in_trash.with_for_update())
    if row is None:
        raise NotFound(code="asset_not_found")
    changes = [Change("deleted", old=True, new=False)]
    merge = await session.scalar(
        select(AssetMerge)
        .where(
            AssetMerge.merged_id == row.id,
            AssetMerge.restored_at.is_(None),
            AssetMerge.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if merge is not None:
        survivor = await session.get(Asset, merge.survivor_id)
        name = "" if survivor is None else (survivor.tag or survivor.name)
        if not confirm_merged:
            raise Conflict(code="asset_restore_merged", params={"asset": name})
        merge.restored_at, merge.restored_by = datetime.now(UTC), subject.user_id
        merge.version += 1
        changes.append(Change("restored_after_merge", None, name))
    if await _counts(session, row.product_type_id, row.state_id):
        await _reserve(session)
    row.deleted_at = None
    await _saved(session, subject, row, changes, action="restored", source=source)
    return row


def purchase_total(row: Asset) -> Decimal | None:
    """Price plus tax (D-141); None when neither is known."""
    if row.purchase_price is None and row.purchase_tax is None:
        return None
    return (row.purchase_price or Decimal(0)) + (row.purchase_tax or Decimal(0))


# --- for other modules and the licence ---------------------------------------------------------


async def count_managed_assets(session: AsyncSession) -> int:
    """Assets using a slot of the plan's asset limit (REQ-AST-002, D-141).

    In an import's batch savepoint (`memo.keep_slot_count`) counted once, then kept up to date.
    """
    known = memo(session)
    if known.get("keep_slot_count") and "slots" in known:
        slots: int = known["slots"]
        return slots
    found = await session.scalar(
        select(func.count())
        .select_from(Asset)
        .join(AssetProductType, AssetProductType.id == Asset.product_type_id)
        .join(AssetState, AssetState.id == Asset.state_id)
        .where(
            Asset.deleted_at.is_(None),
            AssetProductType.category == "it",
            AssetProductType.kind == "asset",
            AssetState.category != AssetStateCategory.DISPOSED,
        )
    )
    if known.get("keep_slot_count"):
        known["slots"] = int(found or 0)
    return int(found or 0)


async def assets_naming_vendor(session: AsyncSession, vendor_id: uuid.UUID) -> int:
    """How many assets (trash included: a restore would need it) name the vendor."""
    found = await session.scalar(
        select(func.count()).select_from(Asset).where(Asset.vendor_id == vendor_id)
    )
    return int(found or 0)
