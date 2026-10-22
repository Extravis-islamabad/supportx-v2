"""A test-only tenant-scoped table (`probe_items`) built exactly like a real business table.

It lives on its own metadata so it never leaks into Alembic autogenerate or the app, and is
created in each throwaway test database with the same RLS helpers migrations use.
"""

from typing import cast

import asyncpg
from sqlalchemy import Column, Index, MetaData, Table, Uuid
from sqlalchemy.dialects.postgresql.base import PGDialect
from sqlalchemy.orm import DeclarativeBase, Mapped
from sqlalchemy.schema import CreateIndex, CreateTable

from app.shared.db.models import (
    NAMING_CONVENTION,
    Actors,
    Base,
    SoftDeleted,
    TenantScoped,
    Timestamps,
    UuidPrimaryKey,
    Versioned,
)
from app.shared.db.repository import Repository
from app.shared.db.rls import app_grant_statements, tenant_rls_statements


class ProbeBase(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = Base.type_annotation_map  # same column types as real models


# Stub so the tenant_id foreign key resolves inside this metadata.
Table("tenants", ProbeBase.metadata, Column("id", Uuid, primary_key=True))


class ProbeItem(
    UuidPrimaryKey, TenantScoped, Timestamps, Actors, Versioned, SoftDeleted, ProbeBase
):
    __tablename__ = "probe_items"
    __table_args__ = (Index(None, "tenant_id", "created_at"),)

    title: Mapped[str]


class ProbeRepository(Repository[ProbeItem]):
    model = ProbeItem


def probe_ddl() -> list[str]:
    """CREATE TABLE/INDEX + RLS + grants for probe_items, as PostgreSQL SQL."""
    dialect = PGDialect()  # type: ignore[no-untyped-call]  # SQLAlchemy dialect classes are unannotated
    table = cast("Table", ProbeItem.__table__)
    statements = [str(CreateTable(table).compile(dialect=dialect))]
    statements += [str(CreateIndex(index).compile(dialect=dialect)) for index in table.indexes]
    return statements + tenant_rls_statements("probe_items") + app_grant_statements("probe_items")


async def create_probe_table(migrator_url: str) -> None:
    """Create probe_items as the migrator (table owner), like a migration would."""
    conn = await asyncpg.connect(migrator_url)
    try:
        async with conn.transaction():
            for statement in probe_ddl():
                await conn.execute(statement)
    finally:
        await conn.close()
