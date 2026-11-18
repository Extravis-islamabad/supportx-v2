"""Vendor support grants (WP-057 S4c-1, REQ-SEC-045, D-173): reading, the opt-out and the end.

A tenant admin grants one named Extravis engineer temporary access; the grant makes a temporary
`vendor_support` account in the shared realm, at a plus-address of the engineer's own
(`domain.support_grants.account_email`). This part holds what does not depend on how the engineer
gets in (`delivery_for`, which waits for the product owner's item 14):

- the grants a tenant admin sees, newest first, with "waiting for the engineer" until the engineer
  completes Keycloak's required actions (lane B (12)): never "active" before;
- the "Never allow vendor support" setting (D-173 (9)); turning it on refuses while a grant is
  open, so an admin ends those first and sees which;
- the end of a grant (expiry, revoke): the grant and the local account change in one
  transaction; then, after the commit, every session ends (the session store's marker and
  Centrifugo, ADR-051) and the Keycloak account is disabled, then deleted (lane B (5)). The grant
  row and its audit stay; the account and its plus-address are gone.

Only tenant admins: grants are a tenant-admin decision (D-173 (1)), so `identity.manage` alone is
not enough.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict, NotFound, PermissionDenied
from app.core.logging import get_logger
from app.modules.identity_access.domain import support_grants as rules
from app.modules.identity_access.domain.permissions import TENANT_ADMIN
from app.modules.identity_access.domain.policy import Subject
from app.modules.identity_access.events import SupportGrantChanged, VendorSupportSettingChanged
from app.modules.identity_access.infra.keycloak_admin import (
    IdentityAdmin,
    IdentityAdminRefused,
    IdentityAdminUnavailable,
)
from app.modules.identity_access.infra.models import (
    IdentitySettings,
    Role,
    SupportGrant,
    User,
    UserRole,
)
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes

log = get_logger(__name__)

GRANT_RECORD_TYPE = "support_grant"

# `end(tenant_id, user_id)`: the session store's ended marker and the realtime disconnect
# (service/worker_sessions.py); None where sessions are not configured (tests, dev).
SessionEnder = Callable[[uuid.UUID, uuid.UUID], Awaitable[None]]


@dataclass(frozen=True)
class GrantView:
    """A grant as a tenant admin sees it. The engineer's address is theirs to see (D-173 (2))."""

    id: uuid.UUID
    engineer_name: str
    engineer_email: str
    reason: str
    ticket_ref: str | None
    access: str
    change_reason: str | None
    unmask_personal: bool
    ip_allowlist: list[str]
    starts_at: datetime
    ends_at: datetime
    state: str  # pending_verification reads "waiting for the engineer" (lane B (12))
    verification: str
    first_used_at: datetime | None
    ended_at: datetime | None
    version: int


def _view(row: SupportGrant) -> GrantView:
    return GrantView(
        id=row.id,
        engineer_name=row.engineer_name,
        engineer_email=row.engineer_email,
        reason=row.reason,
        ticket_ref=row.ticket_ref,
        access=row.access,
        change_reason=row.change_reason,
        unmask_personal=row.unmask_personal,
        ip_allowlist=[str(n) for n in row.ip_allowlist],
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        state=row.state,
        verification=row.verification,
        first_used_at=row.first_used_at,
        ended_at=row.ended_at,
        version=row.version,
    )


async def require_tenant_admin(session: AsyncSession, subject: Subject) -> None:
    """A tenant admin, by their own role (a group's or a custom role's rights are not enough)."""
    found = await session.scalar(
        select(Role.id)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(
            UserRole.user_id == subject.user_id,
            Role.key == TENANT_ADMIN,
            Role.deleted_at.is_(None),
        )
        .limit(1)
    )
    if found is None:
        raise PermissionDenied(code="vendor_support_tenant_admin_only")


async def list_grants(
    session: AsyncSession, subject: Subject, *, limit: int = 200
) -> list[GrantView]:
    """Every grant of the tenant, open ones first, then newest first."""
    await require_tenant_admin(session, subject)
    open_first = SupportGrant.state.in_([s.value for s in rules.OPEN_STATES])
    rows = await session.scalars(
        select(SupportGrant)
        .order_by(open_first.desc(), SupportGrant.created_at.desc(), SupportGrant.id)
        .limit(limit)
    )
    return [_view(r) for r in rows]


async def get_grant(session: AsyncSession, subject: Subject, grant_id: uuid.UUID) -> GrantView:
    """One grant, or 404."""
    await require_tenant_admin(session, subject)
    row = await session.get(SupportGrant, grant_id)
    if row is None:
        raise NotFound(code="support_grant_not_found")
    return _view(row)


async def open_grants(session: AsyncSession) -> int:
    """How many grants still count (waiting for the engineer, or in use)."""
    count = await session.scalar(
        select(func.count())
        .select_from(SupportGrant)
        .where(SupportGrant.state.in_([s.value for s in rules.OPEN_STATES]))
    )
    return int(count or 0)


async def never_allowed(session: AsyncSession) -> bool:
    """The tenant's opt-out (D-173 (9)); no settings row yet means allowed."""
    found = await session.scalar(select(IdentitySettings.never_allow_vendor_support).limit(1))
    return bool(found)


