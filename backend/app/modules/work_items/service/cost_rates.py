"""A person's cost per hour, for a worklog's technician cost (WP-046a S3, REQ-INC-068).

People are identity_access's (lane B): it keeps each person's effective-dated rate and exports
`cost_rate(session, user_id, at)`. This module owns the port and its default, "no rate"; the
adapter that reads identity_access lives here too (work_items imports identity_access, never the
other way) and registers itself at start-up once that function is on main. A rate is personal
and pay-related: it is only read to snapshot a worklog's cost, never shown here.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession


class CostRates(Protocol):
    """The rate in force for a person at a time, in the base currency, or None (unset)."""

    async def cost_rate(
        self, session: AsyncSession, user_id: uuid.UUID, at: datetime
    ) -> Decimal | None:
        """The rate in force at `at`."""


class _NoRates:
    async def cost_rate(
        self, session: AsyncSession, user_id: uuid.UUID, at: datetime
    ) -> Decimal | None:
        del session, user_id, at
        return None


_PORT: list[CostRates] = [_NoRates()]


def register_cost_rates(port: CostRates) -> None:
    """Install the rates (the identity_access adapter at start-up, a fake in tests)."""
    _PORT[0] = port


def reset_cost_rates() -> None:
    """Back to "no rate" (tests)."""
    _PORT[0] = _NoRates()


async def rate_at(session: AsyncSession, user_id: uuid.UUID, at: datetime) -> Decimal | None:
    """The person's cost per hour at `at`, or None when nobody set one."""
    return await _PORT[0].cost_rate(session, user_id, at)


__all__ = ["CostRates", "rate_at", "register_cost_rates", "reset_cost_rates"]
