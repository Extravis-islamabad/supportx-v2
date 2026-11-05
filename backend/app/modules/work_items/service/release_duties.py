"""Release roles as open duties for the role editor's preview (REQ-REL-024 AC2).

identity_access asks "which open duties of these people need these permissions?" before an admin
saves a role change (lane B's `DutyLookup`, #223). A release role names who may hold it: anyone
holding one of its permissions, the people it names, or the members of the groups it names
(REQ-REL-024 AC1); no rule at all means whoever may see releases. A person holding a role on an
open release has a duty there that a role change could strand.

A role is at risk when the change removes any permission it accepts (lane B's review of #235).
Its holder is still eligible, and not reported, when the role names them, accepts one of their
groups, or they hold another accepted permission the change leaves. The duty carries a
permission the person loses, so identity_access (which drops any duty whose permission the
person keeps) leaves it in.

Built-in roles name their duty `release_role.<code>` (labelled per role); a role an admin added
reports `release_role`, so the screen never shows a tenant's own code (rule d).
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access import OpenDuty, Subject, register_duties, subject_for
from app.modules.organization import memberships
from app.modules.work_items.domain.lifecycle import FINAL_CATEGORIES
from app.modules.work_items.domain.releases import RELEASE_ROLES
from app.modules.work_items.domain.types import RELEASE
from app.modules.work_items.infra.models import WorkItem, WorkItemRoleDef, WorkItemRoleHolder
from app.modules.work_items.service import catalogue as config

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


class _Eligibility:
    """Whether a holder still qualifies for a role after the change, people compiled once."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._tenant = config.tenant_of(session)
        self._subjects: dict[uuid.UUID, Subject] = {}
        self._groups: dict[uuid.UUID, frozenset[uuid.UUID]] = {}

    async def still(
        self, definition: WorkItemRoleDef, user_id: uuid.UUID, kept: frozenset[str]
    ) -> bool:
        """By another accepted permission the change leaves, by name, or through a group."""
        if kept:
            if user_id not in self._subjects:
                self._subjects[user_id] = await subject_for(self._session, self._tenant, user_id)
            if any(self._subjects[user_id].holds(p) for p in kept):
                return True
        if not _accepts(definition)[1]:
            return False
        if user_id not in self._groups:
            found = await memberships(self._session, user_id)
            self._groups[user_id] = frozenset(found.group_ids)
        return _still_eligible(definition, user_id, self._groups[user_id])


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
        # Roles the change could strand: it removes at least one permission they accept.
        at_risk = {
            code: accepted
            for code, d in definitions.items()
            if (accepted := _accepts(d)[0]) & permissions
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
        eligible = _Eligibility(session)
        found: list[OpenDuty] = []
        for user_id, role, record_id, display_id in rows:
            if user_id is None:  # a group holds it; its members are not stranded by one role
                continue
            if await eligible.still(definitions[role], user_id, at_risk[role] - permissions):
                continue
            found.append(
                OpenDuty(
                    user_id=user_id,
                    permission=min(at_risk[role] & permissions),  # one they lose
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
