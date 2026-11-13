"""Life cycle versions of action-based types: drafts, publishing, retiring (ADR-049 §2, §6).

A life cycle ("standard", or a set a template names) has numbered versions. Its published
versions never change: an edit starts the next version as a draft, a copy of the latest
published one, and the draft is changed as a whole. A draft saves with its problems; only one
without problems publishes. Records keep the version they were made on (§3), so publishing
changes only what new records start on, and retiring a version only stops it being offered to
new records (the records on it keep moving by it).

Every change here is a change of the type's settings: it takes the type's settings version as
If-Match, bumps it, writes the settings history and `work_items.settings_changed`, so open
designer screens follow live. Who may run a move, when it is offered and what follows it are
WP-029's transition settings (automation), version-wide (ADR-049 Amendment 1), not part of a
version. Staged types' versions (§8) come with their own slice.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.modules import metadata
from app.modules.work_items.domain.lifecycle import (
    ReasonList,
    ReasonMode,
    StatusCategory,
    StatusDef,
    TransitionDef,
    WorkItemAction,
)
from app.modules.work_items.domain.types import WorkItemType
from app.modules.work_items.domain.versions import Move, VersionState, validate
from app.modules.work_items.infra.models import (
    WorkItemLifecycleVersion,
    WorkItemStatus,
    WorkItemTransition,
)
from app.modules.work_items.service import catalogue as config
from app.modules.work_items.service import configuration
from app.modules.work_items.service.catalogue import Catalogue
from app.shared.history import Change, Source

DRAFT_EXISTS = "lifecycle_draft_exists"  # one draft at a time per life cycle
NO_DRAFT = "lifecycle_draft_not_found"
VERSION_NOT_FOUND = "lifecycle_version_not_found"
HAS_PROBLEMS = "lifecycle_version_has_problems"  # {count}: fix them first (the list is on GET)
NOT_PUBLISHED = "lifecycle_version_not_published"  # only a published version retires
LAST_PUBLISHED = "lifecycle_version_last_published"  # new records need one to start on
MOVES_MAX = 500  # a draft's moves (the shipped incident life cycle has about 40)


@dataclass(frozen=True)
class VersionInfo:
    """One version as the designer lists it."""

    number: int
    state: VersionState
    published_at: datetime | None
    published_by: uuid.UUID | None
    problems: list[dict[str, Any]]
    moves: int


@dataclass(frozen=True)
class MoveRow:
    """One move of a version, as stored and as the designer edits it."""

    from_status: str
    action: WorkItemAction
    to_status: str | None
    reason_mode: ReasonMode
    reason_list: ReasonList | None
    permission: str | None
    required_fields: tuple[str, ...]


async def _row(
    session: AsyncSession, wtype: WorkItemType, lifecycle: str, number: int
) -> WorkItemLifecycleVersion:
    found = await session.scalar(
        select(WorkItemLifecycleVersion).where(
            WorkItemLifecycleVersion.type == wtype.code,
            WorkItemLifecycleVersion.lifecycle == lifecycle,
            WorkItemLifecycleVersion.number == number,
        )
    )
    if found is None:
        raise NotFound(code=VERSION_NOT_FOUND)
    return found


async def _draft(
    session: AsyncSession, wtype: WorkItemType, lifecycle: str
) -> WorkItemLifecycleVersion:
    found = await session.scalar(
        select(WorkItemLifecycleVersion).where(
            WorkItemLifecycleVersion.type == wtype.code,
            WorkItemLifecycleVersion.lifecycle == lifecycle,
            WorkItemLifecycleVersion.state == VersionState.DRAFT.value,
        )
    )
    if found is None:
        raise NotFound(code=NO_DRAFT)
    return found


def _known_lifecycle(cat: Catalogue, lifecycle: str) -> None:
    if lifecycle not in cat.lifecycles:
        raise NotFound(code=VERSION_NOT_FOUND)


async def list_versions(
    session: AsyncSession, wtype: WorkItemType, lifecycle: str
) -> list[VersionInfo]:
    """A life cycle's versions, the newest first."""
    _known_lifecycle(await config.load(session, wtype), lifecycle)
    counts = dict(
        (
            await session.execute(
                select(WorkItemTransition.lifecycle_version, func.count())
                .where(
                    WorkItemTransition.type == wtype.code,
                    WorkItemTransition.lifecycle == lifecycle,
                )
                .group_by(WorkItemTransition.lifecycle_version)
            )
        )
        .tuples()
        .all()
    )
    rows = await session.scalars(
        select(WorkItemLifecycleVersion)
        .where(
            WorkItemLifecycleVersion.type == wtype.code,
            WorkItemLifecycleVersion.lifecycle == lifecycle,
        )
        .order_by(WorkItemLifecycleVersion.number.desc())
    )
    return [
        VersionInfo(
            number=v.number,
            state=VersionState(v.state),
            published_at=v.published_at,
            published_by=v.published_by,
            problems=list(v.problems),
            moves=counts.get(v.number, 0),
        )
        for v in rows
    ]


