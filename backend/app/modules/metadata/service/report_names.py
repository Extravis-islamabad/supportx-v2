"""Names of custom field choices for report files (WP-035).

Registered with the reporting port when this module is imported. `field` is "custom.<key>";
retired choices read "<name> (retired)" as on screen (custom_fields.retired_value).
"""

from collections.abc import Mapping, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.metadata.service.custom_fields import definitions
from app.shared.labels import label
from app.shared.reporting import register_names


async def incident_choice_names(
    session: AsyncSession, values: Sequence[str], language: str, field: str
) -> Mapping[str, str]:
    """Choice labels of one incident custom field."""
    definition = (await definitions(session, "incident")).get(field.removeprefix("custom."))
    if definition is None:
        return {}
    wanted = set(values)
    out: dict[str, str] = {}
    for choice in definition.choices:
        if choice.code not in wanted:
            continue
        name = choice.labels.get(language) or choice.labels.get("en")
        if not name:
            continue
        out[choice.code] = (
            label("custom_fields.retired_value", language, name=name) if choice.retired else name
        )
    return out


def register() -> None:
    """Make these names available to report files (idempotent)."""
    register_names("incident.custom", incident_choice_names)
