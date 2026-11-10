"""A rule or an escalation that names a person moves the record with them (D-154 "rules").

D-154a keeps the assignee inside the record's group; a person is assigned from outside it only
by moving the record to their group in the same save. SLA escalations (`reassign_person`) and
automation's set-technician follow the same rule (Haider, through the coordinator, 2026-11-10):

- The step names the person and the group to move with them, chosen in the editor (filled in
  when they are in one group; migration 0126 did that for the steps saved before).
- At run time, the person active, not Away and still in that group: the record moves to the
  group and to them.
- Otherwise the record goes to the group only, nobody on it, and the caller says why
  (`assignee_unavailable`) and tells the step's owner. Never skipped silently.

One helper for both, so the two can never drift apart.
"""

import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules import automation
from app.modules.identity_access import active_user_ids
from app.modules.organization import memberships


class Unavailable(StrEnum):
    """Why the person a step names could not be assigned (history and the owner's notice)."""

    INACTIVE = "inactive"  # deactivated or removed
    AWAY = "away"  # set themselves Away (REQ-ASG-006)
    NOT_IN_GROUP = "not_in_group"  # left the step's group, or the step names none of theirs


@dataclass(frozen=True)
class Placement:
    """What a person-naming step sets on the record, and why the person was left out if so."""

    values: dict[str, Any] = field(default_factory=dict)
    unavailable: Unavailable | None = None


async def place_person(
    session: AsyncSession,
    person_id: uuid.UUID,
    group_id: uuid.UUID | None,
    *,
    record_group_id: uuid.UUID | None,
) -> Placement:
    """Where a step that assigns `person_id` (with `group_id`) puts the record now.

    With no group on the step (one saved before D-154 for a person in several groups), the
    person's only group or the record's own group if they are in it stands in; else the record
    keeps its group and nobody is assigned.
    """
    groups = (await memberships(session, person_id)).group_ids
    if group_id is None:
        if len(groups) == 1:
            group_id = next(iter(groups))
        elif record_group_id is not None and record_group_id in groups:
            group_id = record_group_id
    why: Unavailable | None = None
    if person_id not in await active_user_ids(session, [person_id]):
        why = Unavailable.INACTIVE
    elif person_id in await automation.away_user_ids(session, [person_id]):
        why = Unavailable.AWAY
    elif group_id is None or group_id not in groups:
        why = Unavailable.NOT_IN_GROUP
    if why is None:
        return Placement({"group_id": str(group_id), "technician_id": str(person_id)})
    if group_id is None:
        return Placement({"technician_id": None}, why)  # the record keeps its group
    return Placement({"group_id": str(group_id), "technician_id": None}, why)
