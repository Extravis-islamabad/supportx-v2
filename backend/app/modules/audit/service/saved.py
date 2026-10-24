"""Saved audit searches: a person's own named filters (REQ-AUD-007)."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound
from app.modules.audit.infra.models import AuditSavedSearch

MAX_PER_PERSON = 50


async def list_saved(session: AsyncSession, owner: uuid.UUID) -> list[AuditSavedSearch]:
    """The person's saved searches, by name."""
    return list(
        await session.scalars(
            select(AuditSavedSearch)
            .where(AuditSavedSearch.owner_id == owner)
            .order_by(AuditSavedSearch.name)
        )
    )


async def create_saved(
    session: AsyncSession, owner: uuid.UUID, name: str, query: dict[str, str]
) -> AuditSavedSearch:
    """Save one (409 beyond the per-person limit)."""
    count = await session.scalar(
        select(func.count()).select_from(AuditSavedSearch).where(AuditSavedSearch.owner_id == owner)
    )
    if (count or 0) >= MAX_PER_PERSON:
        raise Conflict(code="saved_search_limit", params={"max": MAX_PER_PERSON})
    context = session.info["supportx.tenant"]
    row = AuditSavedSearch(
        tenant_id=context.tenant_id, owner_id=owner, name=name.strip(), query=dict(query)
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def delete_saved(session: AsyncSession, owner: uuid.UUID, search_id: uuid.UUID) -> None:
    """Delete one of the person's own (404 for anyone else's)."""
    row = await session.scalar(
        select(AuditSavedSearch).where(
            AuditSavedSearch.id == search_id, AuditSavedSearch.owner_id == owner
        )
    )
    if row is None:
        raise NotFound(code="saved_search_not_found")
    await session.delete(row)
    await session.flush()
