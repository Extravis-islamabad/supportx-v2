"""Just-in-time user provisioning (WP-006) and the session events (WP-007).

On the first sign-in the person's row in the chosen tenant is created from the identity provider
(name, email, locale, type), or a person added by an admin or an import is linked by email. After
that SupportX owns the record and a sign-in records only the time (D-092). The tenant must exist
and be active; the person must be active and allowed to sign in.

Events go through the outbox in the same transaction as the user row (CLAUDE.md rule b):
`user.provisioned` (new row), `user.updated` (a pre-created person linked), and
`user.logged_in` or `session.tenant_switched`. A refused login (disabled user) rolls everything
back, so it records neither the sign-in time nor an event.
"""

import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import Boolean, func, literal_column, select, update
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
from app.modules.identity_access.service.identity_settings import get_identity_settings
from app.modules.identity_access.service.invitations import mark_accepted
from app.modules.identity_access.service.roles import map_identity_roles
from app.modules.licensing import LimitKey, hold_limit, reserve_capacity
from app.modules.organization import TenantStatus, find_department, find_site, get_current_tenant
from app.shared.events import Actor, DomainEvent, record_event
from app.shared.ids import new_id

SessionReason = Literal["login", "tenant_switch"]
# What the identity provider said about a person (WP-039: department and site from single
# sign-on, by name or code), read only when the person is created.
Directory = Callable[[str], Awaitable[Mapping[str, str | None]]]


async def _place(
    session: AsyncSession, user_id: uuid.UUID, found: Mapping[str, str | None]
) -> None:
    """Department and site from the provider on first sign-in (REQ-SEC-007 AC3, D-089 D6).

    Matched to the tenant's active departments (code or name) and sites (name); an unknown
    value is left out, never created.
    """
    department = found.get("department")
    site = found.get("site")
    values: dict[str, uuid.UUID] = {}
    if department and (department_id := await find_department(session, department)):
        values["department_id"] = department_id
    if site and (site_id := await find_site(session, site)):
        values["site_id"] = site_id
    if values:
        await session.execute(update(User).where(User.id == user_id).values(**values))


@dataclass(frozen=True)
class ProvisionedUser:
    """The user's row in one tenant, plus that tenant's display name."""

    user_id: uuid.UUID
    tenant_id: uuid.UUID
    tenant_name: str
    # The tenant's session limits for the app signed in to (REQ-SEC-029), in seconds.
    session_idle_seconds: int
    session_absolute_seconds: int


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


def _names(identity: Identity) -> tuple[str, str | None]:
    """First and last name for a person created by their first sign-in (the IdP's display name)."""
    parts = identity.display_name.split(maxsplit=1)
    if not parts:
        return (identity.email.split("@", 1)[0] or identity.subject)[:100], None
    return parts[0][:100], (parts[1][:100] if len(parts) > 1 else None)