async def set_never_allow(
    session: AsyncSession,
    subject: Subject,
    *,
    never_allow: bool,
    expected_version: int,
) -> int:
    """Turn the opt-out on or off; the settings' new version. Refused on while grants are open.

    The same row and version as the other sign-in settings (no row yet is version 0, as
    `get_identity_settings` reads it), written the same way: an upsert that only lands on the
    version read. The route records the audit entry; the event tells every tenant admin.
    """
    await require_tenant_admin(session, subject)
    current = await session.scalar(select(IdentitySettings).with_for_update())
    version = 0 if current is None else current.version
    if version != expected_version:
        raise Conflict(
            code="version_conflict",
            params={"expected_version": expected_version, "current_version": version},
        )
    if current is not None and current.never_allow_vendor_support == never_allow:
        return version
    if current is None and not never_allow:
        return version  # the default already
    if never_allow and await open_grants(session):
        raise Conflict(code="vendor_support_grants_open")
    context = session.info[SESSION_TENANT_KEY]
    saved = await session.scalar(
        insert(IdentitySettings)
        .values(
            tenant_id=context.tenant_id,
            created_by=subject.user_id,
            updated_by=subject.user_id,
            version=1,
            never_allow_vendor_support=never_allow,
        )
        .on_conflict_do_update(
            index_elements=[IdentitySettings.tenant_id],
            set_={
                "never_allow_vendor_support": never_allow,
                "updated_by": subject.user_id,
                "updated_at": func.now(),
                "version": IdentitySettings.version + 1,
            },
            where=IdentitySettings.version == expected_version,
        )
        .returning(IdentitySettings.version)
    )
    if saved is None:  # changed by someone else between the read and the write
        raise Conflict(code="version_conflict", params={"expected_version": expected_version})
    new_version = int(saved)
    await record_event(
        session,
        VendorSupportSettingChanged(never_allow=never_allow),
        aggregate_id=context.tenant_id,
        aggregate_version=new_version,
    )
    return new_version


@dataclass(frozen=True)
class Ended:
    """A grant just ended in the database: what the after-commit steps need."""

    grant_id: uuid.UUID
    tenant_id: uuid.UUID
    support_user_id: uuid.UUID | None
    keycloak_id: str | None


async def end_grant(  # noqa: PLR0913 - the grant, how it ends and who ends it, keyword-only
    session: AsyncSession,
    grant_id: uuid.UUID,
    *,
    tenant_id: uuid.UUID,
    revoked_by: uuid.UUID | None,
    now: datetime,
    source: Source,
) -> Ended | None:
    """End an open grant in this transaction (revoked by an admin, or its time is up).

    The local account is disabled with it, so the database refuses a sign-in at once; the
    sessions and the Keycloak account go after the commit (`finish_end`). None when the grant was
    not open (already ended: idempotent, as the schedule and an admin may race).
    """
    row = await session.scalar(
        select(SupportGrant).where(SupportGrant.id == grant_id).with_for_update()
    )
    if row is None or not rules.is_open(row.state):
        return None
    before = row.state
    row.state = (rules.GrantState.REVOKED if revoked_by else rules.GrantState.ENDED).value
    row.ended_at = now
    row.ended_by = revoked_by
    row.version += 1
    keycloak_id: str | None = None
    if row.support_user_id is not None:
        account = await session.get(User, row.support_user_id)
        if account is not None:
            keycloak_id = account.external_subject
            await session.execute(
                update(User)
                .where(User.id == account.id)
                .values(status="disabled", can_sign_in=False, version=User.version + 1)
            )
    await session.flush()
    await record_changes(
        session,
        record_type=GRANT_RECORD_TYPE,
        record_id=row.id,
        version=row.version,
        kind="updated",
        changes=[Change("state", before, row.state)],
        source=source,
    )
    await record_event(
        session,
        SupportGrantChanged(
            grant_id=row.id,
            change="revoked" if revoked_by else "ended",
            access=rules.Access(row.access).value,
            ends_at=row.ends_at,
        ),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )
    return Ended(row.id, tenant_id, row.support_user_id, keycloak_id)


async def finish_end(
    ended: Ended, *, end_sessions: SessionEnder | None, admin: IdentityAdmin | None
) -> None:
    """After the commit: end every session, then disable and delete the Keycloak account.

    Best effort in order, each step logged on failure and the next still tried: the database row
    already refuses every request and sign-in, and the schedule calls this again for a grant whose
    account still exists (`keycloak_id` kept until the delete succeeds).
    """
    if end_sessions is not None and ended.support_user_id is not None:
        try:
            await end_sessions(ended.tenant_id, ended.support_user_id)
        except Exception:  # noqa: BLE001 - any failure here is logged; the next step still runs
            log.warning("support_grant_sessions_end_failed", grant_id=str(ended.grant_id))
    if admin is None or ended.keycloak_id is None:
        return
    account = ended.keycloak_id
    # Each step on its own: a refused or unreachable logout or disable never skips the delete
    # (lane B on set_enabled: the delete still runs when the disable failed).
    steps: tuple[tuple[str, Callable[[], Awaitable[None]]], ...] = (
        ("logout", lambda: admin.logout_user(account)),
        ("disable", lambda: admin.set_enabled(account, enabled=False)),
        ("delete", lambda: admin.delete_user(account)),
    )
    for name, step in steps:
        try:
            await step()
        except (IdentityAdminRefused, IdentityAdminUnavailable):
            log.warning(
                "support_grant_account_step_failed", step=name, grant_id=str(ended.grant_id)
            )


async def due(session: AsyncSession, now: datetime) -> list[uuid.UUID]:
    """Open grants whose time is up, for the 30-second schedule."""
    rows = await session.scalars(
        select(SupportGrant.id).where(
            SupportGrant.state.in_([s.value for s in rules.OPEN_STATES]),
            SupportGrant.ends_at <= now,
        )
    )
    return list(rows)
