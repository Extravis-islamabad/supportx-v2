"""The asset catalogue: product types, products, states, life cycles, settings (WP-049a s1).

Parity 07 §2 and §4 (REQ-AST-003, 005, 012, 013) and D-141. Admins (`config.assets`, or
`settings.manage`) change it; anyone with `assets.view` reads it, because the asset form needs
it. Every save keeps field history, writes its event to the outbox in the same transaction, and
needs the version read (If-Match). A tenant's defaults (Appendix A) are made the first time its
catalogue is used (`ensure_defaults`), so a new tenant never sees an empty catalogue (D-041).
"""

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict, FieldError, NotFound, PermissionDenied, ValidationFailed
from app.modules.assets.domain.catalogue import (
    API_NAME,
    CURRENCY,
    LIFE_CYCLES_MAX,
    SEED_LIFE_CYCLE_CODE,
    SEED_LIFE_CYCLE_NAMES,
    SEED_MOVES,
    SEED_STATES,
    SEED_TYPES,
    STATE_CODE,
    STATES_MAX,
    TREE_DEPTH_MAX,
    TYPES_MAX,
    AssetAgeBasis,
    AssetDepreciationMethod,
    AssetStateCategory,
    AssetTypeCategory,
    AssetTypeKind,
    Move,
    Problem,
    SeedType,
    amount_problems,
    clean_names,
    depth,
    descendants,
    duplicate_moves,
    tag_pattern_problems,
    would_cycle,
)
from app.modules.assets.events import (
    CatalogueAction,
    CatalogueChanged,
    CatalogueKind,
    ProductChanged,
)
from app.modules.assets.infra.models import (
    AssetLifeCycle,
    AssetLifeCycleTransition,
    AssetProduct,
    AssetProductType,
    AssetSettings,
    AssetState,
)
from app.modules.identity_access import Subject
from app.shared.api.filters import FieldType, FilterField, ResourceFields
from app.shared.db.models import TenantEntity
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes
from app.shared.history.conflicts import stale_version
from app.shared.ids import new_id

VIEW = "assets.view"
MANAGE = "assets.manage"
CONFIGURE = "config.assets"
REINSTATE = "assets.reinstate"
# The per-area right (WP-042); settings.manage still grants every area.
CONFIGURE_ANY = (CONFIGURE, "settings.manage")

TEXT_MAX = 2000
ICON_MAX = 40
NAME_MAX = 200
PART_MAX = 100
GL_MAX = 40
SETTINGS_RECORD = uuid.UUID(int=0)  # asset_settings has no id: one history stream per tenant


# --- helpers ----------------------------------------------------------------------------------


def require_configure(subject: Subject) -> None:
    """403 unless the subject may change the catalogue."""
    if not any(subject.holds(p) for p in CONFIGURE_ANY):
        raise PermissionDenied(params={"permission": CONFIGURE})


def _tenant(session: AsyncSession) -> uuid.UUID:
    tenant: uuid.UUID = session.info[SESSION_TENANT_KEY].tenant_id
    return tenant


def _errors(problems: Iterable[Problem]) -> list[FieldError]:
    return [
        FieldError(
            field=f"body.{p.field}",
            code=p.code,
            message_key=f"errors.field.{p.code}",
            params=dict(p.params),
        )
        for p in problems
    ]


def _refuse(problems: list[Problem]) -> None:
    if problems:
        raise ValidationFailed(errors=_errors(problems))


def _json(value: object) -> Any:  # noqa: ANN401 - history stores JSON values
    if isinstance(value, Decimal | uuid.UUID):
        return str(value)
    if isinstance(value, Mapping):
        return dict(value)
    return value


def _apply(row: object, wanted: Mapping[str, object]) -> list[Change]:
    """Set the wanted values that differ; the changes, oldest value first."""
    changes = []
    for field, value in wanted.items():
        before = getattr(row, field)
        if before != value:
            changes.append(Change(field, _json(before), _json(value)))
            setattr(row, field, value)
    return changes


async def _saved(  # noqa: PLR0913 - one save: what, who, where from
    session: AsyncSession,
    subject: Subject,
    row: Any,  # noqa: ANN401 - any versioned catalogue row
    changes: list[Change],
    *,
    kind: CatalogueKind | None,
    action: CatalogueAction,
    source: Source,
) -> None:
    """History, the version bump and the event, in the caller's transaction."""
    record_id = getattr(row, "id", SETTINGS_RECORD)
    if action != "created":
        row.version += 1
    row.updated_by = subject.user_id
    await session.flush()
    if action == "created":
        await session.refresh(row)  # the database's created_at and updated_at
    await record_changes(
        session,
        record_type=f"asset_{kind or 'product'}",
        record_id=record_id,
        version=row.version,
        kind="created"
        if action == "created"
        else ("deleted" if action == "deleted" else "updated"),
        changes=changes,
        source=source,
    )
    fields = sorted({c.field for c in changes})
    if kind is None:
        event: CatalogueChanged | ProductChanged = ProductChanged(
            product_id=row.id,
            product_type_id=row.product_type_id,
            action=action,
            changed_fields=fields,
        )
    else:
        event = CatalogueChanged(
            kind=kind,
            item_id=None if kind == "settings" else row.id,
            action=action,
            changed_fields=fields,
        )
    await record_event(session, event, aggregate_id=record_id, aggregate_version=row.version)


