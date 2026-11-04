"""Seeding the starter catalog (WP-031, D-138; REQ-CAT-007).

- A new tenant: the consumer of `organization.tenant.provisioned` seeds once. The per-tenant
  marker (`catalog_settings.starter_seeded_at`) makes it idempotent: a redelivered or repeated
  event, or a tenant that later deletes everything, gets nothing. Migration 0074 marked every
  tenant that existed before, so they are never seeded by themselves.
- An existing dev, QA or demo tenant: `make catalog-starter TENANT=<slug>` (tooling) seeds only
  an empty catalog (no categories or items at all, deleted ones included), then sets the marker.
- Everything is a draft (plan D9: an item is published only with a fulfilment group). The admin
  chooses a group and publishes them in one action (`publish_starter`), which publishes only the
  items whose checks pass and is audited.
"""

import uuid
from dataclasses import dataclass, replace

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.audit import WORKER, record
from app.modules.identity_access import Subject
from app.modules.organization import existing_unit_ids
from app.modules.service_catalog.domain.catalog import ItemStatus, publish_problems
from app.modules.service_catalog.domain.starter import CATEGORIES, ITEMS
from app.modules.service_catalog.events import StarterCatalogSeeded
from app.modules.service_catalog.infra.models import CatalogItem, ServiceCategory
from app.modules.service_catalog.service import catalog, categories, settings
from app.modules.service_catalog.service.common import invalid, require_manage
from app.shared.clock import Clock, SystemClock
from app.shared.events import EventEnvelope, record_event
from app.shared.history import Change, Source, record_changes

log = get_logger(__name__)


@dataclass(frozen=True)
class Seeded:
    """What a seed added (zero when it found nothing to do)."""

    categories: int = 0
    items: int = 0


async def _has_catalog(session: AsyncSession) -> bool:
    """Any category or item at all, deleted ones included (the explicit run seeds none then)."""
    items = await session.scalar(select(func.count()).select_from(CatalogItem))
    categories = await session.scalar(select(func.count()).select_from(ServiceCategory))
    return bool(items or categories)


async def _add(session: AsyncSession, clock: Clock) -> Seeded:
    """Add the starter categories and items (drafts), with history and one event."""
    by_key: dict[str, uuid.UUID] = {}
    for order, spec in enumerate(CATEGORIES):
        category = ServiceCategory(
            names=dict(spec.names), descriptions={}, sort_order=order * 10, icon=spec.icon
        )
        await categories.CategoryRepository(session).add(category)
        by_key[spec.key] = category.id
        await record_changes(
            session,
            record_type="service_category",
            record_id=category.id,
            version=category.version,
            kind="created",
            changes=[Change("names", None, dict(spec.names)), Change("starter", None, new=True)],
            source="system",
        )
    for order, item in enumerate(ITEMS):
        values = item.as_values()
        stored = catalog.stored(values)
        row = CatalogItem(
            **{
                "descriptions": {},
                "summaries": {},
                "keywords": {},
                "questions": [],
                "plan": [],
                **stored,
                "category_id": by_key[item.category],
                "extra_category_ids": [by_key[k] for k in item.also_in],
                "sort_order": order * 10,
                "status": ItemStatus.DRAFT.value,
                "kind": "service",
                "starter": True,
            }
        )
        await catalog.ItemRepository(session).add(row)
        after = catalog.snapshot(row)
        await record_changes(
            session,
            record_type=catalog.ITEM_RECORD_TYPE,
            record_id=row.id,
            version=row.version,
            kind="created",
            changes=[Change(k, None, v) for k, v in after.items() if v not in (None, [], {})],
            source="system",
        )
    marker = await settings.load_for_update(session)
    marker.starter_seeded_at = clock.now()
    marker.version += 1
    await session.flush()
    seeded = Seeded(categories=len(CATEGORIES), items=len(ITEMS))
    await record_event(
        session,
        StarterCatalogSeeded(categories=seeded.categories, items=seeded.items),
        aggregate_id=marker.tenant_id,
        aggregate_version=marker.version,
    )
    await record(
        session,
        action_code="catalog.starter_seeded",
        facts=WORKER,
        details={"categories": seeded.categories, "items": seeded.items},
    )
    return seeded


