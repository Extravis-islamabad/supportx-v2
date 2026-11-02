"""Field history implementation (see the package docstring)."""

import uuid
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from fastapi import Request
from sqlalchemy import BigInteger, CheckConstraint, Index, String, Text, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict
from app.core.request_context import current_request_id
from app.core.tenancy import TenantContext
from app.shared.clock import system_clock
from app.shared.db.models import Base, TenantScoped, UuidPrimaryKey
from app.shared.ids import new_id

# Who made the change, as far as the server can tell. Informational, never a security control:
# `ui` means the request came from our console/portal (they send CLIENT_HEADER).
Source = Literal[
    "ui",
    "api",
    "portal",
    "email",
    "rule",
    "workflow",
    "sla",
    "ai_agent",
    "integration",
    "system",
    "import",
]
# `child_*`: a part of the record (a note, a task, a link) was added, changed or removed; `field`
# names the kind of part. Those saves do not bump the record's version (ADR-026).
ChangeKind = Literal[
    "created",
    "updated",
    "status",
    "deleted",
    "restored",
    "child_added",
    "child_changed",
    "child_removed",
]
SOURCES: tuple[str, ...] = Source.__args__  # type: ignore[attr-defined]  # Literal members
KINDS: tuple[str, ...] = ChangeKind.__args__  # type: ignore[attr-defined]  # Literal members
CLIENT_HEADER = "X-SupportX-Client"
_UI_CLIENTS = frozenset({"console", "portal", "mobile"})
MAX_PAGE = 100
CHANGE_IDS_KEY = "supportx.change_ids"
BATCH_KEY = "supportx.batch_id"

JsonValue = Any  # JSON-serialisable field value (str, number, bool, None, list, dict)


class FieldChange(UuidPrimaryKey, TenantScoped, Base):
    """One changed field of one save (append-only)."""

    __tablename__ = "field_changes"
    __table_args__ = (
        Index(None, "tenant_id", "record_type", "record_id", "record_version"),
        Index(
            "ix_field_changes_tenant_record_time",
            "tenant_id",
            "record_type",
            "record_id",
            "occurred_at",
            "change_id",
        ),
        # Reports (lane C, WP-035): backlog over time and time in status.
        Index(
            "ix_field_changes_tenant_type_field_time",
            "tenant_id",
            "record_type",
            "field",
            "occurred_at",
        ),
        CheckConstraint("kind IN (" + ", ".join(f"'{k}'" for k in KINDS) + ")", name="kind_code"),
        CheckConstraint(
            "source IN (" + ", ".join(f"'{s}'" for s in SOURCES) + ")", name="source_code"
        ),
        CheckConstraint("reason IS NULL OR char_length(reason) <= 500", name="reason_length"),
    )

    record_type: Mapped[str] = mapped_column(String(40))
    record_id: Mapped[uuid.UUID]
    record_version: Mapped[int] = mapped_column(BigInteger)
    change_id: Mapped[uuid.UUID]
    kind: Mapped[str] = mapped_column(String(20))
    field: Mapped[str] = mapped_column(String(80))
    old_value: Mapped[JsonValue | None] = mapped_column(JSONB)
    new_value: Mapped[JsonValue | None] = mapped_column(JSONB)
    actor_type: Mapped[str] = mapped_column(String(10))
    actor_id: Mapped[str | None] = mapped_column(String(128))
    source: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(String(64))
    occurred_at: Mapped[datetime]
    # What automation made the change, when one did (ADR-026): {"kind": "matrix"} or
    # {"kind": "rule", "id": ..., "name": ...}. NULL for people's own changes.
    automation_ref: Mapped[JsonValue | None] = mapped_column(JSONB(none_as_null=True))
    # The background job that made a person's change on their behalf (a bulk change, WP-020d),
    # so each record's history names it (REQ-INC-120 AC4). NULL for direct changes.
    batch_id: Mapped[uuid.UUID | None]


@dataclass(frozen=True)
class Change:
    """One field's old and new value."""

    field: str
    old: JsonValue
    new: JsonValue


@dataclass(frozen=True)
class HistoryEntry:
    """One save: what changed, by whom, from where, why."""

    change_id: uuid.UUID
    version: int
    kind: ChangeKind
    occurred_at: datetime
    actor_type: str
    actor_id: str | None
    source: Source
    reason: str | None
    changes: list[Change] = field(default_factory=list)
    automation_ref: JsonValue | None = None
    batch_id: uuid.UUID | None = None


@dataclass(frozen=True)
class ChangesSince:
    """What happened to a record after a given version (for 409 messages)."""

    fields: list[str]
    actor_ids: list[str]
    last_at: datetime | None


def source_of(request: Request) -> Source:
    """`ui` for our own apps (they send X-SupportX-Client), else `api`."""
    client = request.headers.get(CLIENT_HEADER, "").strip().lower()
    return "ui" if client in _UI_CLIENTS else "api"


def _actor(session: AsyncSession) -> tuple[str, str | None]:
    context = session.info.get(SESSION_TENANT_KEY)
    if isinstance(context, TenantContext) and context.user_id is not None:
        return "user", str(context.user_id)
    return "system", None


