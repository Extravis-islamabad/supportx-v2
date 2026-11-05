"""Release roles as open duties for the role editor's preview (REQ-REL-024 AC2).

identity_access asks "which open duties of these people need these permissions?" before an admin
saves a role change (lane B's `DutyLookup`, #223). A release role names who may hold it: anyone
holding one of its permissions, the people it names, or the members of the groups it names
(REQ-REL-024 AC1); no rule at all means whoever may see releases. A person holding a role on an
open release has a duty there that a role change could strand.

A duty is reported only when the person would lose every permission the role accepts, and the
role does not also accept them by name or through a group: a person who keeps another accepted
permission, or is named, still qualifies. Which permissions each person really loses is
identity_access's answer; it drops any duty whose permission the person keeps.

Built-in roles name their duty `release_role.<code>` (labelled per role); a role an admin added
reports `release_role`, so the screen never shows a tenant's own code (rule d).
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access import OpenDuty, register_duties
from app.modules.organization import memberships
from app.modules.work_items.domain.lifecycle import FINAL_CATEGORIES
from app.modules.work_items.domain.releases import RELEASE_ROLES
from app.modules.work_items.domain.types import RELEASE
from app.modules.work_items.infra.models import WorkItem, WorkItemRoleDef, WorkItemRoleHolder

_BUILT_IN = frozenset(RELEASE_ROLES)


def _accepts(definition: WorkItemRoleDef) -> tuple[frozenset[str], bool]:
    """(the permissions the role accepts, whether it also accepts people by name or group)."""
    rule = definition.eligibility or {}
    permissions = frozenset(str(p) for p in rule.get("permissions") or ())
    others = bool(rule.get("user_ids") or rule.get("group_ids"))
    if not permissions and not others:
        return frozenset({RELEASE.permission("view")}), False
    return permissions, others


def _still_eligible(
    definition: WorkItemRoleDef, user: uuid.UUID, groups: frozenset[uuid.UUID]
) -> bool:
    """Whether the role accepts the person by name or through one of their groups."""
    rule = definition.eligibility or {}
    named = {str(u) for u in rule.get("user_ids") or ()}
    eligible_groups = {str(g) for g in rule.get("group_ids") or ()}
    return str(user) in named or bool(eligible_groups & {str(g) for g in groups})


class ReleaseRoleDuties:
    """Asked about any permission: which one a role needs is tenant data (role eligibility)."""

    permissions: frozenset[str] | None = None

    async def open_duties(
        self,
        session: AsyncSession,
        user_ids: Sequence[uuid.UUID],
        permissions: frozenset[str],
        *,
        limit: int,
    ) -> Sequence[OpenDuty]:
        """Open releases on which these people hold a role they would no longer qualify for."""
        if not user_ids or not permissions:
            return []
        definitions = {
            d.code: d
            for d in await session.scalars(
                select(WorkItemRoleDef).where(WorkItemRoleDef.type == RELEASE.code)
            )
        }
        # Roles the change could strand: every permission they accept is among those asked.
        at_risk = {
            code: accepted
            for code, d in definitions.items()
            if (accepted := _accepts(d)[0]) and accepted <= permissions
        }
        if not at_risk:
            return []
        rows = await session.execute(
            select(
                WorkItemRoleHolder.user_id,
                WorkItemRoleHolder.role,
                WorkItem.id,
                WorkItem.display_id,
            )
            .join(WorkItem, WorkItem.id == WorkItemRoleHolder.work_item_id)
            .where(
                WorkItemRoleHolder.type == RELEASE.code,
                WorkItemRoleHolder.user_id.in_(user_ids),
                WorkItemRoleHolder.role.in_(at_risk),
                WorkItem.type == RELEASE.code,
                WorkItem.deleted_at.is_(None),
                WorkItem.status_category.not_in([c.value for c in FINAL_CATEGORIES]),
            )
            .order_by(WorkItem.display_number, WorkItemRoleHolder.role)
        )
        groups: dict[uuid.UUID, frozenset[uuid.UUID]] = {}
        found: list[OpenDuty] = []
        for user_id, role, record_id, display_id in rows:
            if user_id is None:  # a group holds it; its members are not stranded by one role
                continue
            definition = definitions[role]
            if _accepts(definition)[1]:
                if user_id not in groups:
                    groups[user_id] = frozenset((await memberships(session, user_id)).group_ids)
                if _still_eligible(definition, user_id, groups[user_id]):
                    continue
            found.append(
                OpenDuty(
                    user_id=user_id,
                    permission=min(at_risk[role]),
                    record_type=RELEASE.code,
                    record_id=record_id,
                    display_id=display_id,
                    duty=f"release_role.{role}" if role in _BUILT_IN else "release_role",
                )
            )
            if len(found) >= limit:
                break
        return found


RELEASE_DUTIES = ReleaseRoleDuties()


def register() -> None:
    """At import, as the other ports: the role editor's preview asks in the API process."""
    register_duties(RELEASE_DUTIES)
