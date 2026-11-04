"""The AI call log (REQ-AI-031): one row per call, the text cleared after the retention period.

Every call through the gateway is written here, refused and failed ones too: tenant, feature,
user, record, provider, model, the masked input, the output, tools, sources, latency, tokens,
cost and guardrail events. The person's choice (accepted, edited, discarded) is added later by
the feature. After the tenant's retention period (30 days unless changed) a daily job clears
the text and keeps the row, so usage and outcome reporting still work.
"""

import uuid
from datetime import timedelta
from typing import Literal

import structlog
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import Database
from app.core.errors import NotFound
from app.core.tenancy import TenantContext
from app.modules.ai.infra.models import AiCall, AiSettings
from app.modules.ai.service.settings import session_tenant
from app.modules.audit import WORKER, record
from app.modules.identity_access import Subject
from app.shared.clock import system_clock

log = structlog.get_logger(__name__)

Outcome = Literal["accepted", "edited", "discarded"]


async def record_call(session: AsyncSession, **fields: object) -> AiCall:
    """Write one call; returns it (its ID goes back to the feature for the outcome)."""
    call = AiCall(tenant_id=session_tenant(session), **fields)
    session.add(call)
    await session.flush()
    return call


async def set_outcome(
    session: AsyncSession, subject: Subject, call_id: uuid.UUID, outcome: Outcome
) -> AiCall:
    """What the person did with the answer. Only the person who made the call says so."""
    call = await session.get(AiCall, call_id)
    if call is None or call.user_id != subject.user_id:
        raise NotFound(code="ai_call_not_found")
    call.outcome = outcome
    await session.flush()
    return call


PURGE_BATCH = 1000  # rows per statement: each stays short, even after a long outage


async def purge_text(session: AsyncSession) -> int:
    """Clear the text of this tenant's calls older than its retention period; rows stay.

    In batches, so no single statement grows with the backlog. Every purge that clears
    anything is audited (D-131), with the count and the retention period applied.
    """
    days = await session.scalar(select(AiSettings.log_retention_days)) or 30
    now = system_clock.now()
    cleared = 0
    while True:
        batch = (
            select(AiCall.id)
            .where(AiCall.created_at < now - timedelta(days=days), AiCall.text_purged_at.is_(None))
            .limit(PURGE_BATCH)
        )
        result = await session.execute(
            update(AiCall)
            .where(AiCall.id.in_(batch))
            .values(masked_input=None, output=None, text_purged_at=now)
        )
        done = int(getattr(result, "rowcount", 0) or 0)
        cleared += done
        if done < PURGE_BATCH:
            break
    if cleared:
        await record(
            session,
            action_code="ai.calls_purged",
            facts=WORKER,
            object_type="ai_calls",
            details={"calls": cleared, "retention_days": days},
        )
    return cleared


async def purge_sweep(database: Database, settings: Settings) -> None:
    """Daily, in every tenant: the retention period of AI call text (a privacy job)."""
    del settings
    async with database.platform_session() as platform:
        tenants = list((await platform.scalars(text("SELECT audit_tenant_ids()"))).all())
    for tenant in tenants:
        async with database.tenant_session(TenantContext(tenant)) as session:
            cleared = await purge_text(session)
        if cleared:
            log.info("ai_call_text_purged", tenant_id=str(tenant), calls=cleared)
