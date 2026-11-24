"""Who owns a CI, for approvals elsewhere (WP-047a S2a; REQ-SR-031; lane B's shape).

A service request's approval stage may name "the owner of the CI it is about": its owner person
(`owner_user_id`) and owner group (`owner_group_id`), never its support group
(`managed_by_group_id`). A CI with neither is left out, the same as a missing one, so the
caller's own fallback applies. Soft-deleted CIs are left out.

Read-only and IDs only, with no permission check of its own: the approval engine decides who
approves, and the approver then sees the request through the request's own rules, never the
CI's. A merged CI (WP-053 S4b, REQ-CMDB-017) answers with its survivor's owner, keyed by the ID
asked for, following a chain of merges; a merge that was undone (the merged CI restored) is no
alias any more, so the restored CI answers with its own owner again.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.modules.cmdb.infra.models import Ci, CiAlias
from app.modules.cmdb.service.aliases import survivor_of


@dataclass(frozen=True)
class Owner:
    """A CI's owner: a person, a group, or both."""

    user_id: uuid.UUID | None
    group_id: uuid.UUID | None


async def _owners(
    session: AsyncSession, tenant: uuid.UUID, ci_ids: set[uuid.UUID]
) -> dict[uuid.UUID, Owner]:
    rows = await session.execute(
        select(Ci.id, Ci.owner_user_id, Ci.owner_group_id).where(
            Ci.tenant_id == tenant,
            Ci.id.in_(ci_ids),
            Ci.deleted_at.is_(None),
            or_(Ci.owner_user_id.is_not(None), Ci.owner_group_id.is_not(None)),
        )
    )
    return {ci_id: Owner(user_id, group_id) for ci_id, user_id, group_id in rows.all()}


async def owners_of(session: AsyncSession, ci_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Owner]:
    """{CI ID: its owner}, for the CIs of the session's tenant that have one.

    A merged CI's ID gets its survivor's owner (lane B's follow-up to S4b): a request raised
    about a CI that was later merged still finds who owns that CI now.
    """
    if not ci_ids:
        return {}
    tenant: uuid.UUID = session.info[SESSION_TENANT_KEY].tenant_id
    asked = set(ci_ids)
    found = await _owners(session, tenant, asked)
    rest = asked - set(found)
    if not rest:
        return found
    # Only the IDs that are merged CIs (a live alias) go on to their survivor; most never do.
    merged = set(
        await session.scalars(
            select(CiAlias.alias_id).where(
                CiAlias.tenant_id == tenant,
                CiAlias.alias_id.in_(rest),
                CiAlias.restored_at.is_(None),
                CiAlias.deleted_at.is_(None),
            )
        )
    )
    survivors: dict[uuid.UUID, uuid.UUID] = {}
    for merged_id in merged:
        if (survivor := await survivor_of(session, merged_id)) is not None:
            survivors[merged_id] = survivor
    if not survivors:
        return found
    theirs = await _owners(session, tenant, set(survivors.values()))
    for merged_id, survivor in survivors.items():
        if survivor in theirs:
            found[merged_id] = theirs[survivor]
    return found
