"""A tenant's connector defaults (WP-040, D-041: the D-118 defaults, editable per tenant).

- **When a connector counts as failing:** after this many failed runs in a row (3). An
  authentication failure counts at once and is not editable: a refused credential never
  recovers by itself.
- **How long connector errors are kept:** 90 days.
- **How often a new directory syncs:** every 30 minutes, until its own interval is changed.

No row means Appendix A's defaults. Saving takes the version read (If-Match) and goes through
the outbox in the same transaction, so every admin's settings card updates live.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict, FieldError, ValidationFailed
from app.modules.integrations.domain.connector_health import (
    ERROR_RETENTION_DAYS,
    FAILING_AFTER_RUNS,
    SYNC_MINUTES,
)
from app.modules.integrations.events import ConnectorSettingsChanged
from app.modules.integrations.infra.models import ConnectorSettings
from app.shared.events import record_event

# field -> (lowest, highest): the table's check, said per field to the screen.
RANGES: dict[str, tuple[int, int]] = {
    "failing_after_runs": (1, 20),
    "error_retention_days": (7, 365),
    "sync_minutes": (15, 1440),
}


@dataclass(frozen=True)
class ConnectorDefaults:
    """The tenant's connector defaults and the version to send back when saving."""

    failing_after_runs: int = FAILING_AFTER_RUNS
    error_retention_days: int = ERROR_RETENTION_DAYS
    sync_minutes: int = SYNC_MINUTES
    version: int = 0  # never saved


DEFAULTS = ConnectorDefaults()


async def get_connector_settings(session: AsyncSession) -> ConnectorDefaults:
    """The tenant's defaults, or Appendix A's when never saved."""
    row = await session.scalar(select(ConnectorSettings))
    if row is None:
        return DEFAULTS
    return ConnectorDefaults(
        failing_after_runs=row.failing_after_runs,
        error_retention_days=row.error_retention_days,
        sync_minutes=row.sync_minutes,
        version=row.version,
    )


def _problems(values: ConnectorDefaults) -> list[FieldError]:
    found: list[FieldError] = []
    for name, (low, high) in RANGES.items():
        if not low <= getattr(values, name) <= high:
            found.append(
                FieldError(
                    field=f"body.{name}",
                    code="out_of_range",
                    message_key="errors.field.out_of_range",
                    params={"min": low, "max": high},
                )
            )
    return found


async def save_connector_settings(
    session: AsyncSession, values: ConnectorDefaults, *, expected_version: int
) -> tuple[ConnectorDefaults, dict[str, object]]:
    """Save if the stored version is `expected_version` (0 before the first save).

    Returns the saved defaults and, for the audit entry, each changed field before and after.
    """
    if errors := _problems(values):
        raise ValidationFailed(errors=errors)
    row = await session.scalar(select(ConnectorSettings).with_for_update())
    current = await get_connector_settings(session)
    if current.version != expected_version:
        raise Conflict(
            code="version_conflict",
            params={"expected_version": expected_version, "current_version": current.version},
        )
    changes: dict[str, object] = {
        name: {"from": getattr(current, name), "to": getattr(values, name)}
        for name in RANGES
        if getattr(current, name) != getattr(values, name)
    }
    if not changes:
        return current, {}
    fields = {name: getattr(values, name) for name in RANGES}
    if row is None:
        tenant_id = session.info[SESSION_TENANT_KEY].tenant_id
        row = ConnectorSettings(tenant_id=tenant_id, **fields)
        session.add(row)
    else:
        for name, value in fields.items():
            setattr(row, name, value)
        row.version += 1
    await session.flush()
    await record_event(
        session,
        ConnectorSettingsChanged(changed_fields=sorted(changes)),
        aggregate_id=row.tenant_id,
        aggregate_version=row.version,
    )
    saved = await get_connector_settings(session)
    return saved, changes


__all__ = [
    "DEFAULTS",
    "RANGES",
    "ConnectorDefaults",
    "get_connector_settings",
    "save_connector_settings",
]
