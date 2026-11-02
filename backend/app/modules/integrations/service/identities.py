"""Which service identity a connector instance acts as (WP-040, REQ-INT-012).

One per instance, made with it; an instance from before WP-040 session 2 gets one at its next
run. Removing the instance disables its identity (never deleted: history keeps naming it), and
restoring it enables it again. The identity holds only the roles given to it.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.modules.identity_access import create_service_identity, set_service_identity_active
from app.modules.integrations.infra.models import ConnectorIdentity


async def identity_of(session: AsyncSession, kind: str, instance_id: uuid.UUID) -> uuid.UUID | None:
    """The instance's service identity, or None when it has none yet."""
    found: uuid.UUID | None = await session.scalar(
        select(ConnectorIdentity.user_id).where(
            ConnectorIdentity.kind == kind, ConnectorIdentity.instance_id == instance_id
        )
    )
    return found


async def ensure_identity(
    session: AsyncSession, kind: str, instance_id: uuid.UUID, *, name: str
) -> uuid.UUID:
    """The instance's service identity, made now when it has none (`name`: shown in history)."""
    # One maker per instance at a time (a create and a first run can overlap): the lock ends
    # with the transaction.
    await session.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(f"{kind}:{instance_id}", 0)))
    )
    found = await identity_of(session, kind, instance_id)
    if found is not None:
        return found
    user_id = await create_service_identity(session, name=name)
    session.add(
        ConnectorIdentity(
            tenant_id=session.info[SESSION_TENANT_KEY].tenant_id,
            kind=kind,
            instance_id=instance_id,
            user_id=user_id,
        )
    )
    await session.flush()
    return user_id


async def set_identity_active(
    session: AsyncSession, kind: str, instance_id: uuid.UUID, *, active: bool
) -> None:
    """Disable (removed) or enable (restored) the instance's identity, if it has one."""
    found = await identity_of(session, kind, instance_id)
    if found is not None:
        await set_service_identity_active(session, found, active=active)
