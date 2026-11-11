"""Checklists on work items and their library (WP-046a S2; REQ-INC-040, 077, 078).

A record's checklists are parts of it, like its tasks: reading needs the record's view, changing
needs its edit (or being its investigator), a closed change is locked, every change is in the
record's history without bumping its version (ADR-026), and the record channel hears it
(`work_items.part.changed` v3, part `checklist`) so every open screen refreshes live (AC1).

Ticking an item records who and when (AC1); empty items are dropped on save and the answer says
how many (AC2); a checklist added from the library is a copy the record owns (AC3). Admins keep
the library per type: translatable names (REQ-INC-078 AC2) and items, imported from CSV with
the good rows kept and the bad ones listed (AC1).
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import FieldError, NotFound, ValidationFailed
from app.modules.identity_access import Subject
from app.modules.work_items.domain.checklists import (
    DEFAULT_ITEM_LIMIT,
    TITLE_MAX,
    ImportedItems,
    ImportFailure,
    clean_items,
    item_problems,
    parse_items_csv,
)
from app.modules.work_items.domain.closure import OpenItem, OpenWorkKind
from app.modules.work_items.domain.types import WorkItemType
from app.modules.work_items.events import WorkItemPartChangedV3
from app.modules.work_items.infra.models import (
    ChecklistLibrary,
    WorkItem,
    WorkItemChecklist,
    WorkItemChecklistItem,
    WorkItemTypeSettings,
)
from app.modules.work_items.service import parts
from app.modules.work_items.service import work_items as items
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes

MAX_CHECKLISTS = 50  # per record
LANGUAGES = frozenset({"en", "ar", "ur"})
_KIND = {"added": "child_added", "changed": "child_changed", "removed": "child_removed"}


class ChecklistRepository(Repository[WorkItemChecklist]):
    """Checklists of the session's tenant."""

    model = WorkItemChecklist


class ItemRepository(Repository[WorkItemChecklistItem]):
    """Checklist items of the session's tenant."""

    model = WorkItemChecklistItem


class LibraryRepository(Repository[ChecklistLibrary]):
    """Library checklists of the session's tenant."""

    model = ChecklistLibrary


@dataclass(frozen=True)
class ChecklistView:
    """One checklist with its items in order."""

    checklist: WorkItemChecklist
    items: list[WorkItemChecklistItem]


def _problems(problems: Sequence[tuple[str, str]], **params: Any) -> ValidationFailed:  # noqa: ANN401 - problem params
    return ValidationFailed(
        errors=[
            FieldError(field=f, code=c, message_key=f"errors.field.{c}", params=params)
            for f, c in problems
        ]
    )


async def item_limit(session: AsyncSession, wtype: WorkItemType) -> int:
    """The most items one checklist of the type may hold (100 unless an admin changed it)."""
    found = await session.scalar(
        select(WorkItemTypeSettings.checklist_item_max).where(
            WorkItemTypeSettings.type == wtype.code
        )
    )
    return int(found or DEFAULT_ITEM_LIMIT)


async def _signal(  # noqa: PLR0913, PLR0917 - the record, the part and what changed, explicit
    session: AsyncSession,
    record: WorkItem,
    checklist_id: uuid.UUID,
    change: Literal["added", "changed", "removed"],
    changes: list[Change],
    source: Source,
) -> None:
    """History on the record and the live signal, in the change's transaction."""
    await record_changes(
        session,
        record_type=items.RECORD_TYPE,
        record_id=record.id,
        version=record.version,
        kind=_KIND[change],  # type: ignore[arg-type]  # one of the child kinds above
        changes=changes,
        source=source,
    )
    await record_event(
        session,
        WorkItemPartChangedV3(
            work_item_id=record.id, part="checklist", part_id=checklist_id, change=change
        ),
        aggregate_id=record.id,
    )


async def _views(session: AsyncSession, record_id: uuid.UUID) -> list[ChecklistView]:
    lists = list(
        await session.scalars(
            select(WorkItemChecklist)
            .where(
                WorkItemChecklist.work_item_id == record_id,
                WorkItemChecklist.deleted_at.is_(None),
            )
            .order_by(WorkItemChecklist.position, WorkItemChecklist.id)
        )
    )
    rows = await session.scalars(
        select(WorkItemChecklistItem)
        .where(
            WorkItemChecklistItem.work_item_id == record_id,
            WorkItemChecklistItem.deleted_at.is_(None),
        )
        .order_by(WorkItemChecklistItem.position, WorkItemChecklistItem.id)
    )
    by_list: dict[uuid.UUID, list[WorkItemChecklistItem]] = {c.id: [] for c in lists}
    for row in rows:
        by_list.setdefault(row.checklist_id, []).append(row)
    return [ChecklistView(c, by_list.get(c.id, [])) for c in lists]


