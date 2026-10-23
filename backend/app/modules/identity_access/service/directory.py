"""User directory: list, read and the SupportX-owned preferences (WP-008).

Identity fields (email, name, locale, type) belong to Keycloak and are refreshed on every login
(service/users.py). SupportX owns only what Keycloak does not know: a technician's reply
signature and the preferred time zone. Those are edited here, with optimistic concurrency, and
each change emits `identity_access.user.updated` in the same transaction (CLAUDE.md rules b, g).

Permissions (checked here, in the service, never in the router):
- list and read other users: technicians of the tenant;
- read yourself: anyone;
- change preferences: only your own.
"""

import uuid
from collections.abc import Mapping
from typing import Any
from zoneinfo import available_timezones

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict, FieldError, PermissionDenied, ValidationFailed
from app.core.tenancy import TenantContext
from app.modules.identity_access.domain.identity import UserType
from app.modules.identity_access.events import UserUpdated
from app.modules.identity_access.infra.models import User
from app.shared.api.filters import FieldType, FilterField, ResourceFields
from app.shared.api.listing import ListQuery, PageResult, paginate
from app.shared.db.repository import Repository
from app.shared.events import record_event

EDITABLE_FIELDS = frozenset({"signature", "time_zone"})
MAX_SIGNATURE_LENGTH = 2000

USER_FIELDS = ResourceFields(
    name="users",
    fields={
        "id": FilterField(User.id, FieldType.UUID),
        "email": FilterField(User.email, FieldType.STRING, sortable=True),
        "display_name": FilterField(User.display_name, FieldType.STRING, sortable=True),
        "user_type": FilterField(
            User.user_type, FieldType.ENUM, values=frozenset(t.value for t in UserType)
        ),
        "status": FilterField(
            User.status, FieldType.ENUM, values=frozenset({"active", "disabled"})
        ),
        "locale": FilterField(User.locale, FieldType.ENUM, values=frozenset({"en", "ar", "ur"})),
        "created_at": FilterField(User.created_at, FieldType.DATETIME, sortable=True, simple=False),
        "updated_at": FilterField(User.updated_at, FieldType.DATETIME, simple=False),
        "last_login_at": FilterField(
            User.last_login_at, FieldType.DATETIME, sortable=True, simple=False
        ),
    },
    id_column=User.id,
    default_sort=("display_name",),
)


class UserRepository(Repository[User]):
    """Users of the session's tenant."""

    model = User


def _context(session: AsyncSession) -> TenantContext:
    context = session.info.get(SESSION_TENANT_KEY)
    if not isinstance(context, TenantContext):  # pragma: no cover - TenantSession guarantees it
        raise TypeError
    return context


async def _caller(session: AsyncSession) -> User:
    """The calling user's own row in this tenant (403 if there is none, e.g. no session user)."""
    context = _context(session)
    caller = (
        await session.scalar(select(User).where(User.id == context.user_id))
        if context.user_id
        else None
    )
    if caller is None or caller.status != "active":
        raise PermissionDenied
    return caller


async def list_users(session: AsyncSession, query: ListQuery) -> PageResult[User]:
    """One page of users matching the query (technicians only)."""
    caller = await _caller(session)
    if caller.user_type != UserType.TECHNICIAN.value:
        raise PermissionDenied(code="technicians_only")
    return await paginate(session, select(User).where(User.deleted_at.is_(None)), query)


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> User:
    """A user of this tenant: yourself, or anyone if you are a technician (404 if absent)."""
    caller = await _caller(session)
    if user_id != caller.id and caller.user_type != UserType.TECHNICIAN.value:
        raise PermissionDenied(code="technicians_only")
    return await UserRepository(session).get(user_id)


def _validate(changes: Mapping[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    errors: list[FieldError] = []
    for name, value in changes.items():
        if name not in EDITABLE_FIELDS:
            errors.append(
                FieldError(
                    field=f"body.{name}", code="read_only", message_key="errors.field.read_only"
                )
            )
        elif name == "time_zone" and value is not None and value not in available_timezones():
            errors.append(
                FieldError(
                    field="body.time_zone",
                    code="invalid_choice",
                    message_key="errors.field.invalid_choice",
                )
            )
        elif name == "signature" and value is not None and len(value) > MAX_SIGNATURE_LENGTH:
            errors.append(
                FieldError(
                    field="body.signature",
                    code="value_too_long",
                    message_key="errors.field.value_too_long",
                    params={"max_length": MAX_SIGNATURE_LENGTH},
                )
            )
        else:
            clean[name] = value
    if errors:
        raise ValidationFailed(errors=errors)
    return clean


async def update_preferences(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    expected_version: int,
    changes: Mapping[str, Any],
) -> User:
    """Change your own signature/time zone if the record is still at `expected_version`."""
    caller = await _caller(session)
    if user_id != caller.id:
        raise PermissionDenied(code="own_profile_only")
    clean = _validate(changes)
    current = await UserRepository(session).get(user_id)
    changed = sorted(name for name, value in clean.items() if getattr(current, name) != value)
    if not changed:
        if current.version != expected_version:
            raise Conflict(
                code="version_conflict",
                params={"expected_version": expected_version, "current_version": current.version},
            )
        return current  # nothing to change: no new version, no event
    updated = await UserRepository(session).update(
        user_id, expected_version=expected_version, changes={n: clean[n] for n in changed}
    )
    await record_event(
        session,
        UserUpdated(user_id=user_id, changed_fields=changed),
        aggregate_id=user_id,
        aggregate_version=updated.version,
    )
    return updated
