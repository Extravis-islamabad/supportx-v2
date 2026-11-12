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

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.tenancy import TenantContext
from app.modules.audit import WORKER as AUDIT_WORKER
from app.modules.audit import record as record_audit
from app.modules.organization import default_desk_id
from app.modules.work_items.domain import changes as change_rules
from app.modules.work_items.domain.classification import (
    DEFAULT_COLOURS,
    DEFAULT_MATRIX,
    DEFAULT_PRIORITY,
    SCALE_CODES,
)
from app.modules.work_items.domain.lifecycle import (
    DEFAULT_REASONS,
    USER_ACTIONS,
    DefaultStatus,
    Lifecycle,
    ReasonList,
    ReasonMode,
    StatusCategory,
    StatusDef,
    TransitionDef,
    WorkItemAction,
)
from app.modules.work_items.domain.stages import DEFAULT_PATH, FIRST_LIFECYCLE, StageModel
from app.modules.work_items.domain.templates import (
    CONFIRMED_BY_REQUESTER,
    DEFAULT_LIST_VALUES,
    PROBLEM_LIST_VALUES,
    PickList,
    default_rules,
    rules_to_json,
)
from app.modules.work_items.domain.types import (
    DEFAULT_CATEGORIES,
    GUIDED_ANALYSIS,
    STANDARD_LIFECYCLE,
    WorkItemType,
    WorkItemTypeCode,
)
from app.modules.work_items.infra.models import (
    WorkItemCategory,
    WorkItemPathStage,
    WorkItemPriorityCell,
    WorkItemReason,
    WorkItemRoleDef,
    WorkItemScaleValue,
    WorkItemStage,
    WorkItemStagePath,
    WorkItemStatus,
    WorkItemStatusTransition,
    WorkItemTemplate,
    WorkItemTransition,
    WorkItemTypeSettings,
)
from app.shared.db.display_ids import last_number
from app.shared.history import FieldChange
from app.shared.ids import new_id

# 1: WP-020 (life cycle, scales, matrix, reasons, categories); 2: WP-020c (levels, closure
# codes, the standard template).
# The settings' history record type (settings.SETTINGS_RECORD_TYPE; that module imports this one).
SETTINGS_RECORD_TYPE = "work_item_settings"


def settings_record_id(code: str) -> uuid.UUID:
    """The id a type's settings history is kept under (one place, not one per writer)."""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"work_item_settings:{code}")


SEED_VERSION = 4  # 3: the closure code "confirmed by requester" (D-107); 4: staged roles, approvals
STANDARD_TEMPLATE = "standard"
MAJOR_PROBLEM_TEMPLATE = "major_problem"  # REQ-PRB-017, Appendix A: the guided life cycle


@dataclass(frozen=True)
class StatusInfo:
    """One status as screens show it."""

    code: str
    category: str
    colour: str
    labels: dict[str, str] | None
    system: bool
    disabled: bool
    # A requester reply moves a record in this paused status back to in progress (REQ-INC-051).
    resume_on_requester_reply: bool = False