async def seed_new_tenant(session: AsyncSession, clock: Clock | None = None) -> Seeded:
    """Seed once per tenant: nothing if the marker is set (D-138)."""
    marker = await settings.load_for_update(session)
    if marker.starter_seeded_at is not None:
        return Seeded()
    return await _add(session, clock or SystemClock())


async def seed_empty_catalog(session: AsyncSession, clock: Clock | None = None) -> Seeded:
    """The explicit run (tooling): only into a catalog that has never had anything."""
    await settings.load_for_update(session)  # one run at a time per tenant
    if await _has_catalog(session):
        return Seeded()
    return await _add(session, clock or SystemClock())


async def on_tenant_provisioned(envelope: EventEnvelope, session: AsyncSession | None) -> None:
    """Consumer: a new tenant gets the starter catalog (once)."""
    assert session is not None  # noqa: S101 - transactional consumer
    seeded = await seed_new_tenant(session)
    if seeded.items:
        log.info("catalog_starter_seeded", tenant_id=str(envelope.tenant_id), items=seeded.items)


@dataclass(frozen=True)
class Published:
    """The outcome of "choose a group and publish": counts, and what still needs work."""

    published: int
    skipped: list[uuid.UUID]


async def starter_drafts(session: AsyncSession) -> int:
    """How many starter items are still drafts (the console's banner)."""
    count = await session.scalar(
        select(func.count())
        .select_from(CatalogItem)
        .where(
            CatalogItem.starter.is_(True),
            CatalogItem.status == ItemStatus.DRAFT.value,
            CatalogItem.deleted_at.is_(None),
        )
    )
    return count or 0


async def publish_starter(
    session: AsyncSession,
    subject: Subject,
    group_id: uuid.UUID,
    *,
    source: Source,
    clock: Clock | None = None,
) -> Published:
    """Give the starter drafts a fulfilment group and publish those whose checks pass.

    The route audits it (`catalog.starter_published`, with the counts).
    """
    require_manage(subject)
    clock = clock or SystemClock()
    if group_id not in await existing_unit_ids(session, "group", [group_id]):
        raise invalid([("group_id", "not_found")])
    rows = list(
        await session.scalars(
            select(CatalogItem)
            .where(
                CatalogItem.starter.is_(True),
                CatalogItem.status == ItemStatus.DRAFT.value,
                CatalogItem.deleted_at.is_(None),
            )
            .order_by(CatalogItem.sort_order, CatalogItem.id)
            .with_for_update()
        )
    )
    published: int = 0
    skipped: list[uuid.UUID] = []
    for row in rows:
        before = catalog.snapshot(row)
        changes: dict[str, object] = {}
        if row.group_id is None:
            changes["group_id"] = group_id
        ready = not publish_problems(
            replace(catalog.facts_of(row), group_id=row.group_id or group_id)
        )
        if ready:
            changes |= {
                "status": ItemStatus.PUBLISHED.value,
                "published_at": clock.now(),
                "publish_at": None,
            }
        else:
            skipped.append(row.id)
        if not changes:
            continue
        updated = await catalog.ItemRepository(session).update(
            row.id, expected_version=row.version, changes=changes
        )
        after = catalog.snapshot(updated)
        await catalog.record_item_change(
            session,
            updated,
            [Change(k, before[k], after[k]) for k in after if before[k] != after[k]],
            kind="status" if ready else "updated",
            source=source,
        )
        published += int(ready)
    return Published(published=published, skipped=skipped)


__all__ = [
    "Published",
    "Seeded",
    "on_tenant_provisioned",
    "publish_starter",
    "seed_empty_catalog",
    "seed_new_tenant",
    "starter_drafts",
]
