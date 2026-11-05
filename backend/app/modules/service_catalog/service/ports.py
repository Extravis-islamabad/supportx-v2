"""What the catalog asks of modules that depend on it (WP-031 s1).

work_items imports the catalog (a request is raised from an item), so the catalog cannot import
work_items back. Instead work_items registers two answers here at import:
- how many requests an item has (an item with requests is retired, never deleted, plan D3);
- whether a template may be a catalog "report a problem" entry: an incident template, live,
  marked for requesters (REQ-CAT-003). The answer is the template's names per language, or None;
- how many requests each item had since a moment ("most requested", WP-032 D1, REQ-CAT-027).
Unregistered (a test without work_items), an item counts no requests and no template is valid.
"""

import uuid
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

ItemUsage = Callable[[AsyncSession, uuid.UUID], Awaitable[int]]
TemplateCheck = Callable[[AsyncSession, uuid.UUID], Awaitable[Mapping[str, str] | None]]

RequestCounts = Callable[[AsyncSession, datetime], Awaitable[Mapping[uuid.UUID, int]]]

_usage: list[ItemUsage] = []
_templates: list[TemplateCheck] = []
_counts: list[RequestCounts] = []


def register_request_counts(counts: RequestCounts) -> None:
    """Requests per item since a moment (registered by work_items)."""
    if counts not in _counts:
        _counts.append(counts)


async def request_counts(session: AsyncSession, since: datetime) -> dict[uuid.UUID, int]:
    """Requests per item since `since`, across the registered modules (empty without any)."""
    total: dict[uuid.UUID, int] = {}
    for counts in _counts:
        for item_id, n in (await counts(session, since)).items():
            total[item_id] = total.get(item_id, 0) + n
    return total


def register_item_usage(check: ItemUsage) -> None:
    """How many records use an item (registered once by each module that names items)."""
    if check not in _usage:
        _usage.append(check)


def register_template_check(check: TemplateCheck) -> None:
    """Whether a template may be a catalog entry, and its names (registered by work_items)."""
    if check not in _templates:
        _templates.append(check)


async def item_usage(session: AsyncSession, item_id: uuid.UUID) -> int:
    """Records that name the item, across the registered modules."""
    total = 0
    for check in _usage:
        total += await check(session, item_id)
    return total


async def entry_template(session: AsyncSession, template_id: uuid.UUID) -> Mapping[str, str] | None:
    """The template's names if it may be a catalog entry; None otherwise."""
    for check in _templates:
        if (names := await check(session, template_id)) is not None:
            return names
    return None


__all__ = [
    "entry_template",
    "item_usage",
    "register_item_usage",
    "register_request_counts",
    "register_template_check",
    "request_counts",
]
