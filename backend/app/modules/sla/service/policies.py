"""SLA policies and settings (REQ-SLA-001..005; WP-025 session 2).

Every write: permission, rules (codes), versioned change, field history, outbox event. Each
record type has one fallback policy, created on first use with the defaults of wp-025-plan.md
§2 (D-074): it has no conditions, is always last and cannot be disabled or deleted. Other
policies are ordered; the first enabled one whose conditions match applies.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict, FieldError, NotFound, ValidationFailed
from app.modules import organization
from app.modules.identity_access import Subject, user_names
from app.modules.sla.domain.escalation import (
    Action,
    ActionKind,
    Anchor,
    Level,
    Recipient,
    RecipientKind,
    level_of,
    level_problems,
)
from app.modules.sla.domain.policy import (
    CalendarSource,
    PolicyRule,
    PriorityRule,
    ReopenRule,
    TargetKind,
    TargetRow,
    TargetUnit,
    never_matching,
    target_problems,
)
from app.modules.sla.events import (
    SlaPoliciesReordered,
    SlaPolicyDeleted,
    SlaPolicySaved,
    SlaSettingsSaved,
)
from app.modules.sla.infra.models import (
    SlaEscalationLevel,
    SlaPolicy,
    SlaPolicyTarget,
    SlaSettings,
)
from app.modules.sla.service.access import MANAGE, VIEW, require
from app.modules.sla.service.calendars import calendar_exists
from app.modules.sla.service.registry import SlaRecordType, record_type
from app.shared.api.filters import compile_filter
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.history import Change, Source, explain_conflict, record_changes
from app.shared.ids import new_id

RECORD_TYPE = "sla_policy"
SETTINGS_RECORD_TYPE = "sla_settings"
NAME_MAX = 200
WARNING_MIN, WARNING_MAX = 1, 99  # the share of a target after which it warns
LANGUAGES = frozenset({"en", "ar", "ur"})
FALLBACK_NAME = "Default policy"  # labelled `sla_policy.fallback` in the UI

FIELD_PROBLEMS = frozenset(
    {
        "required",
        "name_taken",
        "invalid_language",
        "target_duplicate",
        "target_amount_invalid",
        "fixed_calendar_required",
        "fixed_calendar_unused",
        "calendar_not_found",
        "unknown_priority",
        "fallback_fixed",
        "order_incomplete",
        # Escalation levels (session 3, domain/escalation.py).
        "too_many_levels",
        "levels_same_moment",
        "offset_too_large",
        "level_too_many_recipients",
        "level_too_many_actions",
        "level_does_nothing",
        "recipient_shape",
        "note_too_long",
        "unknown_reference",
    }
)

# The default incident policy (wp-025-plan.md §2): (priority, first response, resolution, source).
_H, _M, _D = TargetUnit.HOURS, TargetUnit.MINUTES, TargetUnit.BUSINESS_DAYS
_ATC, _SITE = CalendarSource.AROUND_THE_CLOCK, CalendarSource.SITE
DEFAULT_TARGETS: tuple[
    tuple[str, tuple[int, TargetUnit], tuple[int, TargetUnit], CalendarSource], ...
] = (
    ("p1", (15, _M), (4, _H), _ATC),
    ("p2", (30, _M), (8, _H), _SITE),
    ("p3", (4, _H), (3, _D), _SITE),
    ("p4", (8, _H), (5, _D), _SITE),
)


class PolicyRepository(Repository[SlaPolicy]):
    """Policies of the session's tenant."""

    model = SlaPolicy


@dataclass(frozen=True)
class PolicyView:
    """A policy with its target rows and whether anything can ever reach it."""

    policy: SlaPolicy
    targets: list[SlaPolicyTarget] = field(default_factory=list)
    never_matches: bool = False
    can_manage: bool = False
    levels: list[Level] = field(default_factory=list)


def _field(name: str, code: str, **params: Any) -> FieldError:  # noqa: ANN401 - label params
    return FieldError(
        field=f"body.{name}", code=code, message_key=f"errors.field.{code}", params=params
    )


