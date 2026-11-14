"""Which work item fields an admin may restrict per role (ADR-047 §1; identity_access's port).

Slice a offers each type's custom fields in use. Built-in fields (root cause, costs, change and
release figures) join in slice b, each with its enforcement, so no field is ever offered before
the server protects it. Core fields (subject, description, status, priority, requester, group,
assignee) are never offered: lists, search, notices and SLAs need them.
"""

from collections.abc import Awaitable, Callable, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules import metadata
from app.modules.identity_access import RuleableField, register_field_catalogue
from app.modules.work_items.domain.types import TYPES


def _provider(entity: str) -> Callable[[AsyncSession], Awaitable[Sequence[RuleableField]]]:
    async def fields(session: AsyncSession) -> Sequence[RuleableField]:
        return [
            RuleableField(
                key=f"custom.{f.key}",
                labels=f.labels,
                custom=True,
                personal_data=f.personal_data,
                sensitive=f.sensitive,
            )
            for f in await metadata.field_marks(session, entity)
        ]

    return fields


def register() -> None:
    """Every work item type's rule-able fields, at import (like the other ports)."""
    for code in TYPES:
        register_field_catalogue(str(code), _provider(str(code)))