async def _locked[T: TenantEntity](
    session: AsyncSession, model: type[T], item_id: uuid.UUID, code: str
) -> T:
    row: T | None = await session.scalar(
        select(model).where(model.id == item_id, model.deleted_at.is_(None)).with_for_update()
    )
    if row is None:
        raise NotFound(code=code)
    return row


async def _fresh(
    session: AsyncSession,
    row: Any,  # noqa: ANN401 - any versioned catalogue row (entities and the settings)
    expected_version: int,
    record_type: str,
) -> None:
    if row.version != expected_version:
        raise await stale_version(
            session,
            row,
            expected_version=expected_version,
            record_type=record_type,
            record_id=getattr(row, "id", SETTINGS_RECORD),
        )


# --- defaults (Appendix A) --------------------------------------------------------------------


async def ensure_defaults(session: AsyncSession) -> None:
    """The tenant's settings row and, the first time, every Appendix A default (idempotent).

    The settings row is the marker: only the transaction that inserts it seeds the rest. A
    parallel first request waits on the row's key until that transaction ends, then finds it.
    """
    tenant = _tenant(session)
    inserted = await session.execute(
        insert(AssetSettings)
        .values(tenant_id=tenant)
        .on_conflict_do_nothing()
        .returning(AssetSettings.tenant_id)
    )
    if inserted.scalar() is None:
        return
    states: dict[str, uuid.UUID] = {}
    for sort, seed in enumerate(SEED_STATES):
        states[seed.code] = new_id()
        session.add(
            AssetState(
                id=states[seed.code],
                tenant_id=tenant,
                code=seed.code,
                names=dict(seed.names),
                category=seed.category.value,
                reason_required=seed.reason_required,
                is_default_for_category=seed.default_for_category,
                system=seed.system,
                sort=sort,
            )
        )
    life_cycle = AssetLifeCycle(
        id=new_id(),
        tenant_id=tenant,
        code=SEED_LIFE_CYCLE_CODE,
        names=dict(SEED_LIFE_CYCLE_NAMES),
        is_default=True,
    )
    session.add(life_cycle)
    await session.flush()
    for move in SEED_MOVES:
        session.add(_transition(tenant, life_cycle.id, move, states))

    def add(seed: SeedType, parent: AssetProductType | None, sort: int) -> None:
        node = AssetProductType(
            id=new_id(),
            tenant_id=tenant,
            parent_id=parent.id if parent else None,
            api_name=seed.api_name,
            names=dict(seed.names),
            icon=seed.icon,
            category=(seed.category.value if seed.category else parent.category if parent else ""),
            kind=(seed.kind.value if seed.kind else parent.kind if parent else ""),
            sort=sort,
        )
        session.add(node)
        for index, child in enumerate(seed.children):
            add(child, node, index)

    for index, top in enumerate(SEED_TYPES):
        add(top, None, index)
    await session.flush()


def _transition(
    tenant: uuid.UUID, life_cycle_id: uuid.UUID, move: Move, states: Mapping[str, uuid.UUID]
) -> AssetLifeCycleTransition:
    return AssetLifeCycleTransition(
        id=new_id(),
        tenant_id=tenant,
        life_cycle_id=life_cycle_id,
        from_state_id=states[move.from_state],
        to_state_id=states[move.to_state],
        reason_required=move.reason_required,
        required_fields=[],
        permission=move.permission,
    )


# --- settings ---------------------------------------------------------------------------------

SETTINGS_FIELDS = (
    "tag_pattern",
    "age_basis",
    "cost_includes_tax",
    "copy_limit",
    "site_follows_owner",
    "portal_own_assets_only",
    "email_include_assets",
    "scan_retention_months",
    "warranty_notice_days",
)


async def get_settings(session: AsyncSession) -> AssetSettings:
    """The tenant's asset settings (made with the defaults on first use)."""
    await ensure_defaults(session)
    row: AssetSettings | None = await session.scalar(select(AssetSettings))
    assert row is not None  # noqa: S101 - ensure_defaults made it
    return row


def _settings_problems(values: Mapping[str, Any]) -> list[Problem]:
    problems = tag_pattern_problems("tag_pattern", values.get("tag_pattern"))
    if "age_basis" in values and values["age_basis"] not in set(AssetAgeBasis):
        problems.append(Problem("age_basis", "invalid_choice"))
    for field, low, high in (
        ("copy_limit", 1, 500),
        ("scan_retention_months", 1, 60),
        ("warranty_notice_days", 1, 365),  # 0114; Appendix A: 30
    ):
        value = values.get(field)
        if field in values and (not isinstance(value, int) or not low <= value <= high):
            problems.append(Problem(field, "out_of_range", (("min", low), ("max", high))))
    return problems