def in_batch(session: AsyncSession, batch_id: uuid.UUID | None) -> None:
    """Mark the session's next history rows as made by background job `batch_id` (None: stop)."""
    if batch_id is None:
        session.info.pop(BATCH_KEY, None)
    else:
        session.info[BATCH_KEY] = batch_id


async def record_changes(  # noqa: PLR0913 - every part of a change, explicit
    session: AsyncSession,
    *,
    record_type: str,
    record_id: uuid.UUID,
    version: int,
    kind: ChangeKind,
    changes: Iterable[Change],
    source: Source,
    reason: str | None = None,
    automation_ref: JsonValue | None = None,
) -> uuid.UUID:
    """Write one save's field changes (same transaction as the record). Returns the change ID.

    `automation_ref` names the automation that made the change, if any (ADR-026).
    """
    change_id = new_id()
    batch_id = session.info.get(BATCH_KEY)
    actor_type, actor_id = _actor(session)
    now = system_clock.now()
    request_id = current_request_id()
    rows = [
        FieldChange(
            record_type=record_type,
            record_id=record_id,
            record_version=version,
            change_id=change_id,
            kind=kind,
            field=change.field,
            old_value=change.old,
            new_value=change.new,
            actor_type=actor_type,
            actor_id=actor_id,
            source=source,
            reason=reason,
            request_id=request_id,
            occurred_at=now,
            automation_ref=automation_ref,
            batch_id=batch_id,
        )
        for change in changes
    ]
    if not rows:  # a status change or deletion with no field diff still deserves a line
        rows = [
            FieldChange(
                record_type=record_type,
                record_id=record_id,
                record_version=version,
                change_id=change_id,
                kind=kind,
                field="",
                old_value=None,
                new_value=None,
                actor_type=actor_type,
                actor_id=actor_id,
                source=source,
                reason=reason,
                request_id=request_id,
                occurred_at=now,
                automation_ref=automation_ref,
                batch_id=batch_id,
            )
        ]
    context = session.info.get(SESSION_TENANT_KEY)
    if isinstance(context, TenantContext):
        for row in rows:
            row.tenant_id = context.tenant_id
    session.add_all(rows)
    await session.flush()
    # The audit log links its entry for this request to the history it wrote (REQ-AUD-006).
    session.info.setdefault(CHANGE_IDS_KEY, []).append(change_id)
    return change_id


def recorded_change_ids(session: AsyncSession) -> list[uuid.UUID]:
    """Change IDs of the field history written in this session's transaction, in order."""
    return list(session.info.get(CHANGE_IDS_KEY, ()))


def changes_between(before: dict[str, JsonValue], after: dict[str, JsonValue]) -> list[Change]:
    """The fields whose values differ, in the order of `after`."""
    return [
        Change(name, before.get(name), value)
        for name, value in after.items()
        if before.get(name) != value
    ]


async def changes_since(
    session: AsyncSession, record_type: str, record_id: uuid.UUID, version: int
) -> ChangesSince:
    """Fields changed, and by whom, in saves after `version` (oldest first)."""
    rows = (
        await session.execute(
            select(FieldChange.field, FieldChange.actor_id, FieldChange.occurred_at)
            .where(
                FieldChange.record_type == record_type,
                FieldChange.record_id == record_id,
                FieldChange.record_version > version,
            )
            .order_by(FieldChange.record_version, FieldChange.id)
        )
    ).all()
    fields: list[str] = []
    actors: list[str] = []
    for row in rows:
        if row.field and row.field not in fields:
            fields.append(row.field)
        if row.actor_id and row.actor_id not in actors:
            actors.append(row.actor_id)
    return ChangesSince(fields, actors, rows[-1].occurred_at if rows else None)


async def explain_conflict(
    session: AsyncSession,
    conflict: Conflict,
    *,
    record_type: str,
    record_id: uuid.UUID,
    names: Callable[[Sequence[str]], Awaitable[Sequence[str]]],
) -> Conflict:
    """The same 409 with who changed which fields since the version the client sent.

    Adds params `changed_fields` (comma-separated field codes, labelled by the UI),
    `changed_by` (comma-separated display names) and `changed_at` (ISO time of the last save).
    """
    expected = conflict.params.get("expected_version")
    if conflict.instance_code != "version_conflict" or not isinstance(expected, int):
        return conflict
    since = await changes_since(session, record_type, record_id, expected)
    params = dict(conflict.params)
    params["changed_fields"] = ",".join(since.fields)
    params["changed_by"] = ", ".join(await names(since.actor_ids)) if since.actor_ids else ""
    params["changed_at"] = since.last_at.isoformat() if since.last_at else None
    return Conflict(code="version_conflict", params=params, headers=conflict.headers)


