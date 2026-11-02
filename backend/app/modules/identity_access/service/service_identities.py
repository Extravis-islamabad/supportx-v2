"""Service identities: each connector instance acts in its own name (WP-040, REQ-INT-012).

A service identity is a user row of type `service`:
- it never signs in: no Keycloak account, no address to link one (a database check), no
  invitation;
- it never takes a seat (the technician count is technicians only);
- it is not a person: people lists, search, pickers and permission holders leave it out, and the
  people screens and imports cannot make, change or retype one;
- it holds only the roles given to it (none by default), so its scope is its own;
- what it changes carries `source = integration` in history (the caller passes it).

Only the integrations module calls this, when it creates, pauses or removes a connector.
"""

import uuid
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import access_changed
from app.modules.identity_access.domain.identity import UserType
from app.modules.identity_access.events import UserCreatedV3, UserStatusChanged
from app.modules.identity_access.infra.models import User
from app.modules.identity_access.service.directory import USER_RECORD_TYPE, UserRepository
from app.shared.events import record_event
from app.shared.history import Change, record_changes

NAME_MAX = 100


async def create_service_identity(session: AsyncSession, *, name: str) -> uuid.UUID:
    """A new, active service identity named after its connector (shown in history)."""
    shown = name.strip()[:NAME_MAX] or "integration"
    identity = await UserRepository(session).add(
        User(
            external_subject=None,
            email=None,
            display_name=shown,
            first_name=shown,
            user_type=UserType.SERVICE.value,
            can_sign_in=False,
            # Its roles are SupportX's alone (none until given): Keycloak's are never mapped.
            roles_mapped_at=datetime.now(UTC),
        )
    )
    await record_changes(
        session,
        record_type=USER_RECORD_TYPE,
        record_id=identity.id,
        version=identity.version,
        kind="created",
        changes=[],
        source="integration",
    )
    await record_event(
        session,
        UserCreatedV3(user_id=identity.id, user_type="service", source="integration"),
        aggregate_id=identity.id,
        aggregate_version=identity.version,
    )
    return identity.id


async def set_service_identity_active(
    session: AsyncSession, identity_id: uuid.UUID, *, active: bool
) -> None:
    """Pause or resume what the identity may do (its connector was removed or restored).

    Only service identities: a person is changed through the people screens.
    """
    identity = await UserRepository(session).get(identity_id)
    if identity.user_type != UserType.SERVICE.value:
        msg = "not a service identity"  # a programming error, never user input
        raise ValueError(msg)
    status: Literal["active", "disabled"] = "active" if active else "disabled"
    if identity.status == status:
        return
    before = identity.status
    identity = await UserRepository(session).update(
        identity_id, expected_version=identity.version, changes={"status": status}
    )
    await record_changes(
        session,
        record_type=USER_RECORD_TYPE,
        record_id=identity.id,
        version=identity.version,
        kind="status",
        changes=[Change("status", before, status)],
        source="integration",
    )
    await record_event(
        session,
        UserStatusChanged(user_id=identity.id, status=status),
        aggregate_id=identity.id,
        aggregate_version=identity.version,
    )
    access_changed(session)
