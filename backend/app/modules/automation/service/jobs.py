"""Housekeeping (WP-029): the automation run log is kept 30 days (Appendix A)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, text

from app.core.config import Settings
from app.core.database import Database
from app.core.tenancy import TenantContext
from app.modules.automation.infra.models import AutomationRun

KEEP = timedelta(days=30)


async def purge_runs(database: Database, settings: Settings) -> None:
    """Schedule: every tenant's run log older than 30 days."""
    del settings
    async with database.platform_session() as session:
        tenants = list((await session.scalars(text("SELECT audit_tenant_ids()"))).all())
    cutoff = datetime.now(UTC) - KEEP
    for tenant in tenants:
        async with database.tenant_session(TenantContext(tenant)) as session:
            await session.execute(delete(AutomationRun).where(AutomationRun.occurred_at < cutoff))