async def moves(
    session: AsyncSession, wtype: WorkItemType, lifecycle: str, number: int
) -> list[MoveRow]:
    """A version's moves, by status and then in the fixed action order."""
    await _row(session, wtype, lifecycle, number)
    rows = await session.scalars(
        select(WorkItemTransition)
        .where(
            WorkItemTransition.type == wtype.code,
            WorkItemTransition.lifecycle == lifecycle,
            WorkItemTransition.lifecycle_version == number,
        )
        .order_by(WorkItemTransition.from_status, WorkItemTransition.action)
    )
    return [
        MoveRow(
            from_status=t.from_status,
            action=WorkItemAction(t.action),
            to_status=t.to_status,
            reason_mode=ReasonMode(t.reason_mode),
            reason_list=ReasonList(t.reason_list) if t.reason_list else None,
            permission=t.permission,
            required_fields=tuple(t.required_fields or ()),
        )
        for t in rows
    ]


async def _problems(
    session: AsyncSession,
    wtype: WorkItemType,
    rows: Sequence[MoveRow],
    allowed_permissions: frozenset[str],
) -> list[dict[str, Any]]:
    statuses = [
        StatusDef(s.code, StatusCategory(s.category), s.colour, s.system)
        for s in await session.scalars(
            select(WorkItemStatus).where(
                WorkItemStatus.type == wtype.code, WorkItemStatus.disabled_at.is_(None)
            )
        )
    ]
    found = validate(
        statuses,
        [
            Move(
                TransitionDef(r.from_status, r.action, r.to_status, r.reason_mode, r.reason_list),
                permission=r.permission,
                required_fields=r.required_fields,
            )
            for r in rows
        ],
        custom_keys=await metadata.definitions(session, wtype.code.value),
        allowed_permissions=frozenset(
            p for p in allowed_permissions if p.startswith(f"{wtype.permission_prefix}.")
        ),
    )
    return [p.as_json() for p in found]


def _transition(
    tenant: uuid.UUID, wtype: WorkItemType, lifecycle: str, number: int, row: MoveRow
) -> WorkItemTransition:
    return WorkItemTransition(
        tenant_id=tenant,
        type=wtype.code,
        lifecycle=lifecycle,
        lifecycle_version=number,
        from_status=row.from_status,
        action=row.action,
        to_status=row.to_status,
        reason_mode=row.reason_mode,
        reason_list=row.reason_list,
        permission=row.permission,
        required_fields=list(row.required_fields) or None,
    )


async def _settings_changed(  # noqa: PLR0913 - the step and its context, explicit
    session: AsyncSession,
    wtype: WorkItemType,
    *,
    expected_version: int,
    change: Change,
    source: Source,
    user_id: uuid.UUID | None,
) -> Catalogue:
    current = await config.load(session, wtype)
    return await configuration.bump(
        session,
        wtype,
        current=current,
        expected_version=expected_version,
        changes=[change],
        changed_fields=["lifecycle_versions"],
        source=source,
        user_id=user_id,
    )