def _type(code: str) -> SlaRecordType:
    found = record_type(code)
    if found is None:
        raise NotFound(code="sla_record_type_not_found", params={"record_type": code})
    return found


async def _names(session: AsyncSession, ids: Sequence[str]) -> Sequence[str]:
    found = await user_names(session, list(ids))
    return [found.get(i, "") for i in ids]


# --- defaults ---------------------------------------------------------------------------------


async def ensure_defaults(session: AsyncSession, code: str) -> None:
    """The settings row and the fallback policy of a record type (idempotent, D-041)."""
    context = session.info[SESSION_TENANT_KEY]
    await session.execute(
        insert(SlaSettings)
        .values(tenant_id=context.tenant_id, record_type=code)
        .on_conflict_do_nothing()
    )
    present = await session.scalar(
        select(SlaPolicy.id).where(
            SlaPolicy.record_type == code,
            SlaPolicy.fallback.is_(True),
            SlaPolicy.deleted_at.is_(None),
        )
    )
    if present is not None:
        return
    policy_id = new_id()
    inserted = await session.execute(
        insert(SlaPolicy)
        .values(
            id=policy_id,
            tenant_id=context.tenant_id,
            record_type=code,
            name=FALLBACK_NAME,
            labels={},
            position=1_000_000,
            fallback=True,
            enabled=True,
        )
        .on_conflict_do_nothing()
        .returning(SlaPolicy.id)
    )
    if inserted.scalar() is None:  # a parallel first request made it
        return
    for priority, response, resolution, source in DEFAULT_TARGETS:
        for kind, (amount, unit) in (
            (TargetKind.FIRST_RESPONSE, response),
            (TargetKind.RESOLUTION, resolution),
        ):
            session.add(
                SlaPolicyTarget(
                    id=new_id(),
                    tenant_id=context.tenant_id,
                    policy_id=policy_id,
                    kind=kind.value,
                    priority=priority,
                    amount=amount,
                    unit=unit.value,
                    source=source.value,
                )
            )
    await session.flush()


# --- reading ------------------------------------------------------------------------------------


def rules_of(policies: Sequence[SlaPolicy], matcher: Any = None) -> list[PolicyRule]:  # noqa: ANN401 - a callable factory
    """The policies as the matching rules see them (`matcher(policy)` gives its condition)."""
    return [
        PolicyRule(
            id=p.id,
            position=p.position,
            enabled=p.enabled,
            fallback=p.fallback,
            has_conditions=p.conditions is not None,
            matches=matcher(p) if matcher is not None else (lambda _record: True),
        )
        for p in policies
    ]


async def policies_of(session: AsyncSession, code: str) -> list[SlaPolicy]:
    """A record type's live policies in order, the fallback last."""
    await ensure_defaults(session, code)
    return list(
        (
            await session.scalars(
                select(SlaPolicy)
                .where(SlaPolicy.record_type == code, SlaPolicy.deleted_at.is_(None))
                .order_by(SlaPolicy.fallback, SlaPolicy.position, SlaPolicy.id)
            )
        ).all()
    )


async def targets_of(
    session: AsyncSession, policy_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[SlaPolicyTarget]]:
    """Each policy's target rows, by kind and priority."""
    found: dict[uuid.UUID, list[SlaPolicyTarget]] = {i: [] for i in policy_ids}
    if policy_ids:
        rows = await session.scalars(
            select(SlaPolicyTarget)
            .where(SlaPolicyTarget.policy_id.in_(policy_ids))
            .order_by(SlaPolicyTarget.kind, SlaPolicyTarget.priority.nulls_last())
        )
        for row in rows:
            found[row.policy_id].append(row)
    return found


def target_rows(rows: Sequence[SlaPolicyTarget]) -> list[TargetRow]:
    """Stored target rows as the domain sees them."""
    return [
        TargetRow(
            kind=TargetKind(r.kind),
            priority=r.priority,
            amount=r.amount,
            unit=TargetUnit(r.unit),
            source=CalendarSource(r.source),
            fixed_calendar_id=r.fixed_calendar_id,
        )
        for r in rows
    ]