async def _find_person(session: AsyncSession, identity: Identity) -> tuple[User | None, bool]:
    """The person this sign-in belongs to (locked), and whether it was linked just now.

    By Keycloak subject; else a person added by an admin or an import (no subject yet) with the
    same email address, which this sign-in links (D-092).
    """
    person = await session.scalar(
        select(User).where(User.external_subject == identity.subject).with_for_update()
    )
    if person is not None:
        return person, False
    person = await session.scalar(
        select(User)
        .where(
            User.external_subject.is_(None),
            func.lower(User.email) == identity.email.strip().lower(),
            User.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if person is None:
        return None, False
    person.external_subject = identity.subject
    return person, True


async def _create_person(
    session: AsyncSession, tenant_id: uuid.UUID, identity: Identity, now: datetime
) -> tuple[uuid.UUID, int, bool]:
    """Insert the person of a first sign-in: (id, version, inserted).

    A parallel first sign-in of the same person finds the other one's row (ON CONFLICT).
    """
    if identity.user_type is UserType.TECHNICIAN:
        # A new technician seat. Existing technicians are never re-checked, so lowering the
        # limit locks nobody out (§13.6).
        await reserve_capacity(session, LimitKey.TECHNICIANS, code="technician_limit_reached")
    first_name, last_name = _names(identity)
    statement = (
        insert(User)
        .values(
            id=new_id(),
            tenant_id=tenant_id,
            external_subject=identity.subject,
            email=identity.email,
            display_name=identity.display_name or first_name,
            first_name=first_name,
            last_name=last_name,
            locale=identity.locale,
            user_type=identity.user_type.value,
            last_login_at=now,
            created_at=now,
            updated_at=now,
            version=1,
        )
        .on_conflict_do_update(
            index_elements=[User.tenant_id, User.external_subject],
            set_={"last_login_at": now},
        )
        .returning(User.id, User.version, literal_column("xmax = 0", Boolean))
    )
    try:
        user_id, version, inserted = (await session.execute(statement)).one()
    except IntegrityError as exc:
        # Another person in this tenant already uses the email address.
        raise Conflict(code="user_email_conflict") from exc
    return user_id, version, inserted


async def _sign_in(  # noqa: PLR0913 - the sign-in and two keyword-only tenant policies
    session: AsyncSession,
    tenant_id: uuid.UUID,
    identity: Identity,
    now: datetime,
    *,
    create_people: bool,
    directory: Directory | None = None,
) -> tuple[uuid.UUID, int, list[DomainEvent]]:
    """The signed-in person (found, linked or created): id, version and the events so far.

    `create_people` off (REQ-SEC-013 AC3): someone the tenant does not know yet is refused.
    """
    if identity.user_type is UserType.TECHNICIAN:
        # Taken first, so parallel first sign-ins of technicians claim seats one at a time.
        await hold_limit(session, LimitKey.TECHNICIANS)
    person, linked = await _find_person(session, identity)
    if person is None and not create_people:
        raise PermissionDenied(code="sign_in_unknown_person")
    if person is None:
        user_id, version, inserted = await _create_person(session, tenant_id, identity, now)
        if inserted and directory is not None:
            await _place(session, user_id, await directory(identity.subject))
        if inserted:
            created = UserProvisioned(
                user_id=user_id, user_type=identity.user_type.value, locale=identity.locale
            )
            return user_id, version, [created]
        person = await session.get(User, user_id)  # a parallel first sign-in created it
        if person is None:
            raise NotFound
    # The refusals roll back the sign-in time and the link: no events.
    if person.status != "active":
        raise PermissionDenied(code="user_disabled")
    if not person.can_sign_in:
        raise PermissionDenied(code="sign_in_not_allowed")
    person.last_login_at = now
    await session.flush()
    events: list[DomainEvent] = []
    if linked:
        events.append(UserUpdated(user_id=person.id, changed_fields=["sign_in_linked"]))
        # An invited person's first sign-in accepts the invitation (REQ-SEC-020).
        await mark_accepted(session, person.id, now)
    return person.id, person.version, events


async def provision_user(  # noqa: PLR0913 - keyword-only event context; one login flow
    database: Database,
    tenant_id: uuid.UUID,
    identity: Identity,
    now: datetime,
    *,
    client: ClientApp,
    reason: SessionReason,
    on_roles_mapped: Callable[[uuid.UUID], Awaitable[None]] | None = None,
    directory: Directory | None = None,
) -> ProvisionedUser:
    """Find, link or create the person in `tenant_id`; refuses unknown, suspended or disabled.

    Once a person exists SupportX owns the record (D-092): a sign-in records only the time, so
    edits made in SupportX (name, email, type) are never overwritten by Keycloak.
    """
    async with database.tenant_session(TenantContext(tenant_id)) as session:
        try:
            tenant = await get_current_tenant(session)
        except NotFound as exc:
            raise PermissionDenied(code="tenant_not_provisioned") from exc
        if tenant.status is not TenantStatus.ACTIVE:
            raise PermissionDenied(code="tenant_suspended")
        settings = await get_identity_settings(session)
        user_id, version, events = await _sign_in(
            session,
            tenant_id,
            identity,
            now,
            create_people=settings.create_people_on_sign_in,
            directory=directory,
        )
        actor = Actor.user(user_id)
        if reason == "login":
            events.append(UserLoggedIn(user_id=user_id, client=client))
        else:
            events.append(SessionTenantSwitched(user_id=user_id, client=client))
        for event in events:
            await record_event(
                session, event, aggregate_id=user_id, aggregate_version=version, actor=actor
            )
        # First login since WP-016: Keycloak roles become SupportX role assignments, once (D-029).
        mapped = await map_identity_roles(session, user_id, identity.roles, now)
    if mapped and on_roles_mapped is not None:
        # Committed: drop any compiled permissions cached from before (the events do it too,
        # but the browser asks for /auth/me immediately after this login).
        await on_roles_mapped(tenant_id)
    idle, absolute = settings.session_limits(client)
    return ProvisionedUser(
        user_id=user_id,
        tenant_id=tenant_id,
        tenant_name=tenant.name,
        session_idle_seconds=idle,
        session_absolute_seconds=absolute,
    )


async def record_logout(
    database: Database, tenant_id: uuid.UUID, user_id: uuid.UUID, client: ClientApp
) -> None:
    """`user.logged_out` (the session itself lives in Valkey; this is its only database trace)."""
    async with database.tenant_session(TenantContext(tenant_id, user_id)) as session:
        await record_event(
            session, UserLoggedOut(user_id=user_id, client=client), aggregate_id=user_id
        )