async def start_draft(  # noqa: PLR0913 - the step and its context, explicit
    session: AsyncSession,
    wtype: WorkItemType,
    lifecycle: str,
    *,
    expected_version: int,
    source: Source,
    user_id: uuid.UUID | None,
    allowed_permissions: frozenset[str],
) -> int:
    """The next version as a draft: a copy of the latest published one. Its number."""
    cat = await config.load(session, wtype)
    _known_lifecycle(cat, lifecycle)
    await configuration.check_version(session, wtype, cat, expected_version)
    if await session.scalar(
        select(WorkItemLifecycleVersion.number).where(
            WorkItemLifecycleVersion.type == wtype.code,
            WorkItemLifecycleVersion.lifecycle == lifecycle,
            WorkItemLifecycleVersion.state == VersionState.DRAFT.value,
        )
    ):
        raise Conflict(code=DRAFT_EXISTS)
    latest = cat.latest_version(lifecycle)
    number = (
        await session.scalar(
            select(func.max(WorkItemLifecycleVersion.number)).where(
                WorkItemLifecycleVersion.type == wtype.code,
                WorkItemLifecycleVersion.lifecycle == lifecycle,
            )
        )
        or 0
    ) + 1
    copied = await moves(session, wtype, lifecycle, latest)
    session.add(
        WorkItemLifecycleVersion(
            tenant_id=config.tenant_of(session),
            type=wtype.code,
            lifecycle=lifecycle,
            number=number,
            state=VersionState.DRAFT.value,
            problems=await _problems(session, wtype, copied, allowed_permissions),
            created_by=user_id,
            updated_by=user_id,
        )
    )
    await session.flush()
    session.add_all(
        [_transition(config.tenant_of(session), wtype, lifecycle, number, row) for row in copied]
    )
    await session.flush()
    await _settings_changed(
        session,
        wtype,
        expected_version=expected_version,
        change=Change(f"lifecycle.{lifecycle}.draft", None, number),
        source=source,
        user_id=user_id,
    )
    return number


async def save_draft(  # noqa: PLR0913 - the draft, its moves and the context, explicit
    session: AsyncSession,
    wtype: WorkItemType,
    lifecycle: str,
    rows: Sequence[MoveRow],
    *,
    expected_version: int,
    source: Source,
    user_id: uuid.UUID | None,
    allowed_permissions: frozenset[str],
) -> list[dict[str, Any]]:
    """Replace the draft's moves; it saves with its problems, which are returned."""
    if len(rows) > MOVES_MAX:
        raise ValidationFailed(code="too_many_moves", params={"max": MOVES_MAX})
    keys = [(r.from_status, r.action) for r in rows]
    if len(set(keys)) != len(keys):
        raise ValidationFailed(code="duplicate_move")
    cat = await config.load(session, wtype)
    await configuration.check_version(session, wtype, cat, expected_version)
    draft = await _draft(session, wtype, lifecycle)
    problems = await _problems(session, wtype, rows, allowed_permissions)
    statuses = set(
        await session.scalars(select(WorkItemStatus.code).where(WorkItemStatus.type == wtype.code))
    )
    # A move naming a status the type does not have cannot be stored at all (its foreign
    # key); the problem list already names it, so the save refuses with that list's count.
    if any(
        r.from_status not in statuses or (r.to_status or r.from_status) not in statuses
        for r in rows
    ):
        raise ValidationFailed(code=HAS_PROBLEMS, params={"count": len(problems)})
    await session.execute(
        delete(WorkItemTransition).where(
            WorkItemTransition.type == wtype.code,
            WorkItemTransition.lifecycle == lifecycle,
            WorkItemTransition.lifecycle_version == draft.number,
        )
    )
    session.add_all(
        [
            _transition(config.tenant_of(session), wtype, lifecycle, draft.number, row)
            for row in rows
        ]
    )
    draft.problems = problems
    draft.updated_by = user_id
    draft.version += 1
    await session.flush()
    await _settings_changed(
        session,
        wtype,
        expected_version=expected_version,
        change=Change(f"lifecycle.{lifecycle}.{draft.number}.moves", None, len(rows)),
        source=source,
        user_id=user_id,
    )
    return problems


