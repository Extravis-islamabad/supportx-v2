"""The tenant's access defaults (WP-021): what the built-in technician role sees (D-052, D-073).

Asked once at first run, "group" preselected: technicians see their groups' records, their own,
and the unassigned ones of their sites. "all" widens those defaults to every record. Until the
question is answered the least-privileged answer applies. A change refreshes compiled
permissions once committed, so it takes effect live.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import Scope, access_changed
from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict
from app.modules.identity_access.events import AccessSettingsChanged
from app.modules.identity_access.infra.models import AccessSettings
from app.shared.events import record_event

TechnicianScope = Literal["group", "all"]
DEFAULT_SCOPE: TechnicianScope = "group"


@dataclass(frozen=True)
class AccessSettingsView:
    """The settings as shown (version 0: never saved, the question is still open)."""

    technician_scope: TechnicianScope
    answered_at: datetime | None
    version: int


async def tenant_technician_scope(session: AsyncSession) -> Scope:
    """The scope the technician defaults use in the session's tenant."""
    found = await session.scalar(select(AccessSettings.technician_scope))
    return cast("Scope", found or DEFAULT_SCOPE)


async def get_access_settings(session: AsyncSession) -> AccessSettingsView:
    """The tenant's settings, or the defaults when never saved."""
    row = await session.scalar(select(AccessSettings))
    if row is None:
        return AccessSettingsView(DEFAULT_SCOPE, None, 0)
    return AccessSettingsView(
        cast("TechnicianScope", row.technician_scope), row.answered_at, row.version
    )


async def save_access_settings(
    session: AsyncSession, *, technician_scope: TechnicianScope, expected_version: int
) -> AccessSettingsView:
    """Answer (or change the answer to) the question. If-Match: version 0 for the first answer."""
    current = await get_access_settings(session)
    if current.version != expected_version:
        raise Conflict(
            code="version_conflict",
            params={"expected_version": expected_version, "current_version": current.version},
        )
    context = session.info[SESSION_TENANT_KEY]
    now = datetime.now(UTC)
    values = {
        "technician_scope": technician_scope,
        "answered_at": now,
        "updated_at": now,
        "updated_by": context.user_id,
    }
    statement = (
        insert(AccessSettings)
        .values(tenant_id=context.tenant_id, created_by=context.user_id, version=1, **values)
        .on_conflict_do_update(
            index_elements=[AccessSettings.tenant_id],
            set_={**values, "version": AccessSettings.version + 1},
            where=AccessSettings.version == expected_version,
        )
        .returning(AccessSettings.version)
    )
    version = await session.scalar(statement)
    if version is None:  # saved by someone else between the read and the write
        raise Conflict(code="version_conflict", params={"expected_version": expected_version})
    changed = (
        ["technician_scope"] if technician_scope != current.technician_scope else ["answered_at"]
    )
    await record_event(
        session,
        AccessSettingsChanged(changed_fields=changed),
        aggregate_id=context.tenant_id,
        aggregate_version=version,
    )
    access_changed(session)
    return AccessSettingsView(technician_scope, now, version)
