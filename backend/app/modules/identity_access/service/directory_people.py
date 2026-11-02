"""People a directory keeps (WP-040 session 2; REQ-INT-063, REQ-INT-064).

The integrations module's sync calls these with values it has already mapped and checked. The
person record's own rules still apply (lengths, unique email and employee ID, a manager without
a loop): a value they refuse is the sync's to count, never written half.

- A directory person whose address matches an existing person is that person (adopted): no
  duplicate is ever made for someone who was invited or wrote in by e-mail first.
- From then on the person is marked with the directory (`directory_source`); the fields it owns
  are read-only on the people screens (`DIRECTORY_FIELDS`, "managed_by_directory").
- Leavers are deactivated, never deleted (their sessions end; their records keep them); a person
  the directory enables again is reactivated with what they held. The last active administrator
  is never deactivated by a sync: the run reports it instead.
"""

import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict
from app.modules.identity_access.domain.identity import UserType
from app.modules.identity_access.infra.models import User
from app.modules.identity_access.service import people

Directory = Literal["entra", "ldap"]


class LeaverOutcome(StrEnum):
    """What a sync did with a leaver."""

    LEFT = "left"
    ALREADY_DISABLED = "already_disabled"
    LAST_ADMIN_KEPT = "last_admin_kept"  # never the last active administrator (counted, shown)


@dataclass(frozen=True)
class SyncedPerson:
    """The person a directory person is, and what this sync did to them."""

    user_id: uuid.UUID
    created: bool
    changed: bool


async def _adoptable(session: AsyncSession, email: str) -> uuid.UUID | None:
    """Any person (active or not; never a service identity) with this address, any case."""
    found: uuid.UUID | None = await session.scalar(
        select(User.id).where(
            func.lower(User.email) == email.strip().lower(),
            User.user_type != UserType.SERVICE.value,
            User.deleted_at.is_(None),
        )
    )
    return found


async def sync_directory_person(
    session: AsyncSession,
    user_id: uuid.UUID | None,
    values: Mapping[str, Any],  # Any: person field values (text, UUIDs), checked by people
    *,
    directory: Directory,
) -> SyncedPerson:
    """Create, adopt or update a synced person; 422 (as the people screens) on a refused value."""
    created = False
    changes: dict[str, Any] = {}
    if user_id is None:
        email = values.get("email")
        user_id = await _adoptable(session, email) if isinstance(email, str) else None
    if user_id is None:
        person = await people.create_person(session, values, source="integration")
        created = True
    else:
        current = await people.get_person(session, user_id)
        changes = {k: v for k, v in values.items() if getattr(current, k) != v}
        person = current
        if changes:
            person = await people.update_person(
                session,
                user_id,
                expected_version=current.version,
                changes=changes,
                source="integration",
            )
    changed = created or bool(changes)
    if person.directory_source != directory:
        person.directory_source = directory  # bookkeeping, not a person field: no version bump
        await session.flush()
    return SyncedPerson(user_id=person.id, created=created, changed=changed)


async def directory_leaver(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    directory: Directory,
    end_sessions: Callable[[uuid.UUID], Awaitable[None]] | None,
) -> LeaverOutcome:
    """Deactivate a person the directory removed or disabled (REQ-INT-064); never deletes."""
    current = await people.get_person(session, user_id)
    if current.status == "disabled":
        return LeaverOutcome.ALREADY_DISABLED
    try:
        await people.deactivate(
            session,
            None,
            user_id,
            expected_version=current.version,
            end_sessions=end_sessions,
            directory=directory,
        )
    except Conflict as refused:
        if refused.code != "last_tenant_admin":
            raise
        return LeaverOutcome.LAST_ADMIN_KEPT
    return LeaverOutcome.LEFT


async def directory_returner(
    session: AsyncSession, user_id: uuid.UUID, *, directory: Directory
) -> bool:
    """Reactivate a person the directory enabled again, keeping what they held; True if so."""
    current = await people.get_person(session, user_id)
    if current.status == "active":
        return False
    held = await people.reactivation(session, user_id)
    await people.reactivate(
        session,
        user_id,
        expected_version=current.version,
        keep_role_ids=held.role_ids,
        keep_group_ids=held.group_ids,
        directory=directory,
    )
    return True