async def levels_of(
    session: AsyncSession, policy_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[Level]]:
    """Each policy's escalation levels, by kind and position."""
    found: dict[uuid.UUID, list[Level]] = {i: [] for i in policy_ids}
    if policy_ids:
        rows = await session.scalars(
            select(SlaEscalationLevel)
            .where(SlaEscalationLevel.policy_id.in_(policy_ids))
            .order_by(SlaEscalationLevel.kind, SlaEscalationLevel.position)
        )
        for row in rows:
            found[row.policy_id].append(
                level_of(
                    {
                        "kind": row.kind,
                        "position": row.position,
                        "anchor": row.anchor,
                        "offset_seconds": row.offset_seconds,
                        "recipients": row.recipients,
                        "fallback": row.fallback,
                        "actions": row.actions,
                        "notify": row.notify,
                    }
                )
            )
    return found


async def list_policies(session: AsyncSession, subject: Subject, code: str) -> list[PolicyView]:
    """A record type's policies in order, each with its targets and a "never matches" flag."""
    require(subject, VIEW)
    _type(code)
    policies = await policies_of(session, code)
    targets = await targets_of(session, [p.id for p in policies])
    levels = await levels_of(session, [p.id for p in policies])
    hidden = set(never_matching(rules_of(policies)))
    manage = subject.holds(MANAGE)
    return [PolicyView(p, targets[p.id], p.id in hidden, manage, levels[p.id]) for p in policies]


async def _row(session: AsyncSession, policy_id: uuid.UUID) -> SlaPolicy:
    row = await session.scalar(
        select(SlaPolicy).where(SlaPolicy.id == policy_id, SlaPolicy.deleted_at.is_(None))
    )
    if row is None:
        raise NotFound(code="sla_policy_not_found", params={"id": str(policy_id)})
    return row


async def get_policy(session: AsyncSession, subject: Subject, policy_id: uuid.UUID) -> PolicyView:
    """One policy (404 for another tenant's or a deleted one)."""
    require(subject, VIEW)
    row = await _row(session, policy_id)
    views = await list_policies(session, subject, row.record_type)
    return next(v for v in views if v.policy.id == row.id)


# --- writing ------------------------------------------------------------------------------------


def _labels(value: Mapping[str, str] | None, errors: list[FieldError]) -> dict[str, str]:
    labels = {k: " ".join(v.split()) for k, v in (value or {}).items() if v and v.strip()}
    if set(labels) - LANGUAGES or any(len(v) > NAME_MAX for v in labels.values()):
        errors.append(_field("labels", "invalid_language"))
    return labels


def _conditions(tree: Any, rtype: SlaRecordType, errors: list[FieldError]) -> Any:  # noqa: ANN401 - the DSL tree
    if tree is None:
        return None
    try:
        compile_filter(tree, rtype.fields, now=datetime.now(UTC), path="body.conditions")
    except ValidationFailed as refused:
        errors.extend(refused.errors)
    return tree


async def _targets(
    session: AsyncSession,
    raw: Sequence[Mapping[str, Any]],
    rtype: SlaRecordType,
    errors: list[FieldError],
) -> list[TargetRow]:
    rows: list[TargetRow] = []
    for index, item in enumerate(raw):
        priority = item.get("priority")
        if priority is not None and priority not in rtype.priorities:
            errors.append(_field(f"targets.{index}.priority", "unknown_priority"))
        rows.append(
            TargetRow(
                kind=TargetKind(item["kind"]),
                priority=priority,
                amount=item.get("amount"),
                unit=TargetUnit(item.get("unit") or TargetUnit.HOURS),
                source=CalendarSource(item.get("source") or CalendarSource.SITE),
                fixed_calendar_id=item.get("fixed_calendar_id"),
            )
        )
    for index, code in target_problems(rows):
        errors.append(_field(f"targets.{index}", code))
    for index, row in enumerate(rows):
        if row.fixed_calendar_id is not None and not await calendar_exists(
            session, row.fixed_calendar_id
        ):
            errors.append(_field(f"targets.{index}.fixed_calendar_id", "calendar_not_found"))
    return rows


