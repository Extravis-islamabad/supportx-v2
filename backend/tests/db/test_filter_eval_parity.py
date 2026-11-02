"""The in-memory filter evaluator gives the SQL compiler's answer (WP-025, D-115 D6).

A property test on real PostgreSQL: seeded random records (with missing values, mixed case,
LIKE characters, both ends of ranges) in a temporary table, and seeded random filters over every
field type and operator. For each filter, the rows SQL returns must be exactly the rows the
evaluator matches. A difference prints the filter and the rows that disagree.
"""

import random
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    MetaData,
    Numeric,
    String,
    Table,
    Uuid,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.shared.api.filter_eval import evaluate
from app.shared.api.filters import (
    OPERATORS,
    FieldType,
    FilterField,
    Op,
    ResourceFields,
    compile_filter,
)
from tooling.db_testing import ThrowawayDatabase

pytestmark = pytest.mark.db

NOW = datetime(2026, 11, 2, 10, 30, tzinfo=UTC)
CODES = ("p1", "p2", "p3", "p4")
TAGS = ("vpn", "mail", "printer")
WORDS = ("Mail", "mail down", "VPN_50%", "printer", "Ärger", "")
IDS = tuple(uuid.UUID(int=i) for i in range(1, 5))

metadata = MetaData()
things = Table(
    "parity_things",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("subject", String),
    Column("priority", String),
    Column("owner_id", Uuid),
    Column("due_at", DateTime(timezone=True)),
    Column("count", BigInteger),
    Column("flag", Boolean),
    Column("amount", Numeric(20, 4)),
    Column("day", Date),
    Column("tags", JSONB(none_as_null=True)),
    prefixes=["TEMPORARY"],
)
FIELDS = ResourceFields(
    name="parity",
    id_column=things.c.id,
    fields={
        "subject": FilterField(things.c.subject, FieldType.STRING),
        "priority": FilterField(things.c.priority, FieldType.ENUM, values=frozenset(CODES)),
        "owner_id": FilterField(things.c.owner_id, FieldType.UUID),
        "due_at": FilterField(things.c.due_at, FieldType.DATETIME),
        "count": FilterField(things.c.count, FieldType.INTEGER),
        "flag": FilterField(things.c.flag, FieldType.BOOLEAN),
        "amount": FilterField(things.c.amount, FieldType.DECIMAL),
        "day": FilterField(things.c.day, FieldType.DATE),
        "tags": FilterField(things.c.tags, FieldType.ENUM, values=frozenset(TAGS), array=True),
    },
)


def _maybe(rng: random.Random, value: Any) -> Any:  # noqa: ANN401 - any column value
    return None if rng.random() < 0.2 else value


def _row(rng: random.Random, i: int) -> dict[str, Any]:
    tags = rng.sample(TAGS, rng.randint(0, 3))
    return {
        "id": i,
        "subject": _maybe(rng, rng.choice(WORDS)),
        "priority": _maybe(rng, rng.choice(CODES)),
        "owner_id": _maybe(rng, rng.choice(IDS)),
        "due_at": _maybe(rng, NOW + timedelta(hours=rng.randint(-24 * 40, 24 * 40))),
        "count": _maybe(rng, rng.randint(-3, 3)),
        "flag": _maybe(rng, rng.random() < 0.5),
        "amount": _maybe(rng, Decimal(rng.randint(-500, 500)) / 100),
        "day": _maybe(rng, date(2026, 11, 2) + timedelta(days=rng.randint(-10, 10))),
        "tags": None if rng.random() < 0.15 else tags,
    }


