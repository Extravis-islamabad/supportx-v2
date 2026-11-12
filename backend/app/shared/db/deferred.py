"""Deferred writes: a block's append-only rows, written as one multi-row INSERT per table.

An asset import saves up to a hundred assets in one savepoint, and each save appends the same
kinds of rows: its outbox events, its field history, its audit entry (with the entry's personal
data and its place in the sealing queue) and its valuation. Written one INSERT each, that was
about seven statements per asset (WP-049b S4c follow-up, step B). Inside

    async with deferred_writes(session):
        ...  # the saves

those writers hand their rows to the session's buffer instead (`deferred(session)`), and the
block writes them when it ends, one INSERT per table and chunk. The rows are built exactly as
before, at call time (IDs, times, hashes), so what lands is what the row-by-row path writes;
only the moment of the INSERT moves, still inside the same transaction. On an exception the
buffer is dropped and nothing is sent; the caller rolls its savepoint back anyway.

Only the import's batch savepoint opens a buffer (assets/service/imports.py `_apply_chunk`).

**Savepoints inside the block.** A savepoint opened in the block takes a mark (each table's
row count); when it rolls back, every list is cut back to its mark, so the rows of a rolled-back
save are never written. A rollback of the transaction the block started in drops everything.

**The guard.** A buffered row is not in the database yet, so code in the block that read it
back would silently see the table without it, a wrong answer rather than an error. Rather than
trust that no caller ever does, while rows are pending the session raises RuntimeError on
(a) any statement that reads one of the deferred tables (matched by name in the SQL sent; the
plain `INSERT INTO <table> ... VALUES` of a writer that still writes at once, an existing
asset's valuation upsert, is a write and passes), and (b) any flush carrying a new or changed
ORM row of those tables that went around the buffer, which would land before rows buffered
earlier. Both raise in production too: a wrong read in an import is worse than a failed batch,
which the import redoes row by row without the buffer.
"""

import re
from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import Table, event, insert
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction, UOWTransaction, class_mapper
from sqlalchemy.sql import FromClause

# The tables the writers defer (the guard watches them while rows are pending).
GUARDED = frozenset(
    {
        "outbox_events",
        "field_changes",
        "audit_entries",
        "audit_queue",
        "audit_personal",
        "asset_valuations",
    }
)
# The only guarded table a writer may still INSERT into at once while rows wait (see the guard).
IMMEDIATE_WRITES = "asset_valuations"
# Written first (the others' parent rows) and last (an event never precedes what it reports).
FIRST = ("audit_entries",)
LAST = ("outbox_events",)
# asyncpg's limit on bind parameters per statement; read at flush time (tests lower it).
MAX_BIND_PARAMS = 32_767

_KEY = "supportx.deferred_writes"
_NAMES = re.compile(r"\b(" + "|".join(sorted(GUARDED)) + r")\b")
_PLAIN_INSERT = re.compile(r"\s*INSERT INTO (\w+)\b", re.IGNORECASE)

Row = dict[str, Any]


class Buffer:
    """The pending rows of one `deferred_writes` block, per table, in call order."""

    def __init__(self, base: SessionTransaction | None) -> None:
        self._base = base
        self._tables: dict[str, Table] = {}
        self._rows: dict[str, list[Row]] = {}
        self._marks: dict[SessionTransaction, dict[str, int]] = {}
        self.flushing = False

    def add(self, *instances: object) -> None:
        """Buffer ORM instances (built as for `session.add`; never added to the session)."""
        for instance in instances:
            mapper = class_mapper(type(instance))
            values = {
                attr.columns[0].key: instance.__dict__[attr.key]
                for attr in mapper.column_attrs
                if attr.key in instance.__dict__
            }
            self.add_values(mapper.local_table, values)

    def add_values(self, table: FromClause, values: Mapping[str, Any]) -> None:
        """Buffer one row of a Core INSERT into `table` (a model's `__table__`)."""
        if not isinstance(table, Table):  # pragma: no cover - our models map tables
            msg = f"deferred writes: {table} is not a table"
            raise TypeError(msg)
        row = dict(values)
        for column in table.columns:
            # Python-side defaults now, as a flush would: every row then has the same keys,
            # and a new_id() primary key is made at call time like the rest of the row.
            default = column.default
            if column.key in row or default is None:
                continue
            if default.is_scalar:
                row[column.key] = default.arg
            elif default.is_callable:
                row[column.key] = default.arg(None)  # wrapped to take a context
        self._tables.setdefault(table.name, table)
        self._rows.setdefault(table.name, []).append(row)

    def pending(self) -> int:
        """How many rows wait to be written."""
        return sum(len(rows) for rows in self._rows.values())

    def tables(self) -> Iterator[tuple[Table, list[Row]]]:
        """The tables with pending rows, parents first and the outbox last."""
        names = [n for n in FIRST if n in self._rows]
        names += [n for n in self._rows if n not in FIRST and n not in LAST]
        names += [n for n in LAST if n in self._rows]
        for name in names:
            if self._rows[name]:
                yield self._tables[name], self._rows[name]

    def clear(self) -> None:
        """Drop every pending row."""
        self._rows.clear()

    def mark(self, transaction: SessionTransaction) -> None:
        """A savepoint opened in the block: remember where each list stands."""
        self._marks[transaction] = {name: len(rows) for name, rows in self._rows.items()}

    def rolled_back(self, transaction: SessionTransaction) -> None:
        """A rollback: cut back to the savepoint's mark, or drop everything for the base."""
        mark = self._marks.pop(transaction, None)
        if mark is None:
            # Not a savepoint of the block: the block's own transaction or one around it, so
            # nothing buffered here may be written.
            self.clear()
            return
        for name, rows in self._rows.items():
            del rows[mark.get(name, 0) :]


