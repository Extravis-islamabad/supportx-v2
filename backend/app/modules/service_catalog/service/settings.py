"""The tenant's catalog settings (WP-031 s1): one row, made on first need.

`hide_default_incident_template` (REQ-CAT-014): requesters are offered only the catalog's
"report a problem" entries, not the default incident form. `starter_seeded_at` is internal
(D-138): it is never changed through the API.
"""

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict
from app.modules.identity_access import Subject
from app.modules.service_catalog.events import CatalogSettingsChanged
from app.modules.service_catalog.infra.models import CatalogSettings
from app.modules.service_catalog.service.common import require_manage
from app.shared.events import record_event

EDITABLE = ("hide_default_incident_template",)


async def read(session: AsyncSession) -> CatalogSettings:
    """The tenant's settings; the defaults (version 1, not stored) before the first change.

    Reading never writes ("GET never acts"): the row is made by the first change or the seed.
    """
    row: CatalogSettings | None = await session.scalar(select(CatalogSettings))
    if row is not None:
        return row
    return CatalogSettings(
        tenant_id=session.info[SESSION_TENANT_KEY].tenant_id,
        starter_seeded_at=None,
        hide_default_incident_template=False,
        version=1,
    )


async def load_for_update(session: AsyncSession) -> CatalogSettings:
    """The tenant's row, locked; created with the defaults if it does not exist yet."""
    await session.execute(
        insert(CatalogSettings)
        .values(tenant_id=session.info[SESSION_TENANT_KEY].tenant_id)
        .on_conflict_do_nothing(index_elements=["tenant_id"])
    )
    row = await session.scalar(select(CatalogSettings).with_for_update())
    assert row is not None  # noqa: S101 - inserted just above (RLS: this tenant's row only)
    return row


async def update(
    session: AsyncSession,
    subject: Subject,
    *,
    expected_version: int,
    values: Mapping[str, Any],
) -> CatalogSettings:
    """Change what is sent (If-Match); unchanged input keeps the version."""
    require_manage(subject)
    row = await load_for_update(session)
    if row.version != expected_version:
        raise Conflict(
            code="version_conflict",
            params={"expected_version": expected_version, "current_version": row.version},
        )
    changed = [k for k in EDITABLE if k in values and getattr(row, k) != values[k]]
    if not changed:
        return row
    for name in changed:
        setattr(row, name, values[name])
    row.version += 1
    await session.flush()
    await record_event(
        session,
        CatalogSettingsChanged(changed_fields=changed),
        aggregate_id=row.tenant_id,
        aggregate_version=row.version,
    )
    return row


__all__ = ["load_for_update", "read", "update"]