def _value(rng: random.Random, name: str) -> Any:  # noqa: ANN401, PLR0911 - one per field type
    if name == "subject":
        return rng.choice(("mail", "MAIL", "50%", "_", "vpn", "Är", "x"))
    if name == "priority":
        return rng.choice(CODES)
    if name == "tags":
        return rng.choice(TAGS)
    if name == "owner_id":
        return str(rng.choice(IDS))
    if name == "due_at":
        return (NOW + timedelta(hours=rng.randint(-24 * 40, 24 * 40))).isoformat()
    if name == "count":
        return rng.randint(-3, 3)
    if name == "flag":
        return rng.random() < 0.5
    if name == "amount":
        return str(Decimal(rng.randint(-500, 500)) / 100)
    return (date(2026, 11, 2) + timedelta(days=rng.randint(-10, 10))).isoformat()


def _condition(rng: random.Random) -> dict[str, Any]:
    name = rng.choice(sorted(FIELDS.fields))
    spec = FIELDS.fields[name]
    op = rng.choice(sorted(OPERATORS[spec.type]))
    node: dict[str, Any] = {"field": name, "op": op.value}
    if op in {
        Op.IS_NULL,
        Op.IS_NOT_NULL,
        Op.TODAY,
        Op.YESTERDAY,
        Op.THIS_WEEK,
        Op.LAST_WEEK,
        Op.THIS_MONTH,
        Op.LAST_MONTH,
        Op.BEFORE_NOW,
        Op.AFTER_NOW,
    }:
        return node
    if op in {Op.LAST_N_DAYS, Op.NEXT_N_DAYS}:
        node["value"] = rng.randint(1, 30)
    elif op in {Op.IN, Op.NOT_IN}:
        node["value"] = list(dict.fromkeys(_value(rng, name) for _ in range(rng.randint(1, 3))))
    elif op is Op.BETWEEN:
        low, high = sorted((_value(rng, name), _value(rng, name)), key=_sort_key(spec))
        node["value"] = [low, high]
    else:
        node["value"] = _value(rng, name)
    return node


def _sort_key(spec: FilterField) -> Any:  # noqa: ANN401 - a key function
    if spec.type is FieldType.DECIMAL:
        return Decimal
    if spec.type is FieldType.DATETIME:
        return datetime.fromisoformat
    return lambda v: v


def _filter(rng: random.Random, depth: int = 0) -> dict[str, Any]:
    if depth < 2 and rng.random() < 0.4:
        kind = rng.choice(("and", "or"))
        return {kind: [_filter(rng, depth + 1) for _ in range(rng.randint(1, 3))]}
    return _condition(rng)


@pytest_asyncio.fixture
async def connection(migrated_db: ThrowawayDatabase) -> AsyncIterator[AsyncConnection]:
    url = migrated_db.admin_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            await conn.run_sync(metadata.create_all)
            yield conn
    finally:
        await engine.dispose()


async def test_the_evaluator_matches_sql_on_random_records_and_filters(
    connection: AsyncConnection,
) -> None:
    rng = random.Random(115)  # noqa: S311 - seeded test data, not security
    rows = [_row(rng, i) for i in range(1, 161)]
    await connection.execute(things.insert(), rows)
    checked = 0
    for _ in range(600):
        tree = _filter(rng)
        where = compile_filter(tree, FIELDS, now=NOW)
        in_sql = set(await connection.scalars(select(things.c.id).where(where)))
        in_memory = {row["id"] for row in rows if evaluate(tree, FIELDS, row, now=NOW)}
        assert in_memory == in_sql, (tree, sorted(in_memory ^ in_sql)[:5])
        checked += 1
    assert checked == 600


def test_an_invalid_filter_is_refused_exactly_like_the_compiler() -> None:
    from app.core.errors import ValidationFailed  # noqa: PLC0415 - only this test needs it

    bad = {"and": [{"field": "priority", "op": "eq", "value": "p9"}]}
    with pytest.raises(ValidationFailed) as sql:
        compile_filter(bad, FIELDS, now=NOW)
    with pytest.raises(ValidationFailed) as memory:
        evaluate(bad, FIELDS, {"priority": "p1"}, now=NOW)
    assert [e.field for e in memory.value.errors] == [e.field for e in sql.value.errors]
    assert [e.code for e in memory.value.errors] == [e.code for e in sql.value.errors]
