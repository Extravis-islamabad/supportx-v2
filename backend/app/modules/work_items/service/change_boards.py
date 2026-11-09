"""Change advisory boards, the admin side (WP-045b S2; REQ-CHG-040, -041).

Each tenant starts with Appendix A's two boards, seeded on first read with no members: the
default "Change advisory board" (reviews what no other board maps) and the "Emergency change
board" (mapped to emergency changes). Seeds are the only boards that may have no members; an
admin's board is refused without one (REQ-CHG-040 AC1), and members are never all removed. The
default board is never deleted, so a change always has a board to fall back on (REQ-CHG-041 AC2).

Every change is versioned (If-Match), kept in field history and announced through the outbox,
so open settings pages refetch (rule 5c).
"""

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict, PermissionDenied
from app.modules.identity_access import Subject, active_user_ids
from app.modules.organization import existing_unit_ids, users_in_groups
from app.modules.work_items.domain import change_boards as rules
from app.modules.work_items.domain.change_risk import RiskLevel
from app.modules.work_items.domain.templates import PickList
from app.modules.work_items.domain.types import TYPES, WorkItemTypeCode
from app.modules.work_items.events import ChangeBoardChanged
from app.modules.work_items.infra.models import (
    ChangeBoard,
    ChangeBoardMember,
    WorkItem,
    WorkItemChangeDetails,
    WorkItemTemplate,
)
from app.modules.work_items.service import catalogue as config
from app.modules.work_items.service import work_items as items
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.history import Change, ChangeKind, Source, record_changes
from app.shared.ids import new_id

RECORD_TYPE = "change_board"
MANAGE = ("config.service_desk", "settings.manage")
NAME_MAX, DESCRIPTION_MAX, LABEL_MAX, MAX_MEMBERS = 200, 2000, 200, 200
LANGUAGES = frozenset({"en", "ar", "ur"})
EDITABLE = ("name", "labels", "description", "chair_id", "rule", "mapping", "position")
# Appendix A's boards: (code, English name, position, is_default, mapping).
SEEDS: tuple[tuple[str, str, int, bool, dict[str, list[str]] | None], ...] = (
    (rules.DEFAULT_BOARD, "Change advisory board", 100, True, None),
    (rules.EMERGENCY_BOARD, "Emergency change board", 0, False, {"change_types": ["emergency"]}),
)


class BoardRepository(Repository[ChangeBoard]):
    """Change boards of the session's tenant."""

    model = ChangeBoard


@dataclass(frozen=True)
class Member:
    """One member: a person or a group, optionally optional."""

    user_id: uuid.UUID | None
    group_id: uuid.UUID | None
    optional: bool = False


@dataclass(frozen=True)
class Board:
    """A board with its members."""

    row: ChangeBoard
    members: tuple[Member, ...]


def _require_manage(subject: Subject) -> None:
    if not any(subject.holds(p) for p in MANAGE):
        raise PermissionDenied(params={"permission": MANAGE[0], "reason": "no_permission"})


def _uuid_or_none(value: Any) -> uuid.UUID | None:  # noqa: ANN401 - a JSON value
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _require_view(subject: Subject) -> None:
    view = TYPES[WorkItemTypeCode.CHANGE].permission("view")
    if not subject.holds(view) and not any(subject.holds(p) for p in MANAGE):
        raise PermissionDenied(params={"permission": view, "reason": "no_permission"})


async def ensure_seeded(session: AsyncSession) -> None:
    """Appendix A's two boards, once per tenant (kept when an admin changed them)."""
    tenant = session.info[SESSION_TENANT_KEY].tenant_id
    for code, name, position, is_default, mapping in SEEDS:
        await session.execute(
            insert(ChangeBoard)
            .values(
                id=new_id(),
                tenant_id=tenant,
                code=code,
                name=name,
                position=position,
                is_default=is_default,
                mapping=mapping,
            )
            .on_conflict_do_nothing(
                index_elements=["tenant_id", "code"],
                index_where=text("code IS NOT NULL AND deleted_at IS NULL"),
            )
        )


