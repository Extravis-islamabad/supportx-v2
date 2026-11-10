"""The tenant's approval settings: the chair who breaks an exact majority split (D-146).

One row, made on the first change; reading never writes (no chair until then). Changing needs
the service desk configuration right; the route audits it, field history records it here and
the outbox event reloads open settings pages. The chair must be an active person of this tenant,
as a named approver must (a deactivated person or a service identity is refused).
"""

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import PermissionDenied
from app.modules.identity_access import Subject, active_user_ids
from app.modules.work_items.events import WorkItemApprovalSettingsChanged
from app.modules.work_items.infra.models import WorkItemApprovalSettings
from app.modules.work_items.service import work_items as items
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes, stale_version

MANAGE = ("config.service_desk", "settings.manage")
RECORD_TYPE = "work_item_approval_settings"


async def read(session: AsyncSession) -> WorkItemApprovalSettings:
    """The tenant's settings; no chair (version 1, not stored) before the first change."""
    row: WorkItemApprovalSettings | None = await session.scalar(select(WorkItemApprovalSettings))
    if row is not None:
        return row
    return WorkItemApprovalSettings(
        tenant_id=session.info[SESSION_TENANT_KEY].tenant_id, chair_user_id=None, version=1
    )


async def chair(session: AsyncSession) -> uuid.UUID | None:
    """The chair, if the tenant has one (the shared level outcome asks)."""
    return (await read(session)).chair_user_id


async def _chair_problem(session: AsyncSession, value: uuid.UUID | None) -> str | None:
    if value is None:
        return None
    if value not in await active_user_ids(session, [value]):
        return "chair_inactive"  # a deactivated, removed or service identity: never a chair
    return None


async def update(
    session: AsyncSession,
    subject: Subject,
    *,
    expected_version: int,
    values: Mapping[str, Any],
    source: Source,
) -> WorkItemApprovalSettings:
    """Change what is sent (If-Match); unchanged input keeps the version."""
    if not any(subject.holds(p) for p in MANAGE):
        raise PermissionDenied(params={"permission": MANAGE[0], "reason": "no_permission"})
    changed_chair = "chair_user_id" in values
    wanted = values.get("chair_user_id")
    chosen = uuid.UUID(str(wanted)) if wanted is not None else None
    if changed_chair and (problem := await _chair_problem(session, chosen)) is not None:
        raise items.field_errors([("chair_user_id", problem)])
    await session.execute(
        insert(WorkItemApprovalSettings)
        .values(tenant_id=session.info[SESSION_TENANT_KEY].tenant_id)
        .on_conflict_do_nothing(index_elements=["tenant_id"])
    )
    row = await session.scalar(select(WorkItemApprovalSettings).with_for_update())
    assert row is not None  # noqa: S101 - inserted just above (RLS: this tenant's row only)
    if row.version != expected_version:
        raise await stale_version(
            session,
            row,
            expected_version=expected_version,
            record_type=RECORD_TYPE,
            record_id=row.tenant_id,
        )
    if not changed_chair or row.chair_user_id == chosen:
        return row
    before = row.chair_user_id
    row.chair_user_id = chosen
    row.version += 1
    await session.flush()
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=row.tenant_id,
        version=row.version,
        kind="updated",
        changes=[
            Change(
                "chair_user_id",
                str(before) if before else None,
                str(chosen) if chosen else None,
            )
        ],
        source=source,
    )
    await record_event(
        session,
        WorkItemApprovalSettingsChanged(changed_fields=["chair_user_id"]),
        aggregate_id=row.tenant_id,
        aggregate_version=row.version,
    )
    return row


__all__ = ["chair", "read", "update"]
