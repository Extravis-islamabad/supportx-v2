"""The vendor support schedule (WP-057 S4c-1, D-173): every 30 seconds, every tenant.

1. Grants whose time is up end (`support_grants.end_grant`), each in its own transaction with the
   tenant set (0023: business tables force RLS); then their sessions and Keycloak account go.
2. Ended grants whose account is not confirmed gone are tried again, at most every 5 minutes
   (`removal_pending`); only a confirmed delete or 404 records the removal (lane B).
3. A removal stuck over 24 hours is told to the tenant admins once per grant (`mark_alerted`,
   the `account_removal_stuck` event); the security overview counts them.

Each tenant's pass sees only that tenant's grants (its own session, RLS), so one tenant's pass
never touches another's (lane B's test). Every step is idempotent: an admin's revoke racing the
schedule ends a grant once, and a delete racing a retry is fine as 404 counts as removed.
"""

import uuid
from collections.abc import Callable

from sqlalchemy import text

from app.core.config import Settings
from app.core.database import Database
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.identity_access.domain import support_grants as rules
from app.modules.identity_access.events import SupportGrantChanged
from app.modules.identity_access.infra.keycloak_admin import IdentityAdmin, KeycloakAdmin
from app.modules.identity_access.infra.models import SupportGrant
from app.modules.identity_access.service import support_grants as grants
from app.modules.identity_access.service.worker_sessions import (
    TenantSessionEnder,
    worker_session_ender,
)
from app.shared.clock import system_clock
from app.shared.events import record_event

log = get_logger(__name__)

EVERY_SECONDS = 30  # D-173: a grant ends within 30 seconds of its time

# Swapped in tests for fakes (as erasure_job.py).
admin_factory: Callable[[Settings], KeycloakAdmin | None] = KeycloakAdmin.from_settings
ender_factory: Callable[[Settings], TenantSessionEnder | None] = worker_session_ender


async def run_tenant(
    database: Database,
    tenant: uuid.UUID,
    *,
    admin: IdentityAdmin | None,
    end_sessions: TenantSessionEnder | None,
) -> None:
    """One tenant's pass: end what is due, retry removals, tell stuck ones once."""
    now = system_clock.now()
    context = TenantContext(tenant)
    async with database.tenant_session(context) as session:
        due = await grants.due(session, now)
        pending = await grants.removal_pending(session, now)
        stuck = await grants.stuck_removals(session, now)
    ended: list[grants.Ended] = []
    for grant_id in due:
        async with database.tenant_session(context) as session:
            done = await grants.end_grant(
                session, grant_id, tenant_id=tenant, revoked_by=None, now=now, source="system"
            )
        if done is not None:
            ended.append(done)
    for item in [*ended, *pending]:
        error = await grants.finish_end(item, end_sessions=end_sessions, admin=admin)
        async with database.tenant_session(context) as session:
            await grants.record_removal(session, item.grant_id, error=error, now=now)
        if error is not None:
            log.warning("support_grant_removal_failed", grant_id=str(item.grant_id), error=error)
    for grant_id in stuck:
        async with database.tenant_session(context) as session:
            if not await grants.mark_alerted(session, grant_id, now):
                continue  # told already: once per grant, never per retry
            row = await session.get(SupportGrant, grant_id)
            if row is None:
                continue
            await record_event(
                session,
                SupportGrantChanged(
                    grant_id=row.id,
                    change="account_removal_stuck",
                    access=rules.Access(row.access).value,
                    ends_at=row.ends_at,
                ),
                aggregate_id=row.id,
                aggregate_version=row.version,
            )


async def support_grant_schedule(database: Database, settings: Settings) -> None:
    """Every tenant, each in its own sessions (RLS)."""
    async with database.platform_session() as platform:
        tenants = list((await platform.scalars(text("SELECT audit_tenant_ids()"))).all())
    if not tenants:
        return
    admin = admin_factory(settings)
    end_sessions = ender_factory(settings)
    try:
        for tenant in tenants:
            await run_tenant(database, tenant, admin=admin, end_sessions=end_sessions)
    finally:
        if admin is not None:
            await admin.close()
