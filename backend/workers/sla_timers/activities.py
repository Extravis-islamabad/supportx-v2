"""The SLA workflow's activities (WP-025 session 3): each is one tenant transaction.

The workflow (`app.modules.sla.infra.temporal`) names them; they call the sla service, which
does the firing exactly once under the record's lock (`sla.fire`).
"""

import uuid

from temporalio import activity

from app.core.database import Database
from app.core.tenancy import TenantContext
from app.modules import sla
from app.modules.sla.infra.temporal import SLA_FIRE, SLA_NEXT_WAKE, ClockRef
from app.shared.clock import system_clock


class SlaActivities:
    """The workflow's two activities, each one tenant transaction."""

    def __init__(self, database: Database) -> None:
        """Bound to the worker's database."""
        self.database = database

    @activity.defn(name=SLA_NEXT_WAKE)
    async def next_wake(self, ref: ClockRef) -> str | None:
        """The earliest pending moment, ISO 8601 (None: nothing pending)."""
        async with self.database.tenant_session(TenantContext(uuid.UUID(ref.tenant_id))) as s:
            moment = await sla.next_wake(s, uuid.UUID(ref.record_id))
        return moment.isoformat() if moment is not None else None

    @activity.defn(name=SLA_FIRE)
    async def fire(self, ref: ClockRef) -> int:
        """Fire what is due now; how many things fired (0 after a repeated wake)."""
        async with self.database.tenant_session(TenantContext(uuid.UUID(ref.tenant_id))) as s:
            result = await sla.fire(s, uuid.UUID(ref.record_id), now=system_clock.now())
        return len(result.fired)