async def update_settings(
    session: AsyncSession,
    subject: Subject,
    values: Mapping[str, Any],
    *,
    expected_version: int,
    source: Source,
) -> AssetSettings:
    """Change the settings sent (If-Match)."""
    require_configure(subject)
    await ensure_defaults(session)
    row = await session.scalar(select(AssetSettings).with_for_update())
    assert row is not None  # noqa: S101 - ensure_defaults made it
    await _fresh(session, row, expected_version, "asset_settings")
    wanted = {k: v for k, v in values.items() if k in SETTINGS_FIELDS}
    _refuse(_settings_problems(wanted))
    changes = _apply(row, wanted)
    if changes:
        await _saved(
            session, subject, row, changes, kind="settings", action="updated", source=source
        )
    return row


# --- states (REQ-AST-012) ---------------------------------------------------------------------


async def list_states(session: AsyncSession) -> Sequence[AssetState]:
    """Every state, in the admin's order."""
    await ensure_defaults(session)
    return (
        await session.scalars(
            select(AssetState)
            .where(AssetState.deleted_at.is_(None))
            .order_by(AssetState.sort, AssetState.code)
        )
    ).all()


def _state_problems(values: Mapping[str, Any], *, creating: bool) -> list[Problem]:
    problems: list[Problem] = []
    if creating:
        code = values.get("code")
        if not isinstance(code, str) or not STATE_CODE.match(code):
            problems.append(Problem("code", "invalid_code"))
    if "category" in values and values["category"] not in set(AssetStateCategory):
        problems.append(Problem("category", "invalid_choice"))
    return problems


async def _clear_category_default(session: AsyncSession, category: str, keep: uuid.UUID) -> None:
    """One default state per category: the new default takes it from the old one."""
    old = await session.scalar(
        select(AssetState)
        .where(
            AssetState.category == category,
            AssetState.is_default_for_category.is_(True),
            AssetState.deleted_at.is_(None),
            AssetState.id != keep,
        )
        .with_for_update()
    )
    if old is not None:
        old.is_default_for_category = False
        await session.flush()


async def create_state(
    session: AsyncSession, subject: Subject, values: Mapping[str, Any], *, source: Source
) -> AssetState:
    """A new state in one of the fixed categories."""
    require_configure(subject)
    existing = await list_states(session)
    names, problems = clean_names("names", values.get("names"))
    problems += _state_problems(values, creating=True)
    if len(existing) >= STATES_MAX:
        problems.append(Problem("code", "too_many_items", (("max", STATES_MAX),)))
    if any(s.code == values.get("code") for s in existing):
        problems.append(Problem("code", "asset_state_code_taken"))
    _refuse(problems)
    row = AssetState(
        id=new_id(),
        tenant_id=_tenant(session),
        code=values["code"],
        names=names,
        category=values["category"],
        reason_required=bool(values.get("reason_required", False)),
        is_default_for_category=False,
        system=False,
        sort=max((s.sort for s in existing), default=0) + 1,
        created_by=subject.user_id,
    )
    session.add(row)
    await session.flush()
    if values.get("is_default_for_category"):
        await _clear_category_default(session, row.category, row.id)
        row.is_default_for_category = True
    changes = [
        Change(f, None, _json(getattr(row, f)))
        for f in ("code", "names", "category", "reason_required", "is_default_for_category")
    ]
    await _saved(session, subject, row, changes, kind="state", action="created", source=source)
    return row


async def update_state(  # noqa: PLR0913 - the If-Match and the source
    session: AsyncSession,
    subject: Subject,
    state_id: uuid.UUID,
    values: Mapping[str, Any],
    *,
    expected_version: int,
    source: Source,
) -> AssetState:
    """Rename, re-order, change its category or reason rule, or make it its category's default."""
    require_configure(subject)
    await ensure_defaults(session)
    row = await _locked(session, AssetState, state_id, "asset_state_not_found")
    await _fresh(session, row, expected_version, "asset_state")
    problems = _state_problems(values, creating=False)
    wanted: dict[str, Any] = {}
    if "names" in values:
        names, name_problems = clean_names("names", values["names"])
        problems += name_problems
        wanted["names"] = names
    for field in ("category", "reason_required", "sort"):
        if field in values:
            wanted[field] = values[field]
    if row.system and wanted.get("category", row.category) != row.category:
        problems.append(Problem("category", "asset_state_system"))
    becomes_default = values.get("is_default_for_category")
    if becomes_default is False and row.is_default_for_category:
        # Every category keeps one default: make another state the default instead.
        problems.append(Problem("is_default_for_category", "asset_state_default_needed"))
    if row.is_default_for_category and wanted.get("category", row.category) != row.category:
        problems.append(Problem("category", "asset_state_default_needed"))
    _refuse(problems)
    changes = _apply(row, wanted)
    if becomes_default and not row.is_default_for_category:
        await _clear_category_default(session, row.category, row.id)
        changes += _apply(row, {"is_default_for_category": True})
    if changes:
        await _saved(session, subject, row, changes, kind="state", action="updated", source=source)
    return row


