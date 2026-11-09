"""The workflow waker's activities (WP-048b S1): each is one tenant transaction.

The Temporal workflow (`app.modules.automation.infra.temporal`) names them; they call the
automation runtime, which applies only what is new, so a repeated wake changes nothing.
"""

import uuid

from temporalio import activity

from app.core.database import Database
from app.core.tenancy import TenantContext
from app.modules.automation.domain.interpreter import InstanceStatus, TimerFired
from app.modules.automation.infra.models import WorkflowInstance
from app.modules.automation.infra.temporal import WF_FIRE, WF_NEXT_WAKE, InstanceRef
from app.modules.automation.service import workflow_runtime


class WorkflowActivities:
    """The waker's two activities, each one tenant transaction."""

    def __init__(self, database: Database) -> None:
        """Bound to the worker's database."""
        self.database = database

    @activity.defn(name=WF_NEXT_WAKE)
    async def next_wake(self, ref: InstanceRef) -> str | None:
        """The instance's next wake time, ISO 8601 (None: no timer to wait for)."""
        context = TenantContext(uuid.UUID(ref.tenant_id))
        async with self.database.tenant_session(context) as session:
            found = await session.get(WorkflowInstance, uuid.UUID(ref.instance_id))
            if found is None or found.status != InstanceStatus.WAITING.value:
                return None
            return found.wake_at.isoformat() if found.wake_at is not None else None

    @activity.defn(name=WF_FIRE)
    async def fire(self, ref: InstanceRef) -> bool:
        """Run the instance with a timer event; whether it was still live."""
        context = TenantContext(uuid.UUID(ref.tenant_id))
        async with self.database.tenant_session(context) as session:
            ran = await workflow_runtime.run(session, uuid.UUID(ref.instance_id), TimerFired())
        return ran is not None
