"""Each tenant's work item configuration: seeded on first use, read for every write (WP-020).

The Appendix A defaults (statuses and transitions, reason lists, impact / urgency / priority
scales, the priority matrix, a starting category tree, the display prefix) are copied into the
tenant's own rows the first time anything of a type is read or written, inside that transaction.
Admins edit the copies (labels, colours, reasons, matrix, prefix, categories; WP-020c, D-056);
structural life-cycle changes wait for the designer (REQ-INC-049).

Seeding is idempotent and safe under concurrency: the type-settings row is inserted with ON
CONFLICT DO NOTHING, and only the transaction that inserted it writes the rest, so two first
requests at the same moment never seed twice (the second waits for the first's row lock).

Defaults added later (WP-020c: levels, closure codes, the standard template) are versioned:
`seed_version` says what a tenant has, and an older tenant is topped up by whichever transaction
moves its `seed_version` forward first (UPDATE ... WHERE seed_version < n RETURNING).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.tenancy import TenantContext
from app.modules.organization import default_desk_id
from app.modules.work_items.domain.classification import (
    DEFAULT_COLOURS,
    DEFAULT_MATRIX,
    DEFAULT_PRIORITY,
    SCALE_CODES,
)
from app.modules.work_items.domain.lifecycle import (
    DEFAULT_REASONS,
    Lifecycle,
    ReasonList,
    ReasonMode,
    StatusCategory,
    StatusDef,
    TransitionDef,
    WorkItemAction,
)
from app.modules.work_items.domain.templates import (
    DEFAULT_LIST_VALUES,
    PickList,
    default_rules,
    rules_to_json,
)
from app.modules.work_items.domain.types import DEFAULT_CATEGORIES, WorkItemType
from app.modules.work_items.infra.models import (
    WorkItemCategory,
    WorkItemPriorityCell,
    WorkItemReason,
    WorkItemScaleValue,
    WorkItemStatus,
    WorkItemTemplate,
    WorkItemTransition,
    WorkItemTypeSettings,
)
from app.shared.db.display_ids import last_number
from app.shared.ids import new_id

# 1: WP-020 (life cycle, scales, matrix, reasons, categories); 2: WP-020c (levels, closure
# codes, the standard template).
SEED_VERSION = 2
STANDARD_TEMPLATE = "standard"


@dataclass(frozen=True)
class StatusInfo:
    """One status as screens show it."""

    code: str
    category: str
    colour: str
    labels: dict[str, str] | None
    system: bool
    disabled: bool


@dataclass(frozen=True)
class ScaleValue:
    """One impact, urgency or priority value."""

    scale: str
    code: str
    rank: int
    colour: str | None
    labels: dict[str, str] | None


@dataclass(frozen=True)
class ReasonInfo:
    """One value of a pick list (a reason list, levels or closure codes)."""

    list: str
    code: str
    labels: dict[str, str] | None
    sort_order: int = 0
    colour: str | None = None
    disabled: bool = False


@dataclass(frozen=True)
class Catalogue:
    """Everything a write or a screen needs to know about one type's configuration."""

    prefix: str
    default_priority: str
    auto_status_on_assign: bool
    keep_following_on_handover: bool
    first_response_on: tuple[str, ...]
    settings_version: int
    default_impact: str | None
    default_urgency: str | None
    lifecycle: Lifecycle
    statuses: list[StatusInfo]
    matrix: Mapping[tuple[str, str], str]
    scales: list[ScaleValue]
    reasons: list[ReasonInfo]  # every pick list, retired values included (marked)
    last_number: int = 0  # the last display number handed out (0: none yet)

    def reason_codes(self, reason_list: ReasonList | PickList | None) -> list[str]:
        """Enabled codes of a pick list (offered for new input)."""
        if reason_list is None:
            return []
        return [r.code for r in self.reasons if r.list == reason_list and not r.disabled]

    def list_values(self, pick_list: PickList) -> list[ReasonInfo]:
        """Every value of a pick list in order, retired ones included."""
        return [r for r in self.reasons if r.list == pick_list]