async def _replace_targets(
    session: AsyncSession, policy_id: uuid.UUID, rows: Sequence[TargetRow]
) -> None:
    await session.execute(delete(SlaPolicyTarget).where(SlaPolicyTarget.policy_id == policy_id))
    context = session.info[SESSION_TENANT_KEY]
    for row in rows:
        session.add(
            SlaPolicyTarget(
                id=new_id(),
                tenant_id=context.tenant_id,
                policy_id=policy_id,
                kind=row.kind.value,
                priority=row.priority,
                amount=row.amount,
                unit=row.unit.value,
                source=row.source.value,
                fixed_calendar_id=row.fixed_calendar_id,
            )
        )
    await session.flush()


def _who(raw: Sequence[Mapping[str, Any]]) -> tuple[Recipient, ...]:
    return tuple(
        Recipient(RecipientKind(r["kind"]), str(r["id"]) if r.get("id") is not None else None)
        for r in raw
    )


async def _levels(
    session: AsyncSession, raw: Sequence[Mapping[str, Any]], errors: list[FieldError]
) -> list[Level]:
    """The sent levels, numbered within each kind in the order sent, then checked."""
    levels: list[Level] = []
    counts: dict[TargetKind, int] = {}
    for item in raw:
        kind = TargetKind(item["kind"])
        counts[kind] = counts.get(kind, 0) + 1
        levels.append(
            Level(
                kind=kind,
                position=counts[kind],
                anchor=Anchor(item.get("anchor") or Anchor.DUE),
                offset_seconds=int(item.get("offset_seconds") or 0),
                recipients=_who(item.get("recipients") or ()),
                fallback=_who(item.get("fallback") or ()),
                actions=tuple(
                    Action(
                        ActionKind(a["kind"]),
                        str(a["target_id"]) if a.get("target_id") is not None else None,
                        (a.get("text") or "").strip() or None,
                    )
                    for a in item.get("actions") or ()
                ),
                notify=bool(item.get("notify", True)),
            )
        )
    for name, code, params in level_problems(levels):
        errors.append(_field(name, code, **params))
    await _level_references(session, levels, errors)
    return levels


def _references(levels: Sequence[Level]) -> tuple[set[str], set[str]]:
    """The people and groups the levels name (as recipients or reassign targets)."""
    people: set[str] = set()
    groups: set[str] = set()
    for level in levels:
        for who in (*level.recipients, *level.fallback):
            if who.id and who.kind in {RecipientKind.USER, RecipientKind.GROUP}:
                (people if who.kind is RecipientKind.USER else groups).add(who.id)
        for action in level.actions:
            if action.target_id and action.kind is ActionKind.REASSIGN_PERSON:
                people.add(action.target_id)
            if action.target_id and action.kind is ActionKind.REASSIGN_GROUP:
                groups.add(action.target_id)
    return people, groups


async def _level_references(
    session: AsyncSession, levels: Sequence[Level], errors: list[FieldError]
) -> None:
    """Named people and groups must exist (live) in the tenant."""
    people, groups = _references(levels)
    try:
        group_ids = [uuid.UUID(g) for g in groups]
        person_ids = [str(uuid.UUID(p)) for p in people]
    except ValueError:
        errors.append(_field("levels", "unknown_reference"))
        return
    known_people = await user_names(session, person_ids) if person_ids else {}
    known_groups = await organization.existing_unit_ids(session, "group", group_ids)
    if set(person_ids) - set(known_people) or set(group_ids) - set(known_groups):
        errors.append(_field("levels", "unknown_reference"))


async def _replace_levels(
    session: AsyncSession, policy_id: uuid.UUID, levels: Sequence[Level]
) -> None:
    await session.execute(
        delete(SlaEscalationLevel).where(SlaEscalationLevel.policy_id == policy_id)
    )
    context = session.info[SESSION_TENANT_KEY]
    for level in levels:
        session.add(
            SlaEscalationLevel(
                id=new_id(),
                tenant_id=context.tenant_id,
                policy_id=policy_id,
                kind=level.kind.value,
                position=level.position,
                anchor=level.anchor.value,
                offset_seconds=level.offset_seconds,
                recipients=[r.as_json() for r in level.recipients],
                fallback=[r.as_json() for r in level.fallback],
                actions=[a.as_json() for a in level.actions],
                notify=level.notify,
            )
        )
    await session.flush()