async def checklists(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, record_id: uuid.UUID
) -> list[ChecklistView]:
    """A record's checklists in their order, each with its items."""
    await items.visible_record(session, subject, wtype, record_id)
    return await _views(session, record_id)


async def open_items(session: AsyncSession, record_id: uuid.UUID) -> int:
    """Items not ticked yet (the closing checks' open work)."""
    return int(
        await session.scalar(
            select(func.count())
            .select_from(WorkItemChecklistItem)
            .join(WorkItemChecklist, WorkItemChecklist.id == WorkItemChecklistItem.checklist_id)
            .where(
                WorkItemChecklistItem.work_item_id == record_id,
                WorkItemChecklistItem.deleted_at.is_(None),
                WorkItemChecklistItem.done_at.is_(None),
                WorkItemChecklist.deleted_at.is_(None),
            )
        )
        or 0
    )


async def _add_items(
    session: AsyncSession, record: WorkItem, checklist: WorkItemChecklist, texts: list[str]
) -> list[WorkItemChecklistItem]:
    current = await session.scalar(
        select(func.max(WorkItemChecklistItem.position)).where(
            WorkItemChecklistItem.checklist_id == checklist.id,
            WorkItemChecklistItem.deleted_at.is_(None),
        )
    )
    start = (current + 1) if current is not None else 0
    repo = ItemRepository(session)
    return [
        await repo.add(
            WorkItemChecklistItem(
                checklist_id=checklist.id,
                work_item_id=record.id,
                text=text,
                position=start + offset,
            )
        )
        for offset, text in enumerate(texts)
    ]


async def _copy_of(
    session: AsyncSession, wtype: WorkItemType, library_id: uuid.UUID
) -> ChecklistLibrary:
    found: ChecklistLibrary | None = await session.scalar(
        select(ChecklistLibrary).where(
            ChecklistLibrary.id == library_id,
            ChecklistLibrary.type == wtype.code,
            ChecklistLibrary.deleted_at.is_(None),
            ChecklistLibrary.disabled_at.is_(None),
        )
    )
    if found is None:
        raise NotFound(code="checklist_library_not_found")
    return found


async def add_checklist(  # noqa: PLR0913 - the record, the checklist and the source, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    values: dict[str, Any],
    *,
    source: Source,
) -> tuple[ChecklistView, int]:
    """A new checklist at the end, from scratch or a library copy; (it, empty items dropped)."""
    record = await parts.for_work(session, subject, wtype, record_id)
    return await _create(session, wtype, record, values, source=source)


async def _create(
    session: AsyncSession,
    wtype: WorkItemType,
    record: WorkItem,
    values: dict[str, Any],
    *,
    source: Source,
) -> tuple[ChecklistView, int]:
    existing = await _views(session, record.id)
    if len(existing) >= MAX_CHECKLISTS:
        raise _problems([("title", "too_many_items")], max=MAX_CHECKLISTS)
    library_id = values.get("library_id")
    library = await _copy_of(session, wtype, uuid.UUID(str(library_id))) if library_id else None
    title = " ".join(str(values.get("title") or (library.name if library else "")).split())
    raw = values.get("items")
    cleaned = clean_items(raw if raw is not None else (library.items if library else []))
    limit = await item_limit(session, wtype)
    problems = item_problems(cleaned.items, limit)
    if not title:
        problems.append(("title", "required"))
    elif len(title) > TITLE_MAX:
        problems.append(("title", "value_too_long"))
    if problems:
        raise _problems(problems, max=limit)
    checklist = await ChecklistRepository(session).add(
        WorkItemChecklist(
            work_item_id=record.id,
            title=title,
            position=(existing[-1].checklist.position + 1) if existing else 0,
            library_id=library.id if library else None,
        )
    )
    made = await _add_items(session, record, checklist, cleaned.items)
    await _signal(
        session,
        record,
        checklist.id,
        "added",
        [Change("checklist", None, title), Change("checklist.items", None, len(made))],
        source,
    )
    return ChecklistView(checklist, made), cleaned.dropped


