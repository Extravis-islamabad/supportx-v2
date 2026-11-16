"""The service catalog's slice of a person's erasure (ADR-052 §4; D-171; lane B's readiness check).

Catalog items name people in their set-up: the item's owner, its default technician, its
approvers and backup approver, and the owners its plan gives new tasks. None of it is the person's
own data; it is the organisation's configuration, so it must keep working once they are gone:

- the owner, named approvers and the backup approver pass to the successor (D4), so an item's
  requests still find someone to ask and someone answerable;
- the default technician and a planned task's owner are cleared: the item's group (and the
  task's group) takes them, as when nobody is named.

Band 500-599 (lane B: owned objects, with the other configuration handed to the successor).
Each call does one bounded batch (at most `ERASE_BATCH` items) and says
where to go on; a second full run finds nothing and counts zero. Each changed item gets its field
history (source system, reason `erased_on_request`) and the usual change event, so screens and
search follow. Counts by kind only, never data.
"""

import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import Text, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access import ERASE_BATCH, ErasureBatch, register_person_data
from app.modules.service_catalog.events import CatalogItemChanged
from app.modules.service_catalog.infra.models import CatalogItem
from app.modules.service_catalog.service.catalog import ITEM_RECORD_TYPE
from app.shared.erasure import ERASED_ON_REQUEST
from app.shared.events import record_event
from app.shared.history import Change, record_changes


def _approval(
    approval: Mapping[str, Any] | None, person: str, successor: str
) -> tuple[dict[str, Any] | None, int]:
    """The approval with the person's places taken by the successor, and how many there were."""
    if not approval:
        return (dict(approval) if approval is not None else None), 0
    replaced = 0
    approvers = []
    for approver in approval.get("approvers") or []:
        if isinstance(approver, Mapping) and str(approver.get("person_id")) == person:
            approvers.append({**approver, "person_id": successor})
            replaced += 1
        else:
            approvers.append(approver)
    out = {**approval, "approvers": approvers}
    if str(approval.get("backup_id")) == person:
        out["backup_id"] = successor
        replaced += 1
    return out, replaced


def _plan(plan: list[Any], person: str) -> tuple[list[Any], int]:
    """The plan with the person no longer a task's owner (its group takes it)."""
    cleared = 0
    tasks = []
    for task in plan:
        if isinstance(task, Mapping) and str(task.get("owner_id")) == person:
            tasks.append({**task, "owner_id": None})
            cleared += 1
        else:
            tasks.append(task)
    return tasks, cleared


async def _batch(
    session: AsyncSession,
    person_id: uuid.UUID,
    successor_id: uuid.UUID,
    after: uuid.UUID | None,
) -> tuple[dict[str, int], uuid.UUID | None]:
    """One batch of the items that name the person anywhere in their set-up."""
    person, successor = str(person_id), str(successor_id)
    query = (
        select(CatalogItem)
        .where(
            or_(
                CatalogItem.owner_id == person_id,
                CatalogItem.technician_id == person_id,
                cast(CatalogItem.approval, Text).contains(person),
                cast(CatalogItem.plan, Text).contains(person),
            )
        )
        .order_by(CatalogItem.id)
        .limit(ERASE_BATCH)
        .with_for_update()
    )
    if after is not None:
        query = query.where(CatalogItem.id > after)
    items = list((await session.scalars(query)).all())
    counts = {"owners_handed_over": 0, "technicians_cleared": 0, "approvers_handed_over": 0,
              "task_owners_cleared": 0}  # fmt: skip
    for item in items:
        changes: list[Change] = []
        if item.owner_id == person_id:
            item.owner_id = successor_id
            changes.append(Change("owner_id", person, successor))
            counts["owners_handed_over"] += 1
        if item.technician_id == person_id:
            item.technician_id = None  # the item's group takes its requests
            changes.append(Change("technician_id", person, None))
            counts["technicians_cleared"] += 1
        approval, replaced = _approval(item.approval, person, successor)
        if replaced:
            item.approval = approval
            changes.append(Change("approval", None, None))  # its shape is the item's own
            counts["approvers_handed_over"] += replaced
        plan, cleared = _plan(list(item.plan or []), person)
        if cleared:
            item.plan = plan
            changes.append(Change("plan", None, None))
            counts["task_owners_cleared"] += cleared
        if not changes:
            continue  # the ID was only a substring of something else
        item.version += 1
        await session.flush()
        await record_changes(
            session,
            record_type=ITEM_RECORD_TYPE,
            record_id=item.id,
            version=item.version,
            kind="updated",
            changes=changes,
            source="system",
            reason=ERASED_ON_REQUEST,
        )
        await record_event(
            session,
            CatalogItemChanged(item_id=item.id, changed_fields=[c.field for c in changes]),
            aggregate_id=item.id,
            aggregate_version=item.version,
        )
    last = items[-1].id if len(items) == ERASE_BATCH else None
    return {k: v for k, v in counts.items() if v}, last


class ServiceCatalog:
    """`service_catalog`: the items' set-up no longer names them (band 500-599)."""

    module: ClassVar[str] = "service_catalog"
    order: ClassVar[int] = 520
    kinds: ClassVar[frozenset[str]] = frozenset(
        {"owners_handed_over", "technicians_cleared", "approvers_handed_over",
         "task_owners_cleared"}
    )  # fmt: skip

    async def erase_person(  # noqa: PLR0913 - the port contract
        self,
        session: AsyncSession,
        person_id: uuid.UUID,
        *,
        successor_id: uuid.UUID,
        keep_files: Mapping[uuid.UUID, str],
        now: datetime,
        cursor: str | None,
    ) -> ErasureBatch:
        """One batch of items, and where to go on."""
        del keep_files, now  # no files or times of their own here
        after = uuid.UUID(cursor) if cursor else None
        counts, last = await _batch(session, person_id, successor_id, after)
        return ErasureBatch(counts, str(last) if last is not None else None)


PORT = ServiceCatalog()


def register() -> None:
    """Register the port (service_catalog's import does; idempotent)."""
    register_person_data(PORT)