async def history_page(
    session: AsyncSession,
    record_type: str,
    record_id: uuid.UUID,
    *,
    before_version: int | None = None,
    limit: int = 25,
) -> tuple[list[HistoryEntry], int | None]:
    """Saves of one record, newest first, `limit` saves per page; plus the next cursor."""
    limit = max(1, min(limit, MAX_PAGE))
    versions_query = (
        select(FieldChange.record_version)
        .where(FieldChange.record_type == record_type, FieldChange.record_id == record_id)
        .group_by(FieldChange.record_version)
        .order_by(FieldChange.record_version.desc())
        .limit(limit + 1)
    )
    if before_version is not None:
        versions_query = versions_query.where(FieldChange.record_version < before_version)
    versions = list(await session.scalars(versions_query))
    more = len(versions) > limit
    versions = versions[:limit]
    if not versions:
        return [], None
    rows = (
        await session.scalars(
            select(FieldChange)
            .where(
                FieldChange.record_type == record_type,
                FieldChange.record_id == record_id,
                FieldChange.record_version.in_(versions),
            )
            .order_by(FieldChange.record_version.desc(), FieldChange.id)
        )
    ).all()
    entries: dict[uuid.UUID, HistoryEntry] = {}
    for row in rows:
        entry = entries.get(row.change_id)
        if entry is None:
            entry = entries[row.change_id] = HistoryEntry(
                change_id=row.change_id,
                version=row.record_version,
                kind=row.kind,  # type: ignore[arg-type]  # stored from ChangeKind
                occurred_at=row.occurred_at,
                actor_type=row.actor_type,
                actor_id=row.actor_id,
                source=row.source,  # type: ignore[arg-type]  # stored from Source
                reason=row.reason,
            )
        if row.field:
            entry.changes.append(Change(row.field, row.old_value, row.new_value))
    return list(entries.values()), versions[-1] if more else None


async def count_saves(session: AsyncSession, record_type: str, record_id: uuid.UUID) -> int:
    """How many saves a record has (the History tab's counter)."""
    total = await session.scalar(
        select(func.count(func.distinct(FieldChange.change_id))).where(
            FieldChange.record_type == record_type, FieldChange.record_id == record_id
        )
    )
    return int(total or 0)


HistoryCursor = tuple[datetime, uuid.UUID]
Actors = Literal["all", "people", "automation"]


async def history_entries(  # noqa: PLR0913 - keyword-only paging and filter options
    session: AsyncSession,
    record_type: str,
    record_id: uuid.UUID,
    *,
    before: HistoryCursor | None = None,
    limit: int = 25,
    actors: Actors = "all",
) -> tuple[list[HistoryEntry], HistoryCursor | None]:
    """Saves of one record, newest first, in true order (ADR-026); plus the next cursor.

    Ordered by the time each save was written (microseconds) and then its change ID, not by the
    record version: parts of a record (notes, tasks, links) are saved without bumping the version,
    and they still appear exactly where they happened. `actors`: people only (`actor_type`
    user without automation), automation only, or both.
    """
    limit = max(1, min(limit, MAX_PAGE))
    saves = (
        select(FieldChange.occurred_at, FieldChange.change_id)
        .where(FieldChange.record_type == record_type, FieldChange.record_id == record_id)
        .group_by(FieldChange.occurred_at, FieldChange.change_id)
        .order_by(FieldChange.occurred_at.desc(), FieldChange.change_id.desc())
        .limit(limit + 1)
    )
    if actors == "people":
        saves = saves.where(FieldChange.actor_type == "user", FieldChange.automation_ref.is_(None))
    elif actors == "automation":
        saves = saves.where(
            (FieldChange.actor_type != "user") | FieldChange.automation_ref.is_not(None)
        )
    if before is not None:
        at, change_id = before
        saves = saves.where(
            (FieldChange.occurred_at < at)
            | ((FieldChange.occurred_at == at) & (FieldChange.change_id < change_id))
        )
    found = (await session.execute(saves)).all()
    more = len(found) > limit
    found = found[:limit]
    if not found:
        return [], None
    change_ids = [row.change_id for row in found]
    rows = (
        await session.scalars(
            select(FieldChange)
            .where(
                FieldChange.record_type == record_type,
                FieldChange.record_id == record_id,
                FieldChange.change_id.in_(change_ids),
            )
            .order_by(FieldChange.id)
        )
    ).all()
    entries: dict[uuid.UUID, HistoryEntry] = {}
    for row in rows:
        entry = entries.get(row.change_id)
        if entry is None:
            entry = entries[row.change_id] = HistoryEntry(
                change_id=row.change_id,
                version=row.record_version,
                kind=row.kind,  # type: ignore[arg-type]  # stored from ChangeKind
                occurred_at=row.occurred_at,
                actor_type=row.actor_type,
                actor_id=row.actor_id,
                source=row.source,  # type: ignore[arg-type]  # stored from Source
                reason=row.reason,
                automation_ref=row.automation_ref,
                batch_id=row.batch_id,
            )
        if row.field:
            entry.changes.append(Change(row.field, row.old_value, row.new_value))
    last = found[-1]
    ordered = [entries[cid] for cid in change_ids if cid in entries]
    return ordered, (last.occurred_at, last.change_id) if more else None
