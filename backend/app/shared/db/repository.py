"""Generic async repository for tenant-scoped records (WP-005).

What every module gets for free:
- `get` / `list` that hide soft-deleted rows; `list` uses keyset pagination on the UUIDv7 id
  (stable under concurrent inserts, architecture.md §10) and returns an opaque cursor;
- `add` that fills id, tenant, timestamps, actors and version from the session's context;
- `update` / `soft_delete` with optimistic concurrency: `UPDATE ... WHERE id = :id AND
  version = :expected`. Zero rows means someone else changed (or deleted) the record first:
  409 Conflict with the current version, or 404 if it is gone (CLAUDE.md rule g).

Tenant safety does not depend on this class: RLS filters every statement in the database. The
repository only never *asks* for another tenant's data.
"""

import base64
import binascii
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import BadRequest, NotFound
from app.core.tenancy import TenantContext
from app.shared.clock import Clock, system_clock
from app.shared.history.conflicts import stale_version
from app.shared.ids import new_id

MAX_PAGE_SIZE = 200
# Columns the repository manages; callers may not set them through `update`.
MANAGED_COLUMNS = frozenset(
    {
        "id",
        "tenant_id",
        "created_at",
        "created_by",
        "updated_at",
        "updated_by",
        "version",
        "deleted_at",
    }
)


@dataclass(frozen=True)
class Page[T]:
    """One page of results plus the cursor for the next page (None on the last page)."""

    items: Sequence[T]
    next_cursor: str | None


def encode_cursor(last_id: uuid.UUID) -> str:
    """Opaque cursor for the row after `last_id`."""
    return base64.urlsafe_b64encode(last_id.bytes).decode().rstrip("=")


def decode_cursor(cursor: str) -> uuid.UUID:
    """Inverse of `encode_cursor`; 400 `invalid_cursor` for anything else."""
    try:
        return uuid.UUID(bytes=base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    except (ValueError, binascii.Error) as exc:
        raise BadRequest(code="invalid_cursor") from exc


class Repository[EntityT]:
    """Subclass per entity and set `model`: `class TicketRepository(Repository[Ticket])`."""

    model: ClassVar[type[Any]]

    def __init__(self, session: AsyncSession, *, clock: Clock = system_clock) -> None:
        context = session.info.get(SESSION_TENANT_KEY)
        if not isinstance(context, TenantContext):
            msg = "repositories need a tenant session (Database.tenant_session)"
            raise TypeError(msg)
        self.session = session
        self.context = context
        self.clock = clock

    async def get(self, entity_id: uuid.UUID, *, include_deleted: bool = False) -> EntityT:
        """The record, or 404 if it does not exist, is deleted, or belongs to another tenant."""
        query = select(self.model).where(self.model.id == entity_id)
        if not include_deleted:
            query = query.where(self.model.deleted_at.is_(None))
        entity: EntityT | None = await self.session.scalar(query)
        if entity is None:
            raise NotFound(params={"id": str(entity_id)})
        return entity

    async def list(self, *, limit: int = 50, cursor: str | None = None) -> Page[EntityT]:
        """Records in creation order (UUIDv7), `limit` per page (capped at 200)."""
        limit = max(1, min(limit, MAX_PAGE_SIZE))
        query = select(self.model).where(self.model.deleted_at.is_(None))
        if cursor is not None:
            query = query.where(self.model.id > decode_cursor(cursor))
        rows: list[EntityT] = list(
            (await self.session.scalars(query.order_by(self.model.id).limit(limit + 1))).all()
        )
        has_more = len(rows) > limit
        items = rows[:limit]
        last: Any = items[-1] if items else None  # see `add` for why Any
        return Page(items=items, next_cursor=encode_cursor(last.id) if has_more else None)

    async def add(self, entity: EntityT) -> EntityT:
        """Insert a new record for the session's tenant."""
        now = self.clock.now()
        # Any: EntityT is any mapped TenantEntity-shaped model; mypy cannot see its Mapped columns
        # through the generic, and the columns are guaranteed by the model base (and the guard).
        record: Any = entity
        record.id = record.id or new_id()
        record.tenant_id = self.context.tenant_id
        record.created_at = record.updated_at = now
        record.created_by = record.updated_by = self.context.user_id
        record.version = 1
        record.deleted_at = None
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def update(
        self, entity_id: uuid.UUID, *, expected_version: int, changes: Mapping[str, Any]
    ) -> EntityT:
        """Apply `changes` if the record is still at `expected_version`; bumps the version."""
        forbidden = MANAGED_COLUMNS.intersection(changes)
        if forbidden:
            msg = f"managed columns cannot be updated directly: {sorted(forbidden)}"
            raise ValueError(msg)
        return await self._versioned_update(entity_id, expected_version, dict(changes))

    async def soft_delete(self, entity_id: uuid.UUID, *, expected_version: int) -> EntityT:
        """Mark the record deleted (optimistic concurrency applies as for updates)."""
        return await self._versioned_update(
            entity_id, expected_version, {"deleted_at": self.clock.now()}
        )

    async def _versioned_update(
        self, entity_id: uuid.UUID, expected_version: int, values: dict[str, Any]
    ) -> EntityT:
        statement = (
            update(self.model)
            .where(
                self.model.id == entity_id,
                self.model.version == expected_version,
                self.model.deleted_at.is_(None),
            )
            .values(
                **values,
                version=self.model.version + 1,
                updated_at=self.clock.now(),
                updated_by=self.context.user_id,
            )
            .returning(self.model)
            .execution_options(populate_existing=True, synchronize_session=False)
        )
        updated: EntityT | None = await self.session.scalar(statement)
        if updated is not None:
            return updated
        current = await self.session.scalar(
            select(self.model).where(self.model.id == entity_id, self.model.deleted_at.is_(None))
        )
        if current is None:
            raise NotFound(params={"id": str(entity_id)})
        # Who saved it since, and when (QA WP-029 BUG-05).
        raise await stale_version(self.session, current, expected_version=expected_version)
