"""Just-in-time user provisioning (WP-006) and the session events (WP-007).

On every login the user's row in the chosen tenant is created or refreshed from the identity
provider (name, email, locale, type, last login). The tenant must exist and be active.

Events go through the outbox in the same transaction as the user row (CLAUDE.md rule b):
`user.provisioned` (new row), `user.updated` (synced profile fields changed), and
`user.logged_in` or `session.tenant_switched`. A refused login (disabled user) rolls everything
back, so it records neither the profile refresh nor an event.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import Boolean, Row, func, literal_column, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Database
from app.core.errors import Conflict, NotFound, PermissionDenied
from app.core.tenancy import TenantContext
from app.modules.identity_access.domain.identity import Identity, UserType
from app.modules.identity_access.events import (
    ClientApp,
    SessionTenantSwitched,
    UserLoggedIn,
    UserLoggedOut,
    UserProvisioned,
    UserUpdated,
)
from app.modules.identity_access.infra.models import User
from app.modules.licensing import LimitKey, hold_limit, reserve_capacity
from app.modules.organization import TenantStatus, get_current_tenant
from app.shared.events import Actor, DomainEvent, record_event
from app.shared.ids import new_id

SessionReason = Literal["login", "tenant_switch"]
# Fields refreshed from the identity provider; a change to any of them is a user.updated event.
SYNCED_FIELDS = ("email", "display_name", "locale", "user_type")


@dataclass(frozen=True)
class ProvisionedUser:
    """The user's row in one tenant, plus that tenant's display name."""

    user_id: uuid.UUID
    tenant_id: uuid.UUID
    tenant_name: str


async def count_technicians(session: AsyncSession) -> int:
    """Active technicians of the session's tenant: the `technicians` licence usage (WP-009)."""
    count = await session.scalar(
        select(func.count())
        .select_from(User)
        .where(
            User.user_type == UserType.TECHNICIAN.value,
            User.status == "active",
            User.deleted_at.is_(None),
        )
    )
    return int(count or 0)


async def tenant_name(database: Database, tenant_id: uuid.UUID) -> str | None:
    """Name of an active tenant, or None if it is unknown or suspended."""
    async with database.tenant_session(TenantContext(tenant_id)) as session:
        try:
            tenant = await get_current_tenant(session)
        except NotFound:
            return None
    return tenant.name if tenant.status is TenantStatus.ACTIVE else None


async def _existing_row(
    session: AsyncSession, tenant_id: uuid.UUID, identity: Identity
) -> Row[str, str, str, str] | None:
    """The user's current synced fields (locked), after claiming a technician seat if needed."""
    technician = identity.user_type is UserType.TECHNICIAN
    if technician:
        # Taken before reading the row, so a parallel first login of the same user sees the row
        # the other one created instead of competing for a second seat.
        await hold_limit(session, LimitKey.TECHNICIANS)
    before = (
        await session.execute(
            select(User.email, User.display_name, User.locale, User.user_type)
            .where(User.tenant_id == tenant_id, User.external_subject == identity.subject)
            .with_for_update()
        )
    ).one_or_none()
    if technician and (before is None or before.user_type != UserType.TECHNICIAN.value):
        # A new technician seat (new user, or a requester promoted in Keycloak). Existing
        # technicians are never re-checked, so lowering the limit locks nobody out (§13.6).
        await reserve_capacity(session, LimitKey.TECHNICIANS, code="technician_limit_reached")
    return before


async def provision_user(  # noqa: PLR0913 - keyword-only event context
    database: Database,
    tenant_id: uuid.UUID,
    identity: Identity,
    now: datetime,
    *,
    client: ClientApp,
    reason: SessionReason,
) -> ProvisionedUser:
    """Create or update the user's row in `tenant_id`; refuses unknown, suspended or disabled."""
    async with database.tenant_session(TenantContext(tenant_id)) as session:
        try:
            tenant = await get_current_tenant(session)
        except NotFound as exc:
            raise PermissionDenied(code="tenant_not_provisioned") from exc
        if tenant.status is not TenantStatus.ACTIVE:
            raise PermissionDenied(code="tenant_suspended")
        profile = {
            "email": identity.email,
            "display_name": identity.display_name,
            "locale": identity.locale,
            "user_type": identity.user_type.value,
            "last_login_at": now,
            "updated_at": now,
        }
        before = await _existing_row(session, tenant_id, identity)
        statement = (
            insert(User)
            .values(
                id=new_id(),
                tenant_id=tenant_id,
                external_subject=identity.subject,
                created_at=now,
                version=1,
                **profile,
            )
            .on_conflict_do_update(
                index_elements=[User.tenant_id, User.external_subject],
                set_={**profile, "version": User.version + 1},
            )
            # xmax = 0 only for a freshly inserted row: tells "created" from "updated".
            .returning(User.id, User.status, User.version, literal_column("xmax = 0", Boolean))
        )
        try:
            user_id, status, version, inserted = (await session.execute(statement)).one()
        except IntegrityError as exc:
            # Another account in this tenant already uses the email address.
            raise Conflict(code="user_email_conflict") from exc
        if status != "active":
            raise PermissionDenied(code="user_disabled")  # rolls back the refresh: no events
        actor = Actor.user(user_id)
        events: list[DomainEvent] = []
        if inserted:
            events.append(
                UserProvisioned(
                    user_id=user_id, user_type=identity.user_type.value, locale=identity.locale
                )
            )
        elif before is not None:
            changed = [name for name in SYNCED_FIELDS if getattr(before, name) != profile[name]]
            if changed:
                events.append(UserUpdated(user_id=user_id, changed_fields=changed))
        if reason == "login":
            events.append(UserLoggedIn(user_id=user_id, client=client))
        else:
            events.append(SessionTenantSwitched(user_id=user_id, client=client))
        for event in events:
            await record_event(
                session, event, aggregate_id=user_id, aggregate_version=version, actor=actor
            )
    return ProvisionedUser(user_id=user_id, tenant_id=tenant_id, tenant_name=tenant.name)


async def record_logout(
    database: Database, tenant_id: uuid.UUID, user_id: uuid.UUID, client: ClientApp
) -> None:
    """`user.logged_out` (the session itself lives in Valkey; this is its only database trace)."""
    async with database.tenant_session(TenantContext(tenant_id, user_id)) as session:
        await record_event(
            session, UserLoggedOut(user_id=user_id, client=client), aggregate_id=user_id
        )