async def live_board_ids(session: AsyncSession, ids: Iterable[uuid.UUID]) -> set[uuid.UUID]:
    """Which of these boards exist (not removed) in the session's tenant."""
    wanted = list(ids)
    if not wanted:
        return set()
    return set(
        await session.scalars(
            select(ChangeBoard.id).where(
                ChangeBoard.id.in_(wanted), ChangeBoard.deleted_at.is_(None)
            )
        )
    )


async def _members(
    session: AsyncSession, board_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, tuple[Member, ...]]:
    rows = await session.scalars(
        select(ChangeBoardMember)
        .where(ChangeBoardMember.board_id.in_(board_ids))
        .order_by(ChangeBoardMember.created_at, ChangeBoardMember.id)
    )
    found: dict[uuid.UUID, list[Member]] = {b: [] for b in board_ids}
    for m in rows:
        found[m.board_id].append(Member(m.user_id, m.group_id, m.optional))
    return {b: tuple(ms) for b, ms in found.items()}


async def boards(session: AsyncSession, subject: Subject) -> list[Board]:
    """Every board in order, with members (seeding the defaults first)."""
    _require_view(subject)
    await ensure_seeded(session)
    rows = list(
        await session.scalars(
            select(ChangeBoard)
            .where(ChangeBoard.deleted_at.is_(None))
            .order_by(ChangeBoard.position, ChangeBoard.code, ChangeBoard.id)
        )
    )
    members = await _members(session, [r.id for r in rows])
    return [Board(r, members[r.id]) for r in rows]


async def board(session: AsyncSession, subject: Subject, board_id: uuid.UUID) -> Board:
    """One board with its members, or 404."""
    _require_view(subject)
    row = await BoardRepository(session).get(board_id)
    return Board(row, (await _members(session, [row.id]))[row.id])


def _labels(raw: Any, problems: list[tuple[str, str]]) -> dict[str, str] | None:  # noqa: ANN401 - the request's JSON
    if not raw:
        return None
    if not isinstance(raw, Mapping) or set(raw) - LANGUAGES:
        problems.append(("labels", "invalid_value"))
        return None
    clean = {k: " ".join(str(v).split()) for k, v in raw.items() if str(v).strip()}
    if any(len(v) > LABEL_MAX for v in clean.values()):
        problems.append(("labels", "value_too_long"))
    return clean or None


async def _check_mapping(
    session: AsyncSession,
    raw: Any,  # noqa: ANN401 - the request's JSON, checked here
    problems: list[tuple[str, str]],
) -> dict[str, list[str]] | None:
    """Known keys, and codes and IDs that exist (types, levels, sites, change templates)."""
    shape = rules.mapping_problems(raw)
    if shape:
        problems += shape
        return None
    if not raw:
        return None
    clean = {k: sorted(dict.fromkeys(raw[k])) for k in rules.MAPPING_KEYS if raw.get(k)}
    cat = await config.load(session, TYPES[WorkItemTypeCode.CHANGE])
    if set(clean.get("change_types", ())) - set(cat.reason_codes(PickList.CHANGE_TYPE)):
        problems.append(("mapping.change_types", "invalid_choice"))
    if set(clean.get("risk_levels", ())) - {level.value for level in RiskLevel}:
        problems.append(("mapping.risk_levels", "invalid_choice"))
    for key, kind in (("site_ids", "site"), ("template_ids", "template")):
        ids = [_uuid_or_none(v) for v in clean.get(key, ())]
        if None in ids:
            problems.append((f"mapping.{key}", "invalid_value"))
            continue
        wanted = [i for i in ids if i is not None]
        if not wanted:
            continue
        known: set[uuid.UUID] = set()
        if kind == "site":
            known = set(await existing_unit_ids(session, "site", wanted))
        else:
            known = set(
                await session.scalars(
                    select(WorkItemTemplate.id).where(
                        WorkItemTemplate.id.in_(wanted),
                        WorkItemTemplate.type == WorkItemTypeCode.CHANGE,
                        WorkItemTemplate.deleted_at.is_(None),
                    )
                )
            )
        if set(wanted) - known:
            problems.append((f"mapping.{key}", f"{kind}_not_found"))
    return clean or None


