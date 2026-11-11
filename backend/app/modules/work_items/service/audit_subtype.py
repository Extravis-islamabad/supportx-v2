"""Which kind of work item a save was, for the audit log's lifecycle entry (WP-064, ADR-045).

Every work-item save writes history as record type `work_item` (followers.RECORD_TYPE), so the
audit sink cannot tell an incident from a problem, and audit may not read this module's tables
(rule e). This module registers one resolver with app/shared/history instead, so no call site
passes a subtype and new ones need nothing (lane A, 2026-11-10).

Only `work_item` is resolved. Other record types this module writes (`change_board`,
`work_item_view`, `work_item_reply_template`, settings) are their own types and need none.

It also tells the sink a status change's categories (`status_category`), from the types' static
models: the staged types' codes carry their stage (closure_closed ...), so the audit log decides
"resolved", "closed" or "reopened" by category, never by code (lane A, 2026-11-10). That change
is added to the sink's copy only, never to history (app/shared/history annotators).

And whose personal data a work item holds (WP-064 S2, ADR-046): its requester and the person it
was raised for. The audit sink salts the fingerprint of free-text values with their salts, so
erasing one of them crypto-shreds those values in the chain.
"""

import uuid
from collections.abc import Mapping

from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.util import identity_key

from app.modules.work_items.domain.types import TYPES, WorkItemTypeCode
from app.modules.work_items.infra.models import WorkItem
from app.modules.work_items.service import followers
from app.shared.history import (
    Change,
    register_change_annotator,
    register_subject_resolver,
    register_subtype_resolver,
)

CATEGORY_FIELD = "status_category"


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


SUBJECT_FIELDS = ("requester_id", "on_behalf_of_id")


async def work_item_subjects(
    session: AsyncSession, record_id: uuid.UUID
) -> Mapping[str, uuid.UUID | None]:
    """The record's requester and on-behalf person now; empty when the row is not visible.

    From the session's copy when it is loaded and current (the save just flushed it), else one
    query in the same tenant session (RLS applies). Never raises for a save.
    """
    found = session.identity_map.get(identity_key(WorkItem, record_id))
    if isinstance(found, WorkItem):
        state = inspect(found)
        if not state.expired and all(name in state.dict for name in SUBJECT_FIELDS):
            return {name: state.dict[name] for name in SUBJECT_FIELDS}
    row = (
        await session.execute(
            select(WorkItem.requester_id, WorkItem.on_behalf_of_id).where(WorkItem.id == record_id)
        )
    ).one_or_none()
    if row is None:
        return {}
    return {"requester_id": row.requester_id, "on_behalf_of_id": row.on_behalf_of_id}


def status_category(type_code: str | None, status_code: object) -> str | None:
    """The category (`open`, `paused`, `resolved`, `closed`, `canceled`) of a type's status code.

    From the type's static model, no query. None for an unknown type or code. Tenants change a
    status's label and colour, never its code or category (D-056).
    """
    try:
        wtype = TYPES.get(WorkItemTypeCode(type_code)) if type_code else None
    except ValueError:
        return None
    if wtype is None:
        return None
    found = next((s for s in wtype.statuses if s.code == status_code), None)
    return found.category.value if found is not None else None


def with_status_category(subtype: str | None, changes: tuple[Change, ...]) -> tuple[Change, ...]:
    """A status change's old and new category, for the audit sink only."""
    status = next((c for c in changes if c.field == "status"), None)
    if status is None:
        return ()
    old, new = status_category(subtype, status.old), status_category(subtype, status.new)
    return () if new is None else (Change(CATEGORY_FIELD, old, new),)


def register() -> None:
    """At import (the consumers worker loads modules without their startup hooks)."""
    register_subtype_resolver(followers.RECORD_TYPE, work_item_subtype)
    register_change_annotator(followers.RECORD_TYPE, with_status_category)
    register_subject_resolver(followers.RECORD_TYPE, work_item_subjects)