async def _checklist(
    session: AsyncSession, record_id: uuid.UUID, checklist_id: uuid.UUID
) -> WorkItemChecklist:
    found: WorkItemChecklist | None = await session.scalar(
        select(WorkItemChecklist).where(
            WorkItemChecklist.id == checklist_id,
            WorkItemChecklist.work_item_id == record_id,
            WorkItemChecklist.deleted_at.is_(None),
        )
    )
    if found is None:
        raise NotFound(code="checklist_not_found")
    return found


async def add_items(  # noqa: PLR0913, PLR0917 - the checklist, its new items, the source
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    checklist_id: uuid.UUID,
    texts: Sequence[object],
    *,
    source: Source,
) -> int:
    """Items at the end of a checklist (within the limit); how many empty ones were dropped."""
    record = await parts.for_work(session, subject, wtype, record_id)
    checklist = await _checklist(session, record_id, checklist_id)
    cleaned = clean_items(texts)
    have = int(
        await session.scalar(
            select(func.count())
            .select_from(WorkItemChecklistItem)
            .where(
                WorkItemChecklistItem.checklist_id == checklist.id,
                WorkItemChecklistItem.deleted_at.is_(None),
            )
        )
        or 0
    )
    limit = await item_limit(session, wtype)
    problems = item_problems(cleaned.items, limit - have)
    if not cleaned.items:
        problems.append(("items", "required"))
    if problems:
        raise _problems(problems, max=limit)
    made = await _add_items(session, record, checklist, cleaned.items)
    await _signal(
        session,
        record,
        checklist.id,
        "changed",
        [
            Change("checklist", checklist.title, checklist.title),
            Change("checklist.items", have, have + len(made)),
        ],
        source,
    )
    return cleaned.dropped


async def tick(  # noqa: PLR0913 - the item, its version, done or not and the source, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    item_id: uuid.UUID,
    *,
    done: bool,
    expected_version: int,
    source: Source,
) -> WorkItemChecklistItem:
    """Tick (or untick) an item: who and when are kept with it (REQ-INC-077 AC1)."""
    record = await parts.for_work(session, subject, wtype, record_id)
    row: WorkItemChecklistItem | None = await session.scalar(
        select(WorkItemChecklistItem).where(
            WorkItemChecklistItem.id == item_id,
            WorkItemChecklistItem.work_item_id == record_id,
            WorkItemChecklistItem.deleted_at.is_(None),
        )
    )
    if row is None:
        raise NotFound(code="checklist_item_not_found")
    updated = await ItemRepository(session).update(
        row.id,
        expected_version=expected_version,
        changes={
            "done_at": datetime.now(UTC) if done else None,
            "done_by": subject.user_id if done else None,
        },
    )
    await _signal(
        session,
        record,
        row.checklist_id,
        "changed",
        [
            Change("checklist.item", row.text, row.text),
            Change("checklist.item.done", not done, done),
        ],
        source,
    )
    return updated


async def remove_checklist(  # noqa: PLR0913 - the checklist, its version and the source, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    checklist_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> None:
    """Remove a checklist and its items (soft delete)."""
    record = await parts.for_work(session, subject, wtype, record_id)
    checklist = await _checklist(session, record_id, checklist_id)
    own_items = list(
        await session.scalars(
            select(WorkItemChecklistItem).where(
                WorkItemChecklistItem.checklist_id == checklist.id,
                WorkItemChecklistItem.deleted_at.is_(None),
            )
        )
    )
    removed = await ChecklistRepository(session).soft_delete(
        checklist.id, expected_version=expected_version
    )
    item_repo = ItemRepository(session)
    for item in own_items:  # its items go with it: never open work on a removed checklist
        await item_repo.soft_delete(item.id, expected_version=item.version)
    await _signal(
        session, record, removed.id, "removed", [Change("checklist", removed.title, None)], source
    )


# --- open work at close (WP-020f port) -----------------------------------------------------------


async def open_work(session: AsyncSession, record: WorkItem) -> list[OpenItem]:
    """Unticked items of the record's checklists, named as "checklist: item"."""
    return [
        OpenItem(OpenWorkKind.CHECKLISTS, f"{view.checklist.title}: {item.text}")
        for view in await _views(session, record.id)
        for item in view.items
        if item.done_at is None
    ]


async def complete_work(session: AsyncSession, record: WorkItem) -> None:
    """The "complete open work on close" setting: every unticked item is ticked by the system."""
    now = datetime.now(UTC)
    repo = ItemRepository(session)
    for view in await _views(session, record.id):
        open_ones = [i for i in view.items if i.done_at is None]
        for item in open_ones:
            # The system ticks it on close: no person is named (done_by stays empty).
            await repo.update(item.id, expected_version=item.version, changes={"done_at": now})
        if open_ones:
            await _signal(
                session,
                record,
                view.checklist.id,
                "changed",
                [Change("checklist.completed", len(open_ones), 0)],
                "system",
            )


# --- the library (REQ-INC-078) -------------------------------------------------------------------


def _labels(raw: Any, problems: list[tuple[str, str]]) -> dict[str, str] | None:  # noqa: ANN401 - JSON
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) - LANGUAGES:
        problems.append(("labels", "invalid_value"))
        return None
    clean = {k: " ".join(str(v).split()) for k, v in raw.items() if str(v).strip()}
    if any(len(v) > TITLE_MAX for v in clean.values()):
        problems.append(("labels", "value_too_long"))
    return clean or None


