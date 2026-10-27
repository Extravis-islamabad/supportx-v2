"""Who uses a site, group or department (WP-021): removing one in use is refused.

The organization module cannot read other modules' tables (CLAUDE.md rule e), so modules that
point at a unit register a check here when they are imported (people in identity_access,
records in work_items). Each check counts the live rows that use the unit.
"""

import uuid
from collections.abc import Awaitable, Callable
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

UnitType = Literal["site", "group", "department"]
UsageCheck = Callable[[AsyncSession, uuid.UUID], Awaitable[int]]

_CHECKS: dict[UnitType, list[tuple[str, UsageCheck]]] = {"site": [], "group": [], "department": []}


def register_usage(kind: UnitType, what: str, check: UsageCheck) -> None:
    """Add a check: `what` names the users of the unit ("people", "records") in the 409."""
    entries = _CHECKS[kind]
    if all(name != what for name, _ in entries):
        entries.append((what, check))


async def usage(session: AsyncSession, kind: UnitType, unit_id: uuid.UUID) -> dict[str, int]:
    """How many of each kind of row use the unit (only kinds with at least one)."""
    found: dict[str, int] = {}
    for what, check in _CHECKS[kind]:
        count = await check(session, unit_id)
        if count:
            found[what] = count
    return found