def tenant_of(session: AsyncSession) -> Any:  # noqa: ANN401 - uuid of the session's tenant
    """The tenant of a tenant session (for rows whose tenant is part of the key)."""
    context = session.info.get(SESSION_TENANT_KEY)
    if not isinstance(context, TenantContext):  # pragma: no cover - every request has one
        msg = "work item configuration needs a tenant session"
        raise TypeError(msg)
    return context.tenant_id


async def ensure_seeded(session: AsyncSession, wtype: WorkItemType) -> None:
    """Copy the defaults of `wtype` into the tenant's rows once (idempotent)."""
    tenant = tenant_of(session)
    existing = await session.scalar(
        select(WorkItemTypeSettings.seed_version).where(WorkItemTypeSettings.type == wtype.code)
    )
    if existing is not None:
        if existing < SEED_VERSION:
            await _top_up(session, wtype, tenant)
        return
    inserted = await session.scalar(
        insert(WorkItemTypeSettings)
        .values(
            tenant_id=tenant,
            type=wtype.code,
            prefix=wtype.default_prefix,
            default_priority=DEFAULT_PRIORITY,
            seed_version=SEED_VERSION,
        )
        .on_conflict_do_nothing()
        .returning(WorkItemTypeSettings.type)
    )
    if inserted is None:  # another transaction seeded it first
        return
    _seed_v2(session, wtype, tenant, await default_desk_id(session))
    rows: list[Any] = [
        WorkItemStatus(
            tenant_id=tenant,
            type=wtype.code,
            code=s.code,
            category=s.category,
            colour=s.colour,
            sort_order=index,
            system=s.system,
        )
        for index, s in enumerate(wtype.statuses)
    ]
    session.add_all(rows)
    await session.flush()
    session.add_all(
        [
            WorkItemTransition(
                tenant_id=tenant,
                type=wtype.code,
                from_status=t.from_status,
                action=t.action,
                to_status=t.to_status,
                reason_mode=t.reason_mode,
                reason_list=t.reason_list,
            )
            for t in wtype.transitions
        ]
        + [
            WorkItemReason(tenant_id=tenant, type=wtype.code, list=lst, code=code, sort_order=i)
            for lst, codes in DEFAULT_REASONS.items()  # the WP-020 reason lists
            for i, code in enumerate(codes)
        ]
        + [
            WorkItemScaleValue(
                tenant_id=tenant,
                type=wtype.code,
                scale=scale,
                code=code,
                rank=rank,
                colour=DEFAULT_COLOURS.get(code),
            )
            for scale, codes in SCALE_CODES.items()
            for rank, code in enumerate(codes, start=1)
        ]
        + [
            WorkItemPriorityCell(
                tenant_id=tenant, type=wtype.code, impact=impact, urgency=urgency, priority=p
            )
            for (impact, urgency), p in DEFAULT_MATRIX.items()
        ]
    )
    for order, (code, children) in enumerate(DEFAULT_CATEGORIES.items()):
        parent = WorkItemCategory(
            id=new_id(),
            tenant_id=tenant,
            type=wtype.code,
            level=1,
            code=code,
            sort_order=order,
        )
        session.add(parent)
        for child_order, (child, items) in enumerate(children.items()):
            node = WorkItemCategory(
                id=new_id(),
                tenant_id=tenant,
                type=wtype.code,
                parent_id=parent.id,
                level=2,
                code=child,
                sort_order=child_order,
            )
            session.add(node)
            for item_order, item in enumerate(items):
                session.add(
                    WorkItemCategory(
                        tenant_id=tenant,
                        type=wtype.code,
                        parent_id=node.id,
                        level=3,
                        code=item,
                        sort_order=item_order,
                    )
                )
        await session.flush()
    await session.flush()


