"""Which CI fields an admin may restrict per role (ADR-047 §1; identity_access's port).

Only the CI custom fields (0175 part 2): one entry per key for the whole `ci` entity, so a rule on
a field scoped to a parent type applies on every subtype (lane A's constraint 3). Every read path
withholds them: the CI record, its history and its versions; lists, the picker, the map and its
exports carry no custom values. Built-in CI fields (name, type, state, site, owners) are never
offered: lists, the map and impact analysis need them.
"""

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules import metadata
from app.modules.cmdb.service.cis import RECORD_TYPE
from app.modules.identity_access import RuleableField, register_field_catalogue


async def _fields(session: AsyncSession) -> Sequence[RuleableField]:
    return [
        RuleableField(
            key=f"custom.{f.key}",
            labels=f.labels,
            custom=True,
            personal_data=f.personal_data,
            sensitive=f.sensitive,
        )
        for f in await metadata.field_marks(session, metadata.CustomFieldEntity.CI)
    ]


def register() -> None:
    """The CI's rule-able fields, at import (like the other ports)."""
    register_field_catalogue(RECORD_TYPE, _fields)