async def publish(  # noqa: PLR0913 - the step and its context, explicit
    session: AsyncSession,
    wtype: WorkItemType,
    lifecycle: str,
    *,
    expected_version: int,
    source: Source,
    user_id: uuid.UUID | None,
    allowed_permissions: frozenset[str],
) -> int:
    """Publish the draft if it has no problems (checked again now); new records start on it."""
    cat = await config.load(session, wtype)
    await configuration.check_version(session, wtype, cat, expected_version)
    draft = await _draft(session, wtype, lifecycle)
    problems = await _problems(
        session, wtype, await moves(session, wtype, lifecycle, draft.number), allowed_permissions
    )
    draft.problems = problems
    if problems:
        await session.flush()
        raise ValidationFailed(code=HAS_PROBLEMS, params={"count": len(problems)})
    draft.state = VersionState.PUBLISHED.value
    draft.published_at = datetime.now(UTC)
    draft.published_by = user_id
    draft.updated_by = user_id
    draft.version += 1
    await session.flush()
    await _settings_changed(
        session,
        wtype,
        expected_version=expected_version,
        change=Change(
            f"lifecycle.{lifecycle}.published", cat.latest_version(lifecycle), draft.number
        ),
        source=source,
        user_id=user_id,
    )
    return draft.number


async def retire(  # noqa: PLR0913 - the step and its context, explicit
    session: AsyncSession,
    wtype: WorkItemType,
    lifecycle: str,
    number: int,
    *,
    expected_version: int,
    source: Source,
    user_id: uuid.UUID | None,
) -> None:
    """Stop offering a published version; the records on it keep moving by it."""
    cat = await config.load(session, wtype)
    await configuration.check_version(session, wtype, cat, expected_version)
    row = await _row(session, wtype, lifecycle, number)
    if row.state != VersionState.PUBLISHED.value:
        raise Conflict(code=NOT_PUBLISHED, params={"number": number})
    if cat.latest_version(lifecycle) == number:
        raise Conflict(code=LAST_PUBLISHED, params={"number": number})
    await session.execute(
        update(WorkItemLifecycleVersion)
        .where(
            WorkItemLifecycleVersion.type == wtype.code,
            WorkItemLifecycleVersion.lifecycle == lifecycle,
            WorkItemLifecycleVersion.number == number,
        )
        .values(
            state=VersionState.RETIRED.value,
            updated_by=user_id,
            version=WorkItemLifecycleVersion.version + 1,
        )
    )
    await _settings_changed(
        session,
        wtype,
        expected_version=expected_version,
        change=Change(f"lifecycle.{lifecycle}.{number}.state", "published", "retired"),
        source=source,
        user_id=user_id,
    )


async def discard_draft(  # noqa: PLR0913 - the step and its context, explicit
    session: AsyncSession,
    wtype: WorkItemType,
    lifecycle: str,
    *,
    expected_version: int,
    source: Source,
    user_id: uuid.UUID | None,
) -> None:
    """Throw the draft away (no record ever ran on it)."""
    cat = await config.load(session, wtype)
    await configuration.check_version(session, wtype, cat, expected_version)
    draft = await _draft(session, wtype, lifecycle)
    number = draft.number
    await session.execute(
        delete(WorkItemTransition).where(
            WorkItemTransition.type == wtype.code,
            WorkItemTransition.lifecycle == lifecycle,
            WorkItemTransition.lifecycle_version == number,
        )
    )
    await session.delete(draft)
    await session.flush()
    await _settings_changed(
        session,
        wtype,
        expected_version=expected_version,
        change=Change(f"lifecycle.{lifecycle}.draft", number, None),
        source=source,
        user_id=user_id,
    )


__all__ = [
    "DRAFT_EXISTS",
    "HAS_PROBLEMS",
    "LAST_PUBLISHED",
    "MOVES_MAX",
    "NOT_PUBLISHED",
    "NO_DRAFT",
    "VERSION_NOT_FOUND",
    "MoveRow",
    "VersionInfo",
    "discard_draft",
    "list_versions",
    "moves",
    "publish",
    "retire",
    "save_draft",
    "start_draft",
]
