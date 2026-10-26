"""`python -m tooling.custom_field_indexes`: build the indexes admins asked for (WP-026, D-087).

An admin marks a custom field that lists filter often for an index (REQ-INC-014 AC2); the field
then shows "requested". This job, run as the migrator role with the deploy's migrate Job (or by
hand: `make custom-field-indexes`), builds each index with CREATE INDEX CONCURRENTLY, so writes
are never blocked, and records "active" or "failed" on the field (live on the admin screen).

Indexes are not tenant data: one expression index per key and type serves every tenant whose
field has that key and type (expressions.py), so a second request for the same index is free.
A failed concurrent build leaves an INVALID index behind; the job drops that one index (only an
index it just tried to build) so a later run can retry. Never touches records (CLAUDE.md rule h).

Environment: SUPPORTX_MIGRATION_DATABASE_URL (migrator).
"""

import asyncio
import sys
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.core.database import Database, create_engine
from app.core.logging import get_logger
from app.core.modules import discover_modules
from app.core.tenancy import TenantContext
from app.modules.metadata.domain.fields import ENTITY_TABLE, CustomFieldEntity, FieldType
from app.modules.metadata.infra.expressions import index_name, index_sql
from app.modules.metadata.service.custom_fields import index_finished, indexes_requested

log = get_logger(__name__)
# Stored on the field and shown as a label; the database's own message goes to the job log only.
BUILD_FAILED = "index_build_failed"


@dataclass(frozen=True)
class Request:
    """One field waiting for its index."""

    tenant: uuid.UUID
    field_id: uuid.UUID
    name: str
    statement: str


async def _requests(database: Database) -> list[Request]:
    async with database.platform_session() as session:
        # The migrator's platform policy on tenants lets it see every tenant (migration 0001).
        tenants = list(await session.scalars(text("SELECT id FROM tenants ORDER BY id")))
    found: list[Request] = []
    for tenant in tenants:
        async with database.tenant_session(TenantContext(tenant)) as session:
            for row in await indexes_requested(session):
                entity = CustomFieldEntity(row.entity)
                kind = FieldType(row.field_type)
                found.append(
                    Request(
                        tenant=tenant,
                        field_id=row.id,
                        name=index_name(entity.value, row.key, kind),
                        statement=index_sql(ENTITY_TABLE[entity], entity.value, row.key, kind),
                    )
                )
    return found


async def _build(engine: AsyncEngine, request: Request) -> str | None:
    """Build one index; None when it is valid afterwards, else the failure code."""
    # CONCURRENTLY cannot run inside a transaction block.
    async with engine.connect() as conn:
        auto = await conn.execution_options(isolation_level="AUTOCOMMIT")
        try:
            await auto.exec_driver_sql(request.statement)
        except Exception as exc:  # noqa: BLE001 - any database failure is recorded, then the next
            log.warning("custom_field_index_failed", index=request.name, error=str(exc))
        valid = await auto.scalar(
            text(
                "SELECT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid"
                " WHERE c.relname = :name"
            ),
            {"name": request.name},
        )
        if valid:
            return None
        if valid is False:
            await auto.exec_driver_sql(f"DROP INDEX CONCURRENTLY IF EXISTS {request.name}")
        return BUILD_FAILED


async def run(migrator_url: str) -> dict[str, int]:
    """Build every requested index; returns how many fields became active and failed."""
    discover_modules()
    database = Database(
        create_engine(migrator_url, application_name="custom-field-indexes", use_null_pool=True)
    )
    outcome = {"active": 0, "failed": 0}
    built: dict[str, str | None] = {}
    try:
        for request in await _requests(database):
            if request.name not in built:
                built[request.name] = await _build(database.engine, request)
            error = built[request.name]
            async with database.tenant_session(TenantContext(request.tenant)) as session:
                await index_finished(session, request.field_id, error)
            outcome["failed" if error else "active"] += 1
            log.info("custom_field_index", index=request.name, failed=error is not None)
    finally:
        await database.dispose()
    return outcome


def main() -> int:  # pragma: no cover - thin CLI over the tested functions
    """CLI entry point."""
    settings = Settings()
    if settings.migration_database_url is None:
        sys.stderr.write("custom field indexes need SUPPORTX_MIGRATION_DATABASE_URL\n")
        return 2
    outcome = asyncio.run(run(settings.migration_database_url.get_secret_value()))
    sys.stdout.write(
        f"custom field indexes: {outcome['active']} active, {outcome['failed']} failed\n"
    )
    return 1 if outcome["failed"] else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
