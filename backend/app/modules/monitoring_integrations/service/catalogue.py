"""MonetX in the integrations catalogue (REQ-INT-001): a `monitoring` connector kind.

The catalogue asks the entitlement interface for `monetx_integration` (rule f). Instances are
the tenant's connections; their status comes from the last import or connection test.
"""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.monitoring_integrations.infra.models import MonitoringConnection
from app.modules.monitoring_integrations.service.connections import FEATURE
from app.modules.monitoring_integrations.service.topology import EVERY
from app.shared.connectors.ports import (
    ConnectorCategory,
    ConnectorInstance,
    ConnectorKind,
    ConnectorStatus,
    register_connector,
    unregister_connector,
)

MONETX = "monetx"
MONETX_KIND = ConnectorKind(
    code=MONETX,
    category=ConnectorCategory.MONITORING,
    page="/admin/integrations/monitoring",
    reason_labels="monitoring_reason",
    feature=FEATURE.value,
    keywords=("connector_keyword.monetx", "connector_keyword.topology"),
)


def _instance(row: MonitoringConnection) -> ConnectorInstance:
    if not row.enabled:
        status, reason = ConnectorStatus.PAUSED, None
    elif row.secret_ref is None:
        status, reason = ConnectorStatus.NOT_SET_UP, None
    elif row.last_error_code is not None:
        status, reason = ConnectorStatus.FAILED, row.last_error_code
    else:
        status, reason = ConnectorStatus.ACTIVE, None
    return ConnectorInstance(
        id=row.id,
        name=row.name,
        status=status,
        reason=reason,
        last_success_at=row.last_run_at if reason is None else None,
        next_run_at=(row.last_run_at + EVERY) if row.enabled and row.last_run_at else None,
    )


class MonetXConnectors:
    """The tenant's MonetX connections as catalogue instances."""

    async def instances(self, session: AsyncSession) -> Sequence[ConnectorInstance]:
        """Every connection, by name."""
        rows = await session.scalars(
            select(MonitoringConnection)
            .where(MonitoringConnection.deleted_at.is_(None))
            .order_by(MonitoringConnection.name)
        )
        return [_instance(r) for r in rows]


def register() -> None:
    """Put MonetX in the catalogue (module startup)."""
    register_connector(MONETX_KIND, MonetXConnectors())


def unregister() -> None:
    """Module shutdown."""
    unregister_connector(MONETX)
