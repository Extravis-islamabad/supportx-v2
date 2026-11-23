"""A person's cost per hour, for a worklog's technician cost (WP-046a S3, REQ-INC-068).

People are identity_access's (lane B, #427): it keeps each person's effective-dated rate and
exports `cost_rate(session, user_id, at)`, None when unset, not yet started, or set in another
currency than today's base (D-164). This module owns the port; its default reads identity_access
(work_items imports identity_access, never the other way), and tests install a fake. A rate is
personal and pay-related: it is only read to snapshot a worklog's cost, never shown here, and
that snapshot is not a view of the rate (D-164 item 3: the worklog save's own audit covers it).
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules import identity_access


class CostRates(Protocol):
    """The rate in force for a person at a time, in the base currency, or None (unset)."""

    async def cost_rate(
        self, session: AsyncSession, user_id: uuid.UUID, at: datetime
    ) -> Decimal | None:
        """The rate in force at `at`."""


class _PeopleRates:
    """identity_access's rate in force (no permission check: a system snapshot, D-164)."""

    async def cost_rate(
        self, session: AsyncSession, user_id: uuid.UUID, at: datetime
    ) -> Decimal | None:
        return await identity_access.cost_rate(session, user_id, at)


_PORT: list[CostRates] = [_PeopleRates()]


def register_cost_rates(port: CostRates) -> None:
    """Install other rates (a fake in tests)."""
    _PORT[0] = port


def reset_cost_rates() -> None:
    """Back to identity_access's rates (after a test's fake)."""
    _PORT[0] = _PeopleRates()


async def rate_at(session: AsyncSession, user_id: uuid.UUID, at: datetime) -> Decimal | None:
    """The person's cost per hour at `at`, or None when nobody set one."""
    return await _PORT[0].cost_rate(session, user_id, at)


__all__ = ["CostRates", "rate_at", "register_cost_rates", "reset_cost_rates"]