async def _check_members(
    session: AsyncSession, raw: Sequence[Mapping[str, Any]], problems: list[tuple[str, str]]
) -> list[Member]:
    """Each person or group once; people active, groups live; at most MAX_MEMBERS."""
    if len(raw) > MAX_MEMBERS:
        problems.append(("members", "too_many_items"))
        return []
    members: list[Member] = []
    seen: set[tuple[str, uuid.UUID]] = set()
    for m in raw:
        user = _uuid_or_none(m["user_id"]) if m.get("user_id") is not None else None
        group = _uuid_or_none(m["group_id"]) if m.get("group_id") is not None else None
        if user is not None and group is None:
            key = ("user", user)
        elif group is not None and user is None:
            key = ("group", group)
        else:
            problems.append(("members", "invalid_value"))
            return []
        if key in seen:
            problems.append(("members", "duplicate_value"))
            return []
        seen.add(key)
        members.append(Member(user, group, bool(m.get("optional"))))
    people = [m.user_id for m in members if m.user_id is not None]
    groups = [m.group_id for m in members if m.group_id is not None]
    if people and set(people) - await active_user_ids(session, people):
        problems.append(("members", "user_not_found"))
    if groups and set(groups) - await existing_unit_ids(session, "group", groups):
        problems.append(("members", "group_not_found"))
    return members


async def _name(
    session: AsyncSession,
    raw: object,
    except_id: uuid.UUID | None,
    problems: list[tuple[str, str]],
) -> str:
    """The board's name: given, not too long, not another board's."""
    name = " ".join(str(raw or "").split())
    if not name:
        problems.append(("name", "required"))
    elif len(name) > NAME_MAX:
        problems.append(("name", "value_too_long"))
    else:
        same = select(ChangeBoard.id).where(
            ChangeBoard.deleted_at.is_(None), ChangeBoard.name.ilike(name)
        )
        if except_id is not None:
            same = same.where(ChangeBoard.id != except_id)
        if await session.scalar(same) is not None:
            problems.append(("name", "duplicate_name"))
    return name


async def _check(
    session: AsyncSession, values: Mapping[str, Any], *, except_id: uuid.UUID | None
) -> tuple[dict[str, Any], list[Member] | None]:
    """The board's fields, cleaned, and its members when sent (`None`: left as they are)."""
    problems: list[tuple[str, str]] = []
    name = await _name(session, values.get("name"), except_id, problems)
    description = (values.get("description") or "").strip() or None
    if description is not None and len(description) > DESCRIPTION_MAX:
        problems.append(("description", "value_too_long"))
    rule = values.get("rule") or "majority"
    if rule not in rules.RULES:
        problems.append(("rule", "invalid_choice"))
    chair = values.get("chair_id")
    if chair is not None and not await active_user_ids(session, [chair]):
        problems.append(("chair_id", "user_not_found"))
    if rule == "majority_with_chair" and chair is None:
        problems.append(("chair_id", "required"))
    position = values.get("position") or 0
    if not isinstance(position, int) or not 0 <= position <= 10_000:  # noqa: PLR2004 - a sane order
        problems.append(("position", "out_of_range"))
    clean = {
        "name": name,
        "labels": _labels(values.get("labels"), problems),
        "description": description,
        "chair_id": chair,
        "rule": rule,
        "mapping": await _check_mapping(session, values.get("mapping"), problems),
        "position": position,
    }
    members = None
    if "members" in values:
        members = await _check_members(session, values["members"] or [], problems)
        if not members and not problems:  # REQ-CHG-040 AC1: never saved without one
            problems.append(("members", "required"))
    if problems:
        raise items.field_errors(problems)
    return clean, members


