"""Alembic environment (WP-005): async engine, supportx_migrator, direct to PostgreSQL.

URL precedence: `config.attributes["database_url"]` (tests and tooling pass it in code), then
SUPPORTX_MIGRATION_DATABASE_URL from settings. The application role never runs migrations.
"""

import asyncio

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

import app.shared.db.display_ids  # noqa: F401 - registers display_id_sequences on the metadata
from app.core.config import Settings
from app.core.database import to_async_url
from app.core.modules import discover_modules
from app.shared.db.models import Base

# Importing every module registers its tables on Base.metadata (for autogenerate and checks).
discover_modules()
target_metadata = Base.metadata


def _database_url() -> str:
    explicit = context.config.attributes.get("database_url")
    if isinstance(explicit, str):
        return explicit
    configured = Settings().migration_database_url
    if configured is None:
        msg = "SUPPORTX_MIGRATION_DATABASE_URL is not set (run `make backend-env` for local dev)"
        raise RuntimeError(msg)
    return configured.get_secret_value()


def _configure(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_online() -> None:
    engine = create_async_engine(to_async_url(_database_url()), poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_configure)
            await connection.commit()
    finally:
        await engine.dispose()


if context.is_offline_mode():
    context.configure(url=_database_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(_run_online())
