"""Who owns a CI, for approvals elsewhere (WP-047a S2a; REQ-SR-031; lane B's shape).

A service request's approval stage may name "the owner of the CI it is about": its owner person
(`owner_user_id`) and owner group (`owner_group_id`), never its support group
(`managed_by_group_id`). A CI with neither is left out, the same as a missing one, so the
caller's own fallback applies. Soft-deleted CIs are left out.

Read-only and IDs only, with no permission check of its own: the approval engine decides who
approves, and the approver then sees the request through the request's own rules, never the
CI's. Merged CIs resolve to their survivor once WP-053 S4b is on main (lane B adds that step).
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.modules.cmdb.infra.models import Ci


@dataclass(frozen=True)
class Owner:
    """A CI's owner: a person, a group, or both."""

    user_id: uuid.UUID | None
    group_id: uuid.UUID | None


async def owners_of(session: AsyncSession, ci_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Owner]:
    """{CI ID: its owner}, for the CIs of the session's tenant that have one."""
    if not ci_ids:
        return {}
    tenant: uuid.UUID = session.info[SESSION_TENANT_KEY].tenant_id
    rows = await session.execute(
        select(Ci.id, Ci.owner_user_id, Ci.owner_group_id).where(
            Ci.tenant_id == tenant,
            Ci.id.in_(set(ci_ids)),
            Ci.deleted_at.is_(None),
            or_(Ci.owner_user_id.is_not(None), Ci.owner_group_id.is_not(None)),
        )
    )
    return {ci_id: Owner(user_id, group_id) for ci_id, user_id, group_id in rows.all()}