def _target_snapshot(rows: Sequence[TargetRow]) -> list[dict[str, Any]]:
    return [
        {
            "kind": r.kind.value,
            "priority": r.priority,
            "amount": r.amount,
            "unit": r.unit.value,
            "source": r.source.value,
            "fixed_calendar_id": str(r.fixed_calendar_id) if r.fixed_calendar_id else None,
        }
        for r in rows
    ]


def _snapshot(
    row: SlaPolicy, rows: Sequence[TargetRow], levels: Sequence[Level] = ()
) -> dict[str, Any]:
    return {
        "name": row.name,
        "labels": dict(row.labels),
        "description": row.description,
        "conditions": row.conditions,
        "enabled": row.enabled,
        "pausing": sorted(row.pausing),
        "targets": _target_snapshot(rows),
        "levels": [level.as_json() for level in levels],
    }


def _pausing(value: Sequence[str] | None, errors: list[FieldError]) -> list[str]:
    kinds = sorted(set(value or ()))
    if set(kinds) - {k.value for k in TargetKind}:
        errors.append(_field("pausing", "invalid_choice"))
    return kinds


async def create_policy(
    session: AsyncSession, subject: Subject, code: str, values: Mapping[str, Any], *, source: Source
) -> PolicyView:
    """A new policy above the fallback, last among the others."""
    require(subject, MANAGE)
    rtype = _type(code)
    await ensure_defaults(session, code)
    errors: list[FieldError] = []
    name = " ".join(str(values.get("name") or "").split())[:NAME_MAX]
    if not name:
        errors.append(_field("name", "required"))
    labels = _labels(values.get("labels"), errors)
    conditions = _conditions(values.get("conditions"), rtype, errors)
    pausing = _pausing(values.get("pausing", [k.value for k in TargetKind]), errors)
    rows = await _targets(session, values.get("targets") or [], rtype, errors)
    levels = await _levels(session, values.get("levels") or [], errors)
    if errors:
        raise ValidationFailed(errors=errors)
    position = await session.scalar(
        select(func.coalesce(func.max(SlaPolicy.position), 0) + 1).where(
            SlaPolicy.record_type == code,
            SlaPolicy.fallback.is_(False),
            SlaPolicy.deleted_at.is_(None),
        )
    )
    row = SlaPolicy(
        record_type=code,
        name=name,
        labels=labels,
        description=(values.get("description") or "").strip() or None,
        conditions=conditions,
        position=int(position or 1),
        fallback=False,
        enabled=bool(values.get("enabled", True)),
        pausing=pausing,
    )
    try:
        async with session.begin_nested():
            await PolicyRepository(session).add(row)
    except IntegrityError:
        raise ValidationFailed(errors=[_field("name", "name_taken")]) from None
    await _replace_targets(session, row.id, rows)
    await _replace_levels(session, row.id, levels)
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=row.id,
        version=row.version,
        kind="created",
        changes=[Change(k, None, v) for k, v in _snapshot(row, rows, levels).items()],
        source=source,
    )
    await record_event(
        session,
        SlaPolicySaved(policy_id=row.id, record_type=code, created=True, changed_fields=[]),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )
    return await get_policy(session, subject, row.id)


