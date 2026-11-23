"""Who owns an asset, for approvals elsewhere (WP-047a S2a; REQ-SR-031; lane B's shape).

A service request's approval stage may name "the owner of the asset it is about". The owner is
the asset's holder person (`owner_user_id`). An asset held by a department, or fitted to another
asset, has no person and is left out, so the caller's own fallback applies (the approval
administrators, recorded); a department head is never guessed. Only soft-deleted assets are left
out: a retired or disposed asset's holder still counts, as the request may be about returning it.

Read-only and IDs only, with no permission check of its own: the approval engine decides who
approves, and the approver then sees the request through the request's own rules, never the
asset's. The caller checks that each person is active and may sign in.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.modules.assets.infra.models import Asset


async def owners_of(
    session: AsyncSession, asset_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, uuid.UUID]:
    """{asset ID: its holder person's ID}, for the assets of the session's tenant that have one."""
    if not asset_ids:
        return {}
    tenant: uuid.UUID = session.info[SESSION_TENANT_KEY].tenant_id
    rows = await session.execute(
        select(Asset.id, Asset.owner_user_id).where(
            Asset.tenant_id == tenant,
            Asset.id.in_(set(asset_ids)),
            Asset.deleted_at.is_(None),
            Asset.owner_user_id.is_not(None),
        )
    )
    return {asset_id: owner for asset_id, owner in rows.all() if owner is not None}
