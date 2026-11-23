"""Who holds a record's named roles now (QA-2026-11-11 F-02).

Most roles are held through `work_item_role_holders`. A few are the record's own fields: a
change's requester and owner are its requester and technician (domain/changes.py). Those are
read from the record, so the roles tab, approval levels and stage rules naming them all agree
with the record's header.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.work_items.domain.types import TYPES, WorkItemTypeCode
from app.modules.work_items.infra.models import WorkItem, WorkItemRoleHolder

Holders = dict[str, tuple[list[uuid.UUID], list[uuid.UUID]]]


async def role_holders(
    session: AsyncSession, record: WorkItem, roles: Sequence[str] | None = None
) -> Holders:
    """Role -> (people, groups), in the order given; `roles` None: every role."""
    query = (
        select(WorkItemRoleHolder)
        .where(WorkItemRoleHolder.work_item_id == record.id)
        .order_by(WorkItemRoleHolder.created_at, WorkItemRoleHolder.id)
    )
    if roles is not None:
        query = query.where(WorkItemRoleHolder.role.in_(roles))
    held: Holders = {}
    for row in await session.scalars(query):
        users, groups = held.setdefault(row.role, ([], []))
        if row.user_id is not None:
            users.append(row.user_id)
        if row.group_id is not None:
            groups.append(row.group_id)
    for role, field_name in TYPES[WorkItemTypeCode(record.type)].record_roles.items():
        if roles is not None and role not in roles:
            continue
        person = getattr(record, field_name)
        held[role] = ([person] if person is not None else [], [])
    return held


__all__ = ["Holders", "role_holders"]
