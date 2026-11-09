"""Which kind of work item a save was, for the audit log's lifecycle entry (WP-064, ADR-045).

Every work-item save writes history as record type `work_item` (followers.RECORD_TYPE), so the
audit sink cannot tell an incident from a problem, and audit may not read this module's tables
(rule e). This module registers one resolver with app/shared/history instead, so no call site
passes a subtype and new ones need nothing (lane A, 2026-11-10).

Only `work_item` is resolved. Other record types this module writes (`change_board`,
`work_item_view`, `work_item_reply_template`, settings) are their own types and need none.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.util import identity_key

from app.modules.work_items.infra.models import WorkItem
from app.modules.work_items.service import followers
from app.shared.history import register_subtype_resolver


async def work_item_subtype(session: AsyncSession, record_id: uuid.UUID) -> str | None:
    """The record's type code (`incident`, `problem` ...), or None; never raises for a save.

    The save has just loaded or flushed the row, so it is normally in the session's identity
    map: looked up by its key, never by scanning. Otherwise one column is read in the same
    tenant session (RLS applies): another tenant's or a missing row gives None.
    """
    found = session.identity_map.get(identity_key(WorkItem, record_id))
    if isinstance(found, WorkItem):
        return found.type
    value = await session.scalar(select(WorkItem.type).where(WorkItem.id == record_id))
    return value if isinstance(value, str) else None


def register() -> None:
    """At import (the consumers worker loads modules without their startup hooks)."""
    register_subtype_resolver(followers.RECORD_TYPE, work_item_subtype)