def _seed_v2(session: AsyncSession, wtype: WorkItemType, tenant: Any, desk: Any) -> None:  # noqa: ANN401 - uuids
    """Levels, closure codes and the standard (default) template."""
    session.add_all(
        [
            WorkItemReason(tenant_id=tenant, type=wtype.code, list=lst, code=code, sort_order=i)
            for lst, codes in DEFAULT_LIST_VALUES.items()
            for i, code in enumerate(codes)
        ]
    )
    session.add(
        WorkItemTemplate(
            tenant_id=tenant,
            type=wtype.code,
            code=STANDARD_TEMPLATE,
            is_default=True,
            desk_id=desk,
            field_rules=rules_to_json(default_rules()),
            defaults={},
        )
    )


async def _top_up(session: AsyncSession, wtype: WorkItemType, tenant: Any) -> None:  # noqa: ANN401 - uuid
    """Give a tenant seeded by an older version the newer defaults, exactly once."""
    moved = await session.scalar(
        update(WorkItemTypeSettings)
        .where(
            WorkItemTypeSettings.type == wtype.code,
            WorkItemTypeSettings.seed_version < SEED_VERSION,
        )
        .values(seed_version=SEED_VERSION)
        .returning(WorkItemTypeSettings.seed_version)
    )
    if moved is None:  # another transaction topped it up first
        return
    _seed_v2(session, wtype, tenant, await default_desk_id(session))
    await session.flush()


async def load(session: AsyncSession, wtype: WorkItemType) -> Catalogue:
    """The tenant's configuration of `wtype` (seeding it first if needed)."""
    await ensure_seeded(session, wtype)
    settings = await session.scalar(
        select(WorkItemTypeSettings).where(WorkItemTypeSettings.type == wtype.code)
    )
    if settings is None:  # pragma: no cover - ensure_seeded just made it
        msg = "type settings missing after seeding"
        raise RuntimeError(msg)
    status_rows = list(
        await session.scalars(
            select(WorkItemStatus)
            .where(WorkItemStatus.type == wtype.code)
            .order_by(WorkItemStatus.sort_order, WorkItemStatus.code)
        )
    )
    transition_rows = list(
        await session.scalars(
            select(WorkItemTransition).where(WorkItemTransition.type == wtype.code)
        )
    )
    lifecycle = Lifecycle.build(
        [StatusDef(s.code, StatusCategory(s.category), s.colour, s.system) for s in status_rows],
        [
            TransitionDef(
                t.from_status,
                WorkItemAction(t.action),
                t.to_status,
                ReasonMode(t.reason_mode),
                ReasonList(t.reason_list) if t.reason_list else None,
            )
            for t in transition_rows
        ],
    )
    cells = await session.scalars(
        select(WorkItemPriorityCell).where(WorkItemPriorityCell.type == wtype.code)
    )
    scales = await session.scalars(
        select(WorkItemScaleValue)
        .where(WorkItemScaleValue.type == wtype.code)
        .order_by(WorkItemScaleValue.scale, WorkItemScaleValue.rank)
    )
    reasons = await session.scalars(
        select(WorkItemReason)
        .where(WorkItemReason.type == wtype.code)
        .order_by(WorkItemReason.list, WorkItemReason.sort_order, WorkItemReason.code)
    )
    return Catalogue(
        prefix=settings.prefix,
        default_priority=settings.default_priority,
        auto_status_on_assign=settings.auto_status_on_assign,
        keep_following_on_handover=settings.keep_following_on_handover,
        first_response_on=tuple(settings.first_response_on),
        settings_version=settings.version,
        default_impact=settings.default_impact,
        default_urgency=settings.default_urgency,
        lifecycle=lifecycle,
        statuses=[
            StatusInfo(s.code, s.category, s.colour, s.labels, s.system, s.disabled_at is not None)
            for s in status_rows
        ],
        matrix={(c.impact, c.urgency): c.priority for c in cells},
        scales=[ScaleValue(v.scale, v.code, v.rank, v.colour, v.labels) for v in scales],
        reasons=[
            ReasonInfo(r.list, r.code, r.labels, r.sort_order, r.colour, r.disabled_at is not None)
            for r in reasons
        ],
        last_number=await last_number(session, wtype.counter_key),
    )
