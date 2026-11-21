"""Which source wins for each CI attribute: the tenant's order (REQ-CMDB-016; WP-053 S4a).

Kept on the CMDB settings row (`source_precedence`, If-Match on the settings' version). Changing
it needs `cmdb.configure`; the route audits who changed it, with the order before and after (the
coordinator's condition 2). The service never decides by deployment or edition.
"""

from collections.abc import Mapping, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules import metadata
from app.modules.cmdb.domain import field_access as field_rules
from app.modules.cmdb.domain import sources as domain
from app.modules.cmdb.domain.sources import AttributeSource, Precedence
from app.modules.cmdb.service.catalogue import (
    config_event,
    get_settings,
    invalid,
    require_configure,
)
from app.modules.cmdb.service.cis import EDITABLE, ENTITY
from app.modules.identity_access import Subject
from app.shared.history import stale_version


async def attributes(session: AsyncSession) -> list[str]:
    """The attributes an order of their own may be set for: the CI's fields and custom fields."""
    keys = [f.key for f in await metadata.field_marks(session, ENTITY, retired=True)]
    return [*EDITABLE, *(f"{field_rules.CUSTOM}{k}" for k in sorted(keys))]


async def precedence(session: AsyncSession) -> tuple[Precedence, int]:
    """The tenant's precedence and the settings' version (its ETag)."""
    row = await get_settings(session)
    return domain.precedence_of(row.source_precedence), row.version


async def change_precedence(
    session: AsyncSession,
    subject: Subject,
    *,
    expected_version: int,
    order: Sequence[AttributeSource],
    overrides: Mapping[str, Sequence[AttributeSource]],
) -> tuple[Precedence, Precedence, int]:
    """Set the order (If-Match on the settings). Returns the order before, after and the version."""
    require_configure(subject)
    row = await get_settings(session)
    if row.version != expected_version:
        raise await stale_version(session, row, expected_version=expected_version)
    if problems := domain.precedence_problems(order, overrides, await attributes(session)):
        raise invalid(problems)
    before = domain.precedence_of(row.source_precedence)
    after = Precedence(tuple(order), {k: tuple(v) for k, v in overrides.items()})
    if domain.precedence_json(after) != domain.precedence_json(before):
        row.source_precedence = domain.precedence_json(after)
        row.version += 1
        row.updated_by = subject.user_id
        await session.flush()
        await config_event(session, "source_precedence", "updated", None, row.version)
    return before, after, row.version
