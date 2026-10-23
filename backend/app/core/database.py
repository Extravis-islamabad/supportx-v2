"""Async database access: engine, sessions, tenant context and unit of work (WP-005).

Two rules make tenant isolation hold even when application code is wrong (CLAUDE.md rule a):

1. Every transaction of a *tenant session* starts with
   `set_config('app.tenant_id', <tenant>, true)` (the parameterised form of `SET LOCAL`), written
   by an `after_begin` hook, so no code path can forget it. A tenant session without a tenant
   raises before any SQL is sent.
2. PostgreSQL row-level security on every business table compares `tenant_id` with that setting.
   Without it, queries see zero rows and writes are rejected (see app/shared/db/rls.py).

`SET LOCAL` matters with PgBouncer in transaction mode: the setting dies with the transaction, so
it can never leak to the next client that gets the same server connection.

PgBouncer + asyncpg (transaction pooling): asyncpg prepares every statement server-side and caches
it per connection, but in transaction mode consecutive transactions may run on different server
connections, which breaks with "prepared statement ... does not exist / already exists". We
disable asyncpg's statement cache and SQLAlchemy's prepared-statement cache, and give every
statement SQLAlchemy still prepares a unique name, as the SQLAlchemy asyncpg/PgBouncer guidance
recommends. This works with any transaction-mode pooler and PgBouncer version a customer runs
on-prem; the cost is one extra parse per statement. See docs/architecture/tenancy.md.
"""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, SessionTransaction
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.core.errors import ServiceUnavailable
from app.core.logging import get_logger
from app.core.tenancy import TenantContext, resolve_tenant

TENANT_SETTING = "app.tenant_id"
USER_SETTING = "app.user_id"
SESSION_TENANT_KEY = "supportx.tenant"
SESSION_PLATFORM_KEY = "supportx.platform"
AFTER_COMMIT_KEY = "supportx.after_commit"
# The request's open unit of work, so per-request helpers (the authorization subject) reuse its
# connection instead of taking a second one: N concurrent requests each holding one connection
# and waiting for another would exhaust a small pool (PgBouncer query_wait_timeout).
REQUEST_SESSION_STATE = "tenant_session"

log = get_logger(__name__)

# set_config(..., true) is SET LOCAL with bind parameters (SET itself cannot take parameters).
_SET_CONTEXT = text(
    "SELECT set_config('app.tenant_id', :tenant_id, true), "
    "set_config('app.user_id', :user_id, true)"
)


class TenantContextMissingError(RuntimeError):
    """A tenant session tried to run SQL without a tenant. Always a programming error."""