async def library(
    session: AsyncSession, wtype: WorkItemType, *, include_disabled: bool
) -> list[ChecklistLibrary]:
    """The type's library checklists by name; disabled ones only for the admin's screen."""
    query = select(ChecklistLibrary).where(
        ChecklistLibrary.type == wtype.code, ChecklistLibrary.deleted_at.is_(None)
    )
    if not include_disabled:
        query = query.where(ChecklistLibrary.disabled_at.is_(None))
    return list(await session.scalars(query.order_by(ChecklistLibrary.name)))


async def save_library(
    session: AsyncSession,
    wtype: WorkItemType,
    library_id: uuid.UUID | None,
    values: dict[str, Any],
    *,
    expected_version: int | None = None,
) -> ChecklistLibrary:
    """Add (no id) or change a library checklist: name, translated names, items, disabled."""
    problems: list[tuple[str, str]] = []
    changes: dict[str, Any] = {}
    if "name" in values or library_id is None:
        name = " ".join(str(values.get("name") or "").split())
        if not name:
            problems.append(("name", "required"))
        elif len(name) > TITLE_MAX:
            problems.append(("name", "value_too_long"))
        changes["name"] = name
    if "labels" in values:
        changes["labels"] = _labels(values["labels"], problems)
    if "items" in values or library_id is None:
        cleaned = clean_items(values.get("items") or [])
        problems += item_problems(cleaned.items, await item_limit(session, wtype))
        changes["items"] = cleaned.items
    if "disabled" in values:
        changes["disabled_at"] = datetime.now(UTC) if values["disabled"] else None
    if problems:
        raise _problems(problems)
    repo = LibraryRepository(session)
    if library_id is None:
        return await repo.add(ChecklistLibrary(type=wtype.code, **changes))
    found: ChecklistLibrary | None = await session.scalar(
        select(ChecklistLibrary).where(
            ChecklistLibrary.id == library_id,
            ChecklistLibrary.type == wtype.code,
            ChecklistLibrary.deleted_at.is_(None),
        )
    )
    if found is None:
        raise NotFound(code="checklist_library_not_found")
    return await repo.update(found.id, expected_version=expected_version or 0, changes=changes)


async def import_items(session: AsyncSession, wtype: WorkItemType, content: bytes) -> ImportedItems:
    """Items read from a CSV for a library checklist (AC1); a whole-file failure is a 422."""
    found = parse_items_csv(content, limit=await item_limit(session, wtype))
    if isinstance(found, ImportFailure):
        raise ValidationFailed(
            errors=[
                FieldError(
                    field="file",
                    code=found.value,
                    message_key=f"checklist_import_failure.{found.value}",
                )
            ]
        )
    return found


# --- a record template's checklists (REQ-INC-040) -----------------------------------------------


async def add_template_checklists(
    session: AsyncSession,
    wtype: WorkItemType,
    record: WorkItem,
    checklists_: Sequence[dict[str, Any]],
    *,
    source: Source,
) -> int:
    """The template's checklists added to the new record (history says so); how many."""
    for spec in checklists_:
        await _create(session, wtype, record, dict(spec), source=source)
    return len(checklists_)


__all__ = [
    "ChecklistView",
    "add_checklist",
    "add_items",
    "add_template_checklists",
    "checklists",
    "import_items",
    "item_limit",
    "library",
    "open_items",
    "remove_checklist",
    "save_library",
    "tick",
]
