"""Planned publish and retire (WP-031 s1, plan D3; REQ-CAT-024).

Every minute, in every tenant, items whose `publish_at` or `retire_at` has come change status
as if an admin had done it: field history (source "rule"), the outbox event (so open screens
update live) and audit. An item no longer complete at its publish time stays a draft: its
`publish_at` is cleared and the refusal is audited, so the admin sees why.
"""

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import Database
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.audit import WORKER, AuditOutcome, record
from app.modules.service_catalog.domain.catalog import ItemStatus, due_status, publish_problems
from app.modules.service_catalog.infra.models import CatalogItem
from app.modules.service_catalog.service.catalog import (
    ItemRepository,
    facts_of,
    record_item_change,
    snapshot,
)
from app.shared.clock import Clock, SystemClock
from app.shared.history import Change

log = get_logger(__name__)
SCHEDULE_EVERY = 60  # seconds
BATCH = 200


async def apply_due(session: AsyncSession, clock: Clock) -> int:
    """Apply every due publish and retire in the session's tenant; how many items changed."""
    now = clock.now()
    rows = list(
        await session.scalars(
            select(CatalogItem)
            .where(
                CatalogItem.deleted_at.is_(None),
                or_(CatalogItem.publish_at <= now, CatalogItem.retire_at <= now),
            )
            .order_by(CatalogItem.id)
            .limit(BATCH)
            .with_for_update(skip_locked=True)
        )
    )
    changed = 0
    for row in rows:
        before = snapshot(row)
        current = ItemStatus(row.status)
        target = due_status(current, row.publish_at, row.retire_at, now)
        changes: dict[str, object] = {}
        if row.publish_at is not None and row.publish_at <= now:
            changes["publish_at"] = None
            if current is ItemStatus.DRAFT and publish_problems(facts_of(row)):
                target = current  # no longer complete: stays a draft (audited below)
                await record(
                    session,
                    action_code="catalog.item_scheduled",
                    facts=WORKER,
                    outcome=AuditOutcome.REFUSED,
                    reason_code="catalog_item_incomplete",
                    object_type="catalog_item",
                    object_id=row.id,
                )
        if row.retire_at is not None and row.retire_at <= now:
            changes["retire_at"] = None
        if target is not current:
            changes["status"] = target.value
            if target is ItemStatus.PUBLISHED or current is ItemStatus.DRAFT:
                changes["published_at"] = row.published_at or now
        updated = await ItemRepository(session).update(
            row.id, expected_version=row.version, changes=changes
        )
        after = snapshot(updated)
        await record_item_change(
            session,
            updated,
            [Change(k, before[k], after[k]) for k in after if before[k] != after[k]],
            kind="status" if "status" in changes else "updated",
            source="rule",
        )
        if "status" in changes:
            await record(
                session,
                action_code="catalog.item_scheduled",
                facts=WORKER,
                object_type="catalog_item",
                object_id=row.id,
                details={"status": target.value},
            )
        changed += 1
    return changed


async def run_schedule(database: Database, settings: Settings) -> None:
    """Every minute: due publishes and retires in every tenant."""
    del settings
    clock = SystemClock()
    async with database.platform_session() as platform:
        tenants = list((await platform.scalars(text("SELECT audit_tenant_ids()"))).all())
    for tenant in tenants:
        async with database.tenant_session(TenantContext(tenant)) as session:
            count = await apply_due(session, clock)
        if count:
            log.info("catalog_schedule_applied", tenant_id=str(tenant), items=count)


__all__ = ["SCHEDULE_EVERY", "apply_due", "run_schedule"]