def to_async_url(url: str) -> str:
    """`postgresql://...` (as configured) → `postgresql+asyncpg://...` (SQLAlchemy dialect)."""
    for prefix in ("postgresql+asyncpg://", "postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+asyncpg://" + url[len(prefix) :]
    msg = "database URL must start with postgresql://"
    raise ValueError(msg)


def _unique_statement_name() -> str:
    return f"__supportx_{uuid.uuid4().hex}__"


def pgbouncer_safe_connect_args(application_name: str) -> dict[str, Any]:
    """Connect arguments for asyncpg that are safe behind a transaction-mode pooler."""
    return {
        "statement_cache_size": 0,  # asyncpg: no named statement cache per connection
        "prepared_statement_cache_size": 0,  # SQLAlchemy dialect: no prepared statement cache
        "prepared_statement_name_func": _unique_statement_name,  # no name clashes across clients
        "server_settings": {"application_name": application_name},
    }


def create_engine(  # noqa: PLR0913 - keyword-only pool settings, all optional
    url: str,
    *,
    application_name: str,
    pool_size: int = 10,
    max_overflow: int = 10,
    pool_timeout: float = 10.0,
    use_null_pool: bool = False,
) -> AsyncEngine:
    """Async engine for the application role. `use_null_pool` is for tests and one-shot tools."""
    pool_args: dict[str, Any] = (
        {"poolclass": NullPool}
        if use_null_pool
        else {
            "pool_size": pool_size,
            "max_overflow": max_overflow,
            "pool_timeout": pool_timeout,
            "pool_pre_ping": True,
        }
    )
    return create_async_engine(
        to_async_url(url),
        connect_args=pgbouncer_safe_connect_args(application_name),
        **pool_args,
    )


class TenantAwareSession(Session):
    """Sync session class behind every AsyncSession we create; see `_apply_context`."""


@event.listens_for(TenantAwareSession, "after_begin")
def _apply_context(
    session: Session, _transaction: SessionTransaction, connection: Connection
) -> None:
    """Write the tenant into the transaction before the first statement runs."""
    if session.info.get(SESSION_PLATFORM_KEY):
        return
    context = session.info.get(SESSION_TENANT_KEY)
    if not isinstance(context, TenantContext):
        msg = "tenant session used without a TenantContext; use Database.tenant_session()"
        raise TenantContextMissingError(msg)
    connection.execute(
        _SET_CONTEXT,
        {
            "tenant_id": str(context.tenant_id),
            "user_id": str(context.user_id) if context.user_id else "",
        },
    )


class Database:
    """Engine plus session factories for one process."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self._sessions = async_sessionmaker(
            engine, expire_on_commit=False, sync_session_class=TenantAwareSession
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> "Database | None":
        """The application database, or None when SUPPORTX_DATABASE_URL is not configured."""
        if settings.database_url is None:
            return None
        return cls(
            create_engine(
                settings.database_url.get_secret_value(),
                application_name=settings.service_name,
                pool_size=settings.db_pool_size,
                max_overflow=settings.db_max_overflow,
                pool_timeout=settings.db_pool_timeout_seconds,
            )
        )

    @asynccontextmanager
    async def tenant_session(self, context: TenantContext) -> AsyncIterator[AsyncSession]:
        """One unit of work for one tenant: commits on success, rolls back on any exception."""
        async with self._sessions(info={SESSION_TENANT_KEY: context}) as session, session.begin():
            yield session

    @asynccontextmanager
    async def platform_session(self) -> AsyncIterator[AsyncSession]:
        """A session with no tenant. RLS still applies: business tables return no rows."""
        async with self._sessions(info={SESSION_PLATFORM_KEY: True}) as session, session.begin():
            yield session

    def session_without_context(self) -> AsyncSession:
        """A raw tenant session with no context; any SQL on it raises. For tests of the guard."""
        return self._sessions()

    async def dispose(self) -> None:
        """Close all pooled connections."""
        await self.engine.dispose()


def get_database(request: Request) -> Database:
    """The process database; 503 if the API runs without SUPPORTX_DATABASE_URL."""
    database: Database | None = getattr(request.app.state, "db", None)
    if database is None:
        raise ServiceUnavailable(code="database_not_configured")
    return database


async def tenant_unit_of_work(
    request: Request,
    database: Annotated[Database, Depends(get_database)],
    tenant: Annotated[TenantContext, Depends(resolve_tenant)],
) -> AsyncIterator[AsyncSession]:
    """Provide one transaction per request.

    Committed after the endpoint returns and before the response is sent; rolled back if the
    endpoint (or the commit) raises.
    """
    async with database.tenant_session(tenant) as session:
        setattr(request.state, REQUEST_SESSION_STATE, session)
        try:
            yield session
        finally:
            setattr(request.state, REQUEST_SESSION_STATE, None)
    # Committed. Run what must only happen for committed data (cache invalidation, WP-016).
    for callback in session.info.get(AFTER_COMMIT_KEY, ()):
        try:
            await callback()
        except Exception:
            log.warning("after_commit_failed", exc_info=True)


def after_commit(session: AsyncSession, callback: Callable[[], Awaitable[None]]) -> None:
    """Run `callback` once this request's transaction has committed (never if it rolls back).

    Only for best-effort side effects with a reliable backstop: for anything that must happen,
    write an event to the outbox instead (CLAUDE.md rule b).
    """
    session.info.setdefault(AFTER_COMMIT_KEY, []).append(callback)


# scope="function": the commit happens before the response is sent, so a failed commit becomes
# an error response instead of a 200 for data that was never saved.
TenantSession = Annotated[AsyncSession, Depends(tenant_unit_of_work, scope="function")]
