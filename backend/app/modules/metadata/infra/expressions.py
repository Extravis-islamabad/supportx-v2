"""Typed SQL for one custom field's value inside a record's JSONB (WP-026; architecture.md §6.6).

One place for the expressions, so list filters and the indexes that speed them up (D-087) are
the very same SQL text and PostgreSQL can use the index. The key is a literal (it matches
`^[a-z][a-z0-9_]{1,39}$`, checked here again), not a bound parameter: an expression index only
serves queries whose expression is identical, constants included.

Keys are shared across tenants (two tenants may give one key different types), so every cast is
guarded by the JSON type or shape: a value of another type reads as NULL instead of failing.
"""

import re
from typing import Any

from sqlalchemy import Boolean, Date, Numeric, String, literal_column
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP

from app.modules.metadata.domain.fields import FieldType

_KEY = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
_TABLE = re.compile(r"^[a-z_]{1,40}$")
NUMBERS = {FieldType.INTEGER, FieldType.DECIMAL, FieldType.CURRENCY}


def value_sql(table: str, key: str, kind: FieldType) -> tuple[str, Any]:
    """(SQL text, SQLAlchemy type) of the field's value in `table.custom`."""
    if not _KEY.fullmatch(key) or not _TABLE.fullmatch(table):
        msg = f"unsafe key or table {table!r}.{key!r}"
        raise ValueError(msg)
    raw = f"({table}.custom -> '{key}')"
    text = f"({table}.custom ->> '{key}')"
    if kind == FieldType.MULTI_CHOICE:
        return f"(CASE WHEN jsonb_typeof{raw} = 'array' THEN {raw} END)", JSONB()
    if kind in NUMBERS:
        return f"(CASE WHEN jsonb_typeof{raw} = 'number' THEN {text}::numeric END)", Numeric()
    if kind == FieldType.YES_NO:
        return f"(CASE WHEN jsonb_typeof{raw} = 'boolean' THEN {text}::boolean END)", Boolean()
    if kind == FieldType.DATE:
        return f"(CASE WHEN {text} ~ '^\\d{{4}}-\\d{{2}}-\\d{{2}}$' THEN {text}::date END)", Date()
    if kind == FieldType.DATETIME:
        # Stored in UTC ISO text (clean_value), so this cast is the same for every session.
        return (
            f"(CASE WHEN {text} ~ '^\\d{{4}}-\\d{{2}}-\\d{{2}}T' THEN {text}::timestamptz END)",
            TIMESTAMP(timezone=True),
        )
    return text, String()


def value_expression(table: str, key: str, kind: FieldType) -> Any:  # noqa: ANN401 - SQLAlchemy expression
    """The value as a typed SQLAlchemy expression (multiple choice: a JSONB array)."""
    sql, sql_type = value_sql(table, key, kind)
    return literal_column(sql, type_=sql_type)


def index_name(entity: str, key: str, kind: FieldType) -> str:
    """A stable index name within PostgreSQL's 63 characters, one per key and type."""
    return f"ix_cf_{entity}_{kind.value}_{key}"[:63]


def index_sql(table: str, entity: str, key: str, kind: FieldType) -> str:
    """CREATE INDEX CONCURRENTLY for one promoted field (run by the migration job, D-087)."""
    sql, _ = value_sql(table, key, kind)
    name = index_name(entity, key, kind)
    if kind == FieldType.MULTI_CHOICE:
        return f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {table} USING gin ({sql})"
    return f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {table} (tenant_id, type, {sql})"