async def update_policy(  # noqa: C901, PLR0912, PLR0913, PLR0915 - one rule per field, flat
    session: AsyncSession,
    subject: Subject,
    policy_id: uuid.UUID,
    values: Mapping[str, Any],
    *,
    expected_version: int,
    source: Source,
) -> PolicyView:
    """Change what was sent. The fallback keeps no conditions and stays enabled."""
    require(subject, MANAGE)
    row = await _row(session, policy_id)
    rtype = _type(row.record_type)
    current = target_rows((await targets_of(session, [row.id]))[row.id])
    current_levels = (await levels_of(session, [row.id]))[row.id]
    before = _snapshot(row, current, current_levels)
    errors: list[FieldError] = []
    columns: dict[str, Any] = {}
    if "name" in values:
        name = " ".join(str(values["name"] or "").split())[:NAME_MAX]
        if not name:
            errors.append(_field("name", "required"))
        columns["name"] = name
    if "labels" in values:
        columns["labels"] = _labels(values["labels"], errors)
    if "description" in values:
        columns["description"] = (values["description"] or "").strip() or None
    if row.fallback:
        errors.extend(_field(f, "fallback_fixed") for f in ("conditions", "enabled") if f in values)
    if "conditions" in values and not row.fallback:
        columns["conditions"] = _conditions(values["conditions"], rtype, errors)
    if "enabled" in values and not row.fallback:
        columns["enabled"] = bool(values["enabled"])
    if "pausing" in values:
        columns["pausing"] = _pausing(values["pausing"], errors)
    rows = current
    if "targets" in values:
        rows = await _targets(session, values["targets"] or [], rtype, errors)
    levels = current_levels
    if "levels" in values:
        levels = await _levels(session, values["levels"] or [], errors)
    if errors:
        raise ValidationFailed(errors=errors)
    columns = {k: v for k, v in columns.items() if getattr(row, k) != v}
    targets_changed = _target_snapshot(rows) != before["targets"]
    levels_changed = [level.as_json() for level in levels] != before["levels"]
    if not columns and not targets_changed and not levels_changed:
        return await get_policy(session, subject, row.id)
    try:
        async with session.begin_nested():
            updated = await PolicyRepository(session).update(
                row.id, expected_version=expected_version, changes=columns
            )
    except Conflict as error:
        raise await explain_conflict(
            session,
            error,
            record_type=RECORD_TYPE,
            record_id=row.id,
            names=lambda ids: _names(session, ids),
        ) from None
    except IntegrityError:
        raise ValidationFailed(errors=[_field("name", "name_taken")]) from None
    if targets_changed:
        await _replace_targets(session, row.id, rows)
    if levels_changed:
        await _replace_levels(session, row.id, levels)
    after = _snapshot(updated, rows, levels)
    changes = [Change(k, before[k], after[k]) for k in after if before[k] != after[k]]
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=row.id,
        version=updated.version,
        kind="updated",
        changes=changes,
        source=source,
    )
    await record_event(
        session,
        SlaPolicySaved(
            policy_id=row.id,
            record_type=row.record_type,
            created=False,
            changed_fields=[c.field for c in changes],
        ),
        aggregate_id=row.id,
        aggregate_version=updated.version,
    )
    return await get_policy(session, subject, row.id)


async def reorder_policies(
    session: AsyncSession,
    subject: Subject,
    code: str,
    order: Sequence[uuid.UUID],
    *,
    source: Source,
) -> list[PolicyView]:
    """The non-fallback policies in this order (every one of them, once)."""
    require(subject, MANAGE)
    _type(code)
    policies = [p for p in await policies_of(session, code) if not p.fallback]
    if sorted(order) != sorted(p.id for p in policies) or len(set(order)) != len(order):
        raise ValidationFailed(errors=[_field("policy_ids", "order_incomplete")])
    before = {p.id: p.position for p in policies}
    versions = {p.id: p.version for p in policies}
    for position, policy_id in enumerate(order, start=1):
        if before[policy_id] != position:
            await session.execute(
                update(SlaPolicy)
                .where(SlaPolicy.id == policy_id)
                .values(position=position, version=SlaPolicy.version + 1)
            )
            await record_changes(
                session,
                record_type=RECORD_TYPE,
                record_id=policy_id,
                version=versions[policy_id] + 1,
                kind="updated",
                changes=[Change("position", before[policy_id], position)],
                source=source,
            )
    await record_event(
        session,
        SlaPoliciesReordered(record_type=code, policy_ids=list(order)),
        aggregate_id=order[0] if order else uuid.UUID(int=0),
        aggregate_version=None,
    )
    return await list_policies(session, subject, code)


