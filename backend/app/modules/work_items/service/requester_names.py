"""Whom a record's requester is named to in notices (WP-046b S2, lane B's open question).

After a merge, the duplicate's requester follows the survivor and gets its public replies and
notes by e-mail. Until the product owner decides, the coordinator's default holds: a reader on
the requester's side sees the survivor's requester by name only when they are in the same
department; anyone else reads "the requester". Staff with full access are unchanged.

This module is the one place the rule lives, so a different answer changes only `named_to`.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access import person_placement
from app.modules.work_items.infra.models import WorkItem
from app.shared.notifications.ports import LabelRef, RecordAccess, VariableValue

UNNAMED = LabelRef("notification_value.unnamed_requester")


async def named_to(
    session: AsyncSession, record: WorkItem, reader_id: uuid.UUID, access: RecordAccess
) -> bool:
    """Whether this reader may read the record's requester by name."""
    if access is RecordAccess.FULL or reader_id in (record.requester_id, record.on_behalf_of_id):
        return True
    theirs = (await person_placement(session, record.requester_id)).department_id
    mine = (await person_placement(session, reader_id)).department_id
    return theirs is not None and theirs == mine


async def requester_name_for(
    session: AsyncSession,
    record: WorkItem,
    reader_id: uuid.UUID,
    access: RecordAccess,
    name: VariableValue,
) -> VariableValue:
    """The requester's name as this reader reads it: the name, or "the requester"."""
    return name if await named_to(session, record, reader_id, access) else UNNAMED