async def _replace_members(
    session: AsyncSession, row: ChangeBoard, members: Sequence[Member]
) -> None:
    current = await session.scalars(
        select(ChangeBoardMember).where(ChangeBoardMember.board_id == row.id)
    )
    for old in current:
        await session.delete(old)
    await session.flush()
    for m in members:
        session.add(
            ChangeBoardMember(
                id=new_id(),
                tenant_id=row.tenant_id,
                board_id=row.id,
                user_id=m.user_id,
                group_id=m.group_id,
                optional=m.optional,
            )
        )
    await session.flush()


def _plain(value: object) -> object:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, Member):
        return {
            "user_id": _plain(value.user_id),
            "group_id": _plain(value.group_id),
            "optional": value.optional,
        }
    return value


async def _changed(
    session: AsyncSession,
    row: ChangeBoard,
    kind: ChangeKind,
    changes: list[Change],
    source: Source,
) -> None:
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=row.id,
        version=row.version,
        kind=kind,
        changes=changes,
        source=source,
    )
    await record_event(
        session,
        ChangeBoardChanged(board_id=row.id, change=kind),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )


async def create_board(
    session: AsyncSession, subject: Subject, values: Mapping[str, Any], *, source: Source
) -> Board:
    """An admin's board: named, with at least one member (REQ-CHG-040 AC1)."""
    _require_manage(subject)
    await ensure_seeded(session)
    clean, members = await _check(session, {"members": [], **values}, except_id=None)
    row = await BoardRepository(session).add(ChangeBoard(**clean))
    await _replace_members(session, row, members or [])
    changes = [Change(k, None, _plain(v)) for k, v in clean.items() if v is not None]
    changes.append(Change("members", None, _plain(members or [])))
    await _changed(session, row, "created", changes, source)
    return Board(row, tuple(members or []))


async def update_board(  # noqa: PLR0913 - the board, its version and the change, explicit
    session: AsyncSession,
    subject: Subject,
    board_id: uuid.UUID,
    values: Mapping[str, Any],
    *,
    expected_version: int,
    source: Source,
) -> Board:
    """Change a board (If-Match). Fields left out keep their value; `members` replaces them."""
    _require_manage(subject)
    found = await board(session, subject, board_id)
    row = found.row
    merged = {**{k: getattr(row, k) for k in EDITABLE}, **values}
    clean, members = await _check(session, merged, except_id=row.id)
    changes = [
        Change(k, _plain(getattr(row, k)), _plain(v))
        for k, v in clean.items()
        if getattr(row, k) != v
    ]
    if members is not None and tuple(members) != found.members:
        changes.append(Change("members", _plain(found.members), _plain(members)))
    if not changes:
        if row.version != expected_version:
            raise Conflict(params={"current_version": row.version})
        return found
    updated = await BoardRepository(session).update(
        row.id, expected_version=expected_version, changes=clean
    )
    if members is not None:
        await _replace_members(session, updated, members)
    await _changed(session, updated, "updated", changes, source)
    return Board(updated, tuple(members) if members is not None else found.members)