async def delete_state(
    session: AsyncSession,
    subject: Subject,
    state_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> None:
    """Soft delete: never a system state, a category's default or one a life cycle uses."""
    require_configure(subject)
    await ensure_defaults(session)
    row = await _locked(session, AssetState, state_id, "asset_state_not_found")
    await _fresh(session, row, expected_version, "asset_state")
    if row.system or row.is_default_for_category:
        raise Conflict(code="asset_state_protected")
    used = await session.scalar(
        select(func.count())
        .select_from(AssetLifeCycleTransition)
        .join(AssetLifeCycle, AssetLifeCycle.id == AssetLifeCycleTransition.life_cycle_id)
        .where(
            AssetLifeCycle.deleted_at.is_(None),
            (AssetLifeCycleTransition.from_state_id == row.id)
            | (AssetLifeCycleTransition.to_state_id == row.id),
        )
    )
    if used:
        raise Conflict(code="asset_state_in_use", params={"used": int(used)})
    row.deleted_at = datetime.now(UTC)
    changes = [Change("deleted_at", None, row.deleted_at.isoformat())]
    await _saved(session, subject, row, changes, kind="state", action="deleted", source=source)


# --- life cycles (REQ-AST-013) ----------------------------------------------------------------


@dataclass(frozen=True)
class LifeCycleView:
    """A life cycle with its moves."""

    record: AssetLifeCycle
    moves: Sequence[AssetLifeCycleTransition]


async def list_life_cycles(session: AsyncSession) -> list[LifeCycleView]:
    """Every life cycle with its moves, the default first."""
    await ensure_defaults(session)
    cycles = (
        await session.scalars(
            select(AssetLifeCycle)
            .where(AssetLifeCycle.deleted_at.is_(None))
            .order_by(AssetLifeCycle.is_default.desc(), AssetLifeCycle.created_at)
        )
    ).all()
    moves = (
        await session.scalars(
            select(AssetLifeCycleTransition).where(
                AssetLifeCycleTransition.life_cycle_id.in_([c.id for c in cycles])
            )
        )
    ).all()
    return [LifeCycleView(c, [m for m in moves if m.life_cycle_id == c.id]) for c in cycles]


async def _moves_from(
    session: AsyncSession, raw: object
) -> tuple[list[tuple[Move, uuid.UUID, uuid.UUID]], list[Problem]]:
    """The moves sent, checked against the tenant's live states."""
    if not isinstance(raw, list):
        return [], [Problem("moves", "required")]
    states = {s.id: s for s in await list_states(session)}
    moves: list[tuple[Move, uuid.UUID, uuid.UUID]] = []
    problems: list[Problem] = []
    for index, item in enumerate(raw):
        from_id, to_id = item.get("from_state_id"), item.get("to_state_id")
        if from_id not in states or to_id not in states:
            problems.append(Problem(f"moves.{index}", "asset_state_not_found"))
            continue
        moves.append(
            (
                Move(
                    str(from_id),
                    str(to_id),
                    reason_required=bool(item.get("reason_required", False)),
                    permission=item.get("permission"),
                ),
                from_id,
                to_id,
            )
        )
    problems += [
        Problem(f"moves.{i}", "asset_move_duplicate")
        for i in duplicate_moves(m for m, _, _ in moves)
    ]
    return moves, problems


async def _replace_moves(
    session: AsyncSession,
    subject: Subject,
    cycle: AssetLifeCycle,
    moves: list[tuple[Move, uuid.UUID, uuid.UUID]],
) -> None:
    await session.execute(
        delete(AssetLifeCycleTransition).where(AssetLifeCycleTransition.life_cycle_id == cycle.id)
    )
    for move, from_id, to_id in moves:
        session.add(
            AssetLifeCycleTransition(
                id=new_id(),
                tenant_id=cycle.tenant_id,
                life_cycle_id=cycle.id,
                from_state_id=from_id,
                to_state_id=to_id,
                reason_required=move.reason_required,
                required_fields=[],
                permission=move.permission,
                created_by=subject.user_id,
            )
        )
    await session.flush()


def _move_list(moves: Iterable[tuple[Move, uuid.UUID, uuid.UUID]]) -> list[Any]:
    return sorted(
        (
            {"from": str(f), "to": str(t), "reason": m.reason_required, "permission": m.permission}
            for m, f, t in moves
        ),
        key=lambda item: (item["from"], item["to"]),
    )


async def create_life_cycle(
    session: AsyncSession, subject: Subject, values: Mapping[str, Any], *, source: Source
) -> LifeCycleView:
    """A new life cycle, its moves given at once."""
    require_configure(subject)
    existing = await list_life_cycles(session)
    names, problems = clean_names("names", values.get("names"))
    code = values.get("code")
    if not isinstance(code, str) or not STATE_CODE.match(code):
        problems.append(Problem("code", "invalid_code"))
    elif any(v.record.code == code for v in existing):
        problems.append(Problem("code", "asset_life_cycle_code_taken"))
    moves, move_problems = await _moves_from(session, values.get("moves", []))
    problems += move_problems
    if len(existing) >= LIFE_CYCLES_MAX:
        problems.append(Problem("names", "too_many_items", (("max", LIFE_CYCLES_MAX),)))
    _refuse(problems)
    cycle = AssetLifeCycle(
        id=new_id(),
        tenant_id=_tenant(session),
        code=code,
        names=names,
        is_default=False,
        created_by=subject.user_id,
    )
    session.add(cycle)
    await session.flush()
    await _replace_moves(session, subject, cycle, moves)
    changes = [
        Change("code", None, code),
        Change("names", None, names),
        Change("moves", None, _move_list(moves)),
    ]
    await _saved(
        session, subject, cycle, changes, kind="life_cycle", action="created", source=source
    )
    return await _cycle_view(session, cycle.id)


async def _cycle_view(session: AsyncSession, cycle_id: uuid.UUID) -> LifeCycleView:
    for view in await list_life_cycles(session):
        if view.record.id == cycle_id:
            return view
    raise NotFound(code="asset_life_cycle_not_found")


async def update_life_cycle(  # noqa: PLR0913 - the If-Match and the source
    session: AsyncSession,
    subject: Subject,
    cycle_id: uuid.UUID,
    values: Mapping[str, Any],
    *,
    expected_version: int,
    source: Source,
) -> LifeCycleView:
    """Rename it, replace its moves, or make it the default (the old default stops being it)."""
    require_configure(subject)
    await ensure_defaults(session)
    cycle = await _locked(session, AssetLifeCycle, cycle_id, "asset_life_cycle_not_found")
    await _fresh(session, cycle, expected_version, "asset_life_cycle")
    problems: list[Problem] = []
    wanted: dict[str, Any] = {}
    if "names" in values:
        names, problems = clean_names("names", values["names"])
        wanted["names"] = names
    moves = None
    if "moves" in values:
        moves, move_problems = await _moves_from(session, values["moves"])
        problems += move_problems
    if values.get("is_default") is False and cycle.is_default:
        problems.append(Problem("is_default", "asset_life_cycle_default_needed"))
    _refuse(problems)
    changes = _apply(cycle, wanted)
    if moves is not None:
        before = await session.scalars(
            select(AssetLifeCycleTransition).where(
                AssetLifeCycleTransition.life_cycle_id == cycle.id
            )
        )
        old = _move_list(
            (
                Move("", "", reason_required=t.reason_required, permission=t.permission),
                t.from_state_id,
                t.to_state_id,
            )
            for t in before
        )
        new = _move_list(moves)
        if old != new:
            await _replace_moves(session, subject, cycle, moves)
            changes.append(Change("moves", old, new))
    if values.get("is_default") and not cycle.is_default:
        previous = await session.scalar(
            select(AssetLifeCycle)
            .where(AssetLifeCycle.is_default.is_(True), AssetLifeCycle.deleted_at.is_(None))
            .with_for_update()
        )
        if previous is not None:
            previous.is_default = False
            await session.flush()
        changes += _apply(cycle, {"is_default": True})
    if changes:
        await _saved(
            session, subject, cycle, changes, kind="life_cycle", action="updated", source=source
        )
    return await _cycle_view(session, cycle.id)


async def delete_life_cycle(
    session: AsyncSession,
    subject: Subject,
    cycle_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> None:
    """Soft delete: never the default, never one a product type uses."""
    require_configure(subject)
    await ensure_defaults(session)
    cycle = await _locked(session, AssetLifeCycle, cycle_id, "asset_life_cycle_not_found")
    await _fresh(session, cycle, expected_version, "asset_life_cycle")
    if cycle.is_default:
        raise Conflict(code="asset_life_cycle_protected")
    used = await session.scalar(
        select(func.count())
        .select_from(AssetProductType)
        .where(AssetProductType.life_cycle_id == cycle.id, AssetProductType.deleted_at.is_(None))
    )
    if used:
        raise Conflict(code="asset_life_cycle_in_use", params={"used": int(used)})
    cycle.deleted_at = datetime.now(UTC)
    changes = [Change("deleted_at", None, cycle.deleted_at.isoformat())]
    await _saved(
        session, subject, cycle, changes, kind="life_cycle", action="deleted", source=source
    )


# --- product types (REQ-AST-003) --------------------------------------------------------------


async def list_product_types(session: AsyncSession) -> Sequence[AssetProductType]:
    """The whole tree, flat (each row names its parent), in the admin's order."""
    await ensure_defaults(session)
    return (
        await session.scalars(
            select(AssetProductType)
            .where(AssetProductType.deleted_at.is_(None))
            .order_by(AssetProductType.sort, AssetProductType.api_name)
        )
    ).all()


async def _type_problems(
    session: AsyncSession,
    values: Mapping[str, Any],
    types: Sequence[AssetProductType],
    *,
    type_id: uuid.UUID | None,
) -> list[Problem]:
    problems = tag_pattern_problems("tag_pattern", values.get("tag_pattern"))
    by_id = {t.id: t for t in types}
    parents = {str(t.id): (str(t.parent_id) if t.parent_id else None) for t in types}
    if "parent_id" in values and values["parent_id"] is not None:
        parent = values["parent_id"]
        if parent not in by_id:
            problems.append(Problem("parent_id", "asset_product_type_not_found"))
        elif type_id is not None and would_cycle(str(type_id), str(parent), parents):
            problems.append(Problem("parent_id", "asset_product_type_cycle"))
        else:
            below = (
                1
                + max(
                    (
                        depth(d, parents) - depth(str(type_id), parents)
                        for d in descendants(str(type_id), parents)
                    ),
                    default=0,
                )
                if type_id is not None
                else 1
            )
            if depth(str(parent), parents) + below > TREE_DEPTH_MAX:
                problems.append(
                    Problem("parent_id", "asset_product_type_too_deep", (("max", TREE_DEPTH_MAX),))
                )
    if "category" in values and values["category"] not in set(AssetTypeCategory):
        problems.append(Problem("category", "invalid_choice"))
    if "kind" in values and values["kind"] not in set(AssetTypeKind):
        problems.append(Problem("kind", "invalid_choice"))
    if "icon" in values and values["icon"] is not None and len(values["icon"]) > ICON_MAX:
        problems.append(Problem("icon", "value_too_long", (("max", ICON_MAX),)))
    description = values.get("description")
    if description is not None and len(description) > TEXT_MAX:
        problems.append(Problem("description", "value_too_long", (("max", TEXT_MAX),)))
    cycle = values.get("life_cycle_id")
    if cycle is not None and not await session.scalar(
        select(AssetLifeCycle.id).where(
            AssetLifeCycle.id == cycle, AssetLifeCycle.deleted_at.is_(None)
        )
    ):
        problems.append(Problem("life_cycle_id", "asset_life_cycle_not_found"))
    return problems


async def create_product_type(
    session: AsyncSession, subject: Subject, values: Mapping[str, Any], *, source: Source
) -> AssetProductType:
    """A new type. Under a parent it takes the parent's category and kind (REQ-AST-003)."""
    require_configure(subject)
    types = await list_product_types(session)
    names, problems = clean_names("names", values.get("names"))
    api_name = values.get("api_name")
    if not isinstance(api_name, str) or not API_NAME.match(api_name):
        problems.append(Problem("api_name", "invalid_code"))
    elif any(t.api_name == api_name for t in types):
        problems.append(Problem("api_name", "asset_api_name_taken"))
    problems += await _type_problems(session, values, types, type_id=None)
    parent = next((t for t in types if t.id == values.get("parent_id")), None)
    if parent is None and values.get("parent_id") is None:
        for field in ("category", "kind"):
            if field not in values:
                problems.append(Problem(field, "required"))
    if len(types) >= TYPES_MAX:
        problems.append(Problem("names", "too_many_items", (("max", TYPES_MAX),)))
    _refuse(problems)
    row = AssetProductType(
        id=new_id(),
        tenant_id=_tenant(session),
        parent_id=parent.id if parent else None,
        api_name=api_name,
        names=names,
        icon=values.get("icon"),
        category=parent.category if parent else values["category"],
        kind=parent.kind if parent else values["kind"],
        description=values.get("description"),
        life_cycle_id=values.get("life_cycle_id"),
        tag_pattern=values.get("tag_pattern"),
        ack_required=bool(values.get("ack_required", False)),
        sort=max(
            (t.sort for t in types if t.parent_id == (parent.id if parent else None)), default=-1
        )
        + 1,
        created_by=subject.user_id,
    )
    session.add(row)
    await session.flush()
    changes = [
        Change(f, None, _json(getattr(row, f)))
        for f in ("api_name", "names", "parent_id", "category", "kind", "icon", "life_cycle_id")
        if getattr(row, f) is not None
    ]
    await _saved(
        session, subject, row, changes, kind="product_type", action="created", source=source
    )
    return row


async def update_product_type(  # noqa: PLR0913, C901 - the If-Match and the source; one rule per field
    session: AsyncSession,
    subject: Subject,
    type_id: uuid.UUID,
    values: Mapping[str, Any],
    *,
    expected_version: int,
    source: Source,
) -> AssetProductType:
    """Change a type. Category and kind are set on top-level types and flow down the tree."""
    require_configure(subject)
    types = await list_product_types(session)
    row = await _locked(session, AssetProductType, type_id, "asset_product_type_not_found")
    await _fresh(session, row, expected_version, "asset_product_type")
    problems = await _type_problems(session, values, types, type_id=row.id)
    wanted: dict[str, Any] = {}
    if "names" in values:
        names, name_problems = clean_names("names", values["names"])
        problems += name_problems
        wanted["names"] = names
    for field in ("icon", "description", "life_cycle_id", "tag_pattern", "ack_required", "sort"):
        if field in values:
            wanted[field] = values[field]
    new_parent = values.get("parent_id", row.parent_id)
    parent = next((t for t in types if t.id == new_parent), None)
    if "parent_id" in values:
        wanted["parent_id"] = new_parent
    if parent is not None:
        # Under a parent, the type follows it (D-141: IT or not is inherited down the tree).
        for field in ("category", "kind"):
            if field in values and values[field] != getattr(parent, field):
                problems.append(Problem(field, "asset_product_type_inherited"))
        wanted["category"], wanted["kind"] = parent.category, parent.kind
    else:
        for field in ("category", "kind"):
            if field in values:
                wanted[field] = values[field]
    _refuse(problems)
    changes = _apply(row, wanted)
    if changes:
        await _saved(
            session, subject, row, changes, kind="product_type", action="updated", source=source
        )
    if {"category", "kind"} & {c.field for c in changes}:
        await _cascade(session, subject, row, types, source)
    return row


async def _cascade(
    session: AsyncSession,
    subject: Subject,
    top: AssetProductType,
    types: Sequence[AssetProductType],
    source: Source,
) -> None:
    """Every type below `top` takes its category and kind."""
    parents = {str(t.id): (str(t.parent_id) if t.parent_id else None) for t in types}
    below = descendants(str(top.id), parents)
    for item in types:
        if str(item.id) not in below or item.id == top.id:
            continue
        locked = await _locked(session, AssetProductType, item.id, "asset_product_type_not_found")
        changes = _apply(locked, {"category": top.category, "kind": top.kind})
        if changes:
            await _saved(
                session,
                subject,
                locked,
                changes,
                kind="product_type",
                action="updated",
                source=source,
            )


async def delete_product_type(
    session: AsyncSession,
    subject: Subject,
    type_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> None:
    """Soft delete: never one with types below it or products of it (REQ-AST-003 AC3)."""
    require_configure(subject)
    await ensure_defaults(session)
    row = await _locked(session, AssetProductType, type_id, "asset_product_type_not_found")
    await _fresh(session, row, expected_version, "asset_product_type")
    children = await session.scalar(
        select(func.count())
        .select_from(AssetProductType)
        .where(AssetProductType.parent_id == row.id, AssetProductType.deleted_at.is_(None))
    )
    if children:
        raise Conflict(code="asset_product_type_has_children", params={"used": int(children)})
    products = await session.scalar(
        select(func.count())
        .select_from(AssetProduct)
        .where(AssetProduct.product_type_id == row.id, AssetProduct.deleted_at.is_(None))
    )
    if products:
        raise Conflict(code="asset_product_type_in_use", params={"used": int(products)})
    row.deleted_at = datetime.now(UTC)
    changes = [Change("deleted_at", None, row.deleted_at.isoformat())]
    await _saved(
        session, subject, row, changes, kind="product_type", action="deleted", source=source
    )


# --- products (REQ-AST-005) -------------------------------------------------------------------

PRODUCT_FIELDS = ResourceFields(
    name="asset_products",
    fields={
        "id": FilterField(AssetProduct.id, FieldType.UUID),
        "name": FilterField(AssetProduct.name, FieldType.STRING, sortable=True),
        "manufacturer": FilterField(AssetProduct.manufacturer, FieldType.STRING, sortable=True),
        "part_number": FilterField(AssetProduct.part_number, FieldType.STRING),
        "product_type_id": FilterField(AssetProduct.product_type_id, FieldType.UUID),
        "hide_from_purchase_orders": FilterField(
            AssetProduct.hide_from_purchase_orders, FieldType.BOOLEAN
        ),
        "updated_at": FilterField(
            AssetProduct.updated_at, FieldType.DATETIME, sortable=True, simple=False
        ),
    },
    id_column=AssetProduct.id,
    default_sort=("name",),
)

PRODUCT_TEXT = {
    "name": NAME_MAX,
    "manufacturer": NAME_MAX,
    "part_number": PART_MAX,
    "gl_code": GL_MAX,
    "description": TEXT_MAX,
}
PRODUCT_EDITABLE = (
    "product_type_id",
    "name",
    "manufacturer",
    "part_number",
    "price",
    "tax",
    "currency",
    "gl_code",
    "hide_from_purchase_orders",
    "depreciation_method",
    "useful_life_years",
    "salvage_value",
    "description",
)


def products_query() -> Any:  # noqa: ANN401 - a Select the listing helper pages through
    """Live products (the list filters and pages this)."""
    return select(AssetProduct).where(AssetProduct.deleted_at.is_(None))


async def _product_problems(session: AsyncSession, values: Mapping[str, Any]) -> list[Problem]:
    problems: list[Problem] = []
    for field, limit in PRODUCT_TEXT.items():
        value = values.get(field)
        if isinstance(value, str) and len(value) > limit:
            problems.append(Problem(field, "value_too_long", (("max", limit),)))
    if "name" in values and not (values["name"] or "").strip():
        problems.append(Problem("name", "required"))
    for field in ("price", "tax", "salvage_value"):
        problems += amount_problems(field, values.get(field))
    currency = values.get("currency")
    if currency is not None and not CURRENCY.match(currency):
        problems.append(Problem("currency", "invalid_currency"))
    method = values.get("depreciation_method")
    if method is not None and method not in set(AssetDepreciationMethod):
        problems.append(Problem("depreciation_method", "invalid_choice"))
    years = values.get("useful_life_years")
    if years is not None and not 1 <= years <= 100:  # noqa: PLR2004 - the column's range
        problems.append(Problem("useful_life_years", "out_of_range", (("min", 1), ("max", 100))))
    if "product_type_id" in values and not await session.scalar(
        select(AssetProductType.id).where(
            AssetProductType.id == values["product_type_id"],
            AssetProductType.deleted_at.is_(None),
        )
    ):
        problems.append(Problem("product_type_id", "asset_product_type_not_found"))
    return problems


def _clean_product(values: Mapping[str, Any]) -> dict[str, Any]:
    cleaned = {k: v for k, v in values.items() if k in PRODUCT_EDITABLE}
    for field in PRODUCT_TEXT:
        if isinstance(cleaned.get(field), str):
            cleaned[field] = cleaned[field].strip() or None
    if cleaned.get("name") is None and "name" in cleaned:
        cleaned["name"] = ""
    return cleaned


async def get_product(session: AsyncSession, product_id: uuid.UUID) -> AssetProduct:
    """One live product, or 404."""
    row = await session.scalar(
        select(AssetProduct).where(AssetProduct.id == product_id, AssetProduct.deleted_at.is_(None))
    )
    if row is None:
        raise NotFound(code="asset_product_not_found")
    return row


async def create_product(
    session: AsyncSession, subject: Subject, values: Mapping[str, Any], *, source: Source
) -> AssetProduct:
    """A new product of a type."""
    require_configure(subject)
    await ensure_defaults(session)
    cleaned = _clean_product(values)
    problems = await _product_problems(session, cleaned)
    if "product_type_id" not in cleaned:
        problems.append(Problem("product_type_id", "required"))
    _refuse(problems)
    row = AssetProduct(
        id=new_id(),
        tenant_id=_tenant(session),
        created_by=subject.user_id,
        **{"hide_from_purchase_orders": False, **cleaned},
    )
    session.add(row)
    await session.flush()
    changes = [Change(f, None, _json(v)) for f, v in cleaned.items() if v is not None]
    await _saved(session, subject, row, changes, kind=None, action="created", source=source)
    return row


async def update_product(  # noqa: PLR0913 - the If-Match and the source
    session: AsyncSession,
    subject: Subject,
    product_id: uuid.UUID,
    values: Mapping[str, Any],
    *,
    expected_version: int,
    source: Source,
) -> AssetProduct:
    """Change the fields sent. Assets keep the cost they were bought at (REQ-AST-005 AC2)."""
    require_configure(subject)
    row = await _locked(session, AssetProduct, product_id, "asset_product_not_found")
    await _fresh(session, row, expected_version, "asset_product")
    cleaned = _clean_product(values)
    _refuse(await _product_problems(session, cleaned))
    changes = _apply(row, cleaned)
    if changes:
        await _saved(session, subject, row, changes, kind=None, action="updated", source=source)
    return row


async def delete_product(
    session: AsyncSession,
    subject: Subject,
    product_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> None:
    """Soft delete (session 2 refuses it while assets use the product)."""
    require_configure(subject)
    row = await _locked(session, AssetProduct, product_id, "asset_product_not_found")
    await _fresh(session, row, expected_version, "asset_product")
    row.deleted_at = datetime.now(UTC)
    changes = [Change("deleted_at", None, row.deleted_at.isoformat())]
    await _saved(session, subject, row, changes, kind=None, action="deleted", source=source)


def product_total(product: AssetProduct) -> Decimal | None:
    """Price plus tax (D-141: the total is never stored on its own)."""
    if product.price is None and product.tax is None:
        return None
    return (product.price or Decimal(0)) + (product.tax or Decimal(0))
