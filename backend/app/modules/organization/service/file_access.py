"""Who may see and upload brand images (WP-017; files service port, ADR-028 item 5).

The owner of a brand upload is the tenant itself (`owner_id` = tenant ID, record `branding`).
Uploading and removing need `branding.manage`; seeing the originals too (everyone else sees the
generated, public variants, never the uploads).
"""

import uuid
from typing import Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound, PermissionDenied
from app.shared.files.ports import Action, Actor, Owner, OwnerType

MANAGE = "branding.manage"
RECORD_TYPE = "branding"


@runtime_checkable
class _Holder(Protocol):
    """The caller's compiled permissions (identity_access's Subject)."""

    def holds(self, permission: str) -> bool:
        """Whether they hold `permission` at any scope."""
        ...


class BrandingFileAccess:
    """`FileOwnerAccess` for the tenant's brand uploads."""

    owner_types = frozenset({OwnerType.BRANDING})

    async def check(
        self,
        session: AsyncSession,
        actor: Actor,
        owner_type: OwnerType,
        owner_id: uuid.UUID,
        action: Action,
    ) -> Owner:
        """The tenant as owner, for brand managers of that tenant only."""
        del session, action  # one rule for every action
        if owner_type != OwnerType.BRANDING or owner_id != actor.tenant_id:
            raise NotFound(code="file_owner_not_found")
        if not isinstance(actor, _Holder) or not actor.holds(MANAGE):
            raise PermissionDenied(code="permission_denied")
        return Owner(OwnerType.BRANDING, owner_id, RECORD_TYPE, owner_id)

    async def visible_owners(
        self, session: AsyncSession, actor: Actor, record_type: str, record_id: uuid.UUID
    ) -> set[tuple[OwnerType, uuid.UUID]]:
        """The tenant's brand uploads, for brand managers."""
        del session, record_type
        if record_id != actor.tenant_id or not isinstance(actor, _Holder):
            raise NotFound(code="file_owner_not_found")
        return {(OwnerType.BRANDING, record_id)} if actor.holds(MANAGE) else set()


FILE_ACCESS = BrandingFileAccess()
