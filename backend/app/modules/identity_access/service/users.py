"""Just-in-time user provisioning (WP-006).

On every login the user's row in the chosen tenant is created or refreshed from the identity
provider (name, email, locale, type, last login). The tenant must exist and be active.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from app.core.database import Database
from app.core.errors import Conflict, NotFound, PermissionDenied
from app.core.tenancy import TenantContext
from app.modules.identity_access.domain.identity import Identity
from app.modules.identity_access.infra.models import User
from app.modules.organization import TenantStatus, get_current_tenant
from app.shared.ids import new_id


@dataclass(frozen=True)
class ProvisionedUser:
    """The user's row in one tenant, plus that tenant's display name."""

    user_id: uuid.UUID
    tenant_id: uuid.UUID
    tenant_name: str


async def tenant_name(database: Database, tenant_id: uuid.UUID) -> str | None:
    """Name of an active tenant, or None if it is unknown or suspended."""
    async with database.tenant_session(TenantContext(tenant_id)) as session:
        try:
            tenant = await get_current_tenant(session)
        except NotFound:
            return None
    return tenant.name if tenant.status is TenantStatus.ACTIVE else None


async def provision_user(
    database: Database, tenant_id: uuid.UUID, identity: Identity, now: datetime
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
            .returning(User.id, User.status)
        )
        try:
            row = (await session.execute(statement)).one()
        except IntegrityError as exc:
            # Another account in this tenant already uses the email address.
            raise Conflict(code="user_email_conflict") from exc
    if row.status != "active":
        raise PermissionDenied(code="user_disabled")
    return ProvisionedUser(user_id=row.id, tenant_id=tenant_id, tenant_name=tenant.name)
