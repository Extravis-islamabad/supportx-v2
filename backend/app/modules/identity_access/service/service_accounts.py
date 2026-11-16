"""Service accounts an admin makes and answers for (WP-057 S4a, REQ-SEC-036).

A service account is a service identity (no sign-in, no seat, never in people lists) with an
owner (an active person of the tenant) and a description of what it is for. API clients act as
it through its keys, so what it does names it, never the admin who made the key (AC2).

- Connector and workflow identities (WP-040, WP-048b) are listed too, read-only here: their own
  screens manage them, and they have no owner.
- When an owner is deactivated, their accounts are flagged `needs_new_owner` (REQ-ADM-011 AC3)
  and the key managers are told; the accounts keep working until someone acts, as their keys
  belong to the account, not the owner.
- Roles go through the guarded service-role path (no tenant administration, nothing beyond the
  admin's own rights).
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import access_changed
from app.core.errors import FieldError, PermissionDenied, ValidationFailed
from app.modules.identity_access.domain.identity import UserType
from app.modules.identity_access.domain.policy import Subject
from app.modules.identity_access.events import UserCreatedV5, UserStatusChanged
from app.modules.identity_access.infra.models import ApiKey, User
from app.modules.identity_access.service.directory import USER_RECORD_TYPE, UserRepository
from app.modules.identity_access.service.roles import ServiceRole, roles_held
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes

MANAGE = "api_keys.manage"  # the keys' owners: the same right (identity_access permissions)
NAME_MAX = 100
DESCRIPTION_MAX = 500
SERVICE = UserType.SERVICE.value


@dataclass(frozen=True)
class ServiceAccountView:
    """A service identity as Admin > Service accounts shows it."""

    id: uuid.UUID
    name: str
    description: str | None
    owner_id: uuid.UUID | None
    owner_name: str | None
    managed_here: bool  # false: a connector's or workflow's identity, managed on its own screen
    needs_new_owner: bool
    active: bool
    keys: int  # active keys it owns
    roles: list[ServiceRole]
    version: int


def _require(subject: Subject) -> None:
    if not subject.holds(MANAGE):
        raise PermissionDenied(params={"permission": MANAGE, "reason": "no_permission"})


def _problem(*, field: str, code: str) -> ValidationFailed:
    return ValidationFailed(
        errors=[FieldError(field=f"body.{field}", code=code, message_key=f"errors.field.{code}")]
    )


async def _owner(session: AsyncSession, owner_id: uuid.UUID) -> User:
    """An active technician of the tenant: someone who can answer for the account."""
    owner = await session.get(User, owner_id)
    if (
        owner is None
        or owner.deleted_at is not None
        or owner.status != "active"
        or owner.user_type != UserType.TECHNICIAN.value
    ):
        raise _problem(field="owner_id", code="service_account_owner_invalid")
    return owner


def _text(value: str | None, limit: int, field: str, *, required: bool) -> str | None:
    cleaned = (value or "").strip()
    if required and not cleaned:
        raise _problem(field=field, code="required")
    del limit  # the request model caps the length (FastAPI answers 422 before this)
    return cleaned or None


async def _views(session: AsyncSession, rows: list[User]) -> list[ServiceAccountView]:
    owners = {
        o.id: o
        for o in await session.scalars(
            select(User).where(
                User.id.in_([r.service_owner_id for r in rows if r.service_owner_id])
            )
        )
    }
    now = datetime.now(UTC)
    counts = dict(
        (
            await session.execute(
                select(ApiKey.owner_id, func.count())
                .where(
                    ApiKey.owner_id.in_([r.id for r in rows]),
                    ApiKey.deleted_at.is_(None),
                    ApiKey.revoked_at.is_(None),
                    (ApiKey.expires_at.is_(None)) | (ApiKey.expires_at > now),
                )
                .group_by(ApiKey.owner_id)
            )
        ).all()
    )
    views: list[ServiceAccountView] = []
    for row in rows:
        owner = owners.get(row.service_owner_id) if row.service_owner_id else None
        views.append(
            ServiceAccountView(
                id=row.id,
                name=row.display_name,
                description=row.service_description,
                owner_id=row.service_owner_id,
                owner_name=owner.display_name if owner is not None else None,
                managed_here=row.service_owner_id is not None,
                needs_new_owner=row.service_owner_id is not None
                and (owner is None or owner.status != "active" or owner.deleted_at is not None),
                active=row.status == "active",
                keys=int(counts.get(row.id, 0)),
                roles=await roles_held(session, row.id),
                version=row.version,
            )
        )
    return views


async def list_service_accounts(
    session: AsyncSession, subject: Subject
) -> list[ServiceAccountView]:
    """Every service identity of the tenant, by name (api_keys.manage)."""
    _require(subject)
    rows = list(
        await session.scalars(
            select(User)
            .where(User.user_type == SERVICE, User.deleted_at.is_(None))
            .order_by(User.display_name, User.id)
        )
    )
    return await _views(session, rows)


async def service_account(
    session: AsyncSession, subject: Subject, account_id: uuid.UUID
) -> ServiceAccountView:
    """One service identity (404 for anything else)."""
    _require(subject)
    row = await UserRepository(session).get(account_id)
    if row.user_type != SERVICE:
        raise PermissionDenied(code="not_a_service_identity")
    return (await _views(session, [row]))[0]


async def create_service_account(  # noqa: PLR0913 - the account's parts, explicit
    session: AsyncSession,
    subject: Subject,
    *,
    name: str,
    description: str | None,
    owner_id: uuid.UUID,
    source: Source,
) -> ServiceAccountView:
    """A new active service account with no roles yet (give them next)."""
    _require(subject)
    shown = _text(name, NAME_MAX, "name", required=True)
    about = _text(description, DESCRIPTION_MAX, "description", required=False)
    await _owner(session, owner_id)
    row = await UserRepository(session).add(
        User(
            external_subject=None,
            email=None,
            display_name=shown,
            first_name=shown,
            user_type=SERVICE,
            can_sign_in=False,
            roles_mapped_at=datetime.now(UTC),  # SupportX's roles only, never Keycloak's
            service_owner_id=owner_id,
            service_description=about,
        )
    )
    await record_changes(
        session,
        record_type=USER_RECORD_TYPE,
        record_id=row.id,
        version=row.version,
        kind="created",
        changes=[Change("service_owner_id", None, str(owner_id))],
        source=source,
    )
    await record_event(
        session,
        UserCreatedV5(user_id=row.id, user_type="service", source="service_account"),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )
    return (await _views(session, [row]))[0]


async def update_service_account(  # noqa: PLR0913 - what changes and its context, explicit
    session: AsyncSession,
    subject: Subject,
    account_id: uuid.UUID,
    *,
    expected_version: int,
    values: Mapping[str, Any],
    source: Source,
) -> ServiceAccountView:
    """Its name, description, owner or active state; only accounts made here (If-Match)."""
    _require(subject)
    row = await UserRepository(session).get(account_id)
    if row.user_type != SERVICE or row.service_owner_id is None:
        raise PermissionDenied(code="service_identity_managed")
    changes: dict[str, Any] = {}
    if "name" in values:
        shown = _text(values["name"], NAME_MAX, "name", required=True)
        changes |= {"display_name": shown, "first_name": shown}
    if "description" in values:
        changes["service_description"] = _text(
            values["description"], DESCRIPTION_MAX, "description", required=False
        )
    if "owner_id" in values:
        await _owner(session, values["owner_id"])
        changes["service_owner_id"] = values["owner_id"]
    if "active" in values:
        changes["status"] = "active" if values["active"] else "disabled"
    changes = {k: v for k, v in changes.items() if getattr(row, k) != v}
    if not changes:
        return (await _views(session, [row]))[0]
    before = {k: getattr(row, k) for k in changes}
    updated = await UserRepository(session).update(
        account_id, expected_version=expected_version, changes=changes
    )
    await record_changes(
        session,
        record_type=USER_RECORD_TYPE,
        record_id=updated.id,
        version=updated.version,
        kind="updated",
        changes=[
            Change(k, str(before[k]) if before[k] is not None else None, str(v) if v else v)
            for k, v in changes.items()
            if k != "first_name"
        ],
        source=source,
    )
    if "status" in changes:
        access_changed(session)  # its keys stop or start at once (authenticate checks status)
        await record_event(
            session,
            UserStatusChanged(user_id=updated.id, status=changes["status"]),
            aggregate_id=updated.id,
            aggregate_version=updated.version,
        )
    return (await _views(session, [updated]))[0]


async def owned_by(session: AsyncSession, owner_id: uuid.UUID) -> list[User]:
    """The service accounts a person answers for (the hand-over, REQ-ADM-011)."""
    return list(
        await session.scalars(
            select(User).where(
                User.service_owner_id == owner_id,
                User.user_type == SERVICE,
                User.deleted_at.is_(None),
            )
        )
    )


__all__ = [
    "MANAGE",
    "ServiceAccountView",
    "create_service_account",
    "list_service_accounts",
    "owned_by",
    "service_account",
    "update_service_account",
]
