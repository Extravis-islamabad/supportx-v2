"""Charge-back on fulfilled service requests (WP-047b S1; REQ-CAT-021).

When a request is fulfilled (its status moves into the resolved category, the first time), what
it charges is frozen on the record: the department (the requested-for person's, at that
moment) or a cost centre (the form answer the item names; V1 has no cost-centre list, the
coordinator 2026-11-25), and the amount. Later moves of the person change nothing (AC1).

The amount's basis is in ONE place (`charge_basis`): the frozen estimate, until the product
owner decides (the coordinator asked Haider; a tenant setting may switch it later). The export
shows the actual cost beside it.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules import service_catalog
from app.modules.identity_access import person_placement
from app.modules.work_items.domain.lifecycle import StatusCategory
from app.modules.work_items.domain.types import SERVICE_REQUEST
from app.modules.work_items.infra.models import WorkItem

COST_CENTRE_MAX = 100  # the column's length


def charge_basis(record: WorkItem) -> Decimal | None:
    """What a fulfilled request charges: today the estimate it was raised with (one place)."""
    return record.estimated_cost


def _cost_centre(answer: Any) -> str | None:  # noqa: ANN401 - a stored form answer
    text = str(answer).strip() if answer not in (None, "", []) else ""
    return text[:COST_CENTRE_MAX] or None


async def freeze_on_fulfilment(session: AsyncSession, record: WorkItem) -> None:
    """Freeze the charge once, when a request first becomes fulfilled (REQ-CAT-021 AC1).

    Once only: a request reopened and fulfilled again keeps its first charge.
    """
    if (
        record.type != SERVICE_REQUEST.code.value
        or record.status_category != StatusCategory.RESOLVED.value
        or record.charged_at is not None
        or record.catalog_item_id is None
    ):
        return
    item = await service_catalog.item_decides(session, record.catalog_item_id)
    if item is None:
        return
    if item.charge_to == service_catalog.ChargeTo.QUESTION.value:
        record.charge_cost_centre = _cost_centre(
            (record.answers or {}).get(item.charge_question_key or "")
        )
    else:
        person = record.on_behalf_of_id or record.requester_id
        if person is not None:
            record.charge_department_id = (await person_placement(session, person)).department_id
    record.charged_amount = charge_basis(record)
    record.charged_at = datetime.now(UTC)
    await session.flush()


__all__ = ["charge_basis", "freeze_on_fulfilment"]
