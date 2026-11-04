"""Who may have AI work on a record: asked of the module that owns it (REQ-AI-025, §11.2).

A call about a record (a summary of an incident, a draft for its reply) is checked again by the
gateway through the record's owning module, with the same rule its API uses. A module registers
its check at start-up; a record type with no check is refused (fail closed), so a new feature can
never reach a record its module has not vouched for.
"""

import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access import Subject

# (session, subject, record ID) → may this subject see the record?
RecordAccess = Callable[[AsyncSession, Subject, uuid.UUID], Awaitable[bool]]

_ACCESS: dict[str, RecordAccess] = {}


def register_record_access(record_type: str, check: RecordAccess) -> None:
    """The owning module's visibility rule for one record type (at its start-up)."""
    _ACCESS[record_type] = check


def unregister_record_access(record_type: str) -> None:
    """At shutdown (tests start the app more than once)."""
    _ACCESS.pop(record_type, None)


async def may_see(
    session: AsyncSession, subject: Subject, record_type: str, record_id: uuid.UUID
) -> bool:
    """Whether the subject may see the record; False when no module vouches for its type."""
    check = _ACCESS.get(record_type)
    return check is not None and await check(session, subject, record_id)