async def delete_board(
    session: AsyncSession,
    subject: Subject,
    board_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> None:
    """Remove a board (soft delete); the default board stays (REQ-CHG-041 AC2)."""
    _require_manage(subject)
    row = await BoardRepository(session).get(board_id)
    if row.is_default:
        raise Conflict(code="default_board_kept", params={"id": str(row.id)})
    removed = await BoardRepository(session).soft_delete(row.id, expected_version=expected_version)
    await _changed(session, removed, "deleted", [], source)


# --- which boards review a change (REQ-CHG-041) --------------------------------------------------


@dataclass(frozen=True)
class Reviewing:
    """A board reviewing one approval level: its people now, its rule and why it was chosen."""

    board_id: uuid.UUID
    rule: rules.BoardRule
    reason: str | None  # "mapped" or "default" for a mapped board; None for one named outright
    people: tuple[uuid.UUID, ...]
    advisory: tuple[uuid.UUID, ...] = ()  # optional members: their votes never count (Haider)


async def _facts(session: AsyncSession, record: WorkItem) -> rules.ChangeFacts:
    details = await session.scalar(
        select(WorkItemChangeDetails).where(WorkItemChangeDetails.work_item_id == record.id)
    )
    risk = None if details is None else (details.risk_chosen or details.risk)
    return rules.ChangeFacts(
        change_type=None if details is None else details.change_type,
        risk=risk,
        site_id=str(record.site_id) if record.site_id else None,
        template_id=str(record.template_id) if record.template_id else None,
    )


async def _people(session: AsyncSession, members: Sequence[Member]) -> tuple[uuid.UUID, ...]:
    """Members as people now: each person, and each group's members, once."""
    people = [m.user_id for m in members if m.user_id is not None]
    groups = frozenset(m.group_id for m in members if m.group_id is not None)
    if groups:
        people += list(await session.scalars(users_in_groups(groups)))
    return tuple(dict.fromkeys(people))


async def reviewing(
    session: AsyncSession, record: WorkItem, refs: Sequence[str], *, every_match: bool
) -> list[Reviewing]:
    """The boards a level names, with their members' people now (group members included).

    "mapped" is the change's own choice by the boards' mappings, else the default board (the
    reason says which); an ID names that board. A removed board reviews nothing.
    """
    await ensure_seeded(session)
    rows = list(await session.scalars(select(ChangeBoard).where(ChangeBoard.deleted_at.is_(None))))
    members = await _members(session, [r.id for r in rows])
    by_id = {r.id: r for r in rows}
    chosen: list[tuple[uuid.UUID, str | None]] = []
    for ref in refs:
        if ref == "mapped":
            facts = [
                rules.BoardFacts(
                    str(r.id), r.code, r.position, r.is_default, r.mapping, bool(members[r.id])
                )
                for r in rows
            ]
            choice = rules.choose(facts, await _facts(session, record), every_match=every_match)
            chosen += [(uuid.UUID(b), choice.reason) for b in choice.board_ids]
        elif _uuid_or_none(ref) in by_id:
            chosen.append((uuid.UUID(ref), None))
    found: list[Reviewing] = []
    for board_id, reason in dict.fromkeys(chosen):
        required = await _people(session, [m for m in members[board_id] if not m.optional])
        optional = await _people(session, [m for m in members[board_id] if m.optional])
        found.append(
            Reviewing(
                board_id,
                rules.BoardRule(by_id[board_id].rule),
                reason,
                required,
                tuple(p for p in optional if p not in required),
            )
        )
    return found


# --- who would approve: the warning before a submit (REQ-CHG-039) ------------------------------


@dataclass(frozen=True)
class Preview:
    """The stage's first level as it would open now (None: the stage needs no approval)."""

    stage: str
    named: tuple[uuid.UUID, ...]
    barred: tuple[tuple[uuid.UUID, str], ...]
    fallback_reason: str | None  # set: the approval administrators decide as well


async def preview(
    session: AsyncSession, subject: Subject, record_id: uuid.UUID, stage: str | None
) -> Preview | None:
    """Who approves the stage (the record's own by default) and who is left out, and why."""
    # Imported here: stage approvals import this module for the boards.
    from app.modules.work_items.service import stage_approvals  # noqa: PLC0415 - see above

    wtype = TYPES[WorkItemTypeCode.CHANGE]
    record = await items.visible_record(session, subject, wtype, record_id)
    code = stage or record.stage
    settings = await stage_approvals.settings_of(session, wtype, record, code)
    if settings is None or code is None:
        return None
    plan = await stage_approvals.plan_level(session, record, settings, index=0)
    return Preview(
        code,
        plan.named,
        tuple((person, why.value) for person, why in plan.barred),
        plan.reason.value if plan.reason else None,
    )