async def delete_policy(
    session: AsyncSession,
    subject: Subject,
    policy_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> None:
    """To the trash; never the fallback. Records keep the targets they started with (D7)."""
    require(subject, MANAGE)
    row = await _row(session, policy_id)
    if row.fallback:
        raise Conflict(code="sla_fallback_required")
    try:
        deleted = await PolicyRepository(session).soft_delete(
            row.id, expected_version=expected_version
        )
    except Conflict as error:
        raise await explain_conflict(
            session,
            error,
            record_type=RECORD_TYPE,
            record_id=row.id,
            names=lambda ids: _names(session, ids),
        ) from None
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=row.id,
        version=deleted.version,
        kind="deleted",
        changes=[],
        source=source,
    )
    await record_event(
        session,
        SlaPolicyDeleted(policy_id=row.id, record_type=row.record_type),
        aggregate_id=row.id,
        aggregate_version=deleted.version,
    )


# --- settings -----------------------------------------------------------------------------------


async def settings_of(session: AsyncSession, code: str) -> SlaSettings:
    """A record type's settings (created on first use)."""
    await ensure_defaults(session, code)
    found = await session.scalar(select(SlaSettings).where(SlaSettings.record_type == code))
    if found is None:  # pragma: no cover - ensure_defaults made it
        raise NotFound(code="sla_record_type_not_found")
    return found


async def get_settings(session: AsyncSession, subject: Subject, code: str) -> SlaSettings:
    """The settings an admin sees."""
    require(subject, VIEW)
    _type(code)
    return await settings_of(session, code)


async def update_settings(  # noqa: PLR0913 - the change, explicit
    session: AsyncSession,
    subject: Subject,
    code: str,
    values: Mapping[str, Any],
    *,
    expected_version: int,
    source: Source,
) -> SlaSettings:
    """Warning point (1-99 %), priority-change rule and reopen rule."""
    require(subject, MANAGE)
    _type(code)
    row = await settings_of(session, code)
    columns: dict[str, Any] = {}
    errors: list[FieldError] = []
    if "warning_percent" in values:
        percent = values["warning_percent"]
        if (
            isinstance(percent, bool)
            or not isinstance(percent, int)
            or not WARNING_MIN <= percent <= WARNING_MAX
        ):
            errors.append(
                _field("warning_percent", "out_of_range", min=WARNING_MIN, max=WARNING_MAX)
            )
        columns["warning_percent"] = percent
    for name, choices in (("priority_rule", PriorityRule), ("reopen_rule", ReopenRule)):
        if name in values:
            if values[name] not in {c.value for c in choices}:
                errors.append(_field(name, "invalid_choice"))
            columns[name] = values[name]
    if errors:
        raise ValidationFailed(errors=errors)
    columns = {k: v for k, v in columns.items() if getattr(row, k) != v}
    if not columns:
        return row
    if row.version != expected_version:
        raise await explain_conflict(
            session,
            Conflict(
                code="version_conflict",
                params={"expected_version": expected_version, "current_version": row.version},
            ),
            record_type=SETTINGS_RECORD_TYPE,
            record_id=uuid.UUID(int=0),
            names=lambda ids: _names(session, ids),
        )
    before = {k: getattr(row, k) for k in columns}
    await session.execute(
        update(SlaSettings)
        .where(SlaSettings.record_type == code, SlaSettings.version == expected_version)
        .values(**columns, version=SlaSettings.version + 1, updated_by=subject.user_id)
    )
    await session.refresh(row)
    await record_changes(
        session,
        record_type=SETTINGS_RECORD_TYPE,
        record_id=uuid.UUID(int=0),
        version=row.version,
        kind="updated",
        changes=[Change(k, before[k], v) for k, v in columns.items()],
        source=source,
    )
    await record_event(
        session,
        SlaSettingsSaved(record_type=code, changed_fields=sorted(columns)),
        aggregate_id=uuid.UUID(int=0),
        aggregate_version=row.version,
    )
    return row
