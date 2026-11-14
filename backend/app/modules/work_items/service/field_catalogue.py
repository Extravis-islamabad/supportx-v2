"""Which work item fields an admin may restrict per role (ADR-047 §1; identity_access's port).

Each type's built-in fields (domain/field_access.BUILTIN: impact details, and the problem's
analysis and review texts) and its custom fields in use. A field is offered only once every read
path withholds it (slice b1), so no rule ever does nothing. Core fields (subject, description,
status, priority, requester, group, assignee) are never offered: lists, search, notices and SLAs
need them.
"""

from collections.abc import Awaitable, Callable, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules import metadata
from app.modules.identity_access import RuleableField, register_field_catalogue
from app.modules.work_items.domain.field_access import BUILTIN
from app.modules.work_items.domain.types import TYPES


def _provider(entity: str) -> Callable[[AsyncSession], Awaitable[Sequence[RuleableField]]]:
    async def fields(session: AsyncSession) -> Sequence[RuleableField]:
        builtin = [
            RuleableField(key=key, label_key=label)
            for key, label in BUILTIN.get(entity, {}).items()
        ]
        return builtin + [
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