def deferred(session: AsyncSession | Session) -> Buffer | None:
    """The session's open buffer, or None (the writers then write at once, as always)."""
    found = session.info.get(_KEY)
    return found if isinstance(found, Buffer) else None


def _chunks(rows: list[Row]) -> Iterator[list[Row]]:
    """Runs of rows with the same columns, each small enough for one statement's parameters."""
    start = 0
    while start < len(rows):
        keys = rows[start].keys()
        size = max(1, MAX_BIND_PARAMS // max(1, len(keys)))
        end = start + 1
        while end < len(rows) and end - start < size and rows[end].keys() == keys:
            end += 1
        yield rows[start:end]
        start = end


async def flush_deferred(session: AsyncSession) -> None:
    """Write the pending rows now: one INSERT per table and chunk, in foreign-key order."""
    buffer = deferred(session)
    if buffer is None or not buffer.pending():
        return
    buffer.flushing = True
    try:
        for table, rows in list(buffer.tables()):
            for chunk in _chunks(rows):
                # Core INSERT without RETURNING: the app role may not read the outbox back.
                await session.execute(insert(table).values(chunk))
        buffer.clear()
    finally:
        buffer.flushing = False


@asynccontextmanager
async def deferred_writes(session: AsyncSession, *, write: bool = True) -> AsyncIterator[None]:
    """Buffer the block's deferred rows; write them as it ends (`write` False: drop them).

    `write=False` is for a block whose savepoint is rolled back anyway (an import's dry run):
    every check of a save runs before its rows reach the buffer, so skipping the writes
    changes no outcome.
    """
    if deferred(session) is not None:
        msg = "deferred writes: a block is already open on this session"
        raise RuntimeError(msg)
    sync = session.sync_session
    connection = (await session.connection()).sync_connection
    if connection is None:  # pragma: no cover - session.connection() always gives one
        msg = "deferred writes: the session has no connection"
        raise RuntimeError(msg)
    buffer = Buffer(sync.get_nested_transaction() or sync.get_transaction())

    def guard(
        _conn: Connection,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,  # noqa: FBT001 - positional in SQLAlchemy's signature
    ) -> None:
        if buffer.flushing or not buffer.pending():
            return
        names = set(_NAMES.findall(statement))
        if not names:
            return
        target = _PLAIN_INSERT.match(statement)
        if (
            target is not None
            and names == {target.group(1)} == {IMMEDIATE_WRITES}
            and "SELECT" not in statement.upper()
        ):
            # The one writer that still writes at once: an existing asset's valuation upsert
            # (only new assets' valuations are buffered). Any other immediate INSERT into a
            # guarded table means a path went around the buffer: refused (lane C's #449 review).
            return
        what = "written around the buffer" if target is not None else "read"
        msg = f"deferred writes: {min(names)} {what} before flush"
        raise RuntimeError(msg)

    session.info[_KEY] = buffer
    event.listen(connection, "before_cursor_execute", guard)
    try:
        yield
        if write:
            await flush_deferred(session)
    finally:
        session.info.pop(_KEY, None)
        event.remove(connection, "before_cursor_execute", guard)


# --- session events (every Session; a no-op without an open buffer) -----------------------------


@event.listens_for(Session, "after_transaction_create")
def _mark(session: Session, transaction: SessionTransaction) -> None:
    buffer = deferred(session)
    if buffer is not None and transaction.nested:
        buffer.mark(transaction)


@event.listens_for(Session, "after_soft_rollback")
def _rolled_back(session: Session, previous_transaction: SessionTransaction) -> None:
    # Fires for a savepoint's rollback too (after the transaction closed), with that savepoint.
    buffer = deferred(session)
    if buffer is not None:
        buffer.rolled_back(previous_transaction)


@event.listens_for(Session, "before_flush")
def _no_bypass(session: Session, _flush_context: UOWTransaction, _instances: object) -> None:
    buffer = deferred(session)
    if buffer is None or buffer.flushing or not buffer.pending():
        return
    for instance in (*session.new, *session.dirty):
        name = getattr(type(instance), "__tablename__", None)
        if name in GUARDED:
            msg = f"deferred writes: {name} written around the buffer before flush"
            raise RuntimeError(msg)
