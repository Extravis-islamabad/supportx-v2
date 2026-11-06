"""The asset record (WP-049a session 2; parity 07 §3: REQ-AST-001, 002, 004, 007, 008).

- **Who:** `assets.view` reads (scoped: all, or the assets at your sites); `assets.manage` adds,
  changes and moves assets to the trash, within its scope.
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
from app.core.errors import FieldError, NotFound, PermissionDenied, ValidationFailed
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
from app.modules.assets.events import AssetAction, AssetChanged
from app.modules.assets.infra.models import (
    Asset,
    AssetProduct,
    AssetProductType,
    AssetSettings,
    AssetState,
)
from app.modules.assets.service.catalogue import TEXT_MAX, ensure_defaults
from app.modules.identity_access import (
    ResourceType,
    Subject,
    authorize_stored,
    scope_filter,
)
from app.modules.licensing import LimitKey, hold_limit, reserve_capacity
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
        "acquired_on": FilterField(Asset.acquired_on, FieldType.DATE, sortable=True),
        "warranty_expires_on": FilterField(
            Asset.warranty_expires_on, FieldType.DATE, sortable=True
        ),
        "created_at": FilterField(Asset.created_at, FieldType.DATETIME, sortable=True),
        "updated_at": FilterField(Asset.updated_at, FieldType.DATETIME, sortable=True),
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
_TEXT_FIELDS = {"name": NAME_MAX, "location": LOCATION_MAX, "description": TEXT_MAX}
_IDENTIFIERS = ("tag", "serial_number", "barcode")
_AMOUNTS = ("purchase_price", "purchase_tax")
_DATES = ("acquired_on", "warranty_expires_on", "expires_on")
_IDS = ("product_id", "vendor_id", "site_id", "purchase_order_id")


def _require(subject: Subject, permission: str) -> None:
    if not subject.holds(permission):
        raise PermissionDenied(params={"permission": permission})


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
    return cleaned, problems


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
    return await session.scalar(
        select(AssetProduct).where(AssetProduct.id == product_id, AssetProduct.deleted_at.is_(None))
    )


async def _type(session: AsyncSession, type_id: uuid.UUID) -> AssetProductType:
    found = await session.get(AssetProductType, type_id)
    if found is None:  # a foreign key holds it
        msg = f"asset product type {type_id} is missing"
        raise RuntimeError(msg)
    return found


async def _default_state(session: AsyncSession) -> AssetState:
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
    return found


async def _counts(session: AsyncSession, type_id: uuid.UUID, state_id: uuid.UUID) -> bool:
    kind = await _type(session, type_id)
    state = await session.get(AssetState, state_id)
    return state is not None and counts_toward_limit(kind.category, kind.kind, state.category)


async def _reserve(session: AsyncSession) -> None:
    """Take one managed-asset slot, or refuse (403 asset_limit_reached), race-safely."""
    await hold_limit(session, LimitKey.ASSETS)
    await reserve_capacity(session, LimitKey.ASSETS, code=LIMIT_CODE)


async def _next_tag(session: AsyncSession, product_type: AssetProductType) -> str:
    """The next tag of the nearest pattern up the type tree, else the tenant's (REQ-AST-008)."""
    node: AssetProductType | None = product_type
    while node is not None:
        if node.tag_pattern:
            number = await next_display_number(session, tag_counter_key(str(node.id)))
            return format_tag(node.tag_pattern, number)
        node = (
            None if node.parent_id is None else await session.get(AssetProductType, node.parent_id)
        )
    settings = await session.get(AssetSettings, _tenant(session))
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
    params = await metadata.problem_params(session, ENTITY, found)
    problems = [Problem(path, code, tuple(params.get(path, {}).items())) for path, code in found]
    merged = {**before, **cleaned}
    return {k: v for k, v in merged.items() if v is not None}, problems


async def _saved(  # noqa: PLR0913 - one save: what, who, the changes, how, where from
    session: AsyncSession,
    subject: Subject,
    row: Asset,
    changes: list[Change],
    *,
    action: AssetAction,
    source: Source,
    reason: str | None = None,
) -> None:
    if action != "created":
        row.version += 1
    row.updated_by = subject.user_id
    await session.flush()
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


async def get_asset(session: AsyncSession, subject: Subject, asset_id: uuid.UUID) -> Asset:
    """One live asset the subject may see (404 otherwise: never a hint that it exists)."""
    _require(subject, VIEW)
    return await _visible(session, subject, asset_id)


async def create_asset(
    session: AsyncSession, subject: Subject, values: Mapping[str, Any], *, source: Source
) -> Asset:
    """A new asset of a product, in the default in-stock state, with its tag."""
    _require(subject, MANAGE)
    await ensure_defaults(session)
    cleaned, problems = _clean(values)
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
    row = Asset(
        id=new_id(),
        tenant_id=_tenant(session),
        created_by=subject.user_id,
        product_type_id=product_type.id,
        state_id=state.id,
        custom=custom or {},
        custom_text=await metadata.text_for_search(session, ENTITY, custom or {}),
        **cleaned,
    )
    session.add(row)
    await session.flush()
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
) -> Asset:
    """Change the fields sent. A product change moves the asset to that product's type."""
    _require(subject, MANAGE)
    row = await _visible(session, subject, asset_id, permission=MANAGE)
    if row.version != expected_version:
        raise await stale_version(
            session, row, expected_version=expected_version, record_type=RECORD_TYPE,
            record_id=row.id,
        )  # fmt: skip
    cleaned, problems = _clean(values)
    problems += await _product_change(session, cleaned)
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
    if not counted and await _counts(session, row.product_type_id, row.state_id):
        await _reserve(session)  # e.g. a non-IT asset's product became an IT one
    await _saved(session, subject, row, changes, action="updated", source=source)
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
    session: AsyncSession, subject: Subject, asset_id: uuid.UUID, *, source: Source
) -> Asset:
    """Back from the trash, taking a slot again if it counts (403 asset_limit_reached)."""
    _require(subject, MANAGE)
    in_trash = select(Asset).where(
        Asset.id == asset_id,
        Asset.deleted_at.is_not(None),
        scope_filter(subject, MANAGE, ASSETS),
    )
    row = await session.scalar(in_trash.with_for_update())
    if row is None:
        raise NotFound(code="asset_not_found")
    if await _counts(session, row.product_type_id, row.state_id):
        await _reserve(session)
    row.deleted_at = None
    restored = Change("deleted", old=True, new=False)
    await _saved(session, subject, row, [restored], action="restored", source=source)
    return row


def purchase_total(row: Asset) -> Decimal | None:
    """Price plus tax (D-141); None when neither is known."""
    if row.purchase_price is None and row.purchase_tax is None:
        return None
    return (row.purchase_price or Decimal(0)) + (row.purchase_tax or Decimal(0))


# --- for other modules and the licence ---------------------------------------------------------


async def count_managed_assets(session: AsyncSession) -> int:
    """Assets using a slot of the plan's asset limit (REQ-AST-002, D-141)."""
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
    return int(found or 0)


async def assets_naming_vendor(session: AsyncSession, vendor_id: uuid.UUID) -> int:
    """How many assets (trash included: a restore would need it) name the vendor."""
    found = await session.scalar(
        select(func.count()).select_from(Asset).where(Asset.vendor_id == vendor_id)
    )
    return int(found or 0)