@dataclass(frozen=True)
class ClosureSettings:
    """Closing rules of one type (WP-020f; REQ-INC-094..098)."""

    resolve_requires: tuple[str, ...]
    close_requires: tuple[str, ...]
    open_work: Mapping[str, str]
    complete_open_work: bool
    auto_close_days: int | None
    reopen_window_days: int
    task_owner_access: bool = False  # WP-020e (D-112)
    task_dependency_mode: str = "block"  # WP-046a S1 (REQ-INC-075): block or warn


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
    attributes: Mapping[str, Any] | None = None  # LIST_ATTRIBUTES (0093)


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
    on_behalf_scope: str  # WP-030, REQ-SR-011
    approvals_hidden_from_requesters: bool  # WP-030 s2, REQ-SR-024 AC3
    approvals_require_sign_in: bool  # D-132: e-mailed approval links need a signed-in approver
    first_task_starts_work: bool  # D-154c: the first ticked task moves a request on
    portal_show_due_time: bool  # WP-028 D5: requesters see the expected resolution time
    review_required_priorities: tuple[str, ...]  # WP-044b s4: problems needing a review
    segregation_strict: bool  # WP-045b S3: changes, implementing groups barred too
    outside_maintenance_blocks: bool  # D-156: changes outside every maintenance window blocked
    open_stage_tasks_block: bool  # WP-058b S3: releases, a stage's open tasks hold its move out
    cab_every_match: bool  # WP-045b S3: changes go to every matching board
    reapproval: Mapping[str, Any] | None  # WP-045b S4: the stored policy (None: shipped)
    lifecycle: Lifecycle  # the standard one; a record follows `lifecycle_of(record.lifecycle)`
    lifecycles: Mapping[str, Lifecycle]  # every transition set by code (WP-044a s4)
    statuses: list[StatusInfo]
    matrix: Mapping[tuple[str, str], str]
    scales: list[ScaleValue]
    reasons: list[ReasonInfo]  # every pick list, retired values included (marked)
    closure: ClosureSettings
    last_number: int = 0  # the last display number handed out (0: none yet)

    def lifecycle_of(self, code: str | None) -> Lifecycle:
        """The transition set a record follows; the standard one for an unknown code."""
        return self.lifecycles.get(code or STANDARD_LIFECYCLE, self.lifecycle)

    def used_actions(self) -> list[WorkItemAction]:
        """Every user action any of the type's transition sets has, in the fixed order."""
        used = {a for lc in self.lifecycles.values() for a in lc.used_actions()}
        return [a for a in USER_ACTIONS if a in used]

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
            await _top_up(session, wtype, tenant, existing)
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
    staged = wtype.stages
    if staged is not None:  # ADR-041: the stages first, their statuses point at them
        session.add_all(
            [
                WorkItemStage(
                    tenant_id=tenant,
                    type=wtype.code,
                    code=st.code,
                    sort_order=i,
                    system=True,
                    approvals=dict(wtype.stage_approvals[st.code])
                    if st.code in wtype.stage_approvals
                    else None,
                )
                for i, st in enumerate(staged.stages)
            ]
        )
        await session.flush()
    rows: list[Any] = [
        WorkItemStatus(
            tenant_id=tenant,
            type=wtype.code,
            code=s.code,
            category=s.category,
            colour=s.colour,
            sort_order=index,
            system=s.system,
            # Appendix A: awaiting requester -> in progress on a requester reply (REQ-INC-051).
            resume_on_requester_reply=s.code == DefaultStatus.AWAITING_REQUESTER,
            **_stage_columns(staged, s.code),
        )
        for index, s in enumerate(wtype.statuses)
    ]
    session.add_all(rows)
    await session.flush()
    if staged is not None:
        await _seed_stage_moves(session, wtype.code, staged, tenant)
        await _seed_path_templates(session, wtype.code, staged, tenant)
    session.add_all(
        [
            WorkItemRoleDef(
                tenant_id=tenant,
                type=wtype.code,
                code=code,
                sort_order=i,
                system=True,
                # Releases: one person per role (REQ-REL-023); changes: people or groups.
                single=wtype.code is not WorkItemTypeCode.CHANGE
                or code in change_rules.SINGLE_ROLES,
            )
            for i, code in enumerate(wtype.roles)
        ]
    )
    session.add_all(
        [
            WorkItemReason(
                tenant_id=tenant, type=wtype.code, list=lst, code=code, sort_order=i, colour=colour
            )
            for lst, values in wtype.own_lists.items()
            for i, (code, colour) in enumerate(values)
        ]
    )
    session.add_all(
        [
            WorkItemTransition(
                tenant_id=tenant,
                type=wtype.code,
                lifecycle=code,
                from_status=t.from_status,
                action=t.action,
                to_status=t.to_status,
                reason_mode=t.reason_mode,
                reason_list=t.reason_list,
            )
            for code, transitions in wtype.lifecycles.items()
            for t in transitions
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


def _stage_columns(staged: StageModel | None, code: str) -> dict[str, Any]:
    """A staged status's stage, completing flag and who sets it (ADR-041 §2)."""
    if staged is None:
        return {}
    status = staged.status(code)
    return {"stage": status.stage, "completing": status.completing, "set_by": status.set_by}


async def _seed_stage_moves(
    session: AsyncSession, type_code: str, staged: StageModel, tenant: uuid.UUID
) -> None:
    """Paths, their stages and the listed status moves (ADR-041 §3, §4), life cycle 1."""
    session.add_all(
        [
            WorkItemStagePath(
                tenant_id=tenant,
                type=type_code,
                code=p.code,
                lifecycle_version=FIRST_LIFECYCLE,
                system=True,
            )
            for p in staged.paths
        ]
    )
    await session.flush()
    session.add_all(
        [
            WorkItemPathStage(
                tenant_id=tenant,
                type=type_code,
                path=p.code,
                stage=stage,
                sort_order=i,
                optional=stage in p.optional,
            )
            for p in staged.paths
            for i, stage in enumerate(p.stages)
        ]
        + [
            WorkItemStatusTransition(
                tenant_id=tenant,
                type=type_code,
                path=t.path,
                lifecycle_version=FIRST_LIFECYCLE,
                from_status=t.from_status,
                to_status=t.to_status,
                reason_mode=t.reason_mode,
                reason_list=t.reason_list,
                permission=t.permission,
                required_fields=list(t.required_fields) or None,
            )
            for t in staged.transitions
        ]
    )
    await session.flush()


async def _seed_path_templates(
    session: AsyncSession, type_code: str, staged: StageModel, tenant: uuid.UUID
) -> None:
    """One template per path (REQ-REL-011), or for changes one per change type (REQ-CHG-022).

    The standard one follows the default path; each other path gets a template of its own name
    (releases: emergency, Appendix A). Changes: Appendix A's five templates, each binding its
    type (`defaults.change_type`) and that type's path; the default one is the normal change.
    """
    if type_code == WorkItemTypeCode.CHANGE:
        await _seed_change_templates(session, type_code, tenant)
        return
    await session.execute(
        update(WorkItemTemplate)
        .where(WorkItemTemplate.type == type_code, WorkItemTemplate.code == STANDARD_TEMPLATE)
        .values(stage_path=DEFAULT_PATH)
    )
    desk = await default_desk_id(session)
    session.add_all(
        [
            WorkItemTemplate(
                tenant_id=tenant,
                type=type_code,
                code=p.code,
                is_default=False,
                desk_id=desk,
                field_rules=rules_to_json(default_rules()),
                defaults={},
                stage_path=p.code,
            )
            for p in staged.paths
            if p.code != DEFAULT_PATH
        ]
    )
    await session.flush()


async def _seed_change_templates(session: AsyncSession, type_code: str, tenant: uuid.UUID) -> None:
    def bound(code: str) -> dict[str, Any]:
        model = change_rules.model_of(code, None)
        return {"defaults": {"change_type": code}, "stage_path": change_rules.path_of(code, model)}

    default_type = change_rules.ChangeModel.NORMAL.value
    await session.execute(
        update(WorkItemTemplate)
        .where(WorkItemTemplate.type == type_code, WorkItemTemplate.code == STANDARD_TEMPLATE)
        .values(code=default_type, **bound(default_type))
    )
    desk = await default_desk_id(session)
    session.add_all(
        [
            WorkItemTemplate(
                tenant_id=tenant,
                type=type_code,
                code=code,
                is_default=False,
                desk_id=desk,
                field_rules=rules_to_json(default_rules()),
                **bound(code),
            )
            for code, _colour in change_rules.CHANGE_TYPES
            if code != default_type
        ]
    )
    await session.flush()


def _seed_v2(session: AsyncSession, wtype: WorkItemType, tenant: Any, desk: Any) -> None:  # noqa: ANN401 - uuids
    """Levels, closure codes and the standard (default) template."""
    session.add_all(
        [
            WorkItemReason(tenant_id=tenant, type=wtype.code, list=lst, code=code, sort_order=i)
            for lst, codes in {
                **DEFAULT_LIST_VALUES,
                **(PROBLEM_LIST_VALUES if wtype.code is WorkItemTypeCode.PROBLEM else {}),
            }.items()
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
    if wtype.code is WorkItemTypeCode.PROBLEM:
        session.add(
            WorkItemTemplate(
                tenant_id=tenant,
                type=wtype.code,
                code=MAJOR_PROBLEM_TEMPLATE,
                desk_id=desk,
                field_rules=rules_to_json(default_rules()),
                defaults={},
                lifecycle=GUIDED_ANALYSIS,
            )
        )


async def _top_up(
    session: AsyncSession, wtype: WorkItemType, tenant: uuid.UUID, existing: int
) -> None:
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
    if existing < 2:  # noqa: PLR2004 - the seed version that added levels, codes, templates
        _seed_v2(session, wtype, tenant, await default_desk_id(session))
        await session.flush()
    await _seed_v3(session, wtype, tenant)
    await session.flush()
    if existing < 4:  # noqa: PLR2004 - the seed version that tops up a staged type's roles
        await _seed_v4(session, wtype, tenant)
        await session.flush()


async def _seed_v4(session: AsyncSession, wtype: WorkItemType, tenant: uuid.UUID) -> None:
    """A staged type seeded before its roles and stage approvals existed gets them (QA10-P4-29).

    Such a tenant had no role definitions (an empty Roles tab) and no stage approvals, so a
    release waiting for its plan approval had nobody to approve it and no move out. Only ever
    adds what is missing, once (the seed version moves under its row lock first), and never
    when an administrator has changed this type's stages or roles: their settings history shows
    it, and their choice (an approval removed on purpose) is kept. Each top-up is audited.
    """
    if wtype.stages is None:
        return
    settings_id = settings_record_id(wtype.code)
    edited = await session.scalar(
        select(FieldChange.id)
        .where(
            FieldChange.record_type == SETTINGS_RECORD_TYPE,
            FieldChange.record_id == settings_id,
            or_(FieldChange.field.startswith("stages."), FieldChange.field.startswith("roles.")),
        )
        .limit(1)
    )
    if edited is not None:
        return
    held = set(
        (
            await session.scalars(
                # The tenant as well as RLS (lane A's review): never another tenant's roles.
                select(WorkItemRoleDef.code).where(
                    WorkItemRoleDef.tenant_id == tenant, WorkItemRoleDef.type == wtype.code
                )
            )
        ).all()
    )
    roles_added = [code for code in wtype.roles if code not in held]
    for code in roles_added:
        await session.execute(
            insert(WorkItemRoleDef)
            .values(
                tenant_id=tenant,
                type=wtype.code,
                code=code,
                sort_order=wtype.roles.index(code),
                system=True,
            )
            .on_conflict_do_nothing()
        )
    any_approvals = await session.scalar(
        select(WorkItemStage.code)
        .where(WorkItemStage.type == wtype.code, WorkItemStage.approvals.is_not(None))
        .limit(1)
    )
    stages_added: list[str] = []
    if not held and any_approvals is None:  # that older seed: no roles, no approvals at all
        for stage, defaults in wtype.stage_approvals.items():
            filled = await session.scalar(
                update(WorkItemStage)
                .where(
                    WorkItemStage.type == wtype.code,
                    WorkItemStage.code == stage,
                    WorkItemStage.approvals.is_(None),
                )
                .values(approvals=dict(defaults))
                .returning(WorkItemStage.code)
            )
            if filled is not None:
                stages_added.append(stage)
    if roles_added or stages_added:
        await record_audit(
            session,
            action_code="work_item.settings_topped_up",
            facts=AUDIT_WORKER,
            object_type="work_item_settings",
            object_id=settings_id,
            details={"type": wtype.code, "roles": roles_added, "stage_approvals": stages_added},
        )


async def _seed_v3(session: AsyncSession, wtype: WorkItemType, tenant: uuid.UUID) -> None:
    """The closure code "confirmed by requester" (D-107); kept when a tenant already has it."""
    await session.execute(
        insert(WorkItemReason)
        .values(
            tenant_id=tenant,
            type=wtype.code,
            list=PickList.CLOSURE_CODE.value,
            code=CONFIRMED_BY_REQUESTER,
            sort_order=len(DEFAULT_LIST_VALUES[PickList.CLOSURE_CODE]) - 1,
        )
        .on_conflict_do_nothing()
    )


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
    status_defs = [
        StatusDef(s.code, StatusCategory(s.category), s.colour, s.system) for s in status_rows
    ]
    lifecycles = {
        code: Lifecycle.build(
            status_defs,
            [
                TransitionDef(
                    t.from_status,
                    WorkItemAction(t.action),
                    t.to_status,
                    ReasonMode(t.reason_mode),
                    ReasonList(t.reason_list) if t.reason_list else None,
                )
                for t in transition_rows
                if t.lifecycle == code
            ],
        )
        # The standard set first, then the others by code.
        for code in [
            STANDARD_LIFECYCLE,
            *sorted({t.lifecycle for t in transition_rows} - {STANDARD_LIFECYCLE}),
        ]
    }
    lifecycle = lifecycles[STANDARD_LIFECYCLE]
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
        on_behalf_scope=settings.on_behalf_scope,
        approvals_hidden_from_requesters=settings.approvals_hidden_from_requesters,
        approvals_require_sign_in=settings.approvals_require_sign_in,
        first_task_starts_work=settings.first_task_starts_work,
        portal_show_due_time=settings.portal_show_due_time,
        review_required_priorities=tuple(settings.review_required_priorities),
        segregation_strict=settings.segregation_strict,
        outside_maintenance_blocks=settings.outside_maintenance_blocks,
        open_stage_tasks_block=settings.open_stage_tasks_block,
        cab_every_match=settings.cab_every_match,
        reapproval=settings.reapproval,
        first_response_on=tuple(settings.first_response_on),
        settings_version=settings.version,
        default_impact=settings.default_impact,
        default_urgency=settings.default_urgency,
        lifecycle=lifecycle,
        lifecycles=lifecycles,
        statuses=[
            StatusInfo(
                s.code,
                s.category,
                s.colour,
                s.labels,
                s.system,
                s.disabled_at is not None,
                s.resume_on_requester_reply,
            )
            for s in status_rows
        ],
        matrix={(c.impact, c.urgency): c.priority for c in cells},
        scales=[ScaleValue(v.scale, v.code, v.rank, v.colour, v.labels) for v in scales],
        reasons=[
            ReasonInfo(
                r.list,
                r.code,
                r.labels,
                r.sort_order,
                r.colour,
                r.disabled_at is not None,
                r.attributes,
            )
            for r in reasons
        ],
        closure=ClosureSettings(
            resolve_requires=tuple(settings.resolve_requires),
            close_requires=tuple(settings.close_requires),
            open_work=dict(settings.open_work),
            complete_open_work=settings.complete_open_work,
            auto_close_days=settings.auto_close_days,
            reopen_window_days=settings.reopen_window_days,
            task_owner_access=settings.task_owner_access,
            task_dependency_mode=settings.task_dependency_mode,
        ),
        last_number=await last_number(session, wtype.counter_key),
    )
