"""User directory: list, read and the SupportX-owned preferences (WP-008).

Identity fields (email, name, locale, type) belong to Keycloak and are refreshed on every login
(service/users.py). SupportX owns only what Keycloak does not know: a technician's reply
signature and the preferred time zone. Those are edited here, with optimistic concurrency, and
each change emits `identity_access.user.updated` in the same transaction (CLAUDE.md rules b, g).

Permissions (WP-016 policy layer; the route checks the permission, this layer the record):
- list and read other users: `users.view`, filtered to the subject's scope;
- read yourself: any signed-in user;
- change preferences: `profile.edit`, own record only.
Field visibility: `last_login_at` only for subjects holding `users.manage`.
"""

import uuid
from collections.abc import Mapping
from typing import Any
from zoneinfo import available_timezones

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, FieldError, PermissionDenied, ValidationFailed
from app.modules.identity_access.domain.identity import UserType
from app.modules.identity_access.domain.policy import RecordFacts, Subject
from app.modules.identity_access.events import UserUpdated
from app.modules.identity_access.infra.models import User
from app.modules.identity_access.service.policy import (
    FieldRule,
    ResourceType,
    authorize,
    authorize_stored,
    require,
    scope_filter,
)
from app.modules.organization import users_in_groups, users_in_sites
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


def users_resource() -> ResourceType:
    """How the policy applies to user records (WP-016).

    own = the user themselves; site/group = users sharing one of the subject's sites/groups;
    the last sign-in time is only shown to subjects who manage users.
    """
    return ResourceType(
        name="users",
        fields=USER_FIELDS,
        owner_columns=(User.id,),
        site_scope=lambda ids: User.id.in_(users_in_sites(ids)),
        group_scope=lambda ids: User.id.in_(users_in_groups(ids)),
        field_rules={"last_login_at": FieldRule("users.manage")},
    )


USERS = users_resource()


async def list_users(session: AsyncSession, subject: Subject, query: ListQuery) -> PageResult[User]:
    """One page of the users the subject may see (users.view, scope-filtered)."""
    visible_rows = select(User).where(
        User.deleted_at.is_(None), scope_filter(subject, "users.view", USERS)
    )
    return await paginate(session, visible_rows, query)


async def get_user(session: AsyncSession, subject: Subject, user_id: uuid.UUID) -> User:
    """Yourself always; anyone else with users.view in scope (404 if absent)."""
    user = await UserRepository(session).get(user_id)
    if user_id != subject.user_id:
        require(
            await authorize_stored(session, subject, "users.view", USERS, User.id, user_id),
            "users.view",
        )
    return user


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
    subject: Subject,
    user_id: uuid.UUID,
    *,
    expected_version: int,
    changes: Mapping[str, Any],
) -> User:
    """Change your own signature/time zone if the record is still at `expected_version`."""
    if user_id != subject.user_id:
        raise PermissionDenied(code="own_profile_only")
    require(
        authorize(subject, "profile.edit", USERS, RecordFacts(owner_ids=frozenset({user_id}))),
        "profile.edit",
    )
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
