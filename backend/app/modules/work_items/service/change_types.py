"""A new change's type, model and path (WP-045a D2; REQ-CHG-005, -006, -011).

The change type comes from the create request or the template's defaults (a template binds the
type, file 05 §3). Its model decides the path when the template names none, and a standard
change is approved at creation: the system's move to `submission_accepted`, which completes
submission, with a history line saying so (never an unexplained tick, REQ-CHG-006 AC1).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.work_items.domain import changes as rules
from app.modules.work_items.domain.templates import PickList
from app.modules.work_items.domain.types import WorkItemType, WorkItemTypeCode
from app.modules.work_items.infra.models import WorkItem, WorkItemChangeDetails, WorkItemTemplate
from app.modules.work_items.service.catalogue import Catalogue

# The create request's fields that only changes take.
CREATE_FIELDS = rules.DETAIL_FIELDS


@dataclass(frozen=True)
class NewChange:
    """What a new change starts with: its own fields, its model and its path."""

    details: Mapping[str, str]
    model: rules.ChangeModel | None
    path: str | None


def problems_for(wtype: WorkItemType, values: Mapping[str, Any]) -> list[tuple[str, str]]:
    """A change's fields sent for another type are refused, not dropped."""
    if wtype.code is WorkItemTypeCode.CHANGE:
        return []
    return [(n, "not_allowed") for n in CREATE_FIELDS if values.get(n) is not None]


def prepare(
    wtype: WorkItemType,
    cat: Catalogue,
    values: Mapping[str, Any],
    template: WorkItemTemplate,
) -> tuple[NewChange | None, list[tuple[str, str]]]:
    """The new change's type, reason, model and path; (None, []) for other types."""
    if wtype.code is not WorkItemTypeCode.CHANGE:
        return None, []
    defaults = template.defaults or {}
    chosen = {
        n: values.get(n) if values.get(n) is not None else defaults.get(n) for n in CREATE_FIELDS
    }
    problems: list[tuple[str, str]] = []
    for name, pick in (
        ("change_type", PickList.CHANGE_TYPE),
        ("change_reason", PickList.CHANGE_REASON),
    ):
        value = chosen[name]
        if value is not None and value not in cat.reason_codes(pick):
            problems.append((name, "invalid_choice"))
    change_type = chosen["change_type"]
    if problems or change_type is None:
        details = {n: v for n, v in chosen.items() if v is not None}
        return NewChange(details, None, None), problems
    attributes = next(
        (v.attributes for v in cat.list_values(PickList.CHANGE_TYPE) if v.code == change_type),
        None,
    )
    model = rules.model_of(change_type, attributes)
    # A template binds a type and its path (file 05 §3, REQ-CHG-022); a type chosen on the form
    # that differs from the template's takes its own path, so any template serves every type.
    bound = defaults.get("change_type") == change_type and template.stage_path is not None
    path = template.stage_path if bound else rules.path_of(change_type, model)
    return NewChange({n: v for n, v in chosen.items() if v is not None}, model, path), []


def pre_approved(new: NewChange | None) -> bool:
    """Whether the new change is approved at creation (a standard model, REQ-CHG-006)."""
    return new is not None and new.model is rules.ChangeModel.STANDARD


async def store(session: AsyncSession, record: WorkItem, new: NewChange | None) -> dict[str, Any]:
    """Keep a new change's own fields (0101); what was kept, for the creation's history."""
    own: dict[str, Any] = dict(new.details) if new is not None else {}
    if own:
        session.add(
            WorkItemChangeDetails(tenant_id=record.tenant_id, work_item_id=record.id, **own)
        )
        await session.flush()
    return own
