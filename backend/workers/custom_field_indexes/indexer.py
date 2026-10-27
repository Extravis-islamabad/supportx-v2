"""Build the custom field indexes admins asked for (WP-026, REQ-INC-014 AC2, D-088, ADR-030).

An admin's request marks the field "pending". One pass, run by the index worker every
`index_worker_interval_seconds` (and by the deploy's migrate Job as a fallback):

1. take the index advisory lock (one builder at a time, across replicas and the migrate Job);
2. collect every tenant's pending fields, and fields left "building" by a pass that stopped;
3. per index (one expression index serves every tenant with that key and type): mark its fields
   "building", run CREATE INDEX CONCURRENTLY (writes go on), then mark them "active" or "failed"
   with a reason code. Each step is a normal tenant write: history, outbox event, live screens.

Runs as the migrator role: only the table owner may create an index, and a concurrent build
cannot run inside a transaction (so not in a database function either). The API and the other
workers never get DDL rights. A failed concurrent build leaves an INVALID index; the pass drops
that index (only one it just tried to build) so a later request can retry. Never touches records.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.database import Database
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.metadata.domain.fields import (
    ENTITY_TABLE,
    CustomFieldEntity,
    FieldType,
    IndexFailure,
    IndexState,
)
from app.modules.metadata.infra.expressions import index_name, index_sql
from app.modules.metadata.service.custom_fields import index_progress, indexes_waiting

log = get_logger(__name__)
LOCK_CLASS = 724120  # first key of the two-int advisory lock: "custom field indexes"
LOCK_KEY = 1

# SQLSTATE → the reason admins read (labels `custom_field_index_error.<code>`).
FAILURES: dict[str, IndexFailure] = {
    "57014": IndexFailure.TIMED_OUT,  # query_canceled (statement_timeout)
    "55P03": IndexFailure.BUSY,  # lock_not_available (lock_timeout)
    "40P01": IndexFailure.BUSY,  # deadlock_detected
    "53100": IndexFailure.DISK_FULL,
    "53200": IndexFailure.OUT_OF_MEMORY,
    "54000": IndexFailure.VALUE_TOO_LARGE,  # program_limit_exceeded (index row too big)
}


@dataclass(frozen=True)
class Waiting:
    """One field waiting for its index."""

    tenant: uuid.UUID
    field_id: uuid.UUID
    name: str
    statement: str


def failure_of(error: BaseException) -> IndexFailure:
    """The reason for a database error (any wrapper: SQLAlchemy, asyncpg)."""
    seen: BaseException | None = error
    while seen is not None:
        state = getattr(seen, "sqlstate", None) or getattr(seen, "pgcode", None)
        if isinstance(state, str):
            return FAILURES.get(state, IndexFailure.UNEXPECTED)
        seen = getattr(seen, "orig", None) or seen.__cause__
    return IndexFailure.UNEXPECTED


async def waiting(database: Database) -> list[Waiting]:
    """Every tenant's fields waiting for an index."""
    async with database.platform_session() as session:
        # The migrator's platform policy on tenants lets it see every tenant (migration 0001).
        tenants = list(await session.scalars(text("SELECT id FROM tenants ORDER BY id")))
    found: list[Waiting] = []
    for tenant in tenants:
        async with database.tenant_session(TenantContext(tenant)) as session:
            for row in await indexes_waiting(session):
                entity = CustomFieldEntity(row.entity)
                kind = FieldType(row.field_type)
                found.append(
                    Waiting(
                        tenant=tenant,
                        field_id=row.id,
                        name=index_name(entity.value, row.key, kind),
                        statement=index_sql(ENTITY_TABLE[entity], entity.value, row.key, kind),
                    )
                )
    return found


async def build(
    conn: AsyncConnection, name: str, statement: str, *, lock_timeout: int, build_timeout: int
) -> IndexFailure | None:
    """Build one index on an autocommit connection; None when it is valid afterwards."""
    failure: IndexFailure | None = None
    await conn.exec_driver_sql(f"SET lock_timeout = '{lock_timeout:d}s'")
    await conn.exec_driver_sql(f"SET statement_timeout = '{build_timeout:d}s'")
    try:
        await conn.exec_driver_sql(statement)
    except Exception as error:  # noqa: BLE001 - every database failure is recorded, then the next
        failure = failure_of(error)
        log.warning("custom_field_index_failed", index=name, reason=failure, error=str(error))
    finally:
        await conn.exec_driver_sql("RESET statement_timeout")
        await conn.exec_driver_sql("RESET lock_timeout")
    valid = await conn.scalar(
        text(
            "SELECT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid"
            " WHERE c.relname = :name"
        ),
        {"name": name},
    )
    if valid:
        return None
    if valid is False:
        await conn.exec_driver_sql(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
    return failure or IndexFailure.UNEXPECTED


async def _mark(
    database: Database, fields: list[Waiting], state: IndexState, failure: IndexFailure | None
) -> None:
    for field in fields:
        async with database.tenant_session(TenantContext(field.tenant)) as session:
            await index_progress(session, field.field_id, state, failure)


async def run_pass(
    database: Database, *, lock_timeout: int = 60, build_timeout: int = 7200
) -> dict[str, int] | None:
    """One pass; fields made active and failed, or None when another builder holds the lock."""
    outcome = {"active": 0, "failed": 0}
    async with database.engine.connect() as conn:
        auto = await conn.execution_options(isolation_level="AUTOCOMMIT")
        locked = await auto.scalar(
            text("SELECT pg_try_advisory_lock(:c, :k)"), {"c": LOCK_CLASS, "k": LOCK_KEY}
        )
        if not locked:
            return None
        try:
            by_index: dict[str, list[Waiting]] = {}
            for field in await waiting(database):
                by_index.setdefault(field.name, []).append(field)
            for name, fields in by_index.items():
                await _mark(database, fields, IndexState.BUILDING, None)
                failure = await build(
                    auto,
                    name,
                    fields[0].statement,
                    lock_timeout=lock_timeout,
                    build_timeout=build_timeout,
                )
                state = IndexState.FAILED if failure else IndexState.ACTIVE
                await _mark(database, fields, state, failure)
                outcome[state.value] += len(fields)
                log.info("custom_field_index", index=name, state=state, reason=failure)
        finally:
            await auto.scalar(
                text("SELECT pg_advisory_unlock(:c, :k)"), {"c": LOCK_CLASS, "k": LOCK_KEY}
            )
    return outcome
