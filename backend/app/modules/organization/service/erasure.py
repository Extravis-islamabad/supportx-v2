"""The organisation's part of a person's GDPR erasure (D-171, ADR-052 §4).

Their site and group memberships go (ordinary membership events, so screens and access follow).
The groups they lead and the departments they head pass to the successor (D4: shared things are
never orphaned), as ordinary saves with their change events. Idempotent: a second call finds
nothing and returns zero counts. Counts by kind only, never data.
"""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.organization.infra.models import Department, GroupMember, SiteMember, SupportGroup
from app.modules.organization.service import structure, units


async def erase_person_units(
    session: AsyncSession, person_id: uuid.UUID, *, successor_id: uuid.UUID
) -> dict[str, int]:
    """Memberships removed; leadership and headship moved to `successor_id`. Counts by kind."""
    found = await units.memberships(session, person_id)
    for site_id in sorted(found.site_ids):
        await units.remove_member(session, "site", site_id, person_id)
    for group_id in sorted(found.group_ids):
        await units.remove_member(session, "group", group_id, person_id)
    # Memberships of removed sites and groups (no screen shows them): gone too, no event.
    leftover_sites = await session.execute(
        delete(SiteMember).where(SiteMember.user_id == person_id)
    )
    leftover_groups = await session.execute(
        delete(GroupMember).where(GroupMember.user_id == person_id)
    )
    led = list(
        await session.scalars(
            select(SupportGroup).where(
                SupportGroup.lead_id == person_id, SupportGroup.deleted_at.is_(None)
            )
        )
    )
    for group in led:
        await structure.save_group(
            session, group.id, {"lead_id": successor_id}, expected_version=group.version
        )
    headed = list(
        await session.scalars(
            select(Department).where(
                Department.head_id == person_id, Department.deleted_at.is_(None)
            )
        )
    )
    for department in headed:
        await structure.save_department(
            session, department.id, {"head_id": successor_id}, expected_version=department.version
        )
    return {
        "site_memberships": len(found.site_ids) + int(getattr(leftover_sites, "rowcount", 0) or 0),
        "group_memberships": len(found.group_ids)
        + int(getattr(leftover_groups, "rowcount", 0) or 0),
        "groups_led": len(led),
        "departments_headed": len(headed),
    }
