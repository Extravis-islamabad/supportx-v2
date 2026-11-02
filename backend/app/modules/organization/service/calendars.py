"""Which working calendar a site or support group names (REQ-ADM-040; WP-025, D-115 D3).

The calendars themselves belong to the sla module. Organization stores only `calendar_id` on
its own rows; whether an ID is a calendar the tenant may use is answered by the sla module,
which registers its check here when it is imported (the same pattern as `register_usage`), so
organization never imports sla and the two packages cannot import each other in a loop.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.organization.infra.models import Site, SupportGroup

CalendarCheck = Callable[[AsyncSession, uuid.UUID], Awaitable[bool]]

_CHECK: list[CalendarCheck] = []


def register_calendar_check(check: CalendarCheck) -> None:
    """Called by the sla module at import: whether an ID is a live calendar of the tenant."""
    _CHECK[:] = [check]


async def calendar_usable(session: AsyncSession, calendar_id: uuid.UUID) -> bool:
    """Whether a site or group may name this calendar.

    Without a registered check (a test app without the sla module) only the database's
    same-tenant foreign key guards the value.
    """
    return await _CHECK[0](session, calendar_id) if _CHECK else True


@dataclass(frozen=True)
class Named:
    """A site or group, by ID and name, for "used by" lists."""

    id: uuid.UUID
    name: str


@dataclass(frozen=True)
class CalendarUsers:
    """The live sites and groups that name a calendar (REQ-ADM-040 AC1)."""

    sites: list[Named] = field(default_factory=list)
    groups: list[Named] = field(default_factory=list)

    @property
    def count(self) -> int:
        """How many sites and groups use it."""
        return len(self.sites) + len(self.groups)


async def calendar_users(
    session: AsyncSession, calendar_ids: list[uuid.UUID]
) -> dict[uuid.UUID, CalendarUsers]:
    """Per calendar, the live sites and groups that name it, by name."""
    sites: dict[uuid.UUID, list[Named]] = {}
    groups: dict[uuid.UUID, list[Named]] = {}
    if calendar_ids:
        for row in await session.execute(
            select(Site.calendar_id, Site.id, Site.name)
            .where(Site.calendar_id.in_(calendar_ids), Site.deleted_at.is_(None))
            .order_by(Site.name)
        ):
            sites.setdefault(row.calendar_id, []).append(Named(row.id, row.name))
        for row in await session.execute(
            select(SupportGroup.calendar_id, SupportGroup.id, SupportGroup.name)
            .where(SupportGroup.calendar_id.in_(calendar_ids), SupportGroup.deleted_at.is_(None))
            .order_by(SupportGroup.name)
        ):
            groups.setdefault(row.calendar_id, []).append(Named(row.id, row.name))
    return {
        calendar_id: CalendarUsers(sites.get(calendar_id, []), groups.get(calendar_id, []))
        for calendar_id in calendar_ids
    }
