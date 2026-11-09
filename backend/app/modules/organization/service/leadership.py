"""Group leadership: what a team lead may manage (D-152).

A team lead manages only the groups they lead (`support_groups.lead_id`), never tenant-wide
settings: their members' availability, the group's assignment rules and round-robin, its reply
templates, saved views and dashboards. Every endpoint for those allows either `groups.manage`
(every group: admins) or `groups.manage_own` for a group the caller leads, and checks it on the
server. Another group's settings answer 403 `group_not_led`; another group's records stay 404,
as the record scopes already make them.

The modules that own those endpoints call `may_manage_group` or `require_group_manager` here
(organization's public interface), so the rule lives in one place.
"""

import uuid
from typing import Protocol

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import PermissionDenied
from app.modules.organization.infra.models import SupportGroup

MANAGE = "groups.manage"
MANAGE_OWN = "groups.manage_own"


class GroupActor(Protocol):
    """Who asks: the authorization subject's user and its permissions (structural)."""

    @property
    def user_id(self) -> uuid.UUID:
        """The person."""
        ...

    def holds(self, permission: str) -> bool:
        """Whether they hold the permission at any scope."""
        ...


def _led(user_id: uuid.UUID) -> Select[uuid.UUID]:
    # Disabled or deleted groups are nobody's to manage: their settings are frozen with them.
    return select(SupportGroup.id).where(
        SupportGroup.lead_id == user_id,
        SupportGroup.deleted_at.is_(None),
        SupportGroup.disabled_at.is_(None),
    )


async def leads_group(session: AsyncSession, user_id: uuid.UUID, group_id: uuid.UUID) -> bool:
    """Whether `user_id` leads the (live) group `group_id`."""
    found = await session.scalar(_led(user_id).where(SupportGroup.id == group_id))
    return found is not None


async def led_groups(session: AsyncSession, user_id: uuid.UUID) -> frozenset[uuid.UUID]:
    """The live groups `user_id` leads (for lists a team lead may manage)."""
    return frozenset((await session.scalars(_led(user_id))).all())


async def may_manage_group(session: AsyncSession, actor: GroupActor, group_id: uuid.UUID) -> bool:
    """`groups.manage`, or `groups.manage_own` for a group the actor leads."""
    if actor.holds(MANAGE):
        return True
    return actor.holds(MANAGE_OWN) and await leads_group(session, actor.user_id, group_id)


async def require_group_manager(
    session: AsyncSession, actor: GroupActor, group_id: uuid.UUID
) -> None:
    """Refuse unless the actor may manage the group.

    403 `group_not_led` for a team lead and another group; otherwise 403 `permission_denied`.
    """
    if await may_manage_group(session, actor, group_id):
        return
    if actor.holds(MANAGE_OWN):
        raise PermissionDenied(code="group_not_led")  # a team lead, another group (D-152)
    raise PermissionDenied(params={"permission": MANAGE_OWN})
